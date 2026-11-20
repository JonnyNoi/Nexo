"""Modo jogo na janela principal: deteção do jogo, overlay, perfis por jogo e sessões de jogo."""
from __future__ import annotations

from PySide6.QtCore import QTimer

from ..core.util import get_setting


class GameMixin:
    """Misturado na MainWindow (usa self.hub, self._alert, self.names, self.pages…)."""

    def _init_game(self):
        from .overlay import OverlayController
        self.overlay = OverlayController()
        self.overlay_manual = False        # overlay ligado à mão (botão "Mostrar agora")
        self.game = None                   # jogo a correr (games.RunningGame)
        self.game_stats: dict = {}
        self._game_busy = False
        self._game_misses = 0
        self._game_timer = QTimer(self)
        self._game_timer.timeout.connect(self._check_game)
        self._game_timer.start(4000)
        self.hub.updated.connect(self._game_tick)
        # perfil do jogo atual (energia, programas fechados, GameMode) — para desfazer no fim
        self._gp_power_prev: str | None = None
        self._gp_gamemode_pid = 0

    # ------------------------------------------------------------------ modo jogo
    def _check_game(self):
        if self._game_busy or not get_setting("game_detect"):
            return
        from .widgets import run_async
        self._game_busy = True

        def detect():  # a importação (compila as regras do disksafety, ~0,1 s) também fica fora da interface
            from ..core import games
            return games.detect_running()

        def done(g):
            self._game_busy = False
            self._game_changed(g)

        def fail(_m):
            self._game_busy = False
        run_async(detect, on_done=done, on_fail=fail)

    def _game_changed(self, g):
        old = self.game
        if g is None and old is not None:
            self._game_misses += 1
            if self._game_misses < 2:   # evita "acabou" falso durante ecrãs de carregamento
                return
        self._game_misses = 0
        if g is not None and old is not None and g.name == old.name:
            return
        if old is not None:
            self._game_ended(old)
            self._profile_stop()
        self.game = g
        self.hub.gaming = g is not None
        self.overlay.fps.set_game(g)
        if g is not None:
            from ..core import gameprofile
            self.game_stats = {"cpu_max": None, "gpu_max": None, "start": g.started, "fps": [], "timeline": [],
                               "load": {"cpu": [0.0, 0], "gpu": [0.0, 0]}, "vram_max": None, "ram_max": None,
                               "wh": 0.0, "power_seen": False}
            extra = self._profile_start(g)
            if get_setting("game_notify"):
                if gameprofile.overlay_for(g.name, get_setting("overlay_auto")):
                    extra.append("overlay ligado")
                self._alert(f"🎮 Jogo detetado: {g.name}" + (" — " + ", ".join(extra) if extra else ""), "info",
                            "Modo jogo")
            if gameprofile.overlay_for(g.name, get_setting("overlay_auto")) or self.overlay_manual:
                self.overlay.show(g.name, g.started)
        elif not self.overlay_manual:
            self.overlay.hide()
        self._notify_game_page()

    def _game_ended(self, g):
        import time as _t
        self._save_session(g)
        mins = max(1, int((_t.time() - (self.game_stats.get("start") or _t.time())) / 60))
        if get_setting("game_notify"):
            parts = [f"Sessão de {g.name}: {mins} min"]
            if self.game_stats.get("cpu_max") is not None:
                parts.append(f"CPU máx. {self.game_stats['cpu_max']:.0f} °C")
            if self.game_stats.get("gpu_max") is not None:
                parts.append(f"GPU máx. {self.game_stats['gpu_max']:.0f} °C")
            for comp, secs in (self.game_stats.get("throttle") or {}).items():
                if secs >= 5:
                    who = {"cpu": "CPU limitada", "gpu": "GPU limitada"}[comp]
                    parts.append(f"{who} pela temperatura {secs / 60:.0f} min" if secs >= 60
                                 else f"{who} pela temperatura {secs:.0f} s")
            if self.game_stats.get("fps_n", 0) >= 10:
                parts.append(f"{self.game_stats['fps_sum'] / self.game_stats['fps_n']:.0f} FPS em média "
                             f"(mín. {self.game_stats['fps_min']:.0f})")
            self._alert(" · ".join(parts), "info", "Modo jogo")
        if self.overlay_manual:
            self.overlay.show("", 0)

    def _game_tick(self, _r):
        if self.game is not None:
            st = self.game_stats
            for key, k in (("cpu_temp", "cpu_max"), ("gpu_temp", "gpu_max"), ("vram", "vram_max"),
                           ("ram", "ram_max")):
                v = self.hub.latest(key)
                if v is not None and (st.get(k) is None or v > st[k]):
                    st[k] = v
            for comp in ("cpu", "gpu"):
                v = self.hub.latest(f"{comp}_load")
                if v is not None and "load" in st:
                    st["load"][comp][0] += v
                    st["load"][comp][1] += 1
            cp, gp = self.hub.latest("cpu_power"), self.hub.latest("gpu_power")
            if cp is not None or gp is not None:
                st["wh"] = st.get("wh", 0.0) + ((cp or 0) + (gp or 0)) / 3600
                st["power_seen"] = True
        # o processo do overlay pode ter ido abaixo: volta a lançá-lo (no máximo a cada 10 s)
        from ..core import gameprofile
        want = self.overlay_manual or (self.game is not None
                                       and gameprofile.overlay_for(self.game.name, get_setting("overlay_auto")))
        if want and not self.overlay.running():
            import time as _t
            if _t.monotonic() - getattr(self, "_ov_retry", 0) > 10:
                self._ov_retry = _t.monotonic()
                self.overlay.show(self.game.name if self.game else "", self.game.started if self.game else 0)
        self.overlay.push(self.hub)
        f = self.overlay.last_fps
        if self.game is not None and f:
            st = self.game_stats
            st["fps_sum"] = st.get("fps_sum", 0.0) + f["fps"]
            st["fps_n"] = st.get("fps_n", 0) + 1
            st["fps_min"] = min(st.get("fps_min") or f["fps"], f["fps"])
            st.setdefault("fps", []).append(f["fps"])
            st.setdefault("timeline", []).append([f["fps"], f.get("ft_max")])

    def _save_session(self, g, wait: bool = False):
        """Guarda a sessão no histórico (Modo jogo → Sessões de jogo)."""
        import time as _t
        from ..core import sessions
        st = self.game_stats or {}
        if not st or st.get("saved"):
            return
        st["saved"] = True
        avg, low1, mn = sessions.fps_stats(st.get("fps") or [])
        load = st.get("load") or {}

        def mean(comp):
            s_, n = load.get(comp, (0.0, 0))
            return s_ / n if n else None
        tl = st.get("timeline") or []
        sess = sessions.Session(g.name, st.get("start") or _t.time(), _t.time(), st.get("cpu_max"), st.get("gpu_max"),
                                avg, low1, mn, cpu_load=mean("cpu"), gpu_load=mean("gpu"),
                                vram_max=st.get("vram_max"), ram_max=st.get("ram_max"),
                                wh=st.get("wh") if st.get("power_seen") else None,
                                stutters=sessions.count_stutters(tl) if len(tl) >= 10 else None,
                                timeline=tl if len(tl) >= 10 else None)
        if wait:   # ao sair do Nexo com o jogo ainda aberto
            sessions.add(sess)
            return
        from .widgets import run_async
        run_async(sessions.add, sess, on_done=lambda _ok: self._notify_game_page(), on_fail=lambda _m: None)

    def set_overlay_manual(self, on: bool):
        self.overlay_manual = on
        if on:
            self.overlay.show(self.game.name if self.game else "", self.game.started if self.game else 0)
        elif self.game is None or not self._overlay_wanted():
            self.overlay.hide()
        self._notify_game_page()

    def _notify_game_page(self):
        name = "Modo jogo"
        if name in self.names:
            p = self.pages[self.names.index(name)]
            if p is not None and p.isVisible():
                p.on_show()

    def _overlay_wanted(self) -> bool:
        from ..core import gameprofile
        return self.game is not None and gameprofile.overlay_for(self.game.name, get_setting("overlay_auto"))

    # ------------------------------------------------------------------ perfil por jogo
    def _profile_start(self, g) -> list[str]:
        """Aplica o perfil do jogo. Devolve o que mudou (para a notificação)."""
        from ..core import gameprofile
        from ..core import power as fc
        from ..core.power import POWER_NAMES
        from .widgets import run_async
        prof = gameprofile.get(g.name)
        extra = []
        power = gameprofile.power_for(g.name)
        if power and gameprofile.power_available():
            first = self._gp_power_prev is None

            def work():
                prev = fc.get_power_profile() if first else None
                return prev, fc.set_power_profile(power)

            def done(res):
                prev, (ok, msg) = res
                # só se o jogo continuar aberto (se já fechou, a energia foi reposta para "equilibrado")
                if first and self._gp_power_prev == "" and self.game is g:
                    self._gp_power_prev = prev or ""
                if not ok:
                    self.notify(f"Perfil de energia do jogo: {msg}", "warn")
            if first:
                self._gp_power_prev = ""   # "" = a ler o perfil anterior
            run_async(work, on_done=done, on_fail=lambda _m: None)
            extra.append(f"energia em «{POWER_NAMES.get(power, power)}»")
        if prof["close"]:
            def closed(names):
                if names:
                    self.notify("Fechados para o jogo: " + ", ".join(names), "info")
            run_async(gameprofile.close_programs, list(prof["close"]), g.pid, on_done=closed,
                      on_fail=lambda _m: None)
            extra.append(f"a fechar {len(prof['close'])} programa(s)")
        if prof["gamemode"] and gameprofile.gamemode_available() and g.pid:
            self._gp_gamemode_pid = g.pid

            def gm(res):
                if not res[0]:
                    self.notify(f"GameMode: {res[1]}", "warn")
            run_async(gameprofile.gamemode_register, g.pid, True, on_done=gm, on_fail=lambda _m: None)
            extra.append("GameMode ligado")
        return extra

    def _profile_stop(self, wait: bool = False):
        """O jogo fechou: repõe a energia e desliga o GameMode."""
        from ..core import gameprofile
        from ..core import power as fc
        from .widgets import run_async
        prev, self._gp_power_prev = self._gp_power_prev, None
        if prev is not None:
            target = prev or "balanced"
            if wait:
                fc.set_power_profile(target)
            else:
                run_async(fc.set_power_profile, target, on_done=lambda _r: None, on_fail=lambda _m: None)
        pid, self._gp_gamemode_pid = self._gp_gamemode_pid, 0
        if pid:
            if wait:
                gameprofile.gamemode_register(pid, False)
            else:
                run_async(gameprofile.gamemode_register, pid, False, on_done=lambda _r: None,
                          on_fail=lambda _m: None)

    def _shutdown_game(self):
        if self.game is not None:
            self._save_session(self.game, wait=True)
            self._profile_stop(wait=True)
        self.overlay.hide()
        self.overlay.fps.stop()
