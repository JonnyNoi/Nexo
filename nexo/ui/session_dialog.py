"""Janela de uma sessão de jogo: resumo e gráfico de frametimes (Modo jogo → Sessões → clicar numa sessão)."""
from __future__ import annotations

import time

from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QVBoxLayout

from ..core import energy, sessions
from .charts import FrameTimeChart
from .widgets import StatTile, Tip, label


class SessionDialog(QDialog):
    def __init__(self, parent, sess: sessions.Session):
        super().__init__(parent)
        self.setWindowTitle(sess.game)
        self.resize(860, 560)
        v = QVBoxLayout(self)
        v.setContentsMargins(22, 20, 22, 18)
        v.setSpacing(12)
        v.addWidget(label(sess.game, "CardTitle"))
        when = time.strftime("%d/%m/%Y %H:%M", time.localtime(sess.start))
        h, m = divmod(int(round(sess.minutes)), 60)
        v.addWidget(label(f"{when} · {h} h {m:02d} min" if h else f"{when} · {m} min", "Muted"))
        fmt = lambda x, u="": "—" if x is None else f"{x:.0f}{u}"  # noqa: E731
        row = QHBoxLayout()
        tiles = [("FPS médio", fmt(sess.fps_avg), f"1 % low {fmt(sess.fps_low1)} · mín. {fmt(sess.fps_min)}"),
                 ("Engasgos", fmt(sess.stutters), self._stutter_sub(sess)),
                 ("Carga média", f"GPU {fmt(sess.gpu_load, ' %')}", f"CPU {fmt(sess.cpu_load, ' %')}"),
                 ("Temperatura máx.", f"CPU {fmt(sess.cpu_max, ' °C')}", f"GPU {fmt(sess.gpu_max, ' °C')}")]
        if sess.wh is not None:
            rest = energy.rest_w() * sess.minutes / 60
            tiles.append(("Energia", energy.fmt_energy(sess.wh + rest), energy.fmt_money(energy.cost(sess.wh + rest))))
        for t, val, sub in tiles:
            row.addWidget(StatTile(t, val, sub), 1)
        v.addLayout(row)
        tl = sess.timeline or []
        if len(tl) >= 10 and any(w for _f, w in tl):
            chart = FrameTimeChart(260)
            good = [f for f, _w in tl if f]
            normal = 1000.0 / sessions.percentile(good, 50) if good else None
            lim = max(2.5 * normal, normal + 20) if normal else None
            chart.set_data(tl, lim, sess.end - sess.start)
            v.addWidget(chart, 1)
            v.addWidget(label("Linha de baixo: quanto demorou em média cada fotograma (menos é melhor). Linha de "
                              "cima: o fotograma mais lento de cada momento. Os pontos vermelhos são engasgos — "
                              "fotogramas 2,5× mais lentos do que o normal, que se sentem mesmo com FPS alto.",
                              "Muted", wrap=True))
        elif len(tl) >= 10:
            v.addWidget(Tip("Esta fonte de FPS só dá a média de cada segundo (RTSS), por isso não há o fotograma "
                            "mais lento nem a contagem de engasgos. Com o PresentMon (Windows) ou o MangoHud (Linux) "
                            "o gráfico completo aparece.", "info"))
        else:
            v.addWidget(Tip("Esta sessão não tem frametimes: foi gravada antes desta versão do Nexo ou sem o contador "
                            "de FPS ativo (Modo jogo → Contador de FPS).", "info"))
            v.addStretch(1)
        bh = QHBoxLayout()
        bh.addStretch(1)
        close = QPushButton("Fechar")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        bh.addWidget(close)
        v.addLayout(bh)

    @staticmethod
    def _stutter_sub(sess: sessions.Session) -> str:
        if sess.stutters is None:
            return "sem dados"
        per_min = sess.stutters / max(1.0, sess.minutes)
        if per_min < 0.2:
            return "jogo fluido"
        if per_min < 1:
            return "alguns engasgos"
        return f"{per_min:.1f} por minuto — muitos"
