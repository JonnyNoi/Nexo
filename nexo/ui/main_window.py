from __future__ import annotations

import logging
import os

from PySide6.QtCore import QByteArray, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer, QVariantAnimation
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (QApplication, QBoxLayout, QButtonGroup, QFrame, QGraphicsOpacityEffect, QGridLayout,
                               QHBoxLayout,
                               QLabel, QMainWindow, QMenu, QPushButton, QScrollArea, QSizePolicy, QStackedWidget,
                               QSystemTrayIcon,
                               QTableWidget, QVBoxLayout, QWidget)

from ..core.util import APP_NAME, APP_VERSION, IS_WIN, get_setting, is_admin, os_label, relaunch_as_admin, set_setting
from . import theme
from . import logo as logo_mod
from .icons import icon as make_icon
from .icons import pixmap as icon_pixmap
from .widgets import Bar, SensorHub, icon_badge, label, run_async, set_notify_target


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

    def debloat():
        from .pages.debloat import DebloatPage
        return DebloatPage()

    def disk():
        from .pages.disk import DiskPage
        return DiskPage()

    def gamemode():
        from .pages.gamemode import GameModePage
        return GameModePage()

    def wallpaper():
        from .pages.wallpaper import WallpaperPage
        return WallpaperPage()

    def internet():
        from .pages.internet import InternetPage
        return InternetPage()

    def fans():
        from .pages.fans import FansPage
        return FansPage(hub)

    def diskhealth():
        from .pages.diskhealth import DiskHealthPage
        return DiskHealthPage()

    def updates():
        from .pages.updates import UpdatesPage
        return UpdatesPage()

    def settings():
        from .pages.settings import SettingsPage
        return SettingsPage(on_settings)

    tools_items = [("Internet", "wifi", internet), ("Atualizações", "upgrade", updates),
                   ("Instalar aplicações", "download", apps),
                   ("Utilitários", "wrench", tools),
                   ("Arranque", "power", startup)]
    if IS_WIN:
        tools_items.append(("Windows debloat", "broom", debloat))
    tools_items += [("Espaço em disco", "disk", disk), ("Fundo de ecrã", "image", wallpaper)]
    return [
        (None, [("Visão geral", "home", dashboard)]),
        ("SISTEMA", [("Informação", "info", system), ("Sensores", "thermo", sensors),
                     ("Saúde dos discos", "hdd", diskhealth), ("Processos", "list", processes),
                     ("Antivírus", "virus", antivirus)]),
        ("DESEMPENHO", [("Otimização", "zap", optimize), ("Stress test", "flame", stress),
                        ("Benchmark", "gauge", benchmark),
                        ("Modo jogo", "gamepad", gamemode),
                        ("Ventoinhas", "fan", fans)]),
        ("FERRAMENTAS", tools_items),
        (None, [("Definições", "gear", settings)]),
    ]


def app_icon(text: str | None = None, color: str | None = None) -> QIcon:
    """Logótipo do Nexo nas cores do tema (com a temperatura escrita, para a bandeja)."""
    colors = (color, color) if color else theme.logo_colors()
    return logo_mod.icon(colors, text)


