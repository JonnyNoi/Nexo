from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QGridLayout, QPlainTextEdit, QPushButton, QRadioButton

from ...core import systools as st
from ...core.util import IS_WIN, is_admin
from ..widgets import Card, Page, SettingRow, Tip, Toggle, confirm, hbox, label, notify, run_async, separator


class ToolsPage(Page):
    def __init__(self):
        super().__init__("Utilitários",
                         "Reparar o sistema, funcionalidades e atualizações do Windows, DNS e atalhos para os painéis "
                         "clássicos" if IS_WIN else
                         "Atualizar o sistema, manutenção, diagnóstico e DNS")
        self.running: set[str] = set()

        if IS_WIN and not is_admin():
            self.add(Tip("Quase tudo nesta página precisa de administrador — use o botão <b>Admin</b> no menu.", "warn"))

        # ---------------------------------------------------------------- ações
        acts = st.actions()
        card = Card("Reparar e manutenção" if IS_WIN else "Manutenção do sistema",
                    "As ações demoradas correm em segundo plano; pode continuar a usar o Nexo.", icon="wrench")
        self.buttons: dict[str, QPushButton] = {}
        for i, a in enumerate(acts):
            b = QPushButton("Executar")
            b.setMinimumWidth(110)
            if a.id in ("restore", "upd"):
                b.setObjectName("Primary")
            b.clicked.connect(lambda _c, a=a: self._run(a))
            self.buttons[a.id] = b
            badges = []
            if a.admin:
                badges.append("admin")
            if a.long:
                badges.append("demora")
            if i:
                card.add(separator())
            card.add(SettingRow(a.name, a.desc, b, " · ".join(badges)))
        self.add(card)

        # ---------------------------------------------------------------- Windows: funcionalidades + update
        if IS_WIN:
            feat = Card("Funcionalidades do Windows", "Componentes opcionais (o mesmo que \"Ativar ou desativar "
                        "funcionalidades do Windows\"). É preciso reiniciar depois.", icon="package")
            self.feat_toggles: list[tuple[st.Feature, Toggle]] = []
            for i, f in enumerate(st.WIN_FEATURES):
                tg = Toggle()
                tg.setEnabled(False)
                tg.clicked.connect(lambda on, f=f, tg=tg: self._feature(f, tg, on))
                if i:
                    feat.add(separator())
                feat.add(SettingRow(f.name, f.desc, tg, "reiniciar"))
                self.feat_toggles.append((f, tg))
            self.add(feat)

            upd = Card("Windows Update", "Escolha quando o Windows instala atualizações. Nunca desliga as "
                       "atualizações de segurança.", icon="shield")
            self.rb_default = QRadioButton("Predefinição — o Windows decide (recomendado para a maioria)")
            self.rb_security = QRadioButton("Só segurança — atualizações de segurança com 4 dias de atraso; "
                                            "grandes atualizações adiadas 1 ano")
            for rb in (self.rb_default, self.rb_security):
                upd.add(rb)
                rb.toggled.connect(lambda on, rb=rb: on and self._update_mode(rb))
            upd.add(separator())
            self.tg_drivers = Toggle()
            self.tg_drivers.clicked.connect(self._drivers)
            upd.add(SettingRow("Instalar drivers pelo Windows Update",
                               "Desligue para o Windows não substituir o driver da placa gráfica que instalou.",
                               self.tg_drivers))
            self.add(upd)

        # ---------------------------------------------------------------- DNS (ambos)
        dns = Card("DNS", "O servidor que traduz nomes de sites em endereços. Um DNS rápido abre os sites mais "
                   "depressa; alguns bloqueiam malware ou anúncios.", icon="globe")
        self.dns_cb = QComboBox()
        for name, ips in st.DNS_PROVIDERS:
            self.dns_cb.addItem(f"{name}  {' · '.join(ips)}" if ips else name, ips)
        self.btn_dns = QPushButton("Aplicar")
        self.btn_dns.setObjectName("Primary")
        self.btn_bench = QPushButton("Testar velocidade")
        self.dns_cur = label("DNS atual: a ler…", "Muted", wrap=True)
        dns.add(hbox(self.dns_cb, self.btn_dns, self.btn_bench, None))
        dns.add(self.dns_cur)
        self.dns_res = label("", wrap=True)
        self.dns_res.setTextFormat(Qt.RichText)
        dns.add(self.dns_res)
        self.btn_dns.clicked.connect(self._set_dns)
        self.btn_bench.clicked.connect(self._bench_dns)
        self.add(dns)

        # ---------------------------------------------------------------- Windows: painéis
        if IS_WIN:
            pan = Card("Painéis clássicos", "Atalhos para as ferramentas do Windows que ficaram escondidas.",
                       icon="gear")
            grid = QGridLayout()
            grid.setSpacing(8)
            for i, (name, cmd) in enumerate(st.WIN_PANELS):
                b = QPushButton(name)
                b.clicked.connect(lambda _c, cmd=cmd: st.open_panel(cmd))
                grid.addWidget(b, i // 4, i % 4)
            pan.add(grid)
            self.add(pan)

        # ---------------------------------------------------------------- registo
        logc = Card("Registo")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(140)
        self.log.setPlaceholderText("O resultado das ações aparece aqui.")
        logc.add(self.log)
        self.add(logc)
        self.body.addStretch(1)
        self._loaded = False

    # ------------------------------------------------------------------
    def on_show(self):
        if self._loaded:
            return
        self._loaded = True
        self.refresh()

    def refresh(self):
        run_async(st.current_dns, on_done=lambda ips: self.dns_cur.setText(
            "DNS atual: " + (", ".join(ips) if ips else "desconhecido")))
        if IS_WIN:
            def states():
                return st.win_feature_states(), st.win_update_mode(), st.win_drivers_via_update()

            def apply(res):
                feats, mode, drivers = res
                for f, tg in self.feat_toggles:
                    known = [feats.get(x) for x in f.features if x in feats]
                    tg.setEnabled(bool(known))
                    tg.setChecked(bool(known) and all(known))
                    if not known:
                        tg.setToolTip("Não disponível nesta edição do Windows")
                for rb in (self.rb_default, self.rb_security):
                    rb.blockSignals(True)
                (self.rb_security if mode == "security" else self.rb_default).setChecked(True)
                for rb in (self.rb_default, self.rb_security):
                    rb.blockSignals(False)
                self.tg_drivers.setChecked(drivers)
            run_async(states, on_done=apply)

    def _log(self, msg):
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def _run(self, a: st.Action):
        if a.id in self.running:
            return
        if a.danger and not confirm(self, a.name, f"{a.name}?\n\n{a.desc}"):
            return
        b = self.buttons[a.id]
        b.setEnabled(False)
        b.setText("A executar…")
        self.running.add(a.id)
        self._log(f"{a.name}: a começar" + (" (pode demorar vários minutos)" if a.long else ""))

        def done(res):
            ok, msg = res
            self.running.discard(a.id)
            b.setEnabled(True)
            b.setText("Executar")
            self._log(("✔ " if ok else "✘ ") + f"{a.name}: {msg}")
            notify(f"{a.name}: {msg.splitlines()[0] if msg else ''}", "ok" if ok else "bad")

        def fail(msg):
            done((False, msg))
        run_async(a.run, on_done=done, on_fail=fail)

    def _feature(self, f, tg, on):
        tg.setEnabled(False)
        self._log(f"{'Ativar' if on else 'Desativar'} {f.name}…")

        def done(res):
            ok, msg = res
            tg.setEnabled(True)
            if not ok:
                tg.setChecked(not on)
            self._log(("✔ " if ok else "✘ ") + f"{f.name}: {msg}")
            notify(f"{f.name}: {msg}", "ok" if ok else "bad")
        run_async(st.win_set_feature, f, bool(on), on_done=done)

    def _update_mode(self, rb):
        mode = "security" if rb is self.rb_security else "default"

        def done(res):
            ok, msg = res
            self._log(("✔ " if ok else "✘ ") + msg)
            notify(msg, "ok" if ok else "bad")
            if not ok:
                self.refresh()
        run_async(st.win_set_update_mode, mode, on_done=done)

    def _drivers(self, on):
        def done(res):
            ok, msg = res
            self._log(("✔ " if ok else "✘ ") + msg)
            notify(msg, "ok" if ok else "bad")
            if not ok:
                self.tg_drivers.setChecked(not on)
        run_async(st.win_set_drivers_via_update, bool(on), on_done=done)

    def _set_dns(self):
        ips = self.dns_cb.currentData()
        name = self.dns_cb.currentText()
        self.btn_dns.setEnabled(False)
        self._log(f"DNS → {name}")

        def done(res):
            ok, msg = res
            self.btn_dns.setEnabled(True)
            self._log(("✔ " if ok else "✘ ") + msg)
            notify(msg, "ok" if ok else "bad")
            self.refresh()
        run_async(st.set_dns, ips or [], on_done=done,
                  on_fail=lambda m: (self.btn_dns.setEnabled(True), notify(m, "bad")))

    def _bench_dns(self):
        self.btn_bench.setEnabled(False)
        self.btn_bench.setText("A testar…")

        def done(res):
            from .. import theme
            self.btn_bench.setEnabled(True)
            self.btn_bench.setText("Testar velocidade")
            best = next((t for _n, t in res if t is not None), None)
            rows = []
            for n, t in res:
                if t is None:
                    rows.append(f"<span style='color:{theme.C['muted']}'>{n}: sem resposta</span>")
                    continue
                col = theme.C["ok"] if t == best else theme.C["text"]
                rows.append(f"<span style='color:{col}'>{'★ ' if t == best else ''}{n}: <b>{t:.0f} ms</b></span>")
            self.dns_res.setText(" &nbsp;·&nbsp; ".join(rows))
            if best is not None:
                fastest = res[0][0]
                idx = next((i for i, (n, _ips) in enumerate(st.DNS_PROVIDERS) if n == fastest), -1)
                if idx >= 0:
                    self.dns_cb.setCurrentIndex(idx)
                self._log(f"DNS mais rápido: {fastest} ({best:.0f} ms) — selecionado, carregue em Aplicar.")
        run_async(st.dns_benchmark, on_done=done)
