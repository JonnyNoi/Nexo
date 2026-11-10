from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QButtonGroup, QFileDialog, QGridLayout, QHeaderView, QLineEdit, QPushButton,
                               QStackedWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...core.sensors import KIND_LABELS, pick, pick_cpu_temp, pick_gpu_temp, pick_power
from ...core.util import IS_WIN, get_setting, set_setting
from ..theme import qc
from ..widgets import Bar, Card, Page, SettingRow, Toggle, hbox, label, notify, run_async, separator

GROUP_ORDER = ["CPU", "GPU", "GPU 2", "Memória", "Placa-mãe", "Disco", "Rede", "Bateria", "ACPI"]


def fmt(v: float, unit: str) -> str:
    if unit in ("MB/s",):
        return f"{v:.2f} {unit}"
    if unit in ("V", "A", "GB"):
        return f"{v:.3f} {unit}" if unit == "V" else f"{v:.2f} {unit}"
    if unit == "°C":
        return f"{v:.1f} {unit}"
    return f"{v:.0f} {unit}"


def _status(value, warn, bad) -> tuple[str, str]:
    if value is None:
        return "muted", ""
    if value >= bad:
        return "bad", "Muito quente"
    if value >= warn:
        return "warn", "Quente"
    return "ok", "Normal"


class PartCard(Card):
    """Cartão simples de um componente: valor principal em grande, estado e 3–4 linhas."""

    def __init__(self, title: str, icon: str):
        super().__init__(title, icon=icon)
        self.lay.setSpacing(8)
        self.big = label("—", "Big")
        self.state = label("")
        self.head_row = hbox(self.big, None, self.state)
        self.add(self.head_row)
        self.bar = Bar(8)
        self.add(self.bar)
        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(16)
        self.grid.setVerticalSpacing(4)
        self.add(self.grid)
        self.lay.addStretch(1)  # cartões da mesma linha ficam alinhados em cima
        self._rows: list[tuple] = []

    def set(self, big: str, kind: str, state: str, bar: float | None, rows: list[tuple[str, str]]):
        color = qc(kind).name()
        self.big.setText(f"<span style='color:{color}'>{big}</span>")
        self.state.setText(f"<b style='color:{color}'>{state}</b>" if state else "")
        self.bar.setVisible(bar is not None)
        if bar is not None:
            self.bar.set(bar)
        while len(self._rows) < len(rows):
            i = len(self._rows)
            k, v = label("", "Muted"), label("")
            v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.grid.addWidget(k, i, 0)
            self.grid.addWidget(v, i, 1)
            self._rows.append((k, v))
        for i, (k, v) in enumerate(self._rows):
            on = i < len(rows)
            k.setVisible(on)
            v.setVisible(on)
            if on:
                k.setText(rows[i][0])
                v.setText(rows[i][1])


