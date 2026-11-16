"""Fiabilidade, throttling, «Porque está lento?» e comparação antes/depois dos benchmarks."""
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from nexo.core import changes, reliability as rel, slowdiag, throttle, util


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None)):
            p.start()
            self.addCleanup(p.stop)


class Reliability(unittest.TestCase):
    def test_classify_kernel(self):
        cases = {
            "amdgpu 0000:03:00.0: amdgpu: GPU reset begin!": "gpu",
            "[drm:amdgpu_job_timedout [amdgpu]] *ERROR* ring gfx_0.0.0 timeout, signaled seq=1": "gpu",
            "NVRM: Xid (PCI:0000:01:00): 79, pid=1234, GPU has fallen off the bus.": "gpu",
            "mce: [Hardware Error]: Machine check events logged": "hardware",
            "Out of memory: Killed process 4242 (brave) total-vm:123kB": "memory",
            "I/O error, dev sda, sector 12345 op 0x0:(READ)": "disk",
            "BTRFS error (device sda2): bdev /dev/sda2 errs: wr 0, rd 1": "disk",
            "watchdog: BUG: soft lockup - CPU#3 stuck for 22s!": "crash",
            "CPU0: Core temperature above threshold, cpu clock throttled": "thermal",
        }
        for msg, cat in cases.items():
            with self.subTest(msg=msg):
                self.assertEqual(rel.classify_kernel(msg)[0], cat)
        self.assertIsNone(rel.classify_kernel("usb 1-1: new high-speed USB device number 2"))

    def test_kernel_grep_is_one_valid_regex(self):
        import re
        re.compile(rel._KERNEL_GREP)

    def test_unclean_boots(self):
        boots = [{"boot_id": "a", "last_entry": 1_000_000_000_000_000},
                 {"boot_id": "b", "last_entry": 1_000_000_100_000_000},
                 {"boot_id": "c", "last_entry": 1_000_000_200_000_000},
                 {"boot_id": "now", "last_entry": 1_000_000_300_000_000}]
        tails = {"a": "x\nsystemd[1]: Stopping Flush Journal to Persistent Storage...\nUnmounted /home.",
                 "b": "brave: algo\nsnapperd.service: Deactivated successfully.",
                 "c": ""}   # sem registos → não sabemos, não conta
        evs = rel.unclean_boots(boots, tails)
        self.assertEqual(len(evs), 1)
        self.assertEqual(evs[0].cat, "shutdown")
        self.assertAlmostEqual(evs[0].when, 1_000_000_100)

    def test_kernel_json(self):
        lines = [json.dumps({"__REALTIME_TIMESTAMP": "1700000000000000", "MESSAGE": "amdgpu: GPU reset begin!"}),
                 json.dumps({"__REALTIME_TIMESTAMP": "1700000001000000",
                             "MESSAGE": list(b"I/O error, dev sdb, sector 1")}),
                 "lixo"]
        evs = rel._kernel_from_json("\n".join(lines))
        self.assertEqual([e.cat for e in evs], ["gpu", "disk"])

    def test_parse_windows(self):
        rows = [{"t": 1700000000, "p": "Microsoft-Windows-Kernel-Power", "id": 41, "m": "O sistema reiniciou…"},
                {"t": 1700000100, "p": "Application Error", "id": 1000, "m": "Faulting application", "a": "game.exe"},
                {"t": 1700000200, "p": "Microsoft-Windows-WHEA-Logger", "id": 19, "m": "Corrected error"},
                {"t": 1700000300, "p": "Outro", "id": 1, "m": "x"}]
        evs = rel.parse_windows(json.dumps(rows))
        self.assertEqual([e.cat for e in evs], ["shutdown", "app", "hardware"])
        self.assertEqual(evs[1].title, "game.exe")
        # o PowerShell devolve um objeto (não lista) quando só há um evento
        self.assertEqual(len(rel.parse_windows(json.dumps(rows[0]))), 1)
        self.assertEqual(rel.parse_windows("não é json"), [])

    def test_group_and_index(self):
        now = 2_000_000_000
        burst = [rel.Event(now - 3600 + i, "disk", "Erro", "") for i in range(50)]
        g = rel.group_events(burst)
        self.assertEqual(len(g), 1)
        self.assertEqual(g[0].count, 50)
        self.assertEqual(rel.stability_index([], now), 10.0)
        idx_disk = rel.stability_index(g, now)
        self.assertLess(idx_disk, 10.0)
        apps = [rel.Event(now - i * 7200, "app", f"p{i}") for i in range(40)]
        self.assertGreaterEqual(rel.stability_index(apps, now), 8.5)   # crashes de programas têm teto
        old = [rel.Event(now - 40 * 86400, "crash", "x")]
        self.assertEqual(rel.stability_index(old, now), 10.0)

    def test_per_day_and_summary(self):
        now = time.time()
        evs = [rel.Event(now, "app", "x"), rel.Event(now, "shutdown", "y"), rel.Event(now - 86400 * 2, "gpu", "z", count=3)]
        days = rel.per_day(evs, now)
        self.assertEqual(len(days), rel.DAYS)
        self.assertEqual(days[-1], "bad")
        self.assertEqual(days[-3], "warn")
        self.assertEqual(rel.summary(evs, now, 7), {"app": 1, "shutdown": 1, "gpu": 3})
        self.assertEqual([e.cat for e in rel.new_since(evs, now - 1)], ["shutdown"])


