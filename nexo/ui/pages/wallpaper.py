"""Página para mudar o fundo do ambiente de trabalho do sistema (Windows e Linux)."""
from __future__ import annotations

import os

from PySide6.QtCore import QRectF, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QImageReader, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QComboBox, QFileDialog, QGridLayout, QLabel, QMenu, QPushButton, QSizePolicy, QVBoxLayout,
                               QWidget)

from ...core import desktopwp as dw
from ...core import wallhaven as wh
from ...core.util import get_setting, set_setting
from .. import theme
from ..widgets import Card, Page, SettingRow, Toggle, hbox, label, notify, run_async, separator


def _thumb(path: str, w: int, h: int):
    r = QImageReader(path)
    r.setAutoTransform(True)
    sz = r.size()
    if sz.isValid() and sz.width() and sz.height():
        scale = max(w / sz.width(), h / sz.height())
        r.setScaledSize(QSize(max(1, int(sz.width() * scale)), max(1, int(sz.height() * scale))))
    img = r.read()
    if img.isNull():
        return None
    return img.copy((img.width() - w) // 2, (img.height() - h) // 2, w, h)


TW, TH = 208, 117   # tamanho das miniaturas em "Os meus fundos"


class Thumb(QWidget):
    """Miniatura clicável de um fundo guardado (cantos arredondados, contorno no fundo atual)."""
    clicked = Signal(str)
    menu = Signal(str, object)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.pix: QPixmap | None = None
        self.current = False
        self._hover = False
        self.setFixedSize(TW + 8, TH + 8)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(os.path.basename(path))
        self.setAttribute(Qt.WA_Hover)

    def set_pixmap(self, pix: QPixmap):
        self.pix = pix
        self.update()

    def set_current(self, on: bool):
        if on != self.current:
            self.current = on
            self.update()

    def enterEvent(self, e):
        self._hover = True
        self.update()

    def leaveEvent(self, e):
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.rect().contains(e.position().toPoint()):
            self.clicked.emit(self.path)

    def contextMenuEvent(self, e):
        self.menu.emit(self.path, e.globalPos())

    def paintEvent(self, _e):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(4, 4, TW, TH)
        path = QPainterPath()
        path.addRoundedRect(r, 10, 10)
        p.setClipPath(path)
        if self.pix is not None:
            p.drawPixmap(r.toRect(), self.pix)
        else:
            p.fillRect(r, QColor(c["surface2"]))
            p.setPen(QColor(c["muted"]))
            p.drawText(r, Qt.AlignCenter, "a carregar…")
        if self._hover and not self.current:
            p.fillRect(r, QColor(255, 255, 255, 28))
        p.setClipping(False)
        if self.current or self._hover:
            p.setPen(QPen(QColor(c["accent"] if self.current else c["border2"]), 3 if self.current else 2))
            p.drawRoundedRect(r.adjusted(-1.5, -1.5, 1.5, 1.5), 11, 11)
        if self.current:   # selo "Atual" no canto
            badge = QRectF(r.left() + 8, r.top() + 8, 52, 20)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(badge, 10, 10)
            p.setPen(QColor("#ffffff"))
            f = p.font()
            f.setBold(True)
            f.setPixelSize(11)
            p.setFont(f)
            p.drawText(badge, Qt.AlignCenter, "Atual")
        p.end()


class ThumbGrid(QWidget):
    """Grelha que reorganiza as miniaturas em colunas conforme a largura disponível."""

    def __init__(self):
        super().__init__()
        self.setObjectName("Transparent")
        # a largura mínima não depende do número de colunas (a grelha adapta-se à janela)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Minimum)
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.grid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.thumbs: list[Thumb] = []
        self._cols = 0

    def set_thumbs(self, thumbs: list[Thumb]):
        for t in self.thumbs:
            self.grid.removeWidget(t)
            t.deleteLater()
        self.thumbs = thumbs
        self._cols = 0
        self._relayout()

    def _relayout(self):
        cols = max(1, (self.width() + self.grid.spacing()) // (TW + 8 + self.grid.spacing()))
        if cols == self._cols:
            return
        self._cols = cols
        for t in self.thumbs:
            self.grid.removeWidget(t)
        for i, t in enumerate(self.thumbs):
            self.grid.addWidget(t, i // cols, i % cols)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._relayout()


class WallpaperPage(Page):
    def __init__(self):
        super().__init__("Fundo do ambiente de trabalho",
                         f"Mude o wallpaper do seu {dw.desktop_name()} — imagem sua ou da galeria do Wallhaven")

        # ---------------------------------------------------------------- fundo atual
        cur = Card("Fundo atual", icon="sun")
        self.preview = QLabel()
        self.preview.setFixedSize(384, 216)
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setObjectName("Muted")
        self.cur_lbl = label("", "Muted", wrap=True)
        self.cur_lbl.setTextInteractionFlags(Qt.TextSelectableByMouse)
        b_file = QPushButton("Escolher imagem…")
        b_file.clicked.connect(self._choose_file)
        b_wh = QPushButton("Procurar no Wallhaven…")
        b_wh.setObjectName("Primary")
        b_wh.clicked.connect(self._wallhaven)
        b_rand = QPushButton("Aleatório do Wallhaven")
        b_rand.setToolTip("Usa a última pesquisa e categoria da galeria")
        b_rand.clicked.connect(lambda: self.random_wallhaven(True))
        self.style = QComboBox()
        for key, v in dw.STYLES.items():
            self.style.addItem(v[0], key)
        self.style.setCurrentIndex(max(0, self.style.findData(get_setting("desktop_wp_style", "fill"))))
        self.style.currentIndexChanged.connect(self._style_changed)
        self.tg_lock = Toggle(bool(get_setting("desktop_wp_lock", False)))
        self.tg_lock.clicked.connect(lambda on: set_setting("desktop_wp_lock", bool(on)))

        right = QWidget()
        right.setObjectName("Transparent")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        rv.addWidget(label(f"<b>Ambiente:</b> {dw.desktop_name()}"))
        rv.addWidget(self.cur_lbl)
        rv.addLayout(hbox(label("Ajuste:"), self.style, None))
        rv.addLayout(hbox(label("Também no ecrã de bloqueio"), None, self.tg_lock))
        rv.addStretch(1)
        rv.addLayout(hbox(b_file, b_rand, b_wh, None))
        row = hbox(self.preview)
        row.addWidget(right, 1)
        cur.add(row)
        self.add(cur)

        # ---------------------------------------------------------------- os meus fundos
        mine = Card("Os meus fundos", "Clique numa imagem para a pôr no ambiente de trabalho · botão direito para mais")
        self.mine_lbl = label("", "Muted")
        mine.add(self.mine_lbl)
        self.mine = ThumbGrid()
        self._files: list[str] = []
        self._current = ""
        mine.add(self.mine)
        self.add(mine)

        # ---------------------------------------------------------------- troca automática
        auto = Card("Troca automática", icon="refresh")
        self.auto_cb = QComboBox()
        for txt, mins in (("Desligada", 0), ("A cada 15 min", 15), ("A cada hora", 60), ("A cada 6 horas", 360),
                          ("Uma vez por dia", 1440)):
            self.auto_cb.addItem(txt, mins)
        self.auto_cb.setCurrentIndex(max(0, self.auto_cb.findData(int(get_setting("wp_auto") or 0))))
        self.auto_src = QComboBox()
        self.auto_src.addItem("dos meus fundos", "local")
        self.auto_src.addItem("aleatório do Wallhaven", "wallhaven")
        self.auto_src.setCurrentIndex(max(0, self.auto_src.findData(get_setting("wp_auto_source"))))
        self.auto_cb.currentIndexChanged.connect(lambda _i: set_setting("wp_auto", self.auto_cb.currentData()))
        self.auto_src.currentIndexChanged.connect(lambda _i: set_setting("wp_auto_source", self.auto_src.currentData()))
        b_now = QPushButton("Trocar agora")
        b_now.clicked.connect(lambda: self.window()._auto_wallpaper(force=True))
        box = QWidget()
        box.setObjectName("Transparent")
        box.setLayout(hbox(self.auto_cb, self.auto_src, b_now))
        auto.add(SettingRow("Trocar o fundo automaticamente",
                            "Funciona enquanto o Nexo estiver aberto (também minimizado na bandeja).", box))
        auto.add(separator())
        auto.add(label("As imagens do Wallhaven pertencem aos seus autores; o Nexo só as descarrega a seu pedido, "
                       "para uso pessoal, e guarda a ligação para a página original.", "Muted", wrap=True))
        self.add(auto)

    # ------------------------------------------------------------------
    def on_show(self):
        self._refresh_current()
        self._load_mine()

    def _refresh_current(self):
        def work():
            p = dw.current_wallpaper()
            return p, (_thumb(p, 384, 216) if p and p.lower().endswith(dw.IMAGE_EXT) else None)

        def done(res):
            p, img = res
            if img is not None:
                self.preview.setPixmap(QPixmap.fromImage(img))
            else:
                self.preview.setText("(sem pré-visualização)")
            self.cur_lbl.setText(p or "Não foi possível ler o fundo atual.")
            self._mark_current(p)
        run_async(work, on_done=done)

    def _load_mine(self):
        files = dw.images()[:120]
        self.mine_lbl.setText(f"{len(files)} imagens guardadas" if files else
                              "Ainda vazio — escolha uma imagem ou procure no Wallhaven.")
        self.mine.setVisible(bool(files))
        if files == self._files:
            self._mark_current(self._current)
            return
        self._files = files
        thumbs = []
        for f in files:
            t = Thumb(f)
            t.clicked.connect(self.apply)
            t.menu.connect(self._menu)
            thumbs.append(t)
        self.mine.set_thumbs(thumbs)
        self._mark_current(self._current)

        def work():
            return [(f, _thumb(f, TW, TH)) for f in files]

        def done(res):
            if files != self._files:   # a lista mudou entretanto
                return
            imgs = dict(res)
            for t in self.mine.thumbs:
                img = imgs.get(t.path)
                if img is not None:
                    t.set_pixmap(QPixmap.fromImage(img))
        run_async(work, on_done=done)

    def _mark_current(self, cur: str):
        self._current = cur or ""
        base = os.path.basename(self._current)
        for t in self.mine.thumbs:
            t.set_current(bool(base) and os.path.basename(t.path) == base)

    def _menu(self, path, global_pos):
        m = QMenu(self)
        m.addAction("Pôr no ambiente de trabalho", lambda: self.apply(path))
        src = wh.source_of(path)
        if src:
            m.addAction("Ver no Wallhaven", lambda: QDesktopServices.openUrl(QUrl(src)))
        m.addAction("Abrir a imagem", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(path)))
        m.addAction("Abrir a pasta", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))))
        m.addSeparator()
        m.addAction("Apagar", lambda: self._delete(path))
        m.exec(global_pos)

    def _delete(self, path):
        try:
            os.remove(path)
        except OSError as e:
            notify(f"Não foi possível apagar: {e}", "bad")
            return
        self._load_mine()

    def _style_changed(self, _i):
        set_setting("desktop_wp_style", self.style.currentData())
        cur = get_setting("desktop_wp")
        if cur and os.path.exists(cur):
            self.apply(cur, quiet=True)

    def apply(self, path: str, quiet: bool = False):
        if not path:
            return
        lock = bool(get_setting("desktop_wp_lock", False))

        def done(res):
            ok, msg = res
            if ok:
                if not quiet:
                    notify("Fundo do ambiente de trabalho alterado." + (f" {msg}" if "bloqueio" in msg else ""),
                           "warn" if "bloqueio" in msg else "ok")
                self._refresh_current()
                self._load_mine()
            else:
                notify(f"Não foi possível mudar o fundo: {msg}", "bad")
        run_async(dw.set_wallpaper, path, self.style.currentData(), lock, on_done=done)

    def _choose_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Escolher imagem", os.path.expanduser("~"),
                                              "Imagens (*.png *.jpg *.jpeg *.webp *.bmp)")
        if path:
            self.apply(path)

    def _wallhaven(self):
        from ..wallhaven_dialog import WallhavenDialog
        WallhavenDialog(self, on_pick=self.apply).exec()

    def random_wallhaven(self, force: bool = False):
        from ..wallhaven_dialog import screen_min_res
        cat = wh.CATEGORIES.get(get_setting("wh_category", "Anime"), "010")
        notify("A procurar um fundo no Wallhaven…", "info")
        run_async(wh.random_from_wallhaven, get_setting("wh_query", "anime scenery"), cat, screen_min_res(),
                  on_done=self.apply,
                  on_fail=lambda m: notify(f"Wallhaven: {m}", "bad"))
