"""main.py — 多声卡窗口管理（PyAudioRouter）主程序

按应用分配音频输出/输入设备。Win10 1803+ 使用系统原生
「应用音量和设备首选项」接口（AudioPolicyConfig），不需要注入进程。
"""
from __future__ import annotations

import math
import os
import sys
import time
import traceback

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QGuiApplication, QIcon
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame, QGraphicsDropShadowEffect,
                               QHBoxLayout, QLabel, QLayout, QMenu, QPushButton, QScrollArea,
                               QSizeGrip, QSystemTrayIcon, QVBoxLayout, QWidget)

import audio_core as ac
import theme
from store import Store
from ui_widgets import DeviceCard, EmptyHint, SessionRow, TitleBar


APP_TITLE = "多声卡窗口管理"
HERE = os.path.dirname(os.path.abspath(__file__))


class MainWindow(QWidget):
    _default_ready = Signal(str)
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
        self.selected_device: str | None = None
        self._default_override = ""
        self._override_until = 0.0
        self._sub_busy = False
        self._route_ts: dict[int, float] = {}
        self._refresh_tick = 0
        self._applied: set[str] = set()

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

        # 轻量轮询：只读默认设备 ID（单次 COM 调用），变了立刻重绘设备卡片。
        # 这样在录制软件 / 系统托盘里切默认设备，这边 0.5 秒内跟上。
        self._last_default_id = ""
        self.dev_timer = QTimer(self)
        self.dev_timer.timeout.connect(self._check_default_device)
        self.dev_timer.start(500)

        # 系统设备变化通知：默认设备切换、设备插拔时立即刷新（比 500ms 轮询更及时）
        self.core.watch_devices(self._on_device_event)

        # 启动后用独立子进程校正一次默认设备（本进程读到的可能是缓存值）。
        # 只做一次：切换默认设备走系统通知，不再起子进程，避免每次切换都卡一下。
        self._default_ready.connect(self._apply_default_override)
        QTimer.singleShot(1500, self._refresh_default_from_subprocess)

        # 电平条刷新（80ms，只读 GetPeakValue，开销很小）
        self.meter_timer = QTimer(self)
        self.meter_timer.timeout.connect(self._update_meters)
        self.meter_timer.start(80)

        self._build_tray()

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
        for b in (self.btn_all, self.btn_fav):
            b.setObjectName("SegBtn")
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
        self.btn_all.setChecked(True)
        self.filter_group.addButton(self.btn_all, 0)
        self.filter_group.addButton(self.btn_fav, 1)
        self.filter_group.idClicked.connect(self._on_filter_changed)
        head.addWidget(self.btn_all)
        head.addWidget(self.btn_fav)

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

        # 用「子进程读到的真值 / 系统通知带来的 id」覆盖缓存值。
        # 不设过期：本进程的 GetDefaultAudioEndpoint 会一直返回旧值，
        # 只有系统真的切换（收到 OnDefaultDeviceChanged）时才更新它。
        if self._default_override:
            if time.monotonic() < self._override_until:
                for d in self.devices:
                    d.is_default = (d.id == self._default_override)
            else:
                self._default_override = ""

        # 设备有变化（默认设备切换、插拔）就重建卡片，外部改默认也能反映出来
        sig = tuple((d.id, d.is_default) for d in self.devices)
        if not self.device_layout.count() or sig != self._dev_sig:
            self._dev_sig = sig
            self._rebuild_devices()
        self._last_default_id = next((d.id for d in self.devices if d.is_default), "")

        try:
            sessions = self.core.sessions(self.flow)
        except Exception:
            sessions = []
        if not self.store.settings.get("show_system_sounds", False):
            sessions = [s for s in sessions if not s.is_system]
        if self.show_fav_only:
            sessions = [s for s in sessions
                        if self.store.is_fav(s.process_name, s.exe_path)]
        if self.selected_device:
            sessions = [s for s in sessions if s.device_id == self.selected_device]
        self._update_section_label()

        self._sync_sessions(sessions)
        self._update_device_counts()
        self._refresh_tick += 1
        self._update_status()

    def _read_default_fresh(self) -> str:
        """用一个独立子进程读系统默认设备。

        audiosrv 会按进程缓存默认设备，本进程内怎么读都可能拿到旧值；
        新起的进程读到的才是当前真实值。

        用 pythonw.exe（无控制台，不会闪黑框）启动，结果写临时文件回传——
        pythonw 没有 stdout，抓不到 print 输出。
        """
        try:
            import subprocess
            import tempfile
            base = os.path.dirname(sys.executable)
            pyw = os.path.join(base, "pythonw.exe")
            py = pyw if os.path.isfile(pyw) else os.path.join(base, "python.exe")
            out = os.path.join(tempfile.gettempdir(), f"pyar_def_{os.getpid()}.txt")
            code = ("import sys, comtypes;"
                    f"sys.path.insert(0, {HERE!r});"
                    "import audio_core as ac;"
                    "comtypes.CoInitialize();"
                    "c = ac.AudioCore(); c.initialize();"
                    f"open({out!r}, 'w', encoding='utf-8').write(c.get_default_id(0, 0))")
            subprocess.run([py, "-c", code], timeout=25,
                           creationflags=0x08000000,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with open(out, encoding="utf-8") as f:
                did = f.read().strip()
            try:
                os.remove(out)
            except Exception:
                pass
            return did
        except Exception:
            return ""

    def _refresh_default_from_subprocess(self):
        # 子进程启动要 1~2 秒，放后台线程；同时只允许一个在跑
        if getattr(self, "_sub_busy", False):
            return
        self._sub_busy = True

        def work():
            try:
                did = self._read_default_fresh()
                if did:
                    self._default_ready.emit(did)      # 跨线程安全
            finally:
                self._sub_busy = False

        import threading
        threading.Thread(target=work, daemon=True).start()

    def _apply_default_override(self, device_id: str):
        if not device_id:
            return
        self._default_override = device_id
        self._override_until = time.monotonic() + 60.0
        self.refresh(full=True)

    def _on_device_event(self, flow: int = -1, role: int = -1, device_id: str = ""):
        """COM 通知回调：只当成「该重新读一次」的信号。

        回调里带的 device_id 不能直接用——audiosrv 给的可能还是缓存旧值，
        一旦拿它当覆盖值，界面就会锁死在旧设备上（之前就是这个 bug）。
        所以统一改成用子进程重新读真值。
        """
        if flow == ac.eRender and role in (ac.eConsole, ac.eMultimedia) and device_id:
            self._default_override = device_id
            self._override_until = time.monotonic() + 60.0
        QTimer.singleShot(50, lambda: self.refresh(full=True))

    def _check_default_device(self):
        """0.5 秒一次的轻量检测：默认设备被别人改了就把界面跟上。"""
        cur = self.core.get_default_id(self.flow)
        if not cur or cur == self._last_default_id:
            return
        self._last_default_id = cur
        self.refresh(full=True)

    def _force_refresh(self):
        """手动刷新：强制重建设备卡片（平时只在设备真变了才重建）。"""
        self._dev_sig = None
        self.refresh(full=True)

    def _on_filter_changed(self, idx: int):
        self.show_fav_only = (idx == 1)
        # 切换「全部 / 收藏」都取消声卡筛选：全部=所有应用，收藏=所有收藏的应用
        self.selected_device = None
        self.refresh(full=True)

    def _on_device_clicked(self, device_id: str):
        """点设备卡片：只看这块声卡上的应用，再点一次取消。"""
        self.selected_device = None if self.selected_device == device_id else device_id
        for i in range(self.device_layout.count()):
            w = self.device_layout.itemAt(i).widget()
            if isinstance(w, DeviceCard):
                w.set_active(w.device.id == self.selected_device)
        self.refresh(full=True)

    def _update_section_label(self):
        name = next((d.short_name for d in self.devices if d.id == self.selected_device), "")
        if name:
            self.section_label.setText(f"{name} 上的应用")
        elif self.show_fav_only:
            self.section_label.setText("收藏的应用")
        else:
            self.section_label.setText("正在播放的应用")

    def _on_device_volume(self, device_id: str, level: float):
        self.core.set_device_volume(device_id, level)

    def _update_meters(self):
        # 设备电平
        for i in range(self.device_layout.count()):
            w = self.device_layout.itemAt(i).widget()
            if isinstance(w, DeviceCard):
                peak = self.core.device_peak(w.device.id)
                if peak <= 0.0:
                    lv = 0.0
                else:
                    db = 20.0 * math.log10(peak)
                    lv = max(0.0, min(1.0, (db + 48.0) / 48.0))
                w.set_level(lv)
        for row in self.rows.values():
            peak = row.session.peak()
            if peak <= 0.0:
                level = 0.0
            else:
                db = 20.0 * math.log10(peak)
                level = max(0.0, min(1.0, (db + 48.0) / 48.0))
            row.set_level(level)

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
        for row in self.rows.values():
            d = row.session.device_id
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
        if hasattr(self, "_empty_hint"):
            self.session_layout.removeWidget(self._empty_hint)
            self._empty_hint.deleteLater()
            del self._empty_hint
        try:
            row = SessionRow(s, self.devices, self.dark,
                             favorite=self.store.is_fav(s.process_name, s.exe_path))
        except Exception:
            traceback.print_exc()
            return None
        row.device_changed.connect(self._on_device_changed)
        row.volume_changed.connect(self._on_volume_changed)
        row.mute_toggled.connect(self._on_mute_toggled)
        row.fav_toggled.connect(self._on_fav_toggled)
        self.session_layout.insertWidget(self.session_layout.count() - 1, row)
        self.rows[key] = row

        # 下拉：有记住的选择就显示它，否则显示会话实际所在设备
        saved = self.store.get(s.process_name, self.flow, s.exe_path)
        row.apply_current_device(self._effective_device(s))

        # 自动套用记忆规则
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
    def _on_device_changed(self, session: ac.Session, device_id: str):
        # 只影响「同一 exe 路径」的行：复制多份的游戏各自独立
        targets = []
        for row in self.rows.values():
            s = row.session
            if session.exe_path:
                same = bool(s.exe_path) and s.exe_path.lower() == session.exe_path.lower()
            else:
                same = s.process_name.lower() == session.process_name.lower()
            if same:
                targets.append(row)

        ok = True
        for row in targets:
            if not self._route(row.session, device_id):
                ok = False

        if not ok:
            # 失败：下拉回退到系统当前实际值，不写入记忆规则
            for row in targets:
                try:
                    row.apply_current_device(self.core.get_route(row.session.pid, self.flow))
                except Exception:
                    row.apply_current_device("")
            self._update_status()
            return

        dev_name = next((d.short_name for d in self.devices if d.id == device_id), "")
        self.store.set(session.process_name, device_id, self.flow,
                       session.exe_path, dev_name)
        for row in targets:
            self._route_ts[row.session.pid] = time.monotonic()
        name = device_id and next((d.short_name for d in self.devices if d.id == device_id), "")
        if device_id:
            self._flash_status(f"{session.process_name} → {name}（已记住）")
        else:
            self._flash_status(f"{session.process_name} 已恢复跟随系统")
        self._update_status()

    def _on_volume_changed(self, session: ac.Session, value: float):
        try:
            self.core.set_session_volume(session, value)
            session.volume = value
        except Exception:
            pass

    def _on_mute_toggled(self, session: ac.Session, muted: bool):
        try:
            self.core.set_session_mute(session, muted)
            session.muted = muted
        except Exception:
            pass

    def _on_fav_toggled(self, session: ac.Session):
        on = self.store.toggle_fav(session.process_name, session.exe_path)
        path = (session.exe_path or "").lower()
        for row in self.rows.values():
            if path and (row.session.exe_path or "").lower() == path:
                row.set_favorite(on)
        self._flash_status(f"已收藏 {session.title}" if on else f"已取消收藏 {session.title}")
        if self.show_fav_only and not on:
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
        self.status_label.setText(
            f"{len(self.rows)} 个会话 · 收藏 {n_fav} · {n_rules} 条记忆规则 · "
            f"自动套用：{auto} · 系统接口：{policy}")
        self.count_label.setText(f"({len(self.rows)})")

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
