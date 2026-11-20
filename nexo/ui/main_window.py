from __future__ import annotations

import logging

from PySide6.QtCore import QByteArray, QEasingCurve, QPropertyAnimation, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QBoxLayout, QButtonGroup, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QPushButton, QScrollArea, QStackedWidget, QSystemTrayIcon,
                               QTableWidget, QVBoxLayout, QWidget)

from ..core.util import APP_NAME, APP_VERSION, IS_WIN, get_setting, is_admin, os_label, relaunch_as_admin, set_setting
from . import theme
from . import logo as logo_mod
from .icons import icon as make_icon
from .mw_background import BackgroundMixin
from .mw_game import GameMixin
from .nav import SIDE_COMPACT_W, SIDE_W, BellButton, LiveBox, NavButton, NavSection, Toast, app_icon
from .widgets import SensorHub, label, set_notify_target


def _page_factories(hub, on_settings):
    """(secção, [(nome, ícone, fábrica)]). As páginas só são criadas quando abertas pela primeira vez —
    o arranque fica mais rápido e páginas nunca visitadas não gastam memória nem CPU.
    As importações estão escritas por extenso (dentro de funções) para o PyInstaller as encontrar."""
    def dashboard():
        from .pages.dashboard import DashboardPage
        return DashboardPage(hub)

    def system():
        from .pages.system import SystemPage
        return SystemPage()

    def sensors():
        from .pages.sensors import SensorsPage
        return SensorsPage(hub)

    def processes():
        from .pages.processes import ProcessesPage
        return ProcessesPage()

    def stress():
        from .pages.stress import StressPage
        return StressPage(hub)

    def benchmark():
        from .pages.benchmark import BenchmarkPage
        return BenchmarkPage()

    def optimize():
        from .pages.optimize import OptimizePage
        return OptimizePage()

    def apps():
        from .pages.apps import AppsPage
        return AppsPage()

    def tools():
        from .pages.tools import ToolsPage
        return ToolsPage()

    def antivirus():
        from .pages.antivirus import AntivirusPage
        return AntivirusPage()

    def startup():
        from .pages.startup import StartupPage
        return StartupPage()

    def peripherals():
        from .pages.peripherals import PeripheralsPage
        return PeripheralsPage()

    def privacy():
        from .pages.privacy import PrivacyPage
        return PrivacyPage()

    def debloat():
        from .pages.debloat import DebloatPage
        return DebloatPage()

    def disk():
        from .pages.disk import DiskPage
        return DiskPage()

    def gamemode():
        from .pages.gamemode import GameModePage
        return GameModePage()

    def tasks():
        from .pages.tasks import TasksPage
        return TasksPage()

    def wallpaper():
        from .pages.wallpaper import WallpaperPage
        return WallpaperPage()

    def internet():
        from .pages.internet import InternetPage
        return InternetPage()

    def reliability():
        from .pages.reliability import ReliabilityPage
        return ReliabilityPage()

    def diskhealth():
        from .pages.diskhealth import DiskHealthPage
        return DiskHealthPage()

    def updates():
        from .pages.updates import UpdatesPage
        return UpdatesPage()

    def battery():
        from .pages.battery import BatteryPage
        return BatteryPage()

    def programs():
        from .pages.programs import ProgramsPage
        return ProgramsPage()

    def energy():
        from .pages.energy import EnergyPage
        return EnergyPage(hub)

    def upgrade():
        from .pages.upgrade import UpgradePage
        return UpgradePage()

    def snapshots():
        from .pages.snapshots import SnapshotsPage
        return SnapshotsPage()

    def settings():
        from .pages.settings import SettingsPage
        return SettingsPage(on_settings)

    # Uma entrada do menu pode juntar várias páginas: (nome no menu, ícone, [(página, ícone, fábrica), …]).
    # As páginas de um grupo aparecem como separadores no topo do conteúdo.
    opt = [("Otimização", "zap", optimize), ("Arranque", "power", startup)]
    if IS_WIN:
        opt.append(("Windows debloat", "broom", debloat))
    else:
        opt.append(("Privacidade", "shield", privacy))
    from ..core import battery as _bat
    try:
        has_bat = _bat.has_battery()
    except Exception:  # noqa: BLE001 — nunca impedir o arranque da janela
        has_bat = False
    sysitems = [("Informação", "info", system), ("Sensores", "thermo", sensors)]
    if has_bat:
        sysitems.append(("Bateria", "battery", battery))
    sysitems.append(("Periféricos", "keyboard", peripherals))
    sysitems.append(("Energia", "zap", energy))
    util = [("Utilitários", "wrench", tools), ("Tarefas agendadas", "clock", tasks)]
    if not IS_WIN:
        util.append(("Snapshots", "shield", snapshots))
    return [
        (None, [("Visão geral", "home", dashboard)]),
        ("SISTEMA", [*sysitems,
                     ("Discos", "hdd", [("Saúde dos discos", "hdd", diskhealth),
                                        ("Espaço em disco", "disk", disk)]),
                     ("Processos", "list", processes),
                     ("Fiabilidade", "chart", reliability),
                     ("Antivírus", "virus", antivirus)]),
        ("DESEMPENHO", [("Otimização", "zap", opt),
                        ("Modo jogo", "gamepad", gamemode),
                        ("Testes", "gauge", [("Benchmark", "gauge", benchmark),
                                             ("Stress test", "flame", stress),
                                             ("O que melhorar", "upgrade", upgrade)])]),
        ("FERRAMENTAS", [("Software", "upgrade", [("Atualizações", "upgrade", updates),
                                                  ("Instalar aplicações", "download", apps),
                                                  ("Programas instalados", "package", programs)]),
                         ("Internet", "wifi", internet),
                         ("Utilitários", "wrench", util),
                         ("Fundo de ecrã", "image", wallpaper)]),
        (None, [("Definições", "gear", settings)]),
    ]



