"""Página «O que melhorar»: o gargalo do PC nos jogos e o que atualizar primeiro (grátis primeiro)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget

from ...core import upgrade as up
from .. import theme
from ..widgets import Bar, Card, Page, StatTile, hbox, icon_badge, label, run_async

_KIND = {"free": ("Grátis", "ok", "check"), "upgrade": ("Comprar", "warn", "upgrade"), "ok": ("Tudo bem", "ok", "check")}
_PART_ICON = {"CPU": "cpu", "Placa gráfica": "gauge", "Memória": "list", "Disco": "hdd", "Monitor": "image",
              "Refrigeração": "thermo", "Equilíbrio": "check"}


class UpgradePage(Page):
    def __init__(self):
        super().__init__("O que melhorar", "Que peça limita o seu PC e o que vale a pena trocar primeiro — a partir "
                         "das sessões de jogo, dos benchmarks e do hardware. As correções grátis aparecem primeiro.")
        self.btn = QPushButton("Analisar de novo")
        self.btn.clicked.connect(self.load)
        self.head.addWidget(self.btn)
        row = hbox()
        self.t_cpu = StatTile("Processador", "—", "")
        self.t_gpu = StatTile("Placa gráfica", "—", "")
        self.t_ram = StatTile("Memória", "—", "")
        self.t_disk = StatTile("Disco do sistema", "—", "")
        for t in (self.t_cpu, self.t_gpu, self.t_ram, self.t_disk):
            row.addWidget(t, 1)
        self.add(row)

        bn = Card("O que limita nos jogos", icon="gamepad")
        self.bn_text = label("A analisar…", wrap=True)
        bn.add(self.bn_text)
        self.bar_gpu = Bar(10)
        self.bar_cpu = Bar(10)
        self.lb_gpu = label("", "Muted")
        self.lb_cpu = label("", "Muted")
        bn.add(self.lb_gpu)
        bn.add(self.bar_gpu)
        bn.add(self.lb_cpu)
        bn.add(self.bar_cpu)
        self.bn_card = bn
        self.add(bn)

        holder = QWidget()
        holder.setObjectName("Transparent")
        self.box = QVBoxLayout(holder)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(12)
        self.add(holder)

        gm = Card("Jogos analisados", "Últimos 90 dias. Carga média durante o jogo — uma placa gráfica perto dos "
                  "100 % está no limite; folgada com FPS baixo aponta para o processador.", icon="chart")
        self.games = QTableWidget(0, 7)
        self.games.setHorizontalHeaderLabels(["Jogo", "Tempo", "CPU", "Placa gráfica", "FPS médio", "1 % low",
                                              "Limitado por"])
        hh = self.games.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, 7):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.games.verticalHeader().setVisible(False)
        self.games.setEditTriggers(QTableWidget.NoEditTriggers)
        self.games.setSelectionMode(QTableWidget.NoSelection)
        self.games.setFocusPolicy(Qt.NoFocus)
        self.games.setAlternatingRowColors(True)
        self.games.setMinimumHeight(200)
        gm.add(self.games)
        self.add(gm)
        self.body.addStretch(1)
        self._busy = False
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            self.load()

    def load(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)

        def work():
            f = up.gather()
            return f, *up.advise(f)

        def done(res):
            self._busy = False
            self._loaded = True
            self.btn.setEnabled(True)
            self._show(*res)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            self.bn_text.setText(f"Não foi possível analisar: {m}")
        run_async(work, on_done=done, on_fail=fail)

    def _show(self, f: up.Facts, b: up.Bottleneck, advice: list[up.Advice]):
        import re
        cpu = re.sub(r"\((R|TM)\)|\d+th Gen |\s+CPU.*$| \d+-Core Processor", "", f.cpu).strip()
        bench = []
        if f.cpu_multi is not None:
            bench.append(f"{f.cpu_multi:.0f} multi")
        if f.cpu_single is not None:
            bench.append(f"{f.cpu_single:.0f} single")
        self.t_cpu.set(f"{f.cores}C / {f.threads}T" if f.threads else "—",
                       " · ".join(x for x in (cpu, " / ".join(bench)) if x))
        gpu = re.sub(r"\s*\(.*?\)", "", f.gpu).replace("Advanced Micro Devices, Inc. ", "").strip()
        gsub = [gpu] + ([f"{f.gpu_score:.0f} pontos (1080p)"] if f.gpu_score is not None else [])
        self.t_gpu.set(f"{f.vram_gb:.0f} GB VRAM" if f.vram_gb else "—", " · ".join(x for x in gsub if x))
        rsub = " · ".join(x for x in (f.ram_kind, f"{f.ram_current} MT/s" if f.ram_current else "") if x)
        self.t_ram.set(f"{f.ram_gb:.0f} GB", rsub,"warn" if f.ram_xmp_off else None)
        self.t_disk.set(f.sys_disk or "—", "", "warn" if f.sys_disk == "HDD" else None)

        self.bn_text.setText(b.text)
        show_bars = b.who != "unknown"
        for w in (self.bar_gpu, self.bar_cpu, self.lb_gpu, self.lb_cpu):
            w.setVisible(show_bars)
        if show_bars:
            self.lb_gpu.setText(f"Limitado pela placa gráfica: {b.gpu_share * 100:.0f} % do tempo de jogo "
                                f"({b.minutes / 60:.1f} h analisadas)")
            self.lb_cpu.setText(f"Limitado pelo processador (ou pelo jogo): {b.cpu_share * 100:.0f} %")
            self.bar_gpu.set(b.gpu_share * 100, "warn" if b.who == "gpu" else "accent")
            self.bar_cpu.set(b.cpu_share * 100, "warn" if b.who == "cpu" else "accent")

        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        n = 0
        for a in advice:
            kind_txt, kind, _ic = _KIND.get(a.kind, _KIND["ok"])
            if a.kind == "upgrade":
                n += 1
                kind_txt = f"{n}.º a comprar"
            c = Card()
            head = hbox()
            head.addWidget(icon_badge(_PART_ICON.get(a.part, "info"), 38, 20, kind), 0, Qt.AlignTop)
            col = QVBoxLayout()
            col.setSpacing(4)
            t = label(a.title, "CardTitle")
            col.addWidget(t)
            col.addWidget(label(a.why, "Muted", wrap=True))
            head.addLayout(col, 1)
            tag = label(f"{a.part} · {kind_txt}", "Badge")
            tag.setStyleSheet(f"color: {theme.C.get(kind, theme.C['muted'])}")
            head.addWidget(tag, 0, Qt.AlignTop)
            if a.page:
                b_go = QPushButton("Ver")
                b_go.clicked.connect(lambda _c=False, p=a.page: self._go(p))
                head.addWidget(b_go, 0, Qt.AlignTop)
            c.add(head)
            self.box.addWidget(c)

        self.games.setRowCount(len(f.games))
        fmt = lambda v, u="": "—" if v is None else f"{v:.0f}{u}"  # noqa: E731
        target = up.fps_target(f)
        for r, g in enumerate(f.games):
            h, m = divmod(int(round(g.minutes)), 60)
            lim = "—"
            if g.gpu_load is not None:
                if g.gpu_load >= up.GPU_BOUND:
                    lim = "Placa gráfica"
                elif g.gpu_load < up.GPU_IDLE and (g.fps_avg is None or g.fps_avg < target):
                    lim = "Processador / jogo"
                else:
                    lim = "Nada claro"
            for c, txt in enumerate((g.game, f"{h} h {m:02d}" if h else f"{m} min", fmt(g.cpu_load, " %"),
                                     fmt(g.gpu_load, " %"), fmt(g.fps_avg), fmt(g.fps_low1), lim)):
                it = QTableWidgetItem(txt)
                if 0 < c < 6:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.games.setItem(r, c, it)
        if not f.games:
            self.games.setRowCount(0)

    def _go(self, page: str):
        w = self.window()
        if hasattr(w, "go_name"):
            w.go_name(page)
