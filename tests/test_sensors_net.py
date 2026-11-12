"""Sensores (conversões e escolha das leituras), teste de velocidade e DNS — só funções puras / com mocks."""
import os
import tempfile
import unittest
from unittest import mock

from nexo.core import sensors, speedtest, systools, util
from nexo.core.sensors import Reading, SensorReader


class Hwmon(unittest.TestCase):
    def test_groups(self):
        self.assertEqual(sensors._hwmon_group("k10temp"), "CPU")
        self.assertEqual(sensors._hwmon_group("amdgpu"), "GPU")
        self.assertEqual(sensors._hwmon_group("nvme"), "Disco")
        self.assertEqual(sensors._hwmon_group("nct6687"), "Placa-mãe")
        self.assertEqual(sensors._hwmon_group("spd5118"), "Memória")
        self.assertEqual(sensors._hwmon_group("desconhecido"), "desconhecido")

    def test_convert_units(self):
        cv = SensorReader._convert
        self.assertEqual(cv("CPU", "temp", "temp1", "Tctl", 54250).value, 54.25)
        self.assertIsNone(cv("CPU", "temp", "temp1", "Tctl", 0))           # sensor desligado
        self.assertIsNone(cv("CPU", "temp", "temp1", "Tctl", 200000))      # leitura absurda
        self.assertEqual(cv("ACPI", "temp", "temp1", "1", 40000).name, "Zona 1")
        r = cv("Placa-mãe", "fan", "fan2", "fan2", 1200)
        self.assertEqual((r.value, r.unit, r.kind), (1200, "RPM", "fan"))
        self.assertAlmostEqual(cv("Placa-mãe", "in", "in0", "Vcore", 1250).value, 1.25)
        p = cv("GPU", "power", "power1", "power1", 45_500_000)
        self.assertEqual((p.name, p.value, p.unit), ("Consumo", 45.5, "W"))
        self.assertEqual(cv("GPU", "freq", "freq1", "sclk", 2_600_000_000).value, 2600)
        self.assertIsNone(cv("GPU", "xpto", "x1", "x", 1))


class Nvidia(unittest.TestCase):
    def test_parse(self):
        res = SensorReader._nv_parse(["65, 97, 2550, 10501, 220.5, 6000, 12288, 55",
                                      "40, [N/A], 300, 405, [N/A], 100, 8192, [N/A]"])
        first = {r.name: r.value for r in res if r.group == "GPU"}
        self.assertEqual(first["Temperatura"], 65)
        self.assertEqual(first["Carga"], 97)
        self.assertEqual(first["Consumo"], 220.5)
        self.assertAlmostEqual(first["VRAM em uso"], 6000 * 100 / 12288)
        second = {r.name for r in res if r.group == "GPU 2"}
        self.assertIn("Temperatura", second)
        self.assertNotIn("Carga", second)     # [N/A] não vira número
        self.assertNotIn("Ventoinha", second)

    def test_short_line(self):
        self.assertEqual([r.name for r in SensorReader._nv_parse(["70"])], ["Temperatura"])


class Windows(unittest.TestCase):
    def test_parse(self):
        rd = SensorReader.__new__(SensorReader)
        data = {"lhm": [
            {"SensorType": "Temperature", "Name": "CPU Package", "Value": 61.5, "Parent": "/amdcpu/0"},
            {"SensorType": "Load", "Name": "CPU Total", "Value": 30, "Parent": "/amdcpu/0"},   # vem do psutil
            {"SensorType": "Load", "Name": "GPU Core", "Value": 88, "Parent": "/gpu-amd/0"},
            {"SensorType": "Fan", "Name": "Fan #1", "Value": 900, "Parent": "/lpc/nct6687d"},
            {"SensorType": "Temperature", "Name": "Temperature", "Value": None, "Parent": "/nvme/0"},
            {"SensorType": "Data", "Name": "Used", "Value": 3, "Parent": "/ram"},
        ], "acpi": {"CurrentTemperature": 3132, "InstanceName": "ACPI\\ThermalZone\\TZ00_0"}, "gpu": 50}
        res = rd._win_parse(data)
        names = {(r.group, r.name) for r in res}
        self.assertIn(("CPU", "CPU Package"), names)
        self.assertNotIn(("CPU", "CPU Total"), names)
        self.assertIn(("Placa-mãe", "Fan #1"), names)
        self.assertIn(("ACPI", "Zona TZ00_0"), names)
        gpu_loads = [r for r in res if r.group == "GPU" and r.kind == "load"]
        self.assertEqual([r.value for r in gpu_loads], [88])   # o contador genérico não duplica
        self.assertEqual(rd._win_parse(None), [])


