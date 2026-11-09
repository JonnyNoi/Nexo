"""Controlo de ventoinhas.

Linux: canais PWM do hwmon (/sys/class/hwmon/hwmonN/pwmM): placa gráfica AMD (amdgpu) e, com o módulo
certo carregado (nct6775, it87…), as ventoinhas da motherboard. Escrever exige root: o Nexo pode instalar
uma regra udev que dá permissão de escrita só a esses ficheiros (pedido único de palavra-passe) — assim as
curvas funcionam sem pedir a palavra-passe a cada ajuste.

Windows: o controlo exige um controlador de kernel (o Nexo não instala nenhum). As rotações aparecem nos
Sensores (via LibreHardwareMonitor) e a página recomenda o FanControl (gratuito, código aberto).

Segurança: nunca abaixo de MIN_PCT (exceto no modo automático do próprio hardware), 100 % se a temperatura
passar SAFE_TEMP e devolução ao modo automático quando o Nexo fecha ou o perfil volta a "Automático".
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass

from .util import IS_LINUX, IS_WIN, read_text, run, run_root, which

MIN_PCT = 20          # nunca parar ventoinhas por engano
SAFE_TEMP = 90        # acima disto: 100 %, seja qual for a curva

# curvas (temperatura °C → % de rotação)
PROFILES: dict[str, dict] = {
    "auto": {"name": "Automático", "desc": "O hardware/BIOS decide (o Nexo não mexe)", "curve": None},
    "silent": {"name": "Silencioso", "desc": "Rotação baixa até aquecer a sério",
               "curve": [(40, 20), (60, 30), (70, 45), (80, 70), (88, 100)], "power": "power-saver"},
    "balanced": {"name": "Equilibrado", "desc": "Bom compromisso entre ruído e temperatura",
                 "curve": [(35, 25), (55, 40), (68, 60), (78, 80), (85, 100)], "power": "balanced"},
    "performance": {"name": "Desempenho", "desc": "Mais ar desde cedo — ideal para jogos",
                    "curve": [(30, 40), (50, 55), (65, 75), (75, 100)], "power": "performance"},
    "max": {"name": "Máximo", "desc": "Todas as ventoinhas a 100 %", "curve": [(0, 100), (100, 100)],
            "power": "performance"},
    "custom": {"name": "Personalizado", "desc": "A sua curva (arraste os pontos)", "curve": None, "power": None},
}
DEFAULT_CUSTOM = [(30, 25), (50, 35), (65, 55), (75, 75), (85, 100)]

# módulos de kernel que expõem as ventoinhas da motherboard (Super I/O)
SUPERIO_MODULES = ("nct6775", "it87", "nct6683", "asus_ec_sensors", "dell_smm_hwmon", "thinkpad_acpi")


def curve_value(curve: list[tuple[float, float]], temp: float) -> float:
    """Interpolação linear entre os pontos da curva."""
    pts = sorted(curve)
    if temp <= pts[0][0]:
        return pts[0][1]
    for (t0, p0), (t1, p1) in zip(pts, pts[1:]):
        if temp <= t1:
            return p0 + (p1 - p0) * (temp - t0) / max(t1 - t0, 1e-6)
    return pts[-1][1]


@dataclass
class Fan:
    id: str               # "amdgpu/pwm1"
    chip: str
    label: str
    group: str            # "GPU" | "CPU" | "Placa-mãe"
    pwm_path: str
    enable_path: str | None
    rpm_path: str | None
    pwm_max: int = 255
    orig_enable: str = ""  # modo que estava antes de o Nexo mexer (para devolver)

    def rpm(self) -> int | None:
        v = read_text(self.rpm_path) if self.rpm_path else ""
        return int(v) if v.isdigit() else None

    def pct(self) -> float | None:
        v = read_text(self.pwm_path)
        return int(v) * 100 / self.pwm_max if v.isdigit() else None

    def mode(self) -> str:
        """'manual', 'auto' ou 'full' (0 = sem controlo = 100 %)."""
        v = read_text(self.enable_path) if self.enable_path else ""
        return {"0": "full", "1": "manual"}.get(v, "auto" if v else "manual")

    def writable(self) -> bool:
        return os.access(self.pwm_path, os.W_OK) and (self.enable_path is None or os.access(self.enable_path, os.W_OK))


def _group(chip: str) -> str:
    if chip in ("amdgpu", "nouveau", "radeon", "i915", "xe"):
        return "GPU"
    if chip.startswith(("k10temp", "coretemp")):
        return "CPU"
    return "Placa-mãe"


def discover() -> list[Fan]:
    if not IS_LINUX:
        return []
    fans: list[Fan] = []
    for hw in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        chip = read_text(hw + "/name") or os.path.basename(hw)
        for pwm in sorted(glob.glob(hw + "/pwm[0-9]*")):
            base = os.path.basename(pwm)
            if not base[3:].isdigit():
                continue          # pwm1_enable, pwm1_mode…
            n = base[3:]
            enable = f"{pwm}_enable" if os.path.exists(f"{pwm}_enable") else None
            rpm = f"{hw}/fan{n}_input" if os.path.exists(f"{hw}/fan{n}_input") else None
            mx = read_text(f"{pwm}_max")
            label = read_text(f"{hw}/fan{n}_label") or (
                "Ventoinha da placa gráfica" if _group(chip) == "GPU" else f"Ventoinha {n}")
            fans.append(Fan(f"{chip}/{base}", chip, label, _group(chip), pwm, enable, rpm,
                            int(mx) if mx.isdigit() and int(mx) > 0 else 255,
                            read_text(enable) if enable else ""))
    return fans


def _write(path: str, value: str, root: bool = True) -> tuple[bool, str]:
    try:
        with open(path, "w") as f:
            f.write(value)
        return True, ""
    except PermissionError:
        if not root:   # o ciclo das curvas nunca pede a palavra-passe
            return False, "sem permissão"
        code, out = run_root(f"echo {int(value)} > '{path}'", timeout=60)
        return code == 0, out or "sem permissão"
    except OSError as e:
        return False, str(e)


def set_pct(fan: Fan, pct: float, root: bool = True) -> tuple[bool, str]:
    """Põe a ventoinha em modo manual com a rotação pedida (limitada a MIN_PCT…100)."""
    pct = max(MIN_PCT, min(100.0, pct))
    if fan.enable_path and read_text(fan.enable_path) != "1":
        ok, msg = _write(fan.enable_path, "1", root)
        if not ok:
            return False, msg
    return _write(fan.pwm_path, str(round(pct * fan.pwm_max / 100)), root)


def set_auto(fan: Fan, root: bool = True) -> tuple[bool, str]:
    """Devolve o controlo ao hardware (o modo original, se era automático; senão 2 = automático)."""
    if not fan.enable_path:
        return True, ""
    orig = fan.orig_enable if fan.orig_enable not in ("", "0", "1") else "2"
    if read_text(fan.enable_path) == orig:
        return True, ""
    return _write(fan.enable_path, orig, root)


def needs_access(fans: list[Fan]) -> bool:
    return IS_LINUX and os.geteuid() != 0 and any(not f.writable() for f in fans)


_UDEV_RULE = "/etc/udev/rules.d/90-nexo-fans.rules"


def grant_access() -> tuple[bool, str]:
    """Regra udev: dá permissão de escrita aos ficheiros pwm (só esses) e aplica-a já."""
    rule = ('ACTION=="add", SUBSYSTEM=="hwmon", '
            'RUN+="/bin/sh -c \'chmod a+w /sys%p/pwm[0-9] /sys%p/pwm[0-9]_enable 2>/dev/null; true\'"')
    script = (f"printf '%s\\n' '# Nexo: controlo de ventoinhas sem palavra-passe' {_sh(rule)} > {_UDEV_RULE} && "
              "for f in /sys/class/hwmon/hwmon*/pwm[0-9] /sys/class/hwmon/hwmon*/pwm[0-9]_enable; do "
              "[ -e \"$f\" ] && chmod a+w \"$f\"; done; true")
    code, out = run_root(script, timeout=120)
    return code == 0, ("Permissão concedida — o controlo fica ativo também depois de reiniciar."
                       if code == 0 else out or "pedido recusado")


def revoke_access() -> tuple[bool, str]:
    code, out = run_root(f"rm -f {_UDEV_RULE}; for f in /sys/class/hwmon/hwmon*/pwm[0-9] "
                         "/sys/class/hwmon/hwmon*/pwm[0-9]_enable; do [ -e \"$f\" ] && chmod go-w \"$f\"; done; true",
                         timeout=120)
    return code == 0, "Permissão removida." if code == 0 else out


def _sh(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def missing_board_fans(fans: list[Fan]) -> bool:
    """Linux sem nenhum canal da motherboard (só GPU ou nada): falta provavelmente o módulo Super I/O."""
    return IS_LINUX and not any(f.group != "GPU" for f in fans)


def load_board_modules() -> tuple[bool, str]:
    """Tenta carregar os módulos Super I/O mais comuns e torna permanente o que funcionar."""
    script = ("loaded=''; for m in nct6775 it87 nct6683; do modprobe $m 2>/dev/null && loaded=\"$loaded $m\"; done; "
              "[ -n \"$loaded\" ] && printf '%s\\n' $loaded > /etc/modules-load.d/nexo-fans.conf; "
              "echo \"carregados:$loaded\"")
    code, out = run_root(script, timeout=120)
    if code != 0:
        return False, out or "pedido recusado"
    found = [f for f in discover() if f.group != "GPU"]
    if found:
        return True, f"Encontradas {len(found)} ventoinha(s) da motherboard."
    return False, ("Nenhum chip de ventoinhas compatível respondeu. Algumas motherboards precisam de "
                   "'acpi_enforce_resources=lax' no arranque do kernel, ou não expõem o controlo ao sistema.")


# ---------------------------------------------------------------------------------- perfil de energia
_WIN_PLANS = {"power-saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
              "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
              "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}
POWER_NAMES = {"power-saver": "Poupança de energia", "balanced": "Equilibrado", "performance": "Desempenho"}


def set_power_profile(name: str) -> tuple[bool, str]:
    if IS_LINUX and which("powerprofilesctl"):
        code, out = run(["powerprofilesctl", "set", name], timeout=10)
        if code != 0 and name == "performance":
            return False, "Este PC não suporta o perfil Desempenho."
        return code == 0, out
    if IS_WIN and name in _WIN_PLANS:
        code, out = run(["powercfg", "/setactive", _WIN_PLANS[name]], timeout=10)
        return code == 0, out
    return False, "Perfis de energia indisponíveis neste sistema."
