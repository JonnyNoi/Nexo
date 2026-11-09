"""Temas (tokens de cor + folha de estilos Qt) e fundo animado de cada tema."""
from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from ..core.util import get_setting, set_setting


def _t(name, effect, bg, surface, surface2, surface3, border, border2, text, muted, accent, accent2, accent_soft,
       ok, warn, bad, info, series, accent_text="#ffffff", light=False):
    return {"name": name, "effect": effect, "light": light, "bg": bg, "surface": surface, "surface2": surface2,
            "surface3": surface3, "border": border, "border2": border2, "text": text, "muted": muted,
            "accent": accent, "accent2": accent2, "accent_soft": accent_soft, "accent_text": accent_text,
            "ok": ok, "warn": warn, "bad": bad, "info": info, "series": series}


# só dois temas: escuro e claro (os temas animados foram retirados)
THEMES: dict[str, dict] = {
    "escuro": _t("Escuro", None, "#0a0c11", "#12151c", "#191d27", "#242a37", "#1e2330", "#2d3444", "#e9ecf3",
                 "#8a93a8", "#6d8bff", "#9b6dff", "#1c2350", "#3ddc97", "#fbbf24", "#f87171", "#60a5fa",
                 ["#6d8bff", "#22d3ee", "#3ddc97", "#c084fc", "#fbbf24", "#f472b6"]),
    "claro": _t("Claro", None, "#f4f5fa", "#ffffff", "#f3f4f9", "#e7e9f1", "#e3e6ee", "#d2d7e2", "#141824",
                "#636c80", "#4f6bff", "#8a4dff", "#e9edff", "#059669", "#b45309", "#dc2626", "#2563eb",
                ["#4f6bff", "#0891b2", "#059669", "#8a4dff", "#d97706", "#db2777"], light=True),
}
GROUPS = {"Temas": ["escuro", "claro"]}
DARK, LIGHT = THEMES["escuro"], THEMES["claro"]   # compatibilidade

C: dict = dict(THEMES["escuro"])
_key = "escuro"
_FONTS = ("Inter", "Segoe UI Variable Text", "Segoe UI", "Noto Sans", "Cantarell", "Ubuntu", "DejaVu Sans")


def current() -> str:
    return _key


def mode() -> str:
    return "light" if C.get("light") else "dark"


def logo_colors() -> tuple[str, str]:
    return C["accent"], C["accent2"]


def backdrop_active() -> bool:
    """Sem fundos na interface: a aplicação usa só as cores do tema."""
    return False


def qc(name: str, alpha: int | None = None) -> QColor:
    c = QColor(C[name])
    if alpha is not None:
        c.setAlpha(alpha)
    return c


def _mix(a: str, b: str, t: float) -> str:
    """Mistura duas cores (t=0 → a, t=1 → b)."""
    ca, cb = QColor(a), QColor(b)
    return QColor(round(ca.red() + (cb.red() - ca.red()) * t), round(ca.green() + (cb.green() - ca.green()) * t),
                  round(ca.blue() + (cb.blue() - ca.blue()) * t)).name()


def _rgba(hex_color: str, a: float) -> str:
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {a:.2f})"


def _font_family() -> str:
    fams = set(QFontDatabase.families())
    return next((f for f in _FONTS if f in fams), QFont().defaultFamily())


