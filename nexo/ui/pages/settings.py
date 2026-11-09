from __future__ import annotations

from PySide6.QtWidgets import QPushButton, QSpinBox

from ...core import startup
from ...core.util import APP_NAME, APP_VERSION, config_dir, get_setting, open_path, set_setting
from .. import theme
from ..widgets import Card, Page, SettingRow, Toggle, hbox, label, notify, separator

class SettingsPage(Page):
    def __init__(self, on_change=None):
        super().__init__("Definições", "Aparência, alertas, bandeja do sistema, arranque e dados do Nexo")
        self._on_change = on_change or (lambda _k: None)
        self._build_appearance()

        # ---------------------------------------------------------------- alertas
        al = Card("Alertas de temperatura",
                  "Aviso (notificação do sistema + mensagem na janela) quando a CPU ou a GPU passam do limite. "
                  "No máximo um aviso a cada 5 minutos por componente.", icon="thermo")
        self.tg_alerts = self._toggle("alerts")
        al.add(SettingRow("Avisar quando aquecer demais", "Funciona também com a janela minimizada na bandeja.",
                          self.tg_alerts))
        al.add(separator())
        self.sp_cpu = self._spin("alert_cpu", 60, 105)
        al.add(SettingRow("Limite da CPU", "A maioria das CPUs desktop começa a reduzir o clock perto dos 95–100 °C.",
                          self.sp_cpu))
        al.add(separator())
        self.sp_gpu = self._spin("alert_gpu", 60, 105)
        al.add(SettingRow("Limite da GPU", "GPUs dedicadas trabalham normalmente abaixo dos 85 °C.", self.sp_gpu))
        self.add(al)

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

        # ---------------------------------------------------------------- dados / sobre
        about = Card("Dados e informação", icon="info")
        btn_dir = QPushButton("Abrir pasta de dados")
        btn_dir.clicked.connect(lambda: open_path(config_dir()))
        btn_log = QPushButton("Abrir registo de erros")
        btn_log.setToolTip("nexo.log: erros e avisos do Nexo (útil para reportar um problema)")
        btn_log.clicked.connect(self._open_log)
        about.add(hbox(label(f"{APP_NAME} {APP_VERSION} · dados em {config_dir()}", "Muted", wrap=True), None,
                       btn_log, btn_dir))
        about.add(label("<b>Atalhos:</b> Ctrl+1…Ctrl+9 mudar de página · Ctrl+Tab página seguinte · "
                        "F5 atualizar · Ctrl+, definições · Ctrl+Q sair", "Muted", wrap=True))
        self.add(about)
        self.body.addStretch(1)

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
        self.add(ap)

    def _pick_theme(self, key):
        for k, b in self.theme_btns.items():
            b.setChecked(k == key)
        set_setting("theme", key)
        self._on_change("theme")

    def on_show(self):
        for k, b in self.theme_btns.items():
            b.setChecked(k == theme.current())

    # ------------------------------------------------------------------
    def _toggle(self, key) -> Toggle:
        tg = Toggle(bool(get_setting(key)))
        tg.clicked.connect(lambda checked, k=key: self._set(k, bool(checked)))
        return tg

    def _spin(self, key, lo, hi) -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(lo, hi)
        sp.setSuffix(" °C")
        sp.setValue(int(get_setting(key)))
        sp.valueChanged.connect(lambda v, k=key: self._set(k, int(v)))
        return sp

    def _set(self, key, value):
        set_setting(key, value)
        self._on_change(key)

    def _open_log(self):
        from ...core import log as nlog
        p = nlog.log_path()
        if not p.exists():
            notify("Ainda não há registo de erros.", "info")
            return
        open_path(p)

    def _autostart(self, on):
        ok, msg = startup.set_self_autostart(bool(on))
        notify(msg, "ok" if ok else "bad")
        if not ok:
            self.tg_auto.setChecked(not on)
