"""Fundo da janela: efeito animado do tema e/ou imagem, GIF ou vídeo escolhido pelo utilizador.

Todos os efeitos são desenhados em código (originais do Nexo). Para poupar CPU/GPU:
- a animação corre a um número limitado de fotogramas por segundo (definição "bg_fps");
- pára com a janela minimizada/escondida e (opcional) quando a janela não está ativa;
- imagens estáticas são escaladas/desfocadas uma só vez e depois apenas deslizam (efeito "Ken Burns").
"""
from __future__ import annotations

import math
import os
import random
import time

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import (QColor, QFont, QImage, QLinearGradient, QMovie, QPainter, QPainterPath, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtGui import QRegion
from PySide6.QtWidgets import QFrame, QWidget

from ..core.util import get_setting
from . import theme

VIDEO_EXT = (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v")
GIF_EXT = (".gif",)
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def _col(name: str, a: int = 255) -> QColor:
    c = QColor(theme.C[name])
    c.setAlpha(a)
    return c


def _layer(w: int, h: int, draw) -> QPixmap:
    """Desenha uma camada estática uma única vez (os caminhos complexos custam muito por fotograma)."""
    img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    draw(q)
    q.end()
    return QPixmap.fromImage(img)


# =========================================================================== efeitos
class Effect:
    def __init__(self):
        self.w = self.h = 0

    def resize(self, w: int, h: int):
        self.w, self.h = w, h

    def paint(self, p: QPainter, t: float):
        raise NotImplementedError


class Plexus(Effect):
    """Rede de partículas que se ligam quando estão perto (o "nexo")."""
    N = 70

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(7)
        self.pts = [[rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(-14, 14), rnd.uniform(-14, 14),
                     rnd.uniform(1.2, 2.6)] for _ in range(self.N)]
        self.last = None

    def paint(self, p, t):
        dt = 0 if self.last is None else min(0.1, t - self.last)
        self.last = t
        w, h = self.w, self.h
        for pt in self.pts:
            pt[0] += pt[2] * dt
            pt[1] += pt[3] * dt
            if pt[0] < 0 or pt[0] > w:
                pt[2] = -pt[2]
            if pt[1] < 0 or pt[1] > h:
                pt[3] = -pt[3]
        # brilho de fundo
        g = QRadialGradient(QPointF(w * 0.75, h * 0.2), max(w, h) * 0.7)
        g.setColorAt(0, _col("accent", 38))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), g)
        maxd = 150.0
        acc, acc2 = QColor(theme.C["accent"]), QColor(theme.C["accent2"])
        pen = QPen()
        pen.setWidthF(1.0)
        pts = self.pts
        for i in range(len(pts)):
            xi, yi = pts[i][0], pts[i][1]
            for j in range(i + 1, len(pts)):
                dx, dy = xi - pts[j][0], yi - pts[j][1]
                if abs(dx) > maxd or abs(dy) > maxd:
                    continue
                d = math.hypot(dx, dy)
                if d < maxd:
                    c = QColor(acc if (i + j) % 3 else acc2)
                    c.setAlpha(int(110 * (1 - d / maxd)))
                    pen.setColor(c)
                    p.setPen(pen)
                    p.drawLine(QPointF(xi, yi), QPointF(pts[j][0], pts[j][1]))
        p.setPen(Qt.NoPen)
        for k, pt in enumerate(pts):
            p.setBrush(QColor(acc2 if k % 4 == 0 else acc))
            p.drawEllipse(QPointF(pt[0], pt[1]), pt[4], pt[4])