def stylesheet() -> str:
    from .icons import svg_file
    c = dict(C)
    check = svg_file("check", c["accent_text"])
    glass = backdrop_active()
    op = max(0.35, min(0.97, get_setting("glass_opacity", 85) / 100))
    if glass:  # interface translúcida por cima do fundo animado / imagem
        base_bg = "transparent"
        card = _rgba(c["surface"], op)
        side = _rgba(c["surface"], min(0.97, op + 0.08))
        field = _rgba(c["surface2"], min(0.97, op + 0.1))
        table = _rgba(c["surface"], max(0.2, op - 0.25))
        alt = _rgba(c["surface2"], max(0.25, op - 0.2))
    else:
        base_bg, card, side, field, table, alt = c["bg"], c["surface"], c["surface"], c["surface2"], c["surface"], \
            c["surface2"]
    light = bool(c.get("light"))
    card_top = _mix(c["surface"], c["accent"], 0.035 if not light else 0.012)
    card_bot = c["surface"] if light else _mix(c["surface"], c["bg"], 0.35)
    glow = _rgba(c["accent"], 0.10 if not light else 0.07)
    glow2 = _rgba(c["accent2"], 0.06 if not light else 0.04)
    nav_on = _rgba(c["accent"], 0.22 if not light else 0.12)
    nav_off = _rgba(c["accent"], 0.03)
    if not glass:
        card = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {card_top}, stop:1 {card_bot})"
        side = f"qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 {_mix(c['surface'], c['accent'], 0.04)}, stop:1 {c['surface']})"
        page_bg = (f"qradialgradient(cx:0.92, cy:0.0, radius:1.1, fx:0.92, fy:0.0, stop:0 {glow}, stop:0.45 {glow2}, "
                   f"stop:1 {c['bg']})")
    else:
        page_bg = base_bg
    return f"""
* {{ font-size: 13px; outline: none; }}
QWidget {{ background: {base_bg}; color: {c['text']}; }}
QScrollArea, QScrollArea > QWidget > QWidget, QStackedWidget {{ background: {base_bg}; }}
QWidget#Page {{ background: {page_bg}; }}
QWidget#Page QLabel, QWidget#Page .QWidget, QWidget#Page QCheckBox, QWidget#Page QRadioButton {{ background: transparent; }}
QDialog, QMessageBox, QFileDialog, QComboBoxPrivateContainer {{ background: {c['surface']}; }}
QDialog QWidget {{ background: transparent; }}
QDialog QLineEdit, QDialog QComboBox, QDialog QSpinBox {{ background: {c['surface2']}; }}
QDialog QListView, QDialog QTreeView, QDialog QListWidget {{ background: {c['surface2']}; }}
QFrame#Card {{ background: {card}; border: 1px solid {c['border']}; border-top-color: {_mix(c['border'], c['border2'] if not light else c['border'], 0.8)}; border-radius: 18px; }}
QFrame#Card:hover {{ border-color: {_mix(c['border2'], c['accent'], 0.25)}; }}
QFrame#Card QLabel, QFrame#Card QCheckBox, QFrame#Card QRadioButton {{ background: transparent; }}
QFrame#Card QWidget#Transparent, QWidget#Transparent {{ background: transparent; }}
QFrame#Sidebar {{ background: {side}; border-right: 1px solid {c['border']}; }}
QFrame#Sidebar QLabel, QFrame#Sidebar QWidget#Transparent {{ background: transparent; }}
QFrame#LiveBox {{ background: {field}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#LiveBox QLabel {{ background: transparent; }}
QFrame#Tip {{ background: {field}; border: 1px solid {c['border']}; border-radius: 12px; }}
QFrame#Tip QLabel {{ background: transparent; }}
QLabel#Title {{ font-size: 28px; font-weight: 800; letter-spacing: -0.5px; }}
QLabel#Subtitle {{ color: {c['muted']}; font-size: 13px; }}
QLabel#CardTitle {{ font-size: 15px; font-weight: 700; letter-spacing: -0.1px; }}
QLabel#Muted {{ color: {c['muted']}; }}
QLabel#Section {{ color: {c['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
QLabel#Big {{ font-size: 30px; font-weight: 800; letter-spacing: -0.8px; }}
QLabel#Logo {{ font-size: 19px; font-weight: 800; letter-spacing: 1.5px; }}
QLabel#Badge {{ background: {c['surface3']}; border-radius: 8px; padding: 2px 8px; color: {c['muted']}; font-size: 11px; font-weight: 600; }}
QLabel#BadgeOk {{ background: transparent; border: 1px solid {c['ok']}; border-radius: 8px; padding: 1px 8px; color: {c['ok']}; font-size: 11px; font-weight: 600; }}
QLabel#Toast {{ background: {c['surface3']}; border: 1px solid {c['border2']}; border-radius: 14px; padding: 12px 16px; }}
QPushButton#Nav {{
    text-align: left; padding: 8px 12px; border: none; border-radius: 10px; background: transparent;
    color: {c['muted']}; font-weight: 600;
}}
QPushButton#Nav:hover {{ background: {c['surface2']}; color: {c['text']}; }}
QPushButton#Nav:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {nav_on}, stop:1 {nav_off});
    border: 1px solid {_rgba(c['accent'], 0.28)}; color: {c['accent'] if light else c['text']}; font-weight: 700; }}
QPushButton#Nav[compact="true"] {{ text-align: center; padding: 9px 0; }}
QPushButton#NavSection {{ border: none; background: transparent; padding: 0; }}
QPushButton#SearchBtn {{
    text-align: left; padding: 7px 10px; border: 1px solid {c['border']}; border-radius: 10px;
    background: {c['surface2']}; color: {c['muted']}; font-weight: 500;
}}
QPushButton#SearchBtn:hover {{ border-color: {c['accent']}; color: {c['text']}; }}
QPushButton {{
    background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 10px; padding: 8px 15px;
    font-weight: 600;
}}
QPushButton:hover {{ background: {c['surface3']}; border-color: {_mix(c['border2'], c['accent'], 0.35)}; }}
QPushButton:pressed {{ background: {c['border2']}; }}
QPushButton:disabled {{ color: {c['muted']}; background: {c['surface']}; }}
QPushButton:checked {{ background: {c['surface3']}; border-color: {c['accent']}; }}
QPushButton#Primary {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent']}, stop:1 {c['accent2']});
    color: {c['accent_text']}; border: 1px solid {_rgba('#ffffff', 0.10)}; }}
QPushButton#Primary:hover {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {_mix(c['accent'], '#ffffff', 0.12)}, stop:1 {_mix(c['accent2'], '#ffffff', 0.12)}); }}
QPushButton#Primary:pressed {{ background: {c['accent']}; }}
QPushButton#Primary:disabled {{ background: {c['surface3']}; color: {c['muted']}; }}
QPushButton#Danger {{ background: transparent; color: {c['bad']}; border: 1px solid {c['bad']}; }}
QPushButton#Danger:hover {{ background: {c['bad']}; color: white; }}
QPushButton#Danger:disabled {{ color: {c['muted']}; border-color: {c['border']}; }}
QPushButton#Ghost {{ background: transparent; border: none; color: {c['muted']}; padding: 4px 8px; }}
QPushButton#Ghost:hover {{ color: {c['text']}; background: {c['surface2']}; }}
QPushButton#Chip {{ padding: 5px 14px; border-radius: 14px; font-weight: 600; background: {c['surface2']}; color: {c['muted']}; }}
QPushButton#Chip:hover {{ color: {c['text']}; }}
QPushButton#Chip:checked {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 {c['accent']}, stop:1 {c['accent2']}); color: {c['accent_text']}; border-color: transparent; }}
QLineEdit, QComboBox, QSpinBox {{
    background: {field}; border: 1px solid {c['border']}; border-radius: 10px; padding: 7px 11px;
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']};
}}
QLineEdit:hover, QComboBox:hover, QSpinBox:hover {{ border-color: {c['border2']}; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {c['accent']}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 8px; padding: 4px;
    selection-background-color: {c['accent']}; selection-color: {c['accent_text']};
}}
QSpinBox::up-button, QSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}
QTableWidget, QTreeWidget, QListWidget, QTableView, QTreeView {{
    background: {table}; alternate-background-color: {alt}; border: none;
    gridline-color: {c['border']}; selection-background-color: {c['accent_soft']}; selection-color: {c['text']};
}}
QListWidget::item {{ padding: 6px; border-radius: 8px; }}
QListWidget::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QListWidget::item:hover {{ background: {c['surface2']}; }}
QTableView::item, QTreeView::item {{ padding: 2px 4px; border: none; }}
QTableView::item:hover, QTreeView::item:hover {{ background: {_rgba(c['accent'], 0.07)}; }}
QTableView::item:selected, QTreeView::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QHeaderView::section {{
    background: transparent; color: {c['muted']}; border: none; border-bottom: 1px solid {c['border']};
    padding: 8px 8px; font-weight: 700; font-size: 12px;
}}
QHeaderView::section:hover {{ color: {c['text']}; }}
QTableCornerButton::section {{ background: transparent; border: none; }}
QTabWidget::pane {{ border: none; }}
QTabBar {{ background: transparent; }}
QFrame#Card QTabWidget, QFrame#Card QTabBar, QFrame#Card QStackedWidget {{ background: transparent; }}
QTabBar::tab {{
    background: transparent; color: {c['muted']}; padding: 7px 16px; margin: 0 4px 6px 0; border: 1px solid transparent;
    border-radius: 10px; font-weight: 600;
}}
QTabBar::tab:selected {{ color: {c['accent'] if c.get('light') else c['text']}; background: {c['accent_soft']}; border-color: {_rgba(c['accent'], 0.35)}; }}
QTabBar::tab:hover:!selected {{ color: {c['text']}; background: {c['surface2']}; }}
QProgressBar {{ background: {c['surface3']}; border: none; border-radius: 5px; height: 10px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['accent']}, stop:1 {c['accent2']}); border-radius: 5px; }}
QScrollBar:vertical {{ background: transparent; width: 9px; margin: 3px 2px; }}
QScrollBar::handle:vertical {{ background: {c['border2']}; border-radius: 2px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {c['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {c['border2']}; border-radius: 3px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QTableView::indicator, QTreeView::indicator, QCheckBox::indicator, QListView::indicator {{
    width: 16px; height: 16px; border-radius: 5px; border: 1px solid {c['border2']}; background: {c['surface2']};
}}
QTableView::indicator:hover, QTreeView::indicator:hover, QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}
QTableView::indicator:checked, QTreeView::indicator:checked, QCheckBox::indicator:checked, QListView::indicator:checked {{
    background: {c['accent']}; border-color: {c['accent']}; image: url({check});
}}
QCheckBox {{ spacing: 8px; }}
QRadioButton::indicator {{ width: 16px; height: 16px; border-radius: 9px; border: 1px solid {c['border2']}; background: {c['surface2']}; }}
QRadioButton::indicator:checked {{ background: {c['accent']}; border: 4px solid {c['surface2']}; }}
QPlainTextEdit {{ background: {field}; border: 1px solid {c['border']}; border-radius: 10px; font-family: monospace; font-size: 12px; padding: 4px; }}
QToolTip {{ background: {c['surface2']}; color: {c['text']}; border: 1px solid {c['border2']}; border-radius: 8px; padding: 8px 10px; }}
QMenu {{ background: {c['surface2']}; border: 1px solid {c['border2']}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px 7px 14px; border-radius: 6px; background: transparent; }}
QMenu::item:selected {{ background: {c['accent_soft']}; color: {c['text']}; }}
QMenu::item:disabled {{ color: {c['muted']}; }}
QMenu::separator {{ height: 1px; background: {c['border']}; margin: 5px 8px; }}

QSplitter::handle {{ background: {c['border']}; }}
QSlider::groove:horizontal {{ height: 4px; background: {c['surface3']}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {c['accent']}, stop:1 {c['accent2']}); border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {c['accent']}; width: 16px; height: 16px; margin: -6px 0; border-radius: 8px; border: 3px solid {c['surface2']}; }}
QSlider::handle:horizontal:hover {{ background: {c['accent2']}; }}
"""


