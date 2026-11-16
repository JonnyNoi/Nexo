"""Peças da página Espaço em disco: células ordenáveis por tamanho/nível, barra por nível de segurança,
tabela de ficheiros com caixas e operações (lixo, apagar, desinstalar jogos/programas)."""
from __future__ import annotations

import os
import shutil
import time

from PySide6.QtCore import QRectF, Qt, QUrl
from PySide6.QtGui import QBrush, QDesktopServices, QFont, QPainter
from PySide6.QtWidgets import (QHeaderView, QTableWidget, QTableWidgetItem, QWidget)

from ..core import disksafety as ds
from ..core.util import IS_WIN, human_bytes, open_path
from .theme import qc
from .widgets import notify

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
