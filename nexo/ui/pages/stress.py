from __future__ import annotations

import os
import time

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QSpinBox

from ...core.stress import StressTest
from ...core.util import human_bytes, human_duration
from ..widgets import Card, LineChart, Page, StatTile, confirm, label, notify

DURATIONS = {"1 minuto": 60, "5 minutos": 300, "15 minutos": 900, "30 minutos": 1800, "1 hora": 3600, "Sem limite": 0}


class StressPage(Page):
    def __init__(self, hub):
        super().__init__("Stress test", "Carga máxima na CPU (todos os threads) e/ou teste de RAM com verificação de erros. "
                                        "Pára sozinho ao atingir o limite de temperatura.")
        self.hub = hub
        self.test = StressTest()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.max_temp = None
        self.errors = 0
        self.last_ops = 0
        self.last_t = 0.0

        opts = Card("Configuração")
        g = QGridLayout()
        g.setHorizontalSpacing(16)
        g.setVerticalSpacing(10)
        self.cb_cpu = QCheckBox("CPU")
        self.cb_cpu.setChecked(True)
        self.sp_threads = QSpinBox()
        self.sp_threads.setRange(1, os.cpu_count() or 1)
        self.sp_threads.setValue(os.cpu_count() or 1)
        self.sp_threads.setSuffix(" threads")
        self.cb_ram = QCheckBox("RAM")
        self.sp_ram = QSpinBox()
        self.sp_ram.setRange(10, 85)
        self.sp_ram.setValue(60)
        self.sp_ram.setSuffix(" % da RAM livre")
        self.cb_duration = QComboBox()
        self.cb_duration.addItems(DURATIONS)
        self.cb_duration.setCurrentIndex(2)
        self.sp_limit = QSpinBox()
        self.sp_limit.setRange(60, 105)
        self.sp_limit.setValue(90)
        self.sp_limit.setSuffix(" °C")
        g.addWidget(self.cb_cpu, 0, 0)
        g.addWidget(self.sp_threads, 0, 1)
        g.addWidget(self.cb_ram, 1, 0)
        g.addWidget(self.sp_ram, 1, 1)
        g.addWidget(label("Duração"), 0, 2)
        g.addWidget(self.cb_duration, 0, 3)
        g.addWidget(label("Parar se a CPU passar de"), 1, 2)
        g.addWidget(self.sp_limit, 1, 3)
        g.setColumnStretch(4, 1)
        self.btn = QPushButton("Iniciar teste")
        self.btn.setObjectName("Primary")
        self.btn.setMinimumWidth(160)
        self.btn.clicked.connect(self.toggle)
        g.addWidget(self.btn, 0, 5, 2, 1)
        opts.add(g)
        self.ram_note = label(f"RAM livre agora: {human_bytes(psutil.virtual_memory().available)}", "Muted")
        opts.add(self.ram_note)
        self.add(opts)

        tiles = QHBoxLayout()
        tiles.setSpacing(16)
        self.t_time = StatTile("Tempo", "0s", "parado")
        self.t_temp = StatTile("Temp. CPU", "—", "máx. —")
        self.t_load = StatTile("Carga CPU", "—", "")
        self.t_power = StatTile("Consumo", "—", "")
        self.t_ram = StatTile("RAM", "—", "")
        for t in (self.t_time, self.t_temp, self.t_load, self.t_power, self.t_ram):
            tiles.addWidget(t)
        self.add(tiles)

        row = QHBoxLayout()
        row.setSpacing(16)
        c1 = Card("Temperatura e carga (últimos 5 min)")
        self.chart = LineChart(capacity=300, y_max=100, unit="°C / %", height=220)
        c1.add(self.chart, 1)
        c2 = Card("Registo")
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        c2.add(self.log, 1)
        row.addWidget(c1, 3)
        row.addWidget(c2, 2)
        self.add(row, 1)
        hub.updated.connect(self._sensors)

    def _log(self, msg):
        self.log.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {msg}")

    def toggle(self):
        if self.test.running:
            self.stop("Parado pelo utilizador")
            return
        cpu = self.sp_threads.value() if self.cb_cpu.isChecked() else 0
        ram = self.sp_ram.value() if self.cb_ram.isChecked() else 0
        if not cpu and not ram:
            notify("Escolha CPU e/ou RAM.", "warn")
            return
        if self.hub.latest("cpu_temp") is None and cpu and not confirm(
                self, "Sem sensor de temperatura",
                "Não foi possível ler a temperatura da CPU, por isso o limite de segurança não vai funcionar.\n"
                "Continuar mesmo assim?"):
            return
        self.max_temp = None
        self.errors = 0
        self.last_ops, self.last_t = 0, time.monotonic()
        self.test.start(cpu, ram)
        self.btn.setText("Parar")
        self.btn.setObjectName("Danger")
        self.btn.setStyle(self.btn.style())
        parts = []
        if cpu:
            parts.append(f"CPU em {cpu} threads")
        if ram:
            parts.append(f"RAM {ram}% da livre")
        self._log("Início: " + ", ".join(parts) + f" · limite {self.sp_limit.value()} °C")
        self.timer.start(1000)

    def stop(self, reason: str):
        self.timer.stop()
        self.test.stop()
        self.btn.setText("Iniciar teste")
        self.btn.setObjectName("Primary")
        self.btn.setStyle(self.btn.style())
        elapsed = time.monotonic() - self.test.started
        self._log(f"{reason}. Duração {human_duration(elapsed)}, temperatura máx. "
                  f"{self.max_temp:.0f} °C" if self.max_temp else f"{reason}. Duração {human_duration(elapsed)}")
        if self.cb_ram.isChecked():
            self._log("RAM: " + ("sem erros ✔" if not self.errors else f"{self.errors} ERROS ✘ — memória instável!"))
        self.t_time.set(human_duration(elapsed), reason)
        notify(reason, "warn" if "limite" in reason or self.errors else "ok")

    def _tick(self):
        el = time.monotonic() - self.test.started
        dur = DURATIONS[self.cb_duration.currentText()]
        self.t_time.set(human_duration(el), f"de {human_duration(dur)}" if dur else "sem limite")
        for kind, val in self.test.poll_messages():
            if kind == "error":
                self.errors += 1
                self._log("✘ " + str(val))
            elif kind == "pass":
                self._log(f"RAM: passagem {val} completa sem erros" if not self.errors else f"RAM: passagem {val}")
            else:
                self._log(str(val))
        ops = self.test.ops()
        now = time.monotonic()
        rate = (ops - self.last_ops) / max(now - self.last_t, 1e-3)
        self.last_ops, self.last_t = ops, now
        if self.cb_cpu.isChecked():
            self.t_load.s.setText(f"{rate * 20:.0f}k ops/s")
        t = self.hub.latest("cpu_temp")
        if t is not None and t >= self.sp_limit.value():
            self.stop(f"Parado: CPU atingiu o limite de {self.sp_limit.value()} °C ({t:.0f} °C)")
            return
        if dur and el >= dur:
            self.stop("Teste concluído")
            return
        if not self.test.running:
            self.stop("Os processos de teste terminaram inesperadamente")

    def _sensors(self, _readings):
        h = self.hub
        t = h.latest("cpu_temp")
        load = h.latest("cpu_load")
        if self.test.running and t is not None:
            self.max_temp = max(self.max_temp or t, t)
        if self.isVisible() or self.test.running:
            self.chart.push("Temp. CPU", t)
            self.chart.push("Carga CPU", load)
            self.chart.update()
        if not self.isVisible():
            return
        col = None if t is None else "bad" if t >= self.sp_limit.value() - 5 else "warn" if t >= 80 else "ok"
        self.t_temp.set(f"{t:.0f} °C" if t is not None else "—",
                        f"máx. {self.max_temp:.0f} °C" if self.max_temp else "máx. —", col)
        self.t_load.v.setText(f"{load:.0f}%" if load is not None else "—")
        p = h.latest("cpu_power")
        self.t_power.set(f"{p:.0f} W" if p else "—", "pacote da CPU" if p else "sensor indisponível")
        vm = psutil.virtual_memory()
        self.t_ram.set(f"{vm.percent:.0f}%", f"{human_bytes(vm.total - vm.available)} de {human_bytes(vm.total)}")
        if not self.test.running:
            self.ram_note.setText(f"RAM livre agora: {human_bytes(vm.available)}")

    def shutdown(self):
        self.test.stop()
