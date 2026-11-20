"""Testes de periféricos (página Periféricos): ecrã (píxeis mortos, ghosting, degradê), rato (polling rate,
botões, clique duplo fantasma, roda), teclado (todas as teclas e quantas ao mesmo tempo) e som (colunas
esquerda/direita e nível do microfone)."""
from __future__ import annotations

import math
import struct
import time
from collections import deque

from PySide6.QtCore import QByteArray, QBuffer, QElapsedTimer, QEvent, QIODevice, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QGridLayout, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from ..core.i18n import tr
from . import theme
from .widgets import Bar, StatTile, Tip, label


# =========================================================================== ecrã
class ScreenTest(QWidget):
    """Ecrã inteiro. Clique / Espaço / → avança, ← recua, Esc sai."""

    MODES = [("color", "#000000", "Preto — píxeis acesos (presos) aparecem como pontos de cor"),
             ("color", "#ffffff", "Branco — píxeis mortos aparecem como pontos pretos; manchas = uniformidade"),
             ("color", "#ff0000", "Vermelho"), ("color", "#00ff00", "Verde"), ("color", "#0000ff", "Azul"),
             ("color", "#808080", "Cinzento — manchas escuras nos cantos são «fugas de luz» (normal até certo ponto)"),
             ("gradient", "", "Degradê — riscas em vez de uma transição suave indicam pouca profundidade de cor"),
             ("ghost", "", "Movimento — um rasto atrás dos blocos é ghosting (tempo de resposta lento); tente o "
                           "modo «overdrive» do monitor")]

    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setCursor(Qt.BlankCursor)
        self.i = 0
        self.hint_until = time.monotonic() + 4
        self.clock = QElapsedTimer()
        self.clock.start()
        self.timer = QTimer(self)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.update)
        self.timer.start(4)

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Escape:
            self.close()
        elif k in (Qt.Key_Left, Qt.Key_Backspace):
            self._go(-1)
        else:
            self._go(1)

    def mousePressEvent(self, e):
        self._go(-1 if e.button() == Qt.RightButton else 1)

    def _go(self, d):
        self.i = (self.i + d) % len(self.MODES)
        self.hint_until = time.monotonic() + 3

    def paintEvent(self, _e):
        p = QPainter(self)
        kind, color, hint = self.MODES[self.i]
        r = self.rect()
        if kind == "color":
            p.fillRect(r, QColor(color))
        elif kind == "gradient":
            for k, c in enumerate(("#ffffff", "#ff0000", "#00ff00", "#0000ff")):
                g = QLinearGradient(0, 0, r.width(), 0)
                g.setColorAt(0, QColor("black"))
                g.setColorAt(1, QColor(c))
                p.fillRect(QRectF(0, r.height() * k / 4, r.width(), r.height() / 4 + 1), g)
        else:
            p.fillRect(r, QColor("#7f7f7f"))
            t = self.clock.elapsed() / 1000
            w = 120
            for k, (speed, col) in enumerate(((480, "#ffffff"), (960, "#000000"), (1440, "#0078ff"))):
                x = (t * speed) % (r.width() + w) - w
                y = r.height() * (k + 1) / 4 - w / 2
                p.fillRect(QRectF(x, y, w, w), QColor(col))
                p.setPen(QColor("#202020"))
                p.drawText(QRectF(20, y - 26, 300, 20), Qt.AlignLeft, f"{speed} px/s")
        if time.monotonic() < self.hint_until:
            f = QFont(self.font())
            f.setPointSizeF(f.pointSizeF() * 1.3)
            p.setFont(f)
            txt = f"{self.i + 1}/{len(self.MODES)} · {tr(hint)}\n" + tr("Clique ou Espaço: seguinte · ←: anterior · "
                                                                        "Esc: sair")
            box = QRectF(r.width() * 0.15, r.height() - 130, r.width() * 0.7, 90)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(0, 0, 0, 170))
            p.drawRoundedRect(box, 12, 12)
            p.setPen(QColor("white"))
            p.drawText(box.adjusted(16, 8, -16, -8), Qt.AlignCenter | Qt.TextWordWrap, txt)
        p.end()

    @staticmethod
    def run(parent):
        w = ScreenTest()
        scr = parent.screen() if parent is not None else QApplication.primaryScreen()
        w.setGeometry(scr.geometry())
        w.showFullScreen()
        w.activateWindow()
        return w