class Throttle(unittest.TestCase):
    def feed(self, det, n, t0, **s):
        out = []
        for i in range(n):
            out += det.feed(s, now=t0 + i)
        return out

    def test_sustained_heat_with_clock_drop(self):
        det = throttle.Detector(cpu_limit=100, gpu_limit=105)
        t = 0
        self.feed(det, 5, t, gpu_temp=80, gpu_load=99, gpu_clock=2800)       # máximo atingido
        ev = self.feed(det, 5, 10, gpu_temp=104, gpu_load=99, gpu_clock=2300)
        self.assertEqual(ev, [])                                               # ainda não é "sustentado"
        ev = self.feed(det, 5, 15, gpu_temp=104, gpu_load=99, gpu_clock=2300)
        self.assertEqual([w for w, _e in ev], ["start"])
        self.assertIn("gpu", det.active())
        ev = self.feed(det, 10, 30, gpu_temp=85, gpu_load=99, gpu_clock=2800)
        (what, ep), = ev
        self.assertEqual(what, "end")
        self.assertEqual(ep.clock_drop, 18)
        self.assertEqual(ep.peak_temp, 104)
        self.assertEqual(det.active(), {})

    def test_hot_but_full_clock_is_not_throttling(self):
        det = throttle.Detector(cpu_limit=100, gpu_limit=105)
        self.assertEqual(self.feed(det, 30, 0, cpu_temp=99, cpu_load=100, cpu_clock=4400), [])

    def test_idle_clock_drop_is_not_throttling(self):
        det = throttle.Detector(cpu_limit=100, gpu_limit=105)
        self.feed(det, 5, 0, cpu_temp=60, cpu_load=100, cpu_clock=4400)
        self.assertEqual(self.feed(det, 30, 10, cpu_temp=98, cpu_load=10, cpu_clock=800), [])

    def test_intel_counter(self):
        det = throttle.Detector()
        self.assertEqual(det.feed({}, now=0, counter=5), [])
        ev = det.feed({"cpu_temp": 99}, now=1, counter=9)
        self.assertEqual([(w, e.comp) for w, e in ev], [("start", "cpu")])
        self.assertIn("sinal do processador", ev[0][1].reason)

    def test_log_and_describe(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": d, "APPDATA": d}):
            ep = throttle.Episode("gpu", time.time() - 200, time.time() - 20, "temperatura", 104, 18, "Cyberpunk")
            throttle.log_episode(ep)
            (got,) = throttle.recent(1)
            self.assertEqual(got.game, "Cyberpunk")
            txt = throttle.describe(got)
            self.assertIn("A placa gráfica baixou o clock", txt)
            self.assertIn("3 min", txt)


class SlowDiag(unittest.TestCase):
    BASE = {"cpu_total": 5, "apps": [], "ram_pct": 30, "swap_rate": 0, "disk_busy": {"sda": 1}, "known": [],
            "disks": [{"mount": "/", "free_pct": 40, "free": 10**11}], "smart_bad": [], "throttling": {},
            "power": "balanced", "uptime_days": 1, "oom_recent": 0}

    def kinds(self, **over):
        return [(f.kind, f.title) for f in slowdiag.analyze({**self.BASE, **over})]

    def test_nothing_wrong(self):
        (k, _t), = self.kinds()
        self.assertEqual(k, "ok")

    def test_cpu_and_ram(self):
        apps = [{"name": "Brave", "cpu": 70.0, "rss": 6 * 2**30, "n": 30}, {"name": "Steam", "cpu": 3.0, "rss": 2**29, "n": 4}]
        out = self.kinds(cpu_total=95, apps=apps, ram_pct=93)
        self.assertEqual(out[0][0], "bad")
        titles = " ".join(t for _k, t in out)
        self.assertIn("Processador quase no máximo", titles)
        self.assertIn("Memória RAM quase cheia", titles)

    def test_known_disk_power_uptime(self):
        out = self.kinds(known=[{"key": "pacman", "cpu": 30}], disk_busy={"sda": 97},
                         disks=[{"mount": "/", "free_pct": 3, "free": 2 * 10**9}], power="power-saver", uptime_days=12)
        titles = [t for _k, t in out]
        self.assertTrue(any("pacman" in t for t in titles))
        self.assertTrue(any("ocupado a 97" in t for t in titles))
        self.assertTrue(any("Pouco espaço em /" in t for t in titles))
        self.assertTrue(any("Poupança de energia" in t for t in titles))
        self.assertEqual(out[-1][0], "info")     # tempo ligado: só informação, fica no fim

    def test_smart_warn_is_info_only(self):
        out = self.kinds(smart_bad=[{"name": "SSD", "verdict": "warn", "reason": "CRC"}])
        self.assertEqual(out[0][0], "ok")
        self.assertIn(("info", "O disco SSD tem um aviso de saúde"), out)

    def test_throttling(self):
        ep = throttle.Episode("cpu", 0)
        out = self.kinds(throttling={"cpu": ep}, cpu_temp=99)
        self.assertEqual(out[0], ("bad", "O processador está a baixar o clock por temperatura"))
        self.assertFalse(any("Temperatura alta" in t for _k, t in out))   # não repete o mesmo problema


class Changes(TempConfig):
    def test_compare_with_marks(self):
        t0 = 1_800_000_000
        h = [{"date": "a", "ts": t0, "mode": "Multi-core", "quality": "Normal", "cpu": "i5", "score": 1000},
             {"date": "b", "ts": t0 + 10, "mode": "Single-core", "quality": "Normal", "cpu": "i5", "score": 200},
             {"date": "c", "ts": t0 + 100, "mode": "Multi-core", "quality": "Normal", "cpu": "i5", "score": 1100}]
        changes.mark("ajuste", "Ligou o ajuste «X»", now=t0 + 50)
        changes.mark("ajuste", "Ligou o ajuste «X»", now=t0 + 55)      # repetido no mesmo minuto: conta 1
        changes.mark("atualizacao", "Atualizou o sistema", now=t0 + 60)
        changes.mark("limpeza", "fora do intervalo", now=t0 + 500)
        c = changes.compare(h, h[2])
        self.assertAlmostEqual(c.delta_pct, 10.0)
        self.assertEqual(c.verdict, "melhor")
        self.assertEqual(len(c.changes), 2)
        self.assertIn("1 ajuste, 1 atualização", c.text())
        self.assertIsNone(changes.compare(h, h[0]))        # primeiro resultado: nada para comparar
        self.assertIsNone(changes.compare(h, h[1]))        # outro modo não conta

    def test_noise(self):
        h = [{"date": "a", "ts": 1, "mode": "M", "quality": "Q", "cpu": "c", "score": 1000},
             {"date": "b", "ts": 2, "mode": "M", "quality": "Q", "cpu": "c", "score": 980}]
        c = changes.compare(h, h[1])
        self.assertEqual(c.verdict, "igual")
        self.assertIn("variação normal", c.text())

    def test_old_entries_without_ts(self):
        h = [{"date": "2026-11-04 14:28", "mode": "M", "quality": "Q", "cpu": "c", "score": 100},
             {"date": "2026-11-08 16:47", "mode": "M", "quality": "Q", "cpu": "c", "score": 120}]
        self.assertAlmostEqual(changes.compare(h, h[1]).delta_pct, 20.0)


if __name__ == "__main__":
    unittest.main()
