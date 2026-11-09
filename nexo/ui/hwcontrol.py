"""Gestores de hardware que vivem enquanto o Nexo corre (mesmo com a página fechada ou na bandeja):

- FanManager: aplica a curva do perfil de ventoinhas a cada leitura do SensorHub (1×/s).
"""
from __future__ import annotations


from PySide6.QtCore import QObject, Signal

from ..core import fans as fc
from ..core.util import get_setting, set_setting
from .widgets import notify, run_async

SOURCES = {"auto": "Automático", "cpu": "CPU", "gpu": "GPU", "max": "A mais quente"}


class FanManager(QObject):
    changed = Signal()

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.fans: list[fc.Fan] = fc.discover()
        self.targets: dict[str, float] = {}      # % atual pedido pelo Nexo (por ventoinha)
        self.touched: set[str] = set()           # ventoinhas que o Nexo pôs em modo manual
        self.error = ""
        self.boost = False                       # perfil "Desempenho" temporário durante um jogo
        hub.updated.connect(self._tick)
        if self.profile() != "auto" and not self.can_control():
            self.error = "Sem permissão para controlar as ventoinhas — o perfil fica em pausa."

    # ------------------------------------------------------------------ estado
    def profile(self) -> str:
        p = get_setting("fan_profile", "auto")
        return p if p in fc.PROFILES else "auto"

    def effective_profile(self) -> str:
        p = self.profile()
        if self.boost and p in ("auto", "silent", "balanced"):
            return "performance"
        return p

    def curve(self, key: str | None = None) -> list[tuple[float, float]] | None:
        key = key or self.effective_profile()
        if key == "custom":
            pts = get_setting("fan_curve") or fc.DEFAULT_CUSTOM
            return [(float(t), float(p)) for t, p in pts]
        return fc.PROFILES[key]["curve"]

    def included(self, fan: fc.Fan) -> bool:
        return fan.id not in (get_setting("fan_excluded") or [])

    def source(self, fan: fc.Fan) -> str:
        return (get_setting("fan_sources") or {}).get(fan.id, "auto")

    def can_control(self) -> bool:
        return bool(self.fans) and all(f.writable() for f in self.fans if self.included(f))

    def temp_for(self, fan: fc.Fan) -> float | None:
        ct, gt = self.hub.latest("cpu_temp"), self.hub.latest("gpu_temp")
        src = self.source(fan)
        if src == "auto":
            src = "gpu" if fan.group == "GPU" else "max"
        if src == "cpu":
            return ct if ct is not None else gt
        if src == "gpu":
            return gt if gt is not None else ct
        vals = [v for v in (ct, gt) if v is not None]
        return max(vals) if vals else None

    # ------------------------------------------------------------------ ações
    def set_profile(self, key: str):
        set_setting("fan_profile", key)
        self.error = ""
        if key == "auto":
            self.restore()
        elif not self.can_control():
            self.error = "Sem permissão para controlar as ventoinhas."
        else:
            self._tick(None)
        if get_setting("fan_power_sync") and fc.PROFILES[key].get("power"):
            power = fc.PROFILES[key]["power"]
            run_async(fc.set_power_profile, power,
                      on_done=lambda r: notify(f"Perfil de energia: {fc.POWER_NAMES.get(power, power)}." if r[0]
                                               else f"Perfil de energia: {r[1]}", "ok" if r[0] else "warn"),
                      on_fail=lambda _m: None)
        self.changed.emit()

    def set_boost(self, on: bool):
        if on == self.boost:
            return
        self.boost = on
        if self.effective_profile() == "auto":
            self.restore()
        self.changed.emit()

    def set_included(self, fan: fc.Fan, on: bool):
        ex = set(get_setting("fan_excluded") or [])
        ex.discard(fan.id) if on else ex.add(fan.id)
        set_setting("fan_excluded", sorted(ex))
        if not on and fan.id in self.touched:
            fc.set_auto(fan, root=False)
            self.touched.discard(fan.id)
            self.targets.pop(fan.id, None)

    def set_source(self, fan: fc.Fan, src: str):
        s = dict(get_setting("fan_sources") or {})
        s[fan.id] = src
        set_setting("fan_sources", s)

    def rediscover(self):
        self.fans = fc.discover()
        self.changed.emit()

    def restore(self):
        """Devolve ao hardware as ventoinhas em que o Nexo mexeu."""
        for f in self.fans:
            if f.id in self.touched:
                fc.set_auto(f, root=False)
        self.touched.clear()
        self.targets.clear()

    def _tick(self, _r):
        prof = self.effective_profile()
        if prof == "auto" or not self.fans:
            if self.touched:
                self.restore()
            return
        curve = self.curve(prof)
        if not curve:
            return
        for f in self.fans:
            if not self.included(f) or not f.writable():
                continue
            t = self.temp_for(f)
            if t is None:
                if f.id in self.touched:   # sem leitura de temperatura: mais vale o hardware decidir
                    fc.set_auto(f, root=False)
                    self.touched.discard(f.id)
                continue
            want = 100.0 if t >= fc.SAFE_TEMP else fc.curve_value(curve, t)
            want = max(fc.MIN_PCT, min(100.0, want))
            last = self.targets.get(f.id)
            if last is not None and want < last:
                want = max(want, last - 3)          # desce devagar (sem "ondas" de ruído); sobe logo
            if last is None or abs(want - last) >= 1:
                ok, msg = fc.set_pct(f, want, root=False)
                if ok:
                    self.targets[f.id] = want
                    self.touched.add(f.id)
                elif not self.error:
                    self.error = f"{f.label}: {msg}"
                    self.changed.emit()


_fan_mgr: FanManager | None = None


def fan_manager(hub=None) -> FanManager:
    global _fan_mgr
    if _fan_mgr is None:
        _fan_mgr = FanManager(hub)
    return _fan_mgr


def existing_fan_manager() -> FanManager | None:
    """O gestor das ventoinhas, se já foi criado (sem o criar)."""
    return _fan_mgr
