"""Cópia das definições, limpeza automática e atualizações do próprio Nexo."""
import json
import os
import tempfile
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from nexo.core import autoclean, backup, selfupdate, sessions, util


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(util, "_settings", None)
        q.start()
        self.addCleanup(q.stop)


class Backup(TempConfig):
    def test_round_trip(self):
        util.set_setting("alert_cpu", 77)
        util.set_setting("geometry", "AAAA")              # local: não viaja
        util.set_setting("game_processes", ["jogo.exe"])
        util.save_json("bench_history.json", [{"date": "2026-01-01 10:00", "score": 1000, "mode": "Multi-core"}])
        t = 1_700_000_000
        sessions.add(sessions.Session("Jogo", t, t + 600, 70, 80, 90, 60, 50))
        z = backup.export(Path(self.tmp.name) / "copia")
        self.assertEqual(z.suffix, ".zip")
        with zipfile.ZipFile(z) as f:
            self.assertNotIn("geometry", json.loads(f.read("settings.json")))

        # outro "PC": definições diferentes, sem histórico
        util.set_setting("alert_cpu", 95)
        util.set_setting("geometry", "BBBB")
        util.save_json("bench_history.json", [])
        sessions.clear()
        res = backup.import_backup(z)
        self.assertEqual(util.get_setting("alert_cpu"), 77)
        self.assertEqual(util.get_setting("geometry"), "BBBB")       # a desta máquina fica
        self.assertEqual(util.get_setting("game_processes"), ["jogo.exe"])
        self.assertEqual(res["sessions"], 1)
        self.assertEqual(len(util.load_json("bench_history.json", [])), 1)
        self.assertTrue((util.config_dir() / "settings.json.antes-de-importar").exists())
        # importar 2× não duplica o histórico
        res2 = backup.import_backup(z)
        self.assertEqual((res2["sessions"], res2["bench"]), (0, 0))

    def test_rejects_wrong_types_and_foreign_zip(self):
        bad = Path(self.tmp.name) / "x.zip"
        with zipfile.ZipFile(bad, "w") as f:
            f.writestr("manifest.json", json.dumps({"app": "Nexo"}))
            f.writestr("settings.json", json.dumps({"alert_cpu": "quente", "tray": "sim", "theme": "claro"}))
        backup.import_backup(bad)
        self.assertEqual(util.get_setting("alert_cpu"), util.DEFAULT_SETTINGS["alert_cpu"])
        self.assertEqual(util.get_setting("theme"), "claro")
        other = Path(self.tmp.name) / "y.zip"
        with zipfile.ZipFile(other, "w") as f:
            f.writestr("readme.txt", "olá")
        with self.assertRaises(backup.ImportErrorNexo):
            backup.read_backup(other)
        (Path(self.tmp.name) / "z.zip").write_text("não é zip")
        with self.assertRaises(backup.ImportErrorNexo):
            backup.read_backup(Path(self.tmp.name) / "z.zip")


class AutoClean(TempConfig):
    def test_only_safe_categories(self):
        for c in autoclean.categories():
            self.assertFalse(c.needs_admin or c.caution or c.command, c.id)
            self.assertNotIn(c.id, ("lx_trash", "win_recycle", "lx_browser", "lx_shader"))

    def test_due(self):
        now = time.time()
        self.assertFalse(autoclean.due(now))                       # desligada
        util.set_setting("auto_clean_days", 7)
        util.set_setting("auto_clean_last", now - 3 * 86400)
        self.assertFalse(autoclean.due(now))
        util.set_setting("auto_clean_last", now - 8 * 86400)
        self.assertTrue(autoclean.due(now))

    def test_run_cleans_and_records(self):
        d = Path(self.tmp.name) / "thumbs"
        d.mkdir()
        (d / "a.png").write_bytes(b"x" * 5000)
        from nexo.core import cleanup
        cat = cleanup.CleanCategory("lx_thumbs", "Cache de miniaturas", "", [str(d / "*")])
        with mock.patch.object(autoclean, "categories", return_value=[cat]):
            freed, msg = autoclean.run()
        self.assertGreater(freed, 0)
        self.assertIn("libertados", msg)
        self.assertFalse((d / "a.png").exists())
        self.assertGreater(util.get_setting("auto_clean_last"), 0)


class SelfUpdate(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(selfupdate.newer("2.10", "2.9"))
        self.assertTrue(selfupdate.newer("v3.0", "2.9.9"))
        self.assertFalse(selfupdate.newer("2.1", "2.1"))
        self.assertFalse(selfupdate.newer("2.0.9", "2.1"))

    def test_parse_release(self):
        data = {"tag_name": "v2.2", "body": "Novidades", "html_url": "https://x",
                "assets": [{"name": "Nexo", "browser_download_url": "https://x/Nexo", "size": 10,
                            "digest": "sha256:ABC"},
                           {"name": "Nexo.exe", "browser_download_url": "https://x/Nexo.exe", "size": 20,
                            "digest": "sha256:def"}]}
        with mock.patch.object(selfupdate, "IS_WIN", False):
            r = selfupdate.parse_release(data)
        self.assertEqual((r.version, r.asset_name, r.sha256), ("2.2", "Nexo", "abc"))
        with mock.patch.object(selfupdate, "IS_WIN", True):
            self.assertEqual(selfupdate.parse_release(data).asset_url, "https://x/Nexo.exe")

    def test_install_refuses_without_checksum_or_frozen(self):
        r = selfupdate.Release("9.9", "", "", "https://x/Nexo", "Nexo", 10, "")
        with self.assertRaises(RuntimeError):
            selfupdate.install(r)                      # não é o executável
        with mock.patch.object(selfupdate, "frozen", return_value=True), self.assertRaises(RuntimeError):
            selfupdate.install(r)                      # sem SHA-256

    def test_not_configured(self):
        with mock.patch.object(selfupdate, "UPDATE_REPO", ""):
            self.assertFalse(selfupdate.configured())
            self.assertIsNone(selfupdate.check())


if __name__ == "__main__":
    unittest.main()