class NeonGrid(Effect):
    """Cyberpunk: cidade em silhueta, grelha néon em perspetiva a avançar e linhas de varrimento."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(2077)
        self.horizon = h * 0.55
        self.buildings = []
        x = 0.0
        while x < w:
            bw = rnd.uniform(26, 80)
            bh = rnd.uniform(h * 0.08, h * 0.32)
            wins = [(rnd.uniform(4, bw - 8), rnd.uniform(6, bh - 10), rnd.random() < 0.5) for _ in range(int(bw * bh / 900))]
            self.buildings.append((x, bw, bh, wins))
            x += bw + rnd.uniform(0, 6)

    def paint(self, p, t):
        w, h, hz = self.w, self.h, self.horizon
        sky = QLinearGradient(0, 0, 0, hz)
        sky.setColorAt(0, QColor(0, 0, 0, 0))
        sky.setColorAt(1, _col("accent2", 45))
        p.fillRect(QRectF(0, 0, w, hz), sky)
        # cidade
        mag = QColor(theme.C["series"][2])
        for x, bw, bh, wins in self.buildings:
            p.fillRect(QRectF(x, hz - bh, bw, bh), QColor(8, 4, 16, 235))
            p.setPen(QPen(QColor(mag.red(), mag.green(), mag.blue(), 70), 1))
            p.drawLine(QPointF(x, hz - bh), QPointF(x + bw, hz - bh))
            p.setPen(Qt.NoPen)
            for wx, wy, lit in wins:
                if lit and (int(t * 0.5 + wx) % 7):
                    p.fillRect(QRectF(x + wx, hz - bh + wy, 3, 4), _col("accent", 150))
        # chão
        floor = QLinearGradient(0, hz, 0, h)
        floor.setColorAt(0, QColor(mag.red(), mag.green(), mag.blue(), 60))
        floor.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, hz, w, h - hz), floor)
        cx = w / 2
        pen = QPen(_col("accent2", 150), 1.2)
        p.setPen(pen)
        for i in range(-24, 25):
            p.drawLine(QPointF(cx + i * 18, hz), QPointF(cx + i * w / 9, h))
        speed = (t * 0.35) % 1.0
        for i in range(16):
            z = (i + speed) / 16
            y = hz + (h - hz) * (z ** 2.2)
            c = QColor(mag)
            c.setAlpha(int(40 + 170 * z))
            p.setPen(QPen(c, 1 + 1.5 * z))
            p.drawLine(QPointF(0, y), QPointF(w, y))
        # linha do horizonte e varrimento
        p.setPen(QPen(_col("accent", 200), 2))
        p.drawLine(QPointF(0, hz), QPointF(w, hz))
        sy = (t * 60) % (h + 200) - 100
        g = QLinearGradient(0, sy - 60, 0, sy + 60)
        g.setColorAt(0, QColor(0, 0, 0, 0))
        g.setColorAt(0.5, _col("accent2", 22))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, sy - 60, w, 120), g)


class Sunset(Effect):
    """Synthwave: sol com riscas, montanhas e grelha."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(1984)
        self.stars = [(rnd.uniform(0, w), rnd.uniform(0, h * 0.5), rnd.uniform(0.5, 1.6), rnd.uniform(0, 6.28))
                      for _ in range(120)]
        self.hz = h * 0.62

    def paint(self, p, t):
        w, h, hz = self.w, self.h, self.hz
        p.setPen(Qt.NoPen)
        for x, y, r, ph in self.stars:
            a = int(120 + 120 * math.sin(t * 1.5 + ph))
            p.setBrush(QColor(255, 255, 255, max(0, a)))
            p.drawEllipse(QPointF(x, y), r, r)
        # sol
        R = min(w, h) * 0.2
        cx, cy = w * 0.5, hz - R * 0.35
        g = QLinearGradient(0, cy - R, 0, cy + R)
        g.setColorAt(0, _col("warn", 230))
        g.setColorAt(1, _col("accent", 230))
        sun = QPainterPath()
        sun.addEllipse(QPointF(cx, cy), R, R)
        cut = QPainterPath()
        off = (t * 8) % 14
        for i in range(9):
            y = cy + R * 0.1 + i * 14 + off - 14
            cut.addRect(QRectF(cx - R, y, 2 * R, 2 + i * 0.9))
        clip = QPainterPath()
        clip.addRect(QRectF(0, 0, w, hz))
        p.setBrush(g)
        p.drawPath(sun.subtracted(cut).intersected(clip))
        glow = QRadialGradient(QPointF(cx, cy), R * 2.2)
        glow.setColorAt(0, _col("accent", 70))
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, hz), glow)
        # montanhas
        for layer, (amp, a) in enumerate(((h * 0.10, 200), (h * 0.06, 240))):
            path = QPainterPath(QPointF(0, hz))
            for i in range(41):
                x = w * i / 40
                y = hz - amp * abs(math.sin(i * 0.9 + layer * 1.7)) * (0.6 + 0.4 * math.sin(i * 0.33 + layer))
                path.lineTo(x, y)
            path.lineTo(w, hz)
            path.closeSubpath()
            p.setBrush(QColor(20 + layer * 6, 4, 40 + layer * 10, a))
            p.drawPath(path)
        # grelha
        fl = QLinearGradient(0, hz, 0, h)
        fl.setColorAt(0, QColor(30, 0, 50, 230))
        fl.setColorAt(1, QColor(10, 0, 20, 160))
        p.fillRect(QRectF(0, hz, w, h - hz), fl)
        p.setPen(QPen(_col("accent", 170), 1.2))
        for i in range(-20, 21):
            p.drawLine(QPointF(cx + i * 14, hz), QPointF(cx + i * w / 10, h))
        sp = (t * 0.4) % 1
        for i in range(14):
            z = (i + sp) / 14
            y = hz + (h - hz) * z ** 2
            p.setPen(QPen(_col("info", int(40 + 180 * z)), 1 + z))
            p.drawLine(QPointF(0, y), QPointF(w, y))


