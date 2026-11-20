"""Página "Atualizações": o que há para atualizar no sistema e nas aplicações, e atualizar tudo de uma vez."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QHeaderView, QLineEdit, QMessageBox, QPushButton, QTableWidget,
                               QTableWidgetItem)

from ...core import updates as up
from ...core.util import IS_WIN, get_setting, human_duration, set_setting
from .. import theme
from ..widgets import Card, Page, SettingRow, Toggle, hbox, label, notify, run_async, separator, status_dot

SRC_TIP = {"Sistema": "Pacotes da distribuição", "AUR": "Pacotes do AUR (paru/yay)",
           "Flatpak": "Aplicações Flatpak", "winget": "Programas geridos pelo winget"}


class UpdatesPage(Page):
    def __init__(self):
        super().__init__("Atualizações", "Veja o que há para atualizar no sistema e nas aplicações — o Nexo só "
                                         "procura; instalar fica sempre a seu pedido.")
        self.btn_check = QPushButton("Verificar agora")
        self.btn_check.clicked.connect(lambda: self.check(force=True))
        self.head.addWidget(self.btn_check)

        # ---------------------------------------------------------------- resumo
        top = Card("Estado", icon="upgrade")
        self.big = label("—", "Big")
        self.status = label("", "Muted", wrap=True)
        self.btn_all = QPushButton("Atualizar tudo")
        self.btn_all.setObjectName("Primary")
        self.btn_all.clicked.connect(self._update_all)
        row = hbox(self.big, None, self.btn_all)
        if not IS_WIN:
            self.btn_term = QPushButton("Abrir no terminal")
            self.btn_term.setToolTip("Atualiza tudo num terminal (inclui o AUR e mostra o progresso)")
            self.btn_term.clicked.connect(self._terminal)
            row.insertWidget(2, self.btn_term)
        top.add(row)
        top.add(self.status)
        top.add(separator())
        self.tg_auto = Toggle(bool(get_setting("updates_auto", True)))
        self.tg_auto.clicked.connect(lambda on: set_setting("updates_auto", bool(on)))
        top.add(SettingRow("Verificar automaticamente",
                           "A cada 6 horas, em segundo plano e só com internet. O número aparece no menu lateral.",
                           self.tg_auto))
        self.add(top)

        # ---------------------------------------------------------------- lista
        lst = Card("Atualizações disponíveis")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Filtrar…")
        self.search.textChanged.connect(self._filter)
        self.src = QComboBox()
        self.src.addItem("Todas as origens", "")
        self.src.currentIndexChanged.connect(lambda _i: self._filter())
        self.count = label("", "Muted")
        lst.add(hbox(self.search, self.src, self.count))
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Nome", "Origem", "Versão instalada", "Nova versão"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for i, w in ((1, 110), (2, 200), (3, 200)):
            self.table.setColumnWidth(i, w)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSortingEnabled(True)
        self.table.sortByColumn(0, Qt.AscendingOrder)
        self.table.setMinimumHeight(320)
        lst.add(self.table, 1)
        self.notes = label("", "Muted", wrap=True)
        lst.add(self.notes)
        self.add(lst, 1)

        drv = Card("Drivers da placa gráfica", "Versão instalada e se há uma mais recente (Linux: Mesa ou NVIDIA; "
                   "Windows: driver do fabricante) e o que falta para os jogos e o sistema funcionarem bem.",
                   icon="gauge")
        self.btn_drv = QPushButton("Verificar")
        self.btn_drv.clicked.connect(self.check_drivers)
        drv.head.addWidget(self.btn_drv)
        self.drv_body = label("A verificar…", "", wrap=True)
        self.drv_body.setTextFormat(Qt.RichText)
        self.drv_body.setOpenExternalLinks(True)
        drv.add(self.drv_body)
        drv.add(separator())
        self.comp_body = label("", "", wrap=True)
        self.comp_body.setTextFormat(Qt.RichText)
        self.btn_comp = QPushButton("Abrir o Gestor de Dispositivos" if IS_WIN else "Instalar o que falta")
        self.btn_comp.setObjectName("Primary")
        self.btn_comp.clicked.connect(self._fix_components)
        self.btn_comp.hide()
        drv.add(self.comp_body)
        drv.add(hbox(None, self.btn_comp))
        self.add(drv)
        from ..bios_card import BiosCard
        self.bios = BiosCard()
        self.add(self.bios)
        self._components: list = []
        self._drv_checked = False

        self.items: list[up.Update] = []
        self._busy = False

    # ------------------------------------------------------------------
    def check_drivers(self):
        from ...core import drivers
        from ..netmonitor import monitor
        self.btn_drv.setEnabled(False)
        self.drv_body.setText("A verificar os drivers…")
        online = monitor().online is not False

        def done(lst):
            self.btn_drv.setEnabled(True)
            if not lst:
                self.drv_body.setText("Não encontrei nenhuma placa gráfica com driver identificável.")
                return
            rows = []
            for d in lst:
                kind = {"ok": "ok", "warn": "warn"}.get(d.status, "muted")
                ver = f"{d.component} {d.version}" if d.component != "Driver" else f"versão {d.version}"
                extra = f" · de {d.date}" if d.date else ""
                latest = f" · mais recente: {d.latest}" if d.latest and d.latest != d.version else ""
                link = f" <a href='{d.link}'>Página oficial</a>" if d.link and d.status == "warn" else ""
                rows.append(f"{status_dot(kind)} <b>{d.gpu}</b><br>{ver}{extra}{latest}<br>"
                            f"<span style='color:{theme.C['muted']}'>{d.message}</span>{link}")
            self.drv_body.setText("<br><br>".join(rows))

        def fail(m):
            self.btn_drv.setEnabled(True)
            self.drv_body.setText(f"Não foi possível verificar: {m}")
        run_async(drivers.check, online, on_done=done, on_fail=fail)
        self.check_components()

    # ------------------------------------------------------------------ componentes em falta
    def check_components(self):
        from ...core import components
        self.comp_body.setText("A procurar drivers e componentes em falta…")
        run_async(components.check, on_done=self._show_components,
                  on_fail=lambda m: self.comp_body.setText(f"Não foi possível verificar os componentes: {m}"))

    def _show_components(self, found: list):
        self._components = found
        from html import escape

        from ...core.i18n import tr
        if not found:
            why = ("Todos os dispositivos têm driver." if IS_WIN else
                   "Driver Vulkan, 32 bits para a Steam e microcode — está tudo instalado.")
            self.comp_body.setText(f"{status_dot('ok')} <b>{tr('Nada em falta')}</b><br>"
                                   f"<span style='color:{theme.C['muted']}'>{tr(why)}</span>")
            self.btn_comp.hide()
            return
        rows = []
        for f in found:   # nomes de dispositivos vêm do sistema: escapar antes de pôr em HTML
            cmd = f"<br><code>{escape(f.command)}</code>" if f.command else ""
            rows.append(f"{status_dot(f.kind)} <b>{escape(tr(f.title))}</b><br>"
                        f"<span style='color:{theme.C['muted']}'>{escape(tr(f.detail))}</span>{cmd}")
        self.comp_body.setText("<br><br>".join(rows))
        fixable = [f for f in found if f.action == ("devmgmt" if IS_WIN else "install")]
        if not IS_WIN and fixable:
            pkgs = ", ".join(dict.fromkeys(p for f in fixable for p in f.packages))
            self.btn_comp.setToolTip(f"Instala: {pkgs}")
        self.btn_comp.setVisible(bool(fixable))

    def _fix_components(self):
        from ...core import components
        if IS_WIN:
            components.open_device_manager()
            return
        todo = [f for f in self._components if f.action == "install"]
        pkgs = ", ".join(dict.fromkeys(p for f in todo for p in f.packages))
        if QMessageBox.question(self, "Instalar o que falta",
                                f"Instalar {pkgs}? O sistema vai pedir a palavra-passe.") != QMessageBox.Yes:
            return
        self.btn_comp.setEnabled(False)
        self.btn_comp.setText("A instalar…")

        def done(res):
            ok, msg = res
            self.btn_comp.setEnabled(True)
            self.btn_comp.setText("Instalar o que falta")
            notify(msg, "ok" if ok else "bad")
            self.check_components()

        def fail(m):
            self.btn_comp.setEnabled(True)
            self.btn_comp.setText("Instalar o que falta")
            notify(f"Não foi possível instalar: {m}", "bad")
        run_async(components.install, todo, on_done=done, on_fail=fail)

    def on_show(self):
        if not self._drv_checked:
            self._drv_checked = True
            self.check_drivers()
            self.bios.ensure_checked()
        data = up.cached()
        if data:
            self._show(data)
        if not data or time.time() - data.get("time", 0) > 3600:
            self.check()

    def refresh(self):
        self.check(force=True)

    def check(self, force: bool = False):
        win = self.window()
        if self._busy or not hasattr(win, "check_updates"):
            return
        self._busy = True
        self.btn_check.setEnabled(False)
        self.btn_check.setText("A verificar…")
        self.status.setText("A procurar atualizações… (pode demorar até um minuto)")

        def done(data):
            self._busy = False
            self.btn_check.setEnabled(True)
            self.btn_check.setText("Verificar agora")
            if data:
                self._show(data)
                self.check_drivers()   # as atualizações pendentes também dizem se há driver novo
                if force:
                    n = len(data.get("items", []))
                    notify(f"{n} atualizações disponíveis." if n else "Está tudo atualizado.", "info" if n else "ok")
            else:
                self.status.setText("Não foi possível verificar agora (sem internet?).")
        if not win.check_updates(force=True, on_done=done):
            done(None)

    def _show(self, data: dict):
        self.items = up.items(data)
        n = len(self.items)
        self.big.setText(f"{n} atualizaç{'ão' if n == 1 else 'ões'}" if n else "Tudo atualizado")
        ago = time.time() - data.get("time", time.time())
        when = "agora mesmo" if ago < 60 else f"há {human_duration(ago).split(' ')[0]}"
        by_src: dict[str, int] = {}
        for u in self.items:
            by_src[u.source] = by_src.get(u.source, 0) + 1
        parts = [f"{k}: {v}" for k, v in by_src.items()]
        self.status.setText(f"Última verificação {when}." + (f"  ·  {'  ·  '.join(parts)}" if parts else ""))
        self.btn_all.setEnabled(bool(n))
        cur = self.src.currentData()
        self.src.blockSignals(True)
        self.src.clear()
        self.src.addItem("Todas as origens", "")
        for k in by_src:
            self.src.addItem(k, k)
        self.src.setCurrentIndex(max(0, self.src.findData(cur)))
        self.src.blockSignals(False)
        self.table.setSortingEnabled(False)
        self.table.setRowCount(n)
        for i, u in enumerate(self.items):
            vals = (u.name, u.source, u.current or "—", u.new or "—")
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 1:
                    it.setToolTip(SRC_TIP.get(u.source, u.source))
                if j == 0:
                    it.setData(Qt.UserRole, i)
                self.table.setItem(i, j, it)
        self.table.setSortingEnabled(True)
        self.notes.setText("\n".join(data.get("notes", [])))
        self.notes.setVisible(bool(data.get("notes")))
        self._filter()

    def _filter(self, *_):
        q = self.search.text().lower().strip()
        src = self.src.currentData() or ""
        shown = 0
        for r in range(self.table.rowCount()):
            it = self.table.item(r, 0)
            u = self.items[it.data(Qt.UserRole)] if it is not None else None
            hide = u is None or (q and q not in u.name.lower()) or (src and u.source != src)
            self.table.setRowHidden(r, bool(hide))
            shown += 0 if hide else 1
        self.count.setText(f"{shown} de {len(self.items)}")

    # ------------------------------------------------------------------ atualizar
    def _update_all(self):
        from ..netmonitor import require_online
        if not self.items or not require_online("Atualizar"):
            return
        srcs = {u.source for u in self.items}
        what = []
        if "Sistema" in srcs:
            what.append("os pacotes do sistema (pede a palavra-passe de administrador)")
        if "Flatpak" in srcs:
            what.append("as aplicações Flatpak")
        if "winget" in srcs:
            what.append("os programas do winget")
        extra = ("\n\nOs pacotes do AUR não podem ser atualizados em segundo plano — use «Abrir no terminal»."
                 if "AUR" in srcs else "")
        if not what:
            notify("Use «Abrir no terminal» para atualizar os pacotes do AUR.", "info")
            return
        if QMessageBox.question(self, "Atualizar tudo", "Vai atualizar " + ", ".join(what) + "." + extra +
                                "\n\nPode demorar vários minutos. Continuar?") != QMessageBox.Yes:
            return
        self.btn_all.setEnabled(False)
        self.btn_all.setText("A atualizar…")
        self.status.setText("A atualizar… pode continuar a usar o Nexo.")

        def done(res):
            self.btn_all.setText("Atualizar tudo")
            ok, msg = res
            if ok:
                from ...core import changes
                changes.mark("atualizacao", "Atualizou " + ", ".join(w.split(" (")[0] for w in what))
            notify(("Atualizações instaladas. " if ok else "Atualização com problemas: ") + msg, "ok" if ok else "bad")
            self.check()

        def fail(m):
            self.btn_all.setText("Atualizar tudo")
            self.btn_all.setEnabled(True)
            notify(f"Não foi possível atualizar: {m}", "bad")
        run_async(up.update_all, srcs, on_done=done, on_fail=fail)

    def _terminal(self):
        ok, msg = up.open_terminal_update()
        notify(msg, "info" if ok else "bad")
        if ok:
            self.status.setText("A atualizar no terminal — carregue em «Verificar agora» quando terminar.")

