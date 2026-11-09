"""Testes do parser S.M.A.R.T. (nexo/core/smart.py) com JSON no formato do `smartctl -j -x`.

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import unittest

from nexo.core import smart


def nvme(**health):
    h = {"critical_warning": 0, "temperature": 41, "available_spare": 100, "available_spare_threshold": 10,
         "percentage_used": 3, "data_units_read": 20_000_000, "data_units_written": 30_000_000,
         "power_cycles": 812, "power_on_hours": 2400, "unsafe_shutdowns": 37, "media_errors": 0,
         "num_err_log_entries": 0}
    h.update(health)
    return {"smartctl": {"exit_status": 0}, "device": {"protocol": "NVMe"}, "model_name": "KINGSTON SNV3S1000G",
            "serial_number": "ABC", "firmware_version": "SBM02103", "user_capacity": {"bytes": 1_000_204_886_016},
            "smart_status": {"passed": True}, "temperature": {"current": h["temperature"]},
            "power_on_time": {"hours": h["power_on_hours"]}, "power_cycle_count": h["power_cycles"],
            "nvme_smart_health_information_log": h, "nvme_optional_admin_commands": {"self_test": True}}


def ata(attrs=(), status=0, passed=True, temp=34, stats_used=None):
    base = {1: 0, 5: 0, 9: 18000, 12: 1500, 174: 90, 197: 0, 198: 0, 199: 0, 202: 0, 246: 40_000_000_000}
    table = []
    overrides = dict(attrs)
    for i, raw in {**base, **overrides}.items():
        name = {202: "Percent_Lifetime_Remain", 246: "Total_Host_Sectors_Write"}.get(i, f"Attr_{i}")
        value = 92 if i == 202 else 100
        table.append({"id": i, "name": name, "value": value, "worst": value, "thresh": 1, "when_failed": "",
                      "raw": {"value": raw, "string": str(raw)}})
    j = {"smartctl": {"exit_status": status}, "device": {"protocol": "ATA"}, "model_name": "Micron MTFDDAK256TBN",
         "serial_number": "X1", "user_capacity": {"bytes": 256_060_514_304}, "rotation_rate": 0,
         "logical_block_size": 512, "smart_status": {"passed": passed}, "temperature": {"current": temp},
         "power_on_time": {"hours": 18000}, "power_cycle_count": 1500,
         "ata_smart_attributes": {"table": table},
         "ata_smart_data": {"capabilities": {"self_tests_supported": True}}}
    if stats_used is not None:
        j["ata_device_statistics"] = {"pages": [{"table": [
            {"name": "Percentage Used Endurance Indicator", "value": stats_used}]}]}
    return j


class NvmeTests(unittest.TestCase):
    def test_healthy(self):
        d = smart.parse_smartctl(nvme(), "/dev/nvme0n1", {"tran": "nvme", "rota": False})
        self.assertEqual(d["verdict"], "ok")
        self.assertEqual(d["kind"], "SSD NVMe")
        self.assertEqual(d["life"], 97)
        self.assertEqual(d["written"], 30_000_000 * 512_000)
        self.assertEqual(d["unsafe"], 37)
        self.assertTrue(d["can_selftest"])
        self.assertEqual(d["reasons"], [])

    def test_worn_out(self):
        d = smart.parse_smartctl(nvme(percentage_used=95), "/dev/nvme0n1")
        self.assertEqual(d["life"], 5)
        self.assertEqual(d["verdict"], "bad")

    def test_used_over_100_clamps(self):
        self.assertEqual(smart.parse_smartctl(nvme(percentage_used=130), "x")["life"], 0)

    def test_critical_warning_and_spare(self):
        d = smart.parse_smartctl(nvme(critical_warning=1, available_spare=5), "x")
        self.assertEqual(d["verdict"], "bad")
        self.assertTrue(any("reserva" in t for _k, t in d["reasons"]))

    def test_hot(self):
        d = smart.parse_smartctl(nvme(temperature=74), "x")
        self.assertEqual(d["verdict"], "warn")

    def test_media_errors(self):
        self.assertEqual(smart.parse_smartctl(nvme(media_errors=2), "x")["verdict"], "warn")


class AtaTests(unittest.TestCase):
    def test_healthy_ssd(self):
        d = smart.parse_smartctl(ata(), "/dev/sda", {"tran": "sata", "rota": False})
        self.assertEqual(d["verdict"], "ok", d["reasons"])
        self.assertEqual(d["kind"], "SSD")
        self.assertEqual(d["life"], 92)          # atributo 202 normalizado
        self.assertEqual(d["written"], 40_000_000_000 * 512)
        self.assertEqual(d["unsafe"], 90)

    def test_device_statistics_win_over_attribute(self):
        self.assertEqual(smart.parse_smartctl(ata(stats_used=20), "x")["life"], 80)

    def test_reallocated_sectors(self):
        self.assertEqual(smart.parse_smartctl(ata({5: 8}), "x")["verdict"], "warn")
        self.assertEqual(smart.parse_smartctl(ata({5: 200}), "x")["verdict"], "bad")

    def test_crc_is_cable(self):
        d = smart.parse_smartctl(ata({199: 12}), "x")
        self.assertEqual(d["verdict"], "warn")
        self.assertTrue(any("cabo" in t for _k, t in d["reasons"]))

    def test_failing(self):
        d = smart.parse_smartctl(ata(passed=False, status=8), "x")
        self.assertEqual(d["verdict"], "bad")

    def test_hdd_temperature_limits(self):
        j = ata(temp=55)
        j["rotation_rate"] = 7200
        d = smart.parse_smartctl(j, "x")
        self.assertEqual(d["kind"], "HDD 7200 rpm")
        self.assertIsNone(d["life"])              # sem vida restante num disco mecânico
        self.assertEqual(d["verdict"], "warn")

    def test_permission_denied(self):
        j = {"smartctl": {"exit_status": 2, "messages": [
            {"string": "Smartctl open device: /dev/sda failed: Permission denied"}]}}
        d = smart.parse_smartctl(j, "/dev/sda", {"model": "Micron", "size": 10})
        self.assertEqual(d["verdict"], "unknown")
        self.assertIn("permissão", d["error"])


class WindowsTests(unittest.TestCase):
    def test_powershell_healthy(self):
        d = smart.parse_windows_ps({"Name": "Samsung SSD 980", "Media": "SSD", "Bus": "NVMe", "Size": 10**12,
                                    "Health": "Healthy", "Temp": 40, "Wear": 4, "Hours": 3000})
        self.assertEqual(d["verdict"], "ok")
        self.assertEqual(d["life"], 96)
        self.assertEqual(d["kind"], "SSD NVMe")

    def test_powershell_unhealthy(self):
        d = smart.parse_windows_ps({"Name": "HDD", "Media": "HDD", "Bus": "SATA", "Health": "Unhealthy"})
        self.assertEqual(d["verdict"], "bad")


class LinuxReadTests(unittest.TestCase):
    def test_split_output_of_one_pkexec_call(self):
        import json
        out = ("@@NEXO nvme0n1\n" + json.dumps(nvme()) + "\n@@NEXO sda\n" + json.dumps(ata()))
        orig = (smart.list_block_disks, smart.run_root)
        smart.list_block_disks = lambda: [{"name": "nvme0n1", "tran": "nvme", "rota": False, "size": 1},
                                          {"name": "sda", "tran": "sata", "rota": False, "size": 1}]
        smart.run_root = lambda script, timeout=0: (0, out)
        try:
            res = smart._read_linux("/usr/bin/smartctl")
        finally:
            smart.list_block_disks, smart.run_root = orig
        self.assertEqual([d["dev"] for d in res["disks"]], ["/dev/nvme0n1", "/dev/sda"])
        self.assertEqual({d["verdict"] for d in res["disks"]}, {"ok"})

    def test_password_cancelled(self):
        orig = (smart.list_block_disks, smart.run_root)
        smart.list_block_disks = lambda: [{"name": "sda", "size": 1}]
        smart.run_root = lambda script, timeout=0: (126, "")
        try:
            res = smart._read_linux("/usr/bin/smartctl")
        finally:
            smart.list_block_disks, smart.run_root = orig
        self.assertEqual(res["disks"], [])
        self.assertIn("cancelado", res["error"])


if __name__ == "__main__":
    unittest.main()
