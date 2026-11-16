"""Separador "Limpeza rápida" da página Espaço em disco (misturado na DiskPage)."""
from __future__ import annotations


from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (QPushButton, QTableWidgetItem, QVBoxLayout, QWidget)

from ..core import cleanup
from ..core.util import human_bytes
from .theme import qc
from .widgets import Card, Task, confirm, label, notify, run_async



from .disk_widgets import SizeItem, _table


class CleanMixin:
    """Usa self.tabs/self._drives da DiskPage."""

    # ------------------------------------------------------------------ limpeza
    def _build_clean(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        card = Card("Ficheiros dispensáveis",
                    "Caches, temporários e pacotes antigos que o sistema e as apps voltam a criar quando precisam. "
                    "Feche os navegadores antes de limpar a cache deles.")
        self.btn_calc = QPushButton("Recalcular")
        self.btn_clean = QPushButton("Limpar marcadas")
        self.btn_clean.setObjectName("Primary")
        card.head.addWidget(self.btn_calc)
        card.head.addWidget(self.btn_clean)
        self.btn_calc.clicked.connect(self.calc)
        self.btn_clean.clicked.connect(self.clean)
        self.cats = cleanup.categories()
        self.t_clean = _table(["Categoria", "Descrição", "Segurança", "Tamanho", ""], 1)
        self.t_clean.setColumnWidth(0, 300)
        self.t_clean.setColumnWidth(2, 130)
        self.t_clean.setColumnWidth(3, 100)
        self.t_clean.setColumnWidth(4, 70)
        self.t_clean.setRowCount(len(self.cats))
        self.t_clean.setWordWrap(True)
        for i, c in enumerate(self.cats):
            it = QTableWidgetItem(c.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c.recommended else Qt.Unchecked)
            self.t_clean.setItem(i, 0, it)
            d = QTableWidgetItem(c.desc)
            d.setToolTip(c.desc)
            self.t_clean.setItem(i, 1, d)
            sf = QTableWidgetItem("⚠ Atenção" if c.caution else "✔ Seguro")
            sf.setForeground(QBrush(qc("warn" if c.caution else "ok")))
            sf.setToolTip(c.note)
            d.setToolTip(f"{c.desc}\n\n{c.note}")
            self.t_clean.setItem(i, 2, sf)
            self.t_clean.setItem(i, 3, SizeItem(-1))
            self.t_clean.setItem(i, 4, QTableWidgetItem("admin" if c.needs_admin else ""))
        self.t_clean.itemChanged.connect(lambda _i: self._total())
        self.t_clean.currentCellChanged.connect(self._clean_note)
        card.add(self.t_clean, 1)
        self.clean_note = label("Selecione uma linha para ver o que perde ao limpar. ✔ Seguro = não perde nada "
                                "importante · ⚠ Atenção = seguro, mas há uma consequência a saber.", "Muted", wrap=True)
        card.add(self.clean_note)
        self.clean_total = label("", "CardTitle")
        card.add(self.clean_total)
        v.addWidget(card, 1)
        w.setMinimumHeight(560)
        return w

    def _clean_note(self, row, *_a):
        if 0 <= row < len(self.cats):
            c = self.cats[row]
            color = qc("warn" if c.caution else "ok").name()
            self.clean_note.setText(f"<b>{c.name}</b> — <span style='color:{color}'>{c.note}</span>")

    def calc(self):
        self.btn_calc.setEnabled(False)

        def work():
            for i, c in enumerate(self.cats):
                c.size = cleanup.compute_size(c)
                t.progress.emit(i)
        t = Task(work)
        t.progress.connect(self._size_row)
        t.done.connect(lambda _r: (self.btn_calc.setEnabled(True), self._total()))
        t.failed.connect(lambda m: (self.btn_calc.setEnabled(True), notify(m, "bad")))
        t.start()

    def _size_row(self, i):
        self.t_clean.setItem(i, 3, SizeItem(self.cats[i].size))
        self._total()

    def _total(self):
        tot = sum(max(c.size, 0) for i, c in enumerate(self.cats)
                  if self.t_clean.item(i, 0) and self.t_clean.item(i, 0).checkState() == Qt.Checked)
        self.clean_total.setText(f"Marcado para limpar: {human_bytes(tot)}")

    def clean(self):
        sel = [c for i, c in enumerate(self.cats) if self.t_clean.item(i, 0).checkState() == Qt.Checked]
        if not sel:
            notify("Nada marcado.", "warn")
            return
        if not confirm(self, "Limpar", "Limpar estas categorias?\n\n" + "\n".join(f"• {c.name}" for c in sel)):
            return
        self.btn_clean.setEnabled(False)

        def work():
            out = []
            for c in sel:
                before = c.size if c.size >= 0 else cleanup.compute_size(c)
                ok, msg = cleanup.clean(c)
                after = cleanup.compute_size(c) if ok else before
                out.append((c.name, ok, msg, max(0, before - max(after, 0)) if before >= 0 else 0))
            return out

        def done(res):
            self.btn_clean.setEnabled(True)
            bad = [r for r in res if not r[1]]
            freed = sum(r[3] for r in res)
            if len(res) > len(bad):
                from ..core import changes
                changes.mark("limpeza", f"Limpeza: {', '.join(r[0] for r in res if r[1])}")
            notify(f"Limpeza concluída: {len(res) - len(bad)} categorias"
                   + (f" · libertados {human_bytes(freed)}" if freed else "")
                   + (f" · falharam: {', '.join(r[0] for r in bad)}" if bad else ""), "warn" if bad else "ok")
            self._drives()
            self.calc()
        run_async(work, on_done=done)
