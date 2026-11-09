"""Galeria do wallhaven.cc: pesquisar, ver miniaturas e aplicar como fundo do Nexo."""
from __future__ import annotations

import random
import string
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog, QHBoxLayout, QLineEdit, QListView,
                               QListWidget, QListWidgetItem, QPushButton, QVBoxLayout)

from ..core import wallhaven as wh
from ..core.network import friendly_error
from ..core.util import get_setting, human_bytes, set_setting
from .widgets import Task, label

THUMB = QSize(300, 200)


def screen_min_res() -> str:
    """Resolução mínima = a do ecrã principal (limitada a 4K)."""
    scr = QApplication.primaryScreen()
    if not scr:
        return "1920x1080"
    g = scr.size() * scr.devicePixelRatio()
    return f"{max(1280, min(g.width(), 3840))}x{max(720, min(g.height(), 2160))}"


class WallhavenDialog(QDialog):
    def __init__(self, parent=None, on_pick=None, query: str | None = None, category: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Fundos do Wallhaven")
        self.resize(1120, 760)
        self.on_pick = on_pick
        self.items: list[dict] = []
        self.page = 1
        self.last_page = 1
        self.gen = 0          # invalida miniaturas de pesquisas anteriores
        self.busy = False
        self.loading = False  # há uma página a caminho
        self.seen: set[str] = set()
        self.seed = ""         # mantém a ordem 'aleatória' igual entre páginas (sem repetidos)

        v = QVBoxLayout(self)
        v.setContentsMargins(18, 16, 18, 16)
        v.setSpacing(10)
        top = QHBoxLayout()
        self.q = QLineEdit()
        self.q.setPlaceholderText("Pesquisar (em inglês funciona melhor) — vazio mostra os mais populares")
        self.q.setText(query if query is not None else get_setting("wh_query", "anime scenery"))
        self.cat = QComboBox()
        self.cat.addItems(wh.CATEGORIES)
        self.cat.setCurrentText(category or get_setting("wh_category", "Anime"))
        self.sort = QComboBox()
        self.sort.addItems(wh.SORTS)
        self.uw = QCheckBox("Ultrawide")
        self.uw.setToolTip("Só fundos 21:9 / 32:9")
        self.min_res = screen_min_res()
        w_, h_ = (int(x) for x in self.min_res.split("x"))
        self.uw.setChecked(w_ / max(1, h_) > 2.0)
        self.btn_search = QPushButton("Pesquisar")
        self.btn_search.setObjectName("Primary")
        top.addWidget(self.q, 1)
        top.addWidget(self.cat)
        top.addWidget(self.sort)
        top.addWidget(self.uw)
        top.addWidget(self.btn_search)
        v.addLayout(top)

        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)
        v.addLayout(self.chips)
        self._fill_chips()

        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setIconSize(THUMB)
        self.grid.setGridSize(QSize(THUMB.width() + 16, THUMB.height() + 36))
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setUniformItemSizes(True)
        self.grid.setSelectionMode(QAbstractItemView.SingleSelection)
        self.grid.setSpacing(6)
        # deslizar suave e carregar a página seguinte ao chegar perto do fim
        self.grid.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.grid.verticalScrollBar().setSingleStep(40)
        self.grid.verticalScrollBar().valueChanged.connect(self._maybe_more)
        v.addWidget(self.grid, 1)

        bottom = QHBoxLayout()
        self.status = label("", "Muted", wrap=True)
        self.btn_more = QPushButton("Carregar mais")
        self.btn_open = QPushButton("Ver no site")
        self.btn_use = QPushButton("Usar como fundo")
        self.btn_use.setObjectName("Primary")
        bottom.addWidget(self.status, 1)
        bottom.addWidget(self.btn_more)
        bottom.addWidget(self.btn_open)
        bottom.addWidget(self.btn_use)
        v.addLayout(bottom)
        v.addWidget(label("Imagens de wallhaven.cc (só conteúdo SFW). Pertencem aos respetivos autores — "
                          "uso pessoal como fundo. Duplo clique para aplicar.", "Muted", wrap=True))

        self.btn_search.clicked.connect(self.search)
        self.q.returnPressed.connect(self.search)
        self.sort.currentIndexChanged.connect(lambda _i: self.search())
        self.cat.currentIndexChanged.connect(lambda _i: (self._fill_chips(), self.search()))
        self.uw.toggled.connect(lambda _c: self.search())
        self.btn_more.clicked.connect(self.more)
        self.btn_use.clicked.connect(self.use)
        self.btn_open.clicked.connect(self.open_site)
        self.grid.itemDoubleClicked.connect(lambda _i: self.use())
        self.grid.itemSelectionChanged.connect(self._sel)
        self._sel()
        self.search()

    # ------------------------------------------------------------------
    def _fill_chips(self):
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        sugg = wh.SUGGESTIONS["Anime" if self.cat.currentText() == "Anime" else "Geral"]
        for s in sugg:
            b = QPushButton(s)
            b.setObjectName("Chip")
            b.clicked.connect(lambda _c, s=s: (self.q.setText(s), self.search()))
            self.chips.addWidget(b)
        self.chips.addStretch(1)

    def _sel(self):
        on = bool(self.grid.selectedItems()) and not self.busy
        self.btn_use.setEnabled(on)
        self.btn_open.setEnabled(bool(self.grid.selectedItems()))

    def search(self):
        self.gen += 1
        self.page = 1
        self.last_page = 1
        self.loading = False
        self.items.clear()
        self.seen.clear()
        self.seed = "".join(random.choices(string.ascii_letters + string.digits, k=6))
        self.grid.clear()
        self._fetch()

    def more(self):
        if self.page < self.last_page and not self.loading:
            self.page += 1
            self._fetch()

    def _maybe_more(self, *_a):
        """Carrega a página seguinte quando faltam menos de ~2 linhas para o fim (ou se a lista não enche a janela)."""
        if self.loading or self.page >= self.last_page or not self.items:
            return
        sb = self.grid.verticalScrollBar()
        if sb.maximum() - sb.value() <= THUMB.height() * 2:
            self.more()

    def _offline(self) -> bool:
        from .netmonitor import monitor, require_online
        st = monitor().status
        if require_online("O Wallhaven"):
            return False
        self.status.setText(f"Sem internet ({st.label.lower()}) — {st.detail}")
        return True

    def _fetch(self):
        if self._offline():
            self.btn_more.setEnabled(True)
            if self.page > 1:
                self.page -= 1
            return
        q = self.q.text().strip()
        sorting = wh.SORTS[self.sort.currentText()]
        cats = wh.CATEGORIES[self.cat.currentText()]
        uw, min_res = self.uw.isChecked(), self.min_res
        set_setting("wh_query", q)
        set_setting("wh_category", self.cat.currentText())
        gen, page, seed = self.gen, self.page, self.seed
        self.loading = True
        self.status.setText("A pesquisar…" if page == 1 else f"{len(self.items)} resultados — a carregar mais…")
        self.btn_more.setEnabled(False)
        holder: dict = {}

        def work():
            items, last = wh.search(q, sorting, page, min_res, cats, uw, seed=seed)
            holder["t"].progress.emit(("list", items, last))

            def one(it):
                try:
                    holder["t"].progress.emit(("thumb", it["id"], wh.thumbnail(it["thumb"])))
                except Exception:  # noqa: BLE001
                    pass
            with ThreadPoolExecutor(8) as ex:
                list(ex.map(one, items))
            return len(items)

        def progress(ev):
            if gen != self.gen:
                return
            if ev[0] == "list":
                _k, items, last = ev
                self.last_page = last
                self.loading = False
                items = [it for it in items if it["id"] not in self.seen]
                self.seen.update(it["id"] for it in items)
                for it in items:
                    li = QListWidgetItem(f"{it['res']} · {human_bytes(it['size'])}")
                    li.setData(Qt.UserRole, it)
                    li.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
                    li.setSizeHint(QSize(THUMB.width() + 12, THUMB.height() + 30))
                    self.grid.addItem(li)
                self.items += items
                end = " — fim dos resultados" if self.items and self.page >= self.last_page else ""
                self.status.setText(f"{len(self.items)} resultados{end}" + (" — sem resultados, tente outra pesquisa."
                                                                             if not self.items else ""))
                self.btn_more.setEnabled(self.page < self.last_page)
                # se a página não encheu a janela, pede logo a seguinte (depois de o layout assentar)
                QTimer.singleShot(250, lambda g=gen: g == self.gen and self._maybe_more())
            else:
                _k, iid, data = ev
                img = QImage.fromData(data)
                if img.isNull():
                    return
                pm = QPixmap.fromImage(img.scaled(THUMB, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                                       .copy(0, 0, THUMB.width(), THUMB.height()))
                for i in range(self.grid.count()):
                    li = self.grid.item(i)
                    if li.data(Qt.UserRole)["id"] == iid:
                        li.setIcon(QIcon(pm))
                        break

        def fail(msg):
            if gen == self.gen:
                self.loading = False
                if self.page > 1:
                    self.page -= 1   # 'Carregar mais' volta a tentar a mesma página
                self.status.setText(f"Não foi possível ligar ao wallhaven.cc: {friendly_error(msg)}")
                self.btn_more.setEnabled(True)

        t = Task(work)
        holder["t"] = t
        t.progress.connect(progress)
        t.failed.connect(fail)
        t.start()

    def _current(self) -> dict | None:
        sel = self.grid.selectedItems()
        return sel[0].data(Qt.UserRole) if sel else None

    def open_site(self):
        it = self._current()
        if it:
            QDesktopServices.openUrl(QUrl(it["url"]))

    def use(self):
        it = self._current()
        if not it or self.busy or self._offline():
            return
        self.busy = True
        self._sel()
        self.status.setText(f"A descarregar {it['res']} ({human_bytes(it['size'])})…")

        def done(path):
            self.busy = False
            self._sel()
            self.status.setText("Fundo aplicado.")
            if self.on_pick:
                self.on_pick(path)

        def fail(msg):
            self.busy = False
            self._sel()
            self.status.setText(f"Falhou a descarga: {friendly_error(msg)}")
        t = Task(wh.download, it)
        t.done.connect(done)
        t.failed.connect(fail)
        t.start()
