"""Overlay de jogo: pequena janela por cima de tudo, que não apanha cliques.

Corre num processo próprio (`Nexo --overlay`) e recebe os dados da janela principal por stdin
(uma linha JSON por segundo). No Linux com Wayland arranca via XWayland, que é o que permite
posicionar a janela e mantê-la por cima. Jogos em ecrã inteiro EXCLUSIVO (alguns DirectX no
Windows) desenham por cima de qualquer janela — use "ecrã inteiro sem bordas" no jogo."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import QApplication, QWidget

ITEMS = {"game": "Jogo e tempo", "fps": "FPS", "cpu": "CPU (°C e carga)", "gpu": "GPU (°C e carga)", "power": "Consumo (W)",
         "ram": "RAM", "vram": "VRAM", "clock": "Relógio"}
DEFAULT_ITEMS = ["game", "fps", "cpu", "gpu", "ram", "vram", "clock"]
POSITIONS = {"top-left": "Canto superior esquerdo", "top-right": "Canto superior direito",
             "bottom-left": "Canto inferior esquerdo", "bottom-right": "Canto inferior direito"}


# ============================================================================================ processo do overlay
class _Reader(QObject):
    got = Signal(dict)

    def start(self):
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        for line in sys.stdin:
            try:
                self.got.emit(json.loads(line))
            except ValueError:
                continue
        self.got.emit({"quit": True})  # a janela principal fechou


def _col(v, warn, bad):
    if v is None:
        return QColor("#9aa3b5")
    return QColor("#f87171") if v >= bad else QColor("#fbbf24") if v >= warn else QColor("#3ddc97")


class OverlayWindow(QWidget):
    def __init__(self):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool | Qt.WindowTransparentForInput \
            | Qt.WindowDoesNotAcceptFocus
        if sys.platform.startswith("linux"):
            flags |= Qt.X11BypassWindowManagerHint  # janela "override-redirect": fica acima, mesmo de ecrã inteiro
        super().__init__(None, flags)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.data: dict = {}
        self.cfg: dict = {"pos": "top-left", "opacity": 85, "items": DEFAULT_ITEMS, "size": "detalhado"}
        f = QFont(QApplication.font())
        f.setPointSizeF(10.5)
        f.setBold(True)
        self.font_v = f
        self.font_l = QFont(f)
        self.font_l.setBold(False)
        self.font_l.setPointSizeF(9.0)

    # linhas: [(rótulo, [(texto, cor)])]
    def _lines(self):
        d, items = self.data, self.cfg.get("items", DEFAULT_ITEMS)
        white = QColor("#e9ecf3")
        lines = []

        def fmt(v, unit, dec=0):
            return f"{v:.{dec}f}{unit}" if v is not None else "—"
        if "game" in items and d.get("game"):
            el = int(d.get("elapsed") or 0)
            h, m = divmod(el // 60, 60)
            lines.append(("", [(d["game"], QColor("#a5b4ff")), (f"  {h}h{m:02d}" if h else f"  {m} min", white)]))
        if "fps" in items and (d.get("fps") is not None or d.get("game")):
            fps = d.get("fps")
            if fps is None:
                lines.append(("FPS", [("—", QColor("#9aa3b5"))]))
            else:
                c = QColor("#3ddc97") if fps >= 55 else QColor("#fbbf24") if fps >= 30 else QColor("#f87171")
                lines.append(("FPS", [(f"{fps:.0f}", c), (f"  {d.get('ft') or 1000 / max(fps, 0.1):.1f} ms", white)]))
        if "cpu" in items:
            parts = [(fmt(d.get("cpu_t"), "°"), _col(d.get("cpu_t"), 80, 90)), ("  " + fmt(d.get("cpu_l"), "%"), white)]
            if "power" in items and d.get("cpu_p") is not None:
                parts.append(("  " + fmt(d.get("cpu_p"), "W"), white))
            lines.append(("CPU", parts))
        if "gpu" in items:
            parts = [(fmt(d.get("gpu_t"), "°"), _col(d.get("gpu_t"), 75, 85)), ("  " + fmt(d.get("gpu_l"), "%"), white)]
            if "power" in items and d.get("gpu_p") is not None:
                parts.append(("  " + fmt(d.get("gpu_p"), "W"), white))
            lines.append(("GPU", parts))
        if "ram" in items and d.get("ram_used") is not None:
            lines.append(("RAM", [(fmt(d.get("ram_used"), " GB", 1), _col(d.get("ram_pct"), 85, 95))]))
        if "vram" in items and d.get("vram_used"):
            lines.append(("VRAM", [(d["vram_used"], white)]))
        if "clock" in items:
            lines.append(("", [(time.strftime("%H:%M"), QColor("#9aa3b5"))]))
        return lines

    def _layout(self):
        lines = self._lines()
        compact = self.cfg.get("size") == "compacto"
        fm_v, fm_l = QFontMetrics(self.font_v), QFontMetrics(self.font_l)
        lw = max((fm_l.horizontalAdvance(lb) for lb, _ in lines if lb), default=0) + 8
        pad = 8 if compact else 10
        if compact:  # tudo numa linha
            w = pad * 2 + sum((fm_l.horizontalAdvance(lb + " ") if lb else 0) +
                              sum(fm_v.horizontalAdvance(t) for t, _ in parts) + 14 for lb, parts in lines)
            h = fm_v.height() + pad * 2
        else:
            w = pad * 2 + lw + max((sum(fm_v.horizontalAdvance(t) for t, _ in parts) for _, parts in lines), default=40)
            h = pad * 2 + len(lines) * (fm_v.height() + 2)
        return lines, compact, lw, pad, max(w, 60), max(h, 20)

    def refresh(self):
        lines, compact, lw, pad, w, h = self._layout()
        if (self.width(), self.height()) != (w, h):
            self.resize(w, h)
        scr = QGuiApplication.primaryScreen().geometry()
        m = 14
        pos = self.cfg.get("pos", "top-left")
        x = scr.left() + m if "left" in pos else scr.right() - w - m
        y = scr.top() + m if "top" in pos else scr.bottom() - h - m
        if (self.x(), self.y()) != (x, y):
            self.move(x, y)
        self.update()

    def paintEvent(self, _e):
        lines, compact, lw, pad, w, h = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        bg = QColor(10, 12, 17)
        bg.setAlpha(int(255 * max(20, min(100, self.cfg.get("opacity", 85))) / 100))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(self.rect()), 9, 9)
        fm_v, fm_l = QFontMetrics(self.font_v), QFontMetrics(self.font_l)
        lh = fm_v.height()
        x, y = pad, pad
        for lb, parts in lines:
            if lb:
                p.setFont(self.font_l)
                p.setPen(QColor("#8a93a8"))
                p.drawText(QRectF(x, y, lw, lh), Qt.AlignLeft | Qt.AlignVCenter, lb)
                cx = x + (fm_l.horizontalAdvance(lb + " ") if compact else lw)
            else:
                cx = x
            p.setFont(self.font_v)
            for txt, color in parts:
                tw = fm_v.horizontalAdvance(txt)
                p.setPen(QColor(0, 0, 0, 160))
                p.drawText(QRectF(cx + 1, y + 1, tw + 2, lh), Qt.AlignLeft | Qt.AlignVCenter, txt)
                p.setPen(color)
                p.drawText(QRectF(cx, y, tw + 2, lh), Qt.AlignLeft | Qt.AlignVCenter, txt)
                cx += tw
            if compact:
                x = cx + 14
            else:
                y += lh + 2
        p.end()

    def on_data(self, msg: dict):
        if msg.get("quit"):
            QApplication.quit()
            return
        if "cfg" in msg:
            self.cfg.update(msg["cfg"])
        if "data" in msg:
            self.data = msg["data"]
        if msg.get("hide"):
            self.hide()
            return
        self.refresh()
        if not self.isVisible():
            self.show()
        self.raise_()


def run() -> int:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    w = OverlayWindow()
    r = _Reader()
    r.got.connect(w.on_data)
    r.start()
    t = QTimer()
    t.timeout.connect(w.raise_)  # volta para cima se outra janela "sempre por cima" aparecer
    t.start(2000)
    return app.exec()


# ============================================================================================ lado da janela principal
class OverlayController:
    """Lança/termina o processo do overlay e envia-lhe os dados dos sensores."""

    def __init__(self):
        self.proc: subprocess.Popen | None = None
        self.game = ""
        self.started = 0.0
        from ..core.fps import FpsMeter
        self.fps = FpsMeter()
        self.last_fps: dict | None = None

    def _cmd(self) -> list[str]:
        if getattr(sys, "frozen", False):
            return [sys.executable, "--overlay"]
        return [sys.executable, "-m", "nexo", "--overlay"]

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def show(self, game: str = "", started: float = 0.0):
        self.game, self.started = game, started or time.time()
        if not self.running():
            env = dict(os.environ)
            if sys.platform.startswith("linux") and env.get("WAYLAND_DISPLAY") and env.get("DISPLAY"):
                env["QT_QPA_PLATFORM"] = "xcb"   # XWayland: permite posicionar e ficar por cima
            cwd = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}
            try:
                self.proc = subprocess.Popen(self._cmd(), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                             stderr=subprocess.DEVNULL, text=True, env=env, cwd=cwd, **kw)
            except OSError:
                self.proc = None
                return
        self.send_cfg()

    def hide(self):
        if self.running():
            try:
                self.proc.stdin.close()
            except OSError:
                pass
            try:
                self.proc.terminate()
            except OSError:
                pass
        self.proc = None

    def _send(self, msg: dict):
        if not self.running():
            return
        try:
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
        except (OSError, ValueError):
            self.proc = None

    def send_cfg(self):
        from ..core.util import get_setting
        self._send({"cfg": {"pos": get_setting("overlay_pos"), "opacity": get_setting("overlay_opacity"),
                            "items": get_setting("overlay_items"), "size": get_setting("overlay_size")}})

    def push(self, hub):
        """Chamar 1×/s com o SensorHub."""
        f = self.last_fps = self.fps.read() if (self.fps.pid or self.running()) else None
        if not self.running():
            return
        from ..core.sensors import pick
        r = hub.last
        vram_mb = pick(r, "GPU", "VRAM usada")
        data = {"cpu_t": hub.latest("cpu_temp"), "cpu_l": hub.latest("cpu_load"), "gpu_t": hub.latest("gpu_temp"),
                "gpu_l": hub.latest("gpu_load"), "cpu_p": hub.latest("cpu_power"), "gpu_p": hub.latest("gpu_power"),
                "ram_pct": hub.latest("ram"), "ram_used": pick(r, "Memória", "RAM usada"),
                "vram_used": (f"{vram_mb / 1024:.1f} GB" if vram_mb and vram_mb >= 1024 else
                              f"{vram_mb:.0f} MB" if vram_mb else ""),
                "fps": f["fps"] if f else None, "ft": f["ft"] if f else None,
                "game": self.game, "elapsed": time.time() - self.started if self.game else 0}
        self._send({"data": data})
