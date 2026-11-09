from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy,
                               QVBoxLayout, QWidget)

from ...core import fans as fc
from ...core.util import IS_WIN, get_setting, set_setting
from .. import theme
from ..hwcontrol import SOURCES, fan_manager
from ..theme import qc
from ..widgets import Card, Page, Tip, Toggle, confirm, label, notify, run_async, scaled


class CurveEditor(QWidget):
    """Curva temperatura → rotação. Arrastar os pontos (só no perfil Personalizado)."""
    edited = Signal(list)

    T_MIN, T_MAX = 20, 100

    def __init__(self):
        super().__init__()
        self.points: list[tuple[float, float]] = list(fc.DEFAULT_CUSTOM)
        self.editable = False
        self.temp: float | None = None
        self._drag: int | None = None
        self.setMinimumHeight(230)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMouseTracking(True)

    def set_curve(self, pts, editable: bool):
        self.points = [(float(t), float(p)) for t, p in pts]
        self.editable = editable
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_temp(self, t):
        if t != self.temp:
            self.temp = t
            self.update()

    def _area(self) -> QRectF:
        return QRectF(self.rect()).adjusted(44, 12, -14, -28)

    def _to_px(self, t, p) -> QPointF:
        r = self._area()
        return QPointF(r.left() + (t - self.T_MIN) / (self.T_MAX - self.T_MIN) * r.width(),
                       r.bottom() - p / 100 * r.height())

    def _from_px(self, pos) -> tuple[float, float]:
        r = self._area()
        t = self.T_MIN + (pos.x() - r.left()) / max(r.width(), 1) * (self.T_MAX - self.T_MIN)
        p = (r.bottom() - pos.y()) / max(r.height(), 1) * 100
        return round(max(self.T_MIN, min(self.T_MAX, t))), round(max(fc.MIN_PCT, min(100, p)))

    def _hit(self, pos) -> int | None:
        for i, (t, p) in enumerate(self.points):
            if (self._to_px(t, p) - QPointF(pos)).manhattanLength() < 14:
                return i
        return None

    def mousePressEvent(self, e):
        if self.editable:
            self._drag = self._hit(e.position())

    def mouseMoveEvent(self, e):
        if not self.editable:
            return
        if self._drag is None:
            self.setCursor(Qt.OpenHandCursor if self._hit(e.position()) is not None else Qt.ArrowCursor)
            return
        t, p = self._from_px(e.position())
        i = self._drag
        lo = self.points[i - 1][0] + 1 if i > 0 else self.T_MIN
        hi = self.points[i + 1][0] - 1 if i < len(self.points) - 1 else self.T_MAX
        self.points[i] = (max(lo, min(hi, t)), p)
        self.update()

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            self.edited.emit(list(self.points))

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._area()
        p.setFont(scaled(self.font(), 0.8))
        for pct in (0, 25, 50, 75, 100):
            y = r.bottom() - pct / 100 * r.height()
            p.setPen(QPen(qc("border"), 1, Qt.SolidLine if pct in (0, 100) else Qt.DashLine))
            p.drawLine(QPointF(r.left(), y), QPointF(r.right(), y))
            p.setPen(qc("muted"))
            p.drawText(QRectF(0, y - 8, 38, 16), Qt.AlignRight | Qt.AlignVCenter, f"{pct}%")
        for t in range(self.T_MIN, self.T_MAX + 1, 10):
            x = self._to_px(t, 0).x()
            p.drawText(QRectF(x - 20, r.bottom() + 6, 40, 16), Qt.AlignCenter, f"{t}°")
        # zona de segurança
        x_safe = self._to_px(fc.SAFE_TEMP, 0).x()
        bad = qc("bad")
        bad.setAlpha(28)
        p.fillRect(QRectF(x_safe, r.top(), r.right() - x_safe, r.height()), bad)
        pts = sorted(self.points)
        if pts:
            path = QPainterPath(self._to_px(self.T_MIN, pts[0][1]))
            for t, pc in pts:
                path.lineTo(self._to_px(t, pc))
            path.lineTo(self._to_px(self.T_MAX, pts[-1][1]))
            area = QPainterPath(path)
            area.lineTo(r.bottomRight())
            area.lineTo(r.bottomLeft())
            area.closeSubpath()
            g = QLinearGradient(0, r.top(), 0, r.bottom())
            c1 = qc("accent")
            c1.setAlpha(80)
            c2 = qc("accent")
            c2.setAlpha(0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.fillPath(area, QBrush(g))
            p.setPen(QPen(qc("accent"), 2.5))
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
            if self.editable:
                for t, pc in pts:
                    p.setPen(QPen(qc("accent"), 2))
                    p.setBrush(qc("surface"))
                    p.drawEllipse(self._to_px(t, pc), 6, 6)
        if self.temp is not None and pts:
            t = max(self.T_MIN, min(self.T_MAX, self.temp))
            pc = 100 if t >= fc.SAFE_TEMP else max(fc.MIN_PCT, fc.curve_value(pts, t))
            pt = self._to_px(t, pc)
            p.setPen(QPen(qc("warn"), 1, Qt.DashLine))
            p.drawLine(QPointF(pt.x(), r.top()), QPointF(pt.x(), r.bottom()))
            p.setPen(Qt.NoPen)
            p.setBrush(qc("warn"))
            p.drawEllipse(pt, 5, 5)
            p.setPen(qc("text"))
            p.drawText(QRectF(pt.x() + 8, pt.y() - 22, 140, 18), Qt.AlignLeft,
                       f"agora {self.temp:.0f}° → {pc:.0f}%")
        p.end()


class FansPage(Page):
    def __init__(self, hub):
        super().__init__("Ventoinhas", "Perfis de ruído e arrefecimento, curva própria e estado de cada ventoinha.")
        self.hub = hub
        self.mgr = fan_manager(hub)
        self.btn_refresh = QPushButton("Procurar de novo")
        self.btn_refresh.clicked.connect(self._rediscover)
        self.head.addWidget(self.btn_refresh)

        self.tips = QWidget()
        self.tips.setObjectName("Transparent")
        self.tips_lay = QHBoxLayout(self.tips)
        self.tips_lay.setContentsMargins(0, 0, 0, 0)
        self.add(self.tips)

        # ----------------------------------------------------------- perfis
        prof = Card("Perfil", "Aplica-se a todas as ventoinhas marcadas em baixo. Acima de "
                              f"{fc.SAFE_TEMP} °C vão sempre a 100 %.", icon="fan")
        row = QHBoxLayout()
        row.setSpacing(8)
        self.prof_group = QButtonGroup(self)
        self.prof_group.setExclusive(True)
        self.prof_btns: dict[str, QPushButton] = {}
        for key, p in fc.PROFILES.items():
            b = QPushButton(p["name"])
            b.setCheckable(True)
            b.setToolTip(p["desc"])
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda _c, k=key: self._set_profile(k))
            self.prof_group.addButton(b)
            self.prof_btns[key] = b
            row.addWidget(b)
        row.addStretch(1)
        prof.add(row)
        self.prof_desc = label("", "Muted", wrap=True)
        prof.add(self.prof_desc)
        opts = QGridLayout()
        opts.setHorizontalSpacing(12)
        self.tg_power = Toggle(bool(get_setting("fan_power_sync")))
        self.tg_power.toggled.connect(lambda on: set_setting("fan_power_sync", on))
        self.tg_game = Toggle(bool(get_setting("fan_game_boost")))
        self.tg_game.toggled.connect(lambda on: set_setting("fan_game_boost", on))
        opts.addWidget(self.tg_power, 0, 0)
        opts.addWidget(label("Mudar também o perfil de energia (Silencioso → poupança, Desempenho → desempenho)", wrap=True),
                       0, 1)
        opts.addWidget(self.tg_game, 1, 0)
        opts.addWidget(label("Passar a «Desempenho» enquanto um jogo estiver aberto (Modo jogo)", wrap=True), 1, 1)
        opts.setColumnStretch(1, 1)
        prof.add(opts)
        self.add(prof)

        # ----------------------------------------------------------- curva
        cc = Card("Curva", "Rotação em função da temperatura. No perfil Personalizado arraste os pontos.")
        self.curve = CurveEditor()
        self.curve.edited.connect(self._curve_edited)
        cc.add(self.curve, 1)
        self.btn_reset_curve = QPushButton("Repor curva")
        self.btn_reset_curve.setObjectName("Ghost")
        self.btn_reset_curve.clicked.connect(lambda: self._curve_edited(list(fc.DEFAULT_CUSTOM)))
        cc.head.addWidget(self.btn_reset_curve)
        self.add(cc)

        # ----------------------------------------------------------- lista
        self.list_card = Card("Ventoinhas", "Rotação atual, quem as controla e que temperatura seguem.")
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(8)
        self.list_card.add(self.grid)
        self.add(self.list_card)
        self.body.addStretch(1)
        self.rows: dict[str, tuple] = {}
        self.mgr.changed.connect(self._rebuild)
        hub.updated.connect(self._update)
        self._rebuild()

    # ------------------------------------------------------------------
    def on_show(self):
        self._rebuild()

    def _rediscover(self):
        self.mgr.rediscover()
        notify(f"{len(self.mgr.fans)} ventoinha(s) controláveis encontradas.", "info")

    def _set_profile(self, key):
        if key != "auto" and fc.needs_access(self.mgr.fans):
            self._rebuild()
            notify("Primeiro permita o controlo das ventoinhas (botão em cima).", "warn")
            return
        self.mgr.set_profile(key)
        notify(f"Perfil de ventoinhas: {fc.PROFILES[key]['name']}.", "ok")

    def _curve_edited(self, pts):
        set_setting("fan_curve", [list(p) for p in pts])
        self._rebuild()

    def _grant(self):
        run_async(fc.grant_access, on_done=lambda r: (notify(r[1], "ok" if r[0] else "bad"), self.mgr.rediscover()))

    def _load_modules(self):
        if not confirm(self, "Procurar ventoinhas da motherboard",
                       "O Nexo vai tentar carregar os controladores nct6775, it87 e nct6683 (os mais comuns) e, "
                       "se algum funcionar, deixá-lo ativo nos próximos arranques.\n\nContinuar?"):
            return
        run_async(fc.load_board_modules,
                  on_done=lambda r: (notify(r[1], "ok" if r[0] else "warn"), self.mgr.rediscover()))

    def _rebuild(self):
        m = self.mgr
        # avisos
        while self.tips_lay.count():
            w = self.tips_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        col = QWidget()
        col.setObjectName("Transparent")
        v = QVBoxLayout(col)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        if IS_WIN:
            v.addWidget(Tip("No Windows o controlo das ventoinhas precisa de um controlador de kernel, que o Nexo não "
                            "instala. Recomendamos o <a href='https://getfancontrol.com'>FanControl</a> (gratuito, "
                            "código aberto). As rotações aparecem em Sensores se o LibreHardwareMonitor estiver "
                            "aberto.", "info"))
        else:
            if fc.needs_access(m.fans):
                t = Tip("Para controlar as ventoinhas o Nexo precisa de permissão de escrita nos ficheiros PWM do "
                        "kernel. É pedida a palavra-passe uma única vez (regra udev só para esses ficheiros).",
                        "warn")
                b = QPushButton("Permitir controlo")
                b.setObjectName("Primary")
                b.clicked.connect(self._grant)
                t.layout().addWidget(b, 0, Qt.AlignVCenter)
                v.addWidget(t)
            if fc.missing_board_fans(m.fans):
                t = Tip("Não aparecem ventoinhas da motherboard — normalmente falta carregar o controlador do chip "
                        "de sensores (Super I/O).", "info")
                b = QPushButton("Procurar ventoinhas")
                b.clicked.connect(self._load_modules)
                t.layout().addWidget(b, 0, Qt.AlignVCenter)
                v.addWidget(t)
            if m.error:
                v.addWidget(Tip(m.error, "warn"))
        self.tips_lay.addWidget(col)
        self.tips.setVisible(v.count() > 0)

        # perfis
        cur = m.profile()
        self.prof_btns[cur].setChecked(True)
        eff = m.effective_profile()
        desc = fc.PROFILES[cur]["desc"]
        if eff != cur:
            desc += " — neste momento em «Desempenho» porque há um jogo aberto."
        self.prof_desc.setText(desc)
        for k, b in self.prof_btns.items():
            b.setObjectName("Primary" if k == cur else "")
            b.setStyle(b.style())
        show = cur if cur != "auto" else "balanced"
        self.curve.set_curve(m.curve(show) or fc.DEFAULT_CUSTOM, editable=(cur == "custom"))
        self.btn_reset_curve.setVisible(cur == "custom")

        # lista
        g = self.grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        self.rows = {}
        if not m.fans:
            g.addWidget(label("Nenhuma ventoinha controlável encontrada." if not IS_WIN else
                              "Veja as rotações na página Sensores.", "Muted"), 0, 0)
            return
        for c, h in enumerate(("Ventoinha", "Rotação", "Velocidade", "Controlo", "Segue", "Nexo")):
            g.addWidget(label(h, "Muted"), 0, c)
        for i, f in enumerate(m.fans, start=1):
            name = label(f"<b>{f.label}</b><br><span style='color:{theme.C['muted']}'>{f.group} · {f.chip}</span>")
            rpm = label("—")
            pct = label("—")
            mode = label("—", "Muted")
            src = QComboBox()
            for k, n in SOURCES.items():
                src.addItem(n, k)
            src.setCurrentIndex(max(0, list(SOURCES).index(m.source(f)) if m.source(f) in SOURCES else 0))
            src.currentIndexChanged.connect(lambda _i, f=f, cb=src: m.set_source(f, cb.currentData()))
            tg = Toggle(m.included(f))
            tg.setToolTip("Desligado = o Nexo nunca mexe nesta ventoinha")
            tg.toggled.connect(lambda on, f=f: m.set_included(f, on))
            for c, w in enumerate((name, rpm, pct, mode, src, tg)):
                g.addWidget(w, i, c)
            self.rows[f.id] = (rpm, pct, mode)
        g.setColumnStretch(0, 1)
        self._update(None)

    def _update(self, _r):
        if not self.isVisible():
            return
        m = self.mgr
        self.curve.set_temp(m.temp_for(m.fans[0]) if m.fans else self.hub.latest("cpu_temp"))
        for f in m.fans:
            row = self.rows.get(f.id)
            if not row:
                continue
            rpm, pct, mode = row
            r = f.rpm()
            rpm.setText(f"{r} RPM" if r is not None else "—")
            p = f.pct()
            pct.setText(f"{p:.0f} %" if p is not None else "—")
            md = f.mode()
            mode.setText("Nexo" if f.id in m.touched else {"auto": "Automático (hardware)", "manual": "Manual",
                                                            "full": "Máximo"}[md])
