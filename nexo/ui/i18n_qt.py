"""Aplica a tradução (core/i18n.py) à interface Qt sem mudar o código das páginas.

  • textos definidos depois de criar o widget: setText/setToolTip/setPlaceholderText/setWindowTitle,
    addItem/addItems das listas, cabeçalhos das tabelas, títulos de separadores e menus;
  • textos passados no construtor (QLabel("…"), QPushButton("…")): traduzidos quando o widget é
    preparado para aparecer pela primeira vez (evento Polish).

As caixas de escolha mostram o texto traduzido mas `currentText()`/`itemText()` continuam a devolver o
original em português, porque várias páginas usam esse texto como chave (ex.: METRICS["Carga"])."""
from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QAbstractButton, QApplication, QComboBox, QGroupBox, QLabel, QLineEdit, QMenu,
                               QTableWidget, QTabWidget, QTreeWidget, QWidget)

from ..core.i18n import lang, tr

ORIG = Qt.UserRole + 731   # texto original de cada item das caixas de escolha
_installed = False


class _Polish(QObject):
    def eventFilter(self, obj, e):
        if e.type() == QEvent.Polish and isinstance(obj, QWidget) and not obj.property("nexo_tr"):
            obj.setProperty("nexo_tr", True)
            if isinstance(obj, QLabel):
                t = obj.text()
                if t:
                    QLabel_setText(obj, tr(t))
            elif isinstance(obj, QAbstractButton):
                t = obj.text()
                if t:
                    QAbstractButton_setText(obj, tr(t))
            elif isinstance(obj, QGroupBox):
                obj.setTitle(tr(obj.title()))
            tip = obj.toolTip()
            if tip:
                QWidget_setToolTip(obj, tr(tip))
            name = obj.accessibleName()
            if name:
                obj.setAccessibleName(tr(name))
        return False


QLabel_setText = QLabel.setText
QAbstractButton_setText = QAbstractButton.setText
QWidget_setToolTip = QWidget.setToolTip


def install(app: QApplication) -> bool:
    """Liga a tradução (só se o idioma não for o português). Devolve True se ficou ligada."""
    global _installed
    if _installed or lang() == "pt":
        return _installed
    _installed = True

    def wrap1(cls, name):
        orig = getattr(cls, name)

        def f(self, text, *a, **k):
            return orig(self, tr(text) if isinstance(text, str) else text, *a, **k)
        setattr(cls, name, f)

    for cls, name in ((QLabel, "setText"), (QAbstractButton, "setText"), (QWidget, "setToolTip"),
                      (QLineEdit, "setPlaceholderText"), (QWidget, "setWindowTitle"), (QGroupBox, "setTitle"),
                      (QAction, "setText"), (QAction, "setToolTip"), (QMenu, "setTitle")):
        wrap1(cls, name)

    from PySide6.QtWidgets import QMessageBox, QSystemTrayIcon
    tray_msg = QSystemTrayIcon.showMessage
    QSystemTrayIcon.showMessage = lambda self, title, msg, *a: tray_msg(self, title, tr(msg), *a)
    for name in ("question", "information", "warning", "critical"):
        orig = getattr(QMessageBox, name)
        setattr(QMessageBox, name, staticmethod(
            lambda parent, title, text, *a, _o=orig: _o(parent, tr(title), tr(text), *a)))

    # ---- caixas de escolha: mostra traduzido, devolve o original
    add_item, insert_item = QComboBox.addItem, QComboBox.insertItem
    item_text, current_text = QComboBox.itemText, QComboBox.currentText

    def addItem(self, *a):
        # addItem(texto[, dados]) ou addItem(ícone, texto[, dados])
        if a and isinstance(a[0], str):
            add_item(self, tr(a[0]), *a[1:])
            self.setItemData(self.count() - 1, a[0], ORIG)
        elif len(a) >= 2 and isinstance(a[1], str):
            add_item(self, a[0], tr(a[1]), *a[2:])
            self.setItemData(self.count() - 1, a[1], ORIG)
        else:
            add_item(self, *a)

    def addItems(self, texts):
        for t in texts:
            addItem(self, t)

    def insertItem(self, index, *a):
        if a and isinstance(a[0], str):
            insert_item(self, index, tr(a[0]), *a[1:])
            self.setItemData(index, a[0], ORIG)
        else:
            insert_item(self, index, *a)

    def itemText(self, i):
        o = self.itemData(i, ORIG)
        return o if isinstance(o, str) else item_text(self, i)

    def currentText(self):
        if self.isEditable():
            return current_text(self)
        o = self.itemData(self.currentIndex(), ORIG)
        return o if isinstance(o, str) else current_text(self)

    def findText(self, text, flags=Qt.MatchExactly | Qt.MatchCaseSensitive):
        for i in range(self.count()):
            if itemText(self, i) == text:
                return i
        return -1

    QComboBox.addItem, QComboBox.addItems, QComboBox.insertItem = addItem, addItems, insertItem
    QComboBox.itemText, QComboBox.currentText, QComboBox.findText = itemText, currentText, findText

    # ---- cabeçalhos e separadores
    for cls, name in ((QTableWidget, "setHorizontalHeaderLabels"), (QTreeWidget, "setHeaderLabels")):
        orig = getattr(cls, name)
        setattr(cls, name, lambda self, labels, _o=orig: _o(self, [tr(x) for x in labels]))
    add_tab = QTabWidget.addTab

    def addTab(self, w, *a):
        a = list(a)
        if a and isinstance(a[-1], str):
            a[-1] = tr(a[-1])
        return add_tab(self, w, *a)
    QTabWidget.addTab = addTab

    menu_add = QMenu.addAction

    def addAction(self, *a, **k):
        a = list(a)
        for i, x in enumerate(a[:2]):
            if isinstance(x, str):
                a[i] = tr(x)
                break
        return menu_add(self, *a, **k)
    QMenu.addAction = addAction

    f = _Polish(app)
    app.installEventFilter(f)
    app._nexo_tr_filter = f   # mantém a referência
    return True
