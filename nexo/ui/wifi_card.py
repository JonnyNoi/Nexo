"""Cartão "Wi-Fi" (página Internet): sinal, banda, canal, redes vizinhas e conselhos."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..core import wifi
from . import theme
from .widgets import Card, StatTile, Tip, hbox, label, run_async


class WifiCard(Card):
    def __init__(self):
        super().__init__("Wi-Fi", "Qualidade do sinal e interferências das redes vizinhas — causas comuns de "
                         "internet lenta ou com cortes.", icon="wifi")
        row = hbox()
        self.t_sig = StatTile("Sinal", "—", "")
        self.t_band = StatTile("Banda e canal", "—", "")
        self.t_rate = StatTile("Ligação ao router", "—", "")
        self.t_near = StatTile("Redes à volta", "—", "")
        for t in (self.t_sig, self.t_band, self.t_rate, self.t_near):
            row.addWidget(t, 1)
        self.tiles = QWidget()
        self.tiles.setObjectName("Transparent")
        self.tiles.setLayout(row)
        self.add(self.tiles)
        self.msg = label("", "Muted", wrap=True)
        self.add(self.msg)
        holder = QWidget()
        holder.setObjectName("Transparent")
        self.tips = QVBoxLayout(holder)
        self.tips.setContentsMargins(0, 0, 0, 0)
        self.tips.setSpacing(8)
        self.add(holder)
        self.channels = label("", "Muted", wrap=True)
        self.channels.setTextFormat(Qt.RichText)
        self.add(self.channels)
        bh = QHBoxLayout()
        self.btn = QPushButton("Analisar Wi-Fi")
        self.btn.clicked.connect(self.load)
        bh.addWidget(self.btn)
        bh.addStretch(1)
        self.add(bh)
        self._busy = False

    def load(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)

        def done(st):
            self._busy = False
            self.btn.setEnabled(True)
            self._render(st)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            self.msg.setText(f"Não foi possível ler o Wi-Fi: {m}")
        run_async(wifi.state, on_done=done, on_fail=fail)

    def _render(self, st: wifi.WifiState):
        while self.tips.count():
            w = self.tips.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.tiles.setVisible(st.current is not None)
        self.msg.setText(st.message)
        self.msg.setVisible(bool(st.message))
        cur = st.current
        if cur is None:
            self.channels.setText("")
            return
        kind = "bad" if cur.signal < 30 else "warn" if cur.signal < 55 else None
        self.t_sig.set(f"{cur.signal} %", cur.ssid, kind)
        self.t_band.set(cur.band or "—", f"canal {cur.channel}" if cur.channel else "")
        self.t_rate.set(cur.rate or "—", cur.radio or cur.security)
        same = wifi.crowding(cur, st.nearby)
        self.t_near.set(str(sum(1 for n in st.nearby if not n.in_use)), f"{same} no mesmo canal" if same else
                        "nenhuma no mesmo canal")
        for k, text in wifi.analyze(st):
            if k != "ok":
                self.tips.addWidget(Tip(text, k))
        # ocupação dos canais de 2,4 GHz (1, 6, 11) — útil para escolher o canal do router
        if any(n.band.startswith("2") for n in st.nearby):
            load = {c: sum(1 for n in st.nearby if n.band.startswith("2") and abs(n.channel - c) < 5 and n.signal >= 30)
                    for c in (1, 6, 11)}
            best = wifi.best_24_channel(st.nearby, cur.ssid)
            parts = [f"{'<b>' if c == best else ''}canal {c}: {n} rede(s){'</b>' if c == best else ''}"
                     for c, n in load.items()]
            self.channels.setText(f"<span style='color:{theme.C['muted']}'>2,4 GHz — " + " · ".join(parts)
                                  + f" (o mais livre é o {best})</span>")
        else:
            self.channels.setText("")
