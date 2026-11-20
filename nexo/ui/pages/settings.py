from __future__ import annotations

import time

from PySide6.QtWidgets import QComboBox, QFileDialog, QPushButton, QSpinBox

from ...core import history, snapshot, startup
from ...core.util import APP_NAME, APP_VERSION, config_dir, get_setting, human_bytes, open_path, set_setting
from .. import theme
from ..widgets import Card, Page, SettingRow, Toggle, confirm, hbox, label, notify, run_async, separator

class SettingsPage(Page):
    def __init__(self, on_change=None):
        super().__init__("Definições", "Aparência, alertas, proteção, bandeja do sistema, arranque e dados do Nexo")
        self._on_change = on_change or (lambda _k: None)
        self._build_appearance()

        # ---------------------------------------------------------------- alertas
        al = Card("Alertas",
                  "Aviso (notificação do sistema + mensagem na janela) quando algo precisa de atenção. "
                  "Funciona também com a janela minimizada na bandeja.", icon="alert")
        self.tg_alerts = self._toggle("alerts")
        al.add(SettingRow("Temperatura alta", "CPU ou GPU acima do limite. No máximo um aviso a cada 5 minutos "
                          "por componente.", self.tg_alerts))
        al.add(separator())
        self.sp_cpu = self._spin("alert_cpu", 60, 105)
        al.add(SettingRow("Limite da CPU", "A maioria das CPUs desktop começa a reduzir o clock perto dos 95–100 °C.",
                          self.sp_cpu))
        al.add(separator())
        self.sp_gpu = self._spin("alert_gpu", 60, 105)
        al.add(SettingRow("Limite da GPU", "GPUs dedicadas trabalham normalmente abaixo dos 85 °C.", self.sp_gpu))
        al.add(separator())
        self.tg_ram = self._toggle("alert_ram")
        self.sp_ram = self._spin("alert_ram_pct", 70, 99, " %")
        al.add(SettingRow("Memória quase cheia", "RAM acima deste valor durante 2 minutos seguidos.",
                          hbox(self.sp_ram, self.tg_ram)))
        al.add(separator())
        self.tg_disk = self._toggle("alert_disk")
        self.sp_disk = self._spin("alert_disk_pct", 3, 30, " % livre")
        al.add(SettingRow("Pouco espaço em disco", "Verificado a cada 5 minutos em todos os discos internos.",
                          hbox(self.sp_disk, self.tg_disk)))
        al.add(separator())
        self.tg_smart = self._toggle("alert_smart")
        al.add(SettingRow("Saúde dos discos a piorar",
                          "Avisa quando o S.M.A.R.T. de um disco passa de 'bom' para 'atenção' ou 'mau' "
                          "(usa a última leitura da página Saúde dos discos).", self.tg_smart))
        al.add(separator())
        al.add(SettingRow("Limitação por temperatura",
                          "Avisa quando o processador ou a placa gráfica baixam o clock por estarem demasiado quentes.",
                          self._toggle("alert_throttle")))
        al.add(separator())
        al.add(SettingRow("Problemas de estabilidade",
                          "Avisa de desligares sem aviso, falhas do sistema, erros de hardware e do controlador "
                          "gráfico (verificado no arranque e a cada 6 horas — página Fiabilidade).",
                          self._toggle("alert_reliability")))
        al.add(separator())
        al.add(SettingRow("Relatório da semana",
                          "Uma vez por semana, um resumo de como esteve o PC (saúde, estabilidade, arranque, jogos) "
                          "com aviso no centro de alertas. Também em Visão geral → Relatório da semana.",
                          self._toggle("weekly_report")))
        self.add(al)

        # ---------------------------------------------------------------- proteção
        self._build_protection()

        # ---------------------------------------------------------------- histórico
        hi = Card("Histórico dos sensores",
                  f"Guarda a média e o máximo de cada minuto durante {history.KEEP_DAYS} dias, para ver depois "
                  "em Sensores → Histórico.", icon="chart")
        self.tg_hist = self._toggle("history")
        btn_clear = QPushButton("Apagar histórico")
        btn_clear.clicked.connect(self._clear_history)
        hi.add(SettingRow("Guardar histórico", "Ocupa menos de 2 MB.", hbox(btn_clear, self.tg_hist)))
        self.add(hi)

        # ---------------------------------------------------------------- janela
        win = Card("Janela e bandeja", icon="box")
        self.tg_tray = self._toggle("tray")
        win.add(SettingRow("Ícone na bandeja do sistema",
                           "Mostra temperatura e carga ao passar o rato; clique para abrir o Nexo.", self.tg_tray))
        win.add(separator())
        self.tg_close = self._toggle("close_to_tray")
        win.add(SettingRow("Fechar para a bandeja",
                           "Ao fechar a janela, o Nexo continua a monitorizar em segundo plano "
                           "(para sair: menu da bandeja → Sair, ou Ctrl+Q).", self.tg_close))
        win.add(separator())
        self.tg_min = self._toggle("start_minimized")
        win.add(SettingRow("Abrir minimizado", "Arranca diretamente na bandeja (útil com o arranque automático).",
                           self.tg_min))
        win.add(separator())
        self.tg_anim = self._toggle("page_fade")
        win.add(SettingRow("Transições suaves", "Desvanecer ao mudar de página.", self.tg_anim))
        win.add(separator())
        self.tg_page = self._toggle("remember_page")
        win.add(SettingRow("Lembrar a última página", "Volta a abrir na página onde estava.", self.tg_page))
        win.add(separator())
        self.tg_auto = Toggle(startup.self_autostart_enabled())
        self.tg_auto.clicked.connect(self._autostart)
        win.add(SettingRow("Abrir com o sistema", "Inicia o Nexo minimizado quando entra na sessão.", self.tg_auto))
        self.add(win)

        from ..webpanel_card import WebPanelCard
        self.web = WebPanelCard()
        self.add(self.web)

        self._build_autoclean()
        self._build_backup()
        self._build_selfupdate()

        # ---------------------------------------------------------------- dados / sobre
        about = Card("Dados e informação", icon="info")
        btn_dir = QPushButton("Abrir pasta de dados")
        btn_dir.clicked.connect(lambda: open_path(config_dir()))
        btn_log = QPushButton("Abrir registo de erros")
        btn_log.setToolTip("nexo.log: erros e avisos do Nexo (útil para reportar um problema)")
        btn_log.clicked.connect(self._open_log)
        btn_diag = QPushButton("Copiar diagnóstico")
        btn_diag.setToolTip("Copia a versão, o sistema e as últimas linhas do registo — cole no relatório do problema")
        btn_diag.clicked.connect(self._copy_diag)
        about.add(hbox(label(f"{APP_NAME} {APP_VERSION} · dados em {config_dir()}", "Muted", wrap=True), None,
                       btn_diag, btn_log, btn_dir))
        b_wiz = QPushButton("Assistente de boas-vindas")
        b_wiz.setToolTip("Voltar a ver o assistente da primeira execução")
        b_wiz.clicked.connect(lambda: self.window().show_wizard())
        b_keys = QPushButton("Atalhos de teclado (F1)")
        b_keys.clicked.connect(lambda: self.window().show_shortcuts())
        about.add(hbox(label("<b>Atalhos:</b> Ctrl+K pesquisa · Ctrl+1…Ctrl+9 mudar de página · Ctrl+Shift+A alertas "
                             "· F5 atualizar · F1 todos os atalhos", "Muted", wrap=True), None, b_keys, b_wiz))
        self.add(about)
        self.body.addStretch(1)

    # ------------------------------------------------------------------ limpeza automática
    def _build_autoclean(self):
        from ...core import autoclean, schedule
        c = Card("Limpeza automática", "Limpa sozinho, de tempos a tempos, só o que se refaz sem custo e não precisa "
                 "de palavra-passe. O Lixo, as caches dos navegadores e dos jogos ficam sempre para si decidir.",
                 icon="broom")
        self.cb_clean = QComboBox()
        for days, txt in schedule.INTERVALS.items():
            self.cb_clean.addItem(txt, days)
        self.cb_clean.setCurrentIndex(max(0, self.cb_clean.findData(int(get_setting("auto_clean_days") or 0))))
        self.cb_clean.currentIndexChanged.connect(self._autoclean_changed)
        names = ", ".join(x.name.lower() for x in autoclean.categories()) or "—"
        self.lb_clean = label("", "Muted", wrap=True)
        c.add(SettingRow("Frequência", f"Inclui: {names}.", self.cb_clean))
        b_tasks = QPushButton("Ver todas as tarefas agendadas")
        b_tasks.setObjectName("Ghost")
        b_tasks.clicked.connect(lambda: self.window().go_name("Tarefas agendadas"))
        c.add(hbox(self.lb_clean, None, b_tasks))
        self._autoclean_info()
        self.add(c)

    def _autoclean_changed(self, _i):
        from ...core import schedule
        schedule.set_interval(schedule.get("clean"), int(self.cb_clean.currentData() or 0))
        self._autoclean_info()

    def _autoclean_info(self):
        self.cb_clean.blockSignals(True)
        self.cb_clean.setCurrentIndex(max(0, self.cb_clean.findData(int(get_setting("auto_clean_days") or 0))))
        self.cb_clean.blockSignals(False)
        last = float(get_setting("auto_clean_last") or 0)
        freed = int(get_setting("auto_clean_freed") or 0)
        parts = []
        if last and int(get_setting("auto_clean_days") or 0):
            parts.append("Última limpeza: " + time.strftime("%d/%m/%Y %H:%M", time.localtime(last)))
        if freed:
            parts.append(f"total libertado: {human_bytes(freed)}")
        self.lb_clean.setText(" · ".join(parts))

    # ------------------------------------------------------------------ cópia das definições
    def _build_backup(self):
        c = Card("Cópia das definições", "Guarde as suas definições (overlay, perfis por jogo, alertas, jogos "
                 "marcados…), o histórico dos benchmarks e das sessões de jogo num ficheiro — para levar para outro "
                 "PC ou repor depois de reinstalar.", icon="box")
        b_exp = QPushButton("Exportar…")
        b_exp.clicked.connect(self._export)
        b_imp = QPushButton("Importar…")
        b_imp.clicked.connect(self._import)
        c.add(SettingRow("Ficheiro .zip", "A posição da janela e outras coisas desta máquina não são copiadas.",
                         hbox(b_exp, b_imp)))
        self.add(c)

    def _export(self):
        import os
        from ...core import backup
        name = f"nexo-definicoes-{time.strftime('%Y-%m-%d')}.zip"
        path, _f = QFileDialog.getSaveFileName(self, "Exportar definições", os.path.join(os.path.expanduser("~"), name),
                                               "Cópia do Nexo (*.zip)")
        if not path:
            return
        run_async(backup.export, path, on_done=lambda p: notify(f"Definições exportadas para {p}", "ok"),
                  on_fail=lambda m: notify(f"Não foi possível exportar: {m}", "bad"))

    def _import(self):
        import os
        from ...core import backup
        path, _f = QFileDialog.getOpenFileName(self, "Importar definições", os.path.expanduser("~"),
                                               "Cópia do Nexo (*.zip)")
        if not path:
            return
        try:
            info = backup.read_backup(path)["manifest"]
        except backup.ImportErrorNexo as e:
            notify(str(e), "bad")
            return
        if not confirm(self, "Importar definições",
                       f"Substituir as definições atuais pelas da cópia de {info.get('created', '?')} "
                       f"({info.get('system', '?')})?\n\nAs atuais ficam guardadas em "
                       "settings.json.antes-de-importar. O Nexo reinicia no fim."):
            return
        try:
            res = backup.import_backup(path)
        except backup.ImportErrorNexo as e:
            notify(str(e), "bad")
            return
        notify(f"Importado: {res['settings']} definições, {res['bench']} benchmarks, {res['sessions']} sessões. "
               "A reiniciar…", "ok")
        win = self.window()
        if hasattr(win, "restart_app"):
            from PySide6.QtCore import QTimer
            QTimer.singleShot(1200, win.restart_app)

    # ------------------------------------------------------------------ atualizações do Nexo
    def _build_selfupdate(self):
        from ...core import selfupdate
        c = Card("Atualizações do Nexo", f"Versão instalada: {APP_NAME} {APP_VERSION}.", icon="upgrade")
        self.su_info = label("", "Muted", wrap=True)
        self.su_check = QPushButton("Procurar agora")
        self.su_check.clicked.connect(lambda: self._su_check(manual=True))
        self.su_install = QPushButton("Instalar e reiniciar")
        self.su_install.setObjectName("Primary")
        self.su_install.setVisible(False)
        self.su_install.clicked.connect(self._su_install)
        c.add(SettingRow("Procurar versões novas sozinho", "Uma vez por dia, só com internet. Nada é instalado "
                         "sem a sua autorização.", self._toggle("self_update_check")))
        c.add(separator())
        c.add(hbox(self.su_info, None, self.su_check, self.su_install))
        self._su_rel = None
        if not selfupdate.configured():
            self.su_info.setText("Esta cópia do Nexo não tem um endereço de atualizações configurado.")
            self.su_check.setEnabled(False)
        self.add(c)

    def show_release(self, rel):
        """Chamado pela janela principal quando a verificação diária encontra uma versão nova."""
        self._su_rel = rel
        if rel is None:
            self.su_info.setText("Tem a versão mais recente.")
            self.su_install.setVisible(False)
            return
        notes = rel.notes.splitlines()
        short = "<br>".join(n for n in notes[:8] if n.strip())
        self.su_info.setText(f"<b>Versão {rel.version} disponível.</b>"
                             + (f"<br>{short}" if short else "")
                             + (f"<br><a href='{rel.url}'>Ver todas as novidades</a>" if rel.url else ""))
        self.su_info.setOpenExternalLinks(True)
        self.su_install.setVisible(True)

    def _su_check(self, manual=False):
        from ...core import selfupdate
        from ..netmonitor import require_online
        if not require_online("Procurar atualizações do Nexo"):
            return
        self.su_check.setEnabled(False)
        self.su_info.setText("A procurar…")

        def done(rel):
            self.su_check.setEnabled(True)
            set_setting("self_update_last", time.time())
            self.show_release(rel)

        def fail(m):
            self.su_check.setEnabled(True)
            from ...core.network import friendly_error
            self.su_info.setText(f"Não foi possível procurar: {friendly_error(m)}")
        run_async(selfupdate.check, on_done=done, on_fail=fail)

    def _su_install(self):
        from ...core import selfupdate
        rel = self._su_rel
        if rel is None:
            return
        if not selfupdate.frozen():
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl(rel.url))
            notify("Este Nexo corre a partir do código ou do pacote do sistema: atualize com git pull ou com o gestor de pacotes. Abri a página da versão.", "info")
            return
        if not confirm(self, "Atualizar o Nexo", f"Transferir e instalar o Nexo {rel.version}? O Nexo reinicia no fim."):
            return
        self.su_install.setEnabled(False)
        self.su_info.setText("A transferir…")

        def done(_p):
            notify(f"Nexo {rel.version} instalado. A reiniciar…", "ok")
            win = self.window()
            if hasattr(win, "restart_app"):
                win.restart_app()

        def fail(m):
            self.su_install.setEnabled(True)
            self.su_info.setText(f"A atualização falhou: {m}")
            notify(f"A atualização falhou: {m}", "bad")
        run_async(selfupdate.install, rel, on_done=done, on_fail=fail)

    # ------------------------------------------------------------------ aparência
    def _build_appearance(self):
        ap = Card("Aparência", "Escolha o tema da aplicação. Para mudar o fundo do computador use a página "
                  "'Fundo de ecrã'.", icon="sun")
        self.theme_btns: dict[str, QPushButton] = {}
        row = hbox()
        for key, t in theme.THEMES.items():
            b = QPushButton(("☾  " if not t["light"] else "☀  ") + t["name"])
            b.setCheckable(True)
            b.setMinimumWidth(140)
            b.setChecked(key == theme.current())
            b.clicked.connect(lambda _c=False, k=key: self._pick_theme(k))
            self.theme_btns[key] = b
            row.addWidget(b)
        b_wp = QPushButton("Mudar o fundo do ambiente de trabalho…")
        b_wp.clicked.connect(lambda: self.window().go_name("Fundo de ecrã"))
        row.addStretch(1)
        row.addWidget(b_wp)
        ap.add(row)
        ap.add(separator())
        from ...core import i18n
        self.lang_cb = QComboBox()
        for k, v in i18n.LANGS.items():
            self.lang_cb.addItem(v, k)
        self.lang_cb.setCurrentIndex(max(0, self.lang_cb.findData(i18n.lang())))
        self.lang_cb.currentIndexChanged.connect(self._lang_changed)
        ap.add(SettingRow("Idioma", "Idioma da interface. Muda depois de reiniciar o Nexo.", self.lang_cb))
        self.add(ap)

    def _lang_changed(self, _i):
        from ...core import i18n
        new = self.lang_cb.currentData()
        set_setting("language", new)
        if new == i18n.lang():
            return
        if confirm(self, "Idioma / Language", "Reiniciar o Nexo agora para mudar o idioma?\n"
                   "Restart Nexo now to change the language?"):
            win = self.window()
            if hasattr(win, "restart_app"):
                win.restart_app()

    def _pick_theme(self, key):
        for k, b in self.theme_btns.items():
            b.setChecked(k == key)
        set_setting("theme", key)
        self._on_change("theme")

    def on_show(self):
        for k, b in self.theme_btns.items():
            b.setChecked(k == theme.current())
        win = self.window()
        rel = getattr(win, "_pending_release", None)
        if rel is not None and self._su_rel is None:
            self.show_release(rel)
        if hasattr(win, "set_nav_badge"):
            win.set_nav_badge("Definições", None)
        self._autoclean_info()
        self.web.on_show()

    # ------------------------------------------------------------------
    def _toggle(self, key) -> Toggle:
        tg = Toggle(bool(get_setting(key)))
        tg.clicked.connect(lambda checked, k=key: self._set(k, bool(checked)))
        return tg

    def _spin(self, key, lo, hi, suffix=" °C") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(suffix)
        sp.setValue(int(get_setting(key)))
        sp.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
        return sp

    def _set(self, key, value):
        set_setting(key, value)
        self._on_change(key)

    # ------------------------------------------------------------------ proteção
    def _build_protection(self):
        b = snapshot.backend()
        pr = Card("Proteção (pontos de restauro)",
                  "Antes de ligar ajustes, remover apps ou pacotes, o Nexo cria um ponto de restauro para poder "
                  "voltar atrás se algo correr mal. No máximo um a cada 30 minutos.", icon="shield")
        self.tg_snap = self._toggle("snapshot_before")
        self.tg_snap.setEnabled(b is not None)
        pr.add(SettingRow("Criar ponto de restauro antes de alterar o sistema",
                          f"Sistema usado: {snapshot.backend_label(b)}." + (
                              " No Windows só funciona com o Nexo como administrador." if b == "windows" else "")
                          + ("" if b else " Instale e configure o snapper ou o Timeshift (modo btrfs) para ativar."),
                          self.tg_snap))
        if b:
            pr.add(separator())
            self.btn_snap = QPushButton("Criar ponto agora")
            self.btn_snap.clicked.connect(self._snap_now)
            self.snap_info = label(snapshot.how_to_restore(b), "Muted", wrap=True)
            pr.add(hbox(self.snap_info, self.btn_snap))
            self.snap_list = label("", "Muted", wrap=True)
            pr.add(self.snap_list)
            run_async(snapshot.list_recent, on_done=self._show_snaps, on_fail=lambda _m: None)
        self.add(pr)

    def _show_snaps(self, rows):
        if rows:
            self.snap_list.setText("<b>Últimos pontos do Nexo:</b><br>"
                                   + "<br>".join(f"{d} — {t}" for d, t in rows))

    def _snap_now(self):
        self.btn_snap.setEnabled(False)
        self.btn_snap.setText("A criar…")

        def done(res):
            ok, msg = res
            self.btn_snap.setEnabled(True)
            self.btn_snap.setText("Criar ponto agora")
            notify(msg, "ok" if ok else "bad")
            if ok:
                run_async(snapshot.list_recent, on_done=self._show_snaps, on_fail=lambda _m: None)
        run_async(snapshot.create, "alterações manuais", on_done=done,
                  on_fail=lambda m: (done((False, m))))

    def _clear_history(self):
        if not confirm(self, "Apagar histórico", "Apagar todo o histórico guardado dos sensores?"):
            return
        hub = getattr(self.window(), "hub", None)
        try:
            (hub.record if hub else history.History()).clear()
            notify("Histórico apagado.", "ok")
        except Exception as e:  # noqa: BLE001
            notify(f"Não foi possível apagar: {e}", "bad")

    def _open_log(self):
        from ...core import log as nlog
        p = nlog.log_path()
        if not p.exists():
            notify("Ainda não há registo de erros.", "info")
            return
        open_path(p)

    def _copy_diag(self):
        from PySide6.QtGui import QGuiApplication
        from ...core import log as nlog
        QGuiApplication.clipboard().setText(nlog.diagnostic_report())
        notify("Diagnóstico copiado — cole-o no relatório do problema.", "ok")

    def _autostart(self, on):
        ok, msg = startup.set_self_autostart(bool(on))
        notify(msg, "ok" if ok else "bad")
        if not ok:
            self.tg_auto.setChecked(not on)
