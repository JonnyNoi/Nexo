from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QListWidget, QPushButton, QTableWidget,
                               QTableWidgetItem)

from ...core import sysinfo
from ..widgets import Card, Page, label, notify, run_async


class SystemPage(Page):
    def __init__(self):
        super().__init__("Informação do sistema", "Sistema operativo, processador, memória, placa gráfica, placa-mãe, discos e rede")
        self.data: dict = {}
        self.btn_refresh = QPushButton("Atualizar")
        self.btn_export = QPushButton("Exportar relatório")
        self.btn_export.setObjectName("Primary")
        self.head.addWidget(self.btn_refresh)
        self.head.addWidget(self.btn_export)
        self.btn_refresh.clicked.connect(self.load)
        self.btn_export.clicked.connect(self.export)

        row = QHBoxLayout()
        row.setSpacing(16)
        left = Card()
        self.cats = QListWidget()
        self.cats.setFixedWidth(200)
        self.cats.setStyleSheet("QListWidget::item { padding: 8px; border-radius: 6px; }")
        left.add(self.cats)
        right = Card()
        self.title = label("A recolher informações…", "CardTitle")
        right.add(self.title)
        self.table = QTableWidget(0, 2)
        self.table.horizontalHeader().setVisible(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setWordWrap(True)
        right.add(self.table, 1)
        row.addWidget(left)
        row.addWidget(right, 1)
        self.add(row, 1)
        self.cats.currentTextChanged.connect(self.show_cat)
        self.setMinimumHeight(400)
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        self.title.setText("A recolher informações…")
        self.btn_refresh.setEnabled(False)
        run_async(sysinfo.collect, on_done=self._done)

    def _done(self, data):
        self.btn_refresh.setEnabled(True)
        self.data = data
        cur = self.cats.currentItem().text() if self.cats.currentItem() else None
        self.cats.clear()
        self.cats.addItems(list(data))
        items = self.cats.findItems(cur, Qt.MatchExactly) if cur else []
        self.cats.setCurrentItem(items[0] if items else self.cats.item(0))

    def show_cat(self, name):
        rows = self.data.get(name, [])
        self.title.setText(name)
        self.table.setRowCount(len(rows))
        for i, (k, v) in enumerate(rows):
            a = QTableWidgetItem(k)
            a.setForeground(self.palette().placeholderText())
            self.table.setItem(i, 0, a)
            self.table.setItem(i, 1, QTableWidgetItem(str(v)))
        self.table.resizeRowsToContents()

    def export(self):
        if not self.data:
            return
        path, flt = QFileDialog.getSaveFileName(self, "Exportar relatório", f"relatorio-{time.strftime('%Y%m%d-%H%M')}.html",
                                                "HTML (*.html);;JSON (*.json)")
        if not path:
            return
        if path.endswith(".json") or "JSON" in flt:
            if not path.endswith(".json"):
                path += ".json"
            text = sysinfo.report_json(self.data)
        else:
            if not path.endswith(".html"):
                path += ".html"
            text = sysinfo.report_html(self.data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        notify(f"Relatório guardado em {path}", "ok")
