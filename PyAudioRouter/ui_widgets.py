"""ui_widgets.py — 自定义控件（无边框标题栏、设备卡片、会话行）"""
from __future__ import annotations

from PySide6.QtCore import QFileInfo, QPoint, QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import (QComboBox, QFileIconProvider, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QSizePolicy, QSlider,
                               QVBoxLayout, QWidget)

import theme
from audio_core import Device, Session

_icon_provider = QFileIconProvider()
_icon_cache: dict[str, QIcon] = {}


def file_icon(path: str) -> QIcon:
    if not path:
        return QIcon()
    key = path.lower()
    if key in _icon_cache:
        return _icon_cache[key]
    icon = QIcon()
    try:
        icon = _icon_provider.icon(QFileInfo(path))
    except Exception:
        pass
    if len(_icon_cache) > 400:
        _icon_cache.clear()
    _icon_cache[key] = icon
    return icon


# --------------------------------------------------------------------------- #
class TitleBar(QWidget):
    minimize_clicked = Signal()
    close_clicked = Signal()
    theme_toggled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("TitleBar")
        self.setFixedHeight(46)
        self._drag_pos: QPoint | None = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 10, 4)
        lay.setSpacing(8)

        logo = QLabel()
        logo.setPixmap(theme.app_icon(20).pixmap(20, 20))
        logo.setFixedSize(20, 20)
        lay.addWidget(logo)

        title = QLabel("多声卡窗口管理")
        title.setObjectName("AppTitle")
        lay.addWidget(title)

        lay.addStretch(1)

        self.btn_theme = QPushButton("◐")
        self.btn_theme.setObjectName("WinBtn")
        self.btn_theme.setToolTip("切换深色 / 浅色")
        self.btn_theme.clicked.connect(self.theme_toggled.emit)
        lay.addWidget(self.btn_theme)

        btn_min = QPushButton("—")
        btn_min.setObjectName("WinBtn")
        btn_min.setToolTip("最小化")
        btn_min.clicked.connect(self.minimize_clicked.emit)
        lay.addWidget(btn_min)

        btn_close = QPushButton("✕")
        btn_close.setObjectName("CloseBtn")
        btn_close.setToolTip("关闭")
        btn_close.clicked.connect(self.close_clicked.emit)
        lay.addWidget(btn_close)

    # 拖动窗口
    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
            e.accept()

    def mouseMoveEvent(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.window().move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def mouseReleaseEvent(self, e):
        self._drag_pos = None
        e.accept()


# --------------------------------------------------------------------------- #
class NoWheelComboBox(QComboBox):
    """下拉框忽略滚轮：滚轮只用来滚动列表，避免误改设备。"""

    def wheelEvent(self, e):
        e.ignore()


class NoWheelSlider(QSlider):
    """滑块忽略滚轮：避免滚动列表时误改音量。"""

    def wheelEvent(self, e):
        e.ignore()


def _pct_text(value: float) -> str:
    """电平数值：线性百分比（0~100%），跟电平条长度同一个口径。"""
    return f"{int(round(max(0.0, min(1.0, float(value))) * 100))}%"


class LevelBar(QWidget):
    """细条电平指示：绿 → 黄 → 红。"""

    def __init__(self, dark: bool, parent=None):
        super().__init__(parent)
        self.setFixedHeight(4)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._level = 0.0
        self._dark = dark

    def set_dark(self, dark: bool):
        if dark != self._dark:
            self._dark = dark
            self.update()

    def set_level(self, value: float):
        v = max(0.0, min(1.0, float(value)))
        if abs(v - self._level) > 0.004:
            self._level = v
            self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#2C313A" if self._dark else "#E6E9EE"))
        p.drawRoundedRect(r, 2, 2)
        if self._level <= 0.002:
            return
        w = max(3, int((r.width() - 1) * self._level))
        if self._level > 0.95:
            c = "#E5484D"
        elif self._level > 0.8:
            c = "#E8A33D"
        else:
            c = "#2FBF8F"
        p.setBrush(QColor(c))
        p.drawRoundedRect(QRect(0, 0, w, r.height()), 2, 2)


class DeviceCard(QFrame):
    clicked = Signal(str)
    volume_changed = Signal(str, float)   # (device_id, 0~1)
    menu_requested = Signal(object, object)   # (本卡片, 全局坐标)

    def __init__(self, device: Device, color: str, dark: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("DeviceCard")
        self.device = device
        self.setFixedHeight(96)
        self.setMinimumWidth(128)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(f"{device.name}\n{device.subtitle}\n点击只看这块声卡上的应用")
        self.setProperty("active", "false")
        self._suppress = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        # 第一行：图标 + 名字 + 默认徽章
        top = QHBoxLayout()
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        ic = QLabel()
        ic.setPixmap(theme.device_pixmap(_form_factor_code(device.form_factor), color, 16))
        ic.setFixedSize(16, 16)
        top.addWidget(ic, 0, Qt.AlignVCenter)

        self.name_label = QLabel(device.short_name)
        self.name_label.setObjectName("DevName")
        self.name_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        top.addWidget(self.name_label, 1, Qt.AlignVCenter)
        self.count_label = QLabel("")
        self.count_label.setObjectName("DevCount")
        top.addWidget(self.count_label, 0, Qt.AlignVCenter)
        if device.is_default:
            badge = QLabel("默认")
            badge.setObjectName("Badge")
            top.addWidget(badge, 0, Qt.AlignVCenter)
        lay.addLayout(top)

        # 第二行：音量滑块 + 百分比
        mid = QHBoxLayout()
        mid.setContentsMargins(0, 0, 0, 0)
        mid.setSpacing(6)
        self.slider = NoWheelSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(100)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self._on_volume)
        mid.addWidget(self.slider, 1)
        self.pct = QLabel("100%")
        self.pct.setObjectName("DevPct")
        self.pct.setFixedWidth(34)
        self.pct.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        mid.addWidget(self.pct, 0)
        lay.addLayout(mid)

        # 第三行：电平条 + 数值
        lv_row = QHBoxLayout()
        lv_row.setContentsMargins(0, 0, 0, 0)
        lv_row.setSpacing(5)
        self.level_bar = LevelBar(dark)
        lv_row.addWidget(self.level_bar, 1)
        self.level_label = QLabel("0%")
        self.level_label.setObjectName("LevelPct")
        self.level_label.setFixedWidth(34)
        self.level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lv_row.addWidget(self.level_label, 0)
        lay.addLayout(lv_row)

    # -- 交互 ---------------------------------------------------------------
    def _on_volume(self, value: int):
        self.pct.setText(f"{value}%")
        if self._suppress:
            return
        self.volume_changed.emit(self.device.id, value / 100.0)

    def set_volume(self, level: float):
        self._suppress = True
        try:
            v = int(round(max(0.0, min(1.0, level)) * 100))
            self.slider.setValue(v)
            self.pct.setText(f"{v}%")
        finally:
            self._suppress = False

    def set_level(self, value: float):
        self.level_bar.set_level(value)
        self.level_label.setText(_pct_text(value))

    def set_app_count(self, n: int):
        self.count_label.setText(f"{n} 个" if n else "")

    def set_dark(self, dark: bool):
        self.level_bar.set_dark(dark)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            # 点在滑块上时不要触发筛选
            if self.slider.geometry().contains(e.position().toPoint()):
                super().mousePressEvent(e)
                return
            self.clicked.emit(self.device.id)
            e.accept()

    def contextMenuEvent(self, e):
        self.menu_requested.emit(self, e.globalPos())
        e.accept()

    def set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        label = getattr(self, "name_label", None)
        if label is None:
            return
        fm = label.fontMetrics()
        w = max(20, label.width() - 2)
        label.setText(fm.elidedText(self.device.short_name, Qt.ElideRight, w))


def _form_factor_code(text: str) -> int:
    rev = {v: k for k, v in __import__("audio_core").FORM_FACTOR.items()}
    return rev.get(text, 1)


# --------------------------------------------------------------------------- #
class SessionRow(QFrame):
    device_changed = Signal(object, str)  # (session, device_id)
    volume_changed = Signal(object, float)
    mute_toggled = Signal(object, bool)
    fav_toggled = Signal(object)          # (session,)
    clicked = Signal(object)              # (本行,)
    menu_requested = Signal(object, object)   # (本行, 全局坐标)
    clicked = Signal(object)

    def __init__(self, session: Session, devices: list[Device], dark: bool,
                 favorite: bool = False, parent=None):
        super().__init__(parent)
        self.setObjectName("SessionRow")
        self.setProperty("sel", "false")
        self.session = session
        self.devices = devices
        self._fav = bool(favorite)
        self.setFixedHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._suppress = False

        c = theme.palette(dark)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        # 序号
        self.no_label = QLabel("1")
        self.no_label.setObjectName("RowNo")
        self.no_label.setFixedWidth(18)
        self.no_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.no_label, 0, Qt.AlignVCenter)

        # 进程图标
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(32, 32)
        icon = file_icon(session.exe_path)
        if icon.isNull():
            pm = theme.device_pixmap(1, c["faint"], 20)
            self.icon_label.setPixmap(pm)
        else:
            self.icon_label.setPixmap(icon.pixmap(32, 32))
        lay.addWidget(self.icon_label, 0, Qt.AlignVCenter)

        # 名称 + 完整路径
        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        self.name_label = QLabel(session.title)
        self.name_label.setObjectName("AppName")
        col.addWidget(self.name_label)
        if session.is_system:
            self._full_path = "系统声音（Windows 音频引擎）"
        else:
            self._full_path = session.exe_path or "路径不可读（权限不足）"
        self.sub_label = QLabel(self._full_path)
        self.sub_label.setObjectName("AppSub")
        col.addWidget(self.sub_label)
        lay.addLayout(col, 1)

        # 设备下拉
        self.combo = NoWheelComboBox()
        self.combo.setMinimumWidth(150)
        self.combo.setMaximumWidth(220)
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.addItem("跟随系统", "")
        name_count: dict[str, int] = {}
        for d in devices:
            name_count[d.short_name] = name_count.get(d.short_name, 0) + 1
        for d in devices:
            label = d.short_name
            if name_count.get(label, 0) > 1:
                label = f"{label} ({d.id[-6:-1]})"
            self.combo.addItem(label, d.id)
            self.combo.setItemData(self.combo.count() - 1, d.name, Qt.ToolTipRole)
        self.combo.currentIndexChanged.connect(self._on_device_selected)
        lay.addWidget(self.combo, 0, Qt.AlignVCenter)

        # 音量 + 电平条
        vol_col = QVBoxLayout()
        vol_col.setContentsMargins(0, 0, 0, 0)
        vol_col.setSpacing(3)
        self.slider = NoWheelSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(int(round(session.volume * 100)))
        self.slider.setFixedWidth(96)
        self.slider.setCursor(Qt.PointingHandCursor)
        self.slider.valueChanged.connect(self._on_volume)
        vol_col.addWidget(self.slider)
        self.level_bar = LevelBar(dark)
        self.level_bar.setFixedWidth(96)
        level_row = QHBoxLayout()
        level_row.setContentsMargins(0, 0, 0, 0)
        level_row.setSpacing(5)
        level_row.addWidget(self.level_bar)
        self.level_label = QLabel("0%")
        self.level_label.setObjectName("LevelPct")
        self.level_label.setFixedWidth(34)
        self.level_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        level_row.addWidget(self.level_label)
        vol_col.addLayout(level_row)
        lay.addLayout(vol_col)

        self.vol_label = QLabel(f"{int(round(session.volume * 100))}%")
        self.vol_label.setObjectName("VolValue")
        self.vol_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(self.vol_label, 0, Qt.AlignVCenter)

        # 静音
        self.mute_btn = QPushButton("🔊" if not session.muted else "🔇")
        self.mute_btn.setObjectName("IconBtn")
        self.mute_btn.setCheckable(True)
        self.mute_btn.setChecked(session.muted)
        self.mute_btn.setToolTip("静音 / 取消静音")
        self.mute_btn.clicked.connect(self._on_mute)
        lay.addWidget(self.mute_btn, 0, Qt.AlignVCenter)

        # 收藏
        self.fav_btn = QPushButton()
        self.fav_btn.setObjectName("FavBtn")
        self.fav_btn.setCursor(Qt.PointingHandCursor)
        self.fav_btn.setToolTip("收藏 / 取消收藏")
        self.fav_btn.clicked.connect(self._on_fav)
        lay.addWidget(self.fav_btn, 0, Qt.AlignVCenter)
        self._sync_fav()

        self.setToolTip(f"{session.title}\n{session.exe_path or ''}")

    def resizeEvent(self, e):
        super().resizeEvent(e)
        label = getattr(self, "sub_label", None)
        if label is None:
            return
        fm = label.fontMetrics()
        w = max(40, label.width() - 2)
        label.setText(fm.elidedText(self._full_path, Qt.ElideMiddle, w))

    # -- 交互 ---------------------------------------------------------------
    def _on_device_selected(self, _index: int):
        if self._suppress:
            return
        self.device_changed.emit(self.session, self.combo.currentData() or "")

    def _on_volume(self, value: int):
        self.vol_label.setText(f"{value}%")
        if self._suppress:
            return
        self.volume_changed.emit(self.session, value / 100.0)

    def _on_mute(self):
        muted = self.mute_btn.isChecked()
        self.mute_btn.setText("🔇" if muted else "🔊")
        self.mute_toggled.emit(self.session, muted)

    def _on_fav(self):
        self._fav = not self._fav
        self._sync_fav()
        self.fav_toggled.emit(self.session)

    def _sync_fav(self):
        self.fav_btn.setText("★" if self._fav else "☆")
        self.fav_btn.setProperty("on", "true" if self._fav else "false")
        self.fav_btn.style().unpolish(self.fav_btn)
        self.fav_btn.style().polish(self.fav_btn)

    def current_device_id(self) -> str:
        return self.combo.currentData() or ""

    def set_selected(self, on: bool):
        val = "true" if on else "false"
        if self.property("sel") != val:
            self.setProperty("sel", val)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def set_no(self, n: int):
        self.no_label.setText(str(n))

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)
            e.accept()      # 不要再往上冒泡，否则点行会被当成点空白而清掉选中
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.menu_requested.emit(self, e.globalPos())
        e.accept()

    def set_favorite(self, on: bool):
        self._fav = bool(on)
        self._sync_fav()

    def set_level(self, value: float):
        self.level_bar.set_level(value)
        self.level_label.setText(_pct_text(value))

    def set_dark(self, dark: bool):
        self.level_bar.set_dark(dark)

    # -- 刷新 ---------------------------------------------------------------
    def apply_current_device(self, device_id: str):
        self._suppress = True
        try:
            idx = self.combo.findData(device_id or "")
            self.combo.setCurrentIndex(max(0, idx))
        finally:
            self._suppress = False

    def update_volume(self, volume: float, muted: bool):
        self._suppress = True
        try:
            if not self.slider.isSliderDown():
                self.slider.setValue(int(round(volume * 100)))
                self.vol_label.setText(f"{int(round(volume * 100))}%")
            if self.mute_btn.isChecked() != muted:
                self.mute_btn.setChecked(muted)
                self.mute_btn.setText("🔇" if muted else "🔊")
        finally:
            self._suppress = False