class Pick(unittest.TestCase):
    def r(self, group, name, value, kind="temp"):
        return Reading(group, name, value, "°C", kind)

    def test_cpu_prefers_package(self):
        rs = [self.r("CPU", "Core 0", 70), self.r("CPU", "Tctl", 62), self.r("CPU", "Core 1", 75)]
        self.assertEqual(sensors.pick_cpu_temp(rs), 62)
        self.assertEqual(sensors.pick_cpu_temp([self.r("CPU", "Core 0", 70), self.r("CPU", "Core 1", 75)]), 75)
        self.assertEqual(sensors.pick_cpu_temp([self.r("ACPI", "Zona 1", 50), self.r("ACPI", "Zona 2", 55)]), 55)
        self.assertIsNone(sensors.pick_cpu_temp([]))

    def test_gpu(self):
        rs = [self.r("GPU", "junction", 80), self.r("GPU", "edge", 66)]
        self.assertEqual(sensors.pick_gpu_temp(rs), 66)
        self.assertIsNone(sensors.pick_gpu_temp([self.r("CPU", "Tctl", 50)]))

    def test_pick_and_power(self):
        rs = [self.r("GPU", "Carga", 40, "load"), Reading("GPU", "Consumo", 120, "W", "power")]
        self.assertEqual(sensors.pick(rs, "GPU", "Carga"), 40)
        self.assertIsNone(sensors.pick(rs, "CPU", "Carga"))
        self.assertEqual(sensors.pick_power(rs, "GPU"), 120)


class Speed(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(speedtest.duration_for(1e9, 0), "—")
        self.assertEqual(speedtest.duration_for(100e6, 100), "~8 s")
        self.assertEqual(speedtest.duration_for(2e9, 100), "~3 min")
        self.assertEqual(speedtest.duration_for(50e9, 30), "~3,7 h")

    def test_quality_levels(self):
        fast = speedtest.SpeedResult(ping_ms=12, jitter_ms=2, download_mbps=500, upload_mbps=50)
        self.assertTrue(all(lvl == "ok" for _a, lvl, _t in speedtest.quality(fast)))
        slow = speedtest.SpeedResult(ping_ms=150, jitter_ms=40, download_mbps=2, upload_mbps=0.5)
        self.assertTrue(all(lvl == "bad" for _a, lvl, _t in speedtest.quality(slow)))
        empty = speedtest.quality(speedtest.SpeedResult())
        self.assertEqual(len(empty), 6)

    def test_bufferbloat(self):
        S = speedtest.SpeedResult
        self.assertIsNone(speedtest.bufferbloat(S(ping_ms=10)))
        self.assertEqual(speedtest.bufferbloat(S(ping_ms=10, loaded_ping_ms=20))[0], "ok")
        self.assertEqual(speedtest.bufferbloat(S(ping_ms=10, loaded_ping_ms=80))[0], "warn")
        self.assertEqual(speedtest.bufferbloat(S(ping_ms=10, loaded_ping_ms=300))[0], "bad")

    def test_server_timing(self):
        resp = mock.Mock()
        resp.getheader.return_value = "cfRequestDuration;dur=12.5, other;dur=3, broken;dur=x"
        self.assertEqual(speedtest._server_ms(resp), 12.5)
        resp.getheader.return_value = None
        self.assertEqual(speedtest._server_ms(resp), 0.0)

    def test_history_keeps_30(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": tmp, "APPDATA": tmp}), \
                mock.patch.object(util, "_settings", None):
            for i in range(35):
                speedtest.save(speedtest.SpeedResult(download_mbps=i))
            h = speedtest.history()
            self.assertEqual(len(h), 30)
            self.assertEqual(h[0]["download_mbps"], 34)    # o mais recente primeiro
            speedtest.clear_history()
            self.assertEqual(speedtest.history(), [])


class Dns(unittest.TestCase):
    @unittest.skipIf(util.IS_WIN, "caminho do Linux")
    def test_current_dns_resolvectl(self):
        out = ("Global: 1.1.1.1\nLink 2 (enp5s0): 192.168.1.1 1.1.1.1 fe80::1\nLink 3 (wlan0):")
        with mock.patch.object(systools, "which", return_value="/usr/bin/resolvectl"), \
                mock.patch.object(systools, "run", return_value=(0, out)):
            self.assertEqual(systools.current_dns(), ["1.1.1.1", "192.168.1.1"])

    @unittest.skipIf(util.IS_WIN, "caminho do Linux")
    def test_set_dns_needs_nmcli(self):
        with mock.patch.object(systools, "which", return_value=None):
            ok, msg = systools.set_dns(["1.1.1.1"])
        self.assertFalse(ok)
        self.assertIn("nmcli", msg)

    @unittest.skipIf(util.IS_WIN, "caminho do Linux")
    def test_set_dns_skips_virtual_links(self):
        calls = []

        def fake_run(cmd, timeout=30):
            calls.append(cmd)
            if cmd[:3] == ["nmcli", "-t", "-f"]:
                return 0, "Casa:802-3-ethernet\nlo:loopback\ndocker0:bridge\nwg0:wireguard\nRede\\:5G:802-11-wireless"
            return 0, ""
        with mock.patch.object(systools, "which", return_value="/usr/bin/nmcli"), \
                mock.patch.object(systools, "run", side_effect=fake_run):
            ok, msg = systools.set_dns(["9.9.9.9"])
        self.assertTrue(ok)
        modified = [c[3] for c in calls if c[:3] == ["nmcli", "connection", "modify"]]
        self.assertEqual(modified, ["Casa", "Rede:5G"])
        self.assertIn(["nmcli", "connection", "modify", "Casa", "ipv4.dns", "9.9.9.9", "ipv4.ignore-auto-dns", "yes"],
                      calls)

    def test_actions_have_names(self):
        for a in systools.actions():
            self.assertTrue(a.name)


if __name__ == "__main__":
    unittest.main()