class MainWindow(BackgroundMixin, GameMixin, QMainWindow):
    def __init__(self, start_hidden: bool = False):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} {APP_VERSION}")
        self.setWindowIcon(app_icon())
        self.resize(1380, 880)
        self.setMinimumSize(1080, 660)
        self.hub = SensorHub()
        self._quitting = False

        root = QWidget()
        root.setObjectName("Root")
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # ------------------------------------------------------------- menu lateral
        side = QFrame()
        side.setObjectName("Sidebar")
        self.side = side
        self.compact = bool(get_setting("nav_compact", False))
        side.setFixedWidth(SIDE_COMPACT_W if self.compact else SIDE_W)
        sv = QVBoxLayout(side)
        sv.setContentsMargins(12, 18, 12, 12)
        sv.setSpacing(0)
        brand = QHBoxLayout()
        brand.setSpacing(10)
        brand.setContentsMargins(6, 0, 0, 0)
        self.logo_ic = QLabel()
        self.logo_ic.setPixmap(logo_mod.pixmap(34, theme.logo_colors()))
        brand.addWidget(self.logo_ic)
        self.brand_text = QWidget()
        self.brand_text.setObjectName("Transparent")
        col = QVBoxLayout(self.brand_text)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(0)
        self.logo = label(APP_NAME.upper(), "Logo")
        col.addWidget(self.logo)
        col.addWidget(label(os_label(), "Muted"))
        brand.addWidget(self.brand_text, 1)
        sv.addLayout(brand)
        sv.addSpacing(14)
        self.btn_search = QPushButton("  Procurar…")
        self.btn_search.setObjectName("SearchBtn")
        self.btn_search.setCursor(Qt.PointingHandCursor)
        self.btn_search.setToolTip("Pesquisa rápida: páginas, funções, opções e temas (Ctrl+K)")
        self.btn_search.clicked.connect(self.open_palette)
        kb = QHBoxLayout(self.btn_search)
        kb.setContentsMargins(0, 0, 10, 0)
        kb.addStretch(1)
        self.kb_badge = label("Ctrl+K", "Badge")
        kb.addWidget(self.kb_badge)
        sv.addWidget(self.btn_search)
        sv.addSpacing(4)
        self.btn_search.setIcon(make_icon("search", theme.C["muted"]))
        self.btn_search.setAccessibleName("Pesquisa rápida")

        nav_w = QWidget()
        nav_w.setObjectName("Transparent")
        nv = QVBoxLayout(nav_w)
        nv.setContentsMargins(0, 0, 4, 0)
        nv.setSpacing(2)
        self.nav_layout = nv
        scroll = QScrollArea()
        self.nav_scroll = scroll
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        scroll.setWidget(nav_w)
        sv.addWidget(scroll, 1)

        self.stack = QStackedWidget()
        self.nav = QButtonGroup(self)
        self.nav.setExclusive(True)
        # listas por PÁGINA (índice do QStackedWidget)
        self.pages: list = []          # None até a página ser criada
        self.factories: list = []
        self.names: list[str] = []
        self.icons: list[str] = []
        self.btn_of: list[NavButton] = []        # botão do menu de cada página
        self.group_of: list[list[int]] = []      # páginas que partilham o mesmo botão
        self.badges: dict[int, tuple[str, str]] = {}
        # listas por BOTÃO do menu
        self.nav_buttons: list[NavButton] = []
        self.nav_icons: list[str] = []
        self.groups: list[list[int]] = []
        self._last_in_group: dict[int, int] = {}  # 1.ª página do grupo → última aberta
        self.sections: list[tuple[NavSection, list[NavButton]]] = []
        self.section_of: dict[int, NavSection] = {}
        collapsed = set(get_setting("nav_collapsed", []) or [])
        for title, items in _page_factories(self.hub, self._setting_changed):
            sec = None
            if title:
                nv.addSpacing(10)
                sec = NavSection(title)
                sec.collapsed = title in collapsed
                sec.clicked.connect(lambda _c=False, t=sec: self._toggle_section(t))
                nv.addWidget(sec)
                self.sections.append((sec, []))
            elif self.pages:
                nv.addStretch(1)  # "Definições" fica no fundo
                nv.addSpacing(10)
            for nav_name, nav_ic, what in items:
                members = what if isinstance(what, list) else [(nav_name, nav_ic, what)]
                b = NavButton(nav_name)
                group: list[int] = []
                for name, ic, factory in members:
                    idx = self.stack.addWidget(QWidget())  # marcador até a página ser criada
                    self.pages.append(None)
                    self.factories.append(factory)
                    self.names.append(name)
                    self.icons.append(ic)
                    self.btn_of.append(b)
                    self.group_of.append(group)
                    group.append(idx)
                    if sec is not None:
                        self.section_of[idx] = sec
                if len(group) > 1:
                    b.setToolTip(" · ".join(self.names[i] for i in group))
                self.nav_buttons.append(b)
                self.nav_icons.append(nav_ic)
                self.groups.append(group)
                b.clicked.connect(lambda _c, g=group: self.go(self._group_target(g)))
                self.nav.addButton(b, len(self.nav_buttons) - 1)
                nv.addWidget(b)
                if sec is not None:
                    self.sections[-1][1].append(b)
        self._paint_nav_icons()

        sv.addSpacing(10)
        self.live = LiveBox()
        sv.addWidget(self.live)
        sv.addSpacing(8)
        self.bottom = QBoxLayout(QBoxLayout.LeftToRight)
        self.bottom.setSpacing(6)
        self.btn_theme = QPushButton()
        self.btn_theme.setToolTip("Tema escuro ou claro")
        self.btn_theme.setAccessibleName("Tema")
        self.theme_menu = QMenu(self)
        self.btn_theme.setMenu(self.theme_menu)
        self.theme_menu.aboutToShow.connect(self._fill_theme_menu)
        self.bottom.addWidget(self.btn_theme, 1)
        self.btn_admin = None
        if IS_WIN and not is_admin():
            adm = QPushButton("Admin")
            adm.setToolTip("Reabrir com privilégios de administrador")
            adm.setIcon(make_icon("shield", theme.C["text"]))
            adm.clicked.connect(self._elevate)
            self.bottom.addWidget(adm)
            self.btn_admin = adm
        self.btn_bell = BellButton()
        self.btn_bell.clicked.connect(self.open_alerts)
        self.btn_bell.setIcon(make_icon("bell", theme.C["text"]))
        self.bottom.addWidget(self.btn_bell)
        self.btn_compact = QPushButton()
        self.btn_compact.setFixedSize(36, 36)
        self.btn_compact.setCursor(Qt.PointingHandCursor)
        self.btn_compact.clicked.connect(lambda: self.set_compact(not self.compact))
        self.btn_compact.setAccessibleName("Menu compacto")
        self.btn_compact.setIcon(make_icon("sidebar", theme.C["text"]))
        self.bottom.addWidget(self.btn_compact)
        sv.addLayout(self.bottom)
        self._apply_compact(self.compact)
        self._apply_sections()
        h.addWidget(side)

        # ------------------------------------------------------------- conteúdo
        self.right = QWidget()
        rv = QVBoxLayout(self.right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(0)
        self.subtabs = QFrame()
        self.subtabs.setObjectName("SubTabs")
        st = QHBoxLayout(self.subtabs)
        st.setContentsMargins(28, 12, 28, 12)
        st.setSpacing(8)
        self.subtabs_layout = st
        self.subtab_btns: dict[int, QPushButton] = {}
        self.subtabs.hide()
        rv.addWidget(self.subtabs)
        rv.addWidget(self.stack, 1)
        h.addWidget(self.right, 1)
        self.setCentralWidget(root)
        self.toast = Toast(self.right)
        self.palette_box = None  # pesquisa rápida, criada na primeira utilização
        self.alert_box = None    # centro de alertas, criado na primeira utilização
        set_notify_target(self.notify)

        # ------------------------------------------------------------- bandeja, atalhos, estado
        self.tray: QSystemTrayIcon | None = None
        self._tray_text = None
        self._setup_tray()
        self.refresh_alert_badge()
        self._setup_shortcuts()
        geo = get_setting("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except (ValueError, TypeError, AttributeError):
                logging.getLogger("nexo").debug("Geometria guardada inválida", exc_info=True)

        self.hub.updated.connect(self._live)
        self.hub.alert.connect(self._alert)
        # ligação à internet
        from .netmonitor import monitor
        self.net = monitor()
        self.net.checked.connect(self._net_changed)
        self.live.on_net_click = self._net_recheck
        self.net.start()
        self._init_game()
        self._init_background()
        self._init_web()
        self.current = -1
        last = get_setting("last_page_name") if get_setting("remember_page") else None
        self.go(self.names.index(last) if last in self.names else 0)
        self._start_hidden = start_hidden and self.tray is not None

    # ------------------------------------------------------------------ menu lateral
    def _paint_nav_icons(self):
        c = theme.C
        for b, ic in zip(self.nav_buttons, self.nav_icons):
            b.setIcon(make_icon(ic, c["muted"], c["accent"]))
        if hasattr(self, "btn_compact"):
            self.btn_compact.setIcon(make_icon("sidebar", c["text"]))
            self.btn_bell.setIcon(make_icon("bell", c["text"]))
        for i, b in getattr(self, "subtab_btns", {}).items():
            b.setIcon(make_icon(self.icons[i], c["muted"], c["accent_text"]))

    def _apply_sections(self):
        for sec, buttons in self.sections:
            sec.count = len(buttons)
            show = self.compact or not sec.collapsed
            for b in buttons:
                b.setVisible(show)
            sec.update()

    def _toggle_section(self, sec: NavSection, collapsed: bool | None = None):
        sec.collapsed = (not sec.collapsed) if collapsed is None else collapsed
        set_setting("nav_collapsed", [s.title for s, _b in self.sections if s.collapsed])
        self._apply_sections()

    def set_compact(self, on: bool):
        """Menu só com ícones (mais espaço para as páginas). Ctrl+B alterna."""
        if on == self.compact:
            return
        self.compact = on
        set_setting("nav_compact", on)
        if on:
            self._apply_compact(True)   # tira o texto antes de encolher
        an = QVariantAnimation(self)
        an.setDuration(160)
        an.setEasingCurve(QEasingCurve.OutCubic)
        an.setStartValue(self.side.width())
        an.setEndValue(SIDE_COMPACT_W if on else SIDE_W)
        an.valueChanged.connect(lambda v: self.side.setFixedWidth(int(v)))
        if not on:
            an.finished.connect(lambda: self._apply_compact(False))   # o texto volta já com espaço
        an.start(QVariantAnimation.DeleteWhenStopped)

    def _apply_compact(self, on: bool):
        self.brand_text.setVisible(not on)
        self.kb_badge.setVisible(not on)
        self.btn_search.setText("" if on else "  Procurar…")
        self.live.setVisible(not on)
        self.nav_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff if on else Qt.ScrollBarAsNeeded)
        self.nav_layout.setContentsMargins(0, 0, 0 if on else 4, 0)
        self.side.layout().setContentsMargins(*(10, 18, 10, 12) if on else (12, 18, 12, 12))
        self.bottom.setDirection(QBoxLayout.TopToBottom if on else QBoxLayout.LeftToRight)
        if self.btn_admin is not None:
            self.btn_admin.setText("" if on else "Admin")
        self.btn_compact.setToolTip("Expandir o menu (Ctrl+B)" if on else "Menu compacto, só com ícones (Ctrl+B)")
        for i, b in enumerate(self.nav_buttons):
            b.set_compact(on)
            key = f"Ctrl+{i + 1}" if i < 9 else ""
            parts = " · ".join(self.names[j] for j in self.groups[i]) if len(self.groups[i]) > 1 else ""
            tip = [x for x in ((b.name if on else ""), parts if parts != b.name else "", key) if x]
            b.setToolTip(" — ".join(dict.fromkeys(tip)))
        for sec, _b in self.sections:
            sec.set_compact(on)
        self._theme_btn_text()
        self._apply_sections()

    def set_nav_badge(self, name: str, text: str | None, kind: str = "accent"):
        """Contador/aviso ao lado de uma página do menu (None tira-o; "" mostra só um ponto).
        Numa página de um grupo, o aviso aparece no botão do grupo e no separador da página."""
        if name not in self.names:
            return
        idx = self.names.index(name)
        if text is None:
            self.badges.pop(idx, None)
        else:
            self.badges[idx] = (text, kind)
        shown = next((self.badges[i] for i in self.group_of[idx] if i in self.badges), None)
        self.btn_of[idx].set_badge(*(shown or (None, "accent")))
        if idx in self.subtab_btns:
            self._subtab_text(idx)

    # ------------------------------------------------------------------ separadores dos grupos
    def _group_target(self, group: list[int]) -> int:
        """Ao clicar num grupo, volta à última página aberta dele."""
        return self._last_in_group.get(group[0], group[0])

    def _subtab_text(self, idx: int):
        b = self.subtab_btns[idx]
        badge = self.badges.get(idx)
        b.setText(self.names[idx] + (f"  ·  {badge[0]}" if badge and badge[0] else "  •" if badge else ""))

    def _show_subtabs(self, idx: int):
        group = self.group_of[idx]
        if len(group) < 2:
            self.subtabs.hide()
            return
        if set(self.subtab_btns) != set(group):
            while self.subtabs_layout.count():
                it = self.subtabs_layout.takeAt(0)
                if it.widget() is not None:
                    it.widget().hide()            # sai já do ecrã (o deleteLater só corre depois)
                    it.widget().deleteLater()
            self.subtab_btns = {}
            for i in group:
                b = QPushButton()
                b.setObjectName("Chip")
                b.setCheckable(True)
                b.setCursor(Qt.PointingHandCursor)
                b.setIcon(make_icon(self.icons[i], theme.C["muted"], theme.C["accent_text"]))
                b.clicked.connect(lambda _c=False, i=i: self.go(i))
                self.subtabs_layout.addWidget(b)
                self.subtab_btns[i] = b
                self._subtab_text(i)
            self.subtabs_layout.addStretch(1)
        for i, b in self.subtab_btns.items():
            b.setChecked(i == idx)
        self.subtabs.show()

    # ------------------------------------------------------------------ navegação

    def page(self, idx: int):
        if self.pages[idx] is None:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            try:
                page = self.factories[idx]()
            finally:
                QApplication.restoreOverrideCursor()
            if hasattr(page, "set_icon"):
                page.set_icon(self.icons[idx])
            for t in page.findChildren(QTableWidget):
                t.setShowGrid(False)
            old = self.stack.widget(idx)
            self.stack.insertWidget(idx, page)
            self.stack.removeWidget(old)
            old.deleteLater()
            self.pages[idx] = page
        return self.pages[idx]

    def go(self, idx: int):
        if idx == self.current:
            return
        if self.current >= 0 and self.pages[self.current] is not None:
            self.pages[self.current].on_hide()
        page = self.page(idx)
        self.current = idx
        sec = self.section_of.get(idx)
        if sec is not None and sec.collapsed:
            self._toggle_section(sec, False)
        self.stack.setCurrentIndex(idx)
        self.btn_of[idx].setChecked(True)
        self._last_in_group[self.group_of[idx][0]] = idx
        self._show_subtabs(idx)
        page.on_show()
        if get_setting("page_fade") and self.isVisible():
            self._fade_in(page)
        if get_setting("remember_page"):
            set_setting("last_page_name", self.names[idx])

    def _fade_in(self, page):
        fx = QGraphicsOpacityEffect(page)
        page.setGraphicsEffect(fx)
        an = QPropertyAnimation(fx, b"opacity", page)
        an.setDuration(170)
        an.setStartValue(0.0)
        an.setEndValue(1.0)
        an.setEasingCurve(QEasingCurve.OutCubic)
        an.finished.connect(lambda: page.setGraphicsEffect(None))  # sem custo depois da transição
        an.start(QPropertyAnimation.DeleteWhenStopped)

    def go_name(self, name: str):
        if name in self.names:
            self.go(self.names.index(name))

    def _setup_shortcuts(self):
        for i, g in enumerate(self.groups[:9]):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda g=g: self.go(self._group_target(g)))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.go((self.current + 1) % len(self.pages)))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self,
                  activated=lambda: self.go((self.current - 1) % len(self.pages)))
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_page)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.quit)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.go_name("Definições"))
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.set_compact(not self.compact))
        QShortcut(QKeySequence("Ctrl+Shift+A"), self, activated=self.open_alerts)
        QShortcut(QKeySequence("F1"), self, activated=self.show_shortcuts)

    def open_palette(self):
        if self.palette_box is None:
            from .palette import CommandPalette
            self.palette_box = CommandPalette(self, self.centralWidget())
        self.palette_box.open()

    def show_shortcuts(self):
        from .wizard import ShortcutsDialog
        ShortcutsDialog(self).exec()

    def maybe_first_run(self):
        """Assistente de boas-vindas na primeira vez que o Nexo abre (com a janela à vista)."""
        if not get_setting("wizard_done") and self.isVisible():
            self.show_wizard()

    def show_wizard(self):
        from .wizard import Wizard
        w = Wizard(self)
        w.exec()
        if w.go_to:
            self.go_name(w.go_to)
        cur = self.pages[self.current] if 0 <= self.current < len(self.pages) else None
        if cur is not None:
            cur.on_show()

    def open_alerts(self):
        if self.alert_box is None:
            from .alertcenter import AlertCenter
            self.alert_box = AlertCenter(self, self.centralWidget())
        self.alert_box.open()

    def refresh_alert_badge(self):
        from ..core import alertlog
        n = alertlog.unread()
        self.btn_bell.set_count(n)
        if self.tray is not None:
            self._tray_alerts.setText(f"Alertas ({n} por ler)" if n else "Alertas")

    def _refresh_page(self):
        p = self.pages[self.current]
        for name in ("refresh", "load"):
            fn = getattr(p, name, None)
            if callable(fn):
                fn()
                self.notify("Página atualizada.", "info")
                return
        p.on_show()

    # ------------------------------------------------------------------ bandeja
    def _setup_tray(self):
        want = get_setting("tray") and QSystemTrayIcon.isSystemTrayAvailable()
        if want and self.tray is None:
            self.tray = QSystemTrayIcon(app_icon(), self)
            m = QMenu(self)
            m.addAction("Abrir Nexo", self.show_window)
            self._tray_alerts = m.addAction("Alertas", lambda: (self.show_window(), self.open_alerts()))
            m.addSeparator()
            for name in ("Sensores", "Processos", "Otimização", "Instalar aplicações"):
                if name in self.names:
                    m.addAction(name, lambda n=name: (self.show_window(), self.go_name(n)))
            m.addSeparator()
            quit_act = QAction("Sair", self)
            quit_act.triggered.connect(self.quit)
            m.addAction(quit_act)
            self.tray.setContextMenu(m)
            self.tray.activated.connect(self._tray_click)
            self.tray.setToolTip(APP_NAME)
            self.tray.show()
            if hasattr(self, "btn_bell"):
                self.refresh_alert_badge()
        elif not want and self.tray is not None:
            self.tray.hide()
            self.tray.deleteLater()
            self.tray = None

    def _tray_click(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.isVisible() and not self.isMinimized():
                self.hide()
            else:
                self.show_window()

    def show_window(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _setting_changed(self, key: str):
        if key == "tray":
            self._setup_tray()
        elif key == "theme":
            self.set_theme(get_setting("theme"))
        elif key.startswith(("wallpaper", "accent_")):
            theme.apply(QApplication.instance(), theme.current())  # a cor pode vir do fundo
            self._after_theme()

    def _alert(self, msg: str, kind: str, page: str | None = None):
        """Aviso importante: notificação, bandeja (com a janela escondida) e centro de alertas."""
        from ..core import alertlog
        try:
            alertlog.add(msg, kind, page)
        except OSError:
            logging.getLogger("nexo").warning("Não foi possível guardar o alerta", exc_info=True)
        self.refresh_alert_badge()
        self.notify(msg, kind)
        if self.tray is not None and (not self.isVisible() or self.isMinimized() or not self.isActiveWindow()):
            self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.Warning, 8000)


    # ------------------------------------------------------------------ notificações e leitura ao vivo
    def notify(self, msg: str, kind: str = "info"):
        self.toast.show_msg(msg, kind)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.reposition()
        for box in (getattr(self, "palette_box", None), getattr(self, "alert_box", None)):
            if box is not None and box.isVisible():
                box.setGeometry(self.centralWidget().rect())

    # ------------------------------------------------------------------ painel no telemóvel
    def _init_web(self):
        if get_setting("web_panel"):
            self.set_web_panel(True, quiet=True)
        self.hub.updated.connect(self._web_tick)

    def set_web_panel(self, on: bool, quiet: bool = False) -> tuple[bool, str]:
        from ..core import webpanel
        p = webpanel.panel()
        if not on:
            p.stop()
            return True, ""
        ok, msg = p.start()
        if not ok and not quiet:
            self.notify(msg, "bad")
        elif not ok:
            logging.getLogger("nexo.web").warning("Painel no telemóvel: %s", msg)
        return ok, msg

    def _web_tick(self, _r):
        from ..core import webpanel
        p = webpanel.panel()
        if not p.running:
            return
        import socket
        import time as _t
        h = self.hub
        f = self.overlay.last_fps if self.game is not None else None
        p.update({"host": socket.gethostname(), "cpu_t": h.latest("cpu_temp"), "cpu_l": h.latest("cpu_load"),
                  "gpu_t": h.latest("gpu_temp"), "gpu_l": h.latest("gpu_load"), "cpu_p": h.latest("cpu_power"),
                  "gpu_p": h.latest("gpu_power"), "ram": h.latest("ram"), "vram": h.latest("vram"),
                  "fps": f["fps"] if f else None, "ft": f["ft"] if f else None,
                  "game": self.game.name if self.game is not None else "",
                  "elapsed": _t.time() - self.game.started if self.game is not None else 0})

    def _live(self, _r):
        h = self.hub
        c = theme.C

        def fmt(v, unit):
            return f"{v:.0f}{unit}" if v is not None else "—"

        def tcol(t):
            return None if t is None else "bad" if t >= 90 else "warn" if t >= 80 else "ok"
        ct, gt = h.latest("cpu_temp"), h.latest("gpu_temp")
        cl, gl, ram = h.latest("cpu_load"), h.latest("gpu_load"), h.latest("ram")
        if self.tray is not None:
            self.tray.setToolTip(f"{APP_NAME}\nCPU {fmt(ct, ' °C')} · {fmt(cl, '%')}\n"
                                 f"GPU {fmt(gt, ' °C')} · {fmt(gl, '%')}\nRAM {fmt(ram, '%')}")
            # temperatura da CPU desenhada no próprio ícone
            txt = f"{ct:.0f}" if ct is not None else None
            if txt != self._tray_text:
                self._tray_text = txt
                self.tray.setIcon(app_icon(txt, c["bad"] if ct and ct >= 90 else c["warn"] if ct and ct >= 80
                                           else c["accent"]))
        if not self.isVisible():
            return

        def cell(t, load):
            tc = tcol(t)
            temp = f"<span style='color:{c[tc]}'>{t:.0f}°</span>&nbsp;&nbsp;" if t is not None else ""
            return f"{temp}{fmt(load, '%')}"
        self.live.set("CPU", cell(ct, cl), cl)
        self.live.set("GPU", cell(gt, gl), gl)
        self.live.set("RAM", fmt(ram, "%"), ram)

    def _theme_btn_text(self):
        self.btn_theme.setText("" if self.compact else f"  {theme.C['name']}")
        self.btn_theme.setIcon(make_icon("sun" if theme.mode() == "light" else "moon", theme.C["text"]))

    def _fill_theme_menu(self):
        m = self.theme_menu
        m.clear()
        for key, t in theme.THEMES.items():
            a = m.addAction(make_icon("sun" if t["light"] else "moon", theme.C["text"]), t["name"])
            a.setCheckable(True)
            a.setChecked(key == theme.current())
            a.triggered.connect(lambda _c=False, k=key: self.set_theme(k))
        m.addSeparator()
        m.addAction("Mudar o fundo do ambiente de trabalho…", lambda: self.go_name("Fundo de ecrã"))

    def set_theme(self, key: str):
        theme.apply(QApplication.instance(), key)
        self._after_theme()

    def toggle_theme(self):  # compatibilidade: alterna entre claro e escuro
        self.set_theme("escuro" if theme.mode() == "light" else "claro")

    def _after_theme(self):
        self._theme_btn_text()
        self._paint_nav_icons()
        self.logo_ic.setPixmap(logo_mod.pixmap(34, theme.logo_colors()))
        self.setWindowIcon(app_icon())
        QApplication.instance().setWindowIcon(self.windowIcon())
        self._tray_text = "∅"  # força redesenhar o ícone da bandeja
        self.toast.hide()
        self.btn_search.setIcon(make_icon("search", theme.C["muted"]))
        for pg in self.pages:
            if pg is not None and hasattr(pg, "retheme"):
                pg.retheme()
        cur = self.pages[self.current] if 0 <= self.current < len(self.pages) else None
        if cur is not None and hasattr(cur, "theme_btns"):
            cur.on_show()  # Definições abertas: atualiza os botões Escuro/Claro
        for w in self.findChildren(QWidget):
            w.update()

    # ------------------------------------------------------------------ internet
    def _net_changed(self, st):
        self.live.set_net(st)

    def _net_recheck(self):
        self.live.net_val.setText("a verificar…")
        self.net.refresh(full=True)
        self.go_name("Internet")



    def _elevate(self):
        if relaunch_as_admin():
            self.quit()

    def quit(self):
        self._quitting = True
        self.close()
        QApplication.instance().quit()

    def showEvent(self, e):
        super().showEvent(e)
        if not getattr(self, "_focused_once", False):
            # o foco começa no conteúdo (não no botão de pesquisa, que ficaria contornado à toa)
            self._focused_once = True
            self.stack.setFocusPolicy(Qt.ClickFocus)
            QTimer.singleShot(0, self.stack.setFocus)

    def closeEvent(self, e):
        if not self._quitting and self.tray is not None and get_setting("close_to_tray"):
            e.ignore()
            self.hide()
            if not get_setting("tray_hint_shown"):
                set_setting("tray_hint_shown", True)
                self.tray.showMessage(APP_NAME, "O Nexo continua a correr na bandeja. "
                                      "Para sair: botão direito no ícone → Sair.", QSystemTrayIcon.Information, 6000)
            return
        set_setting("geometry", bytes(self.saveGeometry().toBase64()).decode())
        self._shutdown_game()
        from ..core import webpanel
        webpanel.panel().stop()
        if IS_WIN:
            from ..core import lhm
            lhm.stop_if_started()
        for p in self.pages:
            if p is not None and hasattr(p, "shutdown"):
                p.shutdown()
        self.hub.close()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(e)
        QApplication.instance().quit()
