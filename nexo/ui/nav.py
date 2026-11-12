"""Peças da janela principal: menu lateral (botões, secções, leitura ao vivo) e notificação flutuante."""
from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPainter
from PySide6.QtWidgets import QFrame, QGraphicsOpacityEffect, QGridLayout, QHBoxLayout, QPushButton, QSizePolicy

from ..core.i18n import tr
from . import logo as logo_mod
from . import theme
from .icons import pixmap as icon_pixmap
from .widgets import Bar, icon_badge, label


def app_icon(text: str | None = None, color: str | None = None) -> QIcon:
    """Logótipo do Nexo nas cores do tema (com a temperatura escrita, para a bandeja)."""
    colors = (color, color) if color else theme.logo_colors()
    return logo_mod.icon(colors, text)


class Toast(QFrame):
    """Notificação flutuante no canto inferior direito, com ícone e fecho."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setObjectName("Card")
        h = QHBoxLayout(self)
        h.setContentsMargins(14, 12, 10, 12)
        h.setSpacing(12)
        self.badge_holder = QHBoxLayout()
        h.addLayout(self.badge_holder)
        self.text = label("", wrap=True)
        self.text.setMaximumWidth(380)
        h.addWidget(self.text, 1)
        x = QPushButton("✕")
        x.setObjectName("Ghost")
        x.setFixedSize(26, 26)
        x.clicked.connect(self.hide)
        h.addWidget(x, 0, Qt.AlignTop)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._anim = QPropertyAnimation(self._fx, b"opacity", self)
        self._anim.setDuration(180)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def show_msg(self, msg: str, kind: str):
        while self.badge_holder.count():
            w = self.badge_holder.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        ic = {"ok": "check", "bad": "alert", "warn": "alert"}.get(kind, "info")
        self.badge_holder.addWidget(icon_badge(ic, 30, 16, kind if kind in theme.C else "info"), 0, Qt.AlignTop)
        self.text.setText(msg)
        self.setStyleSheet(f"QFrame#Card {{ border-left: 3px solid {theme.C.get(kind, theme.C['info'])}; "
                           f"background: {theme.C['surface2']}; }}")
        self.adjustSize()
        self.reposition()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.start()
        self._timer.start(max(5000, min(12000, 60 * len(msg))))

    def reposition(self):
        p = self.parentWidget()
        if p:
            self.adjustSize()
            self.move(p.width() - self.width() - 20, p.height() - self.height() - 20)


SIDE_W, SIDE_COMPACT_W = 240, 72


class NavButton(QPushButton):
    """Botão do menu lateral: barra de destaque à esquerda quando ativo e contador/aviso opcional."""

    def __init__(self, name: str):
        super().__init__(name)
        self.name = name
        self.setObjectName("Nav")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)   # cabe no menu compacto
        self.setAccessibleName(name)   # continua com nome no menu compacto (só ícone)
        self.badge: str | None = None
        self.badge_kind = "accent"
        self.compact = False

    def set_badge(self, text: str | None, kind: str = "accent"):
        if (text, kind) != (self.badge, self.badge_kind):
            self.badge, self.badge_kind = text, kind
            self.setAccessibleDescription(f"{text} novidades" if text else "aviso" if text == "" else "")
            self.update()

    def set_compact(self, on: bool):
        self.compact = on
        self.setText("" if on else self.name)
        self.setProperty("compact", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def paintEvent(self, e):
        super().paintEvent(e)
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.isChecked():   # barra de destaque à esquerda
            h = 18
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(c["accent"]))
            p.drawRoundedRect(QRectF(0, (self.height() - h) / 2, 3.5, h), 1.75, 1.75)
        if self.badge is not None:
            col = QColor(c.get(self.badge_kind, c["accent"]))
            if self.compact or not self.badge:   # ponto no canto do ícone
                d = 9
                p.setPen(QColor(c["surface"]))
                p.setBrush(col)
                x = self.width() / 2 + 4 if self.compact else self.width() - 20
                p.drawEllipse(QRectF(x, 6 if self.compact else (self.height() - d) / 2, d, d))
            else:
                f = QFont(self.font())
                f.setPixelSize(11)
                f.setBold(True)
                p.setFont(f)
                w = max(20, p.fontMetrics().horizontalAdvance(self.badge) + 12)
                r = QRectF(self.width() - w - 8, (self.height() - 18) / 2, w, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(r, 9, 9)
                p.setPen(QColor("#ffffff"))
                p.drawText(r, Qt.AlignCenter, self.badge)
        p.end()


class NavSection(QPushButton):
    """Título de secção do menu: clicar recolhe/expande a secção. No modo compacto é só uma linha."""

    def __init__(self, title: str):
        super().__init__(title)
        self.title = title
        self.setObjectName("NavSection")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.collapsed = False
        self.compact = False
        self.count = 0

    def set_compact(self, on: bool):
        self.compact = on
        self.setEnabled(not on)
        self.setFixedHeight(14 if on else 26)
        self.update()

    def paintEvent(self, e):
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.compact:
            p.setPen(QColor(c["border2"]))
            y = self.height() / 2
            p.drawLine(int(self.width() * 0.25), int(y), int(self.width() * 0.75), int(y))
            p.end()
            return
        hover = self.underMouse()
        p.setPen(QColor(c["text"] if hover else c["muted"]))
        f = QFont(self.font())
        f.setPixelSize(11)
        f.setBold(True)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1)
        p.setFont(f)
        r = self.rect().adjusted(12, 0, -10, 0)
        txt = tr(self.title) + (f"  ·  {self.count}" if self.collapsed else "")
        p.drawText(r, Qt.AlignLeft | Qt.AlignVCenter, txt)
        pm = icon_pixmap("chev_right" if self.collapsed else "chev_down", c["text"] if hover else c["muted"], 14)
        p.drawPixmap(int(self.width() - 24), int((self.height() - 14) / 2), pm)
        p.end()

    def enterEvent(self, e):
        self.update()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.update()
        super().leaveEvent(e)


class LiveBox(QFrame):
    """Leitura ao vivo de CPU/GPU/RAM no fundo do menu (texto + barra fina)."""

    def __init__(self):
        super().__init__()
        self.setObjectName("LiveBox")
        g = QGridLayout(self)
        g.setContentsMargins(12, 10, 12, 10)
        g.setHorizontalSpacing(8)
        g.setVerticalSpacing(3)
        self.rows = {}
        for i, key in enumerate(("CPU", "GPU", "RAM")):
            name = label(key, "Muted")
            f = name.font()
            f.setBold(True)
            name.setFont(f)
            val = label("—")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            val.setTextFormat(Qt.RichText)
            bar = Bar(4)
            g.addWidget(name, i * 2, 0)
            g.addWidget(val, i * 2, 1)
            g.addWidget(bar, i * 2 + 1, 0, 1, 2)
            self.rows[key] = (val, bar)
        # ligação à internet (clicar volta a testar)
        self.net_name = label("NET", "Muted")
        f = self.net_name.font()
        f.setBold(True)
        self.net_name.setFont(f)
        self.net_val = label("a verificar…", "Muted")
        self.net_val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.net_val.setTextFormat(Qt.RichText)
        g.addWidget(self.net_name, 6, 0)
        g.addWidget(self.net_val, 6, 1)
        self.on_net_click = None
        self.setToolTip("Ligação à internet — clique para abrir a página Internet")

    def mousePressEvent(self, e):
        if self.on_net_click and e.position().y() >= self.net_name.geometry().top() - 4:
            self.on_net_click()
        super().mousePressEvent(e)

    def set_net(self, st):
        color = theme.C.get(st.level, theme.C["muted"])
        self.net_val.setText(f"<span style='color:{color}'>●</span> {st.short()}")
        tip = [f"<b>{st.label}</b>", st.detail, ""]
        for name, ok, det in st.steps:
            mark = "✔" if ok else "✘" if ok is False else "–"
            tip.append(f"{mark} {name}: {det}")
        tip.append("<br><i>Clique para abrir o teste de velocidade</i>")
        self.setToolTip("<br>".join(tip))

    def set(self, key, text, pct, color=None):
        val, bar = self.rows[key]
        if val.text() != text:
            val.setText(text)
        bar.set(pct or 0, color)



class BellButton(QPushButton):
    """Sino do centro de alertas, com o número de alertas por ler."""

    def __init__(self):
        super().__init__()
        self.setFixedSize(36, 36)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName("Alertas")
        self.setToolTip("Alertas (Ctrl+Shift+A)")
        self.count = 0

    def set_count(self, n: int):
        if n != self.count:
            self.count = n
            self.setToolTip(f"Alertas — {n} por ler (Ctrl+Shift+A)" if n else "Alertas (Ctrl+Shift+A)")
            self.setAccessibleDescription(f"{n} por ler" if n else "nenhum por ler")
            self.update()

    def paintEvent(self, e):
        super().paintEvent(e)
        if not self.count:
            return
        c = theme.C
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        txt = "9+" if self.count > 9 else str(self.count)
        f = QFont(self.font())
        f.setPixelSize(9)
        f.setBold(True)
        p.setFont(f)
        w = max(15, p.fontMetrics().horizontalAdvance(txt) + 7)
        r = QRectF(self.width() - w - 1, 1, w, 15)
        p.setPen(QColor(c["surface"]))
        p.setBrush(QColor(c["bad"]))
        p.drawRoundedRect(r, 7.5, 7.5)
        p.setPen(QColor("#ffffff"))
        p.drawText(r, Qt.AlignCenter, txt)
        p.end()
