"""main.py — 多声卡窗口管理（PyAudioRouter）主程序

按应用分配音频输出/输入设备。Win10 1803+ 使用系统原生
「应用音量和设备首选项」接口（AudioPolicyConfig），不需要注入进程。
"""
from __future__ import annotations

import math
import os
import sys
import threading
import time
import traceback

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLayout, QMenu, QPushButton, QScrollArea,
                               QSizeGrip, QSystemTrayIcon, QVBoxLayout, QWidget)

import audio_core as ac
import theme
from store import Store
from ui_widgets import DeviceCard, EmptyHint, ListGroupHeader, SessionRow, TitleBar


APP_TITLE = "多声卡窗口管理"
HERE = os.path.dirname(os.path.abspath(__file__))

# 多久核对一次系统默认设备（毫秒）。只改这一行。
jian_ge_haomiao = 3000

# 电平：条长和数值都用线性百分比（0~100%），跟常见的混音器读数一致
def _db_level(peak: float) -> float:
    """峰值 -> 电平条位置（线性 0~1），数值按这个换算成百分比。"""
    return max(0.0, min(1.0, float(peak)))


class MainWindow(QWidget):
    _default_ready = Signal(str)
    _need_refresh = Signal()
    def __init__(self):
        super().__init__()
        self.core = ac.AudioCore()
        self.core.initialize()
        self.store = Store()
        self.dark = self.store.settings.get("theme") == "dark"
        self.flow = ac.eRender
        self.rows: dict[str, SessionRow] = {}
        self.devices: list[ac.Device] = []
        self._dev_sig: tuple | None = None
        self.show_fav_only = False
        self.view_mode = 0        # 0 全部 / 1 收藏 / 2 已移除 / 3 记忆
        self._list_mode = 0       # 当前列表页实际渲染的模式（0 = 会话列表）
        self._hidden_sig: tuple | None = None
        self._mem_sig: tuple | None = None
        self._fav_sig: tuple | None = None
        self._live_cache: dict[str, ac.Session] = {}
        # 各页签「运行中 / 未运行」分组是否展开
        self._group_open: dict[tuple[str, str], bool] = {
            (pg, g): True for pg in ("fav", "hid", "mem") for g in ("run", "idle")}
        self.selected_device: str | None = None
        self._route_ts: dict[int, float] = {}
        self._first_seen: dict[int, float] = {}
        self._refresh_tick = 0
        self._applied: set[str] = set()
        self._sys_default_id = ""      # 当前确认过的系统默认设备 id（只由子进程/系统通知写入）
        self._sel: set[str] = set()    # 选中的应用行 key
        self._sel_anchor: str | None = None

        self.setWindowTitle(APP_TITLE)
        self.setWindowIcon(theme.app_icon(64))
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window
                            | Qt.WindowMinimizeButtonHint | Qt.WindowSystemMenuHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(940, 660)
        self.setMinimumSize(760, 520)

        self._build_ui()
        self.apply_theme()
        self._restore_geometry()
        self.refresh(full=True)

        self.timer = QTimer(self)
        self.timer.timeout.connect(lambda: self.refresh(full=False))
        self.timer.start(1500)

        # 系统默认设备：只认「子进程读到的值」。
        # 本进程内的 GetDefaultAudioEndpoint 被 MMDevAPI 按进程缓存，外部改默认设备
        # 之后会一直返回旧值，徽章就钉死在旧声卡上；所以定时用子进程核对。
        self._probe_busy = False
        self._default_ready.connect(self._apply_probed_default)
        self._need_refresh.connect(self._on_need_refresh)
        self.core.watch_devices(self._on_device_event)
        self.dev_timer = QTimer(self)
        self.dev_timer.timeout.connect(self._probe_default)
        self.dev_timer.start(jian_ge_haomiao)
        QTimer.singleShot(300, self._probe_default)

        # 电平条刷新（80ms，只读 GetPeakValue，开销很小）
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(80)

        self._build_tray()

        # Ctrl+A 全选当前页（全部/收藏/已移除/记忆 都生效）
        self.sc_select_all = QShortcut(QKeySequence.SelectAll, self)
        self.sc_select_all.setContext(Qt.WindowShortcut)
        self.sc_select_all.activated.connect(self._select_all)
        self.sc_delete = QShortcut(QKeySequence.Delete, self)
        self.sc_delete.setContext(Qt.WindowShortcut)
        self.sc_delete.activated.connect(self._on_delete_key)

    # ------------------------------------------------------------------ UI
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setObjectName("Shell")
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(36)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(16, 24, 40, 60))
        self.shell.setGraphicsEffect(shadow)
        root.addWidget(self.shell)

        shell_lay = QVBoxLayout(self.shell)
        shell_lay.setContentsMargins(0, 0, 0, 0)
        shell_lay.setSpacing(0)

        self.title_bar = TitleBar()
        self.title_bar.minimize_clicked.connect(self.showMinimized)
        self.title_bar.close_clicked.connect(self._on_close)
        self.title_bar.theme_toggled.connect(self.toggle_theme)
        shell_lay.addWidget(self.title_bar)

        body = QWidget()
        body.setObjectName("Body")
        shell_lay.addWidget(body, 1)

        lay = QVBoxLayout(body)
        lay.setContentsMargins(18, 6, 18, 8)
        lay.setSpacing(10)

        # ---- 顶部：输出设备 + 刷新
        top = QHBoxLayout()
        top.setSpacing(8)
        dev_title = QLabel("声卡")
        dev_title.setObjectName("SectionTitle")
        top.addWidget(dev_title)
        top.addStretch(1)
        self.btn_refresh = QPushButton("↻  刷新")
        self.btn_refresh.setObjectName("GhostBtn")
        self.btn_refresh.setCursor(Qt.PointingHandCursor)
        self.btn_refresh.clicked.connect(self._force_refresh)
        top.addWidget(self.btn_refresh)
        lay.addLayout(top)

        # ---- 设备区
        self.device_scroll = QScrollArea()
        self.device_scroll.setWidgetResizable(False)
        self.device_scroll.setFixedHeight(122)
        self.device_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.device_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.device_host = QWidget()
        self.device_host.setObjectName("Body")
        self.device_layout = QHBoxLayout(self.device_host)
        self.device_layout.setContentsMargins(0, 2, 0, 6)
        self.device_layout.setSpacing(10)
        self.device_layout.addStretch(1)
        self.device_scroll.setWidget(self.device_host)
        lay.addWidget(self.device_scroll)

        # ---- 会话标题 + 收藏筛选
        head = QHBoxLayout()
        head.setSpacing(8)
        self.section_label = QLabel("正在播放的应用")
        self.section_label.setObjectName("SectionTitle")
        head.addWidget(self.section_label)
        self.count_label = QLabel("")
        self.count_label.setObjectName("StatusText")
        head.addWidget(self.count_label)

        head.addSpacing(14)
        self.filter_group = QButtonGroup(self)
        self.btn_all = QPushButton("全部")
        self.btn_fav = QPushButton("收藏")
        self.btn_hidden = QPushButton("已移除")
        self.btn_mem = QPushButton("记忆")
        for b in (self.btn_all, self.btn_fav, self.btn_hidden, self.btn_mem):
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_all.setChecked(True)
        self.filter_group.addButton(self.btn_all, 0)
        self.filter_group.addButton(self.btn_fav, 1)
        self.filter_group.addButton(self.btn_hidden, 2)
        self.filter_group.addButton(self.btn_mem, 3)
        self.filter_group.idClicked.connect(self._on_filter_changed)
        head.addWidget(self.btn_all)
        head.addWidget(self.btn_fav)
        head.addWidget(self.btn_hidden)
        head.addWidget(self.btn_mem)

        head.addStretch(1)
        self.btn_clear = QPushButton("全部恢复默认")
        self.btn_clear.setObjectName("GhostBtn")
        self.btn_clear.setCursor(Qt.PointingHandCursor)
        self.btn_clear.clicked.connect(self.reset_all)
        head.addWidget(self.btn_clear)
        lay.addLayout(head)

        # ---- 会话列表
        self.session_scroll = QScrollArea()
        self.session_scroll.setWidgetResizable(True)
        self.session_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.session_host = QWidget()
        self.session_host.setObjectName("Body")
        self.session_layout = QVBoxLayout(self.session_host)
        self.session_layout.setContentsMargins(0, 0, 4, 0)
        self.session_layout.setSpacing(8)
        self.session_layout.addStretch(1)
        self.session_scroll.setWidget(self.session_host)
        self.session_host.installEventFilter(self)
        lay.addWidget(self.session_scroll, 1)

        # ---- 状态栏
        status = QHBoxLayout()
        status.setContentsMargins(2, 0, 2, 0)
        self.status_label = QLabel("")
        self.status_label.setObjectName("StatusText")
        status.addWidget(self.status_label, 1)
        lay.addLayout(status)

        # 右下角拖拽改变大小
        self.grip = QSizeGrip(self.shell)
        self.grip.setFixedSize(16, 16)
        self.grip.setStyleSheet("background: transparent;")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.grip.move(self.shell.width() - 20, self.shell.height() - 20)
        if hasattr(self, "device_host"):
            self._fit_device_host()

    # --------------------------------------------------------------- theme
    def apply_theme(self):
        QApplication.instance().setStyleSheet(theme.build_qss(self.dark))
        self.title_bar.btn_theme.setText("◑" if self.dark else "◐")

    def toggle_theme(self):
        self.dark = not self.dark
        self.store.set_setting("theme", "dark" if self.dark else "light")
        self.apply_theme()
        self._rebuild_devices()
        for row in self.rows.values():
            row.update_volume(row.session.volume, row.session.muted)
            row.set_dark(self.dark)

    # ---------------------------------------------------------------- tray
    def _build_tray(self):
        self.tray = QSystemTrayIcon(theme.tray_icon(64), self)
        self.tray.setToolTip(APP_TITLE)
        menu = QMenu()
        act_show = menu.addAction("显示主窗口")
        act_show.triggered.connect(self._show_window)
        menu.addSeparator()
        self.act_auto = QAction("自动套用记忆规则", menu, checkable=True)
        self.act_auto.setChecked(bool(self.store.settings.get("auto_apply", True)))
        self.act_auto.toggled.connect(self._on_auto_toggle)
        menu.addAction(self.act_auto)
        act_reset = menu.addAction("全部恢复默认")
        act_reset.triggered.connect(self.reset_all)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.Trigger:
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self._show_window()

    def _show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_auto_toggle(self, checked: bool):
        self.store.set_setting("auto_apply", bool(checked))
        if checked:
            self._applied.clear()
            self.refresh(full=True)
        self._update_status()

    def _on_close(self):
        self._quit()

    def _restore_geometry(self):
        """恢复上次的窗口大小和位置；落在屏幕外就回到屏幕中央。"""
        g = self.store.settings.get("win") or []
        if not isinstance(g, list) or len(g) != 4:
            return
        try:
            x, y, w, h = (int(v) for v in g)
        except Exception:
            return
        self.resize(max(self.minimumWidth(), w), max(self.minimumHeight(), h))
        rect = QRect(x, y, w, h)
        for screen in QGuiApplication.screens():
            if screen.availableGeometry().intersects(rect):
                self.move(x, y)
                return
        scr = QGuiApplication.primaryScreen().availableGeometry()
        self.move(scr.center() - self.rect().center())

    def _save_geometry(self):
        try:
            r = self.geometry()
            self.store.settings["win"] = [r.x(), r.y(), r.width(), r.height()]
        except Exception:
            pass

    def _quit(self):
        self.timer.stop()
        self.dev_timer.stop()
        self._save_geometry()
        try:
            self.store.save()
        except Exception:
            pass
        self.tray.hide()
        self.core.close()
        QApplication.instance().quit()

    # ------------------------------------------------------------- refresh
    def refresh(self, full: bool = False):
        try:
            self.devices = (self.core.output_devices() if self.flow == ac.eRender
                            else self.core.input_devices())
        except Exception:
            self.devices = []

        # 默认徽章只认子进程读到的值（本进程读到的可能是缓存的旧值）
        if self._sys_default_id:
            for d in self.devices:
                d.is_default = (d.id == self._sys_default_id)

        # 设备有变化（默认设备切换、插拔）就重建卡片，外部改默认也能反映出来
        sig = tuple((d.id, d.is_default) for d in self.devices)
        if not self.device_layout.count() or sig != self._dev_sig:
            self._dev_sig = sig
            self._rebuild_devices()

        # 「收藏」/「已移除」/「记忆」页：不列会话
        if self.view_mode in (1, 2, 3):
            self._update_section_label()
            if self.view_mode == 1:
                self._show_fav_rows()
            elif self.view_mode == 2:
                self._show_hidden_rows()
            else:
                self._show_memory_rows()
            self._update_device_counts()
            self._update_status()
            return
        if self._list_mode != 0:
            self._clear_sessions()
            self._list_mode = 0
            self._hidden_sig = None
            self._mem_sig = None
            self._fav_sig = None

        try:
            sessions = self.core.sessions(self.flow)
        except Exception:
            sessions = []
        if not self.store.settings.get("show_system_sounds", False):
            sessions = [s for s in sessions if not s.is_system]
        # 已移除的应用不再出现在列表里
        sessions = [s for s in sessions
                    if not self.store.is_hidden(s.process_name, s.exe_path)]
        if self.show_fav_only:
            sessions = [s for s in sessions
                        if self.store.is_fav(s.process_name, s.exe_path)]
        if self.selected_device:
            sessions = [s for s in sessions if s.device_id == self.selected_device]

        # 新出现的应用排最上面，已有的按出现时间倒序（顺序稳定，不会来回跳）
        now = time.monotonic()
        alive_pids = {x.pid for x in sessions if x.pid}
        self._first_seen = {p: t for p, t in self._first_seen.items() if p in alive_pids}
        for x in sessions:
            if x.pid and x.pid not in self._first_seen:
                self._first_seen[x.pid] = now
        sessions.sort(key=lambda x: -self._first_seen.get(x.pid, 0.0))

        self._update_section_label()

        self._sync_sessions(sessions)
        self._update_device_counts()
        self._refresh_tick += 1
        self._update_status()

    def _probe_default(self):
        """后台线程起子进程读一次系统默认设备，读完用信号回主线程。"""
        if self._probe_busy:
            return
        self._probe_busy = True

        def work():
            try:
                did = self.core.default_id_fresh(self.flow)
                if did:
                    self._default_ready.emit(did)
            finally:
                self._probe_busy = False

        threading.Thread(target=work, daemon=True).start()

    def _apply_probed_default(self, device_id: str):
        """拿到真实的系统默认设备就立刻改徽章。"""
        if not device_id or device_id == self._sys_default_id:
            return
        self._sys_default_id = device_id
        self.refresh(full=True)

    def _on_need_refresh(self):
        """系统通知（设备插拔等）触发的刷新，回到主线程再动界面。"""
        self.refresh(full=True)

    def _on_device_event(self, flow: int = -1, role: int = -1, device_id: str = ""):
        """COM 通知回调：跑在系统的线程上，不能直接碰界面。"""
        if flow == ac.eRender and role == ac.eConsole and device_id:
            # 通知里带的就是新的默认设备，直接采用，界面立刻跟上
            self._default_ready.emit(device_id)
        if flow in (-1, ac.eRender):
            self._probe_default()
        self._need_refresh.emit()

    def _force_refresh(self):
        """手动刷新：强制重建设备卡片（平时只在设备真变了才重建）。"""
        self._dev_sig = None
        self._probe_default()
        self.refresh(full=True)

    def _on_filter_changed(self, idx: int):
        self.view_mode = idx
        self.show_fav_only = (idx == 1)
        self._sel.clear()
        self._sel_anchor = None
        # 切换任何页签都取消声卡筛选（卡片高亮也要跟着撤，卡片只在设备变化时重建）
        self.selected_device = None
        self._sync_device_active()
        self.refresh(full=True)

    def _sync_device_active(self):
        """把声卡卡片的高亮状态同步到 self.selected_device。"""
        for i in range(self.device_layout.count()):
            w = self.device_layout.itemAt(i).widget()
            if isinstance(w, DeviceCard):
                w.set_active(w.device.id == self.selected_device)

    def _on_device_clicked(self, device_id: str):
        """点设备卡片：只看这块声卡上的应用，再点一次取消。"""
        self.selected_device = None if self.selected_device == device_id else device_id
        self._sync_device_active()
        self.refresh(full=True)

    def _update_section_label(self):
        name = next((d.short_name for d in self.devices if d.id == self.selected_device), "")
        if name:
            self.section_label.setText(f"{name} 上的应用")
        elif self.view_mode == 2:
            self.section_label.setText("已移除的应用")
        elif self.view_mode == 3:
            self.section_label.setText("记住的声卡分配")
        elif self.show_fav_only:
            self.section_label.setText("收藏的应用")
        else:
            self.section_label.setText("正在播放的应用")

    def _on_device_menu(self, card, gpos):
        """声卡卡片右键：设为系统默认。"""
        dev = card.device
        is_default = (dev.id == self._sys_default_id)
        menu = QMenu(self)
        act = menu.addAction(("✓ 当前系统默认" if is_default else "设为系统默认"))
        act.setData("default")
        act.setEnabled(not is_default)
        picked = menu.exec(gpos)
        if picked is None or str(picked.data() or "") != "default":
            return
        new_id = self.core.set_default_and_read(dev.id, self.flow)
        if new_id:
            self._sys_default_id = new_id
        self._dev_sig = None
        self.refresh(full=True)
        if new_id == dev.id:
            self._flash_status(f"已把 {dev.short_name} 设为系统默认")
        else:
            self._flash_status("设置未生效：Windows 没有接受这次默认设备切换")

    def _on_device_volume(self, device_id: str, level: float):
        self.core.set_device_volume(device_id, level)

    def _update_meters(self):
        # 设备电平
        for i in range(self.device_layout.count()):
            w = self.device_layout.itemAt(i).widget()
            if isinstance(w, DeviceCard):
                w.set_level(_db_level(self.core.device_peak(w.device.id)))
        for row in self.rows.values():
            if row.session is None:
                continue
            row.set_level(_db_level(row.session.peak()))

    def _effective_device(self, s: ac.Session) -> str:
        """下拉显示的值：以你在本程序里的设置为准。

        设过就一直显示你设的那块，不会被系统里的当前值弹回去
        （CheVolume 也是这个行为：界面上切换自由，不会被别的软件改回来）。
        从没设过的应用才显示它当前实际在哪块。
        """
        saved = self.store.get(s.process_name, self.flow, s.exe_path)
        if saved:
            if any(d.id == saved for d in self.devices):
                return saved
            want = self.store.get_device_name(s.process_name, self.flow, s.exe_path)
            if want:
                for d in self.devices:
                    if d.short_name == want or d.name == want:
                        return d.id
        return s.device_id or ""

    def _rebuild_devices(self):
        self._clear_layout(self.device_layout)
        c = theme.palette(self.dark)
        if not self.devices:
            hint = QLabel("未找到音频设备")
            hint.setObjectName("Empty")
            self.device_layout.addWidget(hint)
            return
        for d in self.devices:
            card = DeviceCard(d, c["sub"], self.dark)
            card.clicked.connect(self._on_device_clicked)
            card.volume_changed.connect(self._on_device_volume)
            card.menu_requested.connect(self._on_device_menu)
            card.set_active(d.id == self.selected_device)
            card.set_volume(self.core.device_volume(d.id))
            self.device_layout.addWidget(card, 1)
        # 设备少时靠左排列，多时均分整行
        if len(self.devices) < 3:
            self.device_layout.addStretch(1)
        self._fit_device_host()

    def _update_device_counts(self):
        """统计每块声卡上当前有几个应用在发声，显示在卡片上。"""
        counts: dict[str, int] = {}
        if self._list_mode:
            sessions = self._live_cache.values()
            for x in sessions:
                d = x.device_id or ""
                if d:
                    counts[d] = counts.get(d, 0) + 1
        else:
            for row in self.rows.values():
                d = row.session.device_id if row.session is not None else ""
                if d:
                    counts[d] = counts.get(d, 0) + 1
        for i in range(self.device_layout.count()):
            w = self.device_layout.itemAt(i).widget()
            if isinstance(w, DeviceCard):
                w.set_app_count(counts.get(w.device.id, 0))

    def _fit_device_host(self):
        """设备卡片宽度有下限（166px），设备变多时靠横向滚动，不压缩已有卡片。"""
        n = max(1, len(self.devices))
        vw = max(1, self.device_scroll.viewport().width())
        spacing = 10
        per = max(166, (vw - spacing * (n - 1)) // n)
        need = n * per + spacing * (n - 1)
        self.device_host.setFixedSize(max(vw, need), 104)
        self.device_layout.activate()

    def _sync_sessions(self, sessions: list[ac.Session]):
        alive = set()
        for s in sessions:
            key = "sys" if s.is_system else f"{s.pid}:{(s.process_name or '').lower()}"
            alive.add(key)
            row = self.rows.get(key)
            if row is None:
                row = self._create_row(key, s)
                if row is None:
                    continue
            else:
                # 一律换成本次枚举出来的新会话对象。
                # 切声卡或应用重开音频流时，audiosrv 会重建会话，旧对象上的
                # 音量(ISimpleAudioVolume)、静音、电平(IAudioMeterInformation)
                # 接口全部失效——复用电平会一直读到 0，音量滑块也会失灵。
                old = row.session
                row.session = s
                old._vol = None
                old._ctl = None
                old._meter = None
                row.update_volume(s.volume, s.muted)
                want = self._effective_device(s)
                if want != row.current_device_id():
                    row.apply_current_device(want)
                if s.exe_path and row.icon_label.pixmap().isNull():
                    from ui_widgets import file_icon
                    ic = file_icon(s.exe_path)
                    if not ic.isNull():
                        row.icon_label.setPixmap(ic.pixmap(32, 32))

        # 按 sessions 顺序重排行（新应用插到最上面）
        ordered = [self.rows[k] for k in (f"{x.pid}:{(x.process_name or '').lower()}"
                                          if not x.is_system else "sys" for x in sessions)
                   if k in self.rows]
        for i, row in enumerate(ordered):
            self.session_layout.insertWidget(i, row)
            row.set_no(i + 1)

        for key in list(self.rows.keys()):
            if key not in alive:
                row = self.rows.pop(key)
                self.session_layout.removeWidget(row)
                try:
                    row.session._vol = None
                    row.session._ctl = None
                    row.session._meter = None
                except Exception:
                    pass
                row.deleteLater()
                self._applied.discard(key)
                self._sel.discard(key)

        if not self.rows:
            text = ("收藏里还没有正在运行的程序\n点应用行右边的 ☆ 就能收藏"
                    if self.show_fav_only
                    else "当前没有应用在发声\n播放一点声音后这里会自动出现")
            if getattr(self, "_empty_text", None) != text:
                if hasattr(self, "_empty_hint"):
                    self.session_layout.removeWidget(self._empty_hint)
                    self._empty_hint.deleteLater()
                    del self._empty_hint
                self._empty_hint = EmptyHint(text)
                self.session_layout.insertWidget(0, self._empty_hint)
                self._empty_text = text
        elif hasattr(self, "_empty_hint"):
            self.session_layout.removeWidget(self._empty_hint)
            self._empty_hint.deleteLater()
            del self._empty_hint
            self._empty_text = None

    def _create_row(self, key: str, s: ac.Session) -> SessionRow | None:
        try:
            row = self._add_app_row(key, s, s.process_name, s.exe_path, "",
                                    "", len(self.rows) + 1)
        except Exception:
            traceback.print_exc()
            return None
        # 自动套用记忆规则
        saved = self.store.get(s.process_name, self.flow, s.exe_path)
        if (self.store.settings.get("auto_apply", True) and saved
                and s.pid and key not in self._applied):
            # 会话当前不在目标设备上才需要套用
            if (s.device_id or "") != saved:
                self._route(s, saved)
            self._applied.add(key)
        return row

    def _route(self, s: ac.Session, device_id: str) -> bool:
        if not s.pid:
            self._flash_status("系统声音无法单独指定设备")
            return False
        try:
            self.core.route_process(s.pid, device_id, self.flow)
            return True
        except Exception as exc:
            msg = str(exc)
            if "80070005" in msg or "拒绝" in msg:
                self._flash_status(
                    "Windows 拒绝了此应用：它还没有系统级设备记录。"
                    "请先在 Windows 声音设置里为它指定一次设备，之后本程序即可接管。")
            else:
                self._flash_status(f"设置失败：{msg}")
            return False

    # -------------------------------------------------------------- events
    @staticmethod
    def _same_app(a: ac.Session, b: ac.Session) -> bool:
        if a.exe_path and b.exe_path:
            return a.exe_path.lower() == b.exe_path.lower()
        return (a.process_name or "").lower() == (b.process_name or "").lower()

    def _paths_of(self, key: str, session: ac.Session | None) -> tuple[str, str]:
        if session is not None:
            return session.process_name, session.exe_path
        return self._split_key(key)

    def _rule_device(self, key: str) -> str:
        return str((self.store.all_rules().get(key) or {}).get("device") or "")

    def _on_device_changed(self, key: str, device_id: str):
        """声卡下拉改变：能路由就立刻切，同时写进记忆；没运行的只写记忆。"""
        row = self.rows.get(key)
        if row is None:
            return
        name, path = self._paths_of(key, row.session)
        dev_name = next((d.short_name for d in self.devices if d.id == device_id), "")
        s = row.session
        if s is not None:
            targets = [r for r in self.rows.values()
                       if r.session is not None and self._same_app(r.session, s)]
            ok = True
            for r in targets:
                if not self._route(r.session, device_id):
                    ok = False
            if not ok:
                for r in targets:
                    try:
                        r.apply_current_device(self.core.get_route(r.session.pid, self.flow))
                    except Exception:
                        r.apply_current_device("")
                self._update_status()
                return
            for r in targets:
                self._route_ts[r.session.pid] = time.monotonic()
                r.apply_current_device(device_id)
        self.store.set(name, device_id, self.flow, path, dev_name)
        self._fav_sig = self._hidden_sig = self._mem_sig = None
        if device_id:
            self._flash_status(f"{name} → {dev_name}（已记住）")
        else:
            self._flash_status(f"{name} 已恢复跟随系统")
        self._update_status()

    def _on_volume_changed(self, key: str, value: float):
        row = self.rows.get(key)
        s = row.session if row is not None else None
        if s is None:
            return
        try:
            self.core.set_session_volume(s, value)
            s.volume = value
        except Exception:
            pass

    def _on_mute_toggled(self, key: str, muted: bool):
        row = self.rows.get(key)
        s = row.session if row is not None else None
        if s is None:
            return
        try:
            self.core.set_session_mute(s, muted)
            s.muted = muted
        except Exception:
            pass

    def _on_fav_toggled(self, key: str, on: bool):
        row = self.rows.get(key)
        if row is None:
            return
        name, path = self._paths_of(key, row.session)
        self.store.set_fav(name, path, on)
        for r in self.rows.values():
            if r is row:
                continue
            rn, rp = self._paths_of(r.key, r.session)
            if path and rp and rp.lower() == path.lower():
                r.set_favorite(on)
            elif not path and rn.lower() == name.lower():
                r.set_favorite(on)
        self._fav_sig = None
        if self.view_mode == 1 and not on:
            self.refresh(full=True)
        else:
            self._flash_status(f"已收藏 {name}" if on else f"已取消收藏 {name}")
            self._update_status()

    def _on_row_action(self, key: str):
        """行尾动作按钮：按当前页签决定是取消收藏 / 恢复 / 删除记忆。"""
        if self.view_mode == 1:
            self._unfav_keys([key])
        elif self.view_mode == 2:
            self._restore_keys([key])
        elif self.view_mode == 3:
            self._remove_memory_keys([key])

    def _live_map(self) -> dict[str, ac.Session]:
        try:
            sessions = self.core.sessions(self.flow)
        except Exception:
            return {}
        live: dict[str, ac.Session] = {}
        for x in sessions:
            live.setdefault(self.store.key(x.process_name, x.exe_path), x)
        return live

    def _device_ok(self, session, fallback: str = "") -> bool:
        """点声卡卡片后的过滤：在运行的按实际所在声卡，没运行的按记住的声卡。"""
        if not self.selected_device:
            return True
        dev = session.device_id if session is not None else fallback
        return (dev or "") == self.selected_device

    def _add_app_row(self, key: str, session, name: str, path: str,
                     device_id: str, extra_text: str, no: int):
        row = SessionRow(session, self.devices, self.dark,
                         favorite=self.store.is_fav(name, path),
                         no=no, extra_text=extra_text,
                         name=name, path=path, device_id=device_id)
        row.key = key
        row.device_changed.connect(self._on_device_changed)
        row.volume_changed.connect(self._on_volume_changed)
        row.mute_toggled.connect(self._on_mute_toggled)
        row.fav_toggled.connect(self._on_fav_toggled)
        row.action.connect(self._on_row_action)
        row.clicked.connect(self._on_row_clicked)
        menu_handler = {0: self._on_row_menu, 1: self._on_fav_menu,
                        2: self._on_hidden_menu}.get(self.view_mode, self._on_memory_menu)
        row.menu_requested.connect(menu_handler)
        self.session_layout.insertWidget(self.session_layout.count() - 1, row)
        self.rows[key] = row
        if session is not None:
            row.apply_current_device(self._effective_device(session))
            row.update_volume(session.volume, session.muted)
        return row

    def _show_empty(self, text: str, tag: str):
        hint = EmptyHint(text)
        self.session_layout.insertWidget(0, hint)
        self._empty_hint = hint
        self._empty_text = tag

    # ---------------------------------------------------- 选择与右键菜单
    def _row_keys_in_order(self) -> list[str]:
        """按界面顺序列出所有带 key 的行（会话行和管理页的行都算）。"""
        rev = {id(r): k for k, r in self.rows.items()}
        out: list[str] = []
        for i in range(self.session_layout.count()):
            w = self.session_layout.itemAt(i).widget()
            k = rev.get(id(w)) or getattr(w, "key", None)
            if k:
                out.append(k)
        return out

    def _selected_keys(self) -> list[str]:
        return [k for k in self._row_keys_in_order() if k in self._sel]

    def _on_row_clicked(self, row):
        key = getattr(row, "key", "")
        if not key:
            return
        mods = QApplication.keyboardModifiers()
        keys = self._row_keys_in_order()
        if mods & Qt.ControlModifier:
            if key in self._sel:
                self._sel.discard(key)
            else:
                self._sel.add(key)
            self._sel_anchor = key
        elif mods & Qt.ShiftModifier and self._sel_anchor in keys and key in keys:
            i, j = keys.index(self._sel_anchor), keys.index(key)
            lo, hi = min(i, j), max(i, j)
            self._sel = set(keys[lo:hi + 1])
        else:
            self._sel = {key}
            self._sel_anchor = key
        self._apply_selection()

    def _apply_selection(self):
        rev = {id(r): k for k, r in self.rows.items()}
        for i in range(self.session_layout.count()):
            w = self.session_layout.itemAt(i).widget()
            if w is None:
                continue
            k = rev.get(id(w)) or getattr(w, "key", None)
            if k and hasattr(w, "set_selected"):
                w.set_selected(k in self._sel)

    def _select_all(self):
        """Ctrl+A / 右键全选：当前页所有行全选，再按一次取消。"""
        keys = self._row_keys_in_order()
        if not keys:
            return
        self._sel = set() if len(self._sel) >= len(keys) else set(keys)
        self._sel_anchor = keys[0] if self._sel else None
        self._apply_selection()

    def eventFilter(self, obj, ev):
        """列表空白区域：左键取消选中，右键出全局菜单。"""
        if obj is getattr(self, "session_host", None):
            if ev.type() == QEvent.MouseButtonPress:
                if ev.button() == Qt.LeftButton and self._sel:
                    self._sel.clear()
                    self._sel_anchor = None
                    self._apply_selection()
            elif ev.type() == QEvent.ContextMenu:
                self._show_list_menu(ev.globalPos())
                return True
        return super().eventFilter(obj, ev)

    def _show_list_menu(self, gpos):
        menu = QMenu(self)
        act_selall = menu.addAction("取消全选" if self._sel else "全选")
        act_selall.setData("selectall")
        menu.addSeparator()
        act_auto = menu.addAction("自动套用记忆规则")
        act_auto.setCheckable(True)
        act_auto.setChecked(bool(self.store.settings.get("auto_apply", True)))
        act_auto.setData("auto")
        if self.view_mode == 1:
            idle = self._idle_fav_keys()
            if idle:
                act_idle = menu.addAction(f"取消所有未运行的收藏（{len(idle)} 个）")
                act_idle.setData("unfav_idle")
        menu.addSeparator()
        if self.view_mode != 3:
            act_mem = menu.addAction("管理记忆…")
            act_mem.setData("memory")
        if self.view_mode != 1:
            act_fav = menu.addAction("管理收藏…")
            act_fav.setData("fav")
        menu.addSeparator()
        act_reset = menu.addAction("全部恢复默认")
        act_reset.setData("reset")

        picked = menu.exec(gpos)
        what = str(picked.data() or "") if picked is not None else ""
        if what == "selectall":
            self._select_all()
        elif what == "unfav_idle":
            self._unfav_all_idle()
        elif what == "auto":
            self._set_auto_apply(act_auto.isChecked())
        elif what == "memory":
            self._goto_view(3)
        elif what == "fav":
            self._goto_view(1)
        elif what == "reset":
            self.reset_all()

    def _set_auto_apply(self, on: bool):
        self.store.set_setting("auto_apply", bool(on))
        if hasattr(self, "act_auto"):
            self.act_auto.setChecked(bool(on))
        self._update_status()
        self._flash_status("自动套用：开" if on else "自动套用：关")

    def _goto_view(self, idx: int):
        btn = self.filter_group.button(idx)
        if btn is not None:
            btn.setChecked(True)
        self._on_filter_changed(idx)

    def _selected_rows(self) -> list:
        return [self.rows[k] for k in self._row_keys_in_order() if k in self._sel]

    def _on_row_menu(self, row, gpos):
        key = getattr(row, "key", "")
        if key and key not in self._sel:
            self._sel = {key}
            self._sel_anchor = key
            self._apply_selection()
        rows = self._selected_rows()
        if not rows:
            return
        n = len(rows)
        fav_flags = [self.store.is_fav(r.session.process_name, r.session.exe_path) for r in rows]
        menu = QMenu(self)
        act_remove = menu.addAction(f"移除应用（{n} 个）" if n > 1 else "移除应用")
        act_remove.setData("remove")
        menu.addSeparator()
        act_addfav = menu.addAction(f"添加收藏（{n} 个）" if n > 1 else "添加收藏")
        act_addfav.setData("addfav")
        act_addfav.setEnabled(not all(fav_flags))
        act_unfav = menu.addAction(f"取消收藏（{n} 个）" if n > 1 else "取消收藏")
        act_unfav.setData("unfav")
        act_unfav.setEnabled(any(fav_flags))

        picked = menu.exec(gpos)
        what = str(picked.data() or "") if picked is not None else ""
        try:
            if what == "remove":
                self._remove_selected(rows)
            elif what == "addfav":
                self._add_fav_selected(rows)
            elif what == "unfav":
                self._unfav_selected(rows)
        except Exception as exc:
            self._flash_status(f"操作失败：{exc}")

    def _remove_selected(self, rows):
        """把这个应用整个从本程序里移除：设备记忆、收藏、条目一起清掉。

        应用本身不关闭、不修改、不卸载；Windows 那边的按应用分配也还原成跟随系统，
        否则会出现「界面上没有了、声音却还固定在那块声卡」的死角。
        移除后可在「已移除」页恢复。
        """
        n = 0
        for row in rows:
            s = row.session
            key = getattr(row, "key", "")
            if self.store.is_hidden(s.process_name, s.exe_path):
                continue
            self.store.remove(s.process_name, s.exe_path)
            if self.store.is_fav(s.process_name, s.exe_path):
                self.store.toggle_fav(s.process_name, s.exe_path)
            self.store.hide(s.process_name, s.exe_path, s.device_id or "")
            self._applied.discard(key)
            self._sel.discard(key)
            if s.pid:
                try:
                    self.core.route_process(s.pid, "", self.flow)
                except Exception:
                    pass
            n += 1
        self._apply_selection()
        self.refresh(full=True)
        if n:
            self._flash_status(f"已移除 {n} 个应用（可在「已移除」页恢复）")
        else:
            self._flash_status("选中的应用都已移除")

    def _clear_sessions(self):
        """清空会话列表（切到「已移除」页或切回来时用）。"""
        self._clear_layout(self.session_layout)
        self.session_layout.addStretch(1)
        self.rows.clear()
        self._sel.clear()
        self._sel_anchor = None
        for attr in ("_empty_hint", "_empty_text"):
            if hasattr(self, attr):
                delattr(self, attr)

    def _group_sig(self, page: str) -> tuple:
        return (self._group_open.get((page, "run"), True),
                self._group_open.get((page, "idle"), True))

    def _on_group_toggle(self, page: str, gkey: str):
        k = (page, gkey)
        self._group_open[k] = not self._group_open.get(k, True)
        if page == "fav":
            self._fav_sig = None
        elif page == "hid":
            self._hidden_sig = None
        else:
            self._mem_sig = None
        self.refresh(full=True)

    def _emit_grouped(self, page: str, entries: list[tuple], extra_text: str,
                      idle_action_text: str = "", idle_action=None) -> int:
        """按「运行中 / 未运行」分组插入行，返回插进去的行数。

        entries: [(key, session, name, path, device_id, 是否运行中)]
        """
        running = [e for e in entries if e[5]]
        idle = [e for e in entries if not e[5]]
        no = 0
        shown = 0
        for gkey, title, items in (("run", "运行中", running), ("idle", "未运行", idle)):
            if not items:
                continue
            opened = bool(self._group_open.get((page, gkey), True))
            action_text = idle_action_text if (gkey == "idle" and idle_action_text) else ""
            head = ListGroupHeader(title, len(items), opened, gkey, self.dark,
                                   action_text=action_text)
            head.clicked.connect(lambda g, p=page: self._on_group_toggle(p, g))
            if action_text and idle_action is not None:
                keys = tuple(e[0] for e in items)
                head.action.connect(lambda _g, _k=keys: idle_action(list(_k)))
            self.session_layout.insertWidget(self.session_layout.count() - 1, head)
            shown += 1
            if not opened:
                no += len(items)          # 折叠时也占号，展开后序号不变
                continue
            for key, sess, name, path, dev, _run in items:
                no += 1
                shown += 1
                self._add_app_row(key, sess, name, path, dev, extra_text, no)
        return shown

    def _show_hidden_rows(self):
        items = self.store.hidden_items()
        live = self._live_map()
        sig = (tuple(sorted((k, str(v.get("device") or "")) for k, v in items.items())),
               tuple(sorted(live)), self.selected_device, self._group_sig("hid"))
        if self._list_mode == 2 and sig == self._hidden_sig:
            return
        self._live_cache = live
        self._clear_sessions()
        self._list_mode = 2
        self._hidden_sig = sig
        if not items:
            self._show_empty("还没有移除任何应用\n在应用行上右键 → 移除应用", "hidden")
            return
        entries = []
        for key, info in sorted(items.items(),
                                key=lambda kv: (str(kv[1].get("name") or "").lower(), kv[0])):
            s = live.get(key)
            dev = str(info.get("device") or "")
            if not self._device_ok(s, dev):
                continue
            entries.append((key, s, str(info.get("name") or key),
                            str(info.get("path") or ""), dev, s is not None))
        if not entries:
            self._show_empty("这块声卡上没有已移除的应用", "hidden-filter")
            return
        self._emit_grouped("hid", entries, "恢复")

    @staticmethod
    def _split_key(key: str) -> tuple[str, str]:
        """把存储键还原成 (进程名, 路径)。"""
        k = (key or "").strip()
        if "\\" in k or "/" in k:
            base = k.replace("/", "\\").rsplit("\\", 1)[-1]
            name = base[:-4] if base.lower().endswith(".exe") else base
            return name, k
        return k, ""

    def _show_fav_rows(self):
        """「收藏」页：运行中的带完整控制，未运行的置灰但可预选声卡。"""
        favs = self.store.favorites()
        live = self._live_map()
        sig = (frozenset(favs), frozenset(live), self.selected_device,
               self._group_sig("fav"))
        if self._list_mode == 1 and sig == self._fav_sig:
            return
        self._live_cache = live
        self._clear_sessions()
        self._list_mode = 1
        self._fav_sig = sig
        if not favs:
            self._show_empty("还没有收藏\n在应用行右边点 ☆ 就能收藏", "fav")
            return
        entries = []
        for k in sorted(favs):
            s = live.get(k)
            if not self._device_ok(s, self._rule_device(k)):
                continue
            name, path = self._split_key(k)
            entries.append((k, s,
                            s.process_name if s else name,
                            s.exe_path if s else path,
                            "" if s else self._rule_device(k),
                            s is not None))
        if not entries:
            self._show_empty("这块声卡上没有收藏的应用", "fav-filter")
            return
        self._emit_grouped("fav", entries, "移出收藏", "取消全部收藏",
                           lambda keys: self._unfav_keys(keys))

    def _show_memory_rows(self):
        """「记忆」页：记忆里的应用，运行中的带完整控制，未运行的置灰。"""
        rules = self.store.all_rules()
        live = self._live_map()
        sig = (tuple(sorted((k, str(v.get("device") or "")) for k, v in rules.items())),
               tuple(sorted(live)), tuple(d.id for d in self.devices),
               self.selected_device, self._group_sig("mem"))
        if self._list_mode == 3 and sig == self._mem_sig:
            return
        self._live_cache = live
        self._clear_sessions()
        self._list_mode = 3
        self._mem_sig = sig
        if not rules:
            self._show_empty("还没有记忆\n在应用行的下拉里选一块声卡，就会记住它", "memory")
            return
        entries = []
        for key, r in sorted(rules.items(),
                             key=lambda kv: (str(kv[1].get("name") or "").lower(), kv[0])):
            s = live.get(key)
            dev = str(r.get("device") or "")
            if not self._device_ok(s, dev):
                continue
            entries.append((key, s, str(r.get("name") or key),
                            str(r.get("path") or ""), dev, s is not None))
        if not entries:
            self._show_empty("这块声卡上没有记忆的应用", "memory-filter")
            return
        self._emit_grouped("mem", entries, "删除记忆")

    def _selection_for(self, row) -> list[str]:
        """右键某行：它不在选中集里就先单独选它，然后返回选中集。"""
        key = getattr(row, "key", "")
        if key and key not in self._sel:
            self._sel = {key}
            self._sel_anchor = key
            self._apply_selection()
        keys = self._selected_keys()
        return keys or ([key] if key else [])

    def _on_memory_menu(self, row, gpos):
        """记忆行右键：删除 / 改记住的声卡（多选时作用于全部选中）。"""
        keys = self._selection_for(row)
        if not keys:
            return
        rules = self.store.all_rules()
        cur = str(rules.get(keys[0], {}).get("device") or "") if len(keys) == 1 else ""
        n = len(keys)
        menu = QMenu(self)
        act_del = menu.addAction(f"删除 {n} 条记忆" if n > 1 else "删除这条记忆")
        act_del.setData("del")
        sub = menu.addMenu("改记住的声卡" if n == 1 else f"改 {n} 条记忆的声卡")
        act_follow = sub.addAction(("✓ " if not cur else "") + "跟随系统（不记忆）")
        act_follow.setData("dev:")
        for d in self.devices:
            act = sub.addAction(("✓ " if n == 1 and d.id == cur else "") + d.short_name)
            act.setData("dev:" + d.id)

        picked = menu.exec(gpos)
        if picked is None:
            return
        what = str(picked.data() or "")
        if what == "del":
            self._remove_memory_keys(keys)
        elif what.startswith("dev:"):
            new_dev = what[4:]
            for k in keys:
                self._on_device_changed(k, new_dev)
            if len(keys) > 1:
                self._flash_status(f"已改 {n} 条记忆")

    def _remove_memory_keys(self, keys, quiet: bool = False):
        rules = self.store.all_rules()
        n = 0
        for k in keys:
            r = rules.get(k)
            if r:
                self.store.remove(str(r.get("name") or ""), str(r.get("path") or ""))
                n += 1
        self._sel.clear()
        self._sel_anchor = None
        self._apply_selection()
        self._mem_sig = None
        self.refresh(full=True)
        if not quiet:
            self._flash_status(f"已删除 {n} 条记忆，对应应用改为跟随系统")

    def _on_fav_menu(self, row, gpos):
        keys = self._selection_for(row)
        if not keys:
            return
        n = len(keys)
        menu = QMenu(self)
        act = menu.addAction(f"取消收藏（{n} 个）" if n > 1 else "取消收藏")
        act.setData("unfav")
        picked = menu.exec(gpos)
        if picked is None or str(picked.data() or "") != "unfav":
            return
        self._unfav_keys(keys)

    def _on_hidden_menu(self, row, gpos):
        keys = self._selection_for(row)
        if not keys:
            return
        n = len(keys)
        menu = QMenu(self)
        act = menu.addAction(f"恢复（{n} 个）" if n > 1 else "恢复到列表")
        act.setData("restore")
        picked = menu.exec(gpos)
        if picked is None or str(picked.data() or "") != "restore":
            return
        self._restore_keys(keys)

    def _idle_fav_keys(self) -> list[str]:
        """没在运行的收藏的 key 列表。"""
        try:
            sessions = self.core.sessions(self.flow)
        except Exception:
            sessions = []
        live = {self.store.key(x.process_name, x.exe_path) for x in sessions}
        return sorted(k for k in self.store.favorites() if k not in live)

    def _unfav_all_idle(self):
        keys = self._idle_fav_keys()
        if not keys:
            self._flash_status("没有未运行的收藏")
            return
        self._unfav_keys(keys)

    def _unfav_keys(self, keys):
        n = len(keys)
        for k in keys:
            self.store.remove_fav(k)
        self._sel.clear()
        self._sel_anchor = None
        self._apply_selection()
        self._fav_sig = None
        self.refresh(full=True)
        self._flash_status(f"已取消收藏 {n} 个应用" if n > 1 else "已取消收藏")

    def _restore_keys(self, keys):
        n = len(keys)
        for k in keys:
            self.store.unhide(k)
        self._sel.clear()
        self._sel_anchor = None
        self._apply_selection()
        self._hidden_sig = None
        self.refresh(full=True)
        self._flash_status(f"已恢复 {n} 个应用到列表" if n > 1 else "已恢复到应用列表")

    def _on_delete_key(self):
        """Delete 键：按当前页删除选中的条目。"""
        keys = self._selected_keys()
        if not keys:
            return
        if self.view_mode == 3:
            self._remove_memory_keys(keys)
        elif self.view_mode == 1:
            self._unfav_keys(keys)
        elif self.view_mode == 2:
            self._restore_keys(keys)

    def _add_fav_selected(self, rows):
        n = 0
        for row in rows:
            s = row.session
            if not self.store.is_fav(s.process_name, s.exe_path):
                self.store.toggle_fav(s.process_name, s.exe_path)
                n += 1
            row.set_favorite(True)
        self._flash_status(f"已收藏 {n} 个应用" if n else "选中的应用都已收藏")
        self._update_status()

    def _unfav_selected(self, rows):
        n = 0
        for row in rows:
            s = row.session
            if self.store.is_fav(s.process_name, s.exe_path):
                self.store.toggle_fav(s.process_name, s.exe_path)
                n += 1
            row.set_favorite(False)
        self._sel.clear()
        self._apply_selection()
        self._flash_status(f"已取消收藏 {n} 个应用" if n else "选中的应用都没收藏")
        if self.show_fav_only:
            self.refresh(full=True)
        else:
            self._update_status()

    def reset_all(self):
        count = 0
        for row in self.rows.values():
            if row.session.pid and self.store.get(row.session.process_name, self.flow, row.session.exe_path):
                self._route(row.session, "")
                row.apply_current_device("")
                count += 1
        self.store.clear(self.flow)
        self._applied.clear()
        self._flash_status(f"已恢复 {count} 个应用为跟随系统" if count else "没有需要恢复的应用")
        self._update_status()

    # ------------------------------------------------------------- helpers
    def _update_status(self):
        n_rules = self.store.count()
        n_fav = self.store.fav_count()
        auto = "开" if self.store.settings.get("auto_apply", True) else "关"
        policy = "可用" if self.core.policy_available else "不可用（需要 Win10 1803+）"
        n_hidden = len(self.store.hidden_items())
        if self.view_mode == 2:
            # 「已移除」页：条数按移除的应用算，不再按会话
            head = f"{n_hidden} 个已移除"
            self.count_label.setText(f"({n_hidden})")
        elif self.view_mode == 1:
            head = f"{n_fav} 个收藏"
            self.count_label.setText(f"({n_fav})")
        elif self.view_mode == 3:
            head = f"{n_rules} 条记忆"
            self.count_label.setText(f"({n_rules})")
        else:
            extra = f" · 已移除 {n_hidden}" if n_hidden else ""
            head = f"{len(self.rows)} 个会话{extra}"
            self.count_label.setText(f"({len(self.rows)})")
        self.status_label.setText(
            f"{head} · 收藏 {n_fav} · {n_rules} 条记忆规则 · "
            f"自动套用：{auto} · 系统接口：{policy}")

    def _flash_status(self, text: str):
        self.status_label.setText(text)
        QTimer.singleShot(2600, self._update_status)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()


def main():
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setApplicationName("PyAudioRouter")
    app.setQuitOnLastWindowClosed(False)
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
