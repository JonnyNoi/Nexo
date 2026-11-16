"""Assistente de boas-vindas (primeira execução) e janela de atalhos de teclado (F1)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from ..core import schedule, snapshot, startup
from ..core.util import APP_NAME, get_setting, set_setting
from . import logo as logo_mod
from . import theme
from .widgets import SettingRow, Toggle, icon_badge, label, separator

SHORTCUTS = [
    ("Ctrl+K", "Pesquisa rápida: páginas, funções e opções"),
    ("Ctrl+1 … Ctrl+9", "Ir para a entrada do menu com esse número"),
    ("Ctrl+Tab / Ctrl+Shift+Tab", "Página seguinte / anterior"),
    ("Ctrl+B", "Menu compacto (só ícones)"),
    ("Ctrl+Shift+A", "Centro de alertas"),
    ("F5", "Atualizar a página aberta"),
    ("Ctrl+,", "Definições"),
    ("F1", "Esta lista de atalhos"),
    ("Tab / Shift+Tab", "Saltar entre botões e opções (o elemento com foco fica contornado)"),
    ("Espaço / Enter", "Carregar no botão ou interruptor com foco"),
    ("Esc", "Fechar a pesquisa, os alertas ou uma janela"),
    ("Ctrl+Q", "Sair do Nexo"),
]


def _dialog_css() -> str:
    c = theme.C
    return (f"QDialog {{ background: {c['surface']}; }}"
            f"QFrame#WizCard {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 14px; }}"
            f"QLabel#WizTitle {{ font-size: 22px; font-weight: 800; }}"
            f"QLabel#Kbd {{ background: {c['surface3']}; border: 1px solid {c['border2']}; border-radius: 6px; "
            f"padding: 2px 8px; font-weight: 700; }}")


def shortcuts_grid() -> QGridLayout:
    g = QGridLayout()
    g.setHorizontalSpacing(16)
    g.setVerticalSpacing(8)
    for r, (keys, what) in enumerate(SHORTCUTS):
        k = QLabel(keys)
        k.setObjectName("Kbd")
        g.addWidget(k, r, 0, Qt.AlignLeft)
        g.addWidget(label(what, wrap=True), r, 1)
    g.setColumnStretch(1, 1)
    return g


class ShortcutsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"{APP_NAME} — atalhos de teclado")
        self.setStyleSheet(_dialog_css())
        v = QVBoxLayout(self)
        v.setContentsMargins(24, 22, 24, 18)
        v.setSpacing(14)
        v.addWidget(label("Atalhos de teclado", "WizTitle"))
        v.addLayout(shortcuts_grid())
        b = QPushButton("Fechar")
        b.setObjectName("Primary")
        b.clicked.connect(self.accept)
        b.setDefault(True)
        v.addWidget(b, 0, Qt.AlignRight)
        self.resize(560, 0)


class Wizard(QDialog):
    """Seis passos curtos. Tudo o que se escolhe aqui pode ser mudado depois nas Definições."""

    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.go_to: str | None = None   # página a abrir no fim
        self.setWindowTitle(f"Bem-vindo ao {APP_NAME}")
        self.setModal(True)
        self.setStyleSheet(_dialog_css())
        self.resize(720, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(28, 24, 28, 20)
        v.setSpacing(14)
        self.stack = QStackedWidget()
        v.addWidget(self.stack, 1)
        for build in (self._welcome, self._look, self._protect, self._tasks, self._games, self._done):
            page = QWidget()
            page.setObjectName("Transparent")
            lay = QVBoxLayout(page)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(12)
            build(lay)
            lay.addStretch(1)
            self.stack.addWidget(page)
        v.addWidget(separator())
        nav = QHBoxLayout()
        self.b_skip = QPushButton("Saltar")
        self.b_skip.setObjectName("Ghost")
        self.b_skip.setToolTip("Fechar o assistente e ficar com as opções recomendadas")
        self.b_skip.clicked.connect(self.finish)
        self.step_lbl = label("", "Muted")
        self.b_back = QPushButton("Anterior")
        self.b_back.clicked.connect(lambda: self._step(-1))
        self.b_next = QPushButton("Seguinte")
        self.b_next.setObjectName("Primary")
        self.b_next.setDefault(True)
        self.b_next.clicked.connect(lambda: self._step(1))
        nav.addWidget(self.b_skip)
        nav.addStretch(1)
        nav.addWidget(self.step_lbl)
        nav.addSpacing(12)
        nav.addWidget(self.b_back)
        nav.addWidget(self.b_next)
        v.addLayout(nav)
        self._update_nav()

    # ------------------------------------------------------------------ passos
    @staticmethod
    def _head(lay, icon: str, title: str, text: str):
        h = QHBoxLayout()
        h.setSpacing(14)
        h.addWidget(icon_badge(icon, 44, 22), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(4)
        col.addWidget(label(title, "WizTitle"))
        col.addWidget(label(text, "Muted", wrap=True))
        h.addLayout(col, 1)
        lay.addLayout(h)

    def _card(self, lay) -> QVBoxLayout:
        f = QFrame()
        f.setObjectName("WizCard")
        v = QVBoxLayout(f)
        v.setContentsMargins(16, 10, 16, 10)
        v.setSpacing(2)
        lay.addWidget(f)
        return v

    def _toggle(self, key: str) -> Toggle:
        t = Toggle(bool(get_setting(key)))
        t.clicked.connect(lambda on, k=key: set_setting(k, bool(on)))
        return t

    def _welcome(self, lay):
        top = QHBoxLayout()
        lg = QLabel()
        lg.setPixmap(logo_mod.pixmap(72, theme.logo_colors()))
        top.addWidget(lg, 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.addWidget(label(f"Bem-vindo ao {APP_NAME}", "WizTitle"))
        col.addWidget(label("Monitoriza, protege e otimiza o seu PC — em Linux e Windows. Em menos de um minuto "
                            "deixamo-lo à sua medida; tudo pode ser mudado depois em Definições.", "Muted", wrap=True))
        top.addLayout(col, 1)
        lay.addLayout(top)
        card = self._card(lay)
        for ic, t, d in (("thermo", "Ver", "Temperaturas, carga, discos e saúde do PC em tempo real."),
                         ("shield", "Proteger", "Avisos, antivírus, pontos de restauro antes de mexer no sistema."),
                         ("zap", "Otimizar", "Limpeza, arranque, testes e um modo jogo com overlay e perfis.")):
            h = QHBoxLayout()
            h.setSpacing(12)
            h.addWidget(icon_badge(ic, 32, 16))
            h.addWidget(label(f"<b>{t}</b> — {d}", wrap=True), 1)
            card.addLayout(h)

    def _look(self, lay):
        self._head(lay, "sun", "Aparência", "Escolha o tema. Muda já, para ver como fica.")
        h = QHBoxLayout()
        self.theme_btns = {}
        for key, t in theme.THEMES.items():
            b = QPushButton(("☀  " if t["light"] else "☾  ") + t["name"])
            b.setCheckable(True)
            b.setMinimumHeight(64)
            b.setChecked(key == theme.current())
            b.clicked.connect(lambda _c=False, k=key: self._pick_theme(k))
            self.theme_btns[key] = b
            h.addWidget(b)
        lay.addLayout(h)
        card = self._card(lay)
        card.addWidget(SettingRow("Menu compacto", "Só ícones no menu lateral, para dar mais espaço às páginas "
                                  "(Ctrl+B alterna a qualquer momento).", self._compact_toggle()))

    def _compact_toggle(self) -> Toggle:
        t = Toggle(bool(get_setting("nav_compact", False)))
        t.clicked.connect(lambda on: self.win.set_compact(bool(on)))
        return t

    def _pick_theme(self, key):
        for k, b in self.theme_btns.items():
            b.setChecked(k == key)
        self.win.set_theme(key)
        self.setStyleSheet(_dialog_css())

    def _protect(self, lay):
        self._head(lay, "shield", "Avisos e proteção", "O que o Nexo vigia por si, mesmo minimizado na bandeja.")
        card = self._card(lay)
        alerts = Toggle(bool(get_setting("alerts")))

        def set_alerts(on):
            for k in ("alerts", "alert_ram", "alert_disk", "alert_smart"):
                set_setting(k, bool(on))
        alerts.clicked.connect(set_alerts)
        card.addWidget(SettingRow("Avisos importantes", "Temperatura alta, memória quase cheia, pouco espaço em disco "
                                  "e saúde dos discos a piorar. Ficam no centro de alertas (sino).", alerts))
        b = snapshot.backend()
        if b:
            card.addWidget(separator())
            card.addWidget(SettingRow("Pontos de restauro", f"Antes de alterar o sistema, cria um ponto para voltar "
                                      f"atrás ({snapshot.backend_label(b)}).", self._toggle("snapshot_before")))
        card.addWidget(separator())
        card.addWidget(SettingRow("Ícone na bandeja", "Temperatura sempre à vista; clique para abrir.",
                                  self._tray_toggle()))
        card.addWidget(separator())
        auto = Toggle(startup.self_autostart_enabled())
        auto.clicked.connect(lambda on: startup.set_self_autostart(bool(on)))
        card.addWidget(SettingRow("Abrir com o sistema", "Arranca minimizado quando entra na sessão — os avisos e as "
                                  "tarefas agendadas só funcionam com o Nexo aberto.", auto))

    def _tray_toggle(self) -> Toggle:
        t = Toggle(bool(get_setting("tray")))

        def changed(on):
            set_setting("tray", bool(on))
            self.win._setting_changed("tray")
        t.clicked.connect(changed)
        return t

    def _tasks(self, lay):
        self._head(lay, "clock", "Tarefas automáticas", "O que o Nexo faz sozinho de tempos a tempos (nunca durante "
                   "um jogo). Pode ver e mudar tudo em Utilitários → Tarefas agendadas.")
        card = self._card(lay)
        for i, t in enumerate(schedule.tasks()):
            if i:
                card.addWidget(separator())
            cb = QComboBox()
            for days, txt in schedule.INTERVALS.items():
                cb.addItem(txt, days)
            cb.setCurrentIndex(max(0, cb.findData(schedule.interval(t))))
            cb.currentIndexChanged.connect(lambda _i, t=t, cb=cb: schedule.set_interval(t, int(cb.currentData() or 0)))
            card.addWidget(SettingRow(t.name, t.desc, cb))

    def _games(self, lay):
        self._head(lay, "gamepad", "Jogos", "O modo jogo deteta Steam, Proton, Wine, Lutris, Heroic, "
                   "Epic, GOG e Xbox.")
        card = self._card(lay)
        card.addWidget(SettingRow("Detetar jogos", "Verifica a cada 4 segundos (quase não gasta nada).",
                                  self._toggle("game_detect")))
        card.addWidget(separator())
        card.addWidget(SettingRow("Overlay ao jogar", "Temperaturas, FPS e uso por cima do jogo.",
                                  self._toggle("overlay_auto")))

    def _done(self, lay):
        self._head(lay, "check", "Pronto!", "O menu está agrupado: SISTEMA para ver o estado do PC, DESEMPENHO para "
                   "o otimizar e FERRAMENTAS para o resto. Comece pela Visão geral — a «Saúde do PC» diz o que vale "
                   "a pena fazer.")
        card = self._card(lay)
        card.addWidget(label("<b>Atalhos úteis</b>"))
        card.addLayout(shortcuts_grid())

    # ------------------------------------------------------------------ navegação
    def _step(self, d: int):
        i = self.stack.currentIndex() + d
        if i >= self.stack.count():
            self.finish()
            return
        self.stack.setCurrentIndex(max(0, i))
        self._update_nav()

    def _update_nav(self):
        i, n = self.stack.currentIndex(), self.stack.count()
        self.step_lbl.setText(f"Passo {i + 1} de {n}")
        self.b_back.setEnabled(i > 0)
        last = i == n - 1
        self.b_next.setText("Começar" if last else "Seguinte")
        self.b_skip.setVisible(not last)

    def finish(self):
        set_setting("wizard_done", True)
        self.accept()

    def reject(self):   # Esc / fechar a janela = saltar
        set_setting("wizard_done", True)
        super().reject()
