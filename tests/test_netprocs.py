"""Rede por programa (saída do ss)."""
import unittest
from unittest import mock

from nexo.core import netprocs

SS1 = """0 0 192.168.1.67:48674 23.103.244.0:443 users:(("teams",pid=5385,fd=37))
\t cubic bytes_sent:1000 bytes_acked:1000 bytes_received:5000 segs_out:9
0 0 192.168.1.67:33884 [2606:4700::1]:443 users:(("Discord",pid=2027,fd=18))
\t cubic bytes_sent:100 bytes_received:200
0 0 127.0.0.1:5000 127.0.0.1:6000 users:(("local",pid=1,fd=3))
\t cubic bytes_sent:9999 bytes_received:9999
"""
SS2 = SS1.replace("bytes_received:5000", "bytes_received:25000").replace("bytes_sent:100 ", "bytes_sent:2100 ")


class NetProcs(unittest.TestCase):
    def test_parse(self):
        socks = netprocs.parse_ss(SS1)
        self.assertEqual(len(socks), 3)
        vals = sorted(socks.values())
        self.assertIn(("Discord", 2027, "2606:4700::1", 100, 200), vals)

    def test_rates_and_local_filtered(self):
        m = netprocs.NetProcMonitor()
        m.has_rates = True
        outs = iter([(0, SS1), (0, SS2)])
        with mock.patch.object(netprocs, "run", side_effect=lambda *a, **k: next(outs)), \
                mock.patch.object(netprocs.psutil, "net_connections", return_value=[]), \
                mock.patch.object(netprocs.time, "monotonic", side_effect=[100.0, 102.0]):
            first = m.sample()
            second = {p.name: p for p in m.sample()}
        self.assertTrue(all(p.down is None for p in first))       # 1.ª leitura: sem velocidade ainda
        self.assertNotIn("local", second)
        self.assertAlmostEqual(second["teams"].down, 10000)       # 20 000 B em 2 s
        self.assertAlmostEqual(second["Discord"].up, 1000)
        self.assertEqual(second["teams"].total_down, 20000)

    def test_local_ranges(self):
        for ip in ("192.168.0.1", "10.1.2.3", "172.20.0.1", "::1", "fe80::1"):
            self.assertTrue(netprocs._is_local(ip), ip)
        for ip in ("8.8.8.8", "172.32.0.1", "2606:4700::1"):
            self.assertFalse(netprocs._is_local(ip), ip)


if __name__ == "__main__":
    unittest.main()
