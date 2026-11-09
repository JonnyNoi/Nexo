from __future__ import annotations

import html
import json
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QHeaderView, QListWidget, QPushButton, QTableWidget,
                               QTableWidgetItem)

from ...core import sysinfo
from ...core.util import APP_NAME, APP_VERSION
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
            with open(path, "w", encoding="utf-8") as f:
                json.dump({k: dict(v) for k, v in self.data.items()}, f, indent=2, ensure_ascii=False)
        else:
            if not path.endswith(".html"):
                path += ".html"
            parts = [f"<!doctype html><meta charset='utf-8'><title>Relatório {APP_NAME}</title>"
                     "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:40px auto;padding:0 16px;"
                     "background:#0e1014;color:#e7e9ee}h1{color:#ff6b3d}h2{border-bottom:1px solid #2a2f3b;padding-bottom:6px}"
                     "table{width:100%;border-collapse:collapse}td{padding:6px 8px;border-bottom:1px solid #1e222b;vertical-align:top}"
                     "td:first-child{color:#8a92a6;width:35%}</style>",
                     f"<h1>{APP_NAME} — relatório do sistema</h1><p>Gerado em {time.strftime('%d/%m/%Y %H:%M')} "
                     f"pelo {APP_NAME} {APP_VERSION}</p>"]
            for cat, rows in self.data.items():
                parts.append(f"<h2>{html.escape(cat)}</h2><table>")
                parts += [f"<tr><td>{html.escape(k)}</td><td>{html.escape(str(v))}</td></tr>" for k, v in rows]
                parts.append("</table>")
            with open(path, "w", encoding="utf-8") as f:
                f.write("".join(parts))
        notify(f"Relatório guardado em {path}", "ok")
