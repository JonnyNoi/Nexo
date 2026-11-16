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
            self.assertIsInstance(cmd, list)   # argumentos diretos, sem shell
            calls.append(cmd)
            return util.run(cmd)
        with mock.patch.object(util, "run_root", fake_root):
            done, err = util.delete_as_admin([str(a), str(b)])
        self.assertEqual(len(calls), 1)
        self.assertEqual(err, "")
        self.assertEqual(sorted(done), sorted([str(a), str(b)]))
        self.assertFalse(a.exists() or b.exists())

    def test_refuses_roots_and_home(self):
        with mock.patch.object(util, "run_root", side_effect=AssertionError("não devia correr")):
            done, err = util.delete_as_admin(["/", os.path.expanduser("~")])
        self.assertEqual(done, [])
        self.assertIn("recusados", err)

    def test_refuses_system_paths(self):
        with mock.patch.object(util, "run_root", side_effect=AssertionError("não devia correr")):
            done, err = util.delete_as_admin(["/usr", "/etc"])
        self.assertEqual(done, [])
        self.assertIn("2 itens de sistema", err)

    def test_system_paths_filtered_out_of_mixed_batch(self):
        a = self.dir / "a.txt"
        a.write_text("x")
        calls = []

        def fake_root(cmd, timeout=300):
            self.assertIsInstance(cmd, list)   # argumentos diretos, sem shell
            calls.append(cmd)
            return util.run(cmd)
        with mock.patch.object(util, "run_root", fake_root):
            done, err = util.delete_as_admin([str(a), "/etc"])
        self.assertEqual(done, [str(a)])
        self.assertNotIn("/etc", calls[0])
        self.assertEqual(calls[0][:3], ["rm", "-rf", "--"])
        self.assertIn("recusados", err)

    def test_windows_never_uses_shell(self):
        a = self.dir / "nome com %TEMP% & coisas.txt"
        a.write_text("x")
        cmds = []

        def fake_run(cmd, timeout=30, shell=False):
            self.assertFalse(shell)
            self.assertIsInstance(cmd, list)
            cmds.append(cmd)
            return 0, ""
        with mock.patch.object(util, "IS_WIN", True), mock.patch.object(util, "is_admin", return_value=True), \
                mock.patch.object(util, "run", fake_run):
            done, err = util.delete_as_admin([str(a)])
        self.assertEqual((done, err), ([str(a)], ""))
        self.assertEqual([c[0] for c in cmds], ["takeown", "icacls"])
        self.assertIn(str(a), cmds[0])

    def test_cancelled_password(self):
        a = self.dir / "a"
        a.write_text("x")
        with mock.patch.object(util, "run_root", return_value=(126, "")):
            done, err = util.delete_as_admin([str(a)])
        self.assertEqual(done, [])
        self.assertTrue(err)
        self.assertTrue(a.exists())


class RunRoot(unittest.TestCase):
    """run_root com lista: vai ao pkexec com o caminho absoluto do programa e sem passar pelo shell."""

    def _call(self, cmd):
        with mock.patch.object(util, "IS_WIN", False), mock.patch("os.geteuid", return_value=1000), \
                mock.patch.object(util, "which", lambda n: f"/usr/bin/{n}"), \
                mock.patch.object(util, "run", return_value=(0, "")) as run:
            util.run_root(cmd)
        return run.call_args[0][0]

    def test_list_skips_shell(self):
        weird = "/tmp/a b'; rm -rf ~ $(x)"
        self.assertEqual(self._call(["rm", "-rf", "--", weird]),
                         ["pkexec", "/usr/bin/rm", "-rf", "--", weird])

    def test_string_still_uses_shell(self):
        self.assertEqual(self._call("a && b"), ["pkexec", "/usr/bin/sh", "-c", "a && b"])

    def test_empty_list(self):
        self.assertEqual(util.run_root([])[0], 1)


if __name__ == "__main__":
    unittest.main()
