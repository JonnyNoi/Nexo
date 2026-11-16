from __future__ import annotations

import os
import shutil
import time

import psutil
from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QBrush, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QHeaderView, QMenu,
                               QPushButton, QTableWidget, QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ...core import cleanup, diskscan
from ...core import disksafety as ds
from ...core.util import IS_WIN, delete_as_admin, human_bytes, is_admin, open_path, relaunch_as_admin
from ..theme import qc
from ..widgets import Bar, Card, Page, Task, confirm, label, notify, run_async, status_dot

R_PATH, R_DIR, R_APPID, R_LEVEL = Qt.UserRole, Qt.UserRole + 1, Qt.UserRole + 2, Qt.UserRole + 3


class SizeItem(QTableWidgetItem):
    def __init__(self, size: int):
        super().__init__(human_bytes(size) if size >= 0 else ("…" if size == -1 else "?"))
        self.setData(Qt.UserRole, size)
        self.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def __lt__(self, other):
        return (self.data(Qt.UserRole) or 0) < (other.data(Qt.UserRole) or 0)


class LevelItem(QTableWidgetItem):
    """Célula 'Segurança' colorida; ordena do mais seguro para o sistema."""

    def __init__(self, level: str):
        super().__init__(ds.LEVELS.get(level, ds.LEVELS[""])[0])
        self.level = level
        self.setData(Qt.UserRole, ds.LEVEL_ORDER.index(level) if level in ds.LEVEL_ORDER else 9)
        _paint_level(self, level)

    def __lt__(self, other):
        return (self.data(Qt.UserRole) or 0) < (other.data(Qt.UserRole) or 0)


def _paint_level(item, level: str, col: int | None = None):
    color = ds.LEVELS.get(level, ds.LEVELS[""])[1]
    f = QFont(item.font() if col is None else item.font(col))
    f.setBold(level != ds.UNKNOWN)
    if col is None:
        item.setForeground(QBrush(qc(color)))
        item.setFont(f)
    else:
        item.setForeground(col, QBrush(qc(color)))
        item.setFont(col, f)


def _table(headers, stretch: int) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


class LevelBar(QWidget):
    """Barra empilhada: quanto do disco é seguro / jogos / pessoal / sistema."""

    def __init__(self):
        super().__init__()
        self.parts: list[tuple[int, str]] = []
        self.setFixedHeight(16)

    def set(self, parts):
        self.parts = [(v, c) for v, c in parts if v > 0]
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        h = r.height()
        p.setPen(Qt.NoPen)
        p.setBrush(qc("surface3"))
        p.drawRoundedRect(r, h / 2, h / 2)
        total = sum(v for v, _ in self.parts)
        if total:
            path_clip = QRectF(r)
            p.setClipRect(path_clip)
            x = r.left()
            for v, c in self.parts:
                w = r.width() * v / total
                p.setBrush(qc(c))
                p.drawRect(QRectF(x, r.top(), w + 0.5, h))
                x += w
        p.end()


class FileTable(QTableWidget):
    """Tabela de ficheiros/pastas com caixa de seleção, nível de segurança e ações."""
    HEAD = ["Nome", "Tamanho", "Segurança", "Tipo", "Modificado", "O que é / o que fazer", "Pasta"]

    def __init__(self):
        super().__init__(0, len(self.HEAD))
        self.setHorizontalHeaderLabels(self.HEAD)
        h = self.horizontalHeader()
        h.setSectionResizeMode(QHeaderView.Interactive)
        h.setStretchLastSection(True)
        for i, w in enumerate((280, 90, 150, 130, 95, 380)):
            self.setColumnWidth(i, w)
        self.verticalHeader().setVisible(False)
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setAlternatingRowColors(True)
        self.setSortingEnabled(True)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.doubleClicked.connect(lambda idx: _open_any(self.item(idx.row(), 0).data(R_PATH)))

    def set_entries(self, entries):
        self.setSortingEnabled(False)
        self.setRowCount(len(entries))
        for i, f in enumerate(entries):
            name = QTableWidgetItem(os.path.basename(f.path.rstrip("/\\")) or f.path)
            name.setData(R_PATH, f.path)
            name.setData(R_DIR, f.is_dir)
            name.setData(R_APPID, f.steam_appid)
            name.setData(R_LEVEL, f.level)
            name.setToolTip(f.path)
            name.setFlags(name.flags() | Qt.ItemIsUserCheckable)
            name.setCheckState(Qt.Unchecked)
            self.setItem(i, 0, name)
            self.setItem(i, 1, SizeItem(f.size))
            self.setItem(i, 2, LevelItem(f.level))
            self.setItem(i, 3, QTableWidgetItem(f.type))
            self.setItem(i, 4, QTableWidgetItem(time.strftime("%Y-%m-%d", time.localtime(f.mtime)) if f.mtime else ""))
            s = QTableWidgetItem(f.suggestion)
            s.setToolTip(f.suggestion)
            self.setItem(i, 5, s)
            d = QTableWidgetItem(os.path.dirname(f.path.rstrip("/\\")))
            d.setToolTip(d.text())
            self.setItem(i, 6, d)
        self.setSortingEnabled(True)
        self.sortByColumn(1, Qt.DescendingOrder)

    def check_level(self, levels: set[str]) -> int:
        n = 0
        for i in range(self.rowCount()):
            it = self.item(i, 0)
            on = it.data(R_LEVEL) in levels
            it.setCheckState(Qt.Checked if on else Qt.Unchecked)
            n += on
        return n

    def checked(self) -> list[tuple[object, str]]:
        out = []
        for i in range(self.rowCount()):
            it = self.item(i, 0)
            if it and it.checkState() == Qt.Checked:
                out.append((it, it.data(R_PATH)))
        if not out:  # sem caixas marcadas usa a seleção
            rows = sorted({ix.row() for ix in self.selectedIndexes()})
            out = [(self.item(r, 0), self.item(r, 0).data(R_PATH)) for r in rows]
        return out


