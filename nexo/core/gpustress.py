"""Stress test da placa gráfica com teste da memória de vídeo (VRAM).

Corre num processo à parte (`Nexo --gpustress`), como o benchmark: um problema no driver não fecha o Nexo.
- Carga: a cena 3D do benchmark (ray marching) em 1440p sem parar.
- VRAM: enche a memória com texturas de 64 MB (4096×4096 RGBA8) com um padrão que depende da posição e de
  uma "semente"; depois, à vez, a própria placa confirma cada textura (shader de verificação que compara
  píxel a píxel e devolve só uma imagem pequena com os erros) e volta a preenchê-la com outra semente.
  O padrão usa só inteiros pequenos e divisões por 256, por isso é exato em vírgula flutuante — qualquer
  diferença é um erro de memória (VRAM instável: overclock, temperatura, placa com defeito).

Envia o progresso em linhas JSON pelo stdout ({"ev": "info"|"progress"|"error"|"done"|"warn", ...})."""
from __future__ import annotations

import json
import os
import re
import sys
import time

from .gpubench import FRAG, VERT

TEX = 4096                 # lado de cada textura (64 MB em RGBA8)
TEX_MB = TEX * TEX * 4 // 2**20
OUT = 256                  # lado da imagem de verificação (cada píxel resume um bloco de 16×16)
SCENE = (2560, 1440)

FILL = """
uniform float seed;
vec4 pat(vec2 c, float s) {
    return vec4(mod(c.x * 7.0 + c.y * 13.0 + s * 31.0, 256.0), mod(c.x * 3.0 + c.y * 29.0 + s * 17.0, 256.0),
                mod(c.x * 11.0 + c.y * 5.0 + s * 41.0, 256.0), mod(c.x + c.y * 19.0 + s * 7.0, 256.0));
}
void main() { gl_FragColor = pat(floor(gl_FragCoord.xy), seed) / 255.0; }
"""

VERIFY = """
uniform sampler2D tex;
uniform float seed;
vec4 pat(vec2 c, float s) {
    return vec4(mod(c.x * 7.0 + c.y * 13.0 + s * 31.0, 256.0), mod(c.x * 3.0 + c.y * 29.0 + s * 17.0, 256.0),
                mod(c.x * 11.0 + c.y * 5.0 + s * 41.0, 256.0), mod(c.x + c.y * 19.0 + s * 7.0, 256.0));
}
void main() {
    vec2 base = floor(gl_FragCoord.xy) * 16.0;
    float bad = 0.0;
    for (int i = 0; i < 16; i++) {
        for (int j = 0; j < 16; j++) {
            vec2 c = base + vec2(float(i), float(j));
            vec4 d = abs(texture2D(tex, (c + 0.5) / 4096.0) * 255.0 - pat(c, seed));
            if (max(max(d.r, d.g), max(d.b, d.a)) > 0.5) bad += 1.0;
        }
    }
    gl_FragColor = vec4(min(bad, 255.0) / 255.0, 0.0, 0.0, 1.0);
}
"""


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


# --------------------------------------------------------------------------- quanta VRAM tem a placa
def vram_total_mb() -> int | None:
    from .util import IS_LINUX, IS_WIN, read_text, run, which
    if which("nvidia-smi"):
        code, out = run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"], timeout=10)
        nums = [int(x) for x in re.findall(r"\d+", out)] if code == 0 else []
        if nums:
            return max(nums)
    if IS_LINUX:
        import glob
        sizes = [int(read_text(p) or 0) for p in glob.glob("/sys/class/drm/card*/device/mem_info_vram_total")]
        if any(sizes):
            return max(sizes) // 2**20
    if IS_WIN:
        try:
            import winreg
            key = r"SYSTEM\CurrentControlSet\Control\Class\{4d36e968-e325-11ce-bfc1-08002be10318}"
            best = 0
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key) as k:
                for i in range(32):
                    try:
                        with winreg.OpenKey(k, f"{i:04d}") as sub:
                            v, _t = winreg.QueryValueEx(sub, "HardwareInformation.qwMemorySize")
                            best = max(best, int(v))
                    except OSError:
                        continue
            return best // 2**20 or None
        except OSError:
            return None
    return None


