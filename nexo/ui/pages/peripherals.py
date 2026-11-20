"""Página "Periféricos": bateria de ratos, teclados, comandos e auscultadores sem fios, e Bluetooth."""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

from ...core import peripherals as per
from ..widgets import Card, Page, StatTile, Tip, hbox, label, run_async


class PeripheralsPage(Page):
    def __init__(self):
        super().__init__("Periféricos", "Bateria dos ratos, teclados, comandos e auscultadores sem fios, e estado "
                         "do Bluetooth. Avisa quando um deles está quase sem bateria.")
        self.btn = QPushButton("Atualizar")
        self.btn.clicked.connect(self.load)
        self.head.addWidget(self.btn)
        bt = Card("Bluetooth", icon="wifi")
        row = hbox()
        self.t_bt = StatTile("Adaptador", "—", "")
        self.t_conn = StatTile("Aparelhos ligados", "—", "")
        row.addWidget(self.t_bt, 1)
        row.addWidget(self.t_conn, 1)
        bt.add(row)
        self.bt_list = label("", "Muted", wrap=True)
        bt.add(self.bt_list)
        self.add(bt)
        tests = Card("Testes de periféricos", "Verifique se tudo funciona como deve — útil depois de comprar um "
                     "monitor, rato ou teclado novo (ainda dentro do prazo de devolução).", icon="sparkle")
        row2 = hbox()
        for txt, tip, fn in (("Ecrã", "Píxeis mortos ou presos, fugas de luz, degradê e ghosting (ecrã inteiro).",
                              self._screen),
                             ("Rato", "Polling rate, botões, roda e cliques duplos fantasma.", self._mouse),
                             ("Teclado", "Todas as teclas e quantas funcionam ao mesmo tempo.", self._keyboard),
                             ("Som e microfone", "Coluna esquerda/direita e nível do microfone.", self._audio)):
            b = QPushButton(txt)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            row2.addWidget(b, 1)
        tests.add(row2)
        self.add(tests)
        holder = QWidget()
        holder.setObjectName("Transparent")
        self.box = QVBoxLayout(holder)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(16)
        self.add(holder)
        self.body.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.load)
        self._busy = False

    # ------------------------------------------------------------------ testes
    def _screen(self):
        from ..periph_tests import ScreenTest
        self._screen_win = ScreenTest.run(self.window())

    def _mouse(self):
        from ..periph_tests import MouseTest
        MouseTest(self).exec()

    def _keyboard(self):
        from ..periph_tests import KeyboardTest
        KeyboardTest(self).exec()

    def _audio(self):
        from ..periph_tests import AudioTest
        AudioTest(self).exec()

    def on_show(self):
        self.load()
        self._timer.start(60_000)

    def on_hide(self):
        self._timer.stop()

    def load(self):
        if self._busy:
            return
        self._busy = True

        def done(res):
            self._busy = False
            self._render(*res)

        def fail(_m):
            self._busy = False
        run_async(per.scan, on_done=done, on_fail=fail)

    def _render(self, devs: list[per.Device], bt: per.Bluetooth):
        if not bt.present:
            self.t_bt.set("Não há", "este PC não tem Bluetooth")
        elif bt.blocked:
            self.t_bt.set("Bloqueado", "modo de avião ou interruptor do portátil", "warn")
        else:
            self.t_bt.set("Ligado" if bt.powered else "Desligado", bt.name, "ok" if bt.powered else None)
        self.t_conn.set(str(len(bt.connected)) if bt.powered else "—", "")
        self.bt_list.setText(" · ".join(bt.connected))
        self.bt_list.setVisible(bool(bt.connected))
        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w:
                w.deleteLater()
        card = Card("Bateria dos aparelhos sem fios", icon="battery")
        if not devs:
            card.add(label("Nenhum aparelho sem fios com bateria encontrado. Ratos e teclados com recetor USB "
                           "(Logitech, Razer…), comandos e auscultadores Bluetooth aparecem aqui quando estão ligados."
                           , "Muted", wrap=True))
        tiles = hbox()
        for i, d in enumerate(sorted(devs, key=lambda d: (d.percent if d.percent is not None else 101))):
            if i and i % 4 == 0:
                card.add(tiles)
                tiles = hbox()
            val = f"{d.percent} %" if d.percent is not None and not d.level else (d.level or "—").capitalize()
            sub = " · ".join(x for x in (d.kind, "a carregar" if d.charging else "") if x)
            kind = "bad" if d.low else "warn" if d.percent is not None and d.percent <= 30 and not d.charging else "ok"
            t = StatTile(d.name, val, sub)
            t.set(val, sub, kind)
            tiles.addWidget(t, 1)
        if devs:
            tiles.addStretch(1)
            card.add(tiles)
        low = per.low_battery(devs)
        if low:
            card.add(Tip("Quase sem bateria: " + ", ".join(d.name for d in low) + ". Carregue-os antes de jogar.",
                         "warn"))
        self.box.addWidget(card)
