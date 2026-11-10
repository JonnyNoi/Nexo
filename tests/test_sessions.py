"""Histórico das sessões de jogo."""
import os
import tempfile
import unittest

from nexo.core import sessions


class Sessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = os.path.join(self.tmp.name, "h.db")

    def test_fps_stats(self):
        samples = [60.0] * 99 + [20.0]
        avg, low1, mn = sessions.fps_stats(samples)
        self.assertAlmostEqual(avg, 59.6)
        self.assertLess(low1, 60)
        self.assertEqual(mn, 20.0)
        self.assertEqual(sessions.fps_stats([60.0] * 5), (None, None, None))   # poucas amostras

    def test_add_recent_summary(self):
        t = 1_700_000_000
        self.assertFalse(sessions.add(sessions.Session("Curto", t, t + 30), self.db))   # < 1 min
        sessions.add(sessions.Session("A", t, t + 3600, 70, 80, 100, 60, 40), self.db)
        sessions.add(sessions.Session("A", t + 7200, t + 9000, 75, 82, 50, 30, 20), self.db)
        sessions.add(sessions.Session("B", t + 10000, t + 10600, None, None, None, None, None), self.db)
        rec = sessions.recent(path=self.db)
        self.assertEqual([r.game for r in rec], ["B", "A", "A"])
        summ = {g.game: g for g in sessions.summary(path=self.db)}
        self.assertEqual(summ["A"].sessions, 2)
        self.assertAlmostEqual(summ["A"].minutes, 90)
        self.assertAlmostEqual(summ["A"].fps_avg, (100 * 3600 + 50 * 1800) / 5400)   # média pesada pelo tempo
        self.assertEqual(summ["A"].gpu_max, 82)
        self.assertIsNone(summ["B"].fps_avg)
        sessions.delete(rec[0].id, self.db)
        self.assertEqual(len(sessions.recent(path=self.db)), 2)
        sessions.clear(self.db)
        self.assertEqual(sessions.recent(path=self.db), [])


if __name__ == "__main__":
    unittest.main()
