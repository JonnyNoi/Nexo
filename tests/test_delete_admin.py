"""Testes de util.delete_as_admin (apagar ficheiros que precisam de permissão).

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexo.core import util


class DeleteAsAdmin(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.object(util, "IS_WIN", False)
        p.start()
        self.addCleanup(p.stop)

    def test_one_root_call_for_all(self):
        a, b = self.dir / "a.txt", self.dir / "pasta com 'espaço'"
        a.write_text("x")
        b.mkdir()
        (b / "f").write_text("y")
        calls = []

        def fake_root(cmd, timeout=300):
            calls.append(cmd)
            return util.run(["sh", "-c", cmd])
        with mock.patch.object(util, "run_root", fake_root):
            done, err = util.delete_as_admin([str(a), str(b)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(err, "")
        self.assertEqual(sorted(done), sorted([str(a), str(b)]))
        self.assertFalse(a.exists() or b.exists())

    def test_refuses_roots_and_home(self):
        with mock.patch.object(util, "run_root", side_effect=AssertionError("não devia correr")):
            self.assertEqual(util.delete_as_admin(["/", os.path.expanduser("~")]), ([], ""))

    def test_cancelled_password(self):
        a = self.dir / "a"
        a.write_text("x")
        with mock.patch.object(util, "run_root", return_value=(126, "")):
            done, err = util.delete_as_admin([str(a)])
        self.assertEqual(done, [])
        self.assertTrue(err)
        self.assertTrue(a.exists())


if __name__ == "__main__":
    unittest.main()
