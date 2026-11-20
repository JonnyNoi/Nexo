"""Gráficos estáticos: barras empilhadas (energia por dia) e frametimes de uma sessão de jogo."""
from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from ..core.i18n import tr
from . import theme
from .theme import qc
from .widgets import scaled


def _nice_max(v: float) -> float:
    """Arredonda o topo do eixo para um valor «redondo» (1, 2, 2,5, 5 × 10ⁿ)."""
    if v <= 0:
        return 1.0
    import math
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 2, 2.5, 5, 10):
        if v <= m * e:
            return m * e
    return 10 * e


class StackedBars(QWidget):
    """Uma barra por categoria (ex.: dia) com várias partes empilhadas. `fmt` formata os valores do eixo."""

    def __init__(self, height: int = 200, fmt=lambda v: f"{v:.0f}"):
        super().__init__()
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)
        self.labels: list[str] = []
        self.parts: list[str] = []
        self.values: list[list[float]] = []      # [categoria][parte]
        self.tips: list[str] = []
        self.fmt = fmt
        self._bars: list[QRectF] = []

    def set_data(self, labels: list[str], parts: list[str], values: list[list[float]], tips: list[str] | None = None):
        self.labels, self.parts, self.values = labels, parts, values
        self.tips = tips or []
        self.update()

    def mouseMoveEvent(self, e):
        pos = e.position() if hasattr(e, "position") else QPointF(e.pos())
        for i, r in enumerate(self._bars):
            if r.left() - 2 <= pos.x() <= r.right() + 2 and i < len(self.tips):
                QToolTip.showText(e.globalPosition().toPoint() if hasattr(e, "globalPosition") else e.globalPos(),
                                  self.tips[i], self)
                return
        QToolTip.hideText()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(scaled(self.font(), 0.8))
        r = QRectF(self.rect()).adjusted(52, 8, -8, -40)
        totals = [sum(v) for v in self.values] or [0]
        top = _nice_max(max(totals) * 1.05)
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.setPen(QPen(qc("border"), 1, Qt.DashLine if i not in (0, 4) else Qt.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(qc("muted"))
            p.drawText(QRectF(0, y - 8, 48, 16), Qt.AlignRight | Qt.AlignVCenter, self.fmt(top * (4 - i) / 4))
        colors = theme.C["series"]
        n = len(self.values)
        self._bars = []
        if n:
            slot = r.width() / n
            w = max(2.0, min(28.0, slot * 0.7))
            every = max(1, int(40 / slot) + 1)    # rótulos sem se sobreporem
            for i, vals in enumerate(self.values):
                x = r.left() + slot * i + (slot - w) / 2
                y = r.bottom()
                for k, v in enumerate(vals):
                    h = r.height() * (v / top) if top else 0
                    if h <= 0:
                        continue
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(colors[k % len(colors)]))
                    p.drawRect(QRectF(x, y - h, w, h))
                    y -= h
                self._bars.append(QRectF(x, r.top(), w, r.height()))
                if i % every == 0 or i == n - 1:
                    p.setPen(qc("muted"))
                    p.drawText(QRectF(x - 20, r.bottom() + 3, w + 40, 14), Qt.AlignHCenter, self.labels[i])
        # legenda
        lx = r.left()
        for k, name in enumerate(self.parts):
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(colors[k % len(colors)]))
            p.drawRoundedRect(QRectF(lx, r.bottom() + 24, 9, 9), 2, 2)
            p.setPen(qc("muted"))
            name = tr(name)
            p.drawText(QPointF(lx + 14, r.bottom() + 33), name)
            lx += p.fontMetrics().horizontalAdvance(name) + 34
        p.end()


class FrameTimeChart(QWidget):
    """Frametimes de uma sessão: linha do fotograma médio (1000/FPS) e do fotograma mais lento de cada ponto;
    os engasgos (≥ `stutter_ms`) ficam marcados a vermelho."""

    def __init__(self, height: int = 220):
        super().__init__()
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.points: list[list] = []
        self.stutter_ms: float | None = None
        self.duration_s = 0.0

    def set_data(self, points: list[list], stutter_ms: float | None, duration_s: float):
        self.points, self.stutter_ms, self.duration_s = points, stutter_ms, duration_s
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(scaled(self.font(), 0.8))
        r = QRectF(self.rect()).adjusted(48, 8, -8, -38)
        avg = [1000.0 / f if f else None for f, _w in self.points]
        worst = [w for _f, w in self.points]
        vals = sorted(v for v in avg + worst if v)
        # o topo ignora os 0,5 % mais altos (um carregamento de 2 s esmagaria o resto do gráfico)
        cap = vals[int(len(vals) * 0.995) - 1] if len(vals) > 20 else (vals[-1] if vals else 50)
        if self.stutter_ms:
            cap = max(cap, self.stutter_ms * 1.2)
        top = _nice_max(cap * 1.1)
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.setPen(QPen(qc("border"), 1, Qt.DashLine if i not in (0, 4) else Qt.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(qc("muted"))
            p.drawText(QRectF(0, y - 8, 44, 16), Qt.AlignRight | Qt.AlignVCenter, f"{top * (4 - i) / 4:.0f} ms")
        n = len(self.points)
        colors = theme.C["series"]

        def xy(i, v):
            x = r.left() + (r.width() * i / max(1, n - 1))
            return QPointF(x, r.bottom() - min(v / top, 1.0) * r.height())

        for series, color, width in ((worst, QColor(colors[1 % len(colors)]), 1.2),
                                     (avg, QColor(colors[0]), 2.0)):
            path = QPainterPath()
            started = False
            for i, v in enumerate(series):
                if not v:
                    started = False
                    continue
                pt = xy(i, v)
                if started:
                    path.lineTo(pt)
                else:
                    path.moveTo(pt)
                    started = True
            p.setPen(QPen(color, width))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        if self.stutter_ms:
            y = r.bottom() - min(self.stutter_ms / top, 1.0) * r.height()
            p.setPen(QPen(qc("bad"), 1, Qt.DotLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(Qt.NoPen)
            p.setBrush(qc("bad"))
            for i, w in enumerate(worst):
                if w and w >= self.stutter_ms:
                    p.drawEllipse(xy(i, w), 2.6, 2.6)
        # eixo do tempo
        p.setPen(qc("muted"))
        mins = self.duration_s / 60
        for k in range(5):
            x = r.left() + r.width() * k / 4
            p.drawText(QRectF(x - 30, r.bottom() + 3, 60, 14), Qt.AlignHCenter, f"{mins * k / 4:.0f} min")
        lx = r.left()
        for name, color in (("Fotograma médio", QColor(colors[0])),
                            ("Fotograma mais lento", QColor(colors[1 % len(colors)])),
                            ("Engasgo", qc("bad"))):
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawRoundedRect(QRectF(lx, r.bottom() + 22, 9, 9), 2, 2)
            p.setPen(qc("muted"))
            name = tr(name)
            p.drawText(QPointF(lx + 14, r.bottom() + 31), name)
            lx += p.fontMetrics().horizontalAdvance(name) + 34
        p.end()