class SensorsPage(Page):
    def __init__(self, hub):
        super().__init__("Sensores", "Como estão as peças do PC agora — atualizado a cada segundo")
        self.hub = hub
        self.items: dict[str, QTreeWidgetItem] = {}
        self.groups: dict[str, QTreeWidgetItem] = {}
        self._shown: dict[str, tuple] = {}   # último texto/visibilidade de cada linha (evita redesenhos)
        self._note = None

        # ---- alternar entre vista simples e todos os sensores
        self.view_group = QButtonGroup(self)
        self.btn_simple = QPushButton("Simples")
        self.btn_all = QPushButton("Todos os sensores")
        self.btn_hist = QPushButton("Histórico")
        self.btn_hist.setToolTip("Temperaturas, carga e consumo da última hora, 24 horas ou 7 dias")
        for i, b in enumerate((self.btn_simple, self.btn_all, self.btn_hist)):
            b.setObjectName("Chip")
            b.setCheckable(True)
            self.view_group.addButton(b, i)
        self.view_group.idClicked.connect(self._set_view)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Procurar sensor…")
        self.search.setFixedWidth(240)
        self.reset = QPushButton("Repor mín./máx.")
        self.btn_csv = QPushButton("Gravar CSV")
        self.btn_csv.setToolTip("Grava todas as leituras (1×/s) num ficheiro CSV — útil para analisar\n"
                                "um jogo ou um stress test no Excel/LibreOffice.")
        self.head.addWidget(self.search)
        self.head.addWidget(self.reset)
        self.head.addWidget(self.btn_csv)
        self.head.addSpacing(12)
        self.head.addWidget(self.btn_simple)
        self.head.addWidget(self.btn_all)
        self.head.addWidget(self.btn_hist)
        self.reset.clicked.connect(self._reset)
        self.btn_csv.clicked.connect(self._toggle_csv)

        chips = hbox(spacing=6)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for k, name in [("all", "Todos")] + list(KIND_LABELS.items()) + [("thread", "Threads")]:
            b = QPushButton(name)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setProperty("kind", k)
            if k == "all":
                b.setChecked(True)
            self.chip_group.addButton(b)
            chips.addWidget(b)
        chips.addStretch(1)
        adv = QWidget()
        adv.setObjectName("Transparent")
        av = QVBoxLayout(adv)
        av.setContentsMargins(0, 0, 0, 0)
        av.setSpacing(12)
        av.addLayout(chips)
        self.chip_group.buttonClicked.connect(lambda _b: self._filter())
        self.search.textChanged.connect(lambda _t: self._filter())

        card = Card()
        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["Sensor", "Atual", "Mínimo", "Máximo"])
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        for c in (1, 2, 3):
            self.tree.header().setSectionResizeMode(c, QHeaderView.Fixed)
            self.tree.setColumnWidth(c, 120)
        self.tree.setAlternatingRowColors(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setUniformRowHeights(True)
        card.add(self.tree, 1)
        av.addWidget(card, 1)

        # ---- vista simples
        simple = QWidget()
        simple.setObjectName("Transparent")
        sv = QVBoxLayout(simple)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(14)
        self.summary = label("", "CardTitle", wrap=True)
        sv.addWidget(self.summary)
        self.parts_grid = QGridLayout()
        self.parts_grid.setSpacing(14)
        sv.addLayout(self.parts_grid)
        sv.addStretch(1)
        self.parts: dict[str, PartCard] = {}
        for key, title, icon in (("cpu", "Processador", "cpu"), ("gpu", "Placa gráfica", "gauge"),
                                 ("ram", "Memória RAM", "box"), ("disk", "Disco", "disk"),
                                 ("net", "Rede", "globe"), ("fans", "Ventoinhas", "refresh"),
                                 ("bat", "Bateria", "zap")):
            self.parts[key] = PartCard(title, icon)

        self.stack = QStackedWidget()
        self.stack.addWidget(simple)
        self.stack.addWidget(adv)
        from ..historyview import HistoryView
        self.hist = HistoryView(hub)
        self.stack.addWidget(self.hist)
        self.add(self.stack, 1)
        self.note = label("", "Muted", wrap=True)
        self.add(self.note)
        if IS_WIN:
            self._build_lhm()
        hub.updated.connect(self._update)
        hub.updated.connect(self._update_simple)
        view = {"all": 1, "history": 2}.get(get_setting("sensors_view", "simple"), 0)
        self.view_group.button(view).setChecked(True)
        self._set_view(view)

    # ------------------------------------------------------------------ vista
    def _set_view(self, i: int):
        self.stack.setCurrentIndex(i)
        set_setting("sensors_view", ("simple", "all", "history")[i])
        for w in (self.search, self.reset, self.btn_csv):
            w.setVisible(i == 1)
        if i == 2:
            if self.isVisible():
                self.hist.start()
            return
        self.hist.stop()
        if i:
            self._filter()
        else:
            self._update_simple(self.hub.last, force=True)

    def _update_simple(self, readings, force=False):
        if (not self.isVisible() and not force) or self.stack.currentIndex() != 0 or not readings:
            return
        lim_cpu = int(get_setting("alert_cpu", 90))
        lim_gpu = int(get_setting("alert_gpu", 85))
        by = {}
        for r in readings:
            by.setdefault(r.group, []).append(r)

        def first(group, kind, exclude=()):
            for r in by.get(group, ()):
                if r.kind == kind and not any(x in r.name for x in exclude):
                    return r
            return None

        def temps(group):
            return [r for r in by.get(group, ()) if r.kind == "temp"]

        cards: list[tuple[str, tuple]] = []
        problems = []
        # CPU
        if "CPU" in by:
            t = pick_cpu_temp(readings)
            kind, st = _status(t, lim_cpu - 10, lim_cpu)
            load = pick(readings, "CPU", "Carga total")
            rows = [("Carga", f"{load:.0f} %" if load is not None else "—")]
            f = pick(readings, "CPU", "Clock médio")
            if f:
                rows.append(("Velocidade", f"{f / 1000:.2f} GHz"))
            pw = pick_power(readings, "CPU")
            if pw is not None:
                rows.append(("Consumo", f"{pw:.0f} W"))
            cards.append(("cpu", (f"{t:.0f} °C" if t is not None else f"{load or 0:.0f} %",
                                  kind if t is not None else "accent", st, load, rows)))
            if kind in ("warn", "bad"):
                problems.append(f"processador {st.lower()} ({t:.0f} °C)")
        # GPU
        if "GPU" in by:
            t = pick_gpu_temp(readings)
            kind, st = _status(t, lim_gpu - 10, lim_gpu)
            load_r = first("GPU", "load", ("VRAM", "memória"))
            rows = [("Carga", f"{load_r.value:.0f} %" if load_r else "—")]
            vram = first("GPU", "mem")
            if vram:
                rows.append(("Memória (VRAM)", fmt(vram.value, vram.unit)))
            pw = pick_power(readings, "GPU")
            if pw is not None:
                rows.append(("Consumo", f"{pw:.0f} W"))
            fan = first("GPU", "fan")
            if fan:
                rows.append(("Ventoinha", f"{fan.value:.0f} RPM" if fan.unit == "RPM" else fmt(fan.value, fan.unit)))
            cards.append(("gpu", (f"{t:.0f} °C" if t is not None else "—", kind if t is not None else "accent", st,
                                  load_r.value if load_r else None, rows)))
            if kind in ("warn", "bad"):
                problems.append(f"placa gráfica {st.lower()} ({t:.0f} °C)")
        # RAM
        ram = pick(readings, "Memória", "RAM em uso")
        if ram is not None:
            kind = "bad" if ram >= 95 else "warn" if ram >= 85 else "ok"
            st = "Quase cheia" if ram >= 95 else "Muito usada" if ram >= 85 else "Normal"
            rows = []
            used = pick(readings, "Memória", "RAM usada")
            if used is not None:
                rows.append(("Em uso", f"{used:.1f} GB"))
            sw = pick(readings, "Memória", "Swap em uso")
            if sw is not None:
                rows.append(("Swap", f"{sw:.0f} %"))
            mt = temps("Memória")
            if mt:
                rows.append(("Temperatura", f"{max(r.value for r in mt):.0f} °C"))
            cards.append(("ram", (f"{ram:.0f} %", kind, st, ram, rows)))
            if kind != "ok":
                problems.append(f"memória {st.lower()}")
        # Disco
        if "Disco" in by:
            dt = temps("Disco")
            comp = next((r for r in dt if r.name.startswith(("Composite", "Temperatura"))), None)
            t = comp.value if comp else (max(r.value for r in dt) if dt else None)
            kind, st = _status(t, 60, 70)
            rows = []
            rd, wr = pick(readings, "Disco", "Leitura"), pick(readings, "Disco", "Escrita")
            if rd is not None:
                rows.append(("Leitura", f"{rd:.1f} MB/s"))
            if wr is not None:
                rows.append(("Escrita", f"{wr:.1f} MB/s"))
            big = f"{t:.0f} °C" if t is not None else f"{(rd or 0) + (wr or 0):.1f} MB/s"
            cards.append(("disk", (big, kind if t is not None else "accent", st, None, rows)))
            if kind in ("warn", "bad"):
                problems.append(f"disco {st.lower()} ({t:.0f} °C)")
        # Rede
        dl, ul = pick(readings, "Rede", "Download"), pick(readings, "Rede", "Upload")
        if dl is not None or ul is not None:
            cards.append(("net", (f"↓ {(dl or 0) * 8:.1f} Mb/s", "accent", "",
                                  None, [("Receber", f"{dl or 0:.2f} MB/s"), ("Enviar", f"{ul or 0:.2f} MB/s")])))
        # Ventoinhas (fora da placa gráfica)
        fans = [r for r in readings if r.kind == "fan" and r.group != "GPU"]
        if fans:
            spinning = [r for r in fans if r.value > 0]
            rows = [(r.name.replace("Ventoinha ", ""), f"{r.value:.0f} RPM") for r in fans[:5]]
            cards.append(("fans", (f"{len(spinning)} a rodar", "accent", "", None, rows)))
        # Bateria
        bat = [r for r in by.get("Bateria", ()) if r.kind == "load"]
        if bat:
            b = bat[0].value
            cards.append(("bat", (f"{b:.0f} %", "bad" if b < 15 else "warn" if b < 30 else "ok",
                                  "Fraca" if b < 30 else "", b, [])))

        shown = [k for k, _ in cards]
        for i, (key, args) in enumerate(cards):
            c = self.parts[key]
            c.set(*args)
            if self.parts_grid.indexOf(c) < 0 or self.parts_grid.getItemPosition(self.parts_grid.indexOf(c))[:2] \
                    != (i // 3, i % 3):
                self.parts_grid.addWidget(c, i // 3, i % 3)
            c.setVisible(True)
        for key, c in self.parts.items():
            if key not in shown:
                c.setVisible(False)
        for col in range(3):
            self.parts_grid.setColumnStretch(col, 1)
        ok = qc("ok").name()
        if problems:
            self.summary.setText(f"<span style='color:{qc('warn').name()}'>⚠ Atenção:</span> " + ", ".join(problems)
                                 + ". Verifique a ventilação e o pó.")
        else:
            self.summary.setText(f"<span style='color:{ok}'>✔ Está tudo normal</span> — temperaturas e uso dentro "
                                 "do esperado.")

    def _reset(self):
        self.hub.minmax.clear()
        self._shown.clear()
        self._filter()

    def _toggle_csv(self):
        if self.hub.csv_path:
            path = self.hub.csv_path
            self.hub.stop_csv()
            self.btn_csv.setText("Gravar CSV")
            self.btn_csv.setObjectName("")
            self.btn_csv.setStyle(self.btn_csv.style())
            notify(f"Registo guardado em {path}", "ok")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Gravar sensores", f"sensores-{time.strftime('%Y%m%d-%H%M')}.csv",
                                              "CSV (*.csv)")
        if not path:
            return
        if not path.lower().endswith(".csv"):
            path += ".csv"
        try:
            self.hub.start_csv(path)
        except OSError as e:
            notify(f"Não foi possível gravar: {e}", "bad")
            return
        self.btn_csv.setText("● Parar gravação")
        self.btn_csv.setObjectName("Danger")
        self.btn_csv.setStyle(self.btn_csv.style())
        notify("A gravar sensores a cada segundo (continua mesmo noutras páginas).", "info")

    # ------------------------------------------------------------------ LibreHardwareMonitor (Windows)
    def _build_lhm(self):
        from ...core import lhm
        c = Card("LibreHardwareMonitor", f"Lê os sensores que o Windows esconde (temperatura da CPU, ventoinhas, "
                 f"tensões). Versão oficial {lhm.VERSION}, guardada na pasta do Nexo — sem instalador.", icon="thermo")
        self.lhm_status = label(lhm.status_text(), "Muted", wrap=True)
        self.lhm_btn = QPushButton("Instalar e abrir")
        self.lhm_btn.setObjectName("Primary")
        self.lhm_btn.clicked.connect(self._lhm_install)
        self.lhm_rm = QPushButton("Remover")
        self.lhm_rm.clicked.connect(self._lhm_remove)
        c.add(hbox(self.lhm_status, None, self.lhm_rm, self.lhm_btn))
        c.add(separator())
        tg = Toggle(bool(get_setting("lhm_autostart")))
        tg.clicked.connect(lambda on: set_setting("lhm_autostart", bool(on)))
        c.add(SettingRow("Abrir com o Nexo", "Abre-o escondido na bandeja quando o Nexo arranca e fecha-o quando o "
                         "Nexo sai.", tg))
        self.add(c)
        self._lhm_refresh()

    def _lhm_refresh(self):
        from ...core import lhm
        self.lhm_status.setText(lhm.status_text())
        inst, run_ = lhm.installed(), lhm.running()
        self.lhm_btn.setText("Abrir agora" if inst else "Instalar e abrir")
        self.lhm_btn.setVisible(not run_)
        self.lhm_rm.setVisible(inst)

    def _lhm_install(self):
        from ...core import lhm
        from ..netmonitor import require_online
        if lhm.installed():
            lhm.start()
            notify("LibreHardwareMonitor aberto na bandeja — os sensores aparecem em alguns segundos.", "ok")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._lhm_refresh)
            return
        if not require_online("Transferir o LibreHardwareMonitor"):
            return
        self.lhm_btn.setEnabled(False)
        self.lhm_status.setText("A transferir…")

        def done(_p):
            self.lhm_btn.setEnabled(True)
            lhm.start()
            notify("LibreHardwareMonitor instalado e aberto na bandeja.", "ok")
            from PySide6.QtCore import QTimer
            QTimer.singleShot(3000, self._lhm_refresh)

        def fail(m):
            self.lhm_btn.setEnabled(True)
            self.lhm_status.setText(f"Não foi possível instalar: {m}")
        run_async(lhm.install, on_done=done, on_fail=fail)

    def _lhm_remove(self):
        from ...core import lhm
        from ..widgets import confirm
        if lhm.running() and not confirm(self, "Remover", "Feche o LibreHardwareMonitor antes de o remover "
                                         "(ícone na bandeja → Exit). Continuar mesmo assim?"):
            return
        lhm.remove()
        self._lhm_refresh()
        notify("LibreHardwareMonitor removido.", "ok")

    def on_show(self):
        if self.stack.currentIndex() == 2:
            self.hist.start()
        elif self.stack.currentIndex():
            self._filter()
        else:
            self._update_simple(self.hub.last, force=True)

    def on_hide(self):
        self.hist.stop()

    def _kind(self):
        b = self.chip_group.checkedButton()
        return b.property("kind") if b else "all"

    def _filter(self):
        self._update(self.hub.last, force=True)

    def _update(self, readings, force=False):
        if (not self.isVisible() and not force) or self.stack.currentIndex() != 1:
            return
        kind = self._kind()
        q = self.search.text().strip().lower()
        minmax = self.hub.minmax
        shown = self._shown
        seen_groups = set()
        bold = None
        self.tree.setUpdatesEnabled(False)
        try:
            for r in readings:
                g = self.groups.get(r.group)
                if g is None:
                    if bold is None:
                        bold = QFont(self.tree.font())
                        bold.setBold(True)
                    g = QTreeWidgetItem([r.group])
                    g.setFont(0, bold)
                    order = GROUP_ORDER.index(r.group) if r.group in GROUP_ORDER else 99
                    g.setData(0, Qt.UserRole, order)
                    idx = sum(1 for x in self.groups.values() if x.data(0, Qt.UserRole) <= order)
                    self.tree.insertTopLevelItem(idx, g)
                    g.setExpanded(True)
                    self.groups[r.group] = g
                key = r.key
                it = self.items.get(key)
                if it is None:
                    it = QTreeWidgetItem([r.name, "", "", ""])
                    for c in (1, 2, 3):
                        it.setTextAlignment(c, Qt.AlignRight | Qt.AlignVCenter)
                    g.addChild(it)
                    self.items[key] = it
                is_thread = r.name.startswith("Carga thread")
                if kind == "thread":
                    vis = is_thread
                elif kind == "all":
                    vis = not is_thread
                else:
                    vis = r.kind == kind and not is_thread
                if vis and q:
                    vis = q in r.name.lower() or q in r.group.lower()
                mm = minmax.get(key) or (r.value, r.value)
                state = (fmt(r.value, r.unit), fmt(mm[0], r.unit), fmt(mm[1], r.unit), vis)
                old = shown.get(key)
                if old != state:
                    if old is None or old[3] != vis:
                        it.setHidden(not vis)
                    if vis:  # linhas escondidas não precisam de texto atualizado
                        for c in (1, 2, 3):
                            if old is None or old[c - 1] != state[c - 1]:
                                it.setText(c, state[c - 1])
                        shown[key] = state
                    else:
                        shown[key] = (None, None, None, False)
                if vis:
                    seen_groups.add(r.group)
            for name, g in self.groups.items():
                hide = name not in seen_groups
                if g.isHidden() != hide:
                    g.setHidden(hide)
        finally:
            self.tree.setUpdatesEnabled(True)
        has_temp = any(r.kind == "temp" and r.group == "CPU" for r in readings)
        if not has_temp and IS_WIN:
            note = ("Sem temperatura da CPU? O Windows não a expõe diretamente. Instale o LibreHardwareMonitor "
                    "(gratuito, código aberto) com o botão abaixo — o Nexo abre-o escondido na bandeja e passa a "
                    "ler todos os sensores dele (temperaturas, ventoinhas, tensões).")
        elif not has_temp:
            note = "Sem temperatura da CPU: carregue o módulo do sensor (coretemp/k10temp) ou instale lm_sensors."
        else:
            note = ""
        if note != self._note:
            self._note = note
            self.note.setText(note)
