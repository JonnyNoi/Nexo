"""Perfis por jogo: gravar/ler, overlay, programas a fechar (com processos falsos) e GameMode."""
import os
import tempfile
import unittest
from unittest import mock

import psutil

from nexo.core import gameprofile as gp
from nexo.core import util


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None)):
            p.start()
            self.addCleanup(p.stop)


class Profiles(TempConfig):
    def test_set_get_and_empty_removed(self):
        self.assertEqual(gp.get("Jogo"), gp.DEFAULT)
        gp.set_value("Jogo", "power", "performance")
        gp.set_value("Jogo", "close", ["discord"])
        self.assertEqual(gp.get("Jogo")["power"], "performance")
        self.assertEqual(gp.power_for("Jogo"), "performance")
        self.assertTrue(gp.has_profile("Jogo"))
        gp.set_value("Jogo", "power", "")
        gp.set_value("Jogo", "close", [])
        self.assertFalse(gp.has_profile("Jogo"))
        self.assertEqual(util.get_setting(gp.KEY), {})
        with self.assertRaises(KeyError):
            gp.set_value("Jogo", "xpto", 1)

    def test_invalid_power_ignored(self):
        util.set_setting(gp.KEY, {"Jogo": {"power": "turbo-maximo"}})
        self.assertEqual(gp.power_for("Jogo"), "")
        self.assertEqual(gp.get(None), gp.DEFAULT)

    def test_overlay(self):
        self.assertTrue(gp.overlay_for("Jogo", True))
        self.assertFalse(gp.overlay_for("Jogo", False))
        gp.set_value("Jogo", "overlay", "off")
        self.assertFalse(gp.overlay_for("Jogo", True))
        gp.set_value("Jogo", "overlay", "on")
        self.assertTrue(gp.overlay_for("Jogo", False))

    def test_known_games(self):
        gp.set_value("B", "gamemode", True)
        gp.set_value("A", "overlay", "on")
        self.assertEqual(gp.known_games()[:2], ["A", "B"])


class FakeProc:
    def __init__(self, pid, name, user="eu"):
        self.info = {"pid": pid, "name": name, "username": user}
        self.pid = pid
        self.terminated = False

    def terminate(self):
        self.terminated = True


class Close(unittest.TestCase):
    def test_never_close_critical(self):
        for n in ("steam", "Steam.exe", "explorer.exe", "plasmashell", "nexo", ""):
            self.assertFalse(gp.can_close(n), n)
        self.assertTrue(gp.can_close("Discord.exe"))

    def test_close_only_listed_user_processes(self):
        procs = [FakeProc(10, "discord"), FakeProc(11, "Discord.exe"), FakeProc(12, "firefox"),
                 FakeProc(13, "discord", user="outro"), FakeProc(14, "steam"), FakeProc(99, "discord")]
        me = mock.Mock(pid=os.getpid())
        me.username.return_value = "eu"
        game = mock.Mock(pid=99)
        game.parent.return_value = None

        def process(pid=None):
            return game if pid == 99 else me
        with mock.patch.object(gp.psutil, "process_iter", return_value=procs), \
                mock.patch.object(gp.psutil, "Process", side_effect=process), \
                mock.patch.object(gp.psutil, "wait_procs", return_value=([], [])):
            closed = gp.close_programs(["discord", "steam", "explorer.exe"], game_pid=99)
        self.assertEqual(closed, ["Discord.exe", "discord"])
        self.assertEqual([p.pid for p in procs if p.terminated], [10, 11])   # 13: outro utilizador; 99: o jogo

    def test_nothing_to_close(self):
        self.assertEqual(gp.close_programs(["steam", ""]), [])

    def test_real_process_table_runs(self):
        # sem nomes que existam: percorre os processos reais sem fechar nada
        self.assertEqual(gp.close_programs(["nexo-processo-que-nao-existe-123"]), [])
        self.assertTrue(psutil.pid_exists(os.getpid()))


class GameMode(unittest.TestCase):
    def test_register(self):
        with mock.patch.object(gp, "gamemode_available", return_value=True), \
                mock.patch.object(gp, "run", return_value=(0, "(0,)")) as run:
            self.assertEqual(gp.gamemode_register(1234, True), (True, ""))
        cmd = run.call_args[0][0]
        self.assertIn("com.feralinteractive.GameMode.RegisterGame", cmd)
        self.assertEqual(cmd[-1], "1234")
        with mock.patch.object(gp, "gamemode_available", return_value=True), \
                mock.patch.object(gp, "run", return_value=(0, "(-1,)")):
            self.assertFalse(gp.gamemode_register(1234, False)[0])
        with mock.patch.object(gp, "gamemode_available", return_value=False):
            self.assertFalse(gp.gamemode_register(1, True)[0])


if __name__ == "__main__":
    unittest.main()
