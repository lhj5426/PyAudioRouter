"""theme.py — 配色、QSS、矢量图标（全部代码生成，不依赖图片资源）"""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QIcon, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPixmap)

LIGHT = {
    "bg": "#F2F4F7",
    "card": "#FFFFFF",
    "card_alt": "#FAFBFC",
    "border": "#E4E7EC",
    "border_strong": "#D3D8E0",
    "text": "#14181F",
    "sub": "#6B7280",
    "faint": "#9AA1AC",
    "accent": "#2F6FED",
    "accent_hover": "#245BD0",
    "accent_soft": "#E9F0FE",
    "hover": "#F1F3F6",
    "track": "#E6E9EE",
    "ok": "#17A673",
    "warn": "#E8A33D",
    "shadow": "rgba(16, 24, 40, 0.08)",
}

DARK = {
    "bg": "#121417",
    "card": "#1B1E24",
    "card_alt": "#20242B",
    "border": "#2A2F38",
    "border_strong": "#363C47",
    "text": "#E9EBEF",
    "sub": "#949BAA",
    "faint": "#6E7686",
    "accent": "#4C8DFF",
    "accent_hover": "#6BA1FF",
    "accent_soft": "#1B2942",
    "hover": "#23272F",
    "track": "#2C313A",
    "ok": "#2FBF8F",
    "warn": "#E0A44A",
    "shadow": "rgba(0, 0, 0, 0.45)",
}


def palette(dark: bool) -> dict:
    return DARK if dark else LIGHT


