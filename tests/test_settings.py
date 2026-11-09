"""Testes da gravação das definições (várias threads ao mesmo tempo).

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import json
import os
import tempfile
import threading
import unittest
from unittest import mock

from nexo.core import util


class SettingsConcurrency(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(util, "_settings", None)
        q.start()
        self.addCleanup(q.stop)

    def test_parallel_writes_keep_valid_file(self):
        errors = []

        def writer(n):
            try:
                for i in range(60):
                    util.set_setting(f"k{n}_{i}", i)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        data = json.loads((util.config_dir() / "settings.json").read_text(encoding="utf-8"))
        for n in range(6):
            self.assertEqual(data[f"k{n}_59"], 59)
        self.assertEqual([f for f in os.listdir(util.config_dir()) if f.endswith(".tmp")], [])


if __name__ == "__main__":
    unittest.main()
