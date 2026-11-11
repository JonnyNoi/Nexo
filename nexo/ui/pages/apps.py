from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QCheckBox, QGridLayout, QLineEdit, QPlainTextEdit, QPushButton, QWidget

from ...core import apps as ap
from ...core.util import IS_WIN
from ..netmonitor import require_online
from ..widgets import Card, Page, Task, Tip, confirm, hbox, label, notify, run_async


class AppTile(QWidget):
    def __init__(self, app: ap.App):
        super().__init__()
        self.app = app
        self.setObjectName("Transparent")
        g = QGridLayout(self)
        g.setContentsMargins(4, 4, 4, 4)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(0)
        self.cb = QCheckBox(app.name)
        f = self.cb.font()
        f.setBold(True)
        self.cb.setFont(f)
        self.badge = label("instalada", "BadgeOk")
        self.badge.hide()
        d = label(app.desc, "Muted", wrap=True)
        d.setContentsMargins(26, 0, 0, 0)
        g.addWidget(self.cb, 0, 0)
        g.addWidget(self.badge, 0, 1, Qt.AlignLeft)
        g.setColumnStretch(2, 1)
        g.addWidget(d, 1, 0, 1, 3)
        self.setToolTip(app.pkg_id)

    def set_installed(self, found: "ap.Found | None"):
        self.found = found
        self.badge.setVisible(found is not None)
        if found is None:
            self.setToolTip(self.app.pkg_id)
            return
        self.badge.setText("instalada" if found.managed and found.source in ("Flatpak", "winget")
                           else f"instalada · {found.label}")
        self.setToolTip(f"{self.app.pkg_id}\nInstalada através de: {found.label}" +
                        ("" if found.managed else "\nO Nexo não a desinstala nem atualiza "
                                                  "(use o gestor por onde a instalou)."))