def build_qss(dark: bool) -> str:
    c = palette(dark)
    return f"""
* {{
    font-family: "Microsoft YaHei UI", "Segoe UI", "PingFang SC", sans-serif;
    font-size: 13px;
    color: {c['text']};
    outline: none;
}}
QWidget#Root {{
    background: transparent;
}}
QFrame#Shell {{
    background: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 14px;
}}
QWidget#Body {{
    background: transparent;
}}

/* ---------- 标题栏 ---------- */
QWidget#TitleBar {{
    background: transparent;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}}
QLabel#AppTitle {{
    font-size: 14px;
    font-weight: 600;
    color: {c['text']};
}}
QLabel#AppVersion {{
    font-size: 11px;
    color: {c['faint']};
}}
QPushButton#WinBtn {{
    border: none;
    border-radius: 8px;
    background: transparent;
    color: {c['sub']};
    font-size: 15px;
    min-width: 30px;
    max-width: 30px;
    min-height: 26px;
    max-height: 26px;
}}
QPushButton#WinBtn:hover {{
    background: {c['hover']};
    color: {c['text']};
}}
QPushButton#CloseBtn {{
    border: none;
    border-radius: 8px;
    background: transparent;
    color: {c['sub']};
    font-size: 15px;
    min-width: 30px;
    max-width: 30px;
    min-height: 26px;
    max-height: 26px;
}}
QPushButton#CloseBtn:hover {{
    background: #E5484D;
    color: #FFFFFF;
}}

/* ---------- 分段标签 ---------- */
QPushButton#SegBtn {{
    border: 1px solid {c['border']};
    background: {c['card']};
    color: {c['sub']};
    padding: 3px 12px;
    border-radius: 7px;
    font-size: 12px;
}}
QPushButton#SegBtn:hover {{
    background: {c['hover']};
    color: {c['text']};
}}
QPushButton#SegBtn:checked {{
    background: {c['accent']};
    border-color: {c['accent']};
    color: #FFFFFF;
    font-weight: 600;
}}

/* ---------- 收藏星标 ---------- */
QPushButton#FavBtn {{
    border: none;
    background: transparent;
    color: {c['faint']};
    font-size: 17px;
    min-width: 26px;
    max-width: 26px;
    min-height: 26px;
    max-height: 26px;
    padding: 0;
}}
QPushButton#FavBtn:hover {{
    color: #E8A33D;
}}
QPushButton#FavBtn[on="true"] {{
    color: #E8A33D;
}}

/* ---------- 设备卡片 ---------- */
QFrame#DeviceCard {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 11px;
}}
QFrame#DeviceCard:hover {{
    border-color: {c['border_strong']};
    background: {c['card_alt']};
}}
QFrame#DeviceCard[active="true"] {{
    border: 1px solid {c['accent']};
    background: {c['accent_soft']};
}}
QLabel#DevName {{
    font-size: 13px;
    font-weight: 600;
    color: {c['text']};
}}
QLabel#DevCount {{
    font-size: 11px;
    color: {c['sub']};
}}
QLabel#DevPct {{
    font-size: 11px;
    color: {c['sub']};
}}
QLabel#LevelPct {{
    font-size: 10px;
    color: {c['faint']};
}}
QLabel#Badge {{
    background: {c['accent_soft']};
    color: {c['accent']};
    border-radius: 7px;
    padding: 1px 7px;
    font-size: 10px;
    font-weight: 600;
}}
QLabel#BadgeGray {{
    background: {c['hover']};
    color: {c['sub']};
    border-radius: 7px;
    padding: 1px 7px;
    font-size: 10px;
}}

/* ---------- 会话行 ---------- */
QFrame#SessionRow {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 11px;
}}
QFrame#SessionRow:hover {{
    border-color: {c['border_strong']};
}}
QFrame#SessionRow[sel="true"] {{
    background: {c['accent_soft']};
    border: 1px solid {c['accent']};
}}
QLabel#AppName {{
    font-size: 13px;
    font-weight: 600;
    color: {c['text']};
}}
QLabel#AppSub {{
    font-size: 12px;
    color: {c['text']};
}}
QLabel#VolValue {{
    font-size: 11px;
    color: {c['sub']};
    min-width: 34px;
}}
QLabel#RowNo {{
    font-size: 11px;
    color: {c['text']};
}}
QLabel#FavState {{
    font-size: 11px;
    color: {c['text']};
}}
QLabel#GroupTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {c['sub']};
}}

/* ---------- 下拉框 ---------- */
QComboBox {{
    background: {c['card_alt']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px 10px;
    min-height: 22px;
    color: {c['text']};
}}
QComboBox:hover {{
    border-color: {c['border_strong']};
}}
QComboBox:focus {{
    border-color: {c['accent']};
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
}}
QComboBox QAbstractItemView {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {c['accent_soft']};
    selection-color: {c['text']};
    outline: none;
}}

/* ---------- 滑块 ---------- */
QSlider::groove:horizontal {{
    height: 4px;
    background: {c['track']};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {c['accent']};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #FFFFFF;
    border: 2px solid {c['accent']};
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::handle:horizontal:hover {{
    background: {c['accent']};
}}

/* ---------- 小按钮 ---------- */
QPushButton#IconBtn {{
    border: 1px solid {c['border']};
    background: {c['card_alt']};
    border-radius: 8px;
    min-width: 30px;
    max-width: 30px;
    min-height: 28px;
    max-height: 28px;
    color: {c['sub']};
    font-size: 13px;
}}
QPushButton#IconBtn:hover {{
    background: {c['hover']};
    color: {c['text']};
}}
QPushButton#IconBtn:checked {{
    background: {c['accent_soft']};
    border-color: {c['accent']};
    color: {c['accent']};
}}
QPushButton#GhostBtn {{
    border: 1px solid {c['border']};
    background: transparent;
    border-radius: 8px;
    padding: 5px 12px;
    color: {c['sub']};
    font-size: 12px;
}}
QPushButton#GhostBtn:hover {{
    background: {c['hover']};
    color: {c['text']};
}}
QPushButton#PrimaryBtn {{
    border: none;
    background: {c['accent']};
    border-radius: 8px;
    padding: 6px 14px;
    color: #FFFFFF;
    font-size: 12px;
    font-weight: 600;
}}
QPushButton#PrimaryBtn:hover {{
    background: {c['accent_hover']};
}}

/* ---------- 滚动区 ---------- */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {c['border_strong']};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['sub']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {c['border_strong']};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

/* ---------- 其他 ---------- */
QLabel#SectionTitle {{
    font-size: 12px;
    font-weight: 600;
    color: {c['sub']};
}}
QLabel#Empty {{
    color: {c['sub']};
    font-size: 12px;
}}
QLabel#StatusText {{
    font-size: 11px;
    color: {c['text']};
}}
QMenu {{
    background: {c['card']};
    border: 1px solid {c['border']};
    border-radius: 9px;
    padding: 5px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
    color: {c['text']};
}}
QMenu::item:selected {{
    background: {c['accent_soft']};
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin: 4px 8px;
}}
QToolTip {{
    background: {c['card']};
    color: {c['text']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: 4px 8px;
}}
"""


