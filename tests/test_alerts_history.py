"""Testes dos alertas (nexo/core/watch.py), do histórico (nexo/core/history.py) e dos pontos de
restauro (nexo/core/snapshot.py). Nada aqui pede palavra-passe nem cria snapshots reais.

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest
from unittest import mock

_TMP = tempfile.mkdtemp(prefix="nexo-test-")
os.environ["XDG_CONFIG_HOME"] = _TMP      # nunca tocar nas definições reais
os.environ["APPDATA"] = _TMP

from nexo.core import history, snapshot, util, watch  # noqa: E402

GB = 1024 ** 3


class DiskAlertsTest(unittest.TestCase):
    def test_warns_once_and_rearms(self):
        a = watch.DiskAlerts()
        low = [watch.Usage("/", 500 * GB, 20 * GB)]          # 4 % livre
        msgs = a.check(low, 10)
        self.assertEqual(len(msgs), 1)
        self.assertIn("Pouco espaço", msgs[0][0])
        self.assertEqual(msgs[0][1], "bad")                    # < metade do limite
        self.assertEqual(a.check(low, 10), [])                 # não repete
        self.assertEqual(a.check([watch.Usage("/", 500 * GB, 55 * GB)], 10), [])   # 11 %: ainda não rearma
        self.assertEqual(len(a.check(low, 10)), 0)
        a.check([watch.Usage("/", 500 * GB, 70 * GB)], 10)     # 14 %: rearma
        self.assertEqual(len(a.check(low, 10)), 1)

    def test_warn_level_and_small_partitions_ignored(self):
        a = watch.DiskAlerts()
        self.assertEqual(a.check([watch.Usage("/boot", 1 * GB, 10 * 1024 ** 2)], 10), [])
        msgs = a.check([watch.Usage("/home", 1000 * GB, 80 * GB)], 10)
        self.assertEqual(msgs[0][1], "warn")


class SmartChangesTest(unittest.TestCase):
    def disk(self, verdict, reasons=(), error=""):
        return {"dev": "/dev/nvme0", "serial": "S1", "model": "SSD X", "verdict": verdict,
                "reasons": list(reasons), "error": error}

    def test_only_worsening_alerts(self):
        msgs, seen = watch.smart_changes({"disks": [self.disk("ok")]}, {})
        self.assertEqual(msgs, [])
        msgs, seen = watch.smart_changes({"disks": [self.disk("warn", [("warn", "setores realocados")])]}, seen)
        self.assertEqual(len(msgs), 1)
        self.assertIn("setores realocados", msgs[0][0])
        msgs, seen = watch.smart_changes({"disks": [self.disk("warn")]}, seen)
        self.assertEqual(msgs, [])                                         # igual: não repete
        msgs, seen = watch.smart_changes({"disks": [self.disk("bad")]}, seen)
        self.assertEqual(msgs[0][1], "bad")
        msgs, seen = watch.smart_changes({"disks": [self.disk("ok")]}, seen)
        self.assertEqual(msgs, [])
        self.assertEqual(seen["S1"], "ok")

    def test_unreadable_disk_is_not_failing(self):
        msgs, _ = watch.smart_changes({"disks": [self.disk("warn", error="sem permissão")]}, {})
        self.assertEqual(msgs, [])

    def test_no_cache(self):
        self.assertEqual(watch.smart_changes(None, {})[0], [])


class HistoryTest(unittest.TestCase):
    def setUp(self):
        self.path = os.path.join(_TMP, f"h-{self.id()}.db")
        self.h = history.History(self.path)

    def tearDown(self):
        self.h.close()

    def test_minute_aggregation_and_query(self):
        base = 1_700_000_000 // 60 * 60
        for s in range(60):                                 # minuto 0: 40→99 °C
            self.h.add({"cpu_temp": 40 + s, "gpu_temp": None}, base + s)
        for s in range(60):                                 # minuto 1: 50 °C constante
            self.h.add({"cpu_temp": 50}, base + 60 + s)
        self.h.add({"cpu_temp": 60}, base + 120)            # muda de minuto → grava o minuto 1
        d = self.h.query(["cpu_temp", "gpu_temp"], base, base + 3600, bucket=60)
        self.assertEqual(len(d["cpu_temp"]), 2)
        _t, avg, mx = d["cpu_temp"][0]
        self.assertAlmostEqual(avg, 69.5, places=1)
        self.assertEqual(mx, 99)
        self.assertEqual(d["gpu_temp"], [])
        # bloco de 10 minutos junta os dois
        d = self.h.query(["cpu_temp"], base, base + 3600, bucket=600)
        self.assertEqual(len(d["cpu_temp"]), 1)
        self.assertEqual(d["cpu_temp"][0][2], 99)
        self.assertEqual(self.h.first_ts(), base)

    def test_prune_and_clear(self):
        old = 1_000_000_000 // 60 * 60
        self.h.add({"ram": 10}, old)
        self.h.flush()
        self.h._last_prune = 0
        now = old + (history.KEEP_DAYS + 1) * 86400
        self.h.add({"ram": 20}, now)
        self.h.flush()
        self.assertEqual(self.h.first_ts(), now // 60 * 60)
        self.h.clear()
        self.assertIsNone(self.h.first_ts())


class SnapshotTest(unittest.TestCase):
    def setUp(self):
        util.set_setting("snapshot_before", True)
        util.set_setting("snapshot_last", 0)

    @mock.patch.object(snapshot, "IS_LINUX", True)
    @mock.patch.object(snapshot, "backend", return_value="snapper")
    def test_prefix_once_per_cooldown(self, _b):
        cmd = snapshot.with_snapshot("sysctl -w a=1", "ajuste: x")
        self.assertTrue(cmd.startswith("{ snapper -c root create"))
        self.assertIn("|| true; }; sysctl -w a=1", cmd)
        self.assertIn("'Nexo: antes de ajuste: x'", cmd)
        self.assertEqual(snapshot.with_snapshot("sysctl -w b=2", "y"), "sysctl -w b=2")   # dentro dos 30 min

    @mock.patch.object(snapshot, "IS_LINUX", True)
    @mock.patch.object(snapshot, "backend", return_value="snapper")
    def test_disabled_setting(self, _b):
        util.set_setting("snapshot_before", False)
        self.assertEqual(snapshot.with_snapshot("x", "y"), "x")

    @mock.patch.object(snapshot, "IS_LINUX", True)
    @mock.patch.object(snapshot, "backend", return_value=None)
    def test_no_backend(self, _b):
        self.assertEqual(snapshot.with_snapshot("x", "y"), "x")

    @mock.patch.object(snapshot, "IS_LINUX", True)
    @mock.patch.object(snapshot, "backend", return_value="timeshift")
    def test_description_is_quoted(self, _b):
        import shlex
        evil = "a'; rm -rf /; echo '"
        cmd = snapshot.with_snapshot("x", evil)
        snap = cmd[2:cmd.index(" >/dev/null")]
        tokens = shlex.split(snap)
        self.assertEqual(tokens[:4], ["timeshift", "--create", "--scripted", "--comments"])
        self.assertEqual(tokens[4:], ["Nexo: antes de " + evil])     # um só argumento, nada executado

    @mock.patch.object(snapshot, "IS_WIN", False)
    def test_before_is_noop_on_linux(self):
        self.assertIsNone(snapshot.before("x"))


if __name__ == "__main__":
    unittest.main()
