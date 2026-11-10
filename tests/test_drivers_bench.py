"""Drivers da placa gráfica e teste de velocidade do disco."""
import os
import tempfile
import time
import unittest
from unittest import mock

from nexo.core import diskbench, drivers, updates


class Drivers(unittest.TestCase):
    def test_pending_update_wins(self):
        d = drivers.DriverInfo("RX", "AMD", "Mesa", "26.1.0", packages=["mesa"])
        pend = [updates.Update("mesa", "26.1.0", "26.2.0", "Sistema")]
        drivers.evaluate([d], pend, online=False)
        self.assertEqual(d.status, "warn")
        self.assertIn("26.2.0", d.message)

    def test_mesa_versions(self):
        with mock.patch.object(drivers, "latest_mesa", return_value="26.3.0"):
            a = drivers.evaluate([drivers.DriverInfo("x", "AMD", "Mesa", "26.2.6")])[0]
            b = drivers.evaluate([drivers.DriverInfo("x", "AMD", "Mesa", "25.3.1")])[0]
            c = drivers.evaluate([drivers.DriverInfo("x", "AMD", "Mesa", "26.3.0")])[0]
        self.assertEqual(a.status, "ok")       # uma versão atrás: normal
        self.assertEqual(b.status, "warn")     # várias versões atrás
        self.assertEqual(c.message, "Versão atual.")

    def test_mesa_offline(self):
        with mock.patch.object(drivers, "latest_mesa", side_effect=OSError("sem rede")):
            d = drivers.evaluate([drivers.DriverInfo("x", "AMD", "Mesa", "26.2.6")])[0]
        self.assertEqual(d.status, "ok")

    def test_windows_driver_age(self):
        now = time.mktime(time.strptime("2026-11-10", "%Y-%m-%d"))
        old = drivers.DriverInfo("GTX", "NVIDIA", "Driver", "31.0.15", "2025-12-01", link="x")
        new = drivers.DriverInfo("GTX", "NVIDIA", "Driver", "32.0.1", "2026-10-01")
        drivers.evaluate([old, new], today=now)
        self.assertEqual(old.status, "warn")
        self.assertEqual(new.status, "ok")

    def test_unknown_version(self):
        self.assertEqual(drivers.evaluate([drivers.DriverInfo("x", "", "Mesa", "")])[0].status, "unknown")


class DiskBench(unittest.TestCase):
    def test_small_run_cleans_up(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(diskbench, "RND_SECONDS", 0.2), \
                mock.patch.object(diskbench.psutil, "disk_usage", return_value=mock.Mock(free=10 * 1024**3)):
            r = diskbench.run(d, 64 * diskbench.MiB)
            self.assertFalse(os.path.exists(os.path.join(d, diskbench.FILE_NAME)))
        self.assertGreater(r.seq_read, 0)
        self.assertGreater(r.rnd_write_iops, 0)

    def test_cancel_cleans_up(self):
        import threading
        stop = threading.Event()
        stop.set()
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(diskbench.psutil, "disk_usage", return_value=mock.Mock(free=10 * 1024**3)):
            with self.assertRaises(diskbench.Cancelled):
                diskbench.run(d, 64 * diskbench.MiB, stop=stop)
            self.assertFalse(os.path.exists(os.path.join(d, diskbench.FILE_NAME)))

    def test_not_enough_space(self):
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.object(diskbench.psutil, "disk_usage", return_value=mock.Mock(free=10)):
            with self.assertRaises(RuntimeError):
                diskbench.run(d, 64 * diskbench.MiB)

    def test_verdict(self):
        r = diskbench.BenchResult("x", 1, seq_read=3500)
        self.assertIn("NVMe", diskbench.verdict(r))


if __name__ == "__main__":
    unittest.main()
