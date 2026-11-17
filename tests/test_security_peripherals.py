"""Stress da GPU (ajudas), firewall/portas, privacidade no Linux e periféricos."""
import unittest
from unittest import mock

from nexo.core import firewall as fw
from nexo.core import gpustress, peripherals, privacy_linux
from nexo.core.firewall import FwStatus, Port


class GpuStress(unittest.TestCase):
    def test_vram_amount(self):
        self.assertEqual(gpustress.default_vram_mb(None), 1024)
        self.assertEqual(gpustress.default_vram_mb(8176, 60), 4864)      # múltiplo de 64 MB
        self.assertEqual(gpustress.default_vram_mb(100, 10), gpustress.TEX_MB)

    def test_count_bad(self):
        img = bytes([0, 0, 0, 255] * 10 + [3, 0, 0, 255, 1, 0, 0, 255])
        self.assertEqual(gpustress.count_bad(img), 4)

    def test_command(self):
        cmd = gpustress.child_command(60, 512)
        self.assertIn("--gpustress", cmd)
        self.assertEqual(cmd[-4:], ["--seconds", "60", "--vram-mb", "512"])


class Firewall(unittest.TestCase):
    def test_exposure(self):
        self.assertFalse(fw._exposed("127.0.0.1"))
        self.assertFalse(fw._exposed("::1"))
        self.assertTrue(fw._exposed("0.0.0.0"))
        self.assertFalse(fw._exposed("192.168.122.1", {"192.168.122.1"}))

    def test_off_with_risky_service(self):
        ports = [Port("TCP", 445, "0.0.0.0", "smbd", True), Port("TCP", 631, "127.0.0.1", "", False)]
        with mock.patch.object(fw, "IS_WIN", False):
            kinds = [k for k, _t in fw.analyze(FwStatus(False, "ufw"), ports)]
        self.assertEqual(kinds[0], "bad")

    def test_off_nothing_exposed(self):
        res = fw.analyze(FwStatus(False, ""), [Port("TCP", 631, "::1", "", False)])
        self.assertEqual([k for k, _ in res], ["warn", "ok"])

    def test_on(self):
        res = fw.analyze(FwStatus(True, "ufw"), [Port("TCP", 22, "0.0.0.0", "", True)])
        self.assertEqual(res[0][0], "ok")
        self.assertIn("1 porta", res[0][1])

    def test_normal_udp_ignored(self):
        res = fw.analyze(FwStatus(False, ""), [Port("UDP", 5353, "0.0.0.0", "avahi", True)])
        self.assertIn("Nenhum serviço está aberto", res[0][1])

    def test_docker_api(self):
        res = fw.analyze(FwStatus(True, "ufw"), [Port("TCP", 2375, "0.0.0.0", "dockerd", True)])
        self.assertTrue(any(k == "bad" and "Docker" in t for k, t in res))


class Privacy(unittest.TestCase):
    def test_gsettings_toggle_and_restore(self):
        store = {("org.gnome.desktop.privacy", "remember-recent-files"): "true"}

        def fake_run(cmd, timeout=0):
            if cmd[1] == "get":
                return 0, store[(cmd[2], cmd[3])] + "\n"
            if cmd[1] == "set":
                store[(cmd[2], cmd[3])] = cmd[4]
            return 0, ""
        t = privacy_linux.GsettingsTweak("t_test_recent", "x", "y",
                                         [("org.gnome.desktop.privacy", "remember-recent-files", "false")])
        backup = {}
        with mock.patch.object(privacy_linux, "run", fake_run), \
                mock.patch("nexo.core.tweaks.load_json", lambda *_a, **_k: dict(backup)), \
                mock.patch("nexo.core.tweaks.save_json", lambda _n, d: (backup.clear(), backup.update(d))):
            self.assertFalse(t.is_on())
            self.assertEqual(t.set(True), (True, "Feito"))
            self.assertTrue(t.is_on())
            t.set(False)
            self.assertEqual(store[("org.gnome.desktop.privacy", "remember-recent-files")], "true")
            self.assertEqual(backup, {})


class Peripherals(unittest.TestCase):
    DUMP = """Device: /org/freedesktop/UPower/devices/battery_BAT0
  native-path:          BAT0
  power supply:         yes
  battery
    percentage:          80%

Device: /org/freedesktop/UPower/devices/mouse_hidpp_battery_0
  native-path:          hidpp_battery_0
  model:                G502 LIGHTSPEED
  power supply:         no
  mouse
    present:             yes
    state:               discharging
    percentage:          9%

Device: /org/freedesktop/UPower/devices/gaming_input_ps_controller_battery_aa
  native-path:          ps-controller-battery-aa
  model:                DualSense Wireless Controller
  power supply:         no
  gaming-input
    state:               charging
    percentage:          50% (should be ignored)
    battery-level:       high

Device: /org/freedesktop/UPower/devices/DisplayDevice
  power supply:         no
  unknown
    percentage:          0%
"""

    def test_upower(self):
        devs = peripherals.parse_upower(self.DUMP)
        self.assertEqual([(d.name, d.kind, d.percent) for d in devs],
                         [("G502 LIGHTSPEED", "Rato", 9), ("DualSense Wireless Controller", "Comando", 80)])
        self.assertTrue(devs[1].charging)
        self.assertEqual([d.name for d in peripherals.low_battery(devs)], ["G502 LIGHTSPEED"])

    def test_bluetooth(self):
        bt = peripherals.parse_btshow("Controller 9C:B1:50:18:7A:F8 (public)\n\tAlias: PC\n\tPowered: no\n"
                                      "\tPowerState: off-blocked\n")
        self.assertEqual((bt.present, bt.powered, bt.blocked, bt.name), (True, False, True, "PC"))
        self.assertFalse(peripherals.parse_btshow("No default controller available").present)


if __name__ == "__main__":
    unittest.main()
