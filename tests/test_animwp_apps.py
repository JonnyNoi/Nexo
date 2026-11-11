import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from nexo.core import animwp, apps


@unittest.skipUnless(shutil.which("ffmpeg"), "precisa do ffmpeg para gerar ficheiros de teste")
class AnimatedDetection(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cfg = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": cls.tmp})
        cls.cfg.start()
        cls.mp4 = os.path.join(cls.tmp, "v.mp4")
        cls.gif = os.path.join(cls.tmp, "a.gif")
        cls.still = os.path.join(cls.tmp, "s.gif")
        run = lambda *a: subprocess.run(["ffmpeg", "-loglevel", "error", "-y", *a], check=True)  # noqa: E731
        run("-f", "lavfi", "-i", "testsrc=size=64x36:rate=5", "-t", "2", cls.mp4)
        run("-i", cls.mp4, cls.gif)
        run("-i", cls.mp4, "-frames:v", "1", cls.still)

    @classmethod
    def tearDownClass(cls):
        cls.cfg.stop()
        shutil.rmtree(cls.tmp, ignore_errors=True)

    def test_detection(self):
        self.assertTrue(animwp.is_animated(self.mp4))
        self.assertTrue(animwp.is_animated(self.gif))
        self.assertFalse(animwp.is_animated(self.still))
        self.assertFalse(animwp.is_animated(os.path.join(self.tmp, "nao-existe.gif")))

    def test_still_frames(self):
        for f in (self.mp4, self.gif):
            out = animwp.still_frame(f)
            self.assertTrue(out and os.path.getsize(out) > 0, f)


class AppDetection(unittest.TestCase):
    def test_linux_sources(self):
        cat = [apps.App("Firefox", "", "x", "", "org.mozilla.firefox"),
               apps.App("Steam", "", "x", "", "com.valvesoftware.Steam"),
               apps.App("Brave", "", "x", "", "com.brave.Browser"),
               apps.App("Obsidian", "", "x", "", "md.obsidian.Obsidian"),
               apps.App("Krita", "", "x", "", "org.kde.krita")]

        def fake_run(cmd, timeout=30):
            if cmd[0] == "flatpak":
                return 0, "org.mozilla.firefox\n"
            if cmd[0] == "pacman":
                return 0, "steam\nbrave-bin\nlinux\n"
            return 1, ""
        with mock.patch.object(apps, "run", fake_run), \
                mock.patch.object(apps, "which", lambda n: n in ("flatpak", "pacman")), \
                mock.patch("shutil.which", lambda n: "/x/obsidian" if n == "obsidian" else None), \
                mock.patch.object(apps, "_desktop_names", lambda: set()):
            found = apps._linux_detect(cat)
        self.assertEqual(found["Firefox"].source, "Flatpak")
        self.assertTrue(found["Firefox"].managed)
        self.assertEqual(found["Steam"].source, "pacman")
        self.assertFalse(found["Steam"].managed)
        self.assertEqual(found["Brave"].source, "pacman")          # variante -bin do AUR
        self.assertEqual(found["Obsidian"].source, "AppImage/manual")
        self.assertNotIn("Krita", found)

    def test_windows_names(self):
        cat = [apps.App("Visual Studio Code", "", "x", "Microsoft.VisualStudioCode"),
               apps.App("Git", "", "x", "Git.Git"),
               apps.App("Visual C++ Redistributable", "", "x", "Microsoft.VCRedist.2015+.x64"),
               apps.App("Steam", "", "x", "Valve.Steam")]
        progs = ["Microsoft Visual Studio Code (User)", "GitHub Desktop",
                 "Microsoft Visual C++ 2015-2022 Redistributable (x64) - 14.40", "Steam Mover"]
        with mock.patch.object(apps, "_win_programs", lambda: progs), \
                mock.patch.object(apps, "which", lambda n: None):
            found = apps._win_detect(cat)
        self.assertIn("Visual Studio Code", found)
        self.assertIn("Visual C++ Redistributable", found)
        self.assertNotIn("Git", found)      # "GitHub Desktop" não é o Git
        self.assertNotIn("Steam", found)    # "Steam Mover" não é o Steam


if __name__ == "__main__":
    unittest.main()
