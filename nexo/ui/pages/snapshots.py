"""Página «Snapshots» (só Linux): ver, criar e apagar snapshots do snapper/Timeshift e abrir o restauro."""
from __future__ import annotations

import subprocess

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem

from ...core import snapshot as snap
from ...core.util import human_bytes
from ..widgets import Card, Page, StatTile, Tip, confirm, hbox, label, notify, run_async


class SnapshotsPage(Page):
    def __init__(self):
        super().__init__("Snapshots", "Fotografias do sistema para voltar atrás quando uma atualização ou um ajuste "
                         "corre mal. Com btrfs são instantâneas e só ocupam o que mudou desde então.")
        self.btn_load = QPushButton("Ver snapshots")
        self.btn_load.setToolTip("A lista só pode ser lida pelo administrador: pede a palavra-passe.")
        self.btn_load.clicked.connect(self.load)
        self.head.addWidget(self.btn_load)

        top = Card("Estado", icon="shield")
        row = hbox()
        self.t_backend = StatTile("Sistema de snapshots", snap.backend_label(), "")
        self.t_count = StatTile("Snapshots", "—", "carregue em «Ver snapshots»")
        self.t_nexo = StatTile("Criados pelo Nexo", "—", "")
        for t in (self.t_backend, self.t_count, self.t_nexo):
            row.addWidget(t, 1)
        top.add(row)
        b = snap.backend()
        if b not in ("snapper", "timeshift"):
            top.add(Tip(snap.setup_hint(), "warn"))
        else:
            top.add(label(snap.how_to_restore(b), "Muted", wrap=True))
        self.add(top)

        new = Card("Criar snapshot", "Antes de mexer no sistema por conta própria (instalar drivers, mudar "
                   "configurações, atualizar o kernel).", icon="sparkle")
        self.desc = QLineEdit()
        self.desc.setPlaceholderText("Descrição (ex.: antes de instalar o driver da NVIDIA)")
        self.desc.setMaxLength(80)
        self.btn_new = QPushButton("Criar agora")
        self.btn_new.setObjectName("Primary")
        self.btn_new.clicked.connect(self._create)
        new.add(hbox(self.desc, self.btn_new))
        self.add(new)

        lst = Card("Snapshots existentes", "Os mais recentes primeiro. «pre/post» são criados aos pares antes e "
                   "depois de cada atualização (snap-pac).", icon="list")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["N.º", "Data", "Descrição", "Tipo", "Espaço"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        for c in (0, 1, 3, 4):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setAlternatingRowColors(True)
        self.table.setMinimumHeight(300)
        self.table.itemSelectionChanged.connect(self._sel_changed)
        lst.add(self.table, 1)
        self.btn_del = QPushButton("Apagar selecionados")
        self.btn_del.setEnabled(False)
        self.btn_del.clicked.connect(self._delete)
        tool = snap.restore_tool()
        self.btn_restore = QPushButton(f"Restaurar no {tool[1]}…" if tool else "Como restaurar")
        self.btn_restore.setToolTip("Restaurar troca o sistema pelo snapshot e precisa de reiniciar — é feito na "
                                    "ferramenta própria, onde pode ver cada snapshot antes de escolher.")
        self.btn_restore.clicked.connect(self._restore)
        lst.add(hbox(self.btn_del, None, self.btn_restore))
        self.add(lst, 1)
        self._snaps: list[snap.Snap] = []
        self._busy = False
        if b not in ("snapper", "timeshift"):
            for w in (self.btn_load, self.btn_new, self.desc, self.btn_del):
                w.setEnabled(False)

    def on_show(self):
        pass   # a lista pede a palavra-passe: só quando o utilizador carregar em «Ver snapshots»

    def load(self):
        if self._busy:
            return
        self._busy = True
        self.btn_load.setEnabled(False)

        def done(res):
            self._busy = False
            self.btn_load.setEnabled(True)
            ok, items, err = res
            if not ok:
                notify(err, "bad")
                return
            self._fill(items)

        def fail(m):
            self._busy = False
            self.btn_load.setEnabled(True)
            notify(m, "bad")
        run_async(snap.list_all, on_done=done, on_fail=fail)

    def _fill(self, items: list[snap.Snap]):
        self._snaps = items
        self.t_count.set(str(len(items)), "")
        mine = [s for s in items if s.by_nexo]
        self.t_nexo.set(str(len(mine)), f"último: {mine[0].date}" if mine else "")
        self.table.setRowCount(len(items))
        for r, s in enumerate(items):
            for c, txt in enumerate((s.id, s.date, s.desc or "—", s.kind,
                                     human_bytes(s.size) if s.size is not None else "—")):
                it = QTableWidgetItem(txt)
                if c in (0, 4):
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.table.setItem(r, c, it)
        if not items:
            notify("Ainda não há snapshots.", "info")

    def _selected(self) -> list[snap.Snap]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self._snaps[r] for r in rows if r < len(self._snaps)]

    def _sel_changed(self):
        self.btn_del.setEnabled(bool(self._selected()))

    def _create(self):
        desc = self.desc.text().strip()
        self.btn_new.setEnabled(False)

        def done(res):
            self.btn_new.setEnabled(True)
            ok, msg = res
            notify(msg, "ok" if ok else "bad")
            if ok:
                self.desc.clear()
                if self._snaps:
                    self.load()

        def fail(m):
            self.btn_new.setEnabled(True)
            notify(m, "bad")
        run_async(snap.create, "snapshot manual", ("Nexo: " + desc) if desc else None, on_done=done, on_fail=fail)

    def _delete(self):
        sel = self._selected()
        if not sel:
            return
        names = ", ".join(s.id for s in sel[:8]) + (" …" if len(sel) > 8 else "")
        if not confirm(self, "Apagar snapshots", f"Apagar {len(sel)} snapshot(s) ({names})? Deixa de ser possível "
                       "voltar a esses pontos. O sistema atual não é alterado."):
            return

        def done(res):
            ok, msg = res
            notify(msg, "ok" if ok else "bad")
            if ok:
                self.load()
        run_async(snap.delete, [s.id for s in sel], on_done=done, on_fail=lambda m: notify(m, "bad"))

    def _restore(self):
        tool = snap.restore_tool()
        if tool is None:
            notify(snap.how_to_restore() or snap.setup_hint(), "info")
            return
        try:
            subprocess.Popen(tool[0], start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            notify(f"Abri o {tool[1]}. Escolha o snapshot e siga os passos — no fim reinicie o PC.", "info")
        except OSError as e:
            notify(f"Não foi possível abrir o {tool[1]}: {e}", "bad")
