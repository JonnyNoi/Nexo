"""Bateria, velocidade da RAM, tempo de arranque, Wi-Fi, programas instalados, relatório semanal e CLI (2.3)."""
import io
import os
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from nexo.core import battery, boottime, programs, ramspeed, util, weekly, wifi


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None)):
            p.start()
            self.addCleanup(p.stop)


class Battery(unittest.TestCase):
    def _sysfs(self, root: Path, name: str, files: dict):
        d = root / name
        d.mkdir()
        for k, v in files.items():
            (d / k).write_text(str(v))

    def test_linux_energy_and_charge(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            self._sysfs(root, "BAT0", {"type": "Battery", "energy_full_design": 57_000_000,
                                       "energy_full": 41_040_000, "cycle_count": 412, "capacity": 63,
                                       "status": "Discharging", "power_now": 9_500_000, "model_name": "5B10W13930"})
            self._sysfs(root, "BAT1", {"type": "Battery", "charge_full_design": 4000_000, "charge_full": 3900_000,
                                       "cycle_count": 0, "status": "Full"})
            self._sysfs(root, "hidpp_battery_0", {"type": "Battery", "scope": "Device", "capacity": 80})
            self._sysfs(root, "AC", {"type": "Mains", "online": 1})
            bats = battery._linux(str(root))
        self.assertEqual([b.name for b in bats], ["BAT0", "BAT1"])
        b0, b1 = bats
        self.assertAlmostEqual(b0.health_pct, 72.0)
        self.assertEqual(b0.cycles, 412)
        self.assertEqual(b0.status, "A descarregar")
        self.assertEqual(b0.power_w, 9.5)
        self.assertEqual(b0.verdict()[0], "warn")
        self.assertEqual(b1.unit, "mAh")
        self.assertIsNone(b1.cycles)          # 0 = o firmware não indica
        self.assertEqual(b1.verdict()[0], "ok")

    def test_verdict_thresholds(self):
        self.assertEqual(battery.Battery("x", 50, 25).verdict()[0], "bad")
        self.assertEqual(battery.Battery("x", 0, 25).verdict()[0], "ok")   # sem capacidade original
        self.assertIsNone(battery.Battery("x", 0, 25).health_pct)

    def test_windows_parse(self):
        data = {"static": {"DesignedCapacity": 50000, "DeviceName": "DELL 7FHHV"}, "full": {"FullChargedCapacity": 45000},
                "cyc": {"CycleCount": 120}, "st": {"Charging": True}, "w32": {"Name": "Bateria", "EstimatedChargeRemaining": 81}}
        b = battery.parse_windows(data)[0]
        self.assertAlmostEqual(b.health_pct, 90.0)
        self.assertEqual((b.cycles, b.percent, b.status), (120, 81, "A carregar"))
        self.assertEqual(battery.parse_windows({}), [])


class RamSpeed(unittest.TestCase):
    UDEV = """MEMORY_DEVICE_0_PRESENT=0
MEMORY_DEVICE_1_SIZE=17179869184
MEMORY_DEVICE_1_TYPE=DDR5
MEMORY_DEVICE_1_SPEED_MTS=4800
MEMORY_DEVICE_1_CONFIGURED_SPEED_MTS=4800
MEMORY_DEVICE_1_PART_NUMBER=UD5-6000
MEMORY_DEVICE_1_LOCATOR=DIMMA2
MEMORY_DEVICE_3_SIZE=17179869184
MEMORY_DEVICE_3_TYPE=DDR5
MEMORY_DEVICE_3_SPEED_MTS=4800
MEMORY_DEVICE_3_CONFIGURED_SPEED_MTS=4800
MEMORY_DEVICE_3_PART_NUMBER=UD5-6000
"""

    def test_part_numbers(self):
        cases = {"UD5-6000": 6000, "F5-6000J3038F16G": 6000, "CMK32GX4M2D3600C18": 3600, "KF436C17BBK2/16": 3600,
                 "KF560C40BBK2-32": 6000, "BL2K8G32C16U4B": 3200, "M378A1K43CB2-CTD": None, "Not Specified": None,
                 "HMA82GS6CJR8N-XN": None, "": None}
        for part, want in cases.items():
            with self.subTest(part=part):
                self.assertEqual(ramspeed.rated_from_part(part), want)

    def test_xmp_off_detected(self):
        mods = ramspeed.parse_udev(self.UDEV)
        self.assertEqual(len(mods), 2)
        v = ramspeed.check(mods)
        self.assertEqual((v.kind, v.current, v.rated), ("warn", 4800, 6000))
        self.assertIn("XMP", v.text)

    def test_running_at_rated_speed(self):
        mods = ramspeed.parse_udev(self.UDEV.replace("CONFIGURED_SPEED_MTS=4800", "CONFIGURED_SPEED_MTS=6000"))
        self.assertEqual(ramspeed.check(mods).kind, "ok")

    def test_below_jedec_and_no_data(self):
        mods = [ramspeed.Module("A", jedec=3200, configured=2133, part="M378A1K43CB2-CTD")]
        self.assertEqual(ramspeed.check(mods).kind, "warn")
        self.assertIsNone(ramspeed.check([]))
        self.assertIsNone(ramspeed.check([ramspeed.Module("A")]))

    def test_windows_parse(self):
        rows = [{"DeviceLocator": "DIMM1", "Capacity": 8 << 30, "Speed": 3200, "ConfiguredClockSpeed": 2133,
                 "PartNumber": "CMK16GX4M2B3200C16 ", "SMBIOSMemoryType": 26}]
        m = ramspeed.parse_windows(rows)[0]
        self.assertEqual((m.kind, m.rated, m.configured), ("DDR4", 3200, 2133))


class BootTime(TempConfig):
    ANALYZE = ("Startup finished in 12.650s (firmware) + 1.967s (loader) + 761ms (kernel) + 5.127s (initrd) "
               "+ 1min 3.713s (userspace) = 1min 24.219s \ngraphical.target reached after 3.620s in userspace.")
    CHAIN = """graphical.target @3.620s
└─multi-user.target @3.620s
  └─libvirtd.service @3.219s +399ms
    └─NetworkManager.service @2.613s +6.604s
      └─dbus.socket @2.555s +61us
"""

    def test_parse(self):
        total, ph = boottime.parse_analyze(self.ANALYZE)
        self.assertAlmostEqual(total, 84.219)
        self.assertAlmostEqual(ph["userspace"], 63.713)
        self.assertEqual(set(ph), {"firmware", "loader", "kernel", "initrd", "userspace"})
        self.assertIsNone(boottime.parse_analyze("Bootup is not yet finished."))
        d = boottime.parse_chain(self.CHAIN)
        self.assertEqual([x.name for x in d], ["NetworkManager.service", "libvirtd.service"])   # sem o socket de 61 µs

    def test_advice(self):
        b = boottime.Boot("x", 0, 84.2, {"firmware": 12.6}, [boottime.Delay("NetworkManager.service", 6.6)])
        texts = " ".join(t for _k, t in boottime.advice(b))
        self.assertIn("Fast Boot", texts)
        self.assertIn("NetworkManager", texts)
        self.assertEqual(boottime.advice(boottime.Boot("y", 0, 15, {}))[0][0], "ok")

    def test_windows_parse(self):
        data = {"boot": {"When": "2026-11-16T08:22:39.000Z", "BootTime": "31250", "Main": "21000", "Post": "10250"},
                "slow": [{"Id": 101, "Name": "Steam Client Bootstrapper", "Ms": "4200"},
                         {"Id": 101, "Name": "Steam Client Bootstrapper", "Ms": "1500"},
                         {"Id": 102, "Name": "nvlddmkm", "Ms": "800"}]}
        b = boottime.parse_windows(data)
        self.assertAlmostEqual(b.total, 31.25)
        self.assertEqual(b.phases, {"main": 21.0, "post": 10.25})
        self.assertEqual([(d.name, d.seconds, d.kind) for d in b.delays],
                         [("Steam Client Bootstrapper", 4.2, "programa"), ("nvlddmkm", 0.8, "controlador")])
        self.assertIsNone(boottime.parse_windows({}))

    def test_history_and_trend(self):
        from nexo.core import changes
        t = time.time() - 10 * 86400
        for i, total in enumerate((30, 31, 29, 30)):
            boottime.record(boottime.Boot(f"b{i}", t + i * 86400, total))
        boottime.record(boottime.Boot("b3", t + 3 * 86400, 30))              # o mesmo arranque não duplica
        changes.mark("arranque", "Desativou «Discord» no arranque", now=t + 3.5 * 86400)
        boottime.record(boottime.Boot("b4", t + 4 * 86400, 22))
        hist = boottime.history()
        self.assertEqual(len(hist), 5)
        tr = boottime.trend(hist)
        self.assertLess(tr.delta, -7)
        self.assertEqual(len(tr.changes), 1)
        self.assertIn("mais rápido", tr.text())
        self.assertIn("arranque", tr.text())


class Wifi(unittest.TestCase):
    NMCLI = ("*:CasaNet:AA\\:BB\\:CC\\:DD\\:EE\\:01:6:2437 MHz:130 Mbit/s:48:WPA2\n"
             " :CasaNet:AA\\:BB\\:CC\\:DD\\:EE\\:02:44:5220 MHz:540 Mbit/s:62:WPA2\n"
             " :Viz1:11\\:22\\:33\\:44\\:55\\:01:5:2432 MHz:130 Mbit/s:70:WPA2\n"
             " :Viz2:11\\:22\\:33\\:44\\:55\\:02:7:2442 MHz:130 Mbit/s:55:WPA2\n"
             " :Viz3:11\\:22\\:33\\:44\\:55\\:03:6:2437 MHz:130 Mbit/s:40:WPA3\n"
             " :Viz4:11\\:22\\:33\\:44\\:55\\:04:9:2452 MHz:130 Mbit/s:35:WPA2\n"
             " ::11\\:22\\:33\\:44\\:55\\:05:11:2462 MHz:130 Mbit/s:20:WPA2\n")

    def test_nmcli_and_analysis(self):
        nets = wifi.parse_nmcli(self.NMCLI)
        self.assertEqual(len(nets), 7)
        cur = next(n for n in nets if n.in_use)
        self.assertEqual((cur.ssid, cur.channel, cur.band, cur.signal), ("CasaNet", 6, "2.4 GHz", 48))
        self.assertEqual(nets[1].band, "5 GHz")
        self.assertEqual(nets[-1].ssid, "(rede oculta)")
        st = wifi.WifiState(cur, nets)
        self.assertEqual(wifi.crowding(cur, nets), 4)
        self.assertEqual(wifi.best_24_channel(nets, "CasaNet"), 1)
        kinds = [k for k, _t in wifi.analyze(st)]
        self.assertEqual(kinds, ["warn", "warn", "warn"])      # sinal fraco, há 5 GHz, canal cheio

    def test_netsh_english_and_portuguese(self):
        en = """
    Name                   : Wi-Fi
    SSID                   : CasaNet
    BSSID                  : aa:bb:cc:dd:ee:02
    Radio type             : 802.11ax
    Band                   : 5 GHz
    Channel                : 44
    Receive rate (Mbps)    : 1201
    Signal                 : 92%
"""
        pt = en.replace("Radio type", "Tipo de rádio").replace("Band ", "Banda").replace("Channel", "Canal") \
               .replace("Receive rate (Mbps)", "Taxa de receção (Mbps)").replace("Signal", "Sinal")
        for text in (en, pt):
            n = wifi.parse_netsh_interface(text)
            self.assertEqual((n.ssid, n.signal, n.channel, n.band, n.rate), ("CasaNet", 92, 44, "5 GHz", "1201 Mbit/s"))
        nets = wifi.parse_netsh_networks("""
SSID 1 : CasaNet
    Network type            : Infrastructure
    Authentication          : WPA2-Personal
    BSSID 1                 : aa:bb:cc:dd:ee:01
         Signal             : 70%
         Channel            : 6
    BSSID 2                 : aa:bb:cc:dd:ee:02
         Signal             : 92%
         Channel            : 44
SSID 2 : Vizinho
    Authentication          : WPA3-Personal
    BSSID 1                 : 11:22:33:44:55:66
         Signal             : 30%
         Channel            : 11
""")
        self.assertEqual([(n.ssid, n.channel, n.band, n.security[:4]) for n in nets],
                         [("CasaNet", 6, "2.4 GHz", "WPA2"), ("CasaNet", 44, "5 GHz", "WPA2"),
                          ("Vizinho", 11, "2.4 GHz", "WPA3")])


class Programs(unittest.TestCase):
    QEI = """Name            : code
Version         : 1.138.0-2.1
Description     : The Open Source build of Visual Studio Code
Installed Size  : 769.95 MiB
Packager        : CachyOS <admin@cachyos.org>
Install Date    : Thu Oct  1 18:44:13 2026

Name            : linux-cachyos
Version         : 6.18.1-1
Description     : The Linux kernel
Installed Size  : 140.20 MiB
Install Date    : Thu Oct  1 18:40:00 2026
"""

    def test_pacman_parse_and_protection(self):
        import locale
        try:   # dentro do Qt o locale é o do sistema: a data não pode depender dele
            locale.setlocale(locale.LC_TIME, "pt_PT.UTF-8")
        except locale.Error:
            pass
        self.addCleanup(locale.setlocale, locale.LC_TIME, "C")
        a, b = programs.parse_pacman_qi(self.QEI)
        self.assertEqual((a.name, a.version, a.source), ("code", "1.138.0-2.1", "pacman"))
        self.assertEqual(a.size, int(769.95 * 1024 ** 2))
        self.assertEqual(time.localtime(a.installed)[:3], (2026, 10, 1))
        self.assertFalse(a.protected)
        self.assertTrue(b.protected)
        ok, msg = programs.uninstall(b)
        self.assertFalse(ok)
        self.assertIn("essencial", msg)

    def test_protected_names(self):
        for n in ("linux", "linux-zen", "glibc", "systemd-libs", "plasma-desktop", "nvidia-utils", "base"):
            self.assertTrue(programs.is_protected(n), n)
        for n in ("firefox", "steam", "code", "cachyos-wallpapers", "gimp"):
            self.assertFalse(programs.is_protected(n), n)

    def test_size_parse(self):
        self.assertEqual(programs._parse_size("1,5 GB"), 1_500_000_000)
        self.assertEqual(programs._parse_size("12.0 KiB"), 12 * 1024)
        self.assertEqual(programs._parse_size("?"), 0)


class Weekly(TempConfig):
    def test_score_history_keeps_worst_of_day(self):
        now = time.time()
        weekly.record_score(90, now)
        weekly.record_score(70, now)
        weekly.record_score(85, now)
        self.assertEqual(weekly._avg_score(now - 86400, now), 70)

    def test_build_and_export(self):
        now = time.time()
        for d in range(14):
            weekly.record_score(80 if d < 7 else 90, now - d * 86400)
        boottime.record(boottime.Boot("a", now - 2 * 86400, 25))
        boottime.record(boottime.Boot("b", now - 9 * 86400, 35))
        rep = weekly.build(now)
        self.assertEqual((rep.score, rep.score_prev), (80, 90))
        self.assertIn("−10", rep.headline)
        texts = " ".join(ln.text for ln in rep.lines)
        self.assertIn("Arranque médio: 25,0 s", texts)
        self.assertIn("mais rápido", texts)
        html = weekly.to_html(rep)
        self.assertIn("<!doctype html>", html)
        self.assertIn("Saúde do PC", weekly.to_text(rep))
        again = weekly.Report.from_dict(rep.as_dict())
        self.assertEqual(again.headline, rep.headline)

    def test_due_waits_a_week(self):
        now = time.time()
        self.assertFalse(weekly.due(now))           # 1.ª vez só marca o início
        self.assertFalse(weekly.due(now + 3 * 86400))
        self.assertTrue(weekly.due(now + 8 * 86400))
        weekly.generate(now + 8 * 86400)
        self.assertFalse(weekly.due(now + 9 * 86400))
        self.assertIsNotNone(weekly.last())
        util.set_setting("weekly_report", False)
        self.assertFalse(weekly.due(now + 30 * 86400))


class Cli(TempConfig):
    def _run(self, *args) -> tuple[int, str]:
        from nexo import cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.main(["nexo", *args])
        return code, buf.getvalue()

    def test_wants_cli(self):
        from nexo import cli
        self.assertTrue(cli.wants_cli(["nexo", "--saude"]))
        self.assertFalse(cli.wants_cli(["nexo", "--minimized"]))
        self.assertFalse(cli.wants_cli(["nexo"]))

    def test_version_help_and_weekly(self):
        code, out = self._run("--versao")
        self.assertEqual(code, 0)
        self.assertIn(util.APP_VERSION, out)
        self.assertIn("--relatorio", self._run("--ajuda")[1])
        code, out = self._run("--relatorio-semanal")
        self.assertEqual(code, 0)
        self.assertIn("relatório de", out)
        path = os.path.join(self.tmp.name, "semana.html")
        self.assertEqual(self._run("--relatorio-semanal", path)[0], 0)
        self.assertTrue(Path(path).read_text(encoding="utf-8").startswith("<!doctype html>"))

    def test_health_json_exit_code(self):
        import json
        from nexo import cli
        from nexo.core.healthscore import Check
        with mock.patch.object(cli, "health_checks", return_value=[Check("bad", "Disco a falhar", "Saúde dos discos"),
                                                                    Check("bad", "Outro", None),
                                                                    Check("ok", "Tudo bem")]):
            code, out = self._run("--saude", "--json")
        data = json.loads(out)
        self.assertEqual(data["score"], 50)
        self.assertEqual(code, 1)
        self.assertEqual(len(data["checks"]), 3)

    def test_report_needs_path(self):
        self.assertEqual(self._run("--relatorio")[0], 64)


if __name__ == "__main__":
    unittest.main()
