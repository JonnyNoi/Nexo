"""Cartão «Painel no telemóvel» (Definições): ligar o servidor, ligação, código QR e novo código."""
from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QSpinBox, QVBoxLayout

from ..core import qr, webpanel
from ..core.util import get_setting, set_setting
from .widgets import Card, SettingRow, Tip, Toggle, hbox, label, notify


def qr_pixmap(text: str, px: int = 200) -> QPixmap:
    """Código QR com margem branca (os leitores precisam de contraste, mesmo no tema escuro)."""
    m = qr.encode(text)
    n = len(m) + 8
    img = QImage(px, px, QImage.Format_RGB32)
    img.fill(QColor("white"))
    p = QPainter(img)
    cell = px / n
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("black"))
    for y, row in enumerate(m):
        for x, dark in enumerate(row):
            if dark:
                p.drawRect(QRectF((x + 4) * cell, (y + 4) * cell, cell + 0.5, cell + 0.5))
    p.end()
    return QPixmap.fromImage(img)


class WebPanelCard(Card):
    def __init__(self):
        super().__init__("Painel no telemóvel", "Veja as temperaturas, o consumo e o FPS no telemóvel enquanto joga: "
                         "abra a ligação (ou leia o código QR) num browser ligado à mesma rede Wi-Fi.", icon="wifi")
        self.tg = Toggle(bool(get_setting("web_panel")))
        self.tg.clicked.connect(self._toggle)
        self.add(SettingRow("Ligar o painel", "Só leitura: ninguém consegue mudar nada no PC a partir daqui. Só abre "
                            "com o código da ligação.", self.tg))
        self.sp_port = QSpinBox()
        self.sp_port.setRange(1024, 65535)
        self.sp_port.setValue(int(get_setting("web_port") or 8765))
        self.sp_port.editingFinished.connect(self._port)
        self.add(SettingRow("Porta", "Mude só se outro programa já usar a 8765.", self.sp_port))
        self.qr = QLabel()
        self.qr.setFixedSize(180, 180)
        self.url = label("", "CardTitle", wrap=True)
        self.url.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.btn_copy = QPushButton("Copiar ligação")
        self.btn_copy.clicked.connect(self._copy)
        self.btn_new = QPushButton("Gerar código novo")
        self.btn_new.setToolTip("A ligação antiga deixa de funcionar (por exemplo, se a partilhou sem querer).")
        self.btn_new.clicked.connect(self._new_code)
        col = QVBoxLayout()
        col.setSpacing(8)
        col.addWidget(self.url)
        col.addWidget(label("Se o telemóvel não abrir: confirme que está na mesma rede e que a firewall deixa entrar "
                            "ligações na porta (página Internet → Firewall).", "Muted", wrap=True))
        col.addLayout(hbox(self.btn_copy, self.btn_new, None))
        col.addStretch(1)
        self.info = hbox(self.qr, col)
        self.add(self.info)
        self.err = Tip("", "warn")
        self.err.hide()
        self.add(self.err)
        self._refresh()

    def _toggle(self, on):
        set_setting("web_panel", bool(on))
        w = self.window()
        if hasattr(w, "set_web_panel"):
            ok, _msg = w.set_web_panel(bool(on))
            if on and not ok:
                self.tg.setChecked(False)
                set_setting("web_panel", False)
        self._refresh()

    def _port(self):
        if int(self.sp_port.value()) == int(get_setting("web_port") or 8765):
            return
        set_setting("web_port", int(self.sp_port.value()))
        if get_setting("web_panel"):
            self._toggle(True)

    def _new_code(self):
        webpanel.new_token()
        if get_setting("web_panel"):
            self._toggle(True)
        notify("Código novo gerado — a ligação antiga deixou de funcionar.", "ok")

    def _copy(self):
        QGuiApplication.clipboard().setText(webpanel.panel().url())
        notify("Ligação copiada.", "ok")

    def _refresh(self):
        p = webpanel.panel()
        on = p.running
        for w in (self.qr, self.url, self.btn_copy, self.btn_new):
            w.setVisible(on)
        if on:
            url = p.url()
            self.url.setText(url)
            self.qr.setPixmap(qr_pixmap(url, 180))
            if url.startswith("http://127."):
                self.err.text.setText("Este PC não parece estar ligado a uma rede local — o telemóvel não o vai "
                                      "encontrar.")
                self.err.show()
            else:
                self.err.hide()
        elif p.error:
            self.err.text.setText(p.error)
            self.err.show()
        else:
            self.err.hide()

    def on_show(self):
        self._refresh()
