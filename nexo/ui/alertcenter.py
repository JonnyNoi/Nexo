"""Centro de alertas (sino no menu lateral): lista dos avisos recentes, por ler e lidos.

Painel por cima do conteúdo, encostado à direita; fecha com Esc ou ao clicar fora."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core import alertlog
from . import theme
from .widgets import icon_badge, label

_ICONS = {"ok": "check", "bad": "alert", "warn": "alert"}


class AlertRow(QFrame):
    def __init__(self, a: alertlog.Alert, on_open):
        super().__init__()
        self.setObjectName("AlertRow")
        self.setProperty("unread", not a.read)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 8, 8, 8)
        h.setSpacing(10)
        kind = a.kind if a.kind in theme.C else "info"
        h.addWidget(icon_badge(_ICONS.get(kind, "info"), 28, 15, kind), 0, Qt.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        msg = label(a.msg, wrap=True)
        if not a.read:
            f = msg.font()
            f.setBold(True)
            msg.setFont(f)
        col.addWidget(msg)
        meta = alertlog.when_text(a.when) + (f"  ·  repetiu {a.count}×" if a.count > 1 else "")
        col.addWidget(label(meta, "Muted"))
        h.addLayout(col, 1)
        if a.page:
            b = QPushButton("Abrir")
            b.setObjectName("Ghost")
            b.setToolTip(f"Abrir a página {a.page}")
            b.setAccessibleName(f"Abrir {a.page}")
            b.clicked.connect(lambda: on_open(a))
            h.addWidget(b, 0, Qt.AlignTop)


class AlertCenter(QWidget):
    """Camada transparente sobre a janela com o painel à direita."""

    def __init__(self, win, parent):
        super().__init__(parent)
        self.win = win
        self.setObjectName("AlertDim")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.panel = QFrame(self)
        self.panel.setObjectName("AlertPanel")
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(16, 16, 16, 12)
        v.setSpacing(10)
        top = QHBoxLayout()
        title = label("Alertas", "CardTitle")
        top.addWidget(title, 1)
        self.b_read = QPushButton("Marcar como lidos")
        self.b_read.setObjectName("Ghost")
        self.b_read.clicked.connect(self._mark_all)
        top.addWidget(self.b_read)
        self.b_clear = QPushButton("Limpar")
        self.b_clear.setObjectName("Ghost")
        self.b_clear.clicked.connect(self._clear)
        top.addWidget(self.b_clear)
        x = QPushButton("✕")
        x.setObjectName("Ghost")
        x.setFixedSize(28, 28)
        x.setToolTip("Fechar (Esc)")
        x.setAccessibleName("Fechar os alertas")
        x.clicked.connect(self.close_center)
        top.addWidget(x)
        v.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.inner = QWidget()
        self.inner.setObjectName("Transparent")
        self.list = QVBoxLayout(self.inner)
        self.list.setContentsMargins(0, 0, 4, 0)
        self.list.setSpacing(6)
        self.scroll.setWidget(self.inner)
        v.addWidget(self.scroll, 1)
        v.addWidget(label("Os alertas ficam guardados aqui (os últimos 200). Configure-os em Definições → Alertas.",
                          "Muted", wrap=True))
        self.hide()

    # ------------------------------------------------------------------
    def open(self):
        c = theme.C
        self.setStyleSheet(
            f"QFrame#AlertPanel {{ background: {c['surface']}; border: 1px solid {c['border2']}; border-radius: 16px; }}"
            f"QFrame#AlertPanel QLabel, QFrame#AlertPanel QWidget#Transparent, QFrame#AlertPanel QScrollArea "
            f"{{ background: transparent; }}"
            f"QFrame#AlertRow {{ background: {c['surface2']}; border: 1px solid {c['border']}; border-radius: 12px; }}"
            f"QFrame#AlertRow[unread=\"true\"] {{ border-left: 3px solid {c['accent']}; }}")
        self.fill()
        self.setGeometry(self.parentWidget().rect())
        self._place()
        self.show()
        self.raise_()
        self.setFocus()

    def fill(self):
        while self.list.count():
            it = self.list.takeAt(0)
            if it.widget() is not None:
                it.widget().hide()
                it.widget().deleteLater()
        alerts = alertlog.all_alerts()
        for a in alerts:
            self.list.addWidget(AlertRow(a, self._open_alert))
        if not alerts:
            empty = label("Sem alertas. Quando alguma coisa precisar de atenção (temperatura, memória, discos, "
                          "atualizações…) aparece aqui.", "Muted", wrap=True)
            empty.setAlignment(Qt.AlignCenter)
            self.list.addWidget(empty)
        self.list.addStretch(1)
        self.b_read.setEnabled(any(not a.read for a in alerts))
        self.b_clear.setEnabled(bool(alerts))

    def paintEvent(self, e):
        from PySide6.QtGui import QColor, QPainter
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 90 if theme.mode() == "dark" else 45))   # escurece o resto
        p.end()

    def _place(self):
        w = min(440, self.width() - 40)
        self.panel.setGeometry(self.width() - w - 16, 16, w, self.height() - 32)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def close_center(self):
        self.hide()
        alertlog.mark_read()          # abrir o painel conta como ter visto os alertas
        self.win.refresh_alert_badge()
        self.win.setFocus()

    def mousePressEvent(self, e):
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.close_center()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_center()
        else:
            super().keyPressEvent(e)

    # ------------------------------------------------------------------
    def _open_alert(self, a: alertlog.Alert):
        alertlog.mark_read(a.id)
        self.close_center()
        self.win.go_name(a.page)

    def _mark_all(self):
        alertlog.mark_read()
        self.win.refresh_alert_badge()
        self.fill()

    def _clear(self):
        alertlog.clear()
        self.win.refresh_alert_badge()
        self.fill()
