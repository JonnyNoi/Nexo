"""Página «Energia»: quanto o PC gasta (kWh) e quanto custa, por dia, por componente e por jogo."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QHeaderView, QSpinBox, QTableWidget, QTableWidgetItem)

from ...core import energy as en
from ...core.i18n import tr
from ...core.util import set_setting
from ..charts import StackedBars
from ..widgets import Card, Page, SettingRow, StatTile, Tip, hbox, label, run_async

CURRENCIES = ["€", "$", "£", "R$", "CHF", "kr", "zł"]


class EnergyPage(Page):
    def __init__(self, hub):
        super().__init__("Energia", "Quanto o PC gasta e quanto custa: consumo medido da CPU e da placa gráfica "
                         "mais uma estimativa do resto do computador. Conta enquanto o Nexo está aberto.")
        self.hub = hub
        row = hbox()
        self.t_now = StatTile("Agora", "—", "")
        self.t_today = StatTile("Hoje", "—", "")
        self.t_week = StatTile("Últimos 7 dias", "—", "")
        self.t_month = StatTile("Por mês (estimativa)", "—", "")
        for t in (self.t_now, self.t_today, self.t_week, self.t_month):
            row.addWidget(t, 1)
        self.add(row)
        self.warn = Tip("", "warn")
        self.warn.hide()
        self.add(self.warn)

        ch = Card("Custo por dia", "Últimos 30 dias. Passe o rato por cima de uma barra para ver o detalhe.",
                  icon="chart")
        self.period = QComboBox()
        for txt, n in (("14 dias", 14), ("30 dias", 30), ("90 dias", 90)):
            self.period.addItem(txt, n)
        self.period.setCurrentIndex(1)
        self.period.currentIndexChanged.connect(lambda _i: self.refresh())
        ch.head.addWidget(self.period)
        self.bars = StackedBars(220, fmt=lambda v: en.fmt_money(v))
        ch.add(self.bars)
        self.split = label("", "Muted", wrap=True)
        ch.add(self.split)
        self.add(ch)

        gm = Card("Jogos", "Energia e custo das sessões de jogo (últimos 30 dias). As sessões gravadas antes desta "
                  "versão não têm o consumo.", icon="gamepad")
        self.games = QTableWidget(0, 4)
        self.games.setHorizontalHeaderLabels(["Jogo", "Tempo", "Energia", "Custo"])
        hh = self.games.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.games.verticalHeader().setVisible(False)
        self.games.setEditTriggers(QTableWidget.NoEditTriggers)
        self.games.setSelectionMode(QTableWidget.NoSelection)
        self.games.setFocusPolicy(Qt.NoFocus)
        self.games.setAlternatingRowColors(True)
        self.games.setMinimumHeight(180)
        gm.add(self.games)
        self.games_info = label("", "Muted", wrap=True)
        gm.add(self.games_info)
        self.add(gm)

        cfg = Card("Preço e estimativas", icon="gear")
        self.sp_price = QDoubleSpinBox()
        self.sp_price.setDecimals(3)
        self.sp_price.setRange(0, 5)
        self.sp_price.setSingleStep(0.01)
        self.sp_price.setValue(en.price())
        self.sp_price.valueChanged.connect(lambda v: self._set("energy_price", round(float(v), 4)))
        self.cb_cur = QComboBox()
        self.cb_cur.addItems(CURRENCIES)
        cur = en.currency()
        if cur not in CURRENCIES:
            self.cb_cur.addItem(cur)
        self.cb_cur.setCurrentText(cur)
        self.cb_cur.currentTextChanged.connect(lambda v: self._set("energy_currency", v))
        cfg.add(SettingRow("Preço do kWh", "Está na fatura da eletricidade (preço da energia com taxas e IVA). "
                           "Em Portugal ronda os 0,15–0,25 €.", hbox(self.sp_price, self.cb_cur)))
        self.sp_rest = QSpinBox()
        self.sp_rest.setRange(0, 400)
        self.sp_rest.setSuffix(" W")
        self.sp_rest.setValue(int(en.rest_w()))
        self.sp_rest.valueChanged.connect(lambda v: self._set("energy_rest_w", int(v)))
        cfg.add(SettingRow("Resto do PC", "Placa-mãe, memória, discos, ventoinhas e perdas da fonte não têm sensor. "
                           "Um PC de secretária gasta normalmente 30–70 W nisto; um portátil 5–15 W. O monitor "
                           "não conta.", self.sp_rest))
        self.add(cfg)
        self.body.addStretch(1)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._live)
        self._busy = False

    def _set(self, key, value):
        set_setting(key, value)
        self.refresh()

    def on_show(self):
        self.refresh()
        self._live()
        self._timer.start(2000)

    def on_hide(self):
        self._timer.stop()

    def _live(self):
        cp, gp = self.hub.latest("cpu_power"), self.hub.latest("gpu_power")
        if cp is None and gp is None:
            self.t_now.set("—", "sem sensores de consumo")
        else:
            w = (cp or 0) + (gp or 0) + en.rest_w()
            self.t_now.set(f"{w:.0f} W", f"{en.fmt_money(en.cost(w))}/hora")
        if (cp is None or gp is None) and self.hub.last:
            what = ("Não há leitura do consumo da CPU nem da placa gráfica" if cp is None and gp is None else
                    "Não há leitura do consumo da CPU" if cp is None else
                    "Não há leitura do consumo da placa gráfica")
            self.warn.text.setText(tr(what) + tr(
                ": essa parte fica a zero e o custo sai mais baixo do que o real. No Linux, o consumo da CPU "
                "Intel/AMD (RAPL) só é legível pelo administrador em alguns sistemas; no Windows precisa do "
                "LibreHardwareMonitor (página Sensores)."))
            self.warn.show()
        else:
            self.warn.hide()

    def refresh(self):
        if self._busy:
            return
        self._busy = True
        n = self.period.currentData() or 30
        pending = self.hub.energy.pending()

        def work():
            return en.days(max(n, 30), pending=pending), en.per_game(30)

        def done(res):
            self._busy = False
            self._show(res[0], res[1], n)

        def fail(_m):
            self._busy = False
        run_async(work, on_done=done, on_fail=fail)

    def _show(self, rows: list[en.Day], games: list, n: int):
        rest = en.rest_w()
        today = rows[-1]
        wh = today.total_wh(rest)
        self.t_today.set(en.fmt_money(en.cost(wh)), en.fmt_energy(wh))
        wk = en.totals(rows[-7:], rest)
        self.t_week.set(en.fmt_money(en.cost(wk.wh)), f"{en.fmt_energy(wk.wh)} · {wk.hours:.0f} h ligado")
        est = en.month_estimate(rows[-30:], rest)
        self.t_month.set(en.fmt_money(est) if est is not None else "—",
                         "pelo uso dos últimos 30 dias" if est is not None else "ainda sem dados")
        shown = rows[-n:]
        labels = [time.strftime("%d/%m", time.strptime(d.day, "%Y-%m-%d")) for d in shown]
        values = [[en.cost(d.cpu_wh), en.cost(d.gpu_wh), en.cost(rest * d.seconds / 3600)] for d in shown]
        tips = []
        for d, lb in zip(shown, labels):
            t = d.total_wh(rest)
            tip = f"{lb}: {en.fmt_money(en.cost(t))} · {en.fmt_energy(t)} · {d.seconds / 3600:.1f} h ligado"
            if d.game_seconds:
                tip += tr(f" · a jogar {en.fmt_energy(d.game_total_wh(rest))}")
            tips.append(tr(tip))
        self.bars.set_data(labels, ["CPU", "Placa gráfica", "Resto do PC (estimativa)"], values, tips)
        tot = en.totals(shown, rest)
        if tot.wh:
            pct = lambda x: 100 * x / tot.wh  # noqa: E731
            txt = tr(f"Em {n} dias: {en.fmt_energy(tot.wh)} = {en.fmt_money(en.cost(tot.wh))} · média de "
                     f"{tot.avg_w:.0f} W com o PC ligado · CPU {pct(tot.cpu_wh):.0f} % · placa gráfica "
                     f"{pct(tot.gpu_wh):.0f} % · resto {pct(tot.rest_wh):.0f} %")
            if tot.game_wh:
                txt += tr(f" · a jogar {pct(tot.game_wh):.0f} %")
            self.split.setText(txt + ".")
        else:
            self.split.setText("Ainda não há dados: o consumo começa a ser registado a partir de agora.")
        self.games.setRowCount(len(games))
        for r, (g, h, gwh, c) in enumerate(games):
            hh, mm = divmod(int(round(h * 60)), 60)
            for col, txt in enumerate((g, f"{hh} h {mm:02d} min" if hh else f"{mm} min", en.fmt_energy(gwh),
                                       en.fmt_money(c))):
                it = QTableWidgetItem(txt)
                if col:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.games.setItem(r, col, it)
        if games:
            per_h = sum(x[2] for x in games) / max(0.01, sum(x[1] for x in games))
            self.games_info.setText(f"A jogar, o PC gasta em média {per_h:.0f} W — "
                                    f"{en.fmt_money(en.cost(per_h))} por hora de jogo.")
        else:
            self.games_info.setText("Sem sessões de jogo com consumo medido nos últimos 30 dias.")
