"""Leitor de fundos animados — processo à parte: `Nexo --wallpaper-player <ficheiro> --style <ajuste>`.

Windows: uma janela por monitor, filha da WorkerW (a camada entre a imagem do fundo e os ícones), como
fazem o Wallpaper Engine / Lively. Pausa quando há um programa em ecrã inteiro (jogos) para não gastar GPU.
X11: janelas do tipo _NET_WM_WINDOW_TYPE_DESKTOP (ficam por baixo de tudo).
Vídeo com o QtMultimedia (sem som, em ciclo); GIF/WEBP animados com o QMovie.
"""
from __future__ import annotations

import os
import sys

from PySide6.QtCore import QRect, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QMovie, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ..core import animwp
from ..core.log import log
from ..core.util import IS_WIN

ASPECT = {"fill": Qt.KeepAspectRatioByExpanding, "span": Qt.KeepAspectRatioByExpanding,
          "tile": Qt.KeepAspectRatioByExpanding, "fit": Qt.KeepAspectRatio, "center": Qt.KeepAspectRatio,
          "stretch": Qt.IgnoreAspectRatio}


def _args(argv: list[str]) -> tuple[str, str]:
    i = argv.index("--wallpaper-player")
    path = argv[i + 1] if i + 1 < len(argv) else ""
    style = argv[argv.index("--style") + 1] if "--style" in argv and argv.index("--style") + 1 < len(argv) else "fill"
    return path, style


# ---------------------------------------------------------------------------------------------- superfícies
class MovieSurface(QWidget):
    """GIF / WEBP / PNG animado, desenhado com o ajuste escolhido."""

    def __init__(self, movie: QMovie, style: str):
        super().__init__()
        self.movie = movie
        self.mode = ASPECT.get(style, Qt.KeepAspectRatioByExpanding)
        self._cache: tuple[int, QSize, QPixmap] | None = None
        movie.frameChanged.connect(lambda _n: self.update())

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("black"))
        frame = self.movie.currentPixmap()
        if frame.isNull():
            return
        key = (self.movie.currentFrameNumber(), self.size())
        if self._cache is None or self._cache[:2] != key:
            self._cache = (*key, frame.scaled(self.size() * self.devicePixelRatioF(), self.mode,
                                              Qt.SmoothTransformation))
        pix = self._cache[2]
        pix.setDevicePixelRatio(self.devicePixelRatioF())
        sz = pix.deviceIndependentSize().toSize()
        p.drawPixmap(QRect((self.width() - sz.width()) // 2, (self.height() - sz.height()) // 2,
                           sz.width(), sz.height()), pix)


def _video_surface(player, style: str) -> QWidget:
    from PySide6.QtMultimediaWidgets import QVideoWidget
    w = QVideoWidget()
    w.setAspectRatioMode(ASPECT.get(style, Qt.KeepAspectRatioByExpanding))
    w.setStyleSheet("background: black;")
    return w


