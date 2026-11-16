"""Cartão «Porque está lento?» (Visão geral): diagnóstico de um clique com explicações e atalhos."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..core import slowdiag
from .widgets import Card, icon_badge, label, notify, run_async

_ICON = {"bad": ("alert", "bad"), "warn": ("alert", "warn"), "info": ("info", "accent"), "ok": ("check", "ok")}


class SlowDiagCard(Card):
    def __init__(self, hub):
        super().__init__("Porque está lento?", "Mede durante 2 segundos o que está a pesar (processador, memória, "
                         "discos, temperatura, atualizações, antivírus…) e explica em linguagem simples.",
                         icon="search")
        self.hub = hub
        self.btn = QPushButton("Diagnosticar agora")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(self.run)
        self.head.addWidget(self.btn, 0, Qt.AlignTop)
        self.results = QWidget()
        self.results.setObjectName("Transparent")
        self.res_lay = QVBoxLayout(self.results)
        self.res_lay.setContentsMargins(0, 4, 0, 0)
        self.res_lay.setSpacing(10)
        self.results.hide()
        self.add(self.results)
        self._busy = False

    def run(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)
        self.btn.setText("A medir…")
        snap = {k: self.hub.latest(k) for k in ("cpu_temp", "gpu_temp")}
        det = getattr(self.window(), "throttle", None)
        thr = det.active() if det is not None else {}

        def work():
            return slowdiag.analyze(slowdiag.collect(snap, thr))

        def done(findings):
            self._busy = False
            self.btn.setEnabled(True)
            self.btn.setText("Diagnosticar outra vez")
            self._show(findings)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            self.btn.setText("Diagnosticar agora")
            notify(f"Diagnóstico falhou: {m}", "bad")
        run_async(work, on_done=done, on_fail=fail)

    def _show(self, findings: list[slowdiag.Finding]):
        while self.res_lay.count():
            it = self.res_lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
            elif it.layout() is not None:
                _clear(it.layout())
        for f in findings[:8]:
            row = QHBoxLayout()
            row.setSpacing(12)
            ic, kind = _ICON.get(f.kind, ("info", "accent"))
            row.addWidget(icon_badge(ic, 30, 15, kind), 0, Qt.AlignTop)
            text = f"<b>{f.title}</b>" + (f"<br>{f.detail}" if f.detail else "")
            lb = label(text, wrap=True)
            lb.setTextFormat(Qt.RichText)
            row.addWidget(lb, 1)
            if f.page:
                b = QPushButton(f.action)
                b.setObjectName("Ghost")
                b.clicked.connect(lambda _c=False, p=f.page: self.window().go_name(p))
                row.addWidget(b, 0, Qt.AlignTop)
            self.res_lay.addLayout(row)
        self.results.show()


def _clear(lay):
    while lay.count():
        it = lay.takeAt(0)
        if it.widget() is not None:
            it.widget().deleteLater()
        elif it.layout() is not None:
            _clear(it.layout())
