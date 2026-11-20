"""Página "Saúde dos discos": S.M.A.R.T. de cada disco — vida restante, temperatura, erros e veredicto."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QGridLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...core import smart
from ...core.util import IS_WIN, human_bytes, human_duration
from .. import theme
from ..widgets import Bar, Card, StatTile, Task, Page, Tip, hbox, icon_badge, label, notify, run_async, separator, status_dot

VERDICT = {"ok": ("Bom", "check"), "warn": ("Atenção", "alert"), "bad": ("Mau", "alert"),
           "unknown": ("Sem dados", "info")}


class DiskHealthPage(Page):
    def __init__(self):
        super().__init__("Saúde dos discos", "Lê os dados S.M.A.R.T. que cada disco regista sobre si próprio e diz se "
                                             "está de boa saúde, quanto já gastou e se há sinais de avaria.")
        self.btn_read = QPushButton("Ler discos")
        self.btn_read.setObjectName("Primary")
        self.btn_read.clicked.connect(self.read)
        self.head.addWidget(self.btn_read)

        top = Card("Estado", icon="hdd")
        self.status = label("", "Muted", wrap=True)
        top.add(self.status)
        self.install_row = QWidget()
        self.install_row.setObjectName("Transparent")
        self.btn_install = QPushButton("Instalar smartmontools")
        self.btn_install.clicked.connect(self._install)
        self.install_row.setLayout(hbox(Tip("Para ler os discos o Nexo usa o <b>smartctl</b> (pacote "
                                            "<b>smartmontools</b>), que não está instalado." +
                                            (" Sem ele mostra só o que o Windows reporta." if IS_WIN else ""),
                                            "warn"), self.btn_install))
        top.add(self.install_row)
        if smart.needs_password():
            top.add(label("Ler os dados dos discos precisa de permissões de administrador: a palavra-passe é "
                          "pedida uma vez por leitura. O resultado fica guardado e aparece também na "
                          "Saúde do sistema da Visão geral.", "Muted", wrap=True))
        self.add(top)

        self.list_holder = QWidget()
        self.list_holder.setObjectName("Transparent")
        self.list_lay = QVBoxLayout(self.list_holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(16)
        self.add(self.list_holder)

        self._build_bench()

        help_ = Card("Como ler isto", icon="info")
        help_.add(label(
            "• <b>Vida restante</b>: os SSD aguentam um número limitado de escritas; 100% é novo. Abaixo de 10% "
            "convém substituir.<br>"
            "• <b>Setores realocados / pendentes</b> (discos SATA): zonas estragadas. Se o número sobe de uma "
            "leitura para a outra, o disco está a degradar-se — faça cópia de segurança.<br>"
            "• <b>Erros CRC</b>: quase sempre o cabo SATA ou a ficha, não o disco.<br>"
            "• <b>Desligamentos inesperados</b>: cortes de energia ou desligar à força. Não é avaria, mas pode "
            "corromper ficheiros.<br>"
            "• Um veredicto «Bom» não garante que o disco nunca falha — tenha sempre cópia do que é importante.",
            "Muted", wrap=True))
        self.add(help_)
        self.body.addStretch(1)
        self._busy = False
        self._shown_time = None

    # ------------------------------------------------------------------ velocidade
    def _build_bench(self):
        from ...core import diskbench as db
        c = Card("Velocidade do disco", "Mede a leitura e a escrita a sério (sem a cache da memória): sequencial "
                 "(ficheiros grandes, cópias) e aleatória de 4 KiB (abrir programas e jogos).", icon="gauge")
        self.bench_target = QComboBox()
        self.bench_target.setMinimumWidth(320)
        self.bench_size = QComboBox()
        for txt, mib in (("256 MiB (rápido)", 256), ("1 GiB", 1024), ("4 GiB (mais preciso)", 4096)):
            self.bench_size.addItem(txt, mib * db.MiB)
        self.bench_size.setCurrentIndex(1)
        self.btn_bench = QPushButton("Testar velocidade")
        self.btn_bench.setObjectName("Primary")
        self.btn_bench.clicked.connect(self._bench_toggle)
        c.add(hbox(self.bench_target, self.bench_size, None, self.btn_bench))
        self.bench_bar = Bar()
        self.bench_bar.setVisible(False)
        c.add(self.bench_bar)
        grid = QGridLayout()
        grid.setSpacing(12)
        self.bench_tiles = {}
        for i, (k, t) in enumerate((("seq_read", "Leitura sequencial"), ("seq_write", "Escrita sequencial"),
                                    ("rnd_read", "Leitura aleatória 4K"), ("rnd_write", "Escrita aleatória 4K"))):
            tile = StatTile(t, "—", "MB/s")
            self.bench_tiles[k] = tile
            grid.addWidget(tile, 0, i)
        w = QWidget()
        w.setObjectName("Transparent")
        w.setLayout(grid)
        c.add(w)
        self.bench_info = label("Escreve um ficheiro temporário no disco escolhido e apaga-o no fim. Feche "
                                "programas que estejam a usar o disco para resultados mais fiéis.", "Muted", wrap=True)
        c.add(self.bench_info)
        self.add(c)
        self._bench_task = None
        self._bench_stop = None
        self._bench_targets_loaded = False

    def _load_bench_targets(self):
        from ...core import diskbench as db

        def done(ts):
            self.bench_target.clear()
            for lbl, where, free in ts:
                self.bench_target.addItem(f"{lbl} — {human_bytes(free)} livres", where)
            self.btn_bench.setEnabled(bool(ts))
            if not ts:
                self.bench_info.setText("Não encontrei nenhum disco onde seja possível escrever.")
        run_async(db.targets, on_done=done)

    def _bench_toggle(self):
        import threading
        from ...core import diskbench as db
        if self._bench_task is not None:
            self._bench_stop.set()
            self.btn_bench.setEnabled(False)
            return
        folder = self.bench_target.currentData()
        if not folder:
            return
        self._bench_stop = threading.Event()
        for t in self.bench_tiles.values():
            t.set("—", "MB/s")
        self.bench_bar.set(0)
        self.bench_bar.setVisible(True)
        self.btn_bench.setText("Cancelar")
        self.bench_info.setText("A testar… (não use o disco entretanto)")
        holder: dict = {}
        size = self.bench_size.currentData()
        stop = self._bench_stop
        t = Task(lambda: db.run(folder, size, lambda *a: holder["t"].progress.emit(a), stop))
        holder["t"] = t
        t.progress.connect(self._bench_progress)
        t.done.connect(self._bench_done)
        t.failed.connect(self._bench_failed)
        self._bench_task = t
        t.start()

    _PHASES = ("seq_write", "seq_read", "rnd_read", "rnd_write")

    def _bench_progress(self, ev):
        phase, frac, mbs = ev
        i = self._PHASES.index(phase)
        self.bench_bar.set((i + frac) / len(self._PHASES) * 100)
        self.bench_tiles[phase].set(f"{mbs:,.0f}".replace(",", " "), "MB/s · a medir…", "accent")

    def _bench_reset(self):
        self._bench_task = None
        self.btn_bench.setEnabled(True)
        self.btn_bench.setText("Testar velocidade")
        self.bench_bar.setVisible(False)

    def _bench_done(self, r):
        from ...core import diskbench as db
        self._bench_reset()
        fmt = lambda v: f"{v:,.0f}".replace(",", " ") if v >= 10 else f"{v:.1f}"  # noqa: E731
        self.bench_tiles["seq_read"].set(fmt(r.seq_read), "MB/s")
        self.bench_tiles["seq_write"].set(fmt(r.seq_write), "MB/s")
        self.bench_tiles["rnd_read"].set(fmt(r.rnd_read), f"MB/s · {r.rnd_read_iops:,.0f} IOPS".replace(",", " "))
        self.bench_tiles["rnd_write"].set(fmt(r.rnd_write), f"MB/s · {r.rnd_write_iops:,.0f} IOPS".replace(",", " "))
        self.bench_info.setText(db.verdict(r) + ("  " + " ".join(r.notes) if r.notes else ""))

    def _bench_failed(self, msg):
        self._bench_reset()
        if msg.startswith("Cancelled"):
            self.bench_info.setText("Teste cancelado (o ficheiro temporário foi apagado).")
            for t in self.bench_tiles.values():
                t.set("—", "MB/s")
        else:
            self.bench_info.setText(f"O teste falhou: {msg}")
            notify(f"Teste de velocidade do disco falhou: {msg}", "bad")

    def shutdown(self):
        if self._bench_stop is not None:
            self._bench_stop.set()

    # ------------------------------------------------------------------
    def on_show(self):
        if not self._bench_targets_loaded:
            self._bench_targets_loaded = True
            self._load_bench_targets()
        self.install_row.setVisible(not smart.smartctl_path())
        data = smart.cached()
        if data and data.get("time") != self._shown_time:
            self._show(data)
        elif not data:
            self.status.setText("Ainda não leu os discos. Carregue em «Ler discos»." if smart.needs_password()
                                else "A ler os discos…")
            if not smart.needs_password() and not self._busy:
                self.read()

    def refresh(self):
        self.read()

    def read(self):
        if self._busy:
            return
        if not smart.smartctl_path() and not IS_WIN:
            notify("Instale primeiro o smartmontools.", "warn")
            return
        self._busy = True
        self.btn_read.setEnabled(False)
        self.btn_read.setText("A ler…")
        self.status.setText("A ler os dados S.M.A.R.T. dos discos…")

        def done(res):
            self._busy = False
            self.btn_read.setEnabled(True)
            self.btn_read.setText("Ler discos")
            if res.get("disks"):
                self._show(res)
                bad = [d for d in res["disks"] if d["verdict"] in ("bad", "warn")]
                notify(f"{len(bad)} disco(s) precisam de atenção." if bad else "Os discos estão de boa saúde.",
                       "warn" if bad else "ok")
                win = self.window()
                if hasattr(win, "set_nav_badge"):
                    win.set_nav_badge("Saúde dos discos", str(len(bad)) if bad else None, "bad")
            else:
                self.status.setText(res.get("error") or "Não foi possível ler os discos.")

        def fail(msg):
            self._busy = False
            self.btn_read.setEnabled(True)
            self.btn_read.setText("Ler discos")
            self.status.setText(f"Erro: {msg}")
        run_async(smart.read_all, on_done=done, on_fail=fail)

    def _install(self):
        self.btn_install.setEnabled(False)
        self.btn_install.setText("A instalar…")

        def done(res):
            ok, msg = res
            self.btn_install.setEnabled(True)
            self.btn_install.setText("Instalar smartmontools")
            notify(msg, "ok" if ok else "bad")
            if ok:
                self.install_row.hide()
                self.read()
        run_async(smart.install_smartmontools, on_done=done)

    # ------------------------------------------------------------------
    def _show(self, data: dict):
        self._shown_time = data.get("time")
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        disks = data.get("disks", [])
        ago = time.time() - (data.get("time") or time.time())
        when = "agora mesmo" if ago < 60 else f"há {human_duration(ago).split(' ')[0]}"
        counts = {k: sum(1 for d in disks if d["verdict"] == k) for k in VERDICT}
        parts = [f"{status_dot('ok')} {counts['ok']} bom"]
        if counts["warn"]:
            parts.append(f"{status_dot('warn')} {counts['warn']} com atenção")
        if counts["bad"]:
            parts.append(f"{status_dot('bad')} {counts['bad']} com problemas")
        if counts["unknown"]:
            parts.append(f"{status_dot('muted')} {counts['unknown']} sem dados")
        self.status.setTextFormat(Qt.RichText)
        self.status.setText(f"{len(disks)} disco(s) · última leitura {when} &nbsp; " + " &nbsp; ".join(parts))
        from ...core import smarthist
        self._hist = smarthist._load()
        order = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
        for d in sorted(disks, key=lambda x: order.get(x["verdict"], 9)):
            self.list_lay.addWidget(self._disk_card(d))

    def _disk_card(self, d: dict) -> Card:
        sub = " · ".join(x for x in (d["kind"], human_bytes(d["size"], 0) if d["size"] else "", d["dev"],
                                     f"firmware {d['firmware']}" if d["firmware"] else "") if x)
        card = Card(d["model"], sub, icon="hdd")
        verdict, ic = VERDICT.get(d["verdict"], VERDICT["unknown"])
        kind = d["verdict"] if d["verdict"] in ("ok", "warn", "bad") else "info"
        v = label(verdict, "Big")
        v.setStyleSheet(f"color: {theme.C.get(kind, theme.C['muted'])}")
        card.head.addWidget(icon_badge(ic, 34, 18, kind), 0, Qt.AlignVCenter)
        card.head.addWidget(v, 0, Qt.AlignVCenter)

        if d.get("error") and not d["attrs"]:
            card.add(Tip(d["error"], "warn"))
            return card

        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(2)
        tiles = []
        if d["life"] is not None:
            tiles.append(("Vida restante", f"{d['life']:.0f}%"))
        t = d["temp"]
        if isinstance(t, (int, float)) and t > 0:
            tiles.append(("Temperatura", f"{t:.0f} °C"))
        if d["hours"] is not None:
            h = int(d["hours"])
            tiles.append(("Tempo ligado", f"{h:,} h".replace(",", " ") + (f" (~{h / 8760:.1f} anos)" if h >= 8760
                                                                             else "")))
        if d["written"]:
            tiles.append(("Dados escritos", human_bytes(d["written"])))
        if d["read"]:
            tiles.append(("Dados lidos", human_bytes(d["read"])))
        if d["cycles"] is not None:
            tiles.append(("Ligado/desligado", f"{d['cycles']}×"))
        if d["unsafe"]:
            tiles.append(("Desligamentos inesperados", str(d["unsafe"])))
        for i, (name, val) in enumerate(tiles):
            t1 = label(name.upper(), "Muted")
            t2 = label(val, "CardTitle")
            grid.addWidget(t1, 0, i)
            grid.addWidget(t2, 1, i)
        grid.setColumnStretch(len(tiles), 1)
        card.add(grid)
        if d["life"] is not None:
            bar = Bar(8)
            bar.set(d["life"], "bad" if d["life"] <= 10 else "warn" if d["life"] <= 25 else "ok")
            card.add(bar)

        card.add(separator())
        reasons = d.get("reasons") or []
        if not reasons:
            ok = "Sem sinais de avaria: sem setores estragados nem erros registados."
            if d["passed"] is True:
                ok = "O disco passa na autoavaliação S.M.A.R.T. e não há sinais de avaria."
            card.add(label(f"{status_dot('ok')} {ok}", wrap=True))
        for k, text in reasons:
            lb = label(f"{status_dot(k)} {text}", wrap=True)
            card.add(lb)
        if d.get("selftest"):
            card.add(label(f"Último autoteste: {d['selftest']}", "Muted", wrap=True))
        self._trend(card, d)

        table = QTableWidget(len(d["attrs"]), 3)
        table.setHorizontalHeaderLabels(["Atributo", "Valor", "Normalizado"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setColumnWidth(1, 200)
        table.setColumnWidth(2, 220)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        if not any(a[2] for a in d["attrs"]):
            table.hideColumn(2)
        for r, (name, val, norm, k) in enumerate(d["attrs"]):
            for c, txt in enumerate((name, val, norm)):
                it = QTableWidgetItem(txt)
                if k in ("warn", "bad") and c == 1:
                    it.setForeground(theme.qc(k))
                table.setItem(r, c, it)
        table.setFixedHeight(min(420, 34 + 30 * max(1, len(d["attrs"]))))
        table.hide()

        btn_det = QPushButton("Ver todos os atributos")
        btn_det.setObjectName("Ghost")
        btn_det.setCheckable(True)
        btn_det.toggled.connect(lambda on: (table.setVisible(on),
                                            btn_det.setText("Esconder atributos" if on else "Ver todos os atributos")))
        row = hbox(btn_det)
        if d.get("can_selftest") and smart.smartctl_path():
            btn_t = QPushButton("Autoteste rápido (2 min)")
            btn_t.setToolTip("O disco verifica-se a si próprio em segundo plano; pode continuar a usar o PC.")
            btn_t.clicked.connect(lambda _c=False, dev=d["dev"]: self._selftest(dev))
            row.addWidget(btn_t)
        row.addStretch(1)
        if d["serial"]:
            row.addWidget(label(f"N.º de série {d['serial']}", "Muted"))
        if d["attrs"]:
            card.add(row)
            card.add(table)
        return card

    def _trend(self, card: Card, d: dict):
        """Evolução ao longo do tempo: setores a subir, quando acaba a vida do SSD, escrita por dia."""
        from ...core import smarthist
        tr = smarthist.for_disk(d, getattr(self, "_hist", None))
        for k, text in tr.notes:
            card.add(label(f"{status_dot(k)} {text}", wrap=True))
        bits = []
        if tr.days:
            bits.append(f"Histórico de {tr.days} dias")
        if tr.written_per_day:
            bits.append(f"escreve ~{human_bytes(tr.written_per_day)} por dia")
        if not tr.days:
            bits.append("A partir de hoje o Nexo guarda a evolução deste disco (uma leitura por dia) para avisar "
                        "se os setores estragados começarem a subir e prever o fim da vida útil")
        elif tr.days < smarthist.MIN_SPAN_DAYS and d.get("life") is not None and tr.life_eta_days is None:
            bits.append(f"a previsão da vida útil precisa de {smarthist.MIN_SPAN_DAYS} dias de histórico")
        from ...core.i18n import tr
        card.add(label(" · ".join(tr(b) for b in bits) + ".", "Muted", wrap=True))

    def _selftest(self, dev: str):
        def done(res):
            ok, msg = res
            notify(msg, "ok" if ok else "bad")
        run_async(smart.start_selftest, dev, on_done=done)
