"""Página "Fiabilidade": crashes, desligares sem aviso, erros de hardware e throttling — com explicação."""
from __future__ import annotations

import time
from datetime import date, timedelta

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QPushButton, QSizePolicy, QVBoxLayout, QWidget

from ...core import reliability as rel
from ...core import throttle
from ...core.util import IS_WIN
from .. import theme
from ..widgets import Card, Page, StatTile, Tip, hbox, label, notify, run_async, status_dot


class DayStrip(QWidget):
    """Faixa de 30 quadrados (um por dia): verde sem problemas, amarelo avisos, vermelho problemas graves."""

    def __init__(self):
        super().__init__()
        self.days: list[str] = ["ok"] * rel.DAYS
        self.setMinimumHeight(46)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.setAccessibleName("Estado de cada um dos últimos 30 dias")

    def set_days(self, days: list[str]):
        self.days = days
        bad = sum(1 for d in days if d == "bad")
        warn = sum(1 for d in days if d == "warn")
        self.setAccessibleDescription(f"{bad} dias com problemas graves, {warn} com avisos")
        self.update()

    def _cell(self) -> tuple[float, float]:
        n = max(1, len(self.days))
        gap = 4.0
        w = (self.width() - gap * (n - 1)) / n
        return w, gap

    def mouseMoveEvent(self, e):
        w, gap = self._cell()
        i = int(e.position().x() // (w + gap))
        if 0 <= i < len(self.days):
            d = date.today() - timedelta(days=len(self.days) - 1 - i)
            txt = {"ok": "sem problemas", "warn": "avisos", "bad": "problemas graves"}[self.days[i]]
            self.setToolTip(f"{d.strftime('%d/%m')}: {txt}")

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, gap = self._cell()
        h = 26
        for i, k in enumerate(self.days):
            c = theme.qc(k, 255 if k != "ok" else 110)
            p.setPen(Qt.NoPen)
            p.setBrush(c)
            p.drawRoundedRect(QRectF(i * (w + gap), 0, w, h), 5, 5)
        p.setPen(theme.qc("muted"))
        f = p.font()
        if f.pointSizeF() > 0:
            f.setPointSizeF(f.pointSizeF() * 0.85)
        elif f.pixelSize() > 0:
            f.setPixelSize(max(9, int(f.pixelSize() * 0.85)))
        p.setFont(f)
        p.drawText(QRectF(0, h + 2, self.width() / 2, 18), Qt.AlignLeft, f"há {len(self.days)} dias")
        p.drawText(QRectF(self.width() / 2, h + 2, self.width() / 2, 18), Qt.AlignRight, "hoje")
        p.end()


def _when(ts: float) -> str:
    d = date.fromtimestamp(ts)
    days = (date.today() - d).days
    hm = time.strftime("%H:%M", time.localtime(ts))
    if days == 0:
        return f"hoje às {hm}"
    if days == 1:
        return f"ontem às {hm}"
    return time.strftime("%d/%m %H:%M", time.localtime(ts))


class ReliabilityPage(Page):
    def __init__(self):
        super().__init__("Fiabilidade", "O que correu mal no PC nos últimos 30 dias — desligares sem aviso, falhas do "
                         "sistema, erros de hardware, do controlador gráfico e programas que fecharam — e o que fazer.")
        self.btn = QPushButton("Analisar agora")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(self.scan)
        self.head.addWidget(self.btn)

        top = Card("Estabilidade", icon="chart")
        row = hbox()
        self.t_index = StatTile("Índice", "—", "0 a 10 (como o Monitor de Fiabilidade do Windows)")
        self.t_week = StatTile("Últimos 7 dias", "—", "")
        self.t_month = StatTile("Últimos 30 dias", "—", "")
        for t in (self.t_index, self.t_week, self.t_month):
            row.addWidget(t, 1)
        top.add(row)
        self.strip = DayStrip()
        top.add(self.strip)
        self.status = label("", "Muted", wrap=True)
        top.add(self.status)
        self.limited_tip = Tip("O registo do sistema não é legível pelo seu utilizador, por isso só aparecem os "
                               "eventos dos seus programas. Para ver tudo, junte-se ao grupo <b>wheel</b>, "
                               "<b>adm</b> ou <b>systemd-journal</b> (ex.: <code>sudo usermod -aG systemd-journal "
                               "$USER</code>) e volte a entrar na sessão.", "warn")
        self.limited_tip.hide()
        top.add(self.limited_tip)
        self.add(top)

        self.cards_holder = QWidget()
        self.cards_holder.setObjectName("Transparent")
        self.cards = QVBoxLayout(self.cards_holder)
        self.cards.setContentsMargins(0, 0, 0, 0)
        self.cards.setSpacing(16)
        self.add(self.cards_holder)

        self.thr = Card("Limitação por temperatura (throttling)",
                        "O Nexo vigia o processador e a placa gráfica enquanto está aberto: se baixarem o clock por "
                        "estarem demasiado quentes, fica registado aqui (e avisa, se os alertas estiverem ligados).",
                        icon="thermo")
        self.thr_lbl = label("", wrap=True)
        self.thr_lbl.setTextFormat(Qt.RichText)
        self.thr.add(self.thr_lbl)
        self.add(self.thr)
        self.add(Tip("A análise lê os registos do " + ("Visualizador de Eventos do Windows" if IS_WIN else
                     "journal do systemd e o coredumpctl") + " — não precisa de palavra-passe e não altera nada."))
        self.body.addStretch(1)
        self._busy = False
        self._shown = None

    # ------------------------------------------------------------------
    def on_show(self):
        data = rel.cached()
        if data.get("when") != self._shown:
            self._render(data)
        if not data or time.time() - data.get("when", 0) > 3600:
            self.scan()
        self._render_throttle()

    def scan(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)
        self.btn.setText("A analisar…")

        def done(data):
            self._busy = False
            self.btn.setEnabled(True)
            self.btn.setText("Analisar agora")
            self._render(data)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            self.btn.setText("Analisar agora")
            notify(f"Não foi possível ler os registos: {m}", "bad")
        run_async(rel.scan, on_done=done, on_fail=fail)

    def _render(self, data: dict):
        self._shown = data.get("when")
        evs = rel.events(data)
        if not data:
            self.status.setText("Ainda não foi feita nenhuma análise.")
            return
        idx = rel.stability_index(evs)
        kind = "ok" if idx >= 8 else "warn" if idx >= 5 else "bad"
        self.t_index.set(f"{idx:.1f}", None, kind)
        for tile, days in ((self.t_week, 7), (self.t_month, 30)):
            s = rel.summary(evs, days=days)
            serious = sum(n for c, n in s.items() if rel.CATEGORIES[c][1] == "bad")
            other = sum(n for c, n in s.items() if rel.CATEGORIES[c][1] != "bad")
            tile.set(str(serious) if serious else "0", f"graves · {other} avisos",
                     "bad" if serious else ("warn" if other else "ok"))
        self.strip.set_days(rel.per_day(evs))
        self.status.setText(f"Última análise: {_when(data['when'])}.")
        self.limited_tip.setVisible(bool(data.get("limited")))
        # cartões por categoria
        while self.cards.count():
            w = self.cards.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        by_cat: dict[str, list] = {}
        for e in evs:
            by_cat.setdefault(e.cat, []).append(e)
        if not by_cat:
            c = Card()
            c.add(label(f"{status_dot('ok')} <b>Nada a registar nos últimos {data.get('days', 30)} dias.</b> "
                        "O sistema não registou falhas, desligares inesperados nem erros de hardware.", wrap=True))
            self.cards.addWidget(c)
            return
        for cat in rel.ORDER:
            lst = by_cat.get(cat)
            if not lst:
                continue
            name, kind, advice = rel.CATEGORIES[cat]
            total = len(lst) if cat == "shutdown" else sum(e.count for e in lst)
            c = Card(f"{name} — {total}×", advice, icon="alert" if kind == "bad" else "info")
            lines = []
            if cat == "app":
                per: dict[str, list] = {}
                for e in lst:
                    per.setdefault(e.title, []).append(e)
                for app, es in sorted(per.items(), key=lambda kv: -sum(x.count for x in kv[1]))[:10]:
                    n = sum(x.count for x in es)
                    lines.append(f"{status_dot(kind)} <b>{app}</b> — {n}× (última: {_when(es[0].when)})")
            else:
                for e in lst[:8]:
                    extra = f" ({e.count}×)" if e.count > 1 else ""
                    det = e.detail.replace("<", "&lt;")
                    lines.append(f"{status_dot(kind)} <b>{_when(e.when)}</b> — {e.title}{extra}"
                                 + (f"<br><span style='color:{theme.C['muted']}'>{det}</span>" if det else ""))
                if len(lst) > 8:
                    lines.append(f"… e mais {len(lst) - 8}.")
            lb = label("<br>".join(lines), wrap=True)
            lb.setTextFormat(Qt.RichText)
            lb.setTextInteractionFlags(Qt.TextSelectableByMouse)
            c.add(lb)
            page = {"disk": "Saúde dos discos", "thermal": "Sensores", "memory": "Processos",
                    "hardware": "Stress test", "gpu": "Atualizações"}.get(cat)
            if page:
                b = QPushButton(f"Abrir {page}")
                b.setObjectName("Ghost")
                b.clicked.connect(lambda _c=False, p=page: self.window().go_name(p))
                c.add(hbox(None, b))
            self.cards.addWidget(c)

    def _render_throttle(self):
        win = self.window()
        det = getattr(win, "throttle", None)
        lines = []
        if det is not None:
            for comp, ep in det.active().items():
                lines.append(f"{status_dot('bad')} <b>Agora:</b> {throttle.describe(ep)}")
        eps = throttle.recent(30)
        for ep in eps[:10]:
            lines.append(f"{status_dot('warn')} <b>{_when(ep.start)}</b> — {throttle.describe(ep)}")
        if not lines:
            lines.append(f"{status_dot('ok')} Nenhuma limitação por temperatura registada. "
                         + ("Limites: processador {:.0f} °C, placa gráfica {:.0f} °C.".format(*det.limits.values())
                            if det is not None else ""))
        else:
            comps = {ep.comp for ep in eps}
            lines.append("<br>" + " ".join(throttle.ADVICE[c] for c in sorted(comps)))
        self.thr_lbl.setText("<br>".join(lines))
