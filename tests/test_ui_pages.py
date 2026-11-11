"""Teste de fumo da interface: abre a janela principal e cada página (sem ecrã, sem tarefas em segundo plano).

Apanha erros de importação, de construção das páginas e de on_show()/on_hide() antes de chegarem ao
executável. Nada é escrito no hardware nem nas definições reais:
- Task.start não lança threads (as páginas ficam no estado "a carregar");
- escritas nas ventoinhas, run_root e pkexec estão bloqueadas;
- XDG_CONFIG_HOME/APPDATA apontam para uma pasta temporária.

Executar:  .venv/bin/python -m unittest discover -s tests -t .
"""
import os
import tempfile
import unittest
from unittest import mock

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("DISPLAY", None)
os.environ.pop("WAYLAND_DISPLAY", None)

try:
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtWidgets import QApplication
    # criada já na importação: outros testes criam uma QCoreApplication (sem widgets) e só pode haver uma
    _APP = QCoreApplication.instance() or QApplication([])
    if not isinstance(_APP, QApplication):
        QApplication = None
except ImportError:  # pragma: no cover - CI sem PySide6
    QApplication = None


def _blocked(*_a, **_k):
    raise AssertionError("o teste da interface tentou mexer no sistema")


@unittest.skipIf(QApplication is None, "PySide6 não instalado ou já existe uma QCoreApplication")
class UiSmoke(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.patches = [mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": cls.tmp.name, "APPDATA": cls.tmp.name})]
        from nexo.core import fans, util
        from nexo.ui import netmonitor, widgets
        cls.patches += [
            mock.patch.object(util, "_settings", None),
            mock.patch.object(widgets.Task, "start", lambda self: self),
            mock.patch.object(widgets.SensorHub, "_loop", lambda self: None),
            mock.patch.object(netmonitor.NetMonitor, "start", lambda *a, **k: None),
            mock.patch.object(util, "run_root", _blocked),
            mock.patch.object(fans, "set_pct", _blocked),
            mock.patch.object(fans, "set_auto", _blocked),
            mock.patch.object(fans, "set_power_profile", _blocked),
        ]
        for p in cls.patches:
            p.start()
        cls.app = _APP
        from nexo.ui import theme
        theme.apply(cls.app)
        from nexo.ui.main_window import MainWindow
        cls.win = MainWindow(start_hidden=True)

    @classmethod
    def tearDownClass(cls):
        cls.win._quitting = True
        for t in cls.win.findChildren(type(cls.win._game_timer)):
            t.stop()
        for p in reversed(cls.patches):
            p.stop()
        cls.tmp.cleanup()

    def test_every_page_opens(self):
        w = self.win
        for i, name in enumerate(w.names):
            with self.subTest(page=name):
                w.go(i)
                self.app.processEvents()
                self.assertIsNotNone(w.pages[i], name)
                self.assertEqual(w.stack.currentIndex(), i)
                self.assertTrue(w.btn_of[i].isChecked(), name)

    def test_groups_show_tabs_and_remember_last(self):
        w = self.win
        groups = [g for g in w.groups if len(g) > 1]
        self.assertTrue(groups, "deve haver entradas do menu com várias páginas")
        g = groups[0]
        w.go(g[1])
        self.assertFalse(w.subtabs.isHidden())
        self.assertEqual(sorted(w.subtab_btns), sorted(g))
        self.assertTrue(w.subtab_btns[g[1]].isChecked())
        w.go(w.names.index("Visão geral"))
        self.assertTrue(w.subtabs.isHidden())
        self.assertEqual(w._group_target(g), g[1])   # ao voltar ao grupo abre a última página vista

    def test_badge_on_group_member(self):
        w = self.win
        idx = w.names.index("Atualizações")
        w.set_nav_badge("Atualizações", "3")
        self.assertEqual(w.btn_of[idx].badge, "3")
        w.go(idx)
        self.assertIn("3", w.subtab_btns[idx].text())
        w.set_nav_badge("Atualizações", None)
        self.assertIsNone(w.btn_of[idx].badge)
        self.assertNotIn("3", w.subtab_btns[idx].text())

    def test_name_navigation_still_works(self):
        for name in ("Espaço em disco", "Stress test", "Instalar aplicações", "Arranque", "Saúde dos discos"):
            with self.subTest(page=name):
                self.win.go_name(name)
                self.assertEqual(self.win.names[self.win.current], name)


if __name__ == "__main__":
    unittest.main()
