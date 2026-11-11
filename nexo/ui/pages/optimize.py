from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem,
                               QWidget)

from ...core import memory, snapshot, tweaks
from ...core.util import human_bytes
from ..widgets import Card, Page, SettingRow, Toggle, confirm, label, notify, run_async, separator


class TweakList(Card):
    """Cartão com uma lista de ajustes reversíveis (interruptores)."""

    def __init__(self, title, subtitle, items: list[tweaks.Tweak]):
        super().__init__(title, subtitle)
        self.items = items
        self.toggles: list[tuple[tweaks.Tweak, Toggle]] = []
        self.btn_restore = QPushButton("Restaurar originais")
        self.head.addWidget(self.btn_restore)
        self.btn_restore.clicked.connect(self.restore)
        if not items:
            self.add(label("Nenhum ajuste disponível neste sistema.", "Muted"))
        for i, t in enumerate(items):
            tg = Toggle()
            badges = []
            if t.needs_admin:
                badges.append("admin")
            if t.reboot:
                badges.append("reiniciar")
            if i:
                self.add(separator())
            self.add(SettingRow(t.name, t.desc, tg, " · ".join(badges)))
            tg.clicked.connect(lambda checked, t=t, tg=tg: self._set(t, tg, checked))
            self.toggles.append((t, tg))

    def refresh(self):
        def states():
            out = []
            for t, _ in self.toggles:
                try:
                    out.append(bool(t.is_on()))
                except Exception:  # noqa: BLE001
                    logging.getLogger("nexo.optimize").debug("Estado do ajuste ilegível", exc_info=True)
                    out.append(False)
            return out

        def apply(vals):
            for (_t, tg), v in zip(self.toggles, vals):
                tg.setChecked(v)
        run_async(states, on_done=apply)

    def _set(self, t, tg, on):
        tg.setEnabled(False)

        def done(res):
            ok, msg = res
            tg.setEnabled(True)
            notify(f"{t.name}: {msg}", "ok" if ok else "bad")
            self.refresh()

        def work():
            # Windows; no Linux o snapshot vai junto do próprio comando root (um só pedido de palavra-passe)
            snap = snapshot.before(f"ajuste: {t.name}") if on else None
            ok, msg = t.set(on)
            if snap and not snap[0]:
                msg += " (aviso: não foi possível criar o ponto de restauro)"
            return ok, msg
        run_async(work, on_done=done)

    def restore(self):
        if not confirm(self, "Restaurar", "Desligar todos os ajustes e repor os valores originais?"):
            return

        def done(msgs):
            notify("; ".join(msgs) if msgs else "Nada para restaurar", "ok")
            self.refresh()
        run_async(tweaks.restore_all, self.items, on_done=done)


class OptimizePage(Page):
    def __init__(self):
        super().__init__("Otimização", "Ajustes de desempenho reversíveis e programas em segundo plano que gastam RAM")

        self.perf = TweakList("Ajustes de desempenho",
                              "Cada ajuste guarda o valor original; desligar volta ao que estava.",
                              tweaks.performance_tweaks())
        self.add(self.perf)
        self.extra: list[TweakList] = []
        extra = tweaks.windows_extra_tweaks() + tweaks.linux_extra_tweaks()
        titles = {"Sistema": ("Ajustes do sistema", "Energia, hibernação, jogos, diagnóstico e privacidade."),
                  "Interface": ("Ajustes da interface", "Explorador, barra de tarefas, menu de contexto e teclado."),
                  "Rede": ("Ajustes de rede", "Ligação à internet."),
                  "Desempenho": ("Ajustes avançados", "Kernel e rede (aplicados com sysctl, persistentes).")}
        for cat in ("Sistema", "Interface", "Rede", "Desempenho"):
            items = [t for t in extra if t.category == cat]
            if items:
                tl = TweakList(*titles[cat], items)
                self.extra.append(tl)
                self.add(tl)

        retired = tweaks.retired_tweaks()
        if retired:
            tl = TweakList("Ajustes retirados", "O Nexo já não recomenda estes ajustes. Desligue-os para repor "
                           "o que estava antes.", retired)
            self.extra.append(tl)
            self.add(tl)

        procs = Card("Programas em segundo plano",
                     "Os que mais gastam RAM. Os pré-marcados são seguros de fechar. Fechar pede ao programa para "
                     "sair normalmente (só força se não responder).")
        self.btn_ref = QPushButton("Atualizar")
        self.btn_close = QPushButton("Fechar marcados")
        self.btn_close.setObjectName("Danger")
        procs.head.addWidget(self.btn_ref)
        procs.head.addWidget(self.btn_close)
        self.btn_ref.clicked.connect(self.load_procs)
        self.btn_close.clicked.connect(self.close_procs)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "Programa", "Processos", "RAM"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(320)
        procs.add(self.table)
        self.add(procs)
        self.procs: list[dict] = []
        self.body.addStretch(1)

    def on_show(self):
        self.perf.refresh()
        for tl in self.extra:
            tl.refresh()
        self.load_procs()

    def load_procs(self):
        run_async(memory.background_processes, on_done=self._procs)

    def _procs(self, procs):
        self.procs = procs
        self.table.setRowCount(len(procs))
        for i, p in enumerate(procs):
            cb = QCheckBox()
            cb.setChecked(p["suggest"])
            w = QWidget()
            w.setObjectName("Transparent")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(10, 0, 0, 0)
            lay.addWidget(cb)
            self.table.setCellWidget(i, 0, w)
            name = QTableWidgetItem(p["name"] + ("   · seguro fechar" if p["suggest"] else ""))
            self.table.setItem(i, 1, name)
            n = QTableWidgetItem(str(len(p["pids"])))
            n.setTextAlignment(Qt.AlignCenter)
            self.table.setItem(i, 2, n)
            r = QTableWidgetItem(human_bytes(p["rss"]))
            r.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(i, 3, r)

    def close_procs(self):
        pids, names = [], []
        for i, p in enumerate(self.procs):
            cb = self.table.cellWidget(i, 0).findChild(QCheckBox)
            if cb and cb.isChecked():
                pids += p["pids"]
                names.append(p["name"])
        if not pids:
            notify("Nenhum programa marcado.", "warn")
            return
        if not confirm(self, "Fechar programas", "Fechar estes programas? Trabalho não guardado pode perder-se.\n\n"
                       + "\n".join(names)):
            return

        def done(n):
            notify(f"{n} processos fechados", "ok")
            self.load_procs()
        run_async(memory.terminate, pids, on_done=done)

