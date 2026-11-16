"""Página "Bateria" (só aparece em portáteis): saúde, ciclos, carga e consumo."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ...core import battery
from ..widgets import Card, Page, Ring, StatTile, Tip, hbox, label, run_async


def _cap(v: float, unit: str) -> str:
    return f"{v:.1f} {unit}".replace(".", ",") if unit == "Wh" else f"{v:.0f} {unit}"


class BatteryPage(Page):
    def __init__(self):
        super().__init__("Bateria", "Quanto a bateria ainda aguenta comparada com quando era nova, ciclos de carga "
                         "e consumo atual.")
        self.btn = QPushButton("Atualizar")
        self.btn.clicked.connect(self.load)
        self.head.addWidget(self.btn)
        holder = QWidget()
        holder.setObjectName("Transparent")
        self.box = QVBoxLayout(holder)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.add(holder)
        self.add(Tip("Para a bateria durar mais anos: evite calor (portátil em cima de almofadas, sol), não a deixe "
                     "muitas vezes a 0 % e, se ficar quase sempre ligado à corrente, ative o limite de carga "
                     "(80 %) — muitos fabricantes têm essa opção no BIOS ou na aplicação deles."))
        self.body.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.load)

    def on_show(self):
        self.load()
        self._timer.start(30_000)

    def on_hide(self):
        self._timer.stop()

    def load(self):
        run_async(battery.batteries, on_done=self._render)

    def _render(self, bats: list[battery.Battery]):
        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w:
                w.deleteLater()
        if not bats:
            self.box.addWidget(Tip("Não foi encontrada nenhuma bateria — este PC trabalha só ligado à corrente."))
            return
        for b in bats:
            title = " ".join(x for x in (b.manufacturer, b.model) if x) or b.name
            card = Card(title, b.technology or None, icon="battery")
            row = hbox(spacing=16)
            h = b.health_pct
            kind, why = b.verdict()
            ring = Ring()
            ring.set(h or 0, f"{h:.0f} %" if h is not None else "—", "saúde", kind)
            row.addWidget(ring)
            tiles = hbox()
            t1 = StatTile("Capacidade", _cap(b.full, b.unit) if b.full else "—",
                          f"de {_cap(b.design, b.unit)} quando nova" if b.design else "")
            t2 = StatTile("Ciclos de carga", str(b.cycles) if b.cycles else "—",
                          "não indicado pelo sistema" if not b.cycles else "a maioria aguenta 500–1000")
            t3 = StatTile("Carga agora", f"{b.percent:.0f} %" if b.percent is not None else "—", b.status)
            pw = f"{b.power_w:.1f} W".replace(".", ",") if b.power_w else "—"
            t4 = StatTile("Consumo" if b.status != "A carregar" else "A carregar a", pw, "")
            for t in (t1, t2, t3, t4):
                tiles.addWidget(t, 1)
            row.addLayout(tiles, 1)
            card.add(row)
            card.add(label(why, wrap=True))
            if b.wear_pct is not None and b.power_w and b.status == "A descarregar" and b.full:
                hours = b.full * (b.percent or 100) / 100 / b.power_w if b.unit == "Wh" else None
                if hours:
                    card.add(label(f"Com o consumo atual, a carga dá para cerca de {hours:.1f} h."
                                   .replace(".", ",", 1), "Muted"))
            self.box.addWidget(card)
