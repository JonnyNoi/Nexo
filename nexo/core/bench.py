"""Benchmark de CPU: path tracer monocromático próprio (princípio do Cinebench).

A imagem é dividida em blocos de 32 px distribuídos pelos processos, do centro para fora.
Cada bloco usa uma semente fixa, por isso a imagem é sempre a mesma (determinística)
e a nota mede apenas a velocidade: nota = amostras por segundo ÷ 1000.
"""
from __future__ import annotations

import math
import random

WIDTH, HEIGHT, TILE = 480, 270, 32
MAX_DEPTH = 5

QUALITY = {"Rápido": 32, "Normal": 96, "Alta": 256}

# esferas: (cx, cy, cz, raio, material, parâmetro)
# material: 0 difuso (albedo), 1 metal (rugosidade), 2 vidro (índice de refração), 3 luz (intensidade)
SPHERES = [
    (0.0, 1.0, 0.0, 1.0, 2, 1.5),
    (-2.2, 0.8, 0.6, 0.8, 1, 0.05),
    (2.1, 0.7, 0.4, 0.7, 0, 0.8),
    (0.9, 0.35, -1.6, 0.35, 1, 0.3),
    (-0.9, 0.3, -1.7, 0.3, 0, 0.5),
    (1.6, 0.25, -1.0, 0.25, 2, 1.5),
    (-0.6, 4.2, -0.8, 1.0, 3, 6.0),
    (-1.5, 0.4, 2.6, 0.4, 0, 0.9),
    (3.4, 1.1, 2.4, 1.1, 1, 0.0),
]

# câmara
_EYE = (0.0, 1.6, -6.2)
_LOOK = (0.0, 0.8, 0.0)
_FOV = 38.0


def _camera():
    ex, ey, ez = _EYE
    fx, fy, fz = _LOOK[0] - ex, _LOOK[1] - ey, _LOOK[2] - ez
    fl = math.sqrt(fx * fx + fy * fy + fz * fz)
    fx, fy, fz = fx / fl, fy / fl, fz / fl
    # direita = forward × up(0,1,0)
    rx, ry, rz = fz, 0.0, -fx
    rl = math.sqrt(rx * rx + rz * rz)
    rx, rz = rx / rl, rz / rl
    # cima = forward × direita
    ux, uy, uz = fy * rz - fz * ry, fz * rx - fx * rz, fx * ry - fy * rx
    h = math.tan(math.radians(_FOV) / 2)
    w = h * WIDTH / HEIGHT
    return (fx, fy, fz), (rx * w, ry * w, rz * w), (ux * h, uy * h, uz * h)


_FWD, _RIGHT, _UP = _camera()


