"""Vista "Histórico" da página Sensores: gráficos de 1 h, 24 h e 7 dias lidos do histórico em disco."""
from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QButtonGroup, QGridLayout, QPushButton, QSizePolicy, QVBoxLayout, QWidget

from . import theme
from .theme import qc
from .widgets import Card, StatTile, hbox, label, run_async, scaled

RANGES = [("1 hora", 3600, 60), ("24 horas", 86400, 600), ("7 dias", 7 * 86400, 3600)]


def _nice_max(v: float) -> float:
    """Arredonda o topo do eixo para que as 4 divisões sejam números redondos (25, 50, 75, 100…)."""
    raw = max(v, 1e-6) / 4
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 10):
        if m * mag >= raw - 1e-9:
            return 4 * m * mag
    return v


class HistoryChart(QWidget):
    """Gráfico com eixo de tempo real: linha = média de cada bloco, sombra = máximo.
    Falhas no histórico (PC desligado) ficam como intervalos sem linha."""

    def __init__(self, unit: str, y_max: float | None = None, height: int = 190):
        super().__init__()
        self.unit = unit
        self.y_max = y_max
        self.series: list[tuple[str, list[tuple[float, float, float]]]] = []
        self.t0 = self.t1 = 0.0
        self.bucket = 60
        self._hover: float | None = None
        self.setMouseTracking(True)
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_data(self, series, t0: float, t1: float, bucket: int):
        self.series = [(n, pts) for n, pts in series]
        self.t0, self.t1, self.bucket = t0, t1, bucket
        self.update()

    def mouseMoveEvent(self, e):
        self._hover = e.position().x()
        self.update()

    def leaveEvent(self, _e):
        self._hover = None
        self.update()

    def _plot_rect(self) -> QRectF:
        return QRectF(self.rect()).adjusted(42, 10, -10, -40)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._plot_rect()
        span = max(self.t1 - self.t0, 1)
        vals = [mx for _n, pts in self.series for _t, _a, mx in pts]
        ymax = self.y_max or ((max(vals) * 1.15) if vals else 1) or 1
        if vals and max(vals) > ymax:
            ymax = max(vals) * 1.05
        ymax = _nice_max(ymax)
        p.setFont(scaled(self.font(), 0.8))
        # grelha horizontal
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.setPen(QPen(qc("border"), 1, Qt.DashLine if i not in (0, 4) else Qt.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(qc("muted"))
            v = ymax * (4 - i) / 4
            p.drawText(QRectF(0, y - 8, 38, 16), Qt.AlignRight | Qt.AlignVCenter, f"{v:g}")
        # eixo do tempo: 7 dias → uma marca por dia (meia-noite); senão 6 marcas espaçadas
        p.setPen(qc("muted"))
        if span > 2 * 86400:
            lt = time.localtime(self.t0)
            t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
            while t < self.t1:
                x = r.left() + (t - self.t0) / span * r.width()
                p.setPen(QPen(qc("border"), 1, Qt.DotLine))
                p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
                p.setPen(qc("muted"))
                p.drawText(QRectF(x - 30, r.bottom() + 3, 60, 14), Qt.AlignHCenter | Qt.AlignTop,
                           time.strftime("%d/%m", time.localtime(t)))
                lt = time.localtime(t + 3600)
                t = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday + 1, 0, 0, 0, 0, 0, -1))
        else:
            for i in range(6):
                t = self.t0 + span * i / 5
                x = r.left() + r.width() * i / 5
                al = Qt.AlignLeft if i == 0 else Qt.AlignRight if i == 5 else Qt.AlignHCenter
                bx = QRectF(x - (0 if i == 0 else 60 if i == 5 else 30), r.bottom() + 3, 60, 14)
                p.drawText(bx, al | Qt.AlignTop, time.strftime("%H:%M", time.localtime(t)))

        def xy(t, v):
            return (r.left() + (t - self.t0) / span * r.width(),
                    r.bottom() - min(max(v, 0) / ymax, 1.0) * r.height())

        colors = theme.C["series"]
        gap = self.bucket * 2.5
        legend_x = r.left()
        for idx, (name, pts) in enumerate(self.series):
            color = QColor(colors[idx % len(colors)])
            # divide em troços contínuos
            runs, cur = [], []
            for pt in pts:
                if cur and pt[0] - cur[-1][0] > gap:
                    runs.append(cur)
                    cur = []
                cur.append(pt)
            if cur:
                runs.append(cur)
            for run in runs:
                if len(run) == 1:
                    x, y = xy(run[0][0], run[0][1])
                    p.setPen(Qt.NoPen)
                    p.setBrush(color)
                    p.drawEllipse(QPointF(x, y), 2, 2)
                    continue
                # sombra do máximo
                band = QPainterPath()
                for k, (t, _a, mx) in enumerate(run):
                    x, y = xy(t, mx)
                    band.moveTo(x, y) if k == 0 else band.lineTo(x, y)
                for t, a, _mx in reversed(run):
                    band.lineTo(*xy(t, a))
                band.closeSubpath()
                c = QColor(color)
                c.setAlpha(45)
                p.fillPath(band, c)
                # linha da média com degradê por baixo
                line = QPainterPath()
                for k, (t, a, _mx) in enumerate(run):
                    x, y = xy(t, a)
                    line.moveTo(x, y) if k == 0 else line.lineTo(x, y)
                area = QPainterPath(line)
                area.lineTo(xy(run[-1][0], 0)[0], r.bottom())
                area.lineTo(xy(run[0][0], 0)[0], r.bottom())
                area.closeSubpath()
                g = QLinearGradient(0, r.top(), 0, r.bottom())
                c1 = QColor(color)
                c1.setAlpha(40)
                c2 = QColor(color)
                c2.setAlpha(0)
                g.setColorAt(0, c1)
                g.setColorAt(1, c2)
                p.fillPath(area, QBrush(g))
                p.setPen(QPen(color, 2))
                p.setBrush(Qt.NoBrush)
                p.drawPath(line)
            # legenda
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            ly = r.bottom() + 28
            p.drawEllipse(QPointF(legend_x + 4, ly - 4), 3.5, 3.5)
            p.setPen(qc("muted"))
            p.drawText(QPointF(legend_x + 12, ly), name)
            legend_x += p.fontMetrics().horizontalAdvance(name) + 30
        p.setPen(qc("muted"))
        p.drawText(QRectF(r.left(), r.bottom() + 17, r.width(), 14), Qt.AlignRight, self.unit + " · sombra = máximo")
        if not vals:
            p.setPen(qc("muted"))
            p.drawText(r, Qt.AlignCenter, "Ainda sem dados neste intervalo")
        # cursor com os valores do ponto mais próximo
        if self._hover is not None and vals and r.left() <= self._hover <= r.right():
            t = self.t0 + (self._hover - r.left()) / r.width() * span
            lines = []
            for idx, (name, pts) in enumerate(self.series):
                near = min(pts, key=lambda q: abs(q[0] - t), default=None)
                if near and abs(near[0] - t) <= self.bucket:
                    lines.append((QColor(colors[idx % len(colors)]),
                                  f"{name}: {near[1]:.0f} (máx. {near[2]:.0f}) {self.unit}"))
            p.setPen(QPen(qc("muted"), 1, Qt.DashLine))
            p.drawLine(QPointF(self._hover, r.top()), QPointF(self._hover, r.bottom()))
            if lines:
                head = time.strftime("%d/%m %H:%M", time.localtime(t))
                fm = p.fontMetrics()
                w = max(fm.horizontalAdvance(s) for _c, s in lines + [(None, head)]) + 20
                h = fm.height() * (len(lines) + 1) + 10
                bx = self._hover + 10 if self._hover + 10 + w < r.right() else self._hover - 10 - w
                box = QRectF(bx, r.top() + 4, w, h)
                bg = QColor(theme.C["surface2"])
                bg.setAlpha(235)
                p.setPen(QPen(qc("border"), 1))
                p.setBrush(bg)
                p.drawRoundedRect(box, 6, 6)
                y = box.top() + 5 + fm.ascent()
                p.setPen(qc("text"))
                p.drawText(QPointF(box.left() + 10, y), head)
                for c, s in lines:
                    y += fm.height()
                    p.setPen(c)
                    p.drawText(QPointF(box.left() + 10, y), s)
        p.end()


