from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QHeaderView, QLineEdit, QPushButton, QTableWidget, QTableWidgetItem, QWidget

from ...core import startup
from ...core.util import IS_WIN
from ..widgets import Card, Page, Toggle, label, notify, run_async


class StartupPage(Page):
    def __init__(self):
        super().__init__("Arranque", "Programas que abrem sozinhos com o sistema. Desativar não desinstala nada "
                                     "e pode voltar a ativar a qualquer momento.")
        self.btn = QPushButton("Atualizar")
        self.head.addWidget(self.btn)
        self.btn.clicked.connect(self.load)
        card = Card()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar…")
        self.search.textChanged.connect(self._filter)
        self.count = label("", "Muted")
        top = QHBoxLayout()
        top.addWidget(self.search, 1)
        top.addWidget(self.count)
        card.add(top)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Ativo", "Nome", "Origem", "Comando"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 70)
        self.table.setColumnWidth(1, 240)
        self.table.setColumnWidth(2, 180)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(40)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        card.add(self.table, 1)
        hint = ("Itens de \"HKLM\" e da pasta Arranque (todos) são de todos os utilizadores e precisam de administrador."
                if IS_WIN else "Itens do sistema (/etc/xdg/autostart) são desativados só para o seu utilizador. "
                               "Serviços systemd --user aplicam-se no próximo início de sessão.")
        card.add(label(hint, "Muted", wrap=True))
        self.add(card, 1)
        self.items: list = []
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        run_async(startup.list_items, on_done=self._show)

    def _show(self, items):
        self.items = items
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            tg = Toggle(it.enabled)
            if it.essential:
                tg.setEnabled(False)
                tg.setToolTip("Componente essencial do ambiente gráfico — desativar pode partir a sessão.")
            w = QWidget()
            w.setObjectName("Transparent")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(12, 0, 0, 0)
            lay.addWidget(tg)
            tg.clicked.connect(lambda on, it=it, tg=tg: self._set(it, tg, on))
            self.table.setCellWidget(i, 0, w)
            n = QTableWidgetItem(it.name + ("   · essencial" if it.essential else ""))
            if it.essential:
                n.setForeground(Qt.gray)
            self.table.setItem(i, 1, n)
            self.table.setItem(i, 2, QTableWidgetItem(it.source))
            c = QTableWidgetItem(it.command)
            c.setToolTip(it.command)
            self.table.setItem(i, 3, c)
        on = sum(1 for x in items if x.enabled)
        self.count.setText(f"{on} ativos de {len(items)}")
        self._filter(self.search.text())

    def _filter(self, text):
        q = text.lower().strip()
        for i, it in enumerate(self.items):
            self.table.setRowHidden(i, bool(q) and q not in it.name.lower() and q not in it.command.lower())

    def _set(self, item, tg, on):
        ok, msg = startup.set_enabled(item, on)
        if ok:
            item.enabled = on
            from ...core import changes
            changes.mark("arranque", f"{'Ativou' if on else 'Desativou'} «{item.name}» no arranque")
        else:
            tg.setChecked(not on)
        notify(f"{item.name}: {'ativado' if on else 'desativado'} — {msg}" if ok else f"{item.name}: {msg}",
               "ok" if ok else "bad")
        self.count.setText(f"{sum(1 for x in self.items if x.enabled)} ativos de {len(self.items)}")
