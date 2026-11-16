from __future__ import annotations

import time

import psutil
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ...core import sysinfo
from ...core.util import IS_LINUX, IS_WIN, human_bytes, human_duration, load_json
from ...core import healthscore
from ..widgets import Card, LineChart, Page, Ring, StatTile, hbox, label, run_async

METRICS = {"Temperatura": ("cpu_temp", "gpu_temp", "°C", 100), "Carga": ("cpu_load", "gpu_load", "%", 100),
           "Consumo": ("cpu_power", "gpu_power", "W", None)}
WINDOWS = {"1 min": 60, "5 min": 300, "15 min": 900}


class DashboardPage(Page):
    def __init__(self, hub):
        super().__init__("Visão geral", "Estado do PC em tempo real")
        self.hub = hub

        # ---------------------------------------------------------------- saúde do PC (pontuação)
        self.score_card = Card()
        self.score_card.setObjectName("Card")
        sc = QHBoxLayout()
        sc.setSpacing(22)
        self.r_score = Ring("Saúde do PC", 118)
        self.r_score.set(0, "—", "")
        self.r_score.setAccessibleName("Pontuação da saúde do PC")
        sc.addWidget(self.r_score)
        right = QVBoxLayout()
        right.setSpacing(6)
        self.score_title = label("A avaliar…", "CardTitle")
        right.addWidget(self.score_title)
        self.score_sub = label("Pontuação de 0 a 100 a partir das verificações abaixo.", "Muted", wrap=True)
        right.addWidget(self.score_sub)
        self.actions_box = QVBoxLayout()
        self.actions_box.setSpacing(4)
        right.addLayout(self.actions_box)
        right.addStretch(1)
        wk = QHBoxLayout()
        wk.addStretch(1)
        self.btn_week = QPushButton("Relatório da semana")
        self.btn_week.setObjectName("Ghost")
        self.btn_week.setToolTip("Como esteve o PC nos últimos 7 dias, comparado com a semana anterior.")
        self.btn_week.clicked.connect(self.open_weekly)
        wk.addWidget(self.btn_week)
        right.addLayout(wk)
        sc.addLayout(right, 1)
        self.score_card.add(sc)
        self.add(self.score_card)
        from ..slowdiag_card import SlowDiagCard
        self.slow_card = SlowDiagCard(hub)
        self.add(self.slow_card)
        self._slow: list = []
        self._slow_at = 0.0

        grid = QGridLayout()
        grid.setSpacing(16)
        self.t_cpu = StatTile("Processador")
        self.t_gpu = StatTile("Placa gráfica")
        self.t_ram = StatTile("Memória")
        self.t_os = StatTile("Sistema")
        for i, t in enumerate((self.t_cpu, self.t_gpu, self.t_ram, self.t_os)):
            t.v.setObjectName("CardTitle")
            grid.addWidget(t, 0, i)
            grid.setColumnStretch(i, 1)
        self.add(grid)

        chart_card = Card("CPU × GPU")
        self.metric_cb = QComboBox()
        self.metric_cb.addItems(METRICS)
        self.window_cb = QComboBox()
        self.window_cb.addItems(WINDOWS)
        self.window_cb.setCurrentIndex(1)
        chart_card.head.addWidget(self.metric_cb)
        chart_card.head.addWidget(self.window_cb)
        self.chart = LineChart(capacity=300, height=220)
        chart_card.add(self.chart, 1)
        self.metric_cb.currentTextChanged.connect(lambda _t: self._redraw())
        self.window_cb.currentTextChanged.connect(lambda _t: self._redraw())

        rings = Card("Utilização")
        rl = QHBoxLayout()
        self.r_ram = Ring("RAM")
        self.r_vram = Ring("VRAM")
        self.r_disk = Ring("Disco do sistema")
        for r in (self.r_ram, self.r_vram, self.r_disk):
            rl.addWidget(r)
        rings.add(rl)
        self.bench_lbl = label("Ainda sem resultados de benchmark.", "Muted", wrap=True)
        rings.add(self.bench_lbl)
        rings.lay.addStretch(1)

        row = QHBoxLayout()
        row.setSpacing(16)
        row.addWidget(chart_card, 3)
        row.addWidget(rings, 2)
        self.add(row)

        self.tiles_row = hbox()
        self.t_temp_cpu = StatTile("Temp. CPU")
        self.t_temp_gpu = StatTile("Temp. GPU")
        self.t_net = StatTile("Rede")
        self.t_disk_io = StatTile("Disco")
        for t in (self.t_temp_cpu, self.t_temp_gpu, self.t_net, self.t_disk_io):
            self.tiles_row.addWidget(t)
        self.add(self.tiles_row)

        self.health = Card("Saúde do sistema", "Verificações automáticas — os botões levam à página que resolve.",
                           icon="heart")
        self.health_grid = QGridLayout()
        self.health_grid.setHorizontalSpacing(24)
        self.health_grid.setVerticalSpacing(8)
        self.health.add(self.health_grid)
        self.add(self.health)
        self._health_key = None
        self._failed_services = None
        self.body.addStretch(1)

        self._cores = f"{psutil.cpu_count(False)}C / {psutil.cpu_count(True)}T"
        self._boot = psutil.boot_time()
        self._tick = 0
        hub.updated.connect(self._update)
        run_async(sysinfo.summary, on_done=self._summary)

    def _summary(self, s):
        self.t_cpu.set(s["cpu"], s["threads"])
        self.t_gpu.set(s["gpu"], "")
        self.t_ram.set(s["ram"], "")
        self.t_os.set(s["os"], "")

    def on_show(self):
        self._tick = 0
        if IS_LINUX and self._failed_services is None:
            def failed():
                from ...core.util import run
                _c, out = run(["systemctl", "--failed", "--no-legend", "--plain"], timeout=10)
                return len([ln for ln in out.splitlines() if ln.strip() and ".service" in ln])
            run_async(failed, on_done=lambda n: setattr(self, "_failed_services", n), on_fail=lambda _m: None)
        hist = load_json("bench_history.json", [])
        if hist:
            last = hist[-1]
            best = max(h["score"] for h in hist if h["mode"] == last["mode"])
            self.bench_lbl.setText(f"Último benchmark ({last['mode']}): <b>{last['score']:.0f} pts</b>"
                                   f" · melhor: {best:.0f} pts")
        self._redraw()

    def _redraw(self):
        a, b, unit, ymax = METRICS[self.metric_cb.currentText()]
        n = WINDOWS[self.window_cb.currentText()]
        self.chart.clear()
        self.chart.unit = unit
        self.chart.y_max = ymax
        self.chart.set_capacity(n)
        for key, name in ((a, "CPU"), (b, "GPU")):
            for v in list(self.hub.history.get(key, []))[-n:]:
                self.chart.push(name, v)
        self.chart.update()

    # ------------------------------------------------------------------ saúde
    def _checks(self, vm) -> list[tuple[str, str, str | None]]:
        """[(tipo, texto, página para resolver)]"""
        h = self.hub
        out = []
        ct, gt = h.latest("cpu_temp"), h.latest("gpu_temp")
        for name, t, warn, bad in (("CPU", ct, 80, 90), ("GPU", gt, 80, 88)):
            if t is None:
                continue
            if t >= bad:
                out.append(("bad", f"{name} muito quente: {t:.0f} °C — verifique ventoinhas e pasta térmica.", "Sensores"))
            elif t >= warn:
                out.append(("warn", f"{name} quente: {t:.0f} °C.", "Sensores"))
            else:
                out.append(("ok", f"Temperatura da {name} normal ({t:.0f} °C).", None))
        if vm.percent >= 90:
            out.append(("bad", f"RAM quase cheia ({vm.percent:.0f}%).", "Processos"))
        elif vm.percent >= 80:
            out.append(("warn", f"RAM muito usada ({vm.percent:.0f}%).", "Processos"))
        else:
            out.append(("ok", f"RAM com folga ({vm.percent:.0f}% em uso).", None))
        du = getattr(self, "_du", None)
        if du is not None:
            free_pct = 100 - du.percent
            if free_pct < 10:
                out.append(("bad", f"Disco do sistema quase cheio ({human_bytes(du.free)} livres).", "Espaço em disco"))
            elif free_pct < 20:
                out.append(("warn", f"Pouco espaço no disco do sistema ({human_bytes(du.free)} livres).",
                            "Espaço em disco"))
            else:
                out.append(("ok", f"Espaço em disco suficiente ({human_bytes(du.free)} livres).", None))
        try:
            sw = psutil.swap_memory()
        except Exception:  # Windows com contadores de desempenho desativados
            sw = None
        if sw and sw.total and sw.percent > 60:
            out.append(("warn", f"Muito swap em uso ({sw.percent:.0f}%) — o PC pode ficar lento.", "Processos"))
        out.extend(self._disk_health_checks())
        up = time.time() - self._boot
        if up > 7 * 86400:
            out.append(("warn", f"Ligado há {human_duration(up)} — reiniciar aplica atualizações e liberta memória.",
                        None))
        if self._failed_services:
            out.append(("warn", f"{self._failed_services} serviço(s) do sistema com falha.", "Utilitários"))
        if time.time() - self._slow_at > 60:   # atualizações, antivírus, drivers: só caches, 1×/min
            self._slow_at = time.time()
            try:
                self._slow = healthscore.slow_checks()
            except Exception:  # noqa: BLE001 — uma cache estragada não pode partir o painel
                import logging
                logging.getLogger("nexo.health").warning("Verificações lentas falharam", exc_info=True)
                self._slow = []
        out.extend((c.kind, c.text, c.page) for c in self._slow)
        return out

    def _disk_health_checks(self) -> list:
        """Resultado da última leitura S.M.A.R.T. (página "Saúde dos discos"), relido só quando muda."""
        from ...core import smart
        from ...core.util import config_dir
        try:
            mtime = (config_dir() / smart.CACHE).stat().st_mtime
        except OSError:
            return []
        if getattr(self, "_smart_mtime", None) != mtime:
            self._smart_mtime = mtime
            data = smart.cached() or {}
            out = []
            for d in data.get("disks", []):
                if d.get("verdict") in ("bad", "warn"):
                    why = next((t for k, t in d.get("reasons", []) if k == d["verdict"]), "")
                    out.append((d["verdict"], f"Disco {d.get('model', '')}: {why}", "Saúde dos discos"))
            if data.get("disks") and not out:
                out.append(("ok", f"Discos de boa saúde ({len(data['disks'])} verificados).", None))
            self._smart_checks = out
        return list(getattr(self, "_smart_checks", []))

    def _update_health(self, vm):
        from .. import theme
        from ..widgets import icon_badge
        checks = self._checks(vm)
        key = tuple((k, t) for k, t, _p in checks)
        if key == self._health_key:
            return
        self._health_key = key
        self._update_score(checks)
        g = self.health_grid
        while g.count():
            w = g.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        checks.sort(key=lambda c: {"bad": 0, "warn": 1, "ok": 2}[c[0]])
        for i, (kind, text, page) in enumerate(checks):
            r, col = divmod(i, 2)
            cell = QWidget()
            cell.setObjectName("Transparent")
            hl = QHBoxLayout(cell)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(10)
            hl.addWidget(icon_badge({"ok": "check"}.get(kind, "alert"), 26, 14, kind))
            lb = label(text, wrap=True)
            if kind != "ok":
                lb.setStyleSheet(f"color: {theme.C[kind]}" if kind == "bad" else "")
            hl.addWidget(lb, 1)
            if page:
                b = QPushButton("Resolver")
                b.setObjectName("Ghost")
                b.clicked.connect(lambda _c, p=page: self.window().go_name(p))
                hl.addWidget(b)
            g.addWidget(cell, r, col)
        for c in range(2):
            g.setColumnStretch(c, 1)

    def open_weekly(self, report=None):
        from ..weekly_dialog import WeeklyDialog
        WeeklyDialog(self, report).exec()

    def _update_score(self, checks):
        actions = {c.text: c.action for c in self._slow}
        cs = [healthscore.Check(k, t, p, actions.get(t, "Resolver")) for k, t, p in checks]
        s = healthscore.score(cs)
        try:
            from ...core import weekly
            weekly.record_score(s)
        except OSError:
            pass
        txt, kind = healthscore.grade(s)
        self.r_score.set(s, str(s), "de 100", kind)
        self.score_title.setText(f"Saúde do PC: {txt}")
        todo = healthscore.top_actions(cs)
        n_bad = sum(1 for c in cs if c.kind == "bad")
        n_warn = sum(1 for c in cs if c.kind == "warn")
        if not todo and not (n_bad or n_warn):
            self.score_sub.setText("Está tudo em ordem — nada para fazer agora.")
        else:
            parts = [f"{n_bad} problema(s)" if n_bad else "", f"{n_warn} aviso(s)" if n_warn else ""]
            self.score_sub.setText(" e ".join(p for p in parts if p) + ". O mais útil a fazer agora:"
                                   if todo else " e ".join(p for p in parts if p) + ".")
        from .. import theme
        from ..widgets import icon_badge
        while self.actions_box.count():
            w = self.actions_box.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        for i, c in enumerate(todo, 1):
            row = QWidget()
            row.setObjectName("Transparent")
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(10)
            hl.addWidget(icon_badge("alert", 24, 13, c.kind))
            lb = label(f"{i}. {c.text}", wrap=True)
            if c.kind == "bad":
                lb.setStyleSheet(f"color: {theme.C['bad']}")
            hl.addWidget(lb, 1)
            b = QPushButton(c.action)
            b.setObjectName("Primary" if i == 1 else "")
            b.setToolTip(f"Abrir {c.page}")
            b.clicked.connect(lambda _c=False, p=c.page: self.window().go_name(p))
            hl.addWidget(b)
            self.actions_box.addWidget(row)

    def _update(self, readings):
        if not self.isVisible():
            return
        from ...core.sensors import pick
        h = self.hub
        a, b, _unit, _ = METRICS[self.metric_cb.currentText()]
        self.chart.push("CPU", h.latest(a))
        self.chart.push("GPU", h.latest(b))
        self.chart.update()

        load = h.latest("cpu_load")
        if load is not None:
            self.t_cpu.s.setText(f"{self._cores} · carga {load:.0f}%")
        gl = h.latest("gpu_load")
        if gl is not None:
            self.t_gpu.s.setText(f"carga {gl:.0f}%")
        vm = psutil.virtual_memory()
        self.t_ram.s.setText(f"{human_bytes(vm.total - vm.available)} em uso ({vm.percent:.0f}%)")
        self.t_os.s.setText(f"ligado há {human_duration(time.time() - self._boot)}")

        self.r_ram.set(vm.percent, f"{vm.percent:.0f}%", human_bytes(vm.total - vm.available))
        vr = h.latest("vram")
        vu = pick(readings, "GPU", "VRAM usada")
        self.r_vram.set(vr or 0, f"{vr:.0f}%" if vr is not None else "—",
                        human_bytes(vu * 1024**2) if vu else "sem dados")
        self._tick += 1
        if self._tick % 5 == 1:  # o espaço em disco muda devagar
            try:
                du = psutil.disk_usage("C:\\" if IS_WIN else "/")
                self.r_disk.set(du.percent, f"{du.percent:.0f}%", f"{human_bytes(du.free)} livres")
                self._du = du
            except OSError:
                self._du = None
            self._update_health(vm)
        ct, gt = h.latest("cpu_temp"), h.latest("gpu_temp")

        def tcol(t):
            return None if t is None else "bad" if t >= 90 else "warn" if t >= 80 else "ok"
        self.t_temp_cpu.set(f"{ct:.0f} °C" if ct is not None else "—",
                            "Pacote da CPU" if ct is not None else "Sensor indisponível", tcol(ct))
        self.t_temp_gpu.set(f"{gt:.0f} °C" if gt is not None else "—",
                            f"consumo {h.latest('gpu_power'):.0f} W" if h.latest("gpu_power") else "", tcol(gt))
        dn, up = pick(readings, "Rede", "Download"), pick(readings, "Rede", "Upload")
        if dn is not None:
            self.t_net.set(f"↓ {dn * 8:.1f} Mb/s", f"↑ {(up or 0) * 8:.1f} Mb/s")
        rd, wr = pick(readings, "Disco", "Leitura"), pick(readings, "Disco", "Escrita")
        if rd is not None:
            self.t_disk_io.set(f"{rd:.1f} MB/s", f"leitura · escrita {(wr or 0):.1f} MB/s")
