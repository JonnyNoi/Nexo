"""Perfil de energia do sistema (usado pelos perfis por jogo).

Linux: power-profiles-daemon (`powerprofilesctl`). Windows: planos de energia do powercfg."""
from __future__ import annotations

import re

from .util import IS_LINUX, IS_WIN, run, which

_WIN_PLANS = {"power-saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
              "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
              "performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"}
POWER_NAMES = {"power-saver": "Poupança de energia", "balanced": "Equilibrado", "performance": "Desempenho"}
_GUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def available() -> bool:
    return IS_WIN or (IS_LINUX and bool(which("powerprofilesctl")))


def get_power_profile() -> str:
    """Perfil de energia ativo ("power-saver" | "balanced" | "performance"; no Windows pode ser o GUID
    de um plano próprio). "" se não for possível saber."""
    if IS_LINUX and which("powerprofilesctl"):
        code, out = run(["powerprofilesctl", "get"], timeout=10)
        return out.strip() if code == 0 else ""
    if IS_WIN:
        code, out = run(["powercfg", "/getactivescheme"], timeout=10)
        m = re.search(_GUID, out, re.I) if code == 0 else None
        if m:
            guid = m.group(0).lower()
            return next((k for k, v in _WIN_PLANS.items() if v == guid), guid)
    return ""


def set_power_profile(name: str) -> tuple[bool, str]:
    if IS_WIN and re.fullmatch(_GUID, name or "", re.I):
        code, out = run(["powercfg", "/setactive", name], timeout=10)   # plano próprio do utilizador
        return code == 0, out
    if IS_LINUX and which("powerprofilesctl"):
        code, out = run(["powerprofilesctl", "set", name], timeout=10)
        if code != 0 and name == "performance":
            return False, "Este PC não suporta o perfil Desempenho."
        return code == 0, out
    if IS_WIN and name in _WIN_PLANS:
        code, out = run(["powercfg", "/setactive", _WIN_PLANS[name]], timeout=10)
        return code == 0, out
    return False, "Perfis de energia indisponíveis neste sistema."