# --------------------------------------------------------------------------- #
# 矢量图标
# --------------------------------------------------------------------------- #
def device_pixmap(form_factor: int, color: str, size: int = 22) -> QPixmap:
    """按设备形态画一个线性图标。"""
    pm = QPixmap(size * 2, size * 2)
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    pen = QPen(QColor(color))
    pen.setWidthF(1.7)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    s = size
    if form_factor in (3, 5):  # 耳机 / 耳麦
        path = QPainterPath()
        path.arcMoveTo(QRectF(s * 0.22, s * 0.20, s * 0.56, s * 0.56), 20)
        path.arcTo(QRectF(s * 0.22, s * 0.20, s * 0.56, s * 0.56), 20, 140)
        p.drawPath(path)
        p.drawRoundedRect(QRectF(s * 0.16, s * 0.52, s * 0.14, s * 0.26), 3, 3)
        p.drawRoundedRect(QRectF(s * 0.70, s * 0.52, s * 0.14, s * 0.26), 3, 3)
    elif form_factor in (4,):  # 麦克风
        p.drawRoundedRect(QRectF(s * 0.38, s * 0.14, s * 0.24, s * 0.42), s * 0.12, s * 0.12)
        path = QPainterPath()
        path.arcMoveTo(QRectF(s * 0.26, s * 0.34, s * 0.48, s * 0.40), 180)
        path.arcTo(QRectF(s * 0.26, s * 0.34, s * 0.48, s * 0.40), 180, 180)
        p.drawPath(path)
        p.drawLine(QPointF(s * 0.5, s * 0.74), QPointF(s * 0.5, s * 0.86))
    elif form_factor in (9, 7):  # HDMI / 显示器
        p.drawRoundedRect(QRectF(s * 0.12, s * 0.22, s * 0.76, s * 0.46), 3, 3)
        p.drawLine(QPointF(s * 0.36, s * 0.80), QPointF(s * 0.64, s * 0.80))
        p.drawLine(QPointF(s * 0.5, s * 0.68), QPointF(s * 0.5, s * 0.80))
    elif form_factor == 8:  # SPDIF
        p.drawEllipse(QRectF(s * 0.18, s * 0.18, s * 0.64, s * 0.64))
        p.drawEllipse(QRectF(s * 0.42, s * 0.42, s * 0.16, s * 0.16))
    else:  # 扬声器
        path = QPainterPath()
        path.moveTo(QPointF(s * 0.18, s * 0.40))
        path.lineTo(QPointF(s * 0.32, s * 0.40))
        path.lineTo(QPointF(s * 0.50, s * 0.22))
        path.lineTo(QPointF(s * 0.50, s * 0.78))
        path.lineTo(QPointF(s * 0.32, s * 0.60))
        path.lineTo(QPointF(s * 0.18, s * 0.60))
        path.closeSubpath()
        p.drawPath(path)
        p.drawArc(QRectF(s * 0.50, s * 0.32, s * 0.22, s * 0.36), -60 * 16, 120 * 16)
        p.drawArc(QRectF(s * 0.50, s * 0.22, s * 0.36, s * 0.56), -55 * 16, 110 * 16)
    p.end()
    return pm


def device_icon(form_factor: int, color: str, size: int = 22) -> QIcon:
    return QIcon(device_pixmap(form_factor, color, size))


def app_icon(size: int = 64) -> QIcon:
    """窗口 / 托盘图标：渐变圆角方块 + 声波。"""
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0.0, QColor("#4C8DFF"))
    grad.setColorAt(1.0, QColor("#2F6FED"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.NoPen)
    r = QRectF(0, 0, size, size)
    p.drawRoundedRect(r, size * 0.26, size * 0.26)

    pen = QPen(QColor("#FFFFFF"))
    pen.setWidthF(size * 0.075)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    cx, cy = size / 2, size / 2
    # 三条声波弧
    for i, rad in enumerate((size * 0.16, size * 0.27, size * 0.38)):
        p.drawArc(QRectF(cx - rad, cy - rad, rad * 2, rad * 2), -52 * 16, 104 * 16)
    p.setBrush(QColor("#FFFFFF"))
    p.setPen(Qt.NoPen)
    p.drawEllipse(QPointF(cx - size * 0.14, cy), size * 0.045, size * 0.045)
    p.end()
    return QIcon(pm)


def tray_icon(size: int = 64) -> QIcon:
    return app_icon(size)
