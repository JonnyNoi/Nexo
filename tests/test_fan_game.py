"""Perfis de ventoinhas automáticos com o Modo jogo (hardware falso: nada é escrito no sysfs).

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QCoreApplication, QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from nexo.core import fans as fc  # noqa: E402
from nexo.core import util  # noqa: E402
from nexo.ui import hwcontrol  # noqa: E402

# QApplication (e não QCoreApplication) para o teste da interface poder correr no mesmo processo
_app = QCoreApplication.instance() or QApplication([])


class FakeHub(QObject):
    updated = Signal(list)

    def __init__(self, cpu=60.0, gpu=55.0):
        super().__init__()
        self.vals = {"cpu_temp": cpu, "gpu_temp": gpu}

    def latest(self, key):
        return self.vals.get(key)


class FakeFan:
    def __init__(self, fid="hwmon0/pwm1", group="GPU"):
        self.id, self.group, self.label, self.chip = fid, group, "Ventoinha", "amdgpu"

    def writable(self):
        return True


def sync_run_async(fn, *args, on_done=None, on_fail=None, **kw):
    r = fn(*args, **kw)
    if on_done:
        on_done(r)


class FanGameProfiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None),
                  mock.patch.object(hwcontrol, "run_async", sync_run_async),
                  mock.patch.object(hwcontrol, "notify", lambda *a, **k: None),
                  mock.patch.object(fc, "discover", lambda: [FakeFan()])):
            p.start()
            self.addCleanup(p.stop)
        self.writes, self.autos, self.power = [], [], ["balanced"]
        for name, fn in (("set_pct", lambda f, pct, root=True: (self.writes.append(pct), (True, ""))[1]),
                         ("set_auto", lambda f, root=True: (self.autos.append(f.id), (True, ""))[1]),
                         ("get_power_profile", lambda: self.power[-1]),
                         ("set_power_profile", lambda n: (self.power.append(n), (True, ""))[1])):
            p = mock.patch.object(fc, name, fn)
            p.start()
            self.addCleanup(p.stop)
        self.mgr = hwcontrol.FanManager(FakeHub())

    def test_old_boost_setting_migrates_to_performance(self):
        util.set_setting("fan_game_boost", True)
        self.assertEqual(hwcontrol.game_profile("Jogo"), "performance")
        util.set_setting("fan_game_profile", "")
        self.assertEqual(hwcontrol.game_profile("Jogo"), "")

    def test_per_game_wins_over_general(self):
        hwcontrol.set_game_profile("balanced")
        hwcontrol.set_game_profile("max", "Jogo A")
        self.assertEqual(hwcontrol.game_profile("Jogo A"), "max")
        self.assertEqual(hwcontrol.game_profile("Jogo B"), "balanced")
        hwcontrol.set_game_profile("", "Jogo A")   # "usar o geral"
        self.assertEqual(hwcontrol.game_profile("Jogo A"), "balanced")

    def test_game_switches_profile_and_cools_down(self):
        hwcontrol.set_game_profile("max")
        self.assertEqual(self.mgr.effective_profile(), "auto")
        self.mgr.set_game("Jogo")
        self.assertEqual(self.mgr.effective_profile(), "max")
        self.assertEqual(self.writes[-1], 100.0)
        self.mgr.set_game(None)           # fechou: ainda a arrefecer
        self.assertTrue(self.mgr.cooling)
        self.assertEqual(self.mgr.effective_profile(), "max")
        self.mgr.set_game("Jogo")          # voltou a abrir durante o arrefecimento
        self.assertFalse(self.mgr.cooling)
        self.mgr.set_game(None)
        self.mgr._cooldown_over()
        self.assertEqual(self.mgr.effective_profile(), "auto")
        self.assertIn("hwmon0/pwm1", self.autos)   # devolvida ao hardware
        self.assertEqual(self.mgr.touched, set())

    def test_no_game_profile_means_no_change(self):
        util.set_setting("fan_profile", "silent")
        self.mgr.set_game("Jogo")
        self.assertEqual(self.mgr.effective_profile(), "silent")
        self.mgr.set_game(None)
        self.assertIsNone(self.mgr.game)   # sem arrefecimento: nada a manter

    def test_changing_base_profile_during_game_keeps_game_profile(self):
        hwcontrol.set_game_profile("performance")
        self.mgr.set_game("Jogo")
        self.autos.clear()
        self.mgr.set_profile("auto")
        self.assertEqual(self.mgr.effective_profile(), "performance")
        self.assertEqual(self.autos, [])

    def test_power_profile_follows_game_and_is_restored(self):
        util.set_setting("fan_power_sync", True)
        self.power[:] = ["power-saver"]
        hwcontrol.set_game_profile("performance")
        self.mgr.set_game("Jogo")
        self.assertEqual(self.power[-1], "performance")
        self.mgr.set_game(None)
        self.mgr._cooldown_over()
        self.assertEqual(self.power[-1], "power-saver")

    def test_shutdown_during_game_restores_power(self):
        util.set_setting("fan_power_sync", True)
        self.power[:] = ["balanced"]
        hwcontrol.set_game_profile("max")
        self.mgr.set_game("Jogo")
        self.mgr.shutdown()
        self.assertEqual(self.power[-1], "balanced")
        self.assertIn("hwmon0/pwm1", self.autos)

    def test_refresh_applies_new_setting_mid_game(self):
        self.mgr.set_game("Jogo")
        self.assertEqual(self.mgr.effective_profile(), "auto")
        hwcontrol.set_game_profile("max")
        self.mgr.refresh_game()
        self.assertEqual(self.writes[-1], 100.0)


if __name__ == "__main__":
    unittest.main()
