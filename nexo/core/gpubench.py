"""Benchmark da placa gráfica (OpenGL): desenha uma cena 3D com ray marching (esferas, chão em xadrez,
sombras suaves, oclusão ambiente e reflexos) inteiramente no shader, numa imagem fora do ecrã.

Corre num processo à parte (`Nexo --gpubench`) para que um problema no driver não feche o Nexo; envia o
progresso em linhas JSON pelo stdout. Nota = fotogramas por segundo × 10 (cena e resolução fixas, por isso
as notas são comparáveis entre PCs)."""
from __future__ import annotations

import json
import sys
import time

RESOLUTIONS = {"1080p": (1920, 1080), "1440p": (2560, 1440), "4k": (3840, 2160)}
WARMUP_S = 2.0
DURATION_S = 15.0

VERT = """
attribute vec2 pos;
varying vec2 uv;
void main() { uv = pos * 0.5 + 0.5; gl_Position = vec4(pos, 0.0, 1.0); }
"""

FRAG = """
#ifdef GL_ES
precision highp float;
#endif
uniform vec2 res;
uniform float t;
varying vec2 uv;

float sdSphere(vec3 p, float r) { return length(p) - r; }
float sdTorus(vec3 p, vec2 q) { vec2 d = vec2(length(p.xz) - q.x, p.y); return length(d) - q.y; }

vec2 map(vec3 p) {
    vec2 r = vec2(p.y + 1.0, 1.0);                        // chão
    for (int i = 0; i < 6; i++) {
        float a = float(i) * 1.0472 + t * 0.4;
        vec3 c = vec3(cos(a) * 2.2, -0.35 + 0.25 * sin(t * 1.3 + float(i)), sin(a) * 2.2);
        float d = sdSphere(p - c, 0.65);
        if (d < r.x) r = vec2(d, 2.0 + float(i));
    }
    vec3 q = p - vec3(0.0, 0.1 + 0.3 * sin(t), 0.0);
    float c = cos(t * 0.7), s = sin(t * 0.7);
    q.xy = mat2(c, -s, s, c) * q.xy;
    float d = sdTorus(q, vec2(0.9, 0.28));
    if (d < r.x) r = vec2(d, 9.0);
    return r;
}

vec3 normal(vec3 p) {
    vec2 e = vec2(0.001, 0.0);
    return normalize(vec3(map(p + e.xyy).x - map(p - e.xyy).x, map(p + e.yxy).x - map(p - e.yxy).x,
                          map(p + e.yyx).x - map(p - e.yyx).x));
}

vec2 march(vec3 ro, vec3 rd) {
    float d = 0.0;
    for (int i = 0; i < 160; i++) {
        vec2 h = map(ro + rd * d);
        if (h.x < 0.0005 * d) return vec2(d, h.y);
        d += h.x;
        if (d > 40.0) break;
    }
    return vec2(-1.0, 0.0);
}

float shadow(vec3 ro, vec3 rd) {
    float res = 1.0, d = 0.02;
    for (int i = 0; i < 64; i++) {
        float h = map(ro + rd * d).x;
        res = min(res, 10.0 * h / d);
        d += clamp(h, 0.02, 0.3);
        if (res < 0.001 || d > 12.0) break;
    }
    return clamp(res, 0.0, 1.0);
}

float ao(vec3 p, vec3 n) {
    float o = 0.0, w = 1.0;
    for (int i = 1; i <= 6; i++) {
        float h = 0.03 * float(i);
        o += w * (h - map(p + n * h).x);
        w *= 0.75;
    }
    return clamp(1.0 - 4.0 * o, 0.0, 1.0);
}

vec3 albedo(vec3 p, float m) {
    if (m < 1.5) return mix(vec3(0.85), vec3(0.18), mod(floor(p.x) + floor(p.z), 2.0));
    if (m > 8.5) return vec3(0.95, 0.75, 0.3);
    return 0.5 + 0.45 * cos(6.2831 * (m * 0.13 + vec3(0.0, 0.33, 0.67)));
}

vec3 shade(vec3 ro, vec3 rd, out vec3 hitP, out vec3 hitN, out float hitM) {
    vec2 h = march(ro, rd);
    vec3 sky = mix(vec3(0.55, 0.65, 0.85), vec3(0.12, 0.15, 0.28), clamp(rd.y * 1.5, 0.0, 1.0));
    hitM = -1.0;
    if (h.x < 0.0) return sky;
    vec3 p = ro + rd * h.x, n = normal(p);
    hitP = p; hitN = n; hitM = h.y;
    vec3 l = normalize(vec3(0.6, 0.8, 0.4));
    float dif = max(dot(n, l), 0.0) * shadow(p + n * 0.002, l);
    float spe = pow(max(dot(reflect(rd, n), l), 0.0), 48.0) * dif;
    float a = ao(p, n);
    vec3 col = albedo(p, h.y) * (0.15 * a + 1.1 * dif * vec3(1.0, 0.95, 0.85)) + spe;
    return mix(col, sky, 1.0 - exp(-0.002 * h.x * h.x));
}

void main() {
    vec2 p = (uv * res * 2.0 - res) / res.y;
    float a = t * 0.15;
    vec3 ro = vec3(6.0 * cos(a), 2.2, 6.0 * sin(a));
    vec3 ww = normalize(-ro), uu = normalize(cross(ww, vec3(0.0, 1.0, 0.0))), vv = cross(uu, ww);
    vec3 rd = normalize(p.x * uu + p.y * vv + 1.8 * ww);
    vec3 hp, hn; float hm;
    vec3 col = shade(ro, rd, hp, hn, hm);
    if (hm > 1.5) {                                        // um reflexo nas esferas e no toro
        vec3 hp2, hn2; float hm2;
        vec3 rcol = shade(hp + hn * 0.003, reflect(rd, hn), hp2, hn2, hm2);
        col = mix(col, rcol, 0.3);
    }
    col = pow(col / (1.0 + col), vec3(0.4545));
    gl_FragColor = vec4(col, 1.0);
}
"""


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def run_child(resolution: str = "1080p", duration: float = DURATION_S, image_path: str | None = None) -> int:
    """Corpo do processo `--gpubench`. Escreve {"ev": "info"|"progress"|"done"|"error", ...}."""
    import os
    if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # sem sessão gráfica (não abre janelas de qualquer forma)
    from PySide6.QtGui import QGuiApplication, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import (QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLFramebufferObjectFormat,
                                  QOpenGLShader, QOpenGLShaderProgram)
    import array

    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])  # noqa: F841 (tem de existir)
    w, h = RESOLUTIONS.get(resolution, RESOLUTIONS["1080p"])
    fmt = QSurfaceFormat()
    fmt.setSwapInterval(0)
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create():
        _emit({"ev": "error", "msg": "Não foi possível criar um contexto OpenGL (driver da placa gráfica?)."})
        return 2
    surf = QOffscreenSurface()
    surf.setFormat(ctx.format())
    surf.create()
    if not ctx.makeCurrent(surf):
        _emit({"ev": "error", "msg": "O contexto OpenGL não ficou ativo."})
        return 2
    f = ctx.functions()
    renderer = f.glGetString(0x1F01) or "?"
    version = f.glGetString(0x1F02) or "?"
    _emit({"ev": "info", "renderer": renderer, "version": version, "w": w, "h": h})
    if "llvmpipe" in renderer.lower() or "software" in renderer.lower() or "gdi generic" in renderer.lower():
        _emit({"ev": "warn", "msg": "O OpenGL está a usar renderização por software (CPU), não a placa gráfica."})

    ffmt = QOpenGLFramebufferObjectFormat()
    fbo = QOpenGLFramebufferObject(w, h, ffmt)
    if not fbo.isValid():
        _emit({"ev": "error", "msg": "A placa não aceitou a imagem fora do ecrã nesta resolução."})
        return 2
    prog = QOpenGLShaderProgram()
    if not (prog.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
            and prog.addShaderFromSourceCode(QOpenGLShader.Fragment, FRAG) and prog.link()):
        _emit({"ev": "error", "msg": "O shader não compilou: " + prog.log()[:500]})
        return 2
    quad = array.array("f", [-1, -1, 1, -1, -1, 1, 1, 1])
    vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
    vbo.create()
    vbo.bind()
    vbo.allocate(quad.tobytes(), len(quad) * 4)
    fbo.bind()
    prog.bind()
    loc = prog.attributeLocation("pos")
    prog.enableAttributeArray(loc)
    prog.setAttributeBuffer(loc, 0x1406, 0, 2)   # GL_FLOAT
    prog.setUniformValue("res", float(w), float(h))
    f.glViewport(0, 0, w, h)

    def frame(tt: float):
        prog.setUniformValue1f("t", tt) if hasattr(prog, "setUniformValue1f") else prog.setUniformValue("t", tt)
        f.glDrawArrays(0x0005, 0, 4)              # GL_TRIANGLE_STRIP
        f.glFinish()

    # aquecimento (a placa sobe as frequências; compilação final do shader no driver)
    t0 = time.perf_counter()
    while time.perf_counter() - t0 < WARMUP_S:
        frame(0.0)
    frames, sim_t = 0, 0.0
    t0 = last = time.perf_counter()
    ftimes: list[float] = []
    while True:
        a = time.perf_counter()
        if a - t0 >= duration:
            break
        frame(sim_t)
        b = time.perf_counter()
        ftimes.append(b - a)
        sim_t += 1 / 60          # animação determinística: a mesma sequência de imagens em qualquer PC
        frames += 1
        if b - last > 0.25:
            last = b
            _emit({"ev": "progress", "frac": (b - t0) / duration, "fps": frames / (b - t0)})
    total = time.perf_counter() - t0
    fps = frames / total
    ftimes.sort(reverse=True)
    worst = ftimes[: max(1, len(ftimes) // 100)]
    low1 = 1 / (sum(worst) / len(worst)) if worst else fps
    if image_path:
        try:
            frame(sim_t)
            fbo.toImage().save(image_path)
        except Exception:  # noqa: BLE001 — a imagem é só para mostrar
            image_path = None
    fbo.release()
    ctx.doneCurrent()
    _emit({"ev": "done", "fps": fps, "low1": low1, "frames": frames, "score": round(fps * 10),
           "renderer": renderer, "w": w, "h": h, "image": image_path})
    return 0


def main_from_argv(argv: list[str]) -> int:
    res = "1080p"
    img = None
    dur = DURATION_S
    for i, a in enumerate(argv):
        if a == "--res" and i + 1 < len(argv):
            res = argv[i + 1]
        elif a == "--image" and i + 1 < len(argv):
            img = argv[i + 1]
        elif a == "--seconds" and i + 1 < len(argv):
            dur = float(argv[i + 1])
    try:
        return run_child(res, dur, img)
    except Exception as e:  # noqa: BLE001
        _emit({"ev": "error", "msg": f"{type(e).__name__}: {e}"})
        return 1


def child_command(resolution: str, image_path: str, seconds: float = DURATION_S) -> list[str]:
    base = [sys.executable, "--gpubench"] if getattr(sys, "frozen", False) else \
        [sys.executable, "-m", "nexo", "--gpubench"]
    return base + ["--res", resolution, "--image", image_path, "--seconds", str(seconds)]
