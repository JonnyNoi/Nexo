from __future__ import annotations

import os
import time

import psutil
from PySide6.QtCore import QProcess, QTimer
from PySide6.QtWidgets import QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QPlainTextEdit, QPushButton, QSpinBox

from ...core.stress import StressTest
from ...core.util import human_bytes, human_duration
from ..widgets import Card, LineChart, Page, StatTile, confirm, label, notify

DURATIONS = {"1 minuto": 60, "5 minutos": 300, "15 minutos": 900, "30 minutos": 1800, "1 hora": 3600, "Sem limite": 0}


class StressPage(Page):
    def __init__(self, hub):
        super().__init__("Stress test", "Carga máxima na CPU (todos os threads), teste de RAM e/ou placa gráfica com "
                                        "teste da VRAM, com verificação de erros. Pára sozinho ao atingir o limite de "
                                        "temperatura.")
        self.hub = hub
        self.test = StressTest()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.max_temp = None
        self.errors = 0
        self.last_ops = 0
        self.last_t = 0.0
        self.gpu_proc: QProcess | None = None
        self._gpu_buf = b""
        self.gpu_errors = 0
        self.gpu_max_temp = None
        self.gpu_passes = 0
        self.started = 0.0

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
        self.cb_gpu = QCheckBox("Placa gráfica + VRAM")
        self.sp_vram = QSpinBox()
        self.sp_vram.setRange(0, 85)
        self.sp_vram.setValue(60)
        self.sp_vram.setSuffix(" % da VRAM")
        self.sp_vram.setToolTip("Quanta memória de vídeo encher e verificar (0 = só carga na placa)")
        self.sp_gpu_limit = QSpinBox()
        self.sp_gpu_limit.setRange(60, 105)
        self.sp_gpu_limit.setValue(90)
        self.sp_gpu_limit.setSuffix(" °C")
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
        g.addWidget(self.cb_gpu, 2, 0)
        g.addWidget(self.sp_vram, 2, 1)
        g.addWidget(label("Parar se a GPU passar de"), 2, 2)
        g.addWidget(self.sp_gpu_limit, 2, 3)
        g.setColumnStretch(4, 1)
        self.btn = QPushButton("Iniciar teste")
        self.btn.setObjectName("Primary")
        self.btn.setMinimumWidth(160)
        self.btn.clicked.connect(self.toggle)
        g.addWidget(self.btn, 0, 5, 3, 1)
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
        self.t_gpu = StatTile("Temp. GPU", "—", "máx. —")
        for t in (self.t_time, self.t_temp, self.t_load, self.t_power, self.t_ram, self.t_gpu):
            tiles.addWidget(t)
        self.add(tiles)

        row = QHBoxLayout()
        row.setSpacing(16)
        c1 = Card("Temperaturas e carga (últimos 5 min)")
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

    @property
    def running(self) -> bool:
        return self.test.running or self.gpu_proc is not None

    def toggle(self):
        if self.running:
            self.stop("Parado pelo utilizador")
            return
        cpu = self.sp_threads.value() if self.cb_cpu.isChecked() else 0
        ram = self.sp_ram.value() if self.cb_ram.isChecked() else 0
        gpu = self.cb_gpu.isChecked()
        if not cpu and not ram and not gpu:
            notify("Escolha CPU, RAM e/ou placa gráfica.", "warn")
            return
        if gpu and self.hub.latest("gpu_temp") is None and not confirm(
                self, "Sem sensor de temperatura",
                "Não foi possível ler a temperatura da placa gráfica, por isso o limite de segurança da GPU não vai "
                "funcionar.\nContinuar mesmo assim?"):
            return
        if self.hub.latest("cpu_temp") is None and cpu and not confirm(
                self, "Sem sensor de temperatura",
                "Não foi possível ler a temperatura da CPU, por isso o limite de segurança não vai funcionar.\n"
                "Continuar mesmo assim?"):
            return
        self.max_temp = self.gpu_max_temp = None
        self.errors = self.gpu_errors = self.gpu_passes = 0
        self.last_ops, self.last_t = 0, time.monotonic()
        self.started = time.monotonic()
        if cpu or ram:
            self.test.start(cpu, ram)
        if gpu:
            self._gpu_start()
        self.btn.setText("Parar")
        self.btn.setObjectName("Danger")
        self.btn.setStyle(self.btn.style())
        parts = []
        if cpu:
            parts.append(f"CPU em {cpu} threads")
        if ram:
            parts.append(f"RAM {ram}% da livre")
        if gpu:
            parts.append(f"placa gráfica (limite {self.sp_gpu_limit.value()} °C)")
        self._log("Início: " + ", ".join(parts) + f" · limite da CPU {self.sp_limit.value()} °C")
        self.timer.start(1000)

    # ------------------------------------------------------------------ placa gráfica (processo à parte)
    def _gpu_start(self):
        from ...core import gpustress
        dur = DURATIONS[self.cb_duration.currentText()]
        pct = self.sp_vram.value()
        mb = gpustress.default_vram_mb(gpustress.vram_total_mb(), pct) if pct else 0
        cmd = gpustress.child_command(dur + 30 if dur else 0, mb)   # o Nexo pára-o; a margem é só por segurança
        self._gpu_buf = b""
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.readyReadStandardOutput.connect(self._gpu_read)
        p.finished.connect(self._gpu_finished)
        self.gpu_proc = p
        if mb:
            self._log(f"Placa gráfica: a reservar {mb} MB de VRAM para o teste…")
        p.start(cmd[0], cmd[1:])

    def _gpu_read(self):
        import json
        if self.gpu_proc is None:
            return
        self._gpu_buf += bytes(self.gpu_proc.readAllStandardOutput())
        *lines, self._gpu_buf = self._gpu_buf.split(b"\n")
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            kind = ev.get("ev")
            if kind == "info":
                vram = f", {ev['vram_mb']} MB de VRAM em teste" if ev.get("vram_mb") else ""
                self._log(f"Placa gráfica: {ev['renderer']} — cena 3D em {ev['w']}×{ev['h']}{vram}")
            elif kind == "selftest":
                self._log("VRAM: verificador confirmado (deteta erros de propósito)")
            elif kind == "warn":
                self._log("⚠ " + ev.get("msg", ""))
            elif kind == "vram_error":
                self.gpu_errors += int(ev.get("count") or 0)
                self._log(f"✘ Erro de VRAM: {ev['count']} píxeis errados no bloco {ev['block']} (≈ {ev['mb']} MB)")
            elif kind == "progress":
                if ev.get("passes", 0) > self.gpu_passes:
                    self.gpu_passes = ev["passes"]
                self.t_gpu.s.setText(f"{ev['fps']:.0f} FPS · {self.gpu_passes} passagens")
            elif kind == "error":
                self._log("✘ Placa gráfica: " + ev.get("msg", ""))

    def _gpu_finished(self, *_a):
        self._gpu_read()
        self.gpu_proc = None
        if self.timer.isActive() and not self.test.running:
            self.stop("O teste da placa gráfica terminou")

    def stop(self, reason: str):
        self.timer.stop()
        self.test.stop()
        gpu = self.gpu_proc is not None or self.gpu_passes or self.gpu_errors
        if self.gpu_proc is not None:
            p, self.gpu_proc = self.gpu_proc, None
            p.finished.disconnect(self._gpu_finished)
            p.kill()
            p.waitForFinished(2000)
        self.btn.setText("Iniciar teste")
        self.btn.setObjectName("Primary")
        self.btn.setStyle(self.btn.style())
        elapsed = time.monotonic() - self.started
        self._log(f"{reason}. Duração {human_duration(elapsed)}, temperatura máx. "
                  f"{self.max_temp:.0f} °C" if self.max_temp else f"{reason}. Duração {human_duration(elapsed)}")
        if self.cb_ram.isChecked():
            self._log("RAM: " + ("sem erros ✔" if not self.errors else f"{self.errors} ERROS ✘ — memória instável!"))
        if gpu:
            if self.gpu_max_temp:
                self._log(f"Placa gráfica: temperatura máx. {self.gpu_max_temp:.0f} °C")
            if self.sp_vram.value():
                self._log("VRAM: " + (f"sem erros em {self.gpu_passes} passagens ✔" if not self.gpu_errors else
                                      f"{self.gpu_errors} píxeis errados ✘ — memória de vídeo instável (overclock, "
                                      "temperatura ou placa com defeito)!"))
        self.t_time.set(human_duration(elapsed), reason)
        notify(reason, "warn" if "limite" in reason or self.errors or self.gpu_errors else "ok")

    def _tick(self):
        el = time.monotonic() - self.started
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
        gt = self.hub.latest("gpu_temp")
        if self.gpu_proc is not None and gt is not None and gt >= self.sp_gpu_limit.value():
            self.stop(f"Parado: GPU atingiu o limite de {self.sp_gpu_limit.value()} °C ({gt:.0f} °C)")
            return
        if dur and el >= dur:
            self.stop("Teste concluído")
            return
        if (self.cb_cpu.isChecked() or self.cb_ram.isChecked()) and not self.test.running and self.gpu_proc is None:
            self.stop("Os processos de teste terminaram inesperadamente")

    def _sensors(self, _readings):
        h = self.hub
        t = h.latest("cpu_temp")
        load = h.latest("cpu_load")
        gt = h.latest("gpu_temp")
        if self.test.running and t is not None:
            self.max_temp = max(self.max_temp or t, t)
        if self.gpu_proc is not None and gt is not None:
            self.gpu_max_temp = max(self.gpu_max_temp or gt, gt)
        if self.isVisible() or self.running:
            self.chart.push("Temp. CPU", t)
            self.chart.push("Carga CPU", load)
            if gt is not None:
                self.chart.push("Temp. GPU", gt)
            self.chart.update()
        if not self.isVisible():
            return
        col = None if t is None else "bad" if t >= self.sp_limit.value() - 5 else "warn" if t >= 80 else "ok"
        self.t_temp.set(f"{t:.0f} °C" if t is not None else "—",
                        f"máx. {self.max_temp:.0f} °C" if self.max_temp else "máx. —", col)
        self.t_load.v.setText(f"{load:.0f}%" if load is not None else "—")
        p = h.latest("cpu_power")
        self.t_power.set(f"{p:.0f} W" if p else "—", "pacote da CPU" if p else "sensor indisponível")
        gcol = None if gt is None else "bad" if gt >= self.sp_gpu_limit.value() - 5 else "warn" if gt >= 80 else "ok"
        self.t_gpu.set(f"{gt:.0f} °C" if gt is not None else "—",
                       None if self.gpu_proc is not None else
                       f"máx. {self.gpu_max_temp:.0f} °C" if self.gpu_max_temp else "máx. —", gcol)
        vm = psutil.virtual_memory()
        self.t_ram.set(f"{vm.percent:.0f}%", f"{human_bytes(vm.total - vm.available)} de {human_bytes(vm.total)}")
        if not self.test.running:
            self.ram_note.setText(f"RAM livre agora: {human_bytes(vm.available)}")

    def shutdown(self):
        self.test.stop()
        if self.gpu_proc is not None:
            self.gpu_proc.kill()