class HistoryView(QWidget):
    def __init__(self, hub):
        super().__init__()
        self.setObjectName("Transparent")
        self.hub = hub
        self.range = 1
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(14)

        self.group = QButtonGroup(self)
        row = hbox(spacing=6)
        for i, (name, _s, _b) in enumerate(RANGES):
            b = QPushButton(name)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(i == self.range)
            self.group.addButton(b, i)
            row.addWidget(b)
        self.group.idClicked.connect(self._pick)
        row.addStretch(1)
        self.info = label("", "Muted")
        row.addWidget(self.info)
        v.addLayout(row)

        tiles = QGridLayout()
        tiles.setSpacing(14)
        self.t_cpu = StatTile("CPU mais quente")
        self.t_gpu = StatTile("GPU mais quente")
        self.t_load = StatTile("Carga média da CPU")
        self.t_ram = StatTile("RAM máxima")
        for i, t in enumerate((self.t_cpu, self.t_gpu, self.t_load, self.t_ram)):
            tiles.addWidget(t, 0, i)
        v.addLayout(tiles)

        self.c_temp = HistoryChart("°C")
        self.c_load = HistoryChart("%", 100)
        self.c_power = HistoryChart("W")
        for title, chart in (("Temperaturas", self.c_temp), ("Carga e memória", self.c_load),
                             ("Consumo", self.c_power)):
            card = Card(title)
            card.add(chart, 1)
            v.addWidget(card)
        self.power_card = self.c_power.parentWidget()
        self.off = label("", "Muted", wrap=True)
        v.addWidget(self.off)
        v.addStretch(1)
        self._busy = False
        self._again = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)

    def _pick(self, i):
        self.range = i
        self.refresh()

    def start(self):
        self.refresh()
        self.timer.start(60_000)

    def stop(self):
        self.timer.stop()

    def refresh(self):
        from ..core.util import get_setting
        self.off.setText("" if get_setting("history") else
                         "O histórico está desligado em Definições → Histórico dos sensores.")
        if self._busy:
            self._again = True     # mudou o intervalo a meio de uma leitura: repete no fim
            return
        self._busy = True
        self._again = False
        _name, span, bucket = RANGES[self.range]
        rec = self.hub.record
        keys = ["cpu_temp", "gpu_temp", "cpu_load", "gpu_load", "ram", "cpu_power", "gpu_power"]
        t1 = time.time()
        t0 = t1 - span

        def work():
            return rec.query(keys, t0, t1, bucket), rec.first_ts()

        def done(res):
            self._busy = False
            if self._again:
                self.refresh()
                return
            data, first = res
            self._show(data, first, t0, t1, bucket)

        def fail(_m):
            self._busy = False
            if self._again:
                self.refresh()
        run_async(work, on_done=done, on_fail=fail)

    def _show(self, d, first, t0, t1, bucket):
        def named(*pairs):
            return [(n, d[k]) for k, n in pairs if d.get(k)]
        self.c_temp.set_data(named(("cpu_temp", "CPU"), ("gpu_temp", "GPU")), t0, t1, bucket)
        self.c_load.set_data(named(("cpu_load", "CPU"), ("gpu_load", "GPU"), ("ram", "RAM")), t0, t1, bucket)
        pw = named(("cpu_power", "CPU"), ("gpu_power", "GPU"))
        self.c_power.set_data(pw, t0, t1, bucket)
        self.power_card.setVisible(bool(pw))

        def peak(k):
            pts = d.get(k) or []
            if not pts:
                return None, None
            t, _a, mx = max(pts, key=lambda q: q[2])
            return mx, t

        def when(t):
            fmt = "%d/%m às %H:%M" if t1 - t0 > 86400 else "às %H:%M"
            return time.strftime(fmt, time.localtime(t))

        for tile, k, warn, bad in ((self.t_cpu, "cpu_temp", 80, 90), (self.t_gpu, "gpu_temp", 75, 85)):
            mx, t = peak(k)
            if mx is None:
                tile.set("—", "sem dados")
            else:
                kind = "bad" if mx >= bad else "warn" if mx >= warn else "ok"
                tile.set(f"{mx:.0f} °C", when(t), kind)
        loads = d.get("cpu_load") or []
        if loads:
            self.t_load.set(f"{sum(a for _t, a, _m in loads) / len(loads):.0f} %",
                            f"pico de {max(m for _t, _a, m in loads):.0f} %")
        else:
            self.t_load.set("—", "sem dados")
        mx, t = peak("ram")
        self.t_ram.set("—" if mx is None else f"{mx:.0f} %", "sem dados" if mx is None else when(t),
                       None if mx is None else ("bad" if mx >= 95 else "warn" if mx >= 85 else "ok"))
        if first:
            self.info.setText("A guardar desde " + time.strftime("%d/%m/%Y %H:%M", time.localtime(first)))
        else:
            self.info.setText("O histórico começa a encher a partir de agora (1 ponto por minuto).")