# =========================================================================== rato
class _MouseArea(QWidget):
    def __init__(self, dlg: "MouseTest"):
        super().__init__()
        self.dlg = dlg
        self.setMouseTracking(True)
        self.setMinimumHeight(260)
        self.setCursor(Qt.CrossCursor)
        self.trail: deque = deque(maxlen=200)

    def mouseMoveEvent(self, e):
        self.dlg.moved(time.perf_counter())
        self.trail.append(e.position())
        self.update()

    def mousePressEvent(self, e):
        self.dlg.pressed(e.button(), True)

    def mouseReleaseEvent(self, e):
        self.dlg.pressed(e.button(), False)

    def mouseDoubleClickEvent(self, e):
        self.dlg.pressed(e.button(), True)

    def wheelEvent(self, e):
        self.dlg.wheel(e.angleDelta().y())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), theme.qc("surface2"))
        p.setPen(theme.qc("muted"))
        if not self.trail:
            p.drawText(self.rect(), Qt.AlignCenter, tr("Mexa o rato aqui dentro em círculos rápidos"))
        p.setPen(Qt.NoPen)
        n = len(self.trail)
        for i, pt in enumerate(self.trail):
            c = theme.qc("accent")
            c.setAlpha(int(40 + 215 * i / max(1, n)))
            p.setBrush(c)
            p.drawEllipse(QPointF(pt), 2.2, 2.2)
        p.end()


class MouseTest(QDialog):
    BUTTONS = [(Qt.LeftButton, "Esquerdo"), (Qt.RightButton, "Direito"), (Qt.MiddleButton, "Meio"),
               (Qt.BackButton, "Retroceder"), (Qt.ForwardButton, "Avançar")]
    GHOST_MS = 60     # dois cliques mais juntos do que isto = interruptor gasto (clique duplo fantasma)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teste do rato")
        self.resize(720, 560)
        self._prev_compress = QApplication.testAttribute(Qt.AA_CompressHighFrequencyEvents)
        QApplication.setAttribute(Qt.AA_CompressHighFrequencyEvents, False)   # cada movimento conta
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        row = QHBoxLayout()
        self.t_rate = StatTile("Polling rate", "—", "mexa o rato depressa")
        self.t_peak = StatTile("Máximo medido", "—", "")
        self.t_wheel = StatTile("Roda", "0", "↑ 0 · ↓ 0")
        self.t_ghost = StatTile("Cliques duplos fantasma", "0", f"cliques com menos de {self.GHOST_MS} ms")
        for t in (self.t_rate, self.t_peak, self.t_wheel, self.t_ghost):
            row.addWidget(t, 1)
        v.addLayout(row)
        self.area = _MouseArea(self)
        v.addWidget(self.area, 1)
        brow = QHBoxLayout()
        self.btn_lbls: dict = {}
        for b, name in self.BUTTONS:
            lb = QLabel(name)
            lb.setAlignment(Qt.AlignCenter)
            lb.setMinimumHeight(34)
            lb.setObjectName("Chip")
            self.btn_lbls[b] = [lb, 0, False]
            brow.addWidget(lb, 1)
        v.addLayout(brow)
        v.addWidget(label("O polling rate é quantas vezes por segundo o rato diz onde está (125, 500, 1000 Hz ou "
                          "mais). Se der muito abaixo do anunciado, confirme no software do rato. No Wayland e em "
                          "monitores de 60 Hz o valor pode aparecer limitado pelo ambiente gráfico.", "Muted",
                          wrap=True))
        close = QPushButton("Fechar")
        close.setObjectName("Primary")
        close.clicked.connect(self.accept)
        v.addLayout(_right(close))
        self.moves: deque = deque()
        self.peak = 0.0
        self.wheel_up = self.wheel_down = 0
        self.ghosts = 0
        self.last_click: dict = {}
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(250)

    def moved(self, t: float):
        self.moves.append(t)

    def _tick(self):
        now = time.perf_counter()
        while self.moves and now - self.moves[0] > 0.5:
            self.moves.popleft()
        if len(self.moves) >= 20 and now - self.moves[-1] < 0.1:
            span = self.moves[-1] - self.moves[0]
            rate = (len(self.moves) - 1) / span if span > 0 else 0
            self.peak = max(self.peak, rate)
            self.t_rate.set(f"{rate:.0f} Hz", _nearest(rate), "ok")
            self.t_peak.set(f"{self.peak:.0f} Hz", _nearest(self.peak))
        for b, (lb, n, down) in self.btn_lbls.items():
            lb.setStyleSheet(f"background: {theme.C['accent']}; color: {theme.C['accent_text']};" if down else
                             f"color: {theme.C['ok']};" if n else "")

    def pressed(self, button, down: bool):
        st = self.btn_lbls.get(button)
        if st is None:
            return
        st[2] = down
        if down:
            st[1] += 1
            now = time.perf_counter()
            last = self.last_click.get(button)
            if last is not None and (now - last) * 1000 < self.GHOST_MS:
                self.ghosts += 1
                self.t_ghost.set(str(self.ghosts), "o interruptor pode estar gasto (clica duas vezes sozinho)", "bad")
            self.last_click[button] = now
            st[0].setText(f"{tr(dict(self.BUTTONS)[button])} · {st[1]}")
        self._tick()

    def wheel(self, dy: int):
        if dy > 0:
            self.wheel_up += 1
        elif dy < 0:
            self.wheel_down += 1
        self.t_wheel.set(str(self.wheel_up + self.wheel_down), f"↑ {self.wheel_up} · ↓ {self.wheel_down}")

    def done(self, r):
        QApplication.setAttribute(Qt.AA_CompressHighFrequencyEvents, self._prev_compress)
        super().done(r)


