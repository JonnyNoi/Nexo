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

    def test_alert_center(self):
        from nexo.core import alertlog
        w = self.win
        alertlog.clear()
        w._alert("Temperatura da CPU alta: 95 °C (limite 90 °C)", "bad")
        w._alert("Pouco espaço no disco /: só 2 GB livres", "warn", "Espaço em disco")
        self.assertEqual(w.btn_bell.count, 2)
        w.open_alerts()
        self.app.processEvents()
        self.assertFalse(w.alert_box.isHidden())
        rows = [r for r in w.alert_box.inner.findChildren(type(w.alert_box.panel)) if r.objectName() == "AlertRow"]
        self.assertEqual(len(rows), 2)
        w.alert_box._open_alert(alertlog.all_alerts()[0])        # "Abrir" leva à página
        self.assertEqual(w.names[w.current], "Espaço em disco")
        self.assertTrue(w.alert_box.isHidden())
        self.assertEqual(w.btn_bell.count, 0)                     # fechar marca tudo como lido

    def test_health_score_card(self):
        w = self.win
        w.go_name("Visão geral")
        page = w.pages[w.current]
        page._update_score([("bad", "Disco quase cheio", "Espaço em disco"), ("warn", "RAM", "Processos"),
                            ("ok", "Tudo bem", None)])
        self.assertIn("Saúde do PC", page.score_title.text())
        self.assertEqual(page.r_score.center, "67")
        self.assertEqual(page.actions_box.count(), 2)

    def test_tasks_page_and_wizard(self):
        from nexo.core import schedule
        from nexo.ui.wizard import ShortcutsDialog, Wizard
        w = self.win
        w.go_name("Tarefas agendadas")
        page = w.pages[w.current]
        cb, info, _btn = page.rows["clean"]
        cb.setCurrentIndex(cb.findData(7))
        self.assertEqual(schedule.interval(schedule.get("clean")), 7)
        self.assertIn("Próxima", info.text())
        wiz = Wizard(w)
        for _ in range(wiz.stack.count() - 1):
            wiz._step(1)
        self.assertEqual(wiz.b_next.text(), "Começar")
        wiz._step(1)
        from nexo.core.util import get_setting
        self.assertTrue(get_setting("wizard_done"))
        ShortcutsDialog(w).close()

    def test_game_profile_card(self):
        from nexo.core import gameprofile
        w = self.win
        w.go_name("Modo jogo")
        card = w.pages[w.current].gp_card
        card.game_cb.setEditText("Jogo de Teste")
        card.power_cb.setCurrentIndex(card.power_cb.findData("performance"))
        if gameprofile.power_available():
            self.assertEqual(gameprofile.power_for("Jogo de Teste"), "performance")
        card.ov_cb.setCurrentIndex(card.ov_cb.findData("off"))
        self.assertFalse(gameprofile.overlay_for("Jogo de Teste", True))
        card._reset()
        self.assertFalse(gameprofile.has_profile("Jogo de Teste"))


if __name__ == "__main__":
    unittest.main()
