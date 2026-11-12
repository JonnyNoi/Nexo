"""Widgets reutilizáveis: cartões, gráficos, anéis, interruptores e tarefas em segundo plano."""
from __future__ import annotations

import logging
import threading
from collections import deque

from PySide6.QtCore import QObject, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QAbstractButton, QAbstractSpinBox, QComboBox, QFrame, QHBoxLayout, QLabel,
                               QMessageBox, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget)

from ..core.i18n import tr
from ..core.util import TaskCancelled
from . import theme
from .theme import qc


# =========================================================================== tarefas
class Task(QObject):
    """Executa fn numa thread; os sinais chegam à thread da interface."""
    done = Signal(object)
    failed = Signal(str)
    progress = Signal(object)

    _alive: set["Task"] = set()

    def __init__(self, fn, *args, **kw):
        super().__init__()
        self._fn, self._args, self._kw = fn, args, kw
        self.cancelled = False
        Task._alive.add(self)
        self.done.connect(lambda _x: Task._alive.discard(self))
        self.failed.connect(lambda _x: Task._alive.discard(self))

    def start(self) -> "Task":
        threading.Thread(target=self._run, daemon=True).start()
        return self

    def _run(self):
        try:
            self.done.emit(self._fn(*self._args, **self._kw))
        except TaskCancelled as e:
            logging.getLogger("nexo.task").info("Tarefa %s cancelada", getattr(self._fn, "__qualname__", self._fn))
            self.failed.emit(f"{type(e).__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            logging.getLogger("nexo.task").exception("Tarefa %s falhou", getattr(self._fn, "__qualname__", self._fn))
            self.failed.emit(f"{type(e).__name__}: {e}")


def run_async(fn, *args, on_done=None, on_fail=None, on_progress=None, **kw) -> Task:
    t = Task(fn, *args, **kw)
    if on_done:
        t.done.connect(on_done)
    t.failed.connect(on_fail or (lambda msg: notify(f"Erro: {msg}", "bad")))
    if on_progress:
        t.progress.connect(on_progress)
    return t.start()


# notificação global (a janela principal regista o destino)
_notify_target = None


def set_notify_target(fn) -> None:
    global _notify_target
    _notify_target = fn


def notify(msg: str, kind: str = "info") -> None:
    if _notify_target:
        _notify_target(msg, kind)


def confirm(parent, title: str, text: str) -> bool:
    return QMessageBox.question(parent, title, text, QMessageBox.Yes | QMessageBox.No,
                                QMessageBox.No) == QMessageBox.Yes


# =========================================================================== layout
class Card(QFrame):
    def __init__(self, title: str | None = None, subtitle: str | None = None, parent=None, icon: str | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(20, 18, 20, 18)
        self.lay.setSpacing(10)
        if title:
            head = QHBoxLayout()
            head.setSpacing(12)
            if icon:
                head.addWidget(icon_badge(icon), 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(2)
            t = QLabel(title)
            t.setObjectName("CardTitle")
            col.addWidget(t)
            if subtitle:
                s = QLabel(subtitle)
                s.setObjectName("Muted")
                s.setWordWrap(True)
                col.addWidget(s)
            head.addLayout(col, 1)
            self.head = head
            self.lay.addLayout(head)

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.lay.addWidget(w, stretch)
        else:
            self.lay.addLayout(w, stretch)
        return w


class Page(QScrollArea):
    """Página com título e conteúdo com scroll."""

    def __init__(self, title: str, subtitle: str = "", scroll: bool = True):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("Page")
        self.body = QVBoxLayout(inner)
        self.body.setContentsMargins(28, 24, 28, 24)
        self.body.setSpacing(16)
        head = QHBoxLayout()
        head.setSpacing(14)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(title)
        t.setObjectName("Title")
        col.addWidget(t)
        if subtitle:
            s = QLabel(subtitle)
            s.setObjectName("Subtitle")
            s.setWordWrap(True)
            col.addWidget(s)
        head.addLayout(col, 1)
        self.head = head
        self.body.addLayout(head)
        self.setWidget(inner)
        if not scroll:
            self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def add(self, w, stretch=0):
        if isinstance(w, QWidget):
            self.body.addWidget(w, stretch)
        else:
            self.body.addLayout(w, stretch)
        return w

    def set_icon(self, name: str) -> None:
        """Ícone grande ao lado do título da página."""
        if getattr(self, "_icon_set", False):
            return
        self._icon_set = True
        self.head.insertWidget(0, icon_badge(name, 44, 22), 0, Qt.AlignTop)

    def on_show(self):
        """Chamado quando a página fica visível."""

    def on_hide(self):
        """Chamado quando outra página fica visível."""


def scaled(font: QFont, factor: float, bold: bool | None = None) -> QFont:
    """Cópia da fonte com tamanho multiplicado (funciona com tamanhos em px ou pt)."""
    f = QFont(font)
    if f.pixelSize() > 0:
        f.setPixelSize(max(1, round(f.pixelSize() * factor)))
    elif f.pointSizeF() > 0:
        f.setPointSizeF(f.pointSizeF() * factor)
    else:
        f.setPixelSize(max(1, round(13 * factor)))
    if bold is not None:
        f.setBold(bold)
    return f


def label(text: str = "", obj: str | None = None, wrap: bool = False) -> QLabel:
    lb = QLabel(text)
    if obj:
        lb.setObjectName(obj)
    lb.setWordWrap(wrap)
    return lb


def hbox(*widgets, spacing=10, margins=(0, 0, 0, 0)) -> QHBoxLayout:
    h = QHBoxLayout()
    h.setSpacing(spacing)
    h.setContentsMargins(*margins)
    for w in widgets:
        if w is None:
            h.addStretch(1)
        elif isinstance(w, QWidget):
            h.addWidget(w)
        else:
            h.addLayout(w)
    return h


class IconBadge(QWidget):
    """Quadrado arredondado com um ícone (cor de destaque suave); acompanha o tema."""

    def __init__(self, name: str, size: int = 34, icon_size: int = 18, kind: str = "accent"):
        super().__init__()
        self.name, self.icon_size, self.kind = name, icon_size, kind
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        from .icons import pixmap
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        r = QRectF(self.rect())
        hero = self.width() >= 40 and self.kind == "accent"   # ícone grande do título da página
        if hero:
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, qc("accent"))
            g.setColorAt(1, qc("accent2"))
            p.setBrush(QBrush(g))
        else:
            bg = qc(self.kind)
            bg.setAlpha(40)
            p.setBrush(bg)
        p.drawRoundedRect(r, r.width() * 0.3, r.width() * 0.3)
        pm = pixmap(self.name, theme.C["accent_text"] if hero else theme.C[self.kind], self.icon_size)
        x = (self.width() - self.icon_size) / 2
        p.drawPixmap(QPointF(x, x), pm)
        p.end()


def icon_badge(name: str, size: int = 34, icon_size: int = 18, kind: str = "accent") -> IconBadge:
    return IconBadge(name, size, icon_size, kind)


class Tip(QFrame):
    """Caixa de aviso/dica com ícone."""

    def __init__(self, text: str, kind: str = "info", icon: str | None = None):
        super().__init__()
        self.setObjectName("Tip")
        h = QHBoxLayout(self)
        h.setContentsMargins(12, 10, 12, 10)
        h.setSpacing(10)
        h.addWidget(icon_badge(icon or {"warn": "alert", "bad": "alert", "ok": "check"}.get(kind, "info"),
                               28, 16, kind), 0, Qt.AlignTop)
        self.text = label(text, wrap=True)
        self.text.setTextFormat(Qt.RichText)
        self.text.setOpenExternalLinks(True)
        h.addWidget(self.text, 1)


def status_dot(kind: str) -> str:
    color = theme.C.get(kind, theme.C["muted"])
    return f"<span style='color:{color}'>●</span>"


# =========================================================================== tiles
class StatTile(Card):
    def __init__(self, title: str, value: str = "—", sub: str = ""):
        super().__init__()
        self.lay.setSpacing(4)
        self.t = label(title.upper(), "Muted")
        self.t.setFont(scaled(self.t.font(), 0.85, True))
        self.v = label(value, "Big", wrap=True)
        self.s = label(sub, "Muted", wrap=True)
        for lb in (self.t, self.v, self.s):
            lb.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.lay.addWidget(self.t)
        self.lay.addWidget(self.v)
        self.lay.addWidget(self.s)
        self.lay.addStretch(1)

    def set(self, value: str, sub: str | None = None, color: str | None = None):
        # chamado 1×/s: setStyleSheet obriga o Qt a recalcular o estilo, por isso só quando a cor muda
        if self.v.text() != value:
            self.v.setText(value)
        css = f"color: {theme.C[color]}" if color else ""
        if css != getattr(self, "_css", ""):
            self._css = css
            self.v.setStyleSheet(css)
        if sub is not None and self.s.text() != sub:
            self.s.setText(sub)


# =========================================================================== gráficos
class LineChart(QWidget):
    """Gráfico de linhas/área com várias séries e janela deslizante."""

    def __init__(self, capacity: int = 120, y_max: float | None = 100, unit: str = "%", height: int = 160):
        super().__init__()
        self.capacity = capacity
        self.y_max = y_max
        self.unit = unit
        self.series: dict[str, deque] = {}
        self.colors: dict[str, int] = {}
        self.setMinimumHeight(height)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def push(self, name: str, value: float | None):
        if name not in self.series:
            self.series[name] = deque(maxlen=self.capacity)
            self.colors[name] = len(self.colors)
        self.series[name].append(value)

    def clear(self):
        self.series.clear()
        self.colors.clear()
        self.update()

    def set_capacity(self, n: int):
        self.capacity = n
        for k, d in self.series.items():
            self.series[k] = deque(d, maxlen=n)
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(40, 8, -8, -22)
        vals = [v for d in self.series.values() for v in d if v is not None]
        ymax = self.y_max or (max(vals) * 1.15 if vals else 1) or 1
        if self.y_max and vals and max(vals) > self.y_max:
            ymax = max(vals) * 1.1
        # grelha
        p.setFont(scaled(self.font(), 0.8))
        for i in range(5):
            y = r.top() + r.height() * i / 4
            p.setPen(QPen(qc("border"), 1, Qt.DashLine if i not in (0, 4) else Qt.SolidLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(qc("muted"))
            val = ymax * (4 - i) / 4
            p.drawText(QRectF(0, y - 8, 36, 16), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val:.0f}" if val >= 10 or val == 0 else f"{val:.1f}")
        p.setPen(qc("muted"))
        p.drawText(QRectF(r.left(), r.bottom() + 4, r.width(), 16), Qt.AlignRight, self.unit)
        series_colors = theme.C["series"]
        legend_x = r.left()
        for name, d in self.series.items():
            color = QColor(series_colors[self.colors[name] % len(series_colors)])
            pts = [(i, v) for i, v in enumerate(d) if v is not None]
            if len(pts) >= 2:
                step = r.width() / max(self.capacity - 1, 1)
                off = self.capacity - len(d)
                path = QPainterPath()
                for k, (i, v) in enumerate(pts):
                    x = r.left() + (i + off) * step
                    y = r.bottom() - min(v / ymax, 1.0) * r.height()
                    if k == 0:
                        path.moveTo(x, y)
                    else:
                        path.lineTo(x, y)
                area = QPainterPath(path)
                area.lineTo(r.left() + (pts[-1][0] + off) * step, r.bottom())
                area.lineTo(r.left() + (pts[0][0] + off) * step, r.bottom())
                area.closeSubpath()
                g = QLinearGradient(0, r.top(), 0, r.bottom())
                c1 = QColor(color)
                c1.setAlpha(70)
                c2 = QColor(color)
                c2.setAlpha(0)
                g.setColorAt(0, c1)
                g.setColorAt(1, c2)
                p.fillPath(area, QBrush(g))
                p.setPen(QPen(color, 2))
                p.setBrush(Qt.NoBrush)  # senão o pincel da legenda anterior enche a linha
                p.drawPath(path)
            # legenda
            last = next((v for v in reversed(d) if v is not None), None)
            txt = f"{name}  {last:.0f}" if last is not None else name
            p.setPen(Qt.NoPen)
            p.setBrush(color)
            p.drawEllipse(QPointF(legend_x + 4, r.bottom() + 12), 3.5, 3.5)
            p.setPen(qc("muted"))
            fm = p.fontMetrics()
            p.drawText(QPointF(legend_x + 12, r.bottom() + 16), txt)
            legend_x += fm.horizontalAdvance(txt) + 28
        p.end()


class Ring(QWidget):
    """Anel de percentagem com texto no centro."""

    def __init__(self, title: str = "", size: int = 120):
        super().__init__()
        self.value = 0.0
        self.title = title
        self.center = "—"
        self.sub = ""
        self.color = "accent"
        self.setFixedSize(size, size + 22)

    def set(self, pct: float, center: str, sub: str = "", color: str | None = None):
        self.value = max(0.0, min(100.0, pct or 0))
        self.center, self.sub = center, sub
        self.color = color or ("bad" if self.value >= 90 else "warn" if self.value >= 75 else "accent")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = self.width()
        rect = QRectF(10, 10, s - 20, s - 20)
        p.setPen(QPen(qc("surface3"), 10, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 0, 360 * 16)
        p.setPen(QPen(qc(self.color), 10, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, 90 * 16, int(-self.value * 3.6 * 16))
        p.setPen(qc("text"))
        p.setFont(scaled(self.font(), 1.35, True))
        p.drawText(QRectF(0, 0, s, s - 8), Qt.AlignCenter, self.center)
        p.setFont(scaled(self.font(), 0.8, False))
        p.setPen(qc("muted"))
        p.drawText(QRectF(0, s / 2 + 8, s, 18), Qt.AlignCenter, tr(self.sub))
        p.drawText(QRectF(0, s, s, 20), Qt.AlignCenter, tr(self.title))
        p.end()


class Bar(QWidget):
    """Barra horizontal fina (uso de disco, etc.)."""

    def __init__(self, height: int = 8):
        super().__init__()
        self.value = 0.0
        self.color = "accent"
        self.setFixedHeight(height)

    def set(self, pct: float, color: str | None = None):
        self.value = max(0.0, min(100.0, pct))
        self.color = color or ("bad" if pct >= 90 else "warn" if pct >= 80 else "accent")
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        h = r.height()
        p.setPen(Qt.NoPen)
        p.setBrush(qc("surface3"))
        p.drawRoundedRect(r, h / 2, h / 2)
        if self.value > 0:
            fill = QRectF(r.left(), r.top(), max(h, r.width() * self.value / 100), h)
            if self.color == "accent":
                g = QLinearGradient(fill.topLeft(), fill.topRight())
                g.setColorAt(0, qc("accent"))
                g.setColorAt(1, qc("accent2"))
                p.setBrush(QBrush(g))
            else:
                p.setBrush(qc(self.color))
            p.drawRoundedRect(fill, h / 2, h / 2)
        p.end()


class Toggle(QAbstractButton):
    """Interruptor estilo iOS/Android."""

    def __init__(self, checked: bool = False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        on = self.isChecked()
        p.setPen(Qt.NoPen)
        p.setBrush(qc("accent") if on else qc("surface3"))
        if not self.isEnabled():
            p.setOpacity(0.5)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 3 if on else r.left() + 3
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 3, d, d))
        if self.hasFocus():   # contorno de foco (navegação pelo teclado)
            p.setOpacity(1.0)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(qc("accent"), 2))
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), r.height() / 2 + 1, r.height() / 2 + 1)
        p.end()

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.update()

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.update()


class SettingRow(QWidget):
    """Linha com título, descrição e um widget à direita."""

    def __init__(self, title: str, desc: str, right: QWidget, badge: str = ""):
        super().__init__()
        self.setObjectName("Transparent")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 6, 0, 6)
        col = QVBoxLayout()
        col.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(8)
        t = label(title)
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        top.addWidget(t)
        if badge:
            b = label(badge, "Badge")
            top.addWidget(b)
        top.addStretch(1)
        col.addLayout(top)
        d = label(desc, "Muted", wrap=True)
        col.addWidget(d)
        h.addLayout(col, 1)
        if not isinstance(right, QWidget):   # aceita também um layout (vários controlos)
            box = QWidget()
            box.setObjectName("Transparent")
            box.setLayout(right)
            right = box
        # leitores de ecrã: o controlo à direita fica com o nome e a descrição da linha
        for w in [right, *right.findChildren(QWidget)]:
            if isinstance(w, (QAbstractButton, QComboBox, QAbstractSpinBox, QSlider)) and not w.accessibleName():
                w.setAccessibleName(title)
                w.setAccessibleDescription(desc)
        h.addWidget(right, 0, Qt.AlignVCenter)


def separator() -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {theme.C['border']}; border: none;")
    return f


# =========================================================================== hub de sensores
HUB_KEYS = ("cpu_load", "gpu_load", "cpu_temp", "gpu_temp", "ram", "vram", "cpu_power", "gpu_power")


class SensorHub(QObject):
    """Lê os sensores 1×/s numa única thread dedicada e distribui pelas páginas.

    Também guarda o histórico (15 min), mínimos/máximos de todos os sensores (mesmo com a página
    de sensores fechada), grava para CSV quando pedido e emite alertas de temperatura."""
    updated = Signal(list)
    alert = Signal(str, str)        # mensagem, tipo
    _got_sig = Signal(list, dict)

    INTERVAL = 1.0

    def __init__(self):
        super().__init__()
        self.last: list = []
        self.history: dict[str, deque] = {k: deque(maxlen=900) for k in HUB_KEYS}
        self.minmax: dict[str, list[float]] = {}
        self._csv = None
        self._csv_writer = None
        self._csv_cols: list[str] = []
        self.csv_path: str | None = None
        self._alert_state: dict[str, float] = {}
        self._ram_high = 0                  # segundos seguidos com a RAM acima do limite
        from ..core.history import History
        self.record = History()             # histórico em disco (média por minuto, 7 dias)
        self._stop = threading.Event()
        self._got_sig.connect(self._got, Qt.QueuedConnection)
        threading.Thread(target=self._loop, daemon=True, name="sensors").start()

    def _loop(self):
        import time as _t

        from ..core.sensors import SensorReader, pick, pick_cpu_temp, pick_gpu_temp, pick_power
        try:
            reader = SensorReader()
        except Exception:  # noqa: BLE001
            logging.getLogger("nexo.sensors").exception("Não foi possível iniciar a leitura dos sensores")
            return
        self._reader = reader
        last_err = None
        nxt = _t.monotonic()
        while not self._stop.is_set():
            try:
                readings = reader.read()
                snap = {
                    "cpu_load": pick(readings, "CPU", "Carga total"), "gpu_load": pick(readings, "GPU", "Carga"),
                    "cpu_temp": pick_cpu_temp(readings), "gpu_temp": pick_gpu_temp(readings),
                    "ram": pick(readings, "Memória", "RAM em uso"), "vram": pick(readings, "GPU", "VRAM em uso"),
                    "cpu_power": pick_power(readings, "CPU"), "gpu_power": pick_power(readings, "GPU"),
                }
                self._got_sig.emit(readings, snap)
            except Exception as e:  # noqa: BLE001
                if repr(e) != last_err:  # 1×/s: regista cada erro diferente só uma vez
                    last_err = repr(e)
                    logging.getLogger("nexo.sensors").exception("Falha a ler os sensores")
            # cadência fixa (não acumula atraso)
            nxt += self.INTERVAL
            delay = nxt - _t.monotonic()
            if delay < 0:
                nxt = _t.monotonic()
                delay = 0
            self._stop.wait(delay)
        reader.close()

    def _got(self, readings, snap):
        self.last = readings
        for k, v in snap.items():
            self.history[k].append(v)
        mm_all = self.minmax
        for r in readings:
            mm = mm_all.get(r.key)
            if mm is None:
                mm_all[r.key] = [r.value, r.value]
            elif r.value < mm[0]:
                mm[0] = r.value
            elif r.value > mm[1]:
                mm[1] = r.value
        if self._csv_writer is not None:
            self._write_csv(readings)
        from ..core.util import get_setting
        if get_setting("history"):
            self.record.add(snap)
        self._check_alerts(snap)
        self.updated.emit(readings)

    # ------------------------------------------------------------------ alertas
    def _check_alerts(self, snap):
        from ..core.util import get_setting
        import time as _t
        now = _t.monotonic()
        if get_setting("alert_ram"):
            self._check_ram(snap.get("ram"), float(get_setting("alert_ram_pct") or 92), now)
        if not get_setting("alerts"):
            return
        for key, name, lim in (("cpu_temp", "CPU", get_setting("alert_cpu")),
                               ("gpu_temp", "GPU", get_setting("alert_gpu"))):
            v = snap.get(key)
            if v is None or not lim:
                continue
            # dispara ao passar o limite; volta a armar quando desce 5 °C; no máximo 1 aviso / 5 min
            armed = self._alert_state.get(key + "_armed", 1.0)
            if v >= lim and armed and now - self._alert_state.get(key, -1e9) > 300:
                self._alert_state[key] = now
                self._alert_state[key + "_armed"] = 0.0
                self.alert.emit(f"Temperatura da {name} alta: {v:.0f} °C (limite {lim} °C)", "bad")
            elif v < lim - 5:
                self._alert_state[key + "_armed"] = 1.0

    RAM_SECONDS = 120

    def _check_ram(self, v, lim: float, now: float):
        """RAM acima do limite durante 2 minutos seguidos (picos curtos não contam);
        volta a armar quando desce 5 pontos; no máximo 1 aviso / 10 min."""
        if v is None:
            return
        if v >= lim:
            self._ram_high += 1
            if (self._ram_high == self.RAM_SECONDS and self._alert_state.get("ram_armed", 1.0)
                    and now - self._alert_state.get("ram", -1e9) > 600):
                self._alert_state["ram"] = now
                self._alert_state["ram_armed"] = 0.0
                self.alert.emit(f"Memória RAM quase cheia ({v:.0f} %) há 2 minutos. Feche programas que não "
                                "estejam a ser usados (página Processos ou Otimização).", "warn")
        else:
            self._ram_high = 0
            if v < lim - 5:
                self._alert_state["ram_armed"] = 1.0

    # ------------------------------------------------------------------ CSV
    def start_csv(self, path: str) -> None:
        import csv
        self.stop_csv()
        self._csv = open(path, "w", newline="", encoding="utf-8")
        self._csv_writer = csv.writer(self._csv, delimiter=";")
        self._csv_cols = []
        self.csv_path = path

    def stop_csv(self) -> None:
        if self._csv is not None:
            try:
                self._csv.close()
            except OSError:
                pass
        self._csv = self._csv_writer = None
        self.csv_path = None

    def _write_csv(self, readings):
        import time as _t
        vals = {f"{r.group}/{r.name} ({r.unit})": r.value for r in readings}
        if not self._csv_cols:
            self._csv_cols = list(vals)
            self._csv_writer.writerow(["Hora", *self._csv_cols])
        try:
            self._csv_writer.writerow([_t.strftime("%Y-%m-%d %H:%M:%S"),
                                       *(f"{vals[c]:.2f}" if c in vals else "" for c in self._csv_cols)])
            self._csv.flush()
        except (OSError, ValueError):
            self.stop_csv()

    # ------------------------------------------------------------------
    def latest(self, key: str):
        d = self.history.get(key)
        return d[-1] if d else None

    def close(self):
        self._stop.set()
        self.stop_csv()
        try:
            self.record.close()
        except Exception:  # noqa: BLE001
            logging.getLogger("nexo.history").exception("Falha a fechar o histórico")