def _nearest(rate: float) -> str:
    for hz in (125, 250, 500, 1000, 2000, 4000, 8000):
        if rate <= hz * 1.15:
            return f"rato de ~{hz} Hz" if rate >= hz * 0.7 else "abaixo do normal"
    return "rato de 8000 Hz"


def _right(w) -> QHBoxLayout:
    h = QHBoxLayout()
    h.addStretch(1)
    h.addWidget(w)
    return h


# =========================================================================== teclado
_K = Qt.Key
_ROWS = [
    [("Esc", _K.Key_Escape, 1)] + [(f"F{i}", getattr(_K, f"Key_F{i}"), 1) for i in range(1, 13)]
    + [("PrtSc", _K.Key_Print, 1), ("ScrLk", _K.Key_ScrollLock, 1), ("Pause", _K.Key_Pause, 1)],
    [("\\", _K.Key_Backslash, 1)] + [(str(i), getattr(_K, f"Key_{i}"), 1) for i in (1, 2, 3, 4, 5, 6, 7, 8, 9, 0)]
    + [("'", _K.Key_Apostrophe, 1), ("«", _K.Key_guillemotleft, 1), ("⌫", _K.Key_Backspace, 2),
       ("Ins", _K.Key_Insert, 1), ("Home", _K.Key_Home, 1), ("PgUp", _K.Key_PageUp, 1)],
    [("Tab", _K.Key_Tab, 1.5)] + [(c, getattr(_K, f"Key_{c}"), 1) for c in "QWERTYUIOP"]
    + [("+", _K.Key_Plus, 1), ("´", _K.Key_Dead_Acute, 1), ("Enter", _K.Key_Return, 1.5),
       ("Del", _K.Key_Delete, 1), ("End", _K.Key_End, 1), ("PgDn", _K.Key_PageDown, 1)],
    [("Caps", _K.Key_CapsLock, 1.8)] + [(c, getattr(_K, f"Key_{c}"), 1) for c in "ASDFGHJKL"]
    + [("Ç", _K.Key_Ccedilla, 1), ("º", _K.Key_masculine, 1), ("~", _K.Key_Dead_Tilde, 1)],
    [("Shift", _K.Key_Shift, 2.3), ("<", _K.Key_Less, 1)] + [(c, getattr(_K, f"Key_{c}"), 1) for c in "ZXCVBNM"]
    + [(",", _K.Key_Comma, 1), (".", _K.Key_Period, 1), ("-", _K.Key_Minus, 1), ("Shift", _K.Key_Shift, 2.3),
       ("↑", _K.Key_Up, 1)],
    [("Ctrl", _K.Key_Control, 1.5), ("Win", _K.Key_Meta, 1.3), ("Alt", _K.Key_Alt, 1.3),
     ("Espaço", _K.Key_Space, 6), ("AltGr", _K.Key_AltGr, 1.3), ("Menu", _K.Key_Menu, 1.3),
     ("Ctrl", _K.Key_Control, 1.5), ("←", _K.Key_Left, 1), ("↓", _K.Key_Down, 1), ("→", _K.Key_Right, 1)],
]


