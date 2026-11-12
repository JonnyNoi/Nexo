"""Gestores de hardware que vivem enquanto o Nexo corre (mesmo com a página fechada ou na bandeja):

- FanManager: aplica a curva do perfil de ventoinhas a cada leitura do SensorHub (1×/s) e troca
  automaticamente de perfil enquanto um jogo está aberto (Modo jogo).
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import fans as fc
from ..core.util import get_setting, set_setting
from .widgets import notify, run_async

SOURCES = {"auto": "Automático", "cpu": "CPU", "gpu": "GPU", "max": "A mais quente"}


def game_profile(game: str | None = None) -> str:
    """Perfil a usar durante um jogo ("" = não mudar). Um perfil escolhido para o jogo ganha ao geral."""
    per_game = get_setting("fan_game_profiles") or {}
    if game and per_game.get(game) in fc.GAME_PROFILES:
        return per_game[game]
    p = get_setting("fan_game_profile")
    if p is None:   # versões antigas: interruptor "Desempenho durante jogos"
        p = "performance" if get_setting("fan_game_boost") else ""
    return p if p in fc.GAME_PROFILES else ""


def set_game_profile(key: str, game: str | None = None) -> None:
    """key "" = não mudar (geral) / usar o geral (por jogo)."""
    if game is None:
        set_setting("fan_game_profile", key)
        return
    per_game = dict(get_setting("fan_game_profiles") or {})
    if key:
        per_game[game] = key
    else:
        per_game.pop(game, None)
    set_setting("fan_game_profiles", per_game)


class FanManager(QObject):
    changed = Signal()

    def __init__(self, hub):
        super().__init__()
        self.hub = hub
        self.fans: list[fc.Fan] = fc.discover()
        self.targets: dict[str, float] = {}      # % atual pedido pelo Nexo (por ventoinha)
        self.touched: set[str] = set()           # ventoinhas que o Nexo pôs em modo manual
        self.error = ""
        self.game: str | None = None             # jogo aberto (ou a arrefecer depois de fechar)
        self.cooling = False                     # o jogo fechou há pouco: perfil de jogo mantém-se
        self._cool = QTimer(self)
        self._cool.setSingleShot(True)
        self._cool.timeout.connect(self._cooldown_over)
        self._power_before: str | None = None    # perfil de energia antes do jogo (para repor)
        hub.updated.connect(self._tick)
        if self.profile() != "auto" and not self.can_control():
            self.error = "Sem permissão para controlar as ventoinhas — o perfil fica em pausa."

    # ------------------------------------------------------------------ estado
    def profile(self) -> str:
        p = get_setting("fan_profile", "auto")
        return p if p in fc.PROFILES else "auto"

    def game_profile(self) -> str:
        """Perfil de jogo em vigor agora ("" se não há jogo ou se não é para mudar)."""
        return game_profile(self.game) if self.game else ""

    def effective_profile(self) -> str:
        return self.game_profile() or self.profile()

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
        if self.effective_profile() == "auto":   # durante um jogo o perfil de jogo continua a mandar
            self.restore()
        elif not self.can_control():
            self.error = "Sem permissão para controlar as ventoinhas."
        else:
            self._tick(None)
        if get_setting("fan_power_sync") and not self.game_profile():
            self._set_power(fc.PROFILES[key].get("power"))
        self.changed.emit()

    def _set_power(self, power: str | None, quiet: bool = False):
        if not power:
            return
        name = fc.POWER_NAMES.get(power, "plano anterior")

        def done(r):
            if not quiet or not r[0]:
                notify(f"Perfil de energia: {name}." if r[0] else f"Perfil de energia: {r[1]}",
                       "ok" if r[0] else "warn")
        run_async(fc.set_power_profile, power, on_done=done, on_fail=lambda _m: None)

    # ------------------------------------------------------------------ modo jogo
    def set_game(self, name: str | None):
        """Chamado pela janela principal quando um jogo abre (nome) ou fecha (None)."""
        if name:
            self._cool.stop()
            self.cooling = False
            if name == self.game:
                return
            before = self.effective_profile()
            self.game = name
            self._game_switched(before)
        elif self.game and not self.cooling:
            if self.game_profile():
                self.cooling = True           # mantém o perfil de jogo enquanto o PC arrefece
                self._cool.start(fc.GAME_COOLDOWN_S * 1000)
                self.changed.emit()
            else:
                self._cooldown_over()

    def _cooldown_over(self):
        before = self.effective_profile()
        self.game, self.cooling = None, False
        self._game_switched(before)

    def refresh_game(self):
        """As opções do perfil de jogo mudaram: aplica já (sem esperar pelo próximo jogo)."""
        if self.game:
            self._game_switched(None)

    def _game_switched(self, before: str | None):
        eff = self.effective_profile()
        if eff == before:
            self.changed.emit()
            return
        self.error = ""
        if eff == "auto":
            self.restore()
        else:
            if not self.can_control() and self.fans:
                self.error = "Sem permissão para controlar as ventoinhas — o perfil de jogo fica em pausa."
            self._tick(None)
        self._sync_game_power()
        self.changed.emit()

    def _sync_game_power(self):
        """Perfil de energia acompanha o perfil de jogo; no fim volta ao que estava antes."""
        if not get_setting("fan_power_sync"):
            return
        from ..core import gameprofile
        if self.game and gameprofile.power_for(self.game):
            want = None   # o perfil do jogo escolhe a energia (Modo jogo → Perfis por jogo)
        else:
            want = fc.PROFILES[self.game_profile()].get("power") if self.game_profile() else None
        if want:
            first = self._power_before is None
            if first:
                self._power_before = ""   # "" = ainda a ler (fora da interface: pode demorar)

            def work():   # ler primeiro e só depois mudar, na mesma thread
                prev = fc.get_power_profile() if first else None
                return prev, fc.set_power_profile(want)

            def done(res):
                prev, (ok, msg) = res
                if first and self._power_before == "" and self.game_profile():
                    self._power_before = prev
                if not ok:
                    notify(f"Perfil de energia: {msg}", "warn")
            run_async(work, on_done=done, on_fail=lambda _m: None)
        elif self._power_before is not None:
            prev, self._power_before = self._power_before, None
            self._set_power(prev or fc.PROFILES[self.profile()].get("power"), quiet=True)

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

    def shutdown(self):
        """O Nexo vai fechar: ventoinhas para o hardware e perfil de energia como estava antes do jogo."""
        self._cool.stop()
        self.restore()
        if self._power_before is not None and get_setting("fan_power_sync"):
            prev = self._power_before or fc.PROFILES[self.profile()].get("power")
            self._power_before = None
            if prev:
                fc.set_power_profile(prev)   # síncrono: a aplicação está a sair

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
