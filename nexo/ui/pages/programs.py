"""Página "Programas instalados": tudo o que está instalado (não só o catálogo), com tamanho e desinstalar."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidget,
                               QTableWidgetItem)

from ...core import changes, programs
from ...core.util import IS_WIN, human_bytes
from ..widgets import Card, Page, label, notify, run_async
from ..widgets import confirm as ask


class _Num(QTableWidgetItem):
    """Célula que ordena pelo valor numérico (tamanho, data) e não pelo texto."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        self.value = value

    def __lt__(self, other):
        return self.value < getattr(other, "value", 0)


class ProgramsPage(Page):
    def __init__(self):
        super().__init__("Programas instalados", "Tudo o que está instalado no PC, com o espaço que ocupa. "
                         "Desinstale o que já não usa." + ("" if IS_WIN else
                                                          " Componentes essenciais do sistema ficam protegidos."))
        self.btn = QPushButton("Atualizar")
        self.btn.clicked.connect(self.load)
        self.head.addWidget(self.btn)
        card = Card()
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Procurar por nome, editor ou descrição…")
        self.search.textChanged.connect(self._filter)
        top.addWidget(self.search, 1)
        self.source = QComboBox()
        self.source.addItem("Todas as origens", "")
        self.source.currentIndexChanged.connect(self._filter)
        self.source.setAccessibleName("Origem")
        top.addWidget(self.source)
        self.only_apps = QCheckBox("Só aplicações" if not IS_WIN else "Esconder componentes")
        self.only_apps.setToolTip("Esconde bibliotecas, ferramentas de linha de comandos e componentes sem "
                                  "entrada no menu de aplicações.")
        self.only_apps.setChecked(True)
        self.only_apps.toggled.connect(self._filter)
        top.addWidget(self.only_apps)
        self.count = label("", "Muted")
        top.addWidget(self.count)
        card.add(top)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Nome", "Versão", "Tamanho", "Instalado", "Origem"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 150), (2, 100), (3, 100), (4, 100)):
            self.table.setColumnWidth(c, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(36)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setMinimumHeight(420)
        self.table.itemSelectionChanged.connect(self._sel_changed)
        card.add(self.table, 1)
        bottom = QHBoxLayout()
        self.detail = label("", "Muted", wrap=True)
        bottom.addWidget(self.detail, 1)
        self.btn_rm = QPushButton("Desinstalar")
        self.btn_rm.setObjectName("Danger")
        self.btn_rm.setEnabled(False)
        self.btn_rm.clicked.connect(self._uninstall)
        bottom.addWidget(self.btn_rm)
        card.add(bottom)
        card.add(label("Windows: abre o desinstalador do próprio programa — siga os passos dele." if IS_WIN else
                       "Pacotes do sistema pedem a palavra-passe; Flatpak não. Remover um pacote também remove as "
                       "dependências que deixaram de ser precisas.", "Muted", wrap=True))
        self.add(card, 1)
        self.items: list[programs.Program] = []
        self._loaded = False
        self._busy = False

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        self.count.setText("A ler…")
        self.btn.setEnabled(False)
        run_async(programs.list_programs, on_done=self._show, on_fail=self._fail)

    def _fail(self, msg):
        self.btn.setEnabled(True)
        self.count.setText("")
        notify(f"Não foi possível ler os programas instalados: {msg}", "bad")

    def _show(self, items: list[programs.Program]):
        self.btn.setEnabled(True)
        self.items = items
        cur = self.source.currentData()
        self.source.blockSignals(True)
        self.source.clear()
        self.source.addItem("Todas as origens", "")
        for s in sorted({p.source for p in items}):
            self.source.addItem(s, s)
        i = self.source.findData(cur)
        self.source.setCurrentIndex(max(0, i))
        self.source.blockSignals(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(items))
        for r, p in enumerate(items):
            n = QTableWidgetItem(p.name + ("   · protegido" if p.protected else ""))
            n.setData(Qt.UserRole, r)
            tip = "\n".join(x for x in (p.description, p.publisher) if x)
            if tip:
                n.setToolTip(tip)
            if p.protected:
                n.setForeground(Qt.gray)
            self.table.setItem(r, 0, n)
            self.table.setItem(r, 1, QTableWidgetItem(p.version))
            self.table.setItem(r, 2, _Num(human_bytes(p.size) if p.size else "—", p.size))
            self.table.setItem(r, 3, _Num(time.strftime("%d/%m/%Y", time.localtime(p.installed)) if p.installed
                                          else "—", p.installed))
            self.table.setItem(r, 4, QTableWidgetItem(p.source))
        self.table.setSortingEnabled(True)
        self.table.sortItems(2, Qt.DescendingOrder)
        self._filter()

    def _filter(self, *_):
        text = self.search.text().strip().lower()
        src = self.source.currentData() or ""
        only = self.only_apps.isChecked()
        shown, size = 0, 0
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            if it is None:
                continue
            p = self.items[it.data(Qt.UserRole)]
            hide = bool((src and p.source != src) or (only and not p.is_app)
                        or (text and text not in f"{p.name} {p.publisher} {p.description}".lower()))
            self.table.setRowHidden(r, hide)
            if not hide:
                shown += 1
                size += p.size
        self.count.setText(f"{shown} de {len(self.items)} · {human_bytes(size)}")

    def _current(self) -> programs.Program | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        it = self.table.item(rows[0].row(), 0)
        return self.items[it.data(Qt.UserRole)] if it else None

    def _sel_changed(self):
        p = self._current()
        self.btn_rm.setEnabled(bool(p and not p.protected and not self._busy))
        if not p:
            self.detail.setText("")
            return
        bits = [p.description, p.publisher and f"de {p.publisher}", p.ident if p.source == "Flatpak" else ""]
        self.detail.setText(" · ".join(b for b in bits if b))

    def _uninstall(self):
        p = self._current()
        if not p or self._busy:
            return
        if not ask(self, "Desinstalar", f"Desinstalar «{p.name}»?"
                   + (f"\n\nLiberta cerca de {human_bytes(p.size)}." if p.size else "")):
            return
        self._busy = True
        self.btn_rm.setEnabled(False)
        self.btn_rm.setText("A desinstalar…")

        def done(res):
            ok, msg = res
            self._busy = False
            self.btn_rm.setText("Desinstalar")
            notify(msg, "ok" if ok else "bad")
            if ok:
                changes.mark("limpeza", f"Desinstalou «{p.name}»")
                self.load()
            else:
                self._sel_changed()

        def fail(m):
            self._busy = False
            self.btn_rm.setText("Desinstalar")
            notify(f"Falhou: {m}", "bad")
            self._sel_changed()
        run_async(programs.uninstall, p, on_done=done, on_fail=fail)