def _trace(ox, oy, oz, dx, dy, dz, rnd) -> float:
    spheres = SPHERES
    sqrt = math.sqrt
    throughput = 1.0
    radiance = 0.0
    for _depth in range(MAX_DEPTH):
        # ---------- interseção mais próxima
        best = 1e30
        hit = None
        for s in spheres:
            lx, ly, lz = ox - s[0], oy - s[1], oz - s[2]
            b = lx * dx + ly * dy + lz * dz
            c = lx * lx + ly * ly + lz * lz - s[3] * s[3]
            disc = b * b - c
            if disc > 0:
                sd = sqrt(disc)
                t = -b - sd
                if t < 1e-4:
                    t = -b + sd
                if 1e-4 < t < best:
                    best = t
                    hit = s
        plane = False
        if dy < -1e-6:
            t = -oy / dy
            if 1e-4 < t < best:
                best = t
                hit = None
                plane = True

        if hit is None and not plane:
            # céu: gradiente suave
            radiance += throughput * (0.12 + 0.75 * max(0.0, dy))
            break

        px, py, pz = ox + dx * best, oy + dy * best, oz + dz * best
        if plane:
            nx, ny, nz = 0.0, 1.0, 0.0
            mat = 0
            checker = (int(math.floor(px * 0.9)) + int(math.floor(pz * 0.9))) & 1
            param = 0.7 if checker else 0.3
        else:
            r = hit[3]
            nx, ny, nz = (px - hit[0]) / r, (py - hit[1]) / r, (pz - hit[2]) / r
            mat, param = hit[4], hit[5]

        if mat == 3:
            radiance += throughput * param
            break

        cos_i = dx * nx + dy * ny + dz * nz
        if mat == 0:
            # difuso: direção cosseno-ponderada (normal + vector unitário aleatório)
            if cos_i > 0:
                nx, ny, nz = -nx, -ny, -nz
            z = 2.0 * rnd() - 1.0
            a = 6.283185307 * rnd()
            rr = sqrt(1.0 - z * z)
            dx, dy, dz = nx + rr * math.cos(a), ny + rr * math.sin(a), nz + z
            l = sqrt(dx * dx + dy * dy + dz * dz) or 1.0
            dx, dy, dz = dx / l, dy / l, dz / l
            throughput *= param
        elif mat == 1:
            # metal: reflexão especular com rugosidade
            dx, dy, dz = dx - 2 * cos_i * nx, dy - 2 * cos_i * ny, dz - 2 * cos_i * nz
            if param > 0:
                z = 2.0 * rnd() - 1.0
                a = 6.283185307 * rnd()
                rr = sqrt(1.0 - z * z) * param
                dx, dy, dz = dx + rr * math.cos(a), dy + rr * math.sin(a), dz + z * param
                l = sqrt(dx * dx + dy * dy + dz * dz) or 1.0
                dx, dy, dz = dx / l, dy / l, dz / l
            if dx * nx + dy * ny + dz * nz <= 0:
                break
            throughput *= 0.85
        else:
            # vidro: refração com Fresnel (aproximação de Schlick)
            if cos_i < 0:
                eta = 1.0 / param
                cos_i = -cos_i
                fnx, fny, fnz = nx, ny, nz
            else:
                eta = param
                fnx, fny, fnz = -nx, -ny, -nz
            k = 1.0 - eta * eta * (1.0 - cos_i * cos_i)
            r0 = ((1 - param) / (1 + param)) ** 2
            fres = r0 + (1 - r0) * (1 - cos_i) ** 5
            if k < 0 or rnd() < fres:
                d = dx * fnx + dy * fny + dz * fnz
                dx, dy, dz = dx - 2 * d * fnx, dy - 2 * d * fny, dz - 2 * d * fnz
            else:
                sk = sqrt(k)
                dx = eta * dx + (eta * cos_i - sk) * fnx
                dy = eta * dy + (eta * cos_i - sk) * fny
                dz = eta * dz + (eta * cos_i - sk) * fnz
        ox, oy, oz = px, py, pz
        # roleta russa depois de 3 ressaltos
        if _depth >= 3:
            if rnd() > throughput:
                break
            throughput = min(1.0, throughput / max(throughput, 1e-3))
    return radiance


def render_tile(args: tuple[int, int, int]) -> tuple[int, int, int, int, bytes, int]:
    """Renderiza um bloco. args = (tx, ty, spp). Devolve (x, y, w, h, pixels cinzentos, amostras)."""
    tx, ty, spp = args
    x0, y0 = tx * TILE, ty * TILE
    w, h = min(TILE, WIDTH - x0), min(TILE, HEIGHT - y0)
    rng = random.Random((ty * 1000 + tx) * 7919 + spp)
    rnd = rng.random
    fx, fy, fz = _FWD
    rx, ry, rz = _RIGHT
    ux, uy, uz = _UP
    ex, ey, ez = _EYE
    out = bytearray(w * h)
    i = 0
    for y in range(y0, y0 + h):
        for x in range(x0, x0 + w):
            acc = 0.0
            for _ in range(spp):
                sx = ((x + rnd()) / WIDTH) * 2 - 1
                sy = 1 - ((y + rnd()) / HEIGHT) * 2
                dx = fx + rx * sx + ux * sy
                dy = fy + ry * sx + uy * sy
                dz = fz + rz * sx + uz * sy
                l = math.sqrt(dx * dx + dy * dy + dz * dz)
                acc += _trace(ex, ey, ez, dx / l, dy / l, dz / l, rnd)
            v = acc / spp
            v = v / (1 + v) * 1.6  # tone mapping simples
            out[i] = max(0, min(255, int(math.sqrt(max(v, 0)) * 255)))
            i += 1
    return x0, y0, w, h, bytes(out), w * h * spp


def tiles(spp: int, subset: int = 1) -> list[tuple[int, int, int]]:
    """Lista de blocos ordenada do centro para fora. subset=N usa só 1 em cada N blocos."""
    nx = (WIDTH + TILE - 1) // TILE
    ny = (HEIGHT + TILE - 1) // TILE
    cx, cy = (nx - 1) / 2, (ny - 1) / 2
    all_t = sorted(((tx, ty) for ty in range(ny) for tx in range(nx)),
                   key=lambda t: (t[0] - cx) ** 2 + (t[1] - cy) ** 2)
    return [(tx, ty, spp) for k, (tx, ty) in enumerate(all_t) if k % subset == 0]
