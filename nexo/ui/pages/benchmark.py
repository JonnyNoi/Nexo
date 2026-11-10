from __future__ import annotations

import multiprocessing as mp
import os
import time

from PySide6.QtCore import QProcess, Qt
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QLabel, QProgressBar, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem)

from ...core import bench
from ...core.sysinfo import cpu_model
from ...core.util import load_json, save_json
from ..widgets import Card, Page, StatTile, Task, label, notify


class BenchView(QLabel):
    def __init__(self):
        super().__init__()
        self.img = QImage(bench.WIDTH, bench.HEIGHT, QImage.Format_Grayscale8)
        self.img.fill(18)
        self.setMinimumSize(480, 270)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)

    def reset(self):
        self.img.fill(18)
        self.update()

    def put_tile(self, x, y, w, h, px: bytes):
        tile = QImage(px, w, h, w, QImage.Format_Grayscale8)
        p = QPainter(self.img)
        p.drawImage(x, y, tile)
        p.end()
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.rect()
        scale = min(r.width() / bench.WIDTH, r.height() / bench.HEIGHT)
        w, h = int(bench.WIDTH * scale), int(bench.HEIGHT * scale)
        p.drawPixmap((r.width() - w) // 2, (r.height() - h) // 2, w, h, QPixmap.fromImage(self.img))
        p.end()


class BenchmarkPage(Page):
    def __init__(self):
        super().__init__("Benchmark", "CPU: path tracer próprio (iluminação global, reflexos, vidro com refração). "
                                      "Placa gráfica: cena 3D em OpenGL. Imagens sempre iguais — as notas comparam-se "
                                      "entre PCs.")
        self.running = False
        self.pool = None

        ctl = Card()
        row = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItems(["Multi-core", "Single-core"])
        self.quality = QComboBox()
        self.quality.addItems(bench.QUALITY)
        self.quality.setCurrentText("Normal")
        self.btn = QPushButton("Iniciar benchmark")
        self.btn.setObjectName("Primary")
        self.btn.clicked.connect(self.toggle)
        row.addWidget(label("Modo"))
        row.addWidget(self.mode)
        row.addSpacing(12)
        row.addWidget(label("Qualidade"))
        row.addWidget(self.quality)
        row.addStretch(1)
        row.addWidget(self.btn)
        ctl.add(row)
        self.progress = QProgressBar()
        self.progress.setMaximum(1000)
        ctl.add(self.progress)
        self.add(ctl)

        body = QHBoxLayout()
        body.setSpacing(16)
        view_card = Card()
        self.view = BenchView()
        view_card.add(self.view, 1)
        body.addWidget(view_card, 3)
        side = QHBoxLayout()
        col = Card("Resultado")
        self.t_score = StatTile("Nota", "—", "amostras/s ÷ 1000")
        self.t_time = StatTile("Tempo", "—", "")
        col.add(self.t_score)
        col.add(self.t_time)
        self.ref = label("Referência: i5-12400F (6C/12T) ≈ 1290 multi / 196 single.\n"
                         "Mais threads = nota multi-core maior; clock e IPC = nota single-core maior.", "Muted", wrap=True)
        col.add(self.ref)
        col.lay.addStretch(1)
        side.addWidget(col)
        body.addLayout(side, 1)
        self.add(body, 1)

        self._build_gpu()

        hist = Card("Histórico")
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Data", "Modo", "Qualidade", "Nota", "Processador / placa"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(180)
        hist.add(self.table)
        self.add(hist)
        self._load_history()

    def _load_history(self):
        hist = load_json("bench_history.json", [])
        self.table.setRowCount(len(hist))
        for i, h in enumerate(reversed(hist)):
            for j, v in enumerate((h["date"], h["mode"], h.get("quality", ""), f"{h['score']:.0f}", h.get("cpu", ""))):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def toggle(self):
        if self.running:
            self.running = False
            if self.pool:
                self.pool.terminate()
            self.btn.setText("Iniciar benchmark")
            notify("Benchmark cancelado", "warn")
            return
        single = self.mode.currentText() == "Single-core"
        spp = bench.QUALITY[self.quality.currentText()]
        tiles = bench.tiles(spp, subset=3 if single else 1)
        procs = 1 if single else (os.cpu_count() or 1)
        self.view.reset()
        self.progress.setValue(0)
        self.t_score.set("…", "a renderizar")
        self.running = True
        self.btn.setText("Cancelar")
        self.mode.setEnabled(False)
        self.quality.setEnabled(False)
        total = sum(1 for _ in tiles)
        meta = {"mode": self.mode.currentText(), "quality": self.quality.currentText()}

        def work():
            ctx = mp.get_context("spawn")
            self.pool = ctx.Pool(procs)
            # arranque dos processos fora da medição
            self.pool.map(int, range(procs))
            t0 = time.perf_counter()
            samples = 0
            done = 0
            try:
                for res in self.pool.imap_unordered(bench.render_tile, tiles):
                    if not self.running:
                        return None
                    samples += res[5]
                    done += 1
                    task.progress.emit((res, done / total, samples, time.perf_counter() - t0))
            except Exception:
                if not self.running:
                    return None
                raise
            finally:
                self.pool.terminate()
                self.pool = None
            return samples, time.perf_counter() - t0

        task = Task(work)
        task.progress.connect(self._progress)
        task.done.connect(lambda r: self._done(r, meta))
        task.failed.connect(self._fail)
        task.start()

    def _progress(self, data):
        (x, y, w, h, px, _s), frac, samples, el = data
        self.view.put_tile(x, y, w, h, px)
        self.progress.setValue(int(frac * 1000))
        if el > 0.5:
            self.t_score.set(f"{samples / el / 1000:.0f}", "parcial")
        self.t_time.set(f"{el:.1f} s", "")

    def _reset_ui(self):
        self.running = False
        self.btn.setText("Iniciar benchmark")
        self.mode.setEnabled(True)
        self.quality.setEnabled(True)

    def _fail(self, msg):
        self._reset_ui()
        notify(f"Erro no benchmark: {msg}", "bad")

    def _done(self, result, meta):
        was_running = self.running
        self._reset_ui()
        if not result or not was_running:
            return
        samples, el = result
        score = samples / el / 1000
        self.progress.setValue(1000)
        self.t_score.set(f"{score:.0f}", f"pontos · {meta['mode']}", "ok")
        self.t_time.set(f"{el:.1f} s", f"{samples / 1e6:.1f} M amostras")
        hist = load_json("bench_history.json", [])
        hist.append({"date": time.strftime("%Y-%m-%d %H:%M"), "score": score, "cpu": cpu_model(), **meta})
        save_json("bench_history.json", hist[-30:])
        self._load_history()
        notify(f"Benchmark {meta['mode']}: {score:.0f} pontos", "ok")

    # ------------------------------------------------------------------ placa gráfica
    def _build_gpu(self):
        from ...core import gpubench
        c = Card("Placa gráfica", "Cena 3D com ray marching (sombras suaves, oclusão ambiente, reflexos) desenhada "
                 "pela GPU durante 15 s. Nota = FPS × 10.", icon="gauge")
        self.gpu_res = QComboBox()
        for k in gpubench.RESOLUTIONS:
            self.gpu_res.addItem(k, k)
        self.gpu_btn = QPushButton("Testar placa gráfica")
        self.gpu_btn.setObjectName("Primary")
        self.gpu_btn.clicked.connect(self._gpu_toggle)
        row = QHBoxLayout()
        row.addWidget(label("Resolução"))
        row.addWidget(self.gpu_res)
        row.addStretch(1)
        row.addWidget(self.gpu_btn)
        c.add(row)
        self.gpu_prog = QProgressBar()
        self.gpu_prog.setMaximum(1000)
        c.add(self.gpu_prog)
        body = QHBoxLayout()
        body.setSpacing(16)
        self.gpu_view = QLabel()
        self.gpu_view.setMinimumSize(384, 216)
        self.gpu_view.setAlignment(Qt.AlignCenter)
        self.gpu_view.setObjectName("Transparent")
        body.addWidget(self.gpu_view, 3)
        col = QHBoxLayout()
        self.g_score = StatTile("Nota", "—", "FPS × 10")
        self.g_fps = StatTile("FPS", "—", "média · 1 % low")
        col.addWidget(self.g_score)
        col.addWidget(self.g_fps)
        body.addLayout(col, 2)
        c.add(body)
        self.gpu_info = label("Referência: RX 6500 XT ≈ 1500 em 1080p.", "Muted", wrap=True)
        c.add(self.gpu_info)
        self.add(c)
        self.gpu_proc: QProcess | None = None
        self._gpu_buf = b""
        self._gpu_result = None

    def _gpu_toggle(self):
        import tempfile
        from ...core import gpubench
        if self.gpu_proc is not None:
            self.gpu_proc.kill()
            return
        self._gpu_img = os.path.join(tempfile.gettempdir(), f"nexo-gpubench-{os.getpid()}.png")
        cmd = gpubench.child_command(self.gpu_res.currentData(), self._gpu_img)
        self._gpu_buf, self._gpu_result, self._gpu_err = b"", None, ""
        p = QProcess(self)
        p.setProcessChannelMode(QProcess.SeparateChannels)
        p.readyReadStandardOutput.connect(self._gpu_read)
        p.finished.connect(self._gpu_finished)
        self.gpu_proc = p
        self.gpu_prog.setValue(0)
        self.g_score.set("…", "a aquecer a placa")
        self.g_fps.set("—", "média · 1 % low")
        self.gpu_btn.setText("Cancelar")
        self.gpu_res.setEnabled(False)
        p.start(cmd[0], cmd[1:])

    def _gpu_read(self):
        import json
        self._gpu_buf += bytes(self.gpu_proc.readAllStandardOutput())
        *lines, self._gpu_buf = self._gpu_buf.split(b"\n")
        for ln in lines:
            try:
                ev = json.loads(ln)
            except ValueError:
                continue
            kind = ev.get("ev")
            if kind == "info":
                self.gpu_info.setText(f"{ev['renderer']} · OpenGL {ev['version']} · {ev['w']}×{ev['h']}")
            elif kind == "warn":
                notify(ev["msg"], "warn")
                self.gpu_info.setText(self.gpu_info.text() + " — " + ev["msg"])
            elif kind == "progress":
                self.gpu_prog.setValue(int(ev["frac"] * 1000))
                self.g_score.set(f"{ev['fps'] * 10:.0f}", "parcial")
                self.g_fps.set(f"{ev['fps']:.0f}", "a medir…")
            elif kind == "done":
                self._gpu_result = ev
            elif kind == "error":
                self._gpu_err = ev.get("msg", "")

    def _gpu_finished(self, *_a):
        from PySide6.QtGui import QPixmap
        self._gpu_read()
        self.gpu_proc = None
        self.gpu_btn.setText("Testar placa gráfica")
        self.gpu_res.setEnabled(True)
        r = self._gpu_result
        if not r:
            self.g_score.set("—", "FPS × 10")
            self.g_fps.set("—", "média · 1 % low")
            if self._gpu_err:
                notify(f"Benchmark da placa gráfica falhou: {self._gpu_err}", "bad")
                self.gpu_info.setText(self._gpu_err)
            else:
                notify("Benchmark da placa gráfica cancelado", "warn")
            return
        self.gpu_prog.setValue(1000)
        self.g_score.set(str(r["score"]), f"pontos · {self.gpu_res.currentText()}", "ok")
        self.g_fps.set(f"{r['fps']:.0f}", f"média · 1 % low {r['low1']:.0f}")
        if r.get("image") and os.path.exists(r["image"]):
            pm = QPixmap(r["image"])
            self.gpu_view.setPixmap(pm.scaled(self.gpu_view.width(), self.gpu_view.height(), Qt.KeepAspectRatio,
                                              Qt.SmoothTransformation))
            try:
                os.remove(r["image"])
            except OSError:
                pass
        hist = load_json("bench_history.json", [])
        hist.append({"date": time.strftime("%Y-%m-%d %H:%M"), "score": r["score"], "cpu": r["renderer"],
                     "mode": "Placa gráfica", "quality": self.gpu_res.currentText()})
        save_json("bench_history.json", hist[-30:])
        self._load_history()
        notify(f"Placa gráfica: {r['score']} pontos ({r['fps']:.0f} FPS)", "ok")

    def shutdown(self):
        if self.gpu_proc is not None:
            self.gpu_proc.kill()
        self.running = False
        if self.pool:
            self.pool.terminate()
