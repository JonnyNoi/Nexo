"""Cartão "Tempo de arranque" (página Arranque): último arranque, fases, evolução e o que o atrasa."""
from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from ..core import boottime
from ..core.util import IS_WIN, is_admin
from . import theme
from .widgets import Card, StatTile, Tip, hbox, label, run_async


def _n(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


class BootBars(QWidget):
    """Barras dos últimos arranques (o mais recente à direita); dica com a data e o tempo."""

    def __init__(self):
        super().__init__()
        self.boots: list[boottime.Boot] = []
        self.setMinimumHeight(70)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setAccessibleName("Tempo dos últimos arranques")

    def set_boots(self, boots: list[boottime.Boot]):
        self.boots = boots[-30:]
        if self.boots:
            self.setAccessibleDescription(", ".join(f"{_n(b.total)} s" for b in self.boots[-5:]))
        self.update()

    def _geom(self):
        n = max(1, len(self.boots))
        gap = 3.0
        w = min(26.0, (self.width() - gap * (n - 1)) / n)
        return w, gap

    def mouseMoveEvent(self, e):
        w, gap = self._geom()
        i = int(e.position().x() // (w + gap))
        if 0 <= i < len(self.boots):
            b = self.boots[i]
            self.setToolTip(f"{time.strftime('%d/%m %H:%M', time.localtime(b.when))}: {_n(b.total)} s")

    def paintEvent(self, _e):
        if not self.boots:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, gap = self._geom()
        top = max(b.total for b in self.boots) or 1
        h = self.height() - 4
        for i, b in enumerate(self.boots):
            bh = max(3.0, h * b.total / top)
            kind = "warn" if b.total >= boottime.SLOW_TOTAL else "accent"
            p.setPen(Qt.NoPen)
            p.setBrush(theme.qc(kind, 255 if i == len(self.boots) - 1 else 140))
            p.drawRoundedRect(QRectF(i * (w + gap), self.height() - bh, w, bh), 3, 3)
        p.end()


class BootCard(Card):
    def __init__(self):
        super().__init__("Tempo de arranque", "Quanto o PC demorou a arrancar e o que o atrasou — guardado a cada "
                         "arranque, para ver se desativar programas abaixo ajudou mesmo.", icon="clock")
        row = hbox()
        self.t_total = StatTile("Último arranque", "—", "")
        self.t_a = StatTile("BIOS/UEFI" if not IS_WIN else "Até ao ambiente de trabalho", "—", "")
        self.t_b = StatTile("Sistema" if not IS_WIN else "Depois do início de sessão", "—", "")
        for t in (self.t_total, self.t_a, self.t_b):
            row.addWidget(t, 1)
        self.add(row)
        self.bars = BootBars()
        self.add(self.bars)
        self.trend = label("", "Muted", wrap=True)
        self.add(self.trend)
        self.delays = label("", wrap=True)
        self.delays.setTextFormat(Qt.RichText)
        self.add(self.delays)
        holder = QWidget()
        holder.setObjectName("Transparent")
        self.tips = QVBoxLayout(holder)
        self.tips.setContentsMargins(0, 0, 0, 0)
        self.tips.setSpacing(8)
        self.add(holder)
        self._loaded = False

    def load(self):
        if IS_WIN and not is_admin():
            self._render(None, "O tempo de arranque vem do Visualizador de Eventos e só é legível como administrador "
                               "(botão Admin no menu).")
            return
        run_async(boottime.record, on_done=lambda b: self._render(b), on_fail=lambda m: self._render(None, m))

    def _render(self, boot, msg: str = ""):
        hist = boottime.history()
        boot = boot or (hist[-1] if hist else None)
        while self.tips.count():
            w = self.tips.takeAt(0).widget()
            if w:
                w.deleteLater()
        if boot is None:
            self.t_total.set("—", "")
            self.trend.setText(msg or "Ainda sem dados (o sistema pode estar a terminar o arranque — tente daqui a "
                                      "um minuto).")
            self.delays.setText("")
            return
        self.t_total.set(f"{_n(boot.total)} s", time.strftime("%d/%m %H:%M", time.localtime(boot.when)),
                         "warn" if boot.total >= boottime.SLOW_TOTAL else None)
        ph = boot.phases
        if IS_WIN:
            self.t_a.set(f"{_n(ph['main'])} s" if "main" in ph else "—", "")
            self.t_b.set(f"{_n(ph['post'])} s" if "post" in ph else "—", "")
        else:
            fw = ph.get("firmware", 0)
            sub = (f"+ carregador {_n(ph['loader'])} s" if ph.get("loader") else "antes do sistema") if fw else \
                "não indicado (arranque sem UEFI)"
            self.t_a.set(f"{_n(fw)} s" if fw else "—", sub, "warn" if fw >= boottime.SLOW_FIRMWARE else None)
            sys_t = sum(ph.get(k, 0) for k in ("kernel", "initrd", "userspace"))
            self.t_b.set(f"{_n(sys_t)} s", " · ".join(f"{boottime.PHASE_NAMES[k]} {_n(ph[k])} s"
                                                      for k in ("kernel", "initrd", "userspace") if k in ph))
        self.bars.set_boots(hist)
        self.bars.setVisible(len(hist) >= 2)
        tr = boottime.trend(hist)
        self.trend.setText(("Este arranque: " + tr.text()) if tr and tr.baseline is not None else
                           "A evolução aparece depois de mais alguns arranques.")
        if boot.delays:
            items = "".join(f"<li>{d.name} — <b>{_n(d.seconds)} s</b>"
                            + (f" <span style='color:{theme.C['muted']}'>({d.kind})</span>" if IS_WIN else "")
                            + "</li>" for d in boot.delays[:6])
            head = ("O que tornou o arranque mais lento (últimos 30 dias):" if IS_WIN else
                    "O que atrasou o arranque (cadeia crítica):")
            self.delays.setText(f"{head}<ul style='margin:4px 0'>{items}</ul>")
        else:
            self.delays.setText("")
        for kind, text in boottime.advice(boot):
            if kind != "ok":
                self.tips.addWidget(Tip(text, kind))