def _base(p: str) -> str:
    return os.path.basename(p.rstrip("/\\")) or p


def _open_any(path: str):
    if path:
        open_path(path if os.path.isdir(path) else os.path.dirname(path))


def move_to_trash(path: str) -> bool:
    from PySide6.QtCore import QFile
    try:
        r = QFile.moveToTrash(path)
        return bool(r[0] if isinstance(r, tuple) else r)
    except Exception:
        return False


def delete_permanent(path: str) -> bool:
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
        return True
    except OSError:
        return False


def _uninstall(path: str, appid: str) -> None:
    """Abre o desinstalador certo para um jogo/programa."""
    if appid:
        QDesktopServices.openUrl(QUrl(f"steam://uninstall/{appid}"))
        notify("A Steam vai pedir para confirmar a desinstalação.", "info")
        return
    low = path.lower().replace("\\", "/")
    if IS_WIN:
        if "xboxgames" in low or "/windowsapps" in low:
            QDesktopServices.openUrl(QUrl("ms-settings:appsfeatures"))
        else:
            QDesktopServices.openUrl(QUrl("ms-settings:appsfeatures"))
        notify("Procure o programa em Definições › Aplicações e carregue em Desinstalar.", "info")
        return
    if "/steamapps/" in low:
        QDesktopServices.openUrl(QUrl("steam://open/games"))
        notify("Na Steam: botão direito no jogo › Gerir › Desinstalar.", "info")
    elif "heroic" in low:
        notify("Desinstale pelo Heroic Games Launcher.", "info")
    elif "lutris" in low:
        notify("Desinstale pelo Lutris (botão direito › Desinstalar).", "info")
    elif "flatpak" in low or "/.var/app/" in low:
        notify("Use a página 'Instalar aplicações' ou 'flatpak uninstall' para remover a app.", "info")
    else:
        notify("Remova este programa pelo gestor de pacotes da sua distribuição.", "info")