_accent_cache: dict[str, tuple[str, str] | None] = {}


def accent_from_image(path: str) -> tuple[str, str] | None:
    """Cor viva dominante de uma imagem (para "cores a partir do fundo")."""
    if path in _accent_cache:
        return _accent_cache[path]
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QImageReader
    res = None
    r = QImageReader(path)
    if r.canRead():
        sz = r.size()
        if sz.isValid() and sz.width() > 0:
            r.setScaledSize(QSize(64, max(1, int(64 * sz.height() / sz.width()))))
        img = r.read()
        if not img.isNull():
            buckets = [[0.0, 0.0, 0.0, 0.0] for _ in range(18)]  # peso, h, s, v
            for y in range(0, img.height(), 2):
                for x in range(0, img.width(), 2):
                    c = img.pixelColor(x, y)
                    h, s_, v, _a = c.getHsvF()
                    if h < 0 or s_ < 0.3 or v < 0.3:
                        continue
                    wgt = s_ * v * v
                    b = buckets[min(17, int(h * 18))]
                    b[0] += wgt
                    b[1] += h * wgt
                    b[2] += s_ * wgt
                    b[3] += v * wgt
            best = max(buckets, key=lambda b: b[0])
            if best[0] > 0:
                h = best[1] / best[0]
                s_ = max(0.6, min(0.95, best[2] / best[0]))
                a1 = QColor.fromHsvF(h, s_, 1.0)
                a2 = QColor.fromHsvF((h + 0.07) % 1.0, max(0.35, s_ - 0.25), 1.0)
                res = (a1.name(), a2.name())
    _accent_cache[path] = res
    return res


