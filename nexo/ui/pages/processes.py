from __future__ import annotations

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QCheckBox, QHBoxLayout, QHeaderView, QLineEdit,
                               QMenu, QPushButton, QStackedWidget, QTableView, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import processes as pr
from ...core.util import get_setting, human_bytes, set_setting
from ..theme import qc
from ..widgets import Bar, Card, Page, confirm, hbox, label, notify, run_async


class _Meter(QWidget):
    """Barra + valor numa célula da tabela simples."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Transparent")
        h = QHBoxLayout(self)
        h.setContentsMargins(8, 0, 8, 0)
        h.setSpacing(10)
        self.bar = Bar(8)
        self.txt = label("")
        self.txt.setFixedWidth(78)
        self.txt.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        h.addWidget(self.bar, 1)
        h.addWidget(self.txt)

    def set(self, pct: float, text: str, warn: float, bad: float):
        self.bar.set(pct, "bad" if pct >= bad else "warn" if pct >= warn else "accent")
        self.txt.setText(text)

COLS = ["Nome", "PID", "CPU", "Memória", "Threads", "Utilizador", "Estado"]


class ProcModel(QAbstractTableModel):
    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLS)

    def headerData(self, s, o, role=Qt.DisplayRole):
        if o == Qt.Horizontal and role == Qt.DisplayRole:
            return COLS[s]
        if o == Qt.Horizontal and role == Qt.TextAlignmentRole and s in (1, 2, 3, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        return None

    def data(self, idx, role=Qt.DisplayRole):
        r = self.rows[idx.row()]
        c = idx.column()
        if role == Qt.DisplayRole:
            return (r["name"], str(r["pid"]), f"{r['cpu']:.1f}%", human_bytes(r["rss"]), str(r["threads"]),
                    r["user"], r["status"])[c]
        if role == Qt.UserRole:  # valor para ordenar
            return (r["name"].lower(), r["pid"], r["cpu"], r["rss"], r["threads"], r["user"].lower(), r["status"])[c]
        if role == Qt.TextAlignmentRole and c in (1, 2, 3, 4):
            return int(Qt.AlignRight | Qt.AlignVCenter)
        if role == Qt.ToolTipRole and c == 0:
            return r["exe"] or r["name"]
        return None

    def update_rows(self, rows: list[dict]):
        old_pids = [r["pid"] for r in self.rows]
        new_pids = [r["pid"] for r in rows]
        if old_pids == new_pids:
            # só mudam os valores — não reconstrói a vista (mantém seleção e scroll)
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 2), self.index(len(rows) - 1, len(COLS) - 1))
        else:
            self.beginResetModel()
            self.rows = rows
            self.endResetModel()


class FilterProxy(QSortFilterProxyModel):
    def __init__(self):
        super().__init__()
        self.query = ""
        self.setSortRole(Qt.UserRole)
        self.setDynamicSortFilter(True)

    def set_query(self, q: str):
        self.query = q.strip().lower()
        self.invalidateFilter()

    def filterAcceptsRow(self, row, parent):
        if not self.query:
            return True
        r = self.sourceModel().rows[row]
        return self.query in r["name"].lower() or self.query == str(r["pid"]) or self.query in r["user"].lower()


class ProcessesPage(Page):
    def __init__(self):
        super().__init__("Processos", "As aplicações abertas e quanto estão a gastar — feche as que estão a pesar")
        self.view_group = QButtonGroup(self)
        self.btn_simple = QPushButton("Simples")
        self.btn_all = QPushButton("Todos os processos")
        for i, b in enumerate((self.btn_simple, self.btn_all)):
            b.setObjectName("Chip")
            b.setCheckable(True)
            self.view_group.addButton(b, i)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Procurar por nome, PID ou utilizador…")
        self.search.setFixedWidth(280)
        self.only_mine = QCheckBox("Só os meus")
        self.only_mine.setChecked(True)
        self.btn_pause = QPushButton("Pausar")
        self.btn_pause.setCheckable(True)
        self.head.addWidget(self.search)
        self.head.addWidget(self.only_mine)
        self.head.addWidget(self.btn_pause)
        self.head.addSpacing(12)
        self.head.addWidget(self.btn_simple)
        self.head.addWidget(self.btn_all)

        card = Card()
        self.model = ProcModel()
        self.proxy = FilterProxy()
        self.proxy.setSourceModel(self.model)
        self.view = QTableView()
        self.view.setModel(self.proxy)
        self.view.setSortingEnabled(True)
        self.view.sortByColumn(2, Qt.DescendingOrder)
        self.view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.view.setAlternatingRowColors(True)
        self.view.setShowGrid(False)
        self.view.verticalHeader().setVisible(False)
        self.view.verticalHeader().setDefaultSectionSize(28)
        hh = self.view.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 80), (2, 80), (3, 110), (4, 80), (5, 130), (6, 100)):
            hh.setSectionResizeMode(c, QHeaderView.Interactive)
            self.view.setColumnWidth(c, w)
        self.view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._menu)
        card.add(self.view, 1)

        self.btn_end = QPushButton("Terminar")
        self.btn_kill = QPushButton("Forçar fim")
        self.btn_kill.setObjectName("Danger")
        self.btn_folder = QPushButton("Abrir pasta")
        self.summary = label("", "Muted")
        card.add(hbox(self.summary, None, self.btn_folder, self.btn_end, self.btn_kill))

        self.stack = QStackedWidget()
        self.stack.addWidget(self._build_simple())
        self.stack.addWidget(card)
        self.add(self.stack, 1)
        self.view_group.idClicked.connect(self._set_view)

        self.btn_end.clicked.connect(lambda: self._end(False))
        self.btn_kill.clicked.connect(lambda: self._end(True))
        self.btn_folder.clicked.connect(self._folder)
        self.search.textChanged.connect(self.proxy.set_query)
        self.only_mine.toggled.connect(lambda _c: self.refresh())
        self.view.selectionModel().selectionChanged.connect(lambda *_: self._sel_changed())
        act = QAction(self)
        act.setShortcut(QKeySequence.Delete)
        act.triggered.connect(lambda: self._end(False))
        self.view.addAction(act)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self._busy = False
        self._sel_changed()
        view = 1 if get_setting("proc_view", "simple") == "all" else 0
        self.view_group.button(view).setChecked(True)
        self._set_view(view, refresh=False)

    # ------------------------------------------------------------------ vista simples
    def _build_simple(self) -> QWidget:
        w = QWidget()
        w.setObjectName("Transparent")
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        self.s_summary = label("A ler…", "CardTitle", wrap=True)
        v.addWidget(self.s_summary)
        card = Card()
        sort_row = hbox(label("Ordenar por:", "Muted"), spacing=6)
        self.sort_group = QButtonGroup(self)
        for i, txt in enumerate(("Memória", "Processador", "Nome")):
            b = QPushButton(txt)
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.sort_group.addButton(b, i)
            sort_row.addWidget(b)
        sort_row.addStretch(1)
        self.sort_group.idClicked.connect(lambda _i: self._fill_simple())
        card.add(sort_row)
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Aplicação", "Processador", "Memória", ""])
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, wd in ((1, 230), (2, 230), (3, 110)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            t.setColumnWidth(c, wd)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(46)
        t.setEditTriggers(QAbstractItemView.NoEditTriggers)
        t.setSelectionMode(QAbstractItemView.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setShowGrid(False)
        t.setAlternatingRowColors(True)
        self.s_table = t
        card.add(t, 1)
        self.s_hidden = label("", "Muted", wrap=True)
        card.add(self.s_hidden)
        v.addWidget(card, 1)
        self.apps: list[dict] = []
        self.hidden = {"count": 0, "cpu": 0.0, "rss": 0}
        return w

    def _set_view(self, i: int, refresh: bool = True):
        self.stack.setCurrentIndex(i)
        set_setting("proc_view", "all" if i else "simple")
        for wdg in (self.search, self.only_mine, self.btn_pause):
            wdg.setVisible(bool(i))
        if refresh:
            self.refresh()

    def _fill_simple(self):
        mode = self.sort_group.checkedId()
        key = {0: lambda a: -a["rss"], 1: lambda a: -a["cpu"], 2: lambda a: a["name"].lower()}[mode]
        apps = sorted(self.apps, key=key)
        t = self.s_table
        total_ram = pr.psutil.virtual_memory().total or 1
        if t.rowCount() != len(apps):
            t.setRowCount(len(apps))
        for i, a in enumerate(apps):
            it = t.item(i, 0)
            if it is None:
                it = QTableWidgetItem()
                f = it.font()
                f.setBold(True)
                it.setFont(f)
                t.setItem(i, 0, it)
                t.setCellWidget(i, 1, _Meter())
                t.setCellWidget(i, 2, _Meter())
                b = QPushButton("Fechar")
                b.clicked.connect(lambda _c=False, row=i: self._close_row(row))
                holder = QWidget()
                holder.setObjectName("Transparent")
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(8, 6, 8, 6)
                hl.addWidget(b)
                t.setCellWidget(i, 3, holder)
            n = len(a["pids"])
            it.setText(a["name"] + (f"   ·  {n} processos" if n > 1 else ""))
            it.setToolTip(a["exe"] or a["name"])
            it.setData(Qt.UserRole, a["key"])
            t.cellWidget(i, 1).set(min(a["cpu"], 100), f"{a['cpu']:.1f} %", 25, 60)
            t.cellWidget(i, 2).set(a["rss"] * 100 / total_ram, human_bytes(a["rss"]), 15, 30)
        self._apps_sorted = apps

    def _got_simple(self, rows):
        self._busy = False
        self.apps, self.hidden = pr.group_apps(rows)
        self._fill_simple()
        cpu = min(sum(r["cpu"] for r in rows), 100)
        vm = pr.psutil.virtual_memory()
        heavy = max(self.apps, key=lambda a: a["rss"], default=None)
        busy = max(self.apps, key=lambda a: a["cpu"], default=None)
        txt = f"{len(self.apps)} aplicações abertas · processador {cpu:.0f} % · memória {human_bytes(vm.used)} de {human_bytes(vm.total)}"
        if busy and busy["cpu"] >= 25:
            txt += (f"<br><span style='color:{qc('warn').name()}'>⚠ {busy['name']} está a usar muito o processador "
                    f"({busy['cpu']:.0f} %)</span>")
        elif heavy:
            txt += f"<br><span style='opacity:.7'>O que mais pesa agora: {heavy['name']} ({human_bytes(heavy['rss'])})</span>"
        self.s_summary.setText(txt)
        h = self.hidden
        self.s_hidden.setText(f"Mais {h['count']} processos do sistema e em segundo plano ({human_bytes(h['rss'])}) "
                              "não aparecem aqui — são necessários ao sistema. Veja-os em «Todos os processos».")

    def _close_row(self, row: int):
        apps = getattr(self, "_apps_sorted", [])
        if row >= len(apps):
            return
        a = apps[row]
        if not confirm(self, "Fechar", f"Fechar {a['name']}?\n\nTrabalho não guardado nesta aplicação pode perder-se."):
            return

        def done(res):
            n, errors = res
            notify(f"{a['name']} fechado." if not errors else f"{a['name']}: {errors[0]}", "warn" if errors else "ok")
            self.refresh()
        run_async(pr.end, a["pids"], False, on_done=done)

    # ------------------------------------------------------------------
    def on_show(self):
        first = not self.model.rows and not self.apps
        self.refresh()
        if first:  # a 1.ª leitura de %CPU é sempre 0 — repete logo para mostrar valores reais
            QTimer.singleShot(700, self.refresh)
        self.timer.start(2000)

    def on_hide(self):
        self.timer.stop()

    def refresh(self):
        if self._busy or (self.stack.currentIndex() == 1 and self.btn_pause.isChecked()):
            return
        self._busy = True
        if self.stack.currentIndex() == 0:
            run_async(pr.snapshot, True, on_done=self._got_simple, on_fail=self._fail)
        else:
            run_async(pr.snapshot, self.only_mine.isChecked(), on_done=self._got, on_fail=self._fail)

    def _fail(self, msg):
        self._busy = False
        notify(f"Erro a ler processos: {msg}", "bad")

    def _got(self, rows):
        self._busy = False
        sel = set(self._selected_pids())
        same = [r["pid"] for r in self.model.rows] == [r["pid"] for r in rows]
        self.model.update_rows(rows)
        if sel and not same:
            self._reselect(sel)
            self._sel_changed()
        cpu = sum(r["cpu"] for r in rows)
        mem = sum(r["rss"] for r in rows)
        self.summary.setText(f"{len(rows)} processos · CPU {min(cpu, 100):.0f}% · {human_bytes(mem)} de RAM")

    def _reselect(self, pids: set[int]):
        sm = self.view.selectionModel()
        sm.blockSignals(True)
        sm.clearSelection()
        for row in range(self.proxy.rowCount()):
            src = self.proxy.mapToSource(self.proxy.index(row, 0))
            if self.model.rows[src.row()]["pid"] in pids:
                sm.select(self.proxy.index(row, 0), sm.SelectionFlag.Select | sm.SelectionFlag.Rows)
        sm.blockSignals(False)

    def _selected(self) -> list[dict]:
        rows = {self.proxy.mapToSource(i).row() for i in self.view.selectionModel().selectedRows()}
        return [self.model.rows[r] for r in sorted(rows) if r < len(self.model.rows)]

    def _selected_pids(self) -> list[int]:
        return [r["pid"] for r in self._selected()]

    def _sel_changed(self):
        sel = self._selected()
        for b in (self.btn_end, self.btn_kill):
            b.setEnabled(bool(sel))
        self.btn_folder.setEnabled(len(sel) == 1 and bool(sel[0]["exe"]))

    # ------------------------------------------------------------------ ações
    def _end(self, force: bool):
        sel = [r for r in self._selected() if not r["self"]]
        if not sel:
            return
        names = ", ".join(sorted({r["name"] for r in sel})[:6]) + ("…" if len(sel) > 6 else "")
        verb = "Forçar o fim de" if force else "Terminar"
        if not confirm(self, verb, f"{verb} {len(sel)} processo(s)?\n\n{names}\n\n"
                                   "Trabalho não guardado nesses programas pode perder-se."):
            return

        def done(res):
            n, errors = res
            notify(f"{n} processo(s) terminado(s)" + (f". {errors[0]}" if errors else ""), "warn" if errors else "ok")
            self.refresh()
        run_async(pr.end, [r["pid"] for r in sel], force, on_done=done)

    def _folder(self):
        sel = self._selected()
        if sel and not pr.open_location(sel[0]["exe"]):
            notify("Localização do programa indisponível.", "warn")

    def _menu(self, pos):
        sel = self._selected()
        if not sel:
            return
        m = QMenu(self)
        m.addAction("Terminar", lambda: self._end(False))
        m.addAction("Forçar fim", lambda: self._end(True))
        if len(sel) == 1:
            m.addAction("Abrir pasta do programa", self._folder).setEnabled(bool(sel[0]["exe"]))
            pm = m.addMenu("Prioridade")
            for i, name in enumerate(pr.PRIORITIES):
                pm.addAction(name, lambda i=i, pid=sel[0]["pid"]: self._prio(pid, i))
            m.addSeparator()
            m.addAction("Copiar caminho", lambda: self._copy(sel[0]["exe"] or sel[0]["name"]))
        m.exec(self.view.viewport().mapToGlobal(pos))

    def _prio(self, pid, level):
        ok, msg = pr.set_priority(pid, level)
        notify(msg, "ok" if ok else "bad")

    def _copy(self, text):
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(text)
        notify("Copiado.", "ok")