class DigitalRain(Effect):
    """Matrix: chuva de caracteres (desenhada sobre uma imagem persistente que vai desvanecendo)."""
    CHARS = "アイウエオカキクケコサシスセソタチツテトナニヌネノ0123456789ABCDEF:<>*+=#$%"
    CELL = 16

    def resize(self, w, h):
        super().resize(w, h)
        self.cols = max(1, w // self.CELL)
        rnd = random.Random()
        self.drops = [rnd.uniform(-h / self.CELL, 0) for _ in range(self.cols)]
        self.speed = [rnd.uniform(8, 22) for _ in range(self.cols)]
        self.img = QImage(max(1, w), max(1, h), QImage.Format_ARGB32_Premultiplied)
        self.img.fill(Qt.transparent)
        self.font = QFont("monospace")
        self.font.setPixelSize(self.CELL - 2)
        self.last = None
        self.rnd = rnd

    def paint(self, p, t):
        dt = 0.05 if self.last is None else min(0.2, t - self.last)
        self.last = t
        ip = QPainter(self.img)
        ip.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        ip.fillRect(self.img.rect(), QColor(0, 0, 0, int(min(255, 260 * dt))))
        ip.setCompositionMode(QPainter.CompositionMode_SourceOver)
        ip.setFont(self.font)
        head, body = QColor(theme.C["accent2"]), QColor(theme.C["accent"])
        rows = self.h / self.CELL
        for i in range(self.cols):
            prev = int(self.drops[i])
            self.drops[i] += self.speed[i] * dt
            cur = int(self.drops[i])
            for r in range(prev + 1, cur + 1):
                if r < 0:
                    continue
                ip.setPen(body)
                ip.drawText(QPointF(i * self.CELL, (r - 1) * self.CELL + self.CELL - 3), self.rnd.choice(self.CHARS))
                ip.setPen(head)
                ip.drawText(QPointF(i * self.CELL, r * self.CELL + self.CELL - 3), self.rnd.choice(self.CHARS))
            if self.drops[i] > rows and self.rnd.random() < 0.03:
                self.drops[i] = self.rnd.uniform(-20, 0)
                self.speed[i] = self.rnd.uniform(8, 22)
        ip.end()
        p.setOpacity(0.55)
        p.drawImage(0, 0, self.img)
        p.setOpacity(1.0)


class Aurora(Effect):
    """Ondas de luz suaves (aurora boreal) e estrelas."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(42)
        self.stars = [(rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(0.4, 1.3), rnd.uniform(0, 6.28))
                      for _ in range(90)]

    def paint(self, p, t):
        w, h = self.w, self.h
        p.setPen(Qt.NoPen)
        for x, y, r, ph in self.stars:
            p.setBrush(QColor(255, 255, 255, int(70 + 60 * math.sin(t + ph))))
            p.drawEllipse(QPointF(x, y), r, r)
        cols = [theme.C["accent"], theme.C["accent2"], theme.C["info"]]
        for k in range(3):
            path = QPainterPath()
            base = h * (0.25 + 0.12 * k)
            amp = h * 0.08
            path.moveTo(0, base)
            for i in range(61):
                x = w * i / 60
                y = base + amp * math.sin(i * 0.18 + t * (0.25 + 0.1 * k) + k * 2) \
                    + amp * 0.5 * math.sin(i * 0.07 - t * 0.15 + k)
                path.lineTo(x, y)
            path.lineTo(w, base + h * 0.35)
            path.lineTo(0, base + h * 0.35)
            path.closeSubpath()
            g = QLinearGradient(0, base - amp, 0, base + h * 0.35)
            c1 = QColor(cols[k])
            c1.setAlpha(70)
            c2 = QColor(cols[k])
            c2.setAlpha(0)
            g.setColorAt(0, c1)
            g.setColorAt(1, c2)
            p.setBrush(g)
            p.drawPath(path)


class Petals(Effect):
    """Sakura: pétalas de cerejeira a cair, a balançar e a rodar; lua e brilho suave."""
    N = 55

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(sum(map(ord, "sakura")))
        self.p = [[rnd.uniform(0, w), rnd.uniform(-h, h), rnd.uniform(18, 46), rnd.uniform(0, 6.28),
                   rnd.uniform(5, 11), rnd.uniform(-90, 90), rnd.uniform(0.6, 1.0)] for _ in range(self.N)]
        self.last = None
        # forma de uma pétala (com o entalhe na ponta), desenhada uma vez
        path = QPainterPath(QPointF(0, 1))
        path.cubicTo(QPointF(-0.9, 0.4), QPointF(-0.7, -0.8), QPointF(-0.15, -1))
        path.lineTo(QPointF(0, -0.75))
        path.lineTo(QPointF(0.15, -1))
        path.cubicTo(QPointF(0.7, -0.8), QPointF(0.9, 0.4), QPointF(0, 1))
        self.shape = path

    def paint(self, p, t):
        dt = 0 if self.last is None else min(0.1, t - self.last)
        self.last = t
        w, h = self.w, self.h
        moon = QRadialGradient(QPointF(w * 0.82, h * 0.18), min(w, h) * 0.32)
        moon.setColorAt(0, QColor(255, 236, 245, 70))
        moon.setColorAt(0.25, _col("accent2", 35))
        moon.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), moon)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 240, 246, 60))
        p.drawEllipse(QPointF(w * 0.82, h * 0.18), min(w, h) * 0.07, min(w, h) * 0.07)
        acc, acc2 = QColor(theme.C["accent"]), QColor(theme.C["accent2"])
        for k, q in enumerate(self.p):
            x0, y, vy, ph, size, rot, alpha = q
            y += vy * dt
            q[1] = y
            q[5] = rot + 40 * dt * (1 if k % 2 else -1)
            x = x0 + 40 * math.sin(t * 0.8 + ph) + t * 12 % (w + 80) - 40
            x %= (w + 40)
            if y > h + 20:
                q[1] = -20
                q[0] = random.uniform(0, w)
            p.save()
            p.translate(x, y)
            p.rotate(q[5])
            p.scale(size * (0.55 + 0.45 * abs(math.sin(t + ph))), size)  # "vira" ao cair
            c = QColor(acc2 if k % 3 else acc)
            c.setAlpha(int(200 * alpha))
            p.setBrush(c)
            p.drawPath(self.shape)
            p.restore()


class RainWindow(Effect):
    """Lo-fi Noite: luzes da cidade desfocadas (bokeh) e chuva a escorrer na janela."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(808)
        cols = theme.C["series"]
        self.bokeh = [(rnd.uniform(0, w), rnd.uniform(h * 0.35, h), rnd.uniform(14, 60), QColor(rnd.choice(cols)),
                       rnd.uniform(0, 6.28)) for _ in range(38)]
        self.streaks = [[rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(260, 520), rnd.uniform(10, 26)]
                        for _ in range(140)]
        self.drops = [(rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(1.5, 4)) for _ in range(90)]
        self.last = None

    def paint(self, p, t):
        dt = 0 if self.last is None else min(0.1, t - self.last)
        self.last = t
        w, h = self.w, self.h
        p.setPen(Qt.NoPen)
        for x, y, r, c, ph in self.bokeh:
            g = QRadialGradient(QPointF(x, y), r)
            cc = QColor(c)
            cc.setAlpha(int(55 + 25 * math.sin(t * 0.7 + ph)))
            g.setColorAt(0, cc)
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(x, y), r, r)
        pen = QPen(QColor(200, 210, 255, 55), 1)
        p.setPen(pen)
        for s in self.streaks:
            s[1] += s[2] * dt
            if s[1] > h + 30:
                s[1] = random.uniform(-80, -10)
                s[0] = random.uniform(0, w)
            p.drawLine(QPointF(s[0], s[1]), QPointF(s[0] - s[3] * 0.15, s[1] - s[3]))
        p.setPen(Qt.NoPen)
        for x, y, r in self.drops:  # gotas paradas no vidro
            yy = (y + t * 3 * r) % h
            p.setBrush(QColor(220, 230, 255, 70))
            p.drawEllipse(QPointF(x, yy), r, r * 1.2)
            p.setBrush(QColor(255, 255, 255, 110))
            p.drawEllipse(QPointF(x - r * 0.3, yy - r * 0.4), r * 0.3, r * 0.3)