def _apply_wallpaper_accent() -> None:
    wp = get_setting("wallpaper")
    if not (wp and get_setting("accent_from_wallpaper")):
        return
    import os
    if os.path.splitext(wp)[1].lower() not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"):
        return
    acc = accent_from_image(wp)
    if not acc:
        return
    a1, a2 = acc
    C["accent"], C["accent2"] = a1, a2
    q = QColor(a1)
    lum = 0.299 * q.redF() + 0.587 * q.greenF() + 0.114 * q.blueF()
    C["accent_text"] = "#101010" if lum > 0.6 else "#ffffff"
    soft = QColor.fromHsvF(max(0.0, q.hsvHueF()), 0.55, 0.28 if not C.get("light") else 0.97)
    C["accent_soft"] = soft.name()
    C["series"] = [a1, a2] + [c for c in C["series"][2:]]


def apply(app: QApplication, key: str | None = None) -> None:
    """Aplica um tema (chave de THEMES). Aceita também "dark"/"light" (definições antigas)."""
    global _key
    if key is None:
        key = get_setting("theme", "escuro")
    key = {"dark": "escuro", "light": "claro"}.get(key, key)
    if key not in THEMES:  # temas antigos: claros passam a "claro", os restantes a "escuro"
        key = "claro" if key in ("verao", "kawaii") else "escuro"
    _key = key
    C.clear()
    C.update(THEMES[key])
    C["series"] = list(C["series"])
    f = app.font()
    fam = _font_family()
    if f.family() != fam:
        f.setFamily(fam)
        app.setFont(f)
    app.setStyleSheet(stylesheet())
    set_setting("theme", key)


def restyle(app: QApplication) -> None:
    """Volta a gerar a folha de estilos (ex.: mudou a opacidade ou o fundo)."""
    app.setStyleSheet(stylesheet())
