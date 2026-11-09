"""Ícones vetoriais (SVG de traço, 24×24) desenhados para o Nexo e coloridos com o tema."""
from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

_P = {
    "home": '<path d="M3 11l9-7 9 7"/><path d="M5 10v10h5v-6h4v6h5V10"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.5" r=".6" fill="C"/>',
    "thermo": '<path d="M10 14V5a2 2 0 0 1 4 0v9a4 4 0 1 1-4 0z"/><path d="M12 9v7"/>',
    "list": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 9h10M7 13h10M7 17h6"/>',
    "flame": '<path d="M12 3c1 4 5 5.5 5 10a5 5 0 0 1-10 0c0-2.5 1.5-3.5 2-5 1 1.5 2 2 2 2 0-3-1-4 1-7z"/>',
    "gauge": '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-5"/><circle cx="12" cy="17" r="1.2"/>',
    "zap": '<path d="M13 3L5 13h6l-1 8 8-10h-6l1-8z"/>',
    "package": '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9L12 3z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
    "wrench": '<path d="M14.5 6.5a4 4 0 0 0 5 5L12 19a2.1 2.1 0 0 1-3-3l7.5-7.5a4 4 0 0 0-5-5l2.5 2.5-1 2-2 1-2.5-2.5"/>',
    "power": '<path d="M12 3v8"/><path d="M6.3 7a8 8 0 1 0 11.4 0"/>',
    "broom": '<path d="M14 4l6 6"/><path d="M17 7l-6 6"/><path d="M11 13c-3 0-6 2-7 7 5-1 7-4 7-7z"/>',
    "hdd": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="12" cy="11" r="3.5"/><path d="M12 11l4 5"/><circle cx="6.5" cy="17" r=".6"/>',
    "disk": '<rect x="3" y="13" width="18" height="7" rx="2"/><path d="M5 13l2-8h10l2 8"/><circle cx="17" cy="16.5" r=".8"/>',
    "usb": '<path d="M12 3v14"/><circle cx="12" cy="19" r="2"/><path d="M12 13l-4-3V7M12 11l4-3V6"/>'
           '<rect x="6.8" y="5" width="2.4" height="2.4"/><circle cx="16" cy="5" r="1.2"/>',
    "gear": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9l2.1 2.1M17 17l2.1 2.1'
            'M4.9 19.1L7 17M17 7l2.1-2.1"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "alert": '<path d="M12 3l9.5 17h-19L12 3z"/><path d="M12 10v4"/><circle cx="12" cy="17" r=".6" fill="C"/>',
    "x": '<path d="M6 6l12 12M18 6L6 18"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14.5-4.5L4 8"/><path d="M4 4v4h4"/><path d="M4 13a8 8 0 0 0 14.5 4.5L20 16"/>'
               '<path d="M20 20v-4h-4"/>',
    "download": '<path d="M12 4v11"/><path d="M7 10l5 5 5-5"/><path d="M5 20h14"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/><path d="M9 12l2 2 4-4"/>',
    "wifi": '<path d="M2.5 9a14 14 0 0 1 19 0"/><path d="M5.5 12.5a9.5 9.5 0 0 1 13 0"/><path d="M8.7 16a5 5 0 0 1 6.6 0"/><circle cx="12" cy="19.3" r=".9" fill="C"/>',
    "speed": '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-5.5"/><circle cx="12" cy="17" r="1.2" fill="C"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3c3 3 3 15 0 18M12 3c-3 3-3 15 0 18"/>',
    "heart": '<path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.5-7 10-7 10z"/>',
    "search": '<circle cx="11" cy="11" r="6.5"/><path d="M16 16l4.5 4.5"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19'
           'M5 19l1.5-1.5M17.5 6.5L19 5"/>',
    "gamepad": '<path d="M6 8h12a4 4 0 0 1 4 4v1.5a3.5 3.5 0 0 1-6.3 2.1L14.5 14h-5l-1.2 1.6A3.5 3.5 0 0 1 2 13.5V12a4 4 0 0 1 4-4z"/>'
               '<path d="M7 10.5v3M5.5 12h3"/><circle cx="16" cy="11" r=".6"/><circle cx="17.5" cy="13" r=".6"/>',
    "image": '<rect x="3" y="4" width="18" height="16" rx="2"/><circle cx="8.5" cy="9.5" r="1.5"/>'
             '<path d="M21 16l-5-5-9 9"/>',
    "moon": '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z"/>',
    "cpu": '<rect x="6" y="6" width="12" height="12" rx="2"/><rect x="9.5" y="9.5" width="5" height="5"/>'
           '<path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/>',
    "virus": '<circle cx="12" cy="12" r="5"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5M5 5l3.5 3.5M15.5 15.5L19 19'
             'M5 19l3.5-3.5M15.5 8.5L19 5"/><circle cx="10.5" cy="11" r=".7" fill="C"/><circle cx="13.5" cy="13" r=".7" fill="C"/>',
    "fan": '<circle cx="12" cy="12" r="1.6"/><path d="M12 10.4C11 7 11.5 3.5 14 3.5c2.6 0 2.4 3.6-.5 6.2"/>'
           '<path d="M13.6 12.4c3.4-1 6.9-.5 6.9 2 0 2.6-3.6 2.4-6.2-.5"/><path d="M11.6 13.6c1 3.4.5 6.9-2 6.9'
           '-2.6 0-2.4-3.6.5-6.2"/><path d="M10.4 11.6c-3.4 1-6.9.5-6.9-2 0-2.6 3.6-2.4 6.2.5"/>',
    "bulb": '<path d="M9 18h6M10 21h4"/><path d="M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2V16h5v-.1c0-.8.4-1.5 1-2A6 6 0 0 0 12 3z"/>',
    "box": '<rect x="3" y="3" width="18" height="18" rx="4"/>',
    "chev_down": '<path d="M6 9l6 6 6-6"/>',
    "chev_right": '<path d="M9 6l6 6-6 6"/>',
    "sidebar": '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M5.5 8h1M5.5 11h1"/>',
    "upgrade": '<path d="M12 20V9"/><path d="M7 13l5-5 5 5"/><path d="M5 4h14"/>',
}


def _svg(name: str, color: str, width: float = 1.8) -> bytes:
    body = _P.get(name, _P["box"]).replace('"C"', f'"{color}"')
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
            f'stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>').encode()


@lru_cache(maxsize=512)
def pixmap(name: str, color: str, size: int = 18, dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    r = QSvgRenderer(QByteArray(_svg(name, color)))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    r.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(name: str, color: str, active: str | None = None, size: int = 18) -> QIcon:
    """Ícone com cor normal e (opcional) cor quando o botão está marcado."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Normal, QIcon.Off)
    if active:
        ic.addPixmap(pixmap(name, active, size), QIcon.Normal, QIcon.On)
        ic.addPixmap(pixmap(name, active, size), QIcon.Active, QIcon.On)
    return ic


def svg_file(name: str, color: str) -> str:
    """Grava o SVG num ficheiro (para usar em folhas de estilo: image: url(...))."""
    from ..core.util import config_dir
    d = config_dir() / "icons"
    d.mkdir(exist_ok=True)
    f = d / f"{name}-{color.lstrip('#')}.svg"
    if not f.exists():
        f.write_bytes(_svg(name, color, 2.6))
    return f.as_posix()