class _Keyboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(760, 260)
        self.down: set[int] = set()
        self.seen: set[int] = set()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rows = len(_ROWS)
        widest = max(sum(w for _l, _k, w in row) for row in _ROWS)
        unit = min(self.width() / (widest + 0.5), self.height() / rows)
        f = QFont(self.font())
        f.setPointSizeF(max(7.0, unit * 0.22))
        p.setFont(f)
        for ri, row in enumerate(_ROWS):
            x = 0.0
            for lbl, key, w in row:
                r = QRectF(x + 2, ri * unit + 2, w * unit - 4, unit - 4)
                if int(key) in self.down:
                    bg, fg = theme.qc("accent"), theme.qc("accent_text")
                elif int(key) in self.seen:
                    bg, fg = theme.qc("ok", 70), theme.qc("text")
                else:
                    bg, fg = theme.qc("surface2"), theme.qc("muted")
                p.setPen(theme.qc("border"))
                p.setBrush(bg)
                p.drawRoundedRect(r, 6, 6)
                p.setPen(fg)
                p.drawText(r, Qt.AlignCenter, tr(lbl))
                x += w * unit
        p.end()


class KeyboardTest(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teste do teclado")
        self.resize(900, 520)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        row = QHBoxLayout()
        self.t_count = StatTile("Teclas testadas", "0", "carregue em todas as teclas")
        self.t_now = StatTile("Ao mesmo tempo", "0", "máximo 0")
        self.t_last = StatTile("Última tecla", "—", "")
        for t in (self.t_count, self.t_now, self.t_last):
            row.addWidget(t, 1)
        v.addLayout(row)
        self.kb = _Keyboard()
        v.addWidget(self.kb, 1)
        v.addWidget(label("Verde = já funcionou. Carregue em várias teclas ao mesmo tempo (ex.: W+A+Shift+Espaço) para "
                          "ver quantas o teclado deixa — teclados baratos falham algumas combinações (ghosting). "
                          "Esc também é testada: para sair use o botão Fechar.", "Muted", wrap=True))
        close = QPushButton("Fechar")
        close.setObjectName("Primary")
        close.setFocusPolicy(Qt.NoFocus)
        close.clicked.connect(self.accept)
        v.addLayout(_right(close))
        self.max_now = 0
        self.setFocusPolicy(Qt.StrongFocus)
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, e):
        if e.type() in (QEvent.KeyPress, QEvent.KeyRelease) and self.isActiveWindow():
            self._key(e, e.type() == QEvent.KeyPress)
            return True      # Tab, Esc, Enter, setas… não mexem na janela
        return False

    def _key(self, e, down: bool):
        if e.isAutoRepeat():
            return
        k = int(e.key())
        if down:
            self.kb.down.add(k)
            self.kb.seen.add(k)
            name = e.text().strip()
            if not name:
                try:
                    name = Qt.Key(k).name.replace("Key_", "")
                except ValueError:
                    name = str(k)
            self.t_last.set(name or "?", f"código {e.nativeScanCode()}")
        else:
            self.kb.down.discard(k)
        self.max_now = max(self.max_now, len(self.kb.down))
        self.t_now.set(str(len(self.kb.down)), f"máximo {self.max_now}")
        self.t_count.set(str(len(self.kb.seen)), "")
        self.kb.update()

    def done(self, r):
        QApplication.instance().removeEventFilter(self)
        super().done(r)


# =========================================================================== som
def tone_pcm(freq: float, seconds: float, rate: int, left: bool, right: bool, volume: float = 0.3) -> bytes:
    """PCM 16 bits estéreo com um tom (e entrada/saída suaves para não estalar)."""
    n = int(seconds * rate)
    fade = int(rate * 0.02)
    out = bytearray()
    for i in range(n):
        env = min(1.0, i / fade, (n - i) / fade) if fade else 1.0
        s = int(32767 * volume * env * math.sin(2 * math.pi * freq * i / rate))
        out += struct.pack("<hh", s if left else 0, s if right else 0)
    return bytes(out)