def default_vram_mb(total: int | None, pct: int = 60) -> int:
    """Quanto testar: uma parte da VRAM (o resto fica para o ambiente gráfico e o jogo/navegador abertos)."""
    if not total:
        return 1024
    return max(TEX_MB, int(total * pct / 100) // TEX_MB * TEX_MB)


def count_bad(rgba: bytes) -> int:
    """Soma dos píxeis errados a partir da imagem de verificação (canal vermelho, RGBA8888)."""
    return sum(rgba[0::4])


# --------------------------------------------------------------------------- processo filho
def run_child(seconds: float = 0, vram_mb: int = 1024) -> int:
    if sys.platform != "win32" and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import array

    from PySide6.QtGui import QGuiApplication, QImage, QOffscreenSurface, QOpenGLContext, QSurfaceFormat
    from PySide6.QtOpenGL import QOpenGLBuffer, QOpenGLFramebufferObject, QOpenGLShader, QOpenGLShaderProgram

    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])  # noqa: F841 (tem de existir)
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
    if any(s in renderer.lower() for s in ("llvmpipe", "software", "gdi generic")):
        _emit({"ev": "error", "msg": "O OpenGL está a usar renderização por software (CPU), não a placa gráfica."})
        return 2

    def program(frag: str):
        p = QOpenGLShaderProgram()
        if not (p.addShaderFromSourceCode(QOpenGLShader.Vertex, VERT)
                and p.addShaderFromSourceCode(QOpenGLShader.Fragment, frag) and p.link()):
            raise RuntimeError("O shader não compilou: " + p.log()[:400])
        return p

    def uni_f(p, name, v):
        (p.setUniformValue1f if hasattr(p, "setUniformValue1f") else p.setUniformValue)(name, float(v))

    def uni_i(p, name, v):
        (p.setUniformValue1i if hasattr(p, "setUniformValue1i") else p.setUniformValue)(name, int(v))

    try:
        scene, fill, verify = program(FRAG), program(FILL), program(VERIFY)
    except RuntimeError as e:
        _emit({"ev": "error", "msg": str(e)})
        return 2
    quad = array.array("f", [-1, -1, 1, -1, -1, 1, 1, 1])
    vbo = QOpenGLBuffer(QOpenGLBuffer.VertexBuffer)
    vbo.create()
    vbo.bind()
    vbo.allocate(quad.tobytes(), len(quad) * 4)

    def draw(p, fbo, w, h):
        fbo.bind()
        p.bind()
        loc = p.attributeLocation("pos")
        p.enableAttributeArray(loc)
        p.setAttributeBuffer(loc, 0x1406, 0, 2)   # GL_FLOAT
        f.glViewport(0, 0, w, h)
        f.glDrawArrays(0x0005, 0, 4)              # GL_TRIANGLE_STRIP

    scene_fbo = QOpenGLFramebufferObject(*SCENE)
    out_fbo = QOpenGLFramebufferObject(OUT, OUT)
    if not (scene_fbo.isValid() and out_fbo.isValid()):
        _emit({"ev": "error", "msg": "A placa não aceitou as imagens fora do ecrã."})
        return 2
    scene.bind()
    scene.setUniformValue("res", float(SCENE[0]), float(SCENE[1]))

    # ---- encher a VRAM
    texs: list = []
    seeds: list[int] = []
    while len(texs) * TEX_MB < vram_mb:
        t = QOpenGLFramebufferObject(TEX, TEX)
        if not t.isValid() or f.glGetError() == 0x0505:   # GL_OUT_OF_MEMORY
            break
        fill.bind()
        uni_f(fill, "seed", len(texs))
        draw(fill, t, TEX, TEX)
        f.glFinish()
        texs.append(t)
        seeds.append(len(seeds))
        if len(texs) % 8 == 0:
            _emit({"ev": "alloc", "mb": len(texs) * TEX_MB})
    if vram_mb and not texs:
        _emit({"ev": "warn", "msg": "Não foi possível reservar memória de vídeo — só a carga da placa é testada."})
    _emit({"ev": "info", "renderer": renderer, "vram_mb": len(texs) * TEX_MB, "w": SCENE[0], "h": SCENE[1]})

    def check(i: int) -> int:
        verify.bind()
        f.glActiveTexture(0x84C0)                 # GL_TEXTURE0
        f.glBindTexture(0x0DE1, texs[i].texture())
        uni_i(verify, "tex", 0)
        uni_f(verify, "seed", seeds[i])
        draw(verify, out_fbo, OUT, OUT)
        img = out_fbo.toImage().convertToFormat(QImage.Format_RGBA8888)
        f.glBindTexture(0x0DE1, 0)
        return count_bad(bytes(img.constBits())[: OUT * OUT * 4])

    if texs:   # o verificador tem de apanhar erros: com a semente errada quase todos os píxeis diferem
        seeds[0] += 1
        caught = check(0)
        seeds[0] -= 1
        if caught < OUT * OUT // 2:
            _emit({"ev": "warn", "msg": "O teste da VRAM não é fiável neste driver — só a carga da placa é testada."})
            texs, seeds = [], []
        else:
            _emit({"ev": "selftest", "ok": True})

    t0 = last = time.perf_counter()
    frames = errors = passes = 0
    sim_t = 0.0
    idx = 0
    next_seed = len(seeds)
    while not seconds or time.perf_counter() - t0 < seconds:
        scene.bind()
        uni_f(scene, "t", sim_t)
        draw(scene, scene_fbo, *SCENE)
        f.glFinish()
        frames += 1
        sim_t += 1 / 60
        if texs:
            bad = check(idx)
            if bad:
                errors += bad
                _emit({"ev": "vram_error", "count": bad, "block": idx, "mb": idx * TEX_MB})
            fill.bind()
            uni_f(fill, "seed", next_seed)
            draw(fill, texs[idx], TEX, TEX)
            seeds[idx] = next_seed
            next_seed = (next_seed + 1) % 4096
            idx += 1
            if idx == len(texs):
                idx = 0
                passes += 1
        now = time.perf_counter()
        if now - last >= 1.0:
            _emit({"ev": "progress", "elapsed": now - t0, "fps": frames / (now - last), "passes": passes,
                   "errors": errors})
            frames, last = 0, now
    _emit({"ev": "done", "passes": passes, "errors": errors, "vram_mb": len(texs) * TEX_MB})
    ctx.doneCurrent()
    return 0


def main_from_argv(argv: list[str]) -> int:
    secs, mb = 0.0, 1024
    for i, a in enumerate(argv):
        if a == "--seconds" and i + 1 < len(argv):
            secs = float(argv[i + 1])
        elif a == "--vram-mb" and i + 1 < len(argv):
            mb = int(argv[i + 1])
    try:
        return run_child(secs, mb)
    except Exception as e:  # noqa: BLE001
        _emit({"ev": "error", "msg": f"{type(e).__name__}: {e}"})
        return 1


def child_command(seconds: float, vram_mb: int) -> list[str]:
    base = [sys.executable, "--gpustress"] if getattr(sys, "frozen", False) else \
        [sys.executable, "-m", "nexo", "--gpustress"]
    return base + ["--seconds", str(seconds), "--vram-mb", str(vram_mb)]
