"""Logótipo do Nexo: hexágono com três ligações em forma de "N" (nós ligados → "nexo").

Desenhado em código para acompanhar as cores do tema e ficar nítido em qualquer tamanho."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap

DEFAULT = ("#4f8cff", "#22d3ee")


def _hexagon(cx: float, cy: float, r: float, rounding: float) -> QPainterPath:
    """Hexágono (vértice em cima) com cantos arredondados."""
    pts = [QPointF(cx + r * math.cos(math.radians(-90 + 60 * i)), cy + r * math.sin(math.radians(-90 + 60 * i)))
           for i in range(6)]
    path = QPainterPath()
    for i in range(6):
        p0, p1, p2 = pts[i - 1], pts[i], pts[(i + 1) % 6]

        def towards(a, b, d):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            ln = math.hypot(dx, dy)
            return QPointF(a.x() + dx / ln * d, a.y() + dy / ln * d)
        a, b = towards(p1, p0, rounding), towards(p1, p2, rounding)
        if i == 0:
            path.moveTo(a)
        else:
            path.lineTo(a)
        path.quadTo(p1, b)
    path.closeSubpath()
    return path


def paint_logo(p: QPainter, rect: QRectF, colors: tuple[str, str] = DEFAULT, text: str | None = None) -> None:
    s = min(rect.width(), rect.height())
    cx, cy = rect.center().x(), rect.center().y()
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    g.setColorAt(0, QColor(colors[0]))
    g.setColorAt(1, QColor(colors[1]))
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(g)
    p.drawPath(_hexagon(cx, cy, s * 0.49, s * 0.09))
    if text:
        f = QFont()
        f.setPixelSize(max(6, int(s * (0.5 if len(text) <= 2 else 0.4))))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("white"))
        p.drawText(rect, Qt.AlignCenter, text)
    else:
        # "N" feito de três ligações entre quatro nós
        u = s / 64
        nodes = [QPointF(cx - 11 * u, cy + 12 * u), QPointF(cx - 11 * u, cy - 12 * u),
                 QPointF(cx + 11 * u, cy + 12 * u), QPointF(cx + 11 * u, cy - 12 * u)]
        pen = QPen(QColor(255, 255, 255, 240), max(1.0, 4.2 * u), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        p.setPen(pen)
        path = QPainterPath(nodes[0])
        for n in nodes[1:]:
            path.lineTo(n)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("white"))
        for n in nodes:
            p.drawEllipse(n, 5.2 * u, 5.2 * u)
        p.setBrush(QColor(colors[0]))
        for n in (nodes[1], nodes[2]):
            p.drawEllipse(n, 2.2 * u, 2.2 * u)
    p.restore()


def pixmap(size: int = 64, colors: tuple[str, str] = DEFAULT, text: str | None = None, dpr: float = 2.0) -> QPixmap:
    px = int(size * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    paint_logo(p, QRectF(0, 0, px, px), colors, text)
    p.end()
    pm.setDevicePixelRatio(dpr)
    return pm


def icon(colors: tuple[str, str] = DEFAULT, text: str | None = None) -> QIcon:
    ic = QIcon()
    for s in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(pixmap(s, colors, text, 1.0))
    return ic


def export(png_path: str, ico_path: str | None = None, colors: tuple[str, str] = DEFAULT) -> None:
    """Grava o logótipo em PNG (256 px) e, opcionalmente, ICO (para o executável do Windows)."""
    img = QImage(256, 256, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    paint_logo(p, QRectF(0, 0, 256, 256), colors)
    p.end()
    img.save(png_path)
    if ico_path:
        img.save(ico_path, "ICO")