class DiskPage(Page):
    def __init__(self):
        super().__init__("Espaço em disco",
                         "Analisa o disco e diz o que é seguro apagar (caches, jogos…) e o que é do sistema e não se deve tocar")
        self.result: diskscan.ScanResult | None = None
        self.task: Task | None = None
        self.dup_task: Task | None = None
        self.cancel = False
        self._scanned_once = False

        self.drives = QGridLayout()
        self.drives.setSpacing(12)
        self.add(self.drives)

        tabs = QTabWidget()
        tabs.addTab(self._build_scan(), "Analisar pasta / disco")
        tabs.addTab(self._build_clean(), "Limpeza rápida")
        self.tabs = tabs
        self.add(tabs, 1)
        self._cleaned_once = False

    # ------------------------------------------------------------------ discos
    def _drives(self):
        while self.drives.count():
            w = self.drives.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        seen = set()
        col = 0
        for p in psutil.disk_partitions(all=False):
            if p.device in seen or p.fstype in ("squashfs", "tmpfs", "overlay") or "/snap/" in p.mountpoint \
                    or p.mountpoint.startswith("/boot"):
                continue
            seen.add(p.device)
            try:
                u = psutil.disk_usage(p.mountpoint)
            except OSError:
                continue
            c = Card()
            c.lay.setSpacing(6)
            head = QHBoxLayout()
            head.addWidget(label(f"<b>{p.mountpoint}</b>  <span style='opacity:.6'>{p.fstype}</span>"), 1)
            b_an = QPushButton("Analisar")
            b_an.setToolTip(f"Analisar {p.mountpoint}")
            b_an.clicked.connect(lambda _=False, m=p.mountpoint: self.scan(m))
            head.addWidget(b_an)
            c.add(head)
            b = Bar()
            b.set(u.percent)
            c.add(b)
            c.add(label(f"{human_bytes(u.free)} livres de {human_bytes(u.total)} ({u.percent:.0f}% usado)", "Muted"))
            self.drives.addWidget(c, col // 4, col % 4)
            col += 1

    # ------------------------------------------------------------------ análise
    def _build_scan(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        v.setSpacing(12)
        ctl = Card()
        row = QHBoxLayout()
        self.root = QComboBox()
        self.root.setEditable(True)
        self.root.addItems(diskscan.default_roots())
        self.root.setMinimumWidth(200)
        browse = QPushButton("Escolher pasta…")
        browse.clicked.connect(self._browse)
        self.btn_scan = QPushButton("Analisar")
        self.btn_scan.setObjectName("Primary")
        self.btn_scan.clicked.connect(lambda: self.scan())
        row.addWidget(self.root, 1)
        row.addWidget(browse)
        row.addWidget(self.btn_scan)
        ctl.add(row)
        self.scan_status = label("O disco do sistema é analisado automaticamente ao abrir esta página.", "Muted", wrap=True)
        ctl.add(self.scan_status)
        v.addWidget(ctl)

        # ---- resumo por nível de segurança
        self.sum_card = Card("O que pode apagar", "Cada pasta é classificada: verde e azul podem sair, "
                                                  "amarelo são coisas suas (veja antes), vermelho é o sistema.")
        self.sum_head = label("", "CardTitle", wrap=True)
        self.sum_card.add(self.sum_head)
        self.lvl_bar = LevelBar()
        self.sum_card.add(self.lvl_bar)
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.lvl_lbls: dict[str, object] = {}
        desc = {ds.SAFE: "caches, temporários, lixo, logs, dependências",
                ds.APP: "jogos e programas — desinstale os que não usa",
                ds.REVIEW: "documentos, fotos, transferências, definições",
                ds.SYSTEM: "Windows / sistema Linux — não tocar",
                ds.UNKNOWN: "não classificado"}
        for i, lv in enumerate(ds.LEVEL_ORDER):
            lb = label("", wrap=True)
            lb.setToolTip(desc[lv])
            self.lvl_lbls[lv] = (lb, desc[lv])
            grid.addWidget(lb, 0, i)
        self.sum_card.add(grid)
        self.sum_card.setVisible(False)
        v.addWidget(self.sum_card)

        res = Card()
        self.rtabs = QTabWidget()
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Pasta", "Tamanho", "%", "Segurança", "O que é / o que fazer"])
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 55)
        self.tree.setColumnWidth(3, 160)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemExpanded.connect(self._expand)
        self.tree.itemDoubleClicked.connect(lambda it, _c: _open_any(it.data(0, R_PATH)))
        self.tree.customContextMenuRequested.connect(lambda pos: self._menu(self.tree, pos))
        self.t_sugg = FileTable()
        self.t_files = FileTable()
        self.t_dups = FileTable()
        for t in (self.t_sugg, self.t_files, self.t_dups):
            t.customContextMenuRequested.connect(lambda pos, t=t: self._menu(t, pos))
        self.t_dirs = _table(["Pasta", "Tamanho", "Ficheiros", "Segurança", "O que é / o que fazer"], 0)
        self.t_dirs.setColumnWidth(1, 100)
        self.t_dirs.setColumnWidth(2, 90)
        self.t_dirs.setColumnWidth(3, 160)
        self.t_dirs.setColumnWidth(4, 380)
        self.t_dirs.setSortingEnabled(True)
        self.t_dirs.setContextMenuPolicy(Qt.CustomContextMenu)
        self.t_dirs.customContextMenuRequested.connect(lambda pos: self._menu(self.t_dirs, pos))
        self.t_dirs.doubleClicked.connect(lambda idx: open_path(self.t_dirs.item(idx.row(), 0).text()))
        self.t_types = _table(["Tipo", "Tamanho", "Ficheiros", ""], 3)
        self.rtabs.addTab(self.t_sugg, "Pode ser apagado")
        self.rtabs.addTab(self.tree, "Explorar por pasta")
        self.rtabs.addTab(self.t_files, "Maiores ficheiros")
        self.rtabs.addTab(self.t_dirs, "Maiores pastas")
        self.rtabs.addTab(self.t_dups, "Duplicados")
        self.rtabs.addTab(self.t_types, "Por tipo")
        self.rtabs.currentChanged.connect(lambda _i: self._update_actions())
        res.add(self.rtabs, 1)
        acts = QHBoxLayout()
        self.sel_lbl = label("Marque as caixas (ou selecione linhas) e escolha uma ação. Botão direito para mais opções.",
                             "Muted")
        self.b_mark = QPushButton("Marcar os seguros")
        self.b_mark.setToolTip("Marca só o que está a verde (caches, temporários, dependências) — jogos e ficheiros pessoais ficam de fora")
        self.b_mark.clicked.connect(self._mark_safe)
        self.b_uninst = QPushButton("Desinstalar…")
        self.b_uninst.setToolTip("Para jogos e programas: abre o desinstalador certo (Steam, Definições…)")
        self.b_uninst.clicked.connect(self._uninstall_sel)
        b_open = QPushButton("Abrir pasta")
        b_trash = QPushButton("Mover para o Lixo" if not IS_WIN else "Mover para a Reciclagem")
        b_del = QPushButton("Apagar definitivamente")
        b_del.setObjectName("Danger")
        b_open.clicked.connect(self._open_sel)
        b_trash.clicked.connect(lambda: self._delete(True))
        b_del.clicked.connect(lambda: self._delete(False))
        acts.addStretch(1)
        for b in (self.b_mark, self.b_uninst, b_open, b_trash, b_del):
            acts.addWidget(b)
        self.sel_lbl.setWordWrap(True)
        res.add(self.sel_lbl)
        res.add(acts)
        v.addWidget(res, 1)
        w.setMinimumHeight(640)
        return w

    def _update_actions(self):
        self.b_mark.setVisible(self.rtabs.currentWidget() is self.t_sugg)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Escolher pasta", self.root.currentText())
        if d:
            self.root.setEditText(d)

    def scan(self, root: str | None = None):
        if self.task:
            self.cancel = True
            return
        if self.dup_task:
            self.cancel = True  # interrompe a procura de duplicados anterior
        if root:
            self.root.setEditText(root)
        root = self.root.currentText().strip()
        if not os.path.isdir(root):
            notify("Pasta inválida.", "bad")
            return
        self.cancel = False
        self.btn_scan.setText("Cancelar")
        self.scan_status.setText(f"A analisar {root}…")

        def progress(n, size, cur):
            if n < 0:
                t.progress.emit(cur)
            else:
                t.progress.emit(f"{n:,} ficheiros · {human_bytes(size)} · {cur}".replace(",", "."))

        t = Task(diskscan.scan, root, progress, lambda: self.cancel, find_duplicates=False, collect_duplicates=True)
        t.progress.connect(lambda s: self.scan_status.setText(s if len(s) < 160 else s[:80] + "…" + s[-70:]))
        t.done.connect(self._scanned)
        t.failed.connect(lambda m: (self._scan_reset(), notify(m, "bad")))
        self.task = t.start()

    def _scan_reset(self):
        self.task = None
        self.btn_scan.setText("Analisar")

    def _status_text(self, r: diskscan.ScanResult, dup_note: str = "") -> str:
        dup_waste = sum(g[0].size * (len(g) - 1) for g in r.duplicates)
        txt = (f"{'Cancelado — resultados parciais. ' if r.cancelled else ''}"
               f"<b>{r.root}</b>: {human_bytes(r.total)} em {r.files:,} ficheiros e {r.dirs:,} pastas "
               f"({r.seconds:.1f} s)").replace(",", ".")
        if r.duplicates:
            txt += f" · duplicados: <b>{human_bytes(dup_waste)}</b> desperdiçados"
        if dup_note:
            txt += f" · {dup_note}"
        if r.errors:
            txt += f" · {r.errors:,} itens sem permissão".replace(",", ".")
        if r.skipped:
            txt += " · não incluído: " + ", ".join(r.skipped[:4]) + ("…" if len(r.skipped) > 4 else "")
        return txt

    def _scanned(self, r: diskscan.ScanResult):
        self._scan_reset()
        self.result = r
        self.scan_status.setText(self._status_text(r, "a procurar duplicados…" if r.dup_candidates else ""))
        self._fill_summary(r)
        self.t_sugg.set_entries(r.recommended)
        self.t_files.set_entries(r.largest)
        self.t_dups.set_entries([])
        self.rtabs.setTabText(0, f"Pode ser apagado ({len(r.recommended)})")
        self.rtabs.setTabText(4, "Duplicados (a procurar…)")
        self._fill_tree(r)
        self._fill_dirs(r)
        self._fill_types(r)
        self.rtabs.setCurrentIndex(0 if r.recommended else 1)
        self._update_actions()
        if r.dup_candidates and not r.cancelled:
            self._start_dups(r)
        else:
            self.rtabs.setTabText(4, "Duplicados")

    def _start_dups(self, r):
        def progress(_n, _size, cur):
            t.progress.emit(cur)
        t = Task(diskscan.find_duplicates, r, lambda: self.cancel, progress)
        t.progress.connect(lambda s: self.rtabs.setTabText(4, "Duplicados (a comparar…)"))

        def done(groups):
            self.dup_task = None
            if self.result is not r:
                return
            dups = [f for g in groups for f in g]
            for f in dups:
                f.level = ds.classify(f.path).level or ds.REVIEW
            self.t_dups.set_entries(dups)
            self.rtabs.setTabText(4, f"Duplicados ({len(groups)} grupos)")
            self.scan_status.setText(self._status_text(r))
        t.done.connect(done)
        t.failed.connect(lambda _m: setattr(self, "dup_task", None))
        self.dup_task = t.start()

    def _fill_summary(self, r: diskscan.ScanResult):
        by = r.by_level
        total = max(sum(by.values()), 1)
        safe_now = sum(f.size for f in r.recommended if f.level == ds.SAFE)
        games = sum(f.size for f in r.recommended if f.level == ds.APP)
        head = f"Pode libertar já <span style='color:{qc('ok').name()}'>{human_bytes(safe_now)}</span> em segurança"
        if games:
            head += (f" · mais <span style='color:{qc('info').name()}'>{human_bytes(games)}</span> "
                     f"em jogos que pode desinstalar")
        self.sum_head.setText(head)
        self.lvl_bar.set([(by.get(lv, 0), ds.LEVELS[lv][1]) for lv in ds.LEVEL_ORDER])
        for lv in ds.LEVEL_ORDER:
            lb, d = self.lvl_lbls[lv]
            n = by.get(lv, 0)
            lb.setVisible(n > 0)
            lb.setText(f"{status_dot(ds.LEVELS[lv][1])} <b>{ds.LEVELS[lv][0] if lv else 'Outros'}</b><br>"
                       f"{human_bytes(n)} <span style='opacity:.6'>({n * 100 / total:.0f}%)</span><br>"
                       f"<span style='opacity:.6'>{d}</span>")
        self.sum_card.setVisible(True)

    # ---- árvore
    def _tree_item(self, path: str, size: int, total: int, v: ds.Verdict, is_dir: bool, has_kids: bool):
        name = os.path.basename(path.rstrip("/\\")) or path
        if v.name:
            name = f"{name}  ·  {v.name}"
        it = QTreeWidgetItem([name if is_dir else f"📄 {name}", human_bytes(size), f"{size * 100 / max(total, 1):.1f}",
                              ds.LEVELS[v.level][0], v.reason])
        it.setData(0, R_PATH, path)
        it.setData(0, R_DIR, is_dir)
        it.setData(0, R_APPID, v.steam_appid)
        it.setData(0, R_LEVEL, v.level)
        it.setToolTip(0, path)
        it.setToolTip(4, v.reason)
        it.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
        it.setTextAlignment(2, Qt.AlignRight | Qt.AlignVCenter)
        _paint_level(it, v.level, 3)
        if has_kids:
            it.addChild(QTreeWidgetItem(["…"]))
        return it

    def _children_items(self, d: str):
        r = self.result
        total = r.sizes.get(r.root, 1)
        out = []
        kids = [(r.sizes[c], c, True) for c in r.children.get(d, ())]
        kids += [(f.size, f.path, False, f) for f in r.big_files.get(d, ())]
        kids.sort(key=lambda x: -x[0])
        for k in kids[:300]:
            size, p, is_dir = k[0], k[1], k[2]
            v = r.verdicts.get(p) if is_dir else ds.Verdict(k[3].level, k[3].suggestion, "", k[3].steam_appid)
            v = v or ds.classify(p)
            has = is_dir and bool(r.children.get(p) or r.big_files.get(p))
            out.append(self._tree_item(p, size, total, v, is_dir, has))
        return out

    def _fill_tree(self, r: diskscan.ScanResult):
        self.tree.clear()
        top = self._tree_item(r.root, r.sizes.get(r.root, r.total), r.sizes.get(r.root, r.total),
                              r.verdicts.get(r.root) or ds.Verdict(), True, False)
        self.tree.addTopLevelItem(top)
        top.addChildren(self._children_items(r.root))
        top.setExpanded(True)

    def _expand(self, it: QTreeWidgetItem):
        if it.childCount() == 1 and it.child(0).data(0, R_PATH) is None and self.result:
            it.takeChild(0)
            it.addChildren(self._children_items(it.data(0, R_PATH)))

    def _fill_dirs(self, r):
        t = self.t_dirs
        t.setSortingEnabled(False)
        t.setRowCount(len(r.folders))
        for i, d in enumerate(r.folders):
            it = QTableWidgetItem(d.path)
            it.setData(R_PATH, d.path)
            it.setData(R_DIR, True)
            it.setData(R_LEVEL, d.level)
            v = r.verdicts.get(d.path)
            it.setData(R_APPID, v.steam_appid if v else "")
            it.setToolTip(d.path)
            t.setItem(i, 0, it)
            t.setItem(i, 1, SizeItem(d.size))
            n = QTableWidgetItem(f"{d.files:,}".replace(",", "."))
            n.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(i, 2, n)
            t.setItem(i, 3, LevelItem(d.level))
            s = QTableWidgetItem(d.suggestion)
            s.setToolTip(d.suggestion)
            t.setItem(i, 4, s)
        t.setSortingEnabled(True)
        t.sortByColumn(1, Qt.DescendingOrder)

    def _fill_types(self, r):
        types = sorted(r.by_type.items(), key=lambda x: -x[1][0])
        self.t_types.setRowCount(len(types))
        for i, (name, (size, count)) in enumerate(types):
            self.t_types.setItem(i, 0, QTableWidgetItem(name))
            self.t_types.setItem(i, 1, SizeItem(size))
            c = QTableWidgetItem(f"{count:,}".replace(",", "."))
            c.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.t_types.setItem(i, 2, c)
            b = Bar(10)
            b.set(size * 100 / max(r.total, 1), "accent")
            holder = QWidget()
            holder.setObjectName("Transparent")
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 0, 8, 0)
            hl.addWidget(b)
            self.t_types.setCellWidget(i, 3, holder)
        self.t_types.setColumnWidth(0, 240)

    # ---- seleção e ações
    def _current_paths(self, w=None):
        """[(item, caminho)] do separador atual (caixas marcadas ou linhas selecionadas)."""
        w = w or self.rtabs.currentWidget()
        if isinstance(w, FileTable):
            return w, w.checked()
        if w is self.t_dirs:
            rows = sorted({ix.row() for ix in w.selectedIndexes()})
            return w, [(w.item(r, 0), w.item(r, 0).data(R_PATH)) for r in rows]
        if w is self.tree:
            return w, [(it, it.data(0, R_PATH)) for it in w.selectedItems() if it.data(0, R_PATH)]
        return None, []

    @staticmethod
    def _meta(item) -> tuple[str, str]:
        """(nível, appid) de uma linha de tabela ou árvore."""
        if isinstance(item, QTreeWidgetItem):
            return item.data(0, R_LEVEL) or "", item.data(0, R_APPID) or ""
        return item.data(R_LEVEL) or "", item.data(R_APPID) or ""

    def _menu(self, w, pos):
        _t, sel = self._current_paths(w)
        if not sel:
            return
        item, path = sel[0]
        level, appid = self._meta(item)
        m = QMenu(self)
        m.addAction("Abrir pasta", lambda: _open_any(path))
        m.addAction("Copiar caminho", lambda: QApplication.clipboard().setText("\n".join(p for _i, p in sel)))
        if level == ds.APP:
            m.addAction("Desinstalar…", lambda: _uninstall(path, appid))
        if level != ds.SYSTEM:
            m.addSeparator()
            m.addAction("Mover para o Lixo" if not IS_WIN else "Mover para a Reciclagem", lambda: self._delete(True, w))
            m.addAction("Apagar definitivamente", lambda: self._delete(False, w))
        m.exec(w.viewport().mapToGlobal(pos))

    def _mark_safe(self):
        n = self.t_sugg.check_level({ds.SAFE})
        tot = sum(self.t_sugg.item(i, 1).data(Qt.UserRole) or 0 for i in range(self.t_sugg.rowCount())
                  if self.t_sugg.item(i, 0).checkState() == Qt.Checked)
        notify(f"{n} itens seguros marcados ({human_bytes(tot)}).", "ok" if n else "warn")

    def _uninstall_sel(self):
        _t, sel = self._current_paths()
        if not sel:
            notify("Selecione um jogo ou programa.", "warn")
            return
        item, path = sel[0]
        level, appid = self._meta(item)
        if level != ds.APP:
            notify("Isto não é um jogo/programa — use 'Mover para o Lixo' se for seguro.", "warn")
            return
        _uninstall(path, appid)

    def _open_sel(self):
        _t, sel = self._current_paths()
        if not sel:
            notify("Selecione um item.", "warn")
            return
        _open_any(sel[0][1])

    def _delete(self, trash: bool, widget=None):
        table, sel = self._current_paths(widget)
        if not sel:
            notify("Marque ou selecione itens primeiro.", "warn")
            return
        # proteção: nunca apagar o que é do sistema
        blocked = [(i, p) for i, p in sel if (self._meta(i)[0] or ds.classify(p).level) == ds.SYSTEM]
        sel = [x for x in sel if x not in blocked]
        if blocked:
            notify(f"{len(blocked)} itens do sistema foram protegidos e não serão apagados "
                   f"(ex.: {_base(blocked[0][1])}).", "bad")
        if not sel:
            return
        sizes = self.result.sizes if self.result else {}
        total = 0
        for _i, p in sel:
            try:
                total += sizes.get(p) or (os.path.getsize(p) if os.path.isfile(p) else 0)
            except OSError:
                pass
        levels = [self._meta(i)[0] for i, _p in sel]
        warn = ""
        if ds.REVIEW in levels:
            warn += "\n\n⚠ Inclui ficheiros pessoais/de aplicações (amarelo) — confirme que não precisa deles."
        games = [p for (i, p) in sel if self._meta(i)[1]]
        if games:
            warn += ("\n\nℹ Para jogos da Steam é melhor 'Desinstalar…' — se apagar a pasta, a Steam continua a "
                     "achar que está instalado.")
        names = "\n".join(os.path.basename(p.rstrip("/\\")) or p for _i, p in sel[:15]) + ("\n…" if len(sel) > 15 else "")
        verb = "Mover para o lixo" if trash else "APAGAR DEFINITIVAMENTE"
        if not confirm(self, verb, f"{verb} {len(sel)} itens ({human_bytes(total)})?\n\n{names}{warn}"
                       + ("" if trash else "\n\nIsto não pode ser desfeito!")):
            return

        def work():
            out = []
            for item, p in sel:
                out.append((item, p, move_to_trash(p) if trash else delete_permanent(p)))
            return out

        def remove_rows(items):
            for item, _p in items:
                if isinstance(item, QTreeWidgetItem):
                    par = item.parent()
                    (par.removeChild(item) if par else None)
                elif table is not None and item.tableWidget() is table:
                    table.removeRow(item.row())

        def done(res):
            ok = [(i, p) for i, p, good in res if good]
            # o que falhou e ainda existe é quase sempre falta de permissão (ficheiros do root/admin)
            stuck = [(i, p) for i, p, good in res if not good and os.path.lexists(p)]
            gone = [(i, p) for i, p, good in res if not good and not os.path.lexists(p)]
            ok += gone
            freed = sum(sizes.get(p, 0) for _i, p in ok)
            remove_rows(ok)
            if ok or not stuck:
                notify(f"{len(ok)} itens {'movidos para o lixo' if trash else 'apagados'}"
                       + (f" ({human_bytes(freed)})" if freed else ""), "ok")
            self._drives()
            if stuck:
                self._delete_elevated(stuck, trash, sizes, remove_rows)
        notify("A apagar…" if not trash else "A mover para o lixo…", "info")
        run_async(work, on_done=done)

    def _delete_elevated(self, stuck, trash, sizes, remove_rows):
        """Itens que falharam por falta de permissão: oferece apagá-los como administrador."""
        names = "\n".join(_base(p) for _i, p in stuck[:10]) + ("\n…" if len(stuck) > 10 else "")
        extra = ("\n\nNota: com permissões de administrador não é possível usar o Lixo — "
                 "serão APAGADOS DEFINITIVAMENTE." if trash else "")
        if IS_WIN and not is_admin():
            if confirm(self, "Precisa de administrador",
                       f"{len(stuck)} itens não foram apagados porque precisam de permissões de administrador:"
                       f"\n\n{names}\n\nReabrir o Nexo como administrador? (depois volte a apagá-los)"):
                if relaunch_as_admin():
                    QApplication.quit()
                else:
                    notify("Não foi possível pedir permissões de administrador.", "bad")
            return
        how = "Será pedida a sua palavra-passe." if not IS_WIN else "O Nexo vai tomar posse dos ficheiros e apagá-los."
        if not confirm(self, "Precisa de permissão",
                       f"{len(stuck)} itens não foram apagados por falta de permissão:\n\n{names}\n\n"
                       f"Apagar como administrador? {how}{extra}\n\nIsto não pode ser desfeito!"):
            notify(f"{len(stuck)} itens não foram apagados (sem permissão).", "warn")
            return
        by_path = {p: i for i, p in stuck}

        def done(res):
            deleted, err = res
            items = [(by_path[p], p) for p in deleted]
            remove_rows(items)
            freed = sum(sizes.get(p, 0) for p in deleted)
            left = len(stuck) - len(deleted)
            if deleted:
                notify(f"{len(deleted)} itens apagados como administrador"
                       + (f" ({human_bytes(freed)})" if freed else "")
                       + (f", {left} continuam lá ({err})" if left else ""), "warn" if left else "ok")
            else:
                notify(f"Não foi possível apagar: {err or 'erro desconhecido'}", "bad")
            self._drives()
        notify("A apagar como administrador…", "info")
        run_async(lambda: delete_as_admin([p for _i, p in stuck]), on_done=done)

    def retheme(self):
        """Volta a aplicar as cores das etiquetas depois de mudar de tema."""
        for t in (self.t_sugg, self.t_files, self.t_dups, self.t_dirs):
            for r in range(t.rowCount()):
                for c in range(t.columnCount()):
                    it = t.item(r, c)
                    if isinstance(it, LevelItem):
                        _paint_level(it, it.level)
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            it = stack.pop()
            if it.data(0, R_PATH) is not None:
                _paint_level(it, it.data(0, R_LEVEL) or "", 3)
            stack += [it.child(i) for i in range(it.childCount())]
        for i, c in enumerate(self.cats):
            sf = self.t_clean.item(i, 2)
            if sf is not None:
                sf.setForeground(QBrush(qc("warn" if c.caution else "ok")))
        if self.result is not None:
            self._fill_summary(self.result)
        self._drives()

    def on_show(self):
        self._drives()
        if not self._cleaned_once:
            self._cleaned_once = True
            self.calc()
        if not self._scanned_once:
            self._scanned_once = True
            self.scan(diskscan.system_root())

    # ------------------------------------------------------------------ limpeza
    def _build_clean(self):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 12, 0, 0)
        card = Card("Ficheiros dispensáveis",
                    "Caches, temporários e pacotes antigos que o sistema e as apps voltam a criar quando precisam. "
                    "Feche os navegadores antes de limpar a cache deles.")
        self.btn_calc = QPushButton("Recalcular")
        self.btn_clean = QPushButton("Limpar marcadas")
        self.btn_clean.setObjectName("Primary")
        card.head.addWidget(self.btn_calc)
        card.head.addWidget(self.btn_clean)
        self.btn_calc.clicked.connect(self.calc)
        self.btn_clean.clicked.connect(self.clean)
        self.cats = cleanup.categories()
        self.t_clean = _table(["Categoria", "Descrição", "Segurança", "Tamanho", ""], 1)
        self.t_clean.setColumnWidth(0, 300)
        self.t_clean.setColumnWidth(2, 130)
        self.t_clean.setColumnWidth(3, 100)
        self.t_clean.setColumnWidth(4, 70)
        self.t_clean.setRowCount(len(self.cats))
        self.t_clean.setWordWrap(True)
        for i, c in enumerate(self.cats):
            it = QTableWidgetItem(c.name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if c.recommended else Qt.Unchecked)
            self.t_clean.setItem(i, 0, it)
            d = QTableWidgetItem(c.desc)
            d.setToolTip(c.desc)
            self.t_clean.setItem(i, 1, d)
            sf = QTableWidgetItem("⚠ Atenção" if c.caution else "✔ Seguro")
            sf.setForeground(QBrush(qc("warn" if c.caution else "ok")))
            sf.setToolTip(c.note)
            d.setToolTip(f"{c.desc}\n\n{c.note}")
            self.t_clean.setItem(i, 2, sf)
            self.t_clean.setItem(i, 3, SizeItem(-1))
            self.t_clean.setItem(i, 4, QTableWidgetItem("admin" if c.needs_admin else ""))
        self.t_clean.itemChanged.connect(lambda _i: self._total())
        self.t_clean.currentCellChanged.connect(self._clean_note)
        card.add(self.t_clean, 1)
        self.clean_note = label("Selecione uma linha para ver o que perde ao limpar. ✔ Seguro = não perde nada "
                                "importante · ⚠ Atenção = seguro, mas há uma consequência a saber.", "Muted", wrap=True)
        card.add(self.clean_note)
        self.clean_total = label("", "CardTitle")
        card.add(self.clean_total)
        v.addWidget(card, 1)
        w.setMinimumHeight(560)
        return w

    def _clean_note(self, row, *_a):
        if 0 <= row < len(self.cats):
            c = self.cats[row]
            color = qc("warn" if c.caution else "ok").name()
            self.clean_note.setText(f"<b>{c.name}</b> — <span style='color:{color}'>{c.note}</span>")

    def calc(self):
        self.btn_calc.setEnabled(False)

        def work():
            for i, c in enumerate(self.cats):
                c.size = cleanup.compute_size(c)
                t.progress.emit(i)
        t = Task(work)
        t.progress.connect(self._size_row)
        t.done.connect(lambda _r: (self.btn_calc.setEnabled(True), self._total()))
        t.failed.connect(lambda m: (self.btn_calc.setEnabled(True), notify(m, "bad")))
        t.start()

    def _size_row(self, i):
        self.t_clean.setItem(i, 3, SizeItem(self.cats[i].size))
        self._total()

    def _total(self):
        tot = sum(max(c.size, 0) for i, c in enumerate(self.cats)
                  if self.t_clean.item(i, 0) and self.t_clean.item(i, 0).checkState() == Qt.Checked)
        self.clean_total.setText(f"Marcado para limpar: {human_bytes(tot)}")

    def clean(self):
        sel = [c for i, c in enumerate(self.cats) if self.t_clean.item(i, 0).checkState() == Qt.Checked]
        if not sel:
            notify("Nada marcado.", "warn")
            return
        if not confirm(self, "Limpar", "Limpar estas categorias?\n\n" + "\n".join(f"• {c.name}" for c in sel)):
            return
        self.btn_clean.setEnabled(False)

        def work():
            out = []
            for c in sel:
                before = c.size if c.size >= 0 else cleanup.compute_size(c)
                ok, msg = cleanup.clean(c)
                after = cleanup.compute_size(c) if ok else before
                out.append((c.name, ok, msg, max(0, before - max(after, 0)) if before >= 0 else 0))
            return out

        def done(res):
            self.btn_clean.setEnabled(True)
            bad = [r for r in res if not r[1]]
            freed = sum(r[3] for r in res)
            if len(res) > len(bad):
                from ...core import changes
                changes.mark("limpeza", f"Limpeza: {', '.join(r[0] for r in res if r[1])}")
            notify(f"Limpeza concluída: {len(res) - len(bad)} categorias"
                   + (f" · libertados {human_bytes(freed)}" if freed else "")
                   + (f" · falharam: {', '.join(r[0] for r in bad)}" if bad else ""), "warn" if bad else "ok")
            self._drives()
            self.calc()
        run_async(work, on_done=done)


