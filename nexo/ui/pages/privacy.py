"""Privacidade (só Linux): o equivalente ao Windows debloat para o que existe nas distribuições."""
from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from ...core import privacy_linux as pl
from ..widgets import Card, Page, confirm, label, notify, run_async
from .optimize import TweakList


class PrivacyPage(Page):
    def __init__(self):
        super().__init__("Privacidade", "O Linux não tem a telemetria do Windows, mas o ambiente de trabalho e a "
                                        "distribuição podem guardar histórico ou enviar estatísticas. Tudo reversível.")
        items = pl.linux_privacy_tweaks()
        self.list = TweakList("Recolha de dados", "Só aparece o que existe neste sistema.", items)
        self.add(self.list)
        if not items:
            self.list.add(label("Nada para ajustar: este sistema não envia telemetria nem estatísticas.", "Muted"))
        hist = Card("Histórico de ficheiros recentes", "Lista dos ficheiros que abriu, usada pelos menus "
                    "\"Recentes\" das aplicações e do ambiente de trabalho.", icon="clock")
        self.btn_clear = QPushButton("Apagar histórico")
        self.btn_clear.clicked.connect(self._clear)
        hist.head.addWidget(self.btn_clear)
        self.hist_info = label("", "Muted", wrap=True)
        hist.add(self.hist_info)
        self.add(hist)
        self.body.addStretch(1)

    def on_show(self):
        self.list.refresh()
        n = len(pl.recent_files())
        self.hist_info.setText(f"{n} ficheiro(s) de histórico encontrados." if n else
                               "Não há ficheiros de histórico do GTK/KDE (o Plasma pode ter o seu próprio, "
                               "que também é apagado).")

    def _clear(self):
        if not confirm(self, "Apagar histórico", "Apagar o histórico de ficheiros recentes? Os ficheiros em si não "
                       "são tocados — só deixam de aparecer em \"Recentes\"."):
            return

        def done(r):
            ok, msg = r
            notify(msg, "ok" if ok else "warn")
            self.on_show()
        run_async(pl.clear_recent, on_done=done)



