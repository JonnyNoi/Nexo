"""Tarefas de fundo da janela principal: vigilância (discos, S.M.A.R.T.), tarefas agendadas,
atualizações do sistema e do Nexo e troca automática do fundo do ambiente de trabalho."""
from __future__ import annotations

import os

from PySide6.QtCore import QTimer

from ..core.util import IS_WIN, get_setting, set_setting
from .widgets import run_async


class BackgroundMixin:
    """Misturado na MainWindow (usa self.notify, self._alert, self.net, self.names, self.pages…)."""

    def _init_background(self):
        self._wp_busy = False
        self._wp_timer = QTimer(self)
        self._wp_timer.timeout.connect(self._auto_wallpaper)
        self._wp_timer.start(60_000)
        # atualizações (contador no menu)
        self._upd_busy = False
        self._upd_waiters: list = []
        from ..core import updates as _up
        self._show_update_badge(_up.cached())
        self._upd_timer = QTimer(self)
        self._upd_timer.timeout.connect(self._auto_updates)
        self._upd_timer.start(30 * 60_000)
        QTimer.singleShot(90_000, self._auto_updates)   # depois do arranque, sem pesar no início
        # vigilância (disco cheio, S.M.A.R.T.)
        from ..core.watch import DiskAlerts
        self._disk_alerts = DiskAlerts()
        self._watch_busy = False
        self._watch_timer = QTimer(self)
        self._watch_timer.timeout.connect(self._watch)
        self._watch_timer.start(5 * 60_000)
        QTimer.singleShot(45_000, self._watch)
        # atualizações do próprio Nexo
        from ..core import selfupdate
        selfupdate.cleanup_old()
        if IS_WIN and get_setting("lhm_autostart"):
            from ..core import lhm
            QTimer.singleShot(1500, lambda: run_async(lhm.start, on_fail=lambda _m: None))
        self._pending_release = None
        self._su_timer = QTimer(self)
        self._su_timer.timeout.connect(self._self_update_check)
        self._su_timer.start(3 * 3600_000)
        QTimer.singleShot(120_000, self._self_update_check)

    # ------------------------------------------------------------------ vigilância
    def _run_scheduled(self):
        """Tarefas agendadas em atraso (Utilitários → Tarefas agendadas), uma de cada vez."""
        from ..core import schedule
        if getattr(self, "_sched_busy", False) or getattr(self, "game", None) is not None:
            return   # durante um jogo nada de trabalho pesado em segundo plano
        due = schedule.due_tasks()
        if not due:
            return
        t = due[0]
        self._sched_busy = True

        def done(res):
            self._sched_busy = False
            msg, kind = res
            if msg:
                self._alert(("🧹 " if t.id == "clean" else "") + msg, kind or "info", t.page)
            self._refresh_tasks_page()
            if len(due) > 1:
                QTimer.singleShot(30_000, self._run_scheduled)

        def fail(m):
            self._sched_busy = False
            schedule.record(t, False, f"Falhou: {m}")
            self._refresh_tasks_page()
        run_async(schedule.run_task, t, on_done=done, on_fail=fail)

    def _refresh_tasks_page(self):
        name = "Tarefas agendadas"
        if name in self.names:
            p = self.pages[self.names.index(name)]
            if p is not None and p.isVisible():
                p.on_show()

    def _watch(self):
        """A cada 5 min: espaço livre dos discos e alterações na cache do S.M.A.R.T. (sem pedir palavra-passe)."""
        self._run_scheduled()
        if self._watch_busy or not (get_setting("alert_disk") or get_setting("alert_smart")):
            return
        self._watch_busy = True
        from ..core import watch

        def work():
            msgs = []
            if get_setting("alert_disk"):
                msgs += self._disk_alerts.check(watch.disk_usages(), float(get_setting("alert_disk_pct") or 10))
            if get_setting("alert_smart"):
                msgs += watch.smart_check_cached()
            return msgs

        def done(msgs):
            self._watch_busy = False
            for m, kind in msgs:
                self._alert(m, kind)

        def fail(_m):
            self._watch_busy = False
        run_async(work, on_done=done, on_fail=fail)

    # ------------------------------------------------------------------ atualizações
    def _show_update_badge(self, data: dict):
        n = len((data or {}).get("items", []))
        self.set_nav_badge("Atualizações", str(n) if n else None, "accent")

    def _auto_updates(self):
        import time as _t
        from ..core import updates as up
        if not get_setting("updates_auto", True) or self.net.online is False:
            return
        if _t.time() - up.cached().get("time", 0) >= 6 * 3600:
            self.check_updates()

    def check_updates(self, force: bool = False, on_done=None) -> bool:
        """Procura atualizações em segundo plano. Devolve False se não houver internet."""
        if self.net.online is False:
            return False
        if on_done:
            self._upd_waiters.append(on_done)
        if self._upd_busy:
            return True
        self._upd_busy = True
        from ..core import updates as up
        from .widgets import run_async

        def finish(data):
            self._upd_busy = False
            if data:
                self._show_update_badge(data)
            waiters, self._upd_waiters = self._upd_waiters, []
            for w in waiters:
                w(data)
        run_async(up.check, on_done=finish, on_fail=lambda _m: finish(None))
        return True

    # ------------------------------------------------------------------ troca automática do fundo
    def _auto_wallpaper(self, force: bool = False):
        """Troca automática do fundo do AMBIENTE DE TRABALHO (sistema)."""
        import time as _t
        mins = int(get_setting("wp_auto") or 0)
        if self._wp_busy or (not force and (not mins or _t.time() - get_setting("wp_auto_last", 0) < mins * 60)):
            return
        if get_setting("wp_auto_source") == "wallhaven" and self.net.online is False:
            if force:
                from .netmonitor import require_online
                require_online("Procurar fundos no Wallhaven")
            return  # sem internet: tenta outra vez quando a ligação voltar
        set_setting("wp_auto_last", _t.time())
        from ..core import desktopwp as dw
        from ..core import wallhaven as wh
        from .widgets import run_async

        def applied(res):
            self._wp_busy = False
            ok, msg = res
            if force:
                self.notify("Fundo do ambiente de trabalho alterado." if ok else f"Não foi possível: {msg}",
                            "ok" if ok else "warn")
            name = "Fundo de ecrã"
            page = self.pages[self.names.index(name)] if name in self.names else None
            if ok and page is not None and page.isVisible():
                page.on_show()

        def apply(path):
            if not path:
                self._wp_busy = False
                return
            run_async(dw.set_wallpaper, path, None, bool(get_setting("desktop_wp_lock", False)),
                      on_done=applied, on_fail=fail)

        def fail(msg):
            self._wp_busy = False
            if force:
                self.notify(f"Não foi possível trocar o fundo: {msg}", "warn")
        self._wp_busy = True
        if get_setting("wp_auto_source") == "wallhaven":
            from .wallhaven_dialog import screen_min_res
            cat = wh.CATEGORIES.get(get_setting("wh_category", "Anime"), "010")
            run_async(wh.random_from_wallhaven, get_setting("wh_query", "anime scenery"), cat, screen_min_res(),
                      on_done=apply, on_fail=fail)
        else:
            import random
            cur = os.path.basename(get_setting("desktop_wp") or "")
            files = [f for f in dw.images() if os.path.basename(f) != cur]
            if files:
                apply(random.choice(files))
            else:
                self._wp_busy = False
                if force:
                    self.notify("Ainda não tem fundos guardados — escolha alguns no Wallhaven.", "info")

    def restart_app(self):
        """Fecha e volta a abrir o Nexo (depois de atualizar ou importar definições)."""
        from PySide6.QtCore import QProcess
        from ..app import restart_command
        prog, args = restart_command()
        if QProcess.startDetached(prog, args):
            self.quit()
        else:
            self.notify("Não foi possível reiniciar sozinho — feche e abra o Nexo.", "warn")

    # ------------------------------------------------------------------ atualizações do próprio Nexo
    def _self_update_check(self):
        import time as _t
        from ..core import selfupdate
        from .netmonitor import monitor
        if not (get_setting("self_update_check") and selfupdate.configured()) or monitor().online is False:
            return
        if _t.time() - float(get_setting("self_update_last") or 0) < 86400:
            return

        def done(rel):
            set_setting("self_update_last", _t.time())
            if rel is None or rel.version == get_setting("self_update_skip"):
                return
            name = "Definições"
            if name in self.names:
                self.set_nav_badge(name, "1", "accent")
                p = self.pages[self.names.index(name)]
                if p is not None and hasattr(p, "show_release"):
                    p.show_release(rel)
            self._pending_release = rel
            self._alert(f"⬆ Nexo {rel.version} disponível — veja em Definições → Atualizações do Nexo.", "info",
                        "Definições")
        run_async(selfupdate.check, on_done=done, on_fail=lambda _m: None)
