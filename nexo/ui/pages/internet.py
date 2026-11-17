"""Página Internet: teste de velocidade com velocímetro, diagnóstico da ligação e histórico."""
from __future__ import annotations

import math
import threading
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ...core import speedtest as sp
from .. import theme
from ..netmonitor import monitor, require_online
from ..theme import qc
from ..widgets import Card, LineChart, Page, Task, confirm, icon_badge, label, notify, scaled

TICKS = [0, 1, 5, 10, 25, 50, 100, 250, 500, 1000]
SWEEP = 240  # graus do arco


def _frac(v: float) -> float:
    """Escala do velocímetro (quase logarítmica, por troços entre as marcas)."""
    v = max(0.0, v)
    for i in range(len(TICKS) - 1):
        a, b = TICKS[i], TICKS[i + 1]
        if v <= b:
            return (i + (v - a) / (b - a)) / (len(TICKS) - 1)
    return 1.0


def fmt_speed(v: float | None) -> str:
    if v is None:
        return "—"
    return f"{v:.1f}" if v < 100 else f"{v:.0f}"


class Gauge(QWidget):
    """Velocímetro com arco em gradiente, marcas e valor animado."""

    def __init__(self):
        super().__init__()
        self.value = 0.0
        self.caption = "Pronto"
        self.unit = "Mb/s"
        self.colors = ("accent", "accent2")
        self.progress = 0.0
        self.setMinimumSize(360, 290)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(350)
        self._anim.valueChanged.connect(self._set_now)

    def _set_now(self, v):
        self.value = float(v)
        self.update()

    def set_value(self, v: float, animate: bool = True):
        self._anim.stop()
        if animate:
            self._anim.setStartValue(self.value)
            self._anim.setEndValue(float(v))
            self._anim.start()
        else:
            self._set_now(v)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        size = min(w - 40, (h - 20) * 1.25, 340)
        rect = QRectF((w - size) / 2, 18, size, size)
        c = rect.center()
        start = 90 + SWEEP / 2            # graus Qt (0 = 3 h, sentido anti-horário)
        thick = size * 0.075

        # fundo do arco
        p.setPen(QPen(qc("surface3"), thick, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(rect, int(start * 16), int(-SWEEP * 16))
        # arco do valor, em gradiente cónico
        f = _frac(self.value)
        if f > 0.002:
            g = QConicalGradient(c, start)
            g.setColorAt(0.0, qc(self.colors[0]))
            g.setColorAt(SWEEP / 360 * 0.999, qc(self.colors[1]))
            g.setColorAt(1.0, qc(self.colors[0]))
            # brilho por baixo
            glow = qc(self.colors[1], 28)
            p.setPen(QPen(glow, thick * 1.45, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(start * 16), int(-SWEEP * f * 16))
            p.setPen(QPen(g, thick, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(rect, int(start * 16), int(-SWEEP * f * 16))
        # marcas e números
        p.setFont(scaled(self.font(), 0.78, True))
        r_out = size / 2 - thick * 1.2
        for i, t in enumerate(TICKS):
            ang = math.radians(start - SWEEP * i / (len(TICKS) - 1))
            on = _frac(self.value) >= i / (len(TICKS) - 1) - 1e-6 and self.value > 0
            p.setPen(qc("text") if on else qc("muted"))
            tx = c.x() + math.cos(ang) * (r_out - 14)
            ty = c.y() - math.sin(ang) * (r_out - 14)
            p.drawText(QRectF(tx - 22, ty - 9, 44, 18), Qt.AlignCenter, str(t))
        # ponteiro
        ang = math.radians(start - SWEEP * f)
        tip = QPointF(c.x() + math.cos(ang) * (r_out - 34), c.y() - math.sin(ang) * (r_out - 34))
        base = QPointF(c.x() + math.cos(ang) * (size * 0.17), c.y() - math.sin(ang) * (size * 0.17))
        p.setPen(QPen(qc(self.colors[1]), 3.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(base, tip)
        # valor no centro
        p.setPen(qc("text"))
        p.setFont(scaled(self.font(), 3.6, True))
        p.drawText(QRectF(rect.left(), c.y() - size * 0.12, size, size * 0.2), Qt.AlignCenter,
                   fmt_speed(self.value) if self.value or self.caption not in ("Pronto",) else "0")
        p.setPen(qc("muted"))
        p.setFont(scaled(self.font(), 1.0, False))
        p.drawText(QRectF(rect.left(), c.y() + size * 0.08, size, 20), Qt.AlignCenter, self.unit)
        # fase atual
        p.setFont(scaled(self.font(), 1.05, True))
        p.setPen(qc(self.colors[0]))
        p.drawText(QRectF(rect.left(), c.y() + size * 0.2, size, 22), Qt.AlignCenter, self.caption)
        # barra de progresso fina
        if self.progress > 0:
            bw = size * 0.36
            y = c.y() + size * 0.2 + 30
            p.setPen(Qt.NoPen)
            p.setBrush(qc("surface3"))
            p.drawRoundedRect(QRectF(c.x() - bw / 2, y, bw, 4), 2, 2)
            p.setBrush(qc(self.colors[0]))
            p.drawRoundedRect(QRectF(c.x() - bw / 2, y, bw * min(1.0, self.progress), 4), 2, 2)
        p.end()


class Metric(Card):
    """Cartão pequeno: ícone, nome, valor grande e unidade."""

    def __init__(self, title: str, icon: str, unit: str, kind: str = "accent"):
        super().__init__()
        self.lay.setContentsMargins(18, 16, 18, 16)
        self.lay.setSpacing(6)
        top = QHBoxLayout()
        top.setSpacing(10)
        top.addWidget(icon_badge(icon, 30, 16, kind))
        t = label(title, "Muted")
        t.setFont(scaled(t.font(), 0.95, True))
        top.addWidget(t, 1)
        self.lay.addLayout(top)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.v = label("—", "Big")
        self.u = label(unit, "Muted")
        row.addWidget(self.v, 0, Qt.AlignBottom)
        row.addWidget(self.u, 0, Qt.AlignBottom)
        row.addStretch(1)
        self.lay.addLayout(row)
        self.sub = label("", "Muted", wrap=True)
        self.lay.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: str | None = None):
        self.v.setText(value)
        self.v.setStyleSheet(f"color: {theme.C[color]}" if color else "")
        self.sub.setText(sub)


class InternetPage(Page):
    def __init__(self):
        super().__init__("Internet", "Teste de velocidade, qualidade e diagnóstico da ligação")
        self.set_icon("wifi")
        self.task: Task | None = None
        self.stop = threading.Event()

        # ---------------------------------------------------------------- velocímetro + métricas
        top = QHBoxLayout()
        top.setSpacing(16)
        hero = Card()
        hero.lay.setContentsMargins(20, 14, 20, 20)
        self.gauge = Gauge()
        hero.add(self.gauge)
        self.btn = QPushButton("  Iniciar teste")
        self.btn.setObjectName("Primary")
        self.btn.setMinimumHeight(46)
        self.btn.setMinimumWidth(220)
        self.btn.setCursor(Qt.PointingHandCursor)
        f = self.btn.font()
        f.setPixelSize(15)
        self.btn.setFont(f)
        self.btn.clicked.connect(self._toggle)
        bh = QHBoxLayout()
        bh.addStretch(1)
        bh.addWidget(self.btn)
        bh.addStretch(1)
        hero.add(bh)
        self.server = label("Servidor: o mais próximo (Cloudflare) · ~25 s · gasta cerca de 50–500 MB "
                            "conforme a velocidade", "Muted", wrap=True)
        self.server.setAlignment(Qt.AlignCenter)
        hero.add(self.server)
        top.addWidget(hero, 5)

        grid = QGridLayout()
        grid.setSpacing(16)
        self.m_down = Metric("Download", "download", "Mb/s")
        self.m_up = Metric("Upload", "refresh", "Mb/s", "info")
        self.m_ping = Metric("Latência", "zap", "ms", "ok")
        self.m_jit = Metric("Variação (jitter)", "gauge", "ms", "warn")
        for i, m in enumerate((self.m_down, self.m_up, self.m_ping, self.m_jit)):
            grid.addWidget(m, i // 2, i % 2)
        gw = QWidget()
        gw.setObjectName("Transparent")
        gw.setLayout(grid)
        grid.setContentsMargins(0, 0, 0, 0)
        top.addWidget(gw, 4)
        self.add(top)

        # ---------------------------------------------------------------- gráfico
        self.chart_card = Card("Durante o teste", "Velocidade medida a cada 0,2 s.", icon="speed")
        self.chart = LineChart(capacity=100, y_max=None, unit="Mb/s", height=170)
        self.chart_card.add(self.chart)
        self.chart_card.setVisible(False)  # aparece quando se faz um teste
        self.add(self.chart_card)

        # ---------------------------------------------------------------- qualidade + diagnóstico
        row = QHBoxLayout()
        row.setSpacing(16)
        self.q_card = Card("O que a sua ligação permite", "Com base no último teste.", icon="check")
        self.q_box = QVBoxLayout()
        self.q_box.setSpacing(8)
        self.q_card.add(self.q_box)
        self.bloat = label("", "Muted", wrap=True)
        self.bloat.setTextFormat(Qt.RichText)
        self.q_card.add(self.bloat)
        self.q_card.lay.addStretch(1)
        row.addWidget(self.q_card, 1)

        netc = Card("Ligação à internet", "Testa a ligação passo a passo e diz onde está o problema.", icon="globe")
        self.net_state = label("A verificar…", wrap=True)
        self.net_state.setTextFormat(Qt.RichText)
        netc.add(self.net_state)
        self.net_steps = label("", "Muted", wrap=True)
        self.net_steps.setTextFormat(Qt.RichText)
        netc.add(self.net_steps)
        netc.lay.addStretch(1)
        self.btn_net = QPushButton("Testar ligação")
        bh2 = QHBoxLayout()
        bh2.addWidget(self.btn_net)
        bh2.addStretch(1)
        netc.add(bh2)
        self.btn_net.clicked.connect(self._test_net)
        row.addWidget(netc, 1)
        self.add(row)
        from ..wifi_card import WifiCard
        self.wifi = WifiCard()
        self.add(self.wifi)
        from ..firewall_card import FirewallCard
        self.firewall = FirewallCard()
        self.add(self.firewall)
        self._wifi_loaded = False
        monitor().checked.connect(self._show_net)
        if monitor().status is not None:
            self._show_net(monitor().status)

        # ---------------------------------------------------------------- programas
        from ...core.netprocs import NetProcMonitor
        self.np_mon = NetProcMonitor()
        pc = Card("Programas a usar a internet",
                  ("Velocidade de cada programa agora (ligações TCP) e quanto transferiu desde que abriu esta página. "
                   "Tráfego UDP (alguns jogos, chamadas, HTTP/3) aparece só como ligações.")
                  if self.np_mon.has_rates else
                  "Programas com ligações abertas para a internet e para quantos servidores. O Windows não diz "
                  "quanto cada programa transfere sem ferramentas extra.", icon="wifi")
        cols = ["Programa", "Ligações", "Servidores"] + (["Download", "Upload", "Total"] if self.np_mon.has_rates else [])
        self.np_table = QTableWidget(0, len(cols))
        self.np_table.setHorizontalHeaderLabels(cols)
        self.np_table.verticalHeader().setVisible(False)
        self.np_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.np_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.np_table.setShowGrid(False)
        self.np_table.setAlternatingRowColors(True)
        hh = self.np_table.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        self.np_table.setMinimumHeight(220)
        pc.add(self.np_table)
        self.add(pc)
        from PySide6.QtCore import QTimer
        self.np_timer = QTimer(self)
        self.np_timer.timeout.connect(self._np_tick)
        self._np_busy = False

        # ---------------------------------------------------------------- histórico
        hc = Card("Histórico", "Os últimos 30 testes ficam guardados neste computador.", icon="list")
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Data", "Download", "Upload", "Latência", "Variação", "Servidor"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setMinimumHeight(180)
        hc.add(self.table)
        self.btn_clear = QPushButton("Limpar histórico")
        self.btn_clear.setObjectName("Ghost")
        self.btn_clear.clicked.connect(self._clear)
        bh3 = QHBoxLayout()
        bh3.addStretch(1)
        bh3.addWidget(self.btn_clear)
        hc.add(bh3)
        self.add(hc)
        self.body.addStretch(1)

        self._fill_history()
        hist = sp.history()
        if hist:
            self._show_result(sp.SpeedResult(**{k: v for k, v in hist[0].items()
                                                if k in sp.SpeedResult.__dataclass_fields__}), animate=False)
        else:
            self._fill_quality(None)

    # ================================================================== programas
    def on_show(self):
        if not self._wifi_loaded:
            self._wifi_loaded = True
            self.wifi.load()
            self.firewall.load()
        self._np_tick()
        self.np_timer.start(2000)

    def on_hide(self):
        self.np_timer.stop()

    def _np_tick(self):
        if self._np_busy:
            return
        from ..widgets import run_async
        self._np_busy = True

        def done(rows):
            self._np_busy = False
            self._np_fill(rows)

        def fail(_m):
            self._np_busy = False
        run_async(self.np_mon.sample, on_done=done, on_fail=fail)

    def _np_fill(self, rows):
        from ...core.util import human_bytes
        t = self.np_table
        rows = rows[:40]
        t.setRowCount(len(rows))

        def cell(r, c, txt, tip=None):
            it = t.item(r, c)
            if it is None:
                it = QTableWidgetItem()
                if c:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                t.setItem(r, c, it)
            if it.text() != txt:
                it.setText(txt)
            if tip is not None:
                it.setToolTip(tip)
        rate = lambda v: "—" if v is None else f"{human_bytes(v)}/s" if v >= 1 else "0"  # noqa: E731
        for i, p in enumerate(rows):
            cell(i, 0, p.name, f"PID {p.pid}")
            cell(i, 1, str(p.conns))
            cell(i, 2, str(len(p.remotes)), "\n".join(sorted(p.remotes)[:15]))
            if self.np_mon.has_rates:
                cell(i, 3, rate(p.down))
                cell(i, 4, rate(p.up))
                tot = p.total_down + p.total_up
                cell(i, 5, human_bytes(tot) if tot else "—")

    # ================================================================== teste
    def _toggle(self):
        if self.task is not None:
            self.stop.set()
            self.btn.setEnabled(False)
            self.btn.setText("A cancelar…")
            return
        if not require_online("O teste de velocidade"):
            return
        self.stop = threading.Event()
        self.chart.clear()
        self.chart.set_capacity(100)
        self.chart_card.setVisible(True)
        for m in (self.m_down, self.m_up, self.m_ping, self.m_jit):
            m.set("—")
        self.btn.setText("  Cancelar")
        self.btn.setObjectName("Danger")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.gauge.caption = "A medir a latência…"
        self.gauge.colors = ("accent", "accent2")
        self.gauge.set_value(0)
        holder: dict = {}

        def work():
            return sp.run(lambda *a: holder["t"].progress.emit(a), self.stop)

        t = Task(work)
        holder["t"] = t
        t.progress.connect(self._progress)
        t.done.connect(self._done)
        t.failed.connect(self._failed)
        self.task = t
        t.start()

    def _progress(self, ev):
        kind, v, frac = ev
        if kind == "phase":
            self.gauge.progress = 0
            if v == "download":
                self.gauge.caption, self.gauge.colors = "Download", ("accent", "accent2")
            elif v == "upload":
                self.gauge.caption, self.gauge.colors = "Upload", ("info", "ok")
                self.gauge.set_value(0)
            self.gauge.update()
        elif kind == "info":
            self.m_ping.set(f"{v['ping']:.0f}", "", self._ping_color(v["ping"]))
            self.m_jit.set(f"{v['jitter']:.0f}")
            self.server.setText(f"Servidor: {v['server']}" + (f" · o seu IP: {v['ip']}" if v["ip"] else ""))
        elif kind == "done_phase":
            (self.m_down if v == "download" else self.m_up).set(fmt_speed(frac))
        elif kind in ("download", "upload"):
            self.gauge.progress = frac
            self.gauge.set_value(v)
            self.chart.push("Download" if kind == "download" else "Upload", v)
            if kind == "download":
                self.chart.push("Upload", None)
            else:
                self.chart.push("Download", None)
            self.chart.update()
            (self.m_down if kind == "download" else self.m_up).set(fmt_speed(v), "a medir…")

    def _reset_btn(self):
        self.task = None
        self.btn.setEnabled(True)
        self.btn.setText("  Testar de novo")
        self.btn.setObjectName("Primary")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)
        self.gauge.progress = 0

    def _done(self, r: sp.SpeedResult):
        self._reset_btn()
        sp.save(r)
        self._show_result(r)
        self._fill_history()
        notify(f"Teste concluído: ↓ {fmt_speed(r.download_mbps)} Mb/s · ↑ {fmt_speed(r.upload_mbps)} Mb/s · "
               f"{r.ping_ms:.0f} ms", "ok")

    def _failed(self, msg: str):
        self._reset_btn()
        cancelled = msg.startswith("Cancelled")
        self.gauge.caption = "Cancelado" if cancelled else "Falhou"
        self.gauge.set_value(0)
        if not cancelled:
            from ...core.network import friendly_error
            notify(f"O teste de velocidade falhou: {friendly_error(msg)}", "bad")

    @staticmethod
    def _ping_color(ms):
        return "ok" if ms <= 40 else "warn" if ms <= 100 else "bad"

    def _show_result(self, r: sp.SpeedResult, animate: bool = True):
        self.gauge.caption = "Download"
        self.gauge.colors = ("accent", "accent2")
        self.gauge.set_value(r.download_mbps or 0, animate)
        self.m_down.set(fmt_speed(r.download_mbps), sp.duration_for(1e9, r.download_mbps or 0) + " por GB")
        self.m_up.set(fmt_speed(r.upload_mbps), "envio de ficheiros e chamadas")
        if r.ping_ms is not None:
            sub = f"com a ligação cheia: {r.loaded_ping_ms:.0f} ms" if r.loaded_ping_ms else ""
            self.m_ping.set(f"{r.ping_ms:.0f}", sub, self._ping_color(r.ping_ms))
        if r.jitter_ms is not None:
            self.m_jit.set(f"{r.jitter_ms:.0f}", "estável" if r.jitter_ms <= 10 else "instável" if r.jitter_ms > 30
                           else "aceitável", "ok" if r.jitter_ms <= 10 else "bad" if r.jitter_ms > 30 else "warn")
        when = time.strftime("%d/%m %H:%M", time.localtime(r.when))
        self.server.setText(f"Último teste: {when}" + (f" · {r.server}" if r.server else ""))
        self._fill_quality(r)

    def _fill_quality(self, r: sp.SpeedResult | None):
        while self.q_box.count():
            it = self.q_box.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if r is None:
            self.q_box.addWidget(label("Faça um teste para ver se a ligação chega para jogos, vídeo em 4K, "
                                       "chamadas e transmissões.", "Muted", wrap=True))
            self.bloat.setText("")
            return
        for name, lvl, det in sp.quality(r):
            h = QHBoxLayout()
            h.setSpacing(10)
            h.addWidget(icon_badge({"ok": "check", "warn": "alert", "bad": "x"}[lvl], 24, 14, lvl))
            h.addWidget(label(name), 1)
            h.addWidget(label(det, "Muted"))
            w = QWidget()
            w.setObjectName("Transparent")
            w.setLayout(h)
            h.setContentsMargins(0, 0, 0, 0)
            self.q_box.addWidget(w)
        bb = sp.bufferbloat(r)
        if bb:
            lvl, txt = bb
            self.bloat.setText(f"<span style='color:{theme.C[lvl]}'>●</span> {txt}")
        else:
            self.bloat.setText("")

    # ================================================================== histórico
    def _fill_history(self):
        h = sp.history()
        self.table.setRowCount(len(h))
        for i, r in enumerate(h):
            vals = [time.strftime("%d/%m/%Y %H:%M", time.localtime(r.get("when", 0))),
                    f"{fmt_speed(r.get('download_mbps'))} Mb/s", f"{fmt_speed(r.get('upload_mbps'))} Mb/s",
                    f"{r['ping_ms']:.0f} ms" if r.get("ping_ms") is not None else "—",
                    f"{r['jitter_ms']:.0f} ms" if r.get("jitter_ms") is not None else "—", r.get("server", "")]
            for j, v in enumerate(vals):
                it = QTableWidgetItem(v)
                if j == 1:
                    it.setForeground(QColor(theme.C["accent"]))
                self.table.setItem(i, j, it)
        self.btn_clear.setVisible(bool(h))

    def _clear(self):
        if confirm(self, "Limpar histórico", "Apagar o histórico dos testes de velocidade?"):
            sp.clear_history()
            self._fill_history()

    # ================================================================== diagnóstico
    def _test_net(self):
        self.btn_net.setEnabled(False)
        self.btn_net.setText("A testar…")
        monitor().refresh(full=True)

    def _show_net(self, st):
        self.btn_net.setEnabled(True)
        self.btn_net.setText("Testar ligação")
        color = theme.C.get(st.level, theme.C["muted"])
        self.net_state.setText(f"<span style='color:{color}'>●</span> <b>{st.label}</b>"
                               + (f" · {st.short()}" if st.online and st.short() != st.label else "")
                               + f"<br><span style='color:{theme.C['muted']}'>{st.detail}</span>")
        rows = []
        for name, ok, det in st.steps:
            c = theme.C["ok"] if ok else theme.C["bad"] if ok is False else theme.C["muted"]
            mark = "✔" if ok else "✘" if ok is False else "–"
            rows.append(f"<span style='color:{c}'>{mark}</span> {name}: {det}")
        self.net_steps.setText("<br>".join(rows))
