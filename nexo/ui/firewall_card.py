"""Cartão "Firewall e portas abertas" (página Internet)."""
from __future__ import annotations

from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QHeaderView, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import firewall as fw
from ..core.util import IS_WIN
from .widgets import Card, StatTile, Tip, confirm, hbox, notify, run_async


class FirewallCard(Card):
    def __init__(self):
        super().__init__("Firewall e portas abertas", "Se o PC aceita ligações de outros aparelhos da rede e que "
                         "programas estão à espera delas.", icon="shield")
        row = hbox()
        self.t_fw = StatTile("Firewall", "—", "")
        self.t_open = StatTile("Abertas para a rede", "—", "")
        self.t_local = StatTile("Só neste PC", "—", "")
        for t in (self.t_fw, self.t_open, self.t_local):
            row.addWidget(t, 1)
        self.add(row)
        holder = QWidget()
        holder.setObjectName("Transparent")
        self.tips = QVBoxLayout(holder)
        self.tips.setContentsMargins(0, 0, 0, 0)
        self.tips.setSpacing(8)
        self.add(holder)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Porta", "Protocolo", "Serviço", "Programa", "Quem pode ligar-se"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setMinimumHeight(200)
        self.add(self.table)
        bh = QHBoxLayout()
        self.btn = QPushButton("Verificar")
        self.btn.clicked.connect(self.load)
        self.btn_on = QPushButton("Ligar a firewall")
        self.btn_on.setObjectName("Primary")
        self.btn_on.clicked.connect(self._enable)
        self.btn_on.hide()
        bh.addWidget(self.btn)
        bh.addWidget(self.btn_on)
        bh.addStretch(1)
        self.add(bh)
        self._busy = False
        self._st: fw.FwStatus | None = None

    def load(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)

        def done(res):
            self._busy = False
            self.btn.setEnabled(True)
            self._render(res)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            notify(f"Não foi possível verificar a firewall: {m}", "warn")
        run_async(fw.scan, on_done=done, on_fail=fail)

    def _render(self, res: dict):
        st: fw.FwStatus = res["status"]
        ports: list[fw.Port] = res["ports"]
        self._st = st
        while self.tips.count():
            w = self.tips.takeAt(0).widget()
            if w:
                w.deleteLater()
        if st.active is None:
            self.t_fw.set("?", "não foi possível ler")
        else:
            self.t_fw.set("Ligada" if st.active else "Desligada", st.name or st.detail,
                          "ok" if st.active else "bad")
        exposed = [p for p in ports if p.exposed]
        self.t_open.set(str(len(exposed)), "portas (TCP/UDP)", "warn" if exposed and st.active is False else None)
        self.t_local.set(str(len(ports) - len(exposed)), "portas só para o próprio PC")
        for kind, text in fw.analyze(st, ports):
            self.tips.addWidget(Tip(text, kind))
        self.btn_on.setVisible(st.active is False)
        self.btn_on.setText("Instalar e ligar a firewall" if st.active is False and not st.installed
                            and not IS_WIN else "Ligar a firewall")
        self.table.setRowCount(len(ports))
        for i, p in enumerate(ports):
            who = "Outros aparelhos da rede" if p.exposed else "Só este PC"
            for j, v in enumerate((str(p.port), p.proto, p.service or "—", p.process or "(sistema)", who)):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def _enable(self):
        st = self._st
        if st is None:
            return
        extra = ("" if IS_WIN else "\n\nA firewall passa a bloquear as ligações que chegam de fora. Se usar partilha "
                 "de ficheiros, KDE Connect ou Steam Remote Play pode ter de os autorizar depois.")
        if not confirm(self, "Ligar a firewall", f"Ligar a firewall{(' (' + st.name + ')') if st.name else ''}?"
                       + extra):
            return
        self.btn_on.setEnabled(False)

        def done(r):
            ok, msg = r
            self.btn_on.setEnabled(True)
            notify(msg, "ok" if ok else "bad")
            self.load()
        run_async(fw.enable, st, on_done=done, on_fail=lambda m: (self.btn_on.setEnabled(True), notify(m, "bad")))
