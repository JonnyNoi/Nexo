"""Regras de segurança do disco: nada do sistema pode aparecer como "seguro apagar".

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import unittest

from nexo.core import disksafety as d

CASES = {
    d.SYSTEM: [
        "/usr", "/usr/lib", "/etc", "/boot", "/home/u/.ssh", "/home/u/.gnupg",
        r"C:\Windows", r"C:\Windows\System32\x", r"C:\Program Files", r"C:\pagefile.sys",
        r"C:\Users\Joao\NTUSER.DAT",
        # uma regra "em qualquer lado" (cache) não pode vencer uma regra de sistema
        r"C:\Windows\System32\cache",
    ],
    d.SAFE: [
        "/tmp/x", "/var/cache/pacman/pkg", "/home/u/.cache/x", "/home/u/proj/node_modules",
        r"C:\Windows\Temp", r"C:\Users\Joao\AppData\Local\Temp",
    ],
    d.REVIEW: [
        "/home/u/Documentos", r"C:\Users\Joao\Documents", "/home/u/.local/share",
    ],
    d.APP: [
        "/home/u/.local/share/Steam/steamapps/common/Jogo",
        r"C:\Program Files (x86)\Steam\steamapps\common\Jogo",
    ],
}


class Classify(unittest.TestCase):
    def test_levels(self):
        for level, paths in CASES.items():
            for p in paths:
                if os.name == "nt" and p.startswith("/"):
                    continue   # as regras de ~ no Windows apontam para C:\\Users
                with self.subTest(path=p):
                    self.assertEqual(d.classify(p).level, level)

    def test_game_flag_only_on_game_root(self):
        root = "/home/u/.local/share/Steam/steamapps/common/Jogo"
        self.assertTrue(d.classify(root).is_game)
        self.assertFalse(d.classify(root + "/bin/jogo.exe").is_game)


if __name__ == "__main__":
    unittest.main()