class Toast(QFrame):
    """Notificação flutuante no canto inferior direito, com ícone e fecho."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 10, 12)
        h.setSpacing(12)
        self.badge_holder = QHBoxLayout()
        h.addLayout(self.badge_holder)
        self.text = label("", wrap=True)
        self.text.setMaximumWidth(380)
        h.addWidget(self.text, 1)
        x = QPushButton("✕")
        x.setObjectName("Ghost")
        x.setFixedSize(26, 26)
        x.clicked.connect(self.hide)
        h.addWidget(x, 0, Qt.AlignTop)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_msg(self, msg: str, kind: str):
        while self.badge_holder.count():
            w = self.badge_holder.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        ic = {"ok": "check", "bad": "alert", "warn": "alert"}.get(kind, "info")
        self.badge_holder.addWidget(icon_badge(ic, 30, 16, kind if kind in theme.C else "info"), 0, Qt.AlignTop)
        self.text.setText(msg)
        self.setStyleSheet(f"QFrame#Card {{ border-left: 3px solid {theme.C.get(kind, theme.C['info'])}; "
                           f"background: {theme.C['surface2']}; }}")
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(max(5000, min(12000, 60 * len(msg))))

    def reposition(self):
        p = self.parentWidget()
        if p:
            self.adjustSize()
            self.move(p.width() - self.width() - 20, p.height() - self.height() - 20)


SIDE_W, SIDE_COMPACT_W = 240, 72


class NavButton(QPushButton):
    """Botão do menu lateral: barra de destaque à esquerda quando ativo e contador/aviso opcional."""

    def __init__(self, name: str):
        super().__init__(name)
        self.name = name
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)   # cabe no menu compacto
        self.badge: str | None = None
        self.badge_kind = "accent"
        self.compact = False

    def set_badge(self, text: str | None, kind: str = "accent"):
        if (text, kind) != (self.badge, self.badge_kind):
            self.badge, self.badge_kind = text, kind
            self.update()

    def set_compact(self, on: bool):
        self.compact = on
        self.setText("" if on else self.name)
        self.setProperty("compact", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def paintEvent(self, e):
        super().paintEvent(e)
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.isChecked():   # barra de destaque à esquerda
            h = 18
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(QRectF(0, (self.height() - h) / 2, 3.5, h), 1.75, 1.75)
        if self.badge is not None:
            col = QColor(c.get(self.badge_kind, c["accent"]))
            if self.compact or not self.badge:   # ponto no canto do ícone
                d = 9
                p.setPen(QColor(c["surface"]))
                p.setBrush(col)
                x = self.width() / 2 + 4 if self.compact else self.width() - 20
                p.drawEllipse(QRectF(x, 6 if self.compact else (self.height() - d) / 2, d, d))
            else:
                f = QFont(self.font())
                f.setPixelSize(11)
                f.setBold(True)
                p.setFont(f)
                w = max(20, p.fontMetrics().horizontalAdvance(self.badge) + 12)
                r = QRectF(self.width() - w - 8, (self.height() - 18) / 2, w, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(r, 9, 9)
                p.setPen(QColor("#ffffff"))
                p.drawText(r, Qt.AlignCenter, self.badge)
        p.end()


class NavSection(QPushButton):
    """Título de secção do menu: clicar recolhe/expande a secção. No modo compacto é só uma linha."""

    def __init__(self, title: str):
        super().__init__(title)
        self.title = title
        self.setObjectName("NavSection")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.collapsed = False
        self.compact = False
        self.count = 0

    def set_compact(self, on: bool):
        self.compact = on
        self.setEnabled(not on)
        self.setFixedHeight(14 if on else 26)
        self.update()

    def paintEvent(self, e):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.compact:
            p.setPen(QColor(c["border2"]))
            y = self.height() / 2
            p.drawLine(int(self.width() * 0.25), int(y), int(self.width() * 0.75), int(y))
            p.end()
            return
        hover = self.underMouse()
        p.setPen(QColor(c["text"] if hover else c["muted"]))
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(f)
        r = self.rect().adjusted(12, 0, -10, 0)
        txt = self.title + (f"  ·  {self.count}" if self.collapsed else "")
        p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, txt)
        pm = icon_pixmap("chev_right" if self.collapsed else "chev_down", c["text"] if hover else c["muted"], 14)
        p.drawPixmap(int(self.width() - 24), int((self.height() - 14) / 2), pm)
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class LiveBox(QFrame):
    """Leitura ao vivo de CPU/GPU/RAM no fundo do menu (texto + barra fina)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("LiveBox")
        g = QGridLayout(self)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(3)
        self.rows = {}
        for i, key in enumerate(("CPU", "GPU", "RAM")):
            name = label(key, "Muted")
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            val = label("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setTextFormat(Qt.RichText)
            bar = Bar(4)
            g.addWidget(name, i * 2, 0)
            g.addWidget(val, i * 2, 1)
            g.addWidget(bar, i * 2 + 1, 0, 1, 2)
            self.rows[key] = (val, bar)
        # ligação à internet (clicar volta a testar)
        self.net_name = label("NET", "Muted")
        f = self.net_name.font()
        f.setBold(True)
        self.net_name.setFont(f)
        self.net_val = label("a verificar…", "Muted")
        self.net_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.net_val.setTextFormat(Qt.RichText)
        g.addWidget(self.net_name, 6, 0)
        g.addWidget(self.net_val, 6, 1)
        self.on_net_click = None
        self.setToolTip("Ligação à internet — clique para abrir a página Internet")

    def mousePressEvent(self, e):
        if self.on_net_click and e.position().y() >= self.net_name.geometry().top() - 4:
            self.on_net_click()
        super().mousePressEvent(e)

    def set_net(self, st):
        color = theme.C.get(st.level, theme.C["muted"])
        self.net_val.setText(f"<span style='color:{color}'>●</span> {st.short()}")
        tip = [f"<b>{st.label}</b>", st.detail, ""]
        for name, ok, det in st.steps:
            mark = "✔" if ok else "✘" if ok is False else "–"
            tip.append(f"{mark} {name}: {det}")
        tip.append("<br><i>Clique para abrir o teste de velocidade</i>")
        self.setToolTip("<br>".join(tip))

    def set(self, key, text, pct, color=None):
        val, bar = self.rows[key]
        if val.text() != text:
            val.setText(text)
        bar.set(pct or 0, color)


class MainWindow(QMainWindow):
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
        self.pages: list = []          # None até a página ser criada
        self.factories: list = []
        self.names: list[str] = []
        self.icons: list[str] = []
        self.nav_buttons: list[NavButton] = []
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
            for name, ic, factory in items:
                b = NavButton(name)
                idx = self.stack.addWidget(QWidget())  # marcador até a página ser criada
                self.pages.append(None)
                self.factories.append(factory)
                self.names.append(name)
                self.icons.append(ic)
                self.nav_buttons.append(b)
                b.clicked.connect(lambda _c, i=idx: self.go(i))
                self.nav.addButton(b, idx)
                nv.addWidget(b)
                if sec is not None:
                    self.sections[-1][1].append(b)
                    self.section_of[idx] = sec
        self._paint_nav_icons()

        sv.addSpacing(10)
        self.live = LiveBox()
        sv.addWidget(self.live)
        sv.addSpacing(8)
        self.bottom = QBoxLayout(QBoxLayout.LeftToRight)
        self.bottom.setSpacing(6)
        self.btn_theme = QPushButton()
        self.btn_theme.setToolTip("Tema escuro ou claro")
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
        self.btn_compact = QPushButton()
        self.btn_compact.setFixedSize(36, 36)
        self.btn_compact.setCursor(Qt.PointingHandCursor)
        self.btn_compact.clicked.connect(lambda: self.set_compact(not self.compact))
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
        rv.addWidget(self.stack, 1)
        h.addWidget(self.right, 1)
        self.setCentralWidget(root)
        self.toast = Toast(self.right)
        self.palette_box = None  # pesquisa rápida, criada na primeira utilização
        set_notify_target(self.notify)

        # ------------------------------------------------------------- bandeja, atalhos, estado
        self.tray: QSystemTrayIcon | None = None
        self._tray_text = None
        self._setup_tray()
        self._setup_shortcuts()
        geo = get_setting("geometry")
        if geo:
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode()))
            except (ValueError, TypeError, AttributeError):
                logging.getLogger("nexo").debug("Geometria guardada inválida", exc_info=True)

        self.hub.updated.connect(self._live)
        self.hub.alert.connect(self._alert)
        self._wp_busy = False
        self._wp_timer = QTimer(self)
        self._wp_timer.timeout.connect(self._auto_wallpaper)
        self._wp_timer.start(60_000)
        # ------------------------------------------------------------- modo jogo
        from .overlay import OverlayController
        self.overlay = OverlayController()
        self.overlay_manual = False        # overlay ligado à mão (botão "Mostrar agora")
        self.game = None                   # jogo a correr (games.RunningGame)
        self.game_stats: dict = {}
        self._game_busy = False
        self._game_misses = 0
        self._game_timer = QTimer(self)
        self._game_timer.timeout.connect(self._check_game)
        self._game_timer.start(4000)
        self.hub.updated.connect(self._game_tick)
        # ------------------------------------------------------------- ligação à internet
        from .netmonitor import monitor
        self.net = monitor()
        self.net.checked.connect(self._net_changed)
        self.live.on_net_click = self._net_recheck
        self.net.start()
        # ------------------------------------------------------------- atualizações (contador no menu)
        self._upd_busy = False
        self._upd_waiters: list = []
        from ..core import updates as _up
        self._show_update_badge(_up.cached())
        self._upd_timer = QTimer(self)
        self._upd_timer.timeout.connect(self._auto_updates)
        self._upd_timer.start(30 * 60_000)
        QTimer.singleShot(90_000, self._auto_updates)   # depois do arranque, sem pesar no início
        # ------------------------------------------------------------- vigilância (disco cheio, S.M.A.R.T.)
        from ..core.watch import DiskAlerts
        self._disk_alerts = DiskAlerts()
        self._watch_busy = False
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch)
        self._watch_timer.start(5 * 60_000)
        QTimer.singleShot(45_000, self._watch)
        # ------------------------------------------------------------- ventoinhas
        # o gestor das ventoinhas só nasce se houver um perfil ativo (ou quando a página abre)
        if get_setting("fan_profile", "auto") != "auto":
            from .hwcontrol import fan_manager
            fan_manager(self.hub)
        self.current = -1
        last = get_setting("last_page_name") if get_setting("remember_page") else None
        self.go(self.names.index(last) if last in self.names else 0)
        self._start_hidden = start_hidden and self.tray is not None

    # ------------------------------------------------------------------ menu lateral
    def _paint_nav_icons(self):
        c = theme.C
        for b, ic in zip(self.nav_buttons, self.icons):
            b.setIcon(make_icon(ic, c["muted"], c["accent"]))
        if hasattr(self, "btn_compact"):
            self.btn_compact.setIcon(make_icon("sidebar", c["text"]))

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
            b.setToolTip(f"{b.name} · {key}" if on and key else b.name if on else key)
        for sec, _b in self.sections:
            sec.set_compact(on)
        self._theme_btn_text()
        self._apply_sections()

    def set_nav_badge(self, name: str, text: str | None, kind: str = "accent"):
        """Contador/aviso ao lado de uma página do menu (None tira-o; "" mostra só um ponto)."""
        if name in self.names:
            self.nav_buttons[self.names.index(name)].set_badge(text, kind)

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
        self.nav.button(idx).setChecked(True)
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
        for i in range(min(9, len(self.pages))):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, activated=lambda i=i: self.go(i))
        QShortcut(QKeySequence("Ctrl+Tab"), self, activated=lambda: self.go((self.current + 1) % len(self.pages)))
        QShortcut(QKeySequence("Ctrl+Shift+Tab"), self,
                  activated=lambda: self.go((self.current - 1) % len(self.pages)))
        QShortcut(QKeySequence("F5"), self, activated=self._refresh_page)
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.quit)
        QShortcut(QKeySequence("Ctrl+,"), self, activated=lambda: self.go_name("Definições"))
        QShortcut(QKeySequence("Ctrl+K"), self, activated=self.open_palette)
        QShortcut(QKeySequence("Ctrl+B"), self, activated=lambda: self.set_compact(not self.compact))

    def open_palette(self):
        if self.palette_box is None:
            from .palette import CommandPalette
            self.palette_box = CommandPalette(self, self.centralWidget())
        self.palette_box.open()

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

    def _alert(self, msg: str, kind: str):
        self.notify(msg, kind)
        if self.tray is not None and (not self.isVisible() or self.isMinimized() or not self.isActiveWindow()):
            self.tray.showMessage(APP_NAME, msg, QSystemTrayIcon.Warning, 8000)

    def _watch(self):
        """A cada 5 min: espaço livre dos discos e alterações na cache do S.M.A.R.T. (sem pedir palavra-passe)."""
        if self._watch_busy or not (get_setting("alert_disk") or get_setting("alert_smart")):
            return
        self._watch_busy = True
        from ..core import watch

        def work():
            msgs = []
            if get_setting("alert_disk"):
                msgs += self._disk_alerts.check(watch.disk_usages(), float(get_setting("alert_disk_pct") or 10))
            if get_setting("alert_smart"):
                msgs += watch.smart_check_cached()
            return msgs

        def done(msgs):
            self._watch_busy = False
            for m, kind in msgs:
                self._alert(m, kind)

        def fail(_m):
            self._watch_busy = False
        run_async(work, on_done=done, on_fail=fail)

    # ------------------------------------------------------------------ notificações e leitura ao vivo
    def notify(self, msg: str, kind: str = "info"):
        self.toast.show_msg(msg, kind)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.toast.isVisible():
            self.toast.reposition()
        if getattr(self, "palette_box", None) is not None and self.palette_box.isVisible():
            self.palette_box.setGeometry(self.centralWidget().rect())

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
        self.btn_theme.setText("" if self.compact else f"  Tema: {theme.C['name']}")
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

    # ------------------------------------------------------------------ atualizações
    def _show_update_badge(self, data: dict):
        n = len((data or {}).get("items", []))
        self.set_nav_badge("Atualizações", str(n) if n else None, "accent")

    def _auto_updates(self):
        import time as _t
        from ..core import updates as up
        if not get_setting("updates_auto", True) or self.net.online is False:
            return
        if _t.time() - up.cached().get("time", 0) >= 6 * 3600:
            self.check_updates()

    def check_updates(self, force: bool = False, on_done=None) -> bool:
        """Procura atualizações em segundo plano. Devolve False se não houver internet."""
        if self.net.online is False:
            return False
        if on_done:
            self._upd_waiters.append(on_done)
        if self._upd_busy:
            return True
        self._upd_busy = True
        from ..core import updates as up
        from .widgets import run_async

        def finish(data):
            self._upd_busy = False
            if data:
                self._show_update_badge(data)
            waiters, self._upd_waiters = self._upd_waiters, []
            for w in waiters:
                w(data)
        run_async(up.check, on_done=finish, on_fail=lambda _m: finish(None))
        return True

    # ------------------------------------------------------------------ troca automática do fundo
    def _auto_wallpaper(self, force: bool = False):
        """Troca automática do fundo do AMBIENTE DE TRABALHO (sistema)."""
        import time as _t
        mins = int(get_setting("wp_auto") or 0)
        if self._wp_busy or (not force and (not mins or _t.time() - get_setting("wp_auto_last", 0) < mins * 60)):
            return
        if get_setting("wp_auto_source") == "wallhaven" and self.net.online is False:
            if force:
                from .netmonitor import require_online
                require_online("Procurar fundos no Wallhaven")
            return  # sem internet: tenta outra vez quando a ligação voltar
        set_setting("wp_auto_last", _t.time())
        from ..core import desktopwp as dw
        from ..core import wallhaven as wh
        from .widgets import run_async

        def applied(res):
            self._wp_busy = False
            ok, msg = res
            if force:
                self.notify("Fundo do ambiente de trabalho alterado." if ok else f"Não foi possível: {msg}",
                            "ok" if ok else "warn")
            name = "Fundo de ecrã"
            page = self.pages[self.names.index(name)] if name in self.names else None
            if ok and page is not None and page.isVisible():
                page.on_show()

        def apply(path):
            if not path:
                self._wp_busy = False
                return
            run_async(dw.set_wallpaper, path, None, bool(get_setting("desktop_wp_lock", False)),
                      on_done=applied, on_fail=fail)

        def fail(msg):
            self._wp_busy = False
            if force:
                self.notify(f"Não foi possível trocar o fundo: {msg}", "warn")
        self._wp_busy = True
        if get_setting("wp_auto_source") == "wallhaven":
            from .wallhaven_dialog import screen_min_res
            cat = wh.CATEGORIES.get(get_setting("wh_category", "Anime"), "010")
            run_async(wh.random_from_wallhaven, get_setting("wh_query", "anime scenery"), cat, screen_min_res(),
                      on_done=apply, on_fail=fail)
        else:
            import random
            cur = os.path.basename(get_setting("desktop_wp") or "")
            files = [f for f in dw.images() if os.path.basename(f) != cur]
            if files:
                apply(random.choice(files))
            else:
                self._wp_busy = False
                if force:
                    self.notify("Ainda não tem fundos guardados — escolha alguns no Wallhaven.", "info")

    # ------------------------------------------------------------------ modo jogo
    def _check_game(self):
        if self._game_busy or not get_setting("game_detect"):
            return
        from .widgets import run_async
        self._game_busy = True

        def detect():  # a importação (compila as regras do disksafety, ~0,1 s) também fica fora da interface
            from ..core import games
            return games.detect_running()

        def done(g):
            self._game_busy = False
            self._game_changed(g)

        def fail(_m):
            self._game_busy = False
        run_async(detect, on_done=done, on_fail=fail)

    def _game_changed(self, g):
        old = self.game
        if g is None and old is not None:
            self._game_misses += 1
            if self._game_misses < 2:   # evita "acabou" falso durante ecrãs de carregamento
                return
        self._game_misses = 0
        if g is not None and old is not None and g.name == old.name:
            return
        if old is not None:
            self._game_ended(old)
        self.game = g
        self.overlay.fps.set_game(g)
        from .hwcontrol import existing_fan_manager, fan_manager, game_profile
        from ..core.fans import PROFILES
        fan_prof = game_profile(g.name) if g is not None else ""
        if fan_prof or existing_fan_manager() is not None:
            fan_manager(self.hub).set_game(g.name if g is not None else None)
        if g is not None:
            self.game_stats = {"cpu_max": None, "gpu_max": None, "start": g.started}
            if get_setting("game_notify"):
                extra = []
                if get_setting("overlay_auto"):
                    extra.append("overlay ligado")
                if fan_prof:
                    extra.append(f"ventoinhas em «{PROFILES[fan_prof]['name']}»")
                self._alert(f"🎮 Jogo detetado: {g.name}" + (" — " + ", ".join(extra) if extra else ""), "info")
            if get_setting("overlay_auto") or self.overlay_manual:
                self.overlay.show(g.name, g.started)
        elif not self.overlay_manual:
            self.overlay.hide()
        self._notify_game_page()

    def _game_ended(self, g):
        import time as _t
        mins = max(1, int((_t.time() - (self.game_stats.get("start") or _t.time())) / 60))
        if get_setting("game_notify"):
            parts = [f"Sessão de {g.name}: {mins} min"]
            if self.game_stats.get("cpu_max") is not None:
                parts.append(f"CPU máx. {self.game_stats['cpu_max']:.0f} °C")
            if self.game_stats.get("gpu_max") is not None:
                parts.append(f"GPU máx. {self.game_stats['gpu_max']:.0f} °C")
            if self.game_stats.get("fps_n", 0) >= 10:
                parts.append(f"{self.game_stats['fps_sum'] / self.game_stats['fps_n']:.0f} FPS em média "
                             f"(mín. {self.game_stats['fps_min']:.0f})")
            self._alert(" · ".join(parts), "info")
        if self.overlay_manual:
            self.overlay.show("", 0)

    def _game_tick(self, _r):
        if self.game is not None:
            for key, k in (("cpu_temp", "cpu_max"), ("gpu_temp", "gpu_max")):
                v = self.hub.latest(key)
                if v is not None and (self.game_stats.get(k) is None or v > self.game_stats[k]):
                    self.game_stats[k] = v
        # o processo do overlay pode ter ido abaixo: volta a lançá-lo (no máximo a cada 10 s)
        want = self.overlay_manual or (self.game is not None and get_setting("overlay_auto"))
        if want and not self.overlay.running():
            import time as _t
            if _t.monotonic() - getattr(self, "_ov_retry", 0) > 10:
                self._ov_retry = _t.monotonic()
                self.overlay.show(self.game.name if self.game else "", self.game.started if self.game else 0)
        self.overlay.push(self.hub)
        f = self.overlay.last_fps
        if self.game is not None and f:
            st = self.game_stats
            st["fps_sum"] = st.get("fps_sum", 0.0) + f["fps"]
            st["fps_n"] = st.get("fps_n", 0) + 1
            st["fps_min"] = min(st.get("fps_min") or f["fps"], f["fps"])

    def set_overlay_manual(self, on: bool):
        self.overlay_manual = on
        if on:
            self.overlay.show(self.game.name if self.game else "", self.game.started if self.game else 0)
        elif self.game is None or not get_setting("overlay_auto"):
            self.overlay.hide()
        self._notify_game_page()

    def _notify_game_page(self):
        name = "Modo jogo"
        if name in self.names:
            p = self.pages[self.names.index(name)]
            if p is not None and p.isVisible():
                p.on_show()

    def _elevate(self):
        if relaunch_as_admin():
            self.quit()

    def quit(self):
        self._quitting = True
        self.close()
        QApplication.instance().quit()

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
        self.overlay.hide()
        self.overlay.fps.stop()
        from .hwcontrol import existing_fan_manager
        fans = existing_fan_manager()
        if fans is not None:
            fans.shutdown()   # ventoinhas para o hardware; energia como estava antes do jogo
        for p in self.pages:
            if p is not None and hasattr(p, "shutdown"):
                p.shutdown()
        self.hub.close()
        if self.tray is not None:
            self.tray.hide()
        super().closeEvent(e)
        QApplication.instance().quit()
