from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QHBoxLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem,
                               QWidget)

from ...core import debloat, tweaks
from ...core.util import IS_WIN, is_admin, relaunch_as_admin
from ..widgets import Card, Page, confirm, label, notify, run_async
from .optimize import TweakList


class DebloatPage(Page):
    def __init__(self):
        super().__init__("Windows debloat", "Remove apps pré-instaladas e desliga telemetria, anúncios e sugestões. "
                                            "Nada que reduza a segurança (Defender, SmartScreen, UAC, Windows Update).")
        self.apps: list[debloat.BloatApp] = []
        if not IS_WIN:
            info = Card("Disponível só no Windows",
                        "Esta secção mexe em apps Appx, no registo e em serviços do Windows. No Linux não há "
                        "bloatware equivalente — para libertar espaço e recursos use as páginas Espaço em disco, "
                        "Otimização e Arranque.")
            self.add(info)
            preview = Card("O que faz no Windows")
            for t in ("• Remover apps: Notícias, Dicas, Solitaire, Clipchamp, Cortana, Copilot, Teams pessoal, "
                      "Candy Crush, TikTok, Spotify/Disney+ pré-instalados, McAfee de teste…",
                      "• Privacidade: telemetria no mínimo, serviços DiagTrack/dmwappushservice, ID de publicidade, "
                      "histórico de atividades, Recall.",
                      "• Interface: sem anúncios no Iniciar e no ecrã de bloqueio, pesquisa sem Bing, sem Copilot, "
                      "Widgets e botão Chat, extensões dos ficheiros visíveis.",
                      "• Tudo com \"Restaurar originais\" — as apps podem ser reinstaladas pela Microsoft Store."):
                preview.add(label(t, wrap=True))
            self.add(preview)
            self.body.addStretch(1)
            return

        if not is_admin():
            warn = Card("Modo de utilizador normal",
                        "Algumas ações (telemetria, serviços, Widgets, remover apps provisionadas) precisam de administrador.")
            b = QPushButton("Reabrir como administrador")
            b.setObjectName("Primary")
            b.clicked.connect(self._elevate)
            warn.head.addWidget(b)
            self.add(warn)

        apps = Card("Apps pré-instaladas", "Só aparecem as que estão instaladas neste PC. As marcadas são as recomendadas.")
        self.btn_reload = QPushButton("Atualizar")
        self.btn_remove = QPushButton("Remover marcadas")
        self.btn_remove.setObjectName("Danger")
        apps.head.addWidget(self.btn_reload)
        apps.head.addWidget(self.btn_remove)
        self.btn_reload.clicked.connect(self.load)
        self.btn_remove.clicked.connect(self.remove)
        self.status = label("A procurar apps…", "Muted")
        apps.add(self.status)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["", "App", "Descrição", "Pacote"])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setColumnWidth(0, 36)
        self.table.setColumnWidth(1, 220)
        self.table.setColumnWidth(3, 260)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(340)
        apps.add(self.table)
        self.add(apps)

        items = tweaks.privacy_tweaks()
        self.priv = TweakList("Privacidade", "Telemetria, publicidade e recolha de dados.",
                              [t for t in items if t.category == "Privacidade"])
        self.ui = TweakList("Interface", "Anúncios, sugestões e elementos que a Microsoft acrescenta ao Windows.",
                            [t for t in items if t.category == "Interface"])
        self.add(self.priv)
        self.add(self.ui)
        self._loaded = False

    def _elevate(self):
        if relaunch_as_admin():
            from PySide6.QtWidgets import QApplication
            QApplication.quit()

    def on_show(self):
        if not IS_WIN:
            return
        self.priv.refresh()
        self.ui.refresh()
        if not self._loaded:
            self._loaded = True
            self.load()

    def load(self):
        self.status.setText("A procurar apps…")
        run_async(debloat.installed, on_done=self._show)

    def _show(self, inst: dict):
        self.apps = [a for a in debloat.CATALOG if a.package in inst]
        self.status.setText(f"{len(self.apps)} apps do catálogo instaladas." if self.apps else
                            "Nenhuma das apps do catálogo está instalada — já está limpo ✔")
        self.table.setRowCount(len(self.apps))
        for i, a in enumerate(self.apps):
            cb = QCheckBox()
            cb.setChecked(a.recommended)
            w = QWidget()
            w.setObjectName("Transparent")
            lay = QHBoxLayout(w)
            lay.setContentsMargins(10, 0, 0, 0)
            lay.addWidget(cb)
            self.table.setCellWidget(i, 0, w)
            self.table.setItem(i, 1, QTableWidgetItem(a.label))
            self.table.setItem(i, 2, QTableWidgetItem(a.desc))
            p = QTableWidgetItem(a.package)
            p.setForeground(Qt.gray)
            self.table.setItem(i, 3, p)

    def remove(self):
        sel = [a for i, a in enumerate(self.apps) if self.table.cellWidget(i, 0).findChild(QCheckBox).isChecked()]
        if not sel:
            notify("Nenhuma app marcada.", "warn")
            return
        if not confirm(self, "Remover apps", f"Remover {len(sel)} apps?\n\n" + "\n".join(a.label for a in sel)
                       + "\n\nPodem ser reinstaladas pela Microsoft Store."):
            return
        self.btn_remove.setEnabled(False)

        def work():
            res = []
            for a in sel:
                ok, msg = debloat.remove(a.package, all_users=is_admin())
                res.append((a.label, ok, msg))
            return res

        def done(res):
            self.btn_remove.setEnabled(True)
            bad = [r for r in res if not r[1]]
            notify(f"{len(res) - len(bad)} apps removidas" + (f", {len(bad)} falharam: " +
                                                              ", ".join(r[0] for r in bad) if bad else ""),
                   "warn" if bad else "ok")
            self.load()
        run_async(work, on_done=done)