class SummerSky(Effect):
    """Céu de Verão: céu em gradiente, raios de sol, nuvens fofas em paralaxe e colinas."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(7_2023)
        self.clouds = []
        for layer in range(3):
            for _ in range(5 - layer):
                blobs = [(rnd.uniform(-60, 60), rnd.uniform(-14, 14), rnd.uniform(26, 58)) for _ in range(6)]
                self.clouds.append([rnd.uniform(0, w), rnd.uniform(h * 0.05, h * 0.45), 0.5 + layer * 0.35,
                                    6 + layer * 7, blobs])
        self.cloud_px = {}

        def draw_sky(q):
            sky = QLinearGradient(0, 0, 0, h)
            sky.setColorAt(0, QColor("#3f8fe8"))
            sky.setColorAt(0.55, QColor("#9fd0ff"))
            sky.setColorAt(1, QColor("#e9f6ff"))
            q.fillRect(QRectF(0, 0, w, h), sky)

        def draw_hills(q):
            q.setPen(Qt.NoPen)
            for k, (col, base, amp) in enumerate((("#7cc48a", 0.78, 0.05), ("#4fa66b", 0.86, 0.04))):
                path = QPainterPath(QPointF(0, h))
                for i in range(41):
                    path.lineTo(w * i / 40, h * base - h * amp * math.sin(i * 0.35 + k * 2))
                path.lineTo(w, h)
                path.closeSubpath()
                q.setBrush(QColor(col))
                q.drawPath(path)
        self.sky_px = _layer(w, h, draw_sky)
        self.hills_px = _layer(w, h, draw_hills)

    def _cloud(self, scale, blobs):
        key = (round(scale, 2), id(blobs))
        pm = self.cloud_px.get(key)
        if pm is None:
            W, H = int(260 * scale), int(160 * scale)
            img = QImage(W, H, QImage.Format_ARGB32_Premultiplied)
            img.fill(Qt.transparent)
            q = QPainter(img)
            q.setRenderHint(QPainter.Antialiasing)
            q.setPen(Qt.NoPen)
            for dx, dy, r in blobs:  # sombra
                q.setBrush(QColor(170, 190, 225, 120))
                q.drawEllipse(QPointF(W / 2 + dx * scale, H / 2 + (dy + 10) * scale), r * scale, r * scale * 0.8)
            for dx, dy, r in blobs:
                q.setBrush(QColor(255, 255, 255, 235))
                q.drawEllipse(QPointF(W / 2 + dx * scale, H / 2 + dy * scale), r * scale, r * scale * 0.8)
            q.end()
            pm = self.cloud_px[key] = QPixmap.fromImage(img)
        return pm

    def paint(self, p, t):
        w, h = self.w, self.h
        p.drawPixmap(0, 0, self.sky_px)
        sun = QPointF(w * 0.18, h * 0.12)
        p.save()
        p.translate(sun)
        p.rotate(t * 2)
        p.setPen(Qt.NoPen)
        for i in range(12):
            p.rotate(30)
            g = QLinearGradient(0, 0, max(w, h), 0)
            g.setColorAt(0, QColor(255, 250, 220, 60))
            g.setColorAt(1, QColor(255, 250, 220, 0))
            p.setBrush(g)
            path = QPainterPath(QPointF(0, 0))
            path.lineTo(max(w, h), -60)
            path.lineTo(max(w, h), 60)
            path.closeSubpath()
            p.drawPath(path)
        p.restore()
        glow = QRadialGradient(sun, min(w, h) * 0.25)
        glow.setColorAt(0, QColor(255, 255, 240, 255))
        glow.setColorAt(0.15, QColor(255, 250, 210, 200))
        glow.setColorAt(1, QColor(255, 250, 210, 0))
        p.fillRect(QRectF(0, 0, w, h), glow)
        for c in self.clouds:
            x = (c[0] + t * c[3]) % (w + 400) - 200
            pm = self._cloud(c[2], c[4])
            p.drawPixmap(QPointF(x - pm.width() / 2, c[1] - pm.height() / 2), pm)
        p.drawPixmap(0, 0, self.hills_px)


class Comet(Effect):
    """Cometa: céu estrelado, estrelas cadentes e um cometa que atravessa o céu devagar."""

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(3_141)
        self.stars = [(rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(0.4, 1.7), rnd.uniform(0, 6.28))
                      for _ in range(220)]
        self.shoot = []
        self.rnd = rnd
        self.next_shot = 0.0

    def paint(self, p, t):
        w, h = self.w, self.h
        neb = QRadialGradient(QPointF(w * 0.3, h * 0.35), max(w, h) * 0.6)
        neb.setColorAt(0, _col("accent2", 40))
        neb.setColorAt(0.5, _col("accent", 22))
        neb.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, 0, w, h), neb)
        p.setPen(Qt.NoPen)
        for x, y, r, ph in self.stars:
            p.setBrush(QColor(255, 255, 255, int(110 + 110 * math.sin(t * 1.3 + ph))))
            p.drawEllipse(QPointF(x, y), r, r)
        # cometa (ciclo de 40 s)
        ph = (t % 40) / 40
        cx, cy = -0.1 * w + 1.2 * w * ph, h * 0.12 + h * 0.18 * ph
        ang = math.atan2(0.18 * h, 1.2 * w)
        tail = max(w, h) * 0.35
        tx, ty = cx - tail * math.cos(ang), cy - tail * math.sin(ang)
        g = QLinearGradient(QPointF(cx, cy), QPointF(tx, ty))
        g.setColorAt(0, QColor(255, 255, 255, 230))
        g.setColorAt(0.2, _col("accent2", 160))
        g.setColorAt(1, QColor(0, 0, 0, 0))
        p.setPen(QPen(g, 5, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(tx, ty))
        p.setPen(QPen(g, 2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, cy), QPointF(tx + 30, ty + 40))
        head = QRadialGradient(QPointF(cx, cy), 16)
        head.setColorAt(0, QColor(255, 255, 255, 255))
        head.setColorAt(1, QColor(255, 255, 255, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(head)
        p.drawEllipse(QPointF(cx, cy), 16, 16)
        # estrelas cadentes
        if t > self.next_shot:
            self.next_shot = t + self.rnd.uniform(0.8, 2.5)
            self.shoot.append([self.rnd.uniform(w * 0.2, w), self.rnd.uniform(0, h * 0.5), t])
        alive = []
        for x0, y0, t0 in self.shoot:
            k = (t - t0) / 0.9
            if k > 1:
                continue
            alive.append([x0, y0, t0])
            x, y = x0 - 420 * k, y0 + 210 * k
            g = QLinearGradient(QPointF(x, y), QPointF(x + 90, y - 45))
            g.setColorAt(0, QColor(255, 255, 255, int(230 * (1 - k))))
            g.setColorAt(1, QColor(255, 255, 255, 0))
            p.setPen(QPen(g, 2))
            p.drawLine(QPointF(x, y), QPointF(x + 90, y - 45))
        self.shoot = alive


class Lanterns(Effect):
    """Lanternas: lanternas de papel a subir devagar, a balançar e a brilhar."""
    N = 34

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(88)
        self.l = [[rnd.uniform(0, w), rnd.uniform(0, h * 1.2), rnd.uniform(0.45, 1.15), rnd.uniform(0, 6.28),
                   rnd.uniform(8, 22)] for _ in range(self.N)]
        self.l.sort(key=lambda q: q[2])  # as pequenas (longe) primeiro
        self.last = None

    def paint(self, p, t):
        dt = 0 if self.last is None else min(0.1, t - self.last)
        self.last = t
        w, h = self.w, self.h
        hz = QLinearGradient(0, h * 0.5, 0, h)
        hz.setColorAt(0, QColor(0, 0, 0, 0))
        hz.setColorAt(1, _col("accent", 50))
        p.fillRect(QRectF(0, h * 0.5, w, h * 0.5), hz)
        p.setPen(Qt.NoPen)
        for q in self.l:
            x0, y, sc, ph, spd = q
            y -= spd * sc * dt
            if y < -60:
                y = h + random.uniform(20, 120)
                q[0] = random.uniform(0, w)
            q[1] = y
            x = x0 + 18 * sc * math.sin(t * 0.5 + ph)
            fl = 0.85 + 0.15 * math.sin(t * 6 + ph * 3)
            glow = QRadialGradient(QPointF(x, y), 46 * sc)
            glow.setColorAt(0, _col("accent", int(110 * fl)))
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(glow)
            p.drawEllipse(QPointF(x, y), 46 * sc, 46 * sc)
            body = QLinearGradient(0, y - 16 * sc, 0, y + 16 * sc)
            body.setColorAt(0, QColor(255, 220, 150, int(235 * fl)))
            body.setColorAt(1, _col("accent2", int(235 * fl)))
            p.setBrush(body)
            p.drawRoundedRect(QRectF(x - 11 * sc, y - 15 * sc, 22 * sc, 30 * sc), 9 * sc, 9 * sc)
            p.setBrush(QColor(60, 20, 10, 200))
            p.drawRect(QRectF(x - 7 * sc, y + 14 * sc, 14 * sc, 2.5 * sc))


class MechaHUD(Effect):
    """Mecha HUD: anéis segmentados a rodar, grelha hexagonal a pulsar e linha de varrimento."""

    def resize(self, w, h):
        super().resize(w, h)
        self.cx, self.cy = w * 0.72, h * 0.5
        self.R = min(w, h) * 0.36
        hexes = QPainterPath()
        r = 26
        dx, dy = r * 1.732, r * 1.5
        for row in range(int(h / dy) + 2):
            for col in range(int(w / dx) + 2):
                x = col * dx + (dx / 2 if row % 2 else 0)
                y = row * dy
                pts = [QPointF(x + r * math.cos(math.radians(60 * i + 30)), y + r * math.sin(math.radians(60 * i + 30)))
                       for i in range(6)]
                hexes.moveTo(pts[0])
                for pt in pts[1:]:
                    hexes.lineTo(pt)
                hexes.closeSubpath()
        self.hexes = hexes

    def paint(self, p, t):
        w, h = self.w, self.h
        pulse = 0.5 + 0.5 * math.sin(t * 1.2)
        p.setPen(QPen(_col("accent", int(18 + 22 * pulse)), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.hexes)
        cx, cy, R = self.cx, self.cy, self.R
        for k, (rr, segs, speed, width, colname) in enumerate((
                (1.0, 24, 12, 3, "accent"), (0.82, 8, -20, 6, "accent2"), (0.66, 48, 30, 2, "accent"),
                (0.5, 3, -45, 10, "accent2"))):
            p.setPen(QPen(_col(colname, 150 if k % 2 == 0 else 110), width, Qt.SolidLine, Qt.FlatCap))
            rect = QRectF(cx - R * rr, cy - R * rr, 2 * R * rr, 2 * R * rr)
            span = 360 / segs
            for i in range(segs):
                start = (i * span + t * speed) % 360
                p.drawArc(rect, int(start * 16), int(span * 0.6 * 16))
        # mira e marcas
        p.setPen(QPen(_col("accent", 160), 1))
        p.drawLine(QPointF(cx - R * 1.15, cy), QPointF(cx - R * 0.2, cy))
        p.drawLine(QPointF(cx + R * 0.2, cy), QPointF(cx + R * 1.15, cy))
        p.drawLine(QPointF(cx, cy - R * 1.15), QPointF(cx, cy - R * 0.2))
        p.drawLine(QPointF(cx, cy + R * 0.2), QPointF(cx, cy + R * 1.15))
        # radar a varrer
        a = (t * 70) % 360
        g = QLinearGradient(QPointF(cx, cy), QPointF(cx + R * math.cos(math.radians(a)), cy - R * math.sin(math.radians(a))))
        g.setColorAt(0, _col("accent2", 0))
        g.setColorAt(1, _col("accent2", 180))
        p.setPen(QPen(g, 2))
        p.drawLine(QPointF(cx, cy), QPointF(cx + R * 0.98 * math.cos(math.radians(a)),
                                           cy - R * 0.98 * math.sin(math.radians(a))))
        sy = (t * 90) % (h + 100) - 50
        sg = QLinearGradient(0, sy - 30, 0, sy + 30)
        sg.setColorAt(0, QColor(0, 0, 0, 0))
        sg.setColorAt(0.5, _col("accent", 30))
        sg.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(QRectF(0, sy - 30, w, 60), sg)


class Kawaii(Effect):
    """Kawaii: corações, estrelas e bolhas em tons pastel a flutuar (tema claro)."""
    N = 40

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(1234)
        self.items = [[rnd.uniform(0, w), rnd.uniform(0, h), rnd.uniform(8, 26), rnd.choice("hsb"), rnd.uniform(0, 6.28),
                       rnd.uniform(8, 20), rnd.randrange(6)] for _ in range(self.N)]
        heart = QPainterPath(QPointF(0, 0.35))
        heart.cubicTo(QPointF(-1.1, -0.35), QPointF(-0.45, -1.05), QPointF(0, -0.45))
        heart.cubicTo(QPointF(0.45, -1.05), QPointF(1.1, -0.35), QPointF(0, 0.35))
        heart.lineTo(QPointF(0, 0.75))
        self.heart = heart
        star = QPainterPath()
        for i in range(10):
            r = 1.0 if i % 2 == 0 else 0.45
            a = math.radians(-90 + 36 * i)
            pt = QPointF(r * math.cos(a), r * math.sin(a))
            star.moveTo(pt) if i == 0 else star.lineTo(pt)
        star.closeSubpath()
        self.star = star
        self.last = None

    def paint(self, p, t):
        dt = 0 if self.last is None else min(0.1, t - self.last)
        self.last = t
        w, h = self.w, self.h
        g = QLinearGradient(0, 0, w, h)
        g.setColorAt(0, QColor(255, 228, 242, 160))
        g.setColorAt(1, QColor(226, 222, 255, 160))
        p.fillRect(QRectF(0, 0, w, h), g)
        cols = theme.C["series"]
        p.setPen(Qt.NoPen)
        for it in self.items:
            x0, y, size, kind, ph, spd, ci = it
            y -= spd * dt
            if y < -40:
                y = h + 40
                it[0] = random.uniform(0, w)
            it[1] = y
            x = x0 + 14 * math.sin(t * 0.7 + ph)
            c = QColor(cols[ci % len(cols)])
            c.setAlpha(120)
            p.save()
            p.translate(x, y)
            p.rotate(15 * math.sin(t + ph))
            p.scale(size, size)
            p.setBrush(c)
            if kind == "h":
                p.drawPath(self.heart)
            elif kind == "s":
                p.drawPath(self.star)
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(c, 0.12))
                p.drawEllipse(QPointF(0, 0), 0.8, 0.8)
                p.setPen(Qt.NoPen)
            p.restore()


class Fireflies(Effect):
    """Pirilampos: floresta à noite, silhuetas de erva e luzes que vagueiam e piscam."""
    N = 70

    def resize(self, w, h):
        super().resize(w, h)
        rnd = random.Random(55)
        self.f = [[rnd.uniform(0, w), rnd.uniform(h * 0.25, h), rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0),
                   rnd.uniform(1.5, 3.2)] for _ in range(self.N)]
        grass = QPainterPath(QPointF(0, h))
        x = 0.0
        while x < w:
            bh = rnd.uniform(h * 0.05, h * 0.2)
            grass.lineTo(x + rnd.uniform(2, 6), h - bh)
            x += rnd.uniform(6, 14)
            grass.lineTo(x, h)
        grass.lineTo(w, h)
        grass.closeSubpath()
        trees = QPainterPath()
        for i in range(9):
            tx = w * (i + rnd.uniform(-0.3, 0.3)) / 8
            th = h * rnd.uniform(0.45, 0.8)
            trees.addRect(QRectF(tx - 8, h - th, 16, th))
            trees.addEllipse(QPointF(tx, h - th), rnd.uniform(50, 110), rnd.uniform(70, 140))
        def draw_trees(q):
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(4, 18, 12, 200))
            q.drawPath(trees.simplified())

        def draw_grass(q):
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(2, 10, 6, 235))
            q.drawPath(grass)
        self.trees_px = _layer(w, h, draw_trees)
        self.grass_px = _layer(w, h, draw_grass)

    def paint(self, p, t):
        w = self.w
        p.setPen(Qt.NoPen)
        p.drawPixmap(0, 0, self.trees_px)
        for q in self.f:
            x, y, ph, spd, r = q
            q[0] = (x + math.cos(t * 0.4 * spd + ph) * 0.6) % w
            q[1] = y + math.sin(t * 0.5 * spd + ph * 2) * 0.4
            blink = max(0.0, math.sin(t * 1.6 * spd + ph * 5))
            if blink < 0.05:
                continue
            g = QRadialGradient(QPointF(q[0], q[1]), r * 6)
            g.setColorAt(0, _col("accent", int(220 * blink)))
            g.setColorAt(0.3, _col("accent2", int(90 * blink)))
            g.setColorAt(1, QColor(0, 0, 0, 0))
            p.setBrush(g)
            p.drawEllipse(QPointF(q[0], q[1]), r * 6, r * 6)
        p.drawPixmap(0, 0, self.grass_px)


EFFECTS = {"plexus": Plexus, "grid": NeonGrid, "sunset": Sunset, "rain": DigitalRain, "aurora": Aurora,
           "petals": Petals, "rainwin": RainWindow, "sky": SummerSky, "comet": Comet, "lanterns": Lanterns,
           "hud": MechaHUD, "kawaii": Kawaii, "fireflies": Fireflies}


# =========================================================================== fundo da janela
class Backdrop(QWidget):
    """Widget raiz da janela: pinta o fundo; os filhos ficam translúcidos por cima."""

    def __init__(self):
        super().__init__()
        self.setAttribute(Qt.WA_OpaquePaintEvent)
        self.effect: Effect | None = None
        self.effect_key = None
        self._t0 = time.monotonic()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._covers: list[QWidget] = []
        self._covers_at = 0.0
        # papel de parede
        self._wp_path = None
        self._wp_src: QImage | None = None     # imagem original (estática)
        self._wp_scaled: QPixmap | None = None  # já escalada/desfocada para o tamanho atual
        self._movie: QMovie | None = None
        self._player = None
        self._sink = None
        self._frame: QImage | None = None
        self.paused = False
        self.reload()

    # ------------------------------------------------------------------ configuração
    def reload(self):
        """Lê o tema e as definições atuais (chamar depois de mudar tema/fundo)."""
        key = theme.C.get("effect")
        if key != self.effect_key:
            self.effect_key = key
            self.effect = EFFECTS[key]() if key in EFFECTS else None
            if self.effect:
                self.effect.resize(self.width(), self.height())
        self._load_wallpaper(None)  # o fundo da interface foi retirado (ver página "Fundo do ambiente de trabalho")
        self._sync_timer()
        self.update()

    def _load_wallpaper(self, path):
        if path == self._wp_path and (self._wp_src is not None or self._movie or self._player):
            self._rescale()
            return
        self._stop_media()
        self._wp_path = path
        self._wp_src = None
        self._wp_scaled = None
        self._frame = None
        if not path or not os.path.exists(path):
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in GIF_EXT:
            self._movie = QMovie(path)
            self._movie.setCacheMode(QMovie.CacheAll)
            self._movie.frameChanged.connect(self._gif_frame)
            self._movie.start()
        elif ext in VIDEO_EXT:
            try:
                from PySide6.QtMultimedia import QMediaPlayer, QVideoSink
                from PySide6.QtCore import QUrl
            except ImportError:
                return
            self._player = QMediaPlayer(self)
            self._sink = QVideoSink(self)
            self._sink.videoFrameChanged.connect(self._video_frame)
            self._player.setVideoSink(self._sink)
            self._player.setLoops(QMediaPlayer.Infinite)
            self._player.setSource(QUrl.fromLocalFile(path))
            self._player.play()
        else:
            img = QImage(path)
            if not img.isNull():
                self._wp_src = img
                self._rescale()

    def _stop_media(self):
        if self._movie:
            self._movie.stop()
            self._movie.deleteLater()
            self._movie = None
        if self._player:
            self._player.stop()
            self._player.deleteLater()
            self._sink.deleteLater()
            self._player = self._sink = None

    def _gif_frame(self, _n):
        self._frame = self._movie.currentImage()
        if not self._timer.isActive():
            self._tick()

    def _video_frame(self, frame):
        img = frame.toImage()
        if not img.isNull():
            self._frame = img
            if not self._timer.isActive():
                self._tick()

    def _rescale(self):
        """Escala (com margem para deslizar) e desfoca a imagem estática uma única vez."""
        if self._wp_src is None or self.width() < 2:
            return
        w, h = int(self.width() * 1.08), int(self.height() * 1.08)
        img = self._wp_src.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        blur = int(get_setting("wallpaper_blur", 0))
        if blur:
            f = 2 ** (blur + 1)
            img = img.scaled(max(1, img.width() // f), max(1, img.height() // f), Qt.IgnoreAspectRatio,
                             Qt.SmoothTransformation).scaled(img.width(), img.height(), Qt.IgnoreAspectRatio,
                                                             Qt.SmoothTransformation)
        self._wp_scaled = QPixmap.fromImage(img)

    # ------------------------------------------------------------------ animação
    def animated(self) -> bool:
        return bool(self.effect) or bool(self._wp_scaled is not None and get_setting("wallpaper_motion", True))

    def set_paused(self, paused: bool):
        if paused == self.paused:
            return
        self.paused = paused
        if self._movie:
            self._movie.setPaused(paused)
        if self._player:
            (self._player.pause if paused else self._player.play)()
        self._sync_timer()

    def _sync_timer(self):
        if self.animated() and get_setting("bg_animate", True) and not self.paused:
            fps = max(5, min(60, int(get_setting("bg_fps", 30))))
            self._timer.start(int(1000 / fps))
        else:
            self._timer.stop()

    def _tick(self):
        """Redesenha só o que se vê do fundo. Por baixo de cartões quase opacos o fundo fica parado:
        assim o Qt não tem de redesenhar todos os cartões/gráficos a cada fotograma (muito menos CPU)."""
        if get_setting("glass_opacity", 85) < 70:
            self.update()
            return
        now = time.monotonic()
        if now - self._covers_at > 1.0:
            self._covers_at = now
            self._covers = [f for f in self.findChildren(QFrame) if f.objectName() in ("Card", "Sidebar")]
        region = QRegion(self.rect())
        for wdg in self._covers:
            try:
                if wdg.isVisible():
                    region -= QRegion(QRect(wdg.mapTo(self, QPoint(0, 0)), wdg.size()).adjusted(2, 2, -2, -2))
            except RuntimeError:  # cartão apagado entretanto: refaz a lista no próximo fotograma
                self._covers_at = 0.0
                self.update()
                return
        self.update(region)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._covers_at = 0.0
        if self.effect:
            self.effect.resize(self.width(), self.height())
        self._rescale()

    # ------------------------------------------------------------------ pintura
    def paintEvent(self, _e):
        p = QPainter(self)
        w, h = self.width(), self.height()
        t = time.monotonic() - self._t0
        p.fillRect(self.rect(), QColor(theme.C["bg"]))
        has_wp = False
        if self._wp_scaled is not None:
            pm = self._wp_scaled
            mx, my = pm.width() / pm.devicePixelRatio() - w, pm.height() / pm.devicePixelRatio() - h
            if get_setting("wallpaper_motion", True):
                x = -mx / 2 - mx / 2 * math.sin(t * 2 * math.pi / 60)
                y = -my / 2 - my / 2 * math.cos(t * 2 * math.pi / 75)
            else:
                x, y = -mx / 2, -my / 2
            p.drawPixmap(QPointF(x, y), pm)
            has_wp = True
        elif self._frame is not None and not self._frame.isNull():
            img = self._frame
            sz = img.size().scaled(QSize(w, h), Qt.KeepAspectRatioByExpanding)
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            p.drawImage(QRectF((w - sz.width()) / 2, (h - sz.height()) / 2, sz.width(), sz.height()), img)
            has_wp = True
        if has_wp:
            dim = QColor(theme.C["bg"])
            dim.setAlpha(int(255 * max(0, min(95, get_setting("wallpaper_dim", 55))) / 100))
            p.fillRect(self.rect(), dim)
        if self.effect and (not has_wp or get_setting("effect_over_wallpaper", False)):
            p.setRenderHint(QPainter.Antialiasing)
            self.effect.paint(p, t)
        p.end()


_previews: dict[tuple[str, int, int], QPixmap] = {}


def preview(key: str, w: int = 340, h: int = 200) -> QPixmap:
    """Miniatura do fundo de um tema (fotograma do efeito real), para a galeria de temas."""
    ck = (key, w, h)
    if ck in _previews:
        return _previews[ck]
    saved = dict(theme.C)
    theme.C.clear()
    theme.C.update(theme.THEMES[key])
    try:
        img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
        img.fill(QColor(theme.C["bg"]))
        eff_key = theme.C.get("effect")
        if eff_key in EFFECTS:
            eff = EFFECTS[eff_key]()
            eff.resize(w, h)
            scratch = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
            for i in range(24):  # aquece efeitos com estado (chuva, pétalas…)
                q = QPainter(scratch)
                eff.paint(q, 2.0 + i / 12)
                q.end()
            p = QPainter(img)
            p.setRenderHint(QPainter.Antialiasing)
            eff.paint(p, 4.0)
            p.end()
        pm = QPixmap.fromImage(img)
    finally:
        theme.C.clear()
        theme.C.update(saved)
    _previews[ck] = pm
    return pm