class AppsPage(Page):
    def __init__(self):
        sub = ("Escolha as aplicações e instale todas de uma vez — " +
               ("sem anúncios nem caixas \"Seguinte\", através do winget da Microsoft." if IS_WIN else
                "através do Flathub (Flatpak), sem palavra-passe e sem mexer nos pacotes do sistema."))
        super().__init__("Instalar aplicações", sub)
        self.backend, msg = ap.backend()
        self.tiles: list[AppTile] = []
        self.installed: dict[str, ap.Found] = {}
        self.busy = False

        self.search = QLineEdit()
        self.search.setPlaceholderText("Procurar aplicação…")
        self.search.setFixedWidth(240)
        self.btn_upgrade = QPushButton("Atualizar todas")
        self.btn_upgrade.setToolTip("Atualiza TODAS as aplicações instaladas pelo " + (self.backend or "gestor"))
        self.btn_uninstall = QPushButton("Desinstalar")
        self.btn_uninstall.setObjectName("Danger")
        self.btn_install = QPushButton("Instalar selecionadas")
        self.btn_install.setObjectName("Primary")
        self.head.addWidget(self.search)
        self.head.addWidget(self.btn_upgrade)
        self.head.addWidget(self.btn_uninstall)
        self.head.addWidget(self.btn_install)

        if not self.backend:
            self.add(Tip(msg, "warn"))
            self.btn_upgrade.setEnabled(False)

        chips = hbox(spacing=6)
        self.chip_group = QButtonGroup(self)
        cats = [c for c in ap.CATEGORIES if any(a.category == c for a in ap.available_apps())]
        for c in ["Todas", *cats]:
            b = QPushButton(c)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(c == "Todas")
            self.chip_group.addButton(b)
            chips.addWidget(b)
        chips.addStretch(1)
        self.sel_lbl = label("", "Muted")
        self.btn_clear = QPushButton("Limpar seleção")
        self.btn_clear.setObjectName("Ghost")
        chips.addWidget(self.sel_lbl)
        chips.addWidget(self.btn_clear)
        self.add(chips)

        self.cards: dict[str, Card] = {}
        for cat in cats:
            card = Card(cat)
            grid = QGridLayout()
            grid.setHorizontalSpacing(18)
            grid.setVerticalSpacing(10)
            items = [a for a in ap.available_apps() if a.category == cat]
            for i, a in enumerate(items):
                t = AppTile(a)
                t.cb.toggled.connect(lambda _c: self._sel_changed())
                self.tiles.append(t)
                grid.addWidget(t, i // 3, i % 3)
            for col in range(3):
                grid.setColumnStretch(col, 1)
            card.add(grid)
            self.cards[cat] = card
            self.add(card)

        # barra de ações + registo
        act = Card("Registo da instalação", icon="list")
        self.act_card = act
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(130)
        self.log.setPlaceholderText("O progresso aparece aqui.")
        act.add(self.log)
        self.add(act)
        self.body.addStretch(1)

        self.search.textChanged.connect(lambda _t: self._filter())
        self.chip_group.buttonClicked.connect(lambda _b: self._filter())
        self.btn_install.clicked.connect(lambda: self._run("install"))
        self.btn_uninstall.clicked.connect(lambda: self._run("uninstall"))
        self.btn_upgrade.clicked.connect(self._upgrade)
        self.btn_clear.clicked.connect(lambda: [t.cb.setChecked(False) for t in self.tiles])
        self._loaded = False
        self._sel_changed()

    # ------------------------------------------------------------------
    def on_show(self):
        if not self._loaded and self.backend:
            self._loaded = True
            self.refresh()

    def refresh(self):
        if not self.backend or self.busy:
            return
        self._log("A verificar o que já está instalado…")
        run_async(ap.detect_installed, on_done=self._got_installed)

    def _got_installed(self, found):
        self.installed = found
        for t in self.tiles:
            t.set_installed(found.get(t.app.name))
        by_src: dict[str, int] = {}
        for f in found.values():
            by_src[f.label] = by_src.get(f.label, 0) + 1
        det = ", ".join(f"{n} {src}" for src, n in sorted(by_src.items(), key=lambda x: -x[1]))
        self._log(f"{len(found)} aplicações do catálogo já estão instaladas" + (f" ({det})." if det else "."))

    def _filter(self):
        q = self.search.text().strip().lower()
        b = self.chip_group.checkedButton()
        cat = b.text() if b else "Todas"
        for t in self.tiles:
            ok = (cat == "Todas" or t.app.category == cat) and (
                not q or q in t.app.name.lower() or q in t.app.desc.lower())
            t.setVisible(ok)
        for name, card in self.cards.items():
            card.setVisible(any(t.isVisibleTo(card) for t in self.tiles if t.app.category == name))

    def _selected(self) -> list[ap.App]:
        return [t.app for t in self.tiles if t.cb.isChecked()]

    def _sel_changed(self):
        n = len(self._selected())
        self.sel_lbl.setText(f"{n} selecionada(s)" if n else "")
        self.btn_clear.setVisible(bool(n))
        on = bool(n) and bool(self.backend) and not self.busy
        self.btn_install.setEnabled(on)
        self.btn_uninstall.setEnabled(on)
        self.btn_install.setText(f"Instalar ({n})" if n else "Instalar selecionadas")

    def _log(self, msg):
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _set_busy(self, on: bool):
        self.busy = on
        self.btn_upgrade.setEnabled(not on and bool(self.backend))
        self._sel_changed()

    # ------------------------------------------------------------------ ações
    def _run(self, kind: str):
        sel = self._selected()
        if not sel:
            return
        if kind == "install" and not require_online("Instalar aplicações"):
            return
        if kind == "install":   # já instaladas por outro lado (ex.: pacman): não duplica com o Flatpak/winget
            dup = [a for a in sel if a.name in self.installed]
            if dup and not confirm(self, "Já instaladas", "Estas aplicações já estão instaladas:\n\n" +
                                   "\n".join(f"{a.name} ({self.installed[a.name].label})" for a in dup) +
                                   "\n\nInstalar outra cópia na mesma?"):
                sel = [a for a in sel if a not in dup]
                if not sel:
                    return
        if kind == "uninstall":
            other = [a for a in sel if a.name in self.installed and not self.installed[a.name].managed]
            for a in other:
                self._log(f"ℹ {a.name}: instalada através de {self.installed[a.name].label} — "
                          "desinstale-a por esse gestor.")
            sel = [a for a in sel if a.name in self.installed and self.installed[a.name].managed]
            if not sel:
                notify("Nenhuma das selecionadas foi instalada por esta página (veja o registo).", "warn")
                self.ensureWidgetVisible(self.act_card)
                return
            if not confirm(self, "Desinstalar", "Desinstalar estas aplicações?\n\n" + "\n".join(a.name for a in sel)):
                return
        fn = ap.install if kind == "install" else ap.uninstall
        verb = "Instalar" if kind == "install" else "Desinstalar"
        self._set_busy(True)
        self.ensureWidgetVisible(self.act_card)
        notify(f"{verb}: {len(sel)} aplicação(ões) — o progresso aparece no registo, no fim da página.", "info")
        holder: dict = {}

        def work():
            res = []
            for i, a in enumerate(sel):
                holder["t"].progress.emit(("start", i, a, None))
                ok, msg = fn(a.pkg_id)
                holder["t"].progress.emit(("end", i, a, (ok, msg)))
                res.append(ok)
            return res

        def progress(ev):
            stage, i, a, r = ev
            if stage == "start":
                self._log(f"{verb} {a.name} ({i + 1}/{len(sel)})…")
            else:
                ok, msg = r
                self._log(("✔ " if ok else "✘ ") + f"{a.name}: " + msg.replace("\n", " · "))

        def done(res):
            self._set_busy(False)
            n = sum(res)
            notify(f"{verb}: {n} de {len(res)} concluída(s).", "ok" if n == len(res) else "warn")
            for t in self.tiles:
                if t.cb.isChecked() and t.app in sel:
                    t.cb.setChecked(False)
            self.refresh()

        def fail(msg):
            self._set_busy(False)
            notify(f"Erro: {msg}", "bad")

        t = Task(work)
        holder["t"] = t
        t.progress.connect(progress)
        t.done.connect(done)
        t.failed.connect(fail)
        t.start()

    def _upgrade(self):
        if not require_online("Atualizar aplicações"):
            return
        if not confirm(self, "Atualizar todas", "Atualizar todas as aplicações instaladas pelo "
                       f"{self.backend}? Pode demorar vários minutos."):
            return
        self._set_busy(True)
        self._log("A atualizar todas as aplicações…")

        def done(res):
            ok, msg = res
            self._set_busy(False)
            self._log(("✔ " if ok else "✘ ") + msg.replace("\n", " · "))
            notify("Aplicações atualizadas." if ok else "Algumas atualizações falharam (veja o registo).",
                   "ok" if ok else "warn")
            self.refresh()
        run_async(ap.upgrade_all, on_done=done, on_fail=lambda m: (self._set_busy(False), notify(m, "bad")))