# --------------------------------------------------------------------------- #
class HiddenRow(QFrame):
    """「已移除」页里的条目：只有名字、路径和一个恢复按钮。"""

    restore = Signal(str)          # (key,)
    clicked = Signal(object)
    menu_requested = Signal(object, object)

    def __init__(self, key: str, name: str, path: str, dark: bool,
                 no: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("SessionRow")
        self.key = key
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        no_label = QLabel(str(no))
        no_label.setObjectName("RowNo")
        no_label.setFixedWidth(18)
        no_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(no_label, 0, Qt.AlignVCenter)

        c = theme.palette(dark)
        ic = QLabel()
        ic.setFixedSize(32, 32)
        icon = file_icon(path)
        if icon.isNull():
            ic.setPixmap(theme.device_pixmap(1, c["faint"], 20))
        else:
            ic.setPixmap(icon.pixmap(32, 32))
        lay.addWidget(ic, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        name_label = QLabel(name or key)
        name_label.setObjectName("AppName")
        col.addWidget(name_label)
        path_label = QLabel(path or "")
        path_label.setObjectName("AppSub")
        path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._path_label = path_label
        self._full_path = path or ""
        col.addWidget(path_label)
        lay.addLayout(col, 1)

        btn = QPushButton("恢复")
        btn.setObjectName("GhostBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.restore.emit(self.key))
        lay.addWidget(btn, 0, Qt.AlignVCenter)

    def set_selected(self, on: bool):
        val = "true" if on else "false"
        if self.property("sel") != val:
            self.setProperty("sel", val)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)
            e.accept()
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.menu_requested.emit(self, e.globalPos())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        _elide_path(self)


# --------------------------------------------------------------------------- #
class MemoryRow(QFrame):
    """「记忆」页里的条目：应用 + 它记住的声卡（可下拉改、可删除）。"""

    device_changed = Signal(str, str)   # (key, device_id)
    removed = Signal(str)               # (key,)
    menu_requested = Signal(object, object)   # (本行, 全局坐标)
    clicked = Signal(object)

    def __init__(self, key: str, name: str, path: str, device_id: str,
                 devices: list[Device], dark: bool, no: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("SessionRow")
        self.key = key
        self._suppress = True
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        no_label = QLabel(str(no))
        no_label.setObjectName("RowNo")
        no_label.setFixedWidth(18)
        no_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(no_label, 0, Qt.AlignVCenter)

        c = theme.palette(dark)
        ic = QLabel()
        ic.setFixedSize(32, 32)
        icon = file_icon(path)
        if icon.isNull():
            ic.setPixmap(theme.device_pixmap(1, c["faint"], 20))
        else:
            ic.setPixmap(icon.pixmap(32, 32))
        lay.addWidget(ic, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        name_label = QLabel(name or key)
        name_label.setObjectName("AppName")
        col.addWidget(name_label)
        path_label = QLabel(path or "路径不可读（只有进程名）")
        path_label.setObjectName("AppSub")
        path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._path_label = path_label
        self._full_path = path or ""
        col.addWidget(path_label)
        lay.addLayout(col, 1)

        self.combo = NoWheelComboBox()
        self.combo.setMinimumWidth(150)
        self.combo.setMaximumWidth(220)
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.addItem("跟随系统（不记忆）", "")
        name_count: dict[str, int] = {}
        for d in devices:
            name_count[d.short_name] = name_count.get(d.short_name, 0) + 1
        for d in devices:
            label = d.short_name
            if name_count.get(label, 0) > 1:
                label = f"{label} ({d.id[-6:-1]})"
            self.combo.addItem(label, d.id)
            self.combo.setItemData(self.combo.count() - 1, d.name, Qt.ToolTipRole)
        if device_id and self.combo.findData(device_id) < 0:
            # 记忆里的声卡现在不在（拔了 / 停用），仍然显示出来免得看着像没记住
            self.combo.addItem(f"（不在线）{device_id[-6:-1]}", device_id)
        self.combo.setCurrentIndex(max(0, self.combo.findData(device_id or "")))
        self.combo.currentIndexChanged.connect(self._on_device)
        lay.addWidget(self.combo, 0, Qt.AlignVCenter)

        btn = QPushButton("删除")
        btn.setObjectName("GhostBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.removed.emit(self.key))
        lay.addWidget(btn, 0, Qt.AlignVCenter)

        self._suppress = False

    def _on_device(self, _index: int):
        if self._suppress:
            return
        self.device_changed.emit(self.key, self.combo.currentData() or "")

    def set_selected(self, on: bool):
        val = "true" if on else "false"
        if self.property("sel") != val:
            self.setProperty("sel", val)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)
            e.accept()
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.menu_requested.emit(self, e.globalPos())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        _elide_path(self)


# --------------------------------------------------------------------------- #
def _elide_path(row) -> None:
    """管理行里的路径文字按可用宽度中段省略（窗口变窄时不挤掉右侧控件）。"""
    lab = getattr(row, "_path_label", None)
    if lab is None:
        return
    full = getattr(row, "_full_path", "") or ""
    if not full:
        return
    lab.setText(lab.fontMetrics().elidedText(full, Qt.ElideMiddle, max(20, lab.width() - 2)))


class ListGroupHeader(QFrame):
    """可折叠的分组标题：▾ 运行中 (2)。"""

    clicked = Signal(str)          # (分组 key)
    action = Signal(str)           # 右侧按钮点击 (分组 key)

    def __init__(self, title: str, count: int, opened: bool, group_key: str,
                 dark: bool, parent=None, action_text: str = ""):
        super().__init__(parent)
        self.setObjectName("GroupHead")
        self.setFixedHeight(26)
        self.setCursor(Qt.PointingHandCursor)
        self.group_key = group_key
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 2, 4, 2)
        lay.setSpacing(6)
        lab = QLabel(f"{'▾' if opened else '▸'} {title} ({count})")
        lab.setObjectName("GroupTitle")
        lay.addWidget(lab)
        lay.addStretch(1)
        if action_text:
            btn = QPushButton(action_text)
            btn.setObjectName("GhostBtn")
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedHeight(22)
            btn.clicked.connect(lambda: self.action.emit(self.group_key))
            lay.addWidget(btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self.group_key)
            e.accept()
            return
        super().mousePressEvent(e)


# --------------------------------------------------------------------------- #
class FavRow(QFrame):
    """「收藏」页里的条目：不管应用在不在运行都能看到、能取消收藏。"""

    unfav = Signal(str)            # (key,)
    clicked = Signal(object)
    menu_requested = Signal(object, object)

    def __init__(self, key: str, name: str, path: str, running: bool,
                 dark: bool, no: int = 0, parent=None):
        super().__init__(parent)
        self.setObjectName("SessionRow")
        self.key = key
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(10)

        no_label = QLabel(str(no))
        no_label.setObjectName("RowNo")
        no_label.setFixedWidth(18)
        no_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lay.addWidget(no_label, 0, Qt.AlignVCenter)

        c = theme.palette(dark)
        ic = QLabel()
        ic.setFixedSize(32, 32)
        icon = file_icon(path)
        if icon.isNull():
            ic.setPixmap(theme.device_pixmap(1, c["faint"], 20))
        else:
            ic.setPixmap(icon.pixmap(32, 32))
        lay.addWidget(ic, 0, Qt.AlignVCenter)

        col = QVBoxLayout()
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(2)
        name_label = QLabel(name or key)
        name_label.setObjectName("AppName")
        col.addWidget(name_label)
        path_label = QLabel(path or "只有进程名，路径不可读")
        path_label.setObjectName("AppSub")
        path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._path_label = path_label
        self._full_path = path or ""
        col.addWidget(path_label)
        lay.addLayout(col, 1)

        state = QLabel("运行中" if running else "未运行")
        state.setObjectName("FavState")
        lay.addWidget(state, 0, Qt.AlignVCenter)

        btn = QPushButton("取消收藏")
        btn.setObjectName("GhostBtn")
        btn.setCursor(Qt.PointingHandCursor)
        btn.clicked.connect(lambda: self.unfav.emit(self.key))
        lay.addWidget(btn, 0, Qt.AlignVCenter)

    def set_selected(self, on: bool):
        val = "true" if on else "false"
        if self.property("sel") != val:
            self.setProperty("sel", val)
            self.style().unpolish(self)
            self.style().polish(self)
            self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.clicked.emit(self)
            e.accept()
            return
        super().mousePressEvent(e)

    def contextMenuEvent(self, e):
        self.menu_requested.emit(self, e.globalPos())
        e.accept()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        _elide_path(self)


# --------------------------------------------------------------------------- #
class EmptyHint(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 28, 0, 28)
        lab = QLabel(text)
        lab.setObjectName("Empty")
        lab.setAlignment(Qt.AlignCenter)
        lay.addWidget(lab)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
