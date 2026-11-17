"""Monitor abaixo da taxa de atualização: EDID, ferramentas do compositor e veredicto."""
import json
import unittest

from nexo.core import display, i18n
from nexo.core.display import Monitor


def _dtd(w, h, hz, hb=160, vb=45) -> bytes:
    clock = round((w + hb) * (h + vb) * hz / 10_000)
    return bytes([clock & 0xFF, clock >> 8, w & 0xFF, hb & 0xFF, (w >> 8) << 4 | hb >> 8,
                  h & 0xFF, vb & 0xFF, (h >> 8) << 4 | vb >> 8]) + bytes(10)


def _edid(name="GAMER 27", modes=((1920, 1080, 144),)) -> bytes:
    base = bytearray(b"\x00\xff\xff\xff\xff\xff\xff\x00" + bytes(46))
    descs = [_dtd(*m) for m in modes]
    descs.append(b"\x00\x00\x00\xfc\x00" + (name.encode() + b"\n").ljust(13, b" "))
    while len(descs) < 4:
        descs.append(b"\x00\x00\x00\x10" + bytes(14))
    base += b"".join(descs) + b"\x00\x00"
    return bytes(base)


class Edid(unittest.TestCase):
    def test_name_and_max(self):
        e = display.parse_edid(_edid(modes=((1920, 1080, 60), (1920, 1080, 144))))
        self.assertEqual(e["name"], "GAMER 27")
        self.assertEqual(e["native"], (1920, 1080))
        self.assertAlmostEqual(e["max_hz"], 144, delta=0.1)

    def test_invalid(self):
        self.assertIsNone(display.parse_edid(b"lixo")["max_hz"])


class Tools(unittest.TestCase):
    def test_kscreen(self):
        data = {"outputs": [{"name": "DP-1", "connected": True, "enabled": True, "currentModeId": "1", "modes": [
            {"id": "1", "refreshRate": 60, "size": {"width": 2560, "height": 1440}},
            {"id": "2", "refreshRate": 164.96, "size": {"width": 2560, "height": 1440}},
            {"id": "3", "refreshRate": 240, "size": {"width": 1920, "height": 1080}}]},
            {"name": "HDMI-A-1", "connected": False, "enabled": False, "modes": []}]}
        [m] = display.parse_kscreen(json.dumps(data))
        self.assertEqual((m.output, m.width, m.hz, m.max_hz, m.native), ("DP-1", 2560, 60, 164.96, (2560, 1440)))

    def test_hyprctl(self):
        data = [{"name": "DP-2", "make": "AOC", "model": "24G2", "width": 1920, "height": 1080,
                 "refreshRate": 143.98, "availableModes": ["1920x1080@143.98Hz", "1920x1080@60.00Hz"]}]
        [m] = display.parse_hyprctl(json.dumps(data))
        self.assertEqual((m.name, m.hz, m.max_hz), ("AOC 24G2", 143.98, 143.98))

    def test_sway(self):
        data = [{"name": "DP-1", "active": True, "make": "Dell", "model": "S2721DGF",
                 "current_mode": {"width": 2560, "height": 1440, "refresh": 59951},
                 "modes": [{"width": 2560, "height": 1440, "refresh": 59951},
                           {"width": 2560, "height": 1440, "refresh": 165080}]}]
        [m] = display.parse_sway(json.dumps(data))
        self.assertEqual((m.hz, m.max_hz), (59.95, 165.08))

    def test_xrandr(self):
        text = ("Screen 0: minimum 320 x 200, current 1920 x 1080, maximum 16384 x 16384\n"
                "DP-1 connected primary 1920x1080+0+0 (normal left inverted right x axis y axis) 527mm x 296mm\n"
                "   1920x1080     60.00*+ 144.00   119.98    99.93  \n"
                "   1280x720      60.00  \n"
                "HDMI-1 disconnected (normal left inverted right x axis y axis)\n"
                "   1024x768      60.00  \n")
        [m] = display.parse_xrandr(text)
        self.assertEqual((m.output, m.hz, m.max_hz, m.native), ("DP-1", 60.0, 144.0, (1920, 1080)))


class Verdict(unittest.TestCase):
    def test_60_on_144_warns(self):
        v = display.check(Monitor("DP-1", "AOC", 1920, 1080, 60.0, 144.0, (1920, 1080)))
        self.assertEqual(v.kind, "warn")
        self.assertIn("144 Hz", v.text)

    def test_rounding_is_ok(self):
        self.assertEqual(display.check(Monitor("DP-1", "", 1920, 1080, 59.94, 60.0)).kind, "ok")
        self.assertEqual(display.check(Monitor("DP-1", "", 1920, 1080, 165.0, 170.0)).kind, "ok")

    def test_low_resolution_is_info(self):
        v = display.check(Monitor("DP-1", "", 1920, 1080, 144.0, 144.0, (2560, 1440)))
        self.assertEqual(v.kind, "ok")
        self.assertIn("2560×1440", v.text)

    def test_unknown(self):
        self.assertIsNone(display.check(Monitor("DP-1", max_hz=144.0)))

    def test_qt_fallback(self):
        display.set_qt_screens([{"name": "eDP-1", "model": "", "hz": 60.0, "width": 1920, "height": 1080}])
        self.addCleanup(display.set_qt_screens, [])
        mons = [Monitor("eDP-1", "Painel", max_hz=144.0, native=(1920, 1080))]
        display._merge_qt(mons)
        self.assertEqual(display.check(mons[0]).kind, "warn")

    def test_translated(self):
        i18n.set_lang_for_tests("en")
        self.addCleanup(i18n.set_lang_for_tests, None)
        v = display.check(Monitor("DP-1", "", 1920, 1080, 60.0, 144.0))
        self.assertTrue(i18n.tr(v.text).startswith("The monitor is running at 60 Hz"))


if __name__ == "__main__":
    unittest.main()