# ---------------------------------------------------------------------------------------------- Windows
class _Win32:
    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt
        self.ct, self.wt = ctypes, wt
        u = ctypes.windll.user32
        u.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowW.restype = wt.HWND
        u.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
        u.FindWindowExW.restype = wt.HWND
        u.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                          ctypes.POINTER(ctypes.c_size_t)]
        u.SetParent.argtypes = [wt.HWND, wt.HWND]
        u.SetParent.restype = wt.HWND
        u.GetParent.argtypes = [wt.HWND]
        u.GetParent.restype = wt.HWND
        u.IsWindow.argtypes = [wt.HWND]
        u.GetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
        u.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowLongPtrW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_ssize_t]
        u.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wt.UINT]
        u.MapWindowPoints.argtypes = [wt.HWND, wt.HWND, ctypes.POINTER(wt.POINT), wt.UINT]
        u.GetForegroundWindow.restype = wt.HWND
        u.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
        u.MonitorFromWindow.restype = wt.HMONITOR
        u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]
        u.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM), wt.LPARAM]
        u.EnumDisplayMonitors.argtypes = [wt.HDC, ctypes.c_void_p,
                                          ctypes.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC,
                                                             ctypes.POINTER(wt.RECT), wt.LPARAM), wt.LPARAM]
        self.u = u

    def workerw(self) -> int:
        """A janela onde se desenha o fundo animado (pede ao Explorer para a criar com a mensagem 0x052C)."""
        u, ct = self.u, self.ct
        progman = u.FindWindowW("Progman", None)
        res = ct.c_size_t()
        u.SendMessageTimeoutW(progman, 0x052C, 0xD, 0x1, 0, 1000, ct.byref(res))
        u.SendMessageTimeoutW(progman, 0x052C, 0, 0, 0, 1000, ct.byref(res))
        child = u.FindWindowExW(progman, None, "WorkerW", None)   # Windows 11 24H2+: dentro do Progman
        if child:
            return child
        found = [None]

        @ct.WINFUNCTYPE(self.wt.BOOL, self.wt.HWND, self.wt.LPARAM)
        def cb(hwnd, _lp):
            if u.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
                found[0] = u.FindWindowExW(None, hwnd, "WorkerW", None)
            return True
        u.EnumWindows(cb, 0)
        return found[0] or progman

    def monitors(self) -> list[tuple[int, int, int, int]]:
        out = []
        wt = self.wt

        @self.ct.WINFUNCTYPE(wt.BOOL, wt.HMONITOR, wt.HDC, self.ct.POINTER(wt.RECT), wt.LPARAM)
        def cb(_h, _dc, r, _lp):
            rc = r.contents
            out.append((rc.left, rc.top, rc.right - rc.left, rc.bottom - rc.top))
            return True
        self.u.EnumDisplayMonitors(None, None, cb, 0)
        return out

    def attach(self, hwnd: int, parent: int, rect: tuple[int, int, int, int]) -> None:
        u, wt = self.u, self.wt
        GWL_STYLE, GWL_EXSTYLE = -16, -20
        WS_CHILD, WS_VISIBLE, WS_POPUP, WS_CAPTION, WS_THICKFRAME = 0x40000000, 0x10000000, 0x80000000, 0xC00000, 0x40000
        style = u.GetWindowLongPtrW(hwnd, GWL_STYLE)
        style = (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD | WS_VISIBLE
        u.SetWindowLongPtrW(hwnd, GWL_STYLE, style)
        u.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, u.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) | 0x80 | 0x08000000)  # TOOL|NOACTIVATE
        u.SetParent(hwnd, parent)
        pt = wt.POINT(rect[0], rect[1])
        u.MapWindowPoints(None, parent, self.ct.byref(pt), 1)   # coordenadas do ecrã -> da WorkerW
        u.SetWindowPos(hwnd, None, pt.x, pt.y, rect[2], rect[3], 0x0004 | 0x0010 | 0x0040)  # NOZORDER|NOACTIVATE|SHOW

    def fullscreen_app(self) -> bool:
        """Há um programa em ecrã inteiro à frente (jogo, vídeo)? Então o fundo nem se vê — pausa."""
        u, ct, wt = self.u, self.ct, self.wt
        fg = u.GetForegroundWindow()
        if not fg:
            return False
        buf = ct.create_unicode_buffer(64)
        u.GetClassNameW(fg, buf, 64)
        if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
            return False
        r = wt.RECT()
        u.GetWindowRect(fg, ct.byref(r))

        class MONITORINFO(ct.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]
        mi = MONITORINFO()
        mi.cbSize = ct.sizeof(MONITORINFO)
        if not u.GetMonitorInfoW(u.MonitorFromWindow(fg, 2), ct.byref(mi)):
            return False
        m = mi.rcMonitor
        return r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom


# ---------------------------------------------------------------------------------------------- leitor
class Player:
    def __init__(self, app: QApplication, path: str, style: str):
        self.app, self.path, self.style = app, path, style
        self.surfaces: list[QWidget] = []
        self.paused = False
        self.win = _Win32() if IS_WIN else None
        self.parent = None
        self.media = None
        self.movie = None
        if animwp.is_video(path):
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            self.media = QMediaPlayer()
            self.audio = QAudioOutput()
            self.audio.setMuted(True)
            self.media.setAudioOutput(self.audio)
            self.media.setLoops(QMediaPlayer.Loops.Infinite)
            self.media.setSource(QUrl.fromLocalFile(path))
            self.media.errorOccurred.connect(lambda _e, msg: log.error("fundo animado: %s", msg))
        else:
            self.movie = QMovie(path)
            self.movie.setCacheMode(QMovie.CacheAll)
        self.build()
        self.tick = QTimer(interval=2000, timeout=self._check)
        self.tick.start()

    def _new_surface(self) -> QWidget:
        if self.media is not None:
            return _video_surface(self.media, self.style)
        return MovieSurface(self.movie, self.style)

    def build(self):
        for s in self.surfaces:
            s.close()
            s.deleteLater()
        self.surfaces = []
        if self.win is not None:
            self.parent = self.win.workerw()
            if not self.parent:   # sem Explorer (ou ainda a arrancar no início de sessão): tenta daqui a pouco
                log.warning("fundo animado: não encontrei a camada do ambiente de trabalho (Progman/WorkerW)")
                QTimer.singleShot(5000, self.build)
                return
            rects = self.win.monitors()
        else:
            rects = [s.geometry().getRect() for s in self.app.screens()]
        if self.media is not None:   # um só leitor de vídeo: vários QVideoWidget num QMediaPlayer não dá
            rects = rects[:1] if len(rects) == 1 else [self._union(rects)]
        for r in rects:
            w = self._new_surface()
            w.setWindowFlags(Qt.FramelessWindowHint | Qt.Tool | Qt.WindowDoesNotAcceptFocus |
                             Qt.WindowStaysOnBottomHint)
            w.setAttribute(Qt.WA_ShowWithoutActivating)
            w.setWindowTitle("Nexo — fundo animado")
            if self.win is not None:
                w.resize(r[2], r[3])
                hwnd = int(w.winId())
                self.win.attach(hwnd, self.parent, r)
                w.show()
            else:
                w.setAttribute(Qt.WA_X11NetWmWindowTypeDesktop)
                w.setGeometry(*r)
                w.show()
            self.surfaces.append(w)
        if self.media is not None:
            self.media.setVideoOutput(self.surfaces[0])
            self.media.play()
        else:
            self.movie.start()

    @staticmethod
    def _union(rects):
        x0 = min(r[0] for r in rects)
        y0 = min(r[1] for r in rects)
        x1 = max(r[0] + r[2] for r in rects)
        y1 = max(r[1] + r[3] for r in rects)
        return x0, y0, x1 - x0, y1 - y0

    def _set_paused(self, on: bool):
        if on == self.paused:
            return
        self.paused = on
        if self.media is not None:
            self.media.pause() if on else self.media.play()
        else:
            self.movie.setPaused(on)

    def _check(self):
        if not os.path.exists(self.path):
            self.app.quit()
            return
        if self.win is None or not self.surfaces:
            return
        if not self.win.u.IsWindow(self.parent) or any(
                self.win.u.GetParent(int(s.winId())) != self.parent for s in self.surfaces):
            # o Explorer reiniciou e levou as nossas janelas: arranca um leitor novo e sai
            log.info("fundo animado: o Explorer reiniciou — a relançar o leitor")
            self.tick.stop()
            animwp.relaunch_player(self.path, self.style)
            self.app.quit()
            return
        self._set_paused(self.win.fullscreen_app())


def run(argv: list[str] | None = None) -> int:
    argv = argv or sys.argv
    path, style = _args(argv)
    if not path or not os.path.isfile(path):
        log.error("fundo animado: ficheiro não encontrado: %s", path)
        return 1
    if not animwp.register_self(path):
        log.info("fundo animado: %s já não é o fundo escolhido (ou já está a tocar) — a sair", path)
        return 0
    app = QApplication([argv[0]])
    app.setQuitOnLastWindowClosed(False)
    _player = Player(app, path, style)  # noqa: F841 (tem de viver até ao fim)
    return app.exec()
