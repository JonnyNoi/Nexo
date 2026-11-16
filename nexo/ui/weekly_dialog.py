"""Janela "Relatório da semana" (Visão geral → botão, ou a partir do alerta semanal)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core import weekly
from . import theme
from .widgets import icon_badge, label, notify, run_async


class WeeklyDialog(QDialog):
    def __init__(self, parent=None, report: weekly.Report | None = None):
        super().__init__(parent)
        self.setWindowTitle("Relatório da semana")
        self.resize(640, 520)
        self.report = report
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        self.title = label("", "CardTitle")
        v.addWidget(self.title)
        self.period = label("", "Muted")
        v.addWidget(self.period)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        inner.setObjectName("Transparent")
        self.rows = QVBoxLayout(inner)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(8)
        self.rows.addStretch(1)
        scroll.setWidget(inner)
        v.addWidget(scroll, 1)
        bh = QHBoxLayout()
        self.btn_new = QPushButton("Gerar agora")
        self.btn_new.setToolTip("Calcula o relatório dos últimos 7 dias neste momento.")
        self.btn_new.clicked.connect(self._regen)
        bh.addWidget(self.btn_new)
        self.btn_save = QPushButton("Guardar HTML…")
        self.btn_save.clicked.connect(self._save)
        bh.addWidget(self.btn_save)
        bh.addStretch(1)
        close = QPushButton("Fechar")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        bh.addWidget(close)
        v.addLayout(bh)
        if report is None:
            self.report = weekly.last()
        if self.report is None:
            self._regen()
        else:
            self._render()

    def _regen(self):
        self.btn_new.setEnabled(False)

        def done(rep):
            self.btn_new.setEnabled(True)
            self.report = rep
            self._render()
        run_async(weekly.build, on_done=done, on_fail=lambda m: (self.btn_new.setEnabled(True),
                                                                 notify(f"Falhou: {m}", "bad")))

    def _render(self):
        rep = self.report
        if rep is None:
            return
        from datetime import date, timedelta
        d0 = date.fromtimestamp(rep.start) + timedelta(days=1)
        d1 = date.fromtimestamp(rep.end)
        self.title.setText(rep.headline)
        self.period.setText(f"De {d0.strftime('%d/%m')} a {d1.strftime('%d/%m/%Y')}")
        while self.rows.count() > 1:
            w = self.rows.takeAt(0).widget()
            if w:
                w.deleteLater()
        icons = {"ok": "check", "info": "info", "warn": "alert", "bad": "alert"}
        for i, ln in enumerate(rep.lines):
            row = QWidget()
            row.setObjectName("Transparent")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(10)
            h.addWidget(icon_badge(icons.get(ln.kind, "info"), 26, 14, ln.kind if ln.kind != "info" else "accent"),
                        0, Qt.AlignTop)
            lb = label(ln.text, wrap=True)
            if ln.kind == "bad":
                lb.setStyleSheet(f"color: {theme.C['bad']}")
            h.addWidget(lb, 1)
            if ln.page:
                b = QPushButton("Ver")
                b.setObjectName("Ghost")
                b.clicked.connect(lambda _c, p=ln.page: self._go(p))
                h.addWidget(b, 0, Qt.AlignTop)
            self.rows.insertWidget(i, row)

    def _go(self, page: str):
        w = self.parent().window() if self.parent() else None
        if w is not None and hasattr(w, "go_name"):
            w.go_name(page)
        self.accept()

    def _save(self):
        if not self.report:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar relatório", "relatorio-semanal-nexo.html",
                                              "Página HTML (*.html)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(weekly.to_html(self.report))
            notify("Relatório guardado.", "ok")
        except OSError as e:
            notify(f"Não foi possível guardar: {e}", "bad")