class AudioTest(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Teste do som")
        self.resize(620, 420)
        v = QVBoxLayout(self)
        v.setContentsMargins(20, 18, 20, 16)
        v.setSpacing(12)
        try:
            import PySide6.QtMultimedia  # noqa: F401
            self.ok = True
        except ImportError:
            self.ok = False
            v.addWidget(Tip("Esta instalação do Nexo não tem o módulo de som do Qt (QtMultimedia).", "warn"))
            v.addLayout(_right(self._close()))
            return
        from PySide6.QtMultimedia import QMediaDevices
        self.devices = QMediaDevices(self)
        v.addWidget(label("Colunas / auscultadores", "Section"))
        self.cb_out = QComboBox()
        for d in QMediaDevices.audioOutputs():
            self.cb_out.addItem(d.description(), d)
        self.cb_out.setCurrentIndex(max(0, next((i for i, d in enumerate(QMediaDevices.audioOutputs())
                                                 if d == QMediaDevices.defaultAudioOutput()), 0)))
        v.addWidget(self.cb_out)
        g = QGridLayout()
        for i, (txt, l_, r_) in enumerate((("◀ Esquerda", True, False), ("Ambos", True, True),
                                           ("Direita ▶", False, True))):
            b = QPushButton(txt)
            b.clicked.connect(lambda _c=False, a=l_, z=r_: self._play(a, z))
            g.addWidget(b, 0, i)
        v.addLayout(g)
        v.addWidget(label("Deve ouvir o som só do lado indicado. Se vier trocado, os auscultadores estão ao contrário "
                          "ou o cabo/canais estão trocados nas definições de som.", "Muted", wrap=True))
        v.addWidget(label("Microfone", "Section"))
        self.cb_in = QComboBox()
        for d in QMediaDevices.audioInputs():
            self.cb_in.addItem(d.description(), d)
        self.cb_in.setCurrentIndex(max(0, next((i for i, d in enumerate(QMediaDevices.audioInputs())
                                                if d == QMediaDevices.defaultAudioInput()), 0)))
        self.cb_in.currentIndexChanged.connect(lambda _i: self._start_mic())
        v.addWidget(self.cb_in)
        self.level = Bar(14)
        v.addWidget(self.level)
        self.level_lbl = label("Fale para o microfone: a barra deve mexer-se.", "Muted", wrap=True)
        v.addWidget(self.level_lbl)
        v.addStretch(1)
        v.addLayout(_right(self._close()))
        self.sink = None
        self.buf = None
        self.source = None
        self.mic_io = None
        self.peak = 0.0
        if not QMediaDevices.audioInputs():
            self.level_lbl.setText("Não foi encontrado nenhum microfone.")
        else:
            QTimer.singleShot(0, self._start_mic)

    def _close(self):
        b = QPushButton("Fechar")
        b.setObjectName("Primary")
        b.clicked.connect(self.accept)
        return b

    def _play(self, left: bool, right: bool):
        from PySide6.QtMultimedia import QAudio, QAudioFormat, QAudioSink
        dev = self.cb_out.currentData()
        if dev is None:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(48000)
        fmt.setChannelCount(2)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if self.sink is not None:
            self.sink.stop()
        self.sink = QAudioSink(dev, fmt, self)
        self.buf = QBuffer(self)
        self.buf.setData(QByteArray(tone_pcm(440 if left and right else 660, 1.2, 48000, left, right)))
        self.buf.open(QIODevice.ReadOnly)
        self.sink.stateChanged.connect(lambda st: self.sink.stop() if st == QAudio.IdleState else None)
        self.sink.start(self.buf)

    def _start_mic(self):
        from PySide6.QtMultimedia import QAudioFormat, QAudioSource
        if self.source is not None:
            self.source.stop()
        dev = self.cb_in.currentData()
        if dev is None:
            return
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        self.source = QAudioSource(dev, fmt, self)
        self.mic_io = self.source.start()
        if self.mic_io is None:
            self.level_lbl.setText("Não foi possível abrir o microfone (permissões ou outro programa a usá-lo).")
            return
        self.mic_io.readyRead.connect(self._mic_data)

    def _mic_data(self):
        data = bytes(self.mic_io.readAll().data())
        if len(data) < 2:
            return
        n = len(data) // 2
        samples = struct.unpack(f"<{n}h", data[:n * 2])
        rms = math.sqrt(sum(s * s for s in samples) / n) / 32768
        db = 20 * math.log10(rms) if rms > 0 else -90
        pct = max(0.0, min(100.0, (db + 60) / 60 * 100))
        self.peak = max(pct, self.peak * 0.97)
        self.level.set(pct, "bad" if pct > 95 else "ok" if pct > 15 else "accent")
        if self.peak > 15:
            self.level_lbl.setText(f"O microfone está a captar som ({db:.0f} dBFS)."
                                   + (" Está a saturar — baixe o ganho." if pct > 95 else ""))

    def done(self, r):
        if getattr(self, "ok", False):
            if self.sink is not None:
                self.sink.stop()
            if self.source is not None:
                self.source.stop()
        super().done(r)
