"""Centro de alertas, pontuação da saúde do PC e tarefas agendadas."""
import os
import tempfile
import time
import unittest
from unittest import mock

from nexo.core import alertlog, healthscore, schedule, util


class TempConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None)):
            p.start()
            self.addCleanup(p.stop)


class AlertLog(TempConfig):
    def test_add_read_clear(self):
        a = alertlog.add("Temperatura da CPU alta: 95 °C (limite 90 °C)", "bad", now=1000)
        self.assertEqual(a.page, "Sensores")
        alertlog.add("Pouco espaço no disco /: só 3 GB livres", "warn", now=1001)
        self.assertEqual(alertlog.unread(), 2)
        first, second = alertlog.all_alerts()
        self.assertEqual(first.page, "Espaço em disco")       # o mais recente primeiro
        alertlog.mark_read(second.id)
        self.assertEqual(alertlog.unread(), 1)
        alertlog.mark_read()
        self.assertEqual(alertlog.unread(), 0)
        alertlog.clear()
        self.assertEqual(alertlog.all_alerts(), [])

    def test_repeats_are_merged(self):
        alertlog.add("Memória RAM quase cheia (95 %)", "warn", now=1000)
        alertlog.mark_read()
        alertlog.add("Memória RAM quase cheia (95 %)", "warn", now=1100)
        (a,) = alertlog.all_alerts()
        self.assertEqual((a.count, a.read, a.when), (2, False, 1100))
        alertlog.add("Memória RAM quase cheia (95 %)", "warn", now=1100 + alertlog.DEDUP_S + 1)
        self.assertEqual(len(alertlog.all_alerts()), 2)

    def test_limit_and_explicit_page(self):
        for i in range(alertlog.MAX + 15):
            alertlog.add(f"aviso {i}", "info", "", now=i * 1000)
        lst = alertlog.all_alerts()
        self.assertEqual(len(lst), alertlog.MAX)
        self.assertEqual(lst[0].msg, f"aviso {alertlog.MAX + 14}")
        self.assertEqual(lst[0].page, "")
        self.assertEqual(len({a.id for a in lst}), alertlog.MAX)

    def test_guess_page(self):
        g = alertlog.guess_page
        self.assertEqual(g("Sessão de Elden Ring: 60 min · CPU máx. 80 °C"), "Modo jogo")
        self.assertEqual(g("O disco Samsung está com problemas de saúde: setores realocados."), "Saúde dos discos")
        self.assertEqual(g("algo sem relação"), "")

    def test_corrupted_file(self):
        (util.config_dir() / alertlog.FILE).write_text("[{\"id\": 1, \"msg\": 3, \"x\": []}, 5, \"lixo\"]")
        self.assertEqual(alertlog.unread(), 1)
        alertlog.add("novo", "info", now=1)
        self.assertEqual(alertlog.all_alerts()[0].msg, "novo")

    def test_when_text(self):
        now = time.mktime((2026, 11, 12, 15, 0, 0, 0, 0, -1))
        self.assertEqual(alertlog.when_text(now - 10, now), "agora")
        self.assertEqual(alertlog.when_text(now - 600, now), "há 10 min")
        self.assertEqual(alertlog.when_text(now - 3 * 3600, now), "há 3 h")
        self.assertTrue(alertlog.when_text(now - 26 * 3600, now).startswith("ontem"))
        self.assertEqual(alertlog.when_text(now - 5 * 86400, now), time.strftime("%d/%m %H:%M",
                                                                                  time.localtime(now - 5 * 86400)))


class Health(TempConfig):
    C = healthscore.Check

    def test_score(self):
        self.assertEqual(healthscore.score([self.C("ok", "x")]), 100)
        self.assertEqual(healthscore.score([self.C("bad", "x"), self.C("warn", "y")]), 67)
        self.assertEqual(healthscore.score([self.C("warn", str(i)) for i in range(20)]), 100 - healthscore.MAX_WARN_TOTAL)
        self.assertEqual(healthscore.score([self.C("bad", str(i)) for i in range(9)]), 0)

    def test_grade_and_actions(self):
        self.assertEqual(healthscore.grade(95)[1], "ok")
        self.assertEqual(healthscore.grade(60)[1], "warn")
        self.assertEqual(healthscore.grade(10)[1], "bad")
        cs = [self.C("warn", "a", "P1"), self.C("ok", "b", "P2"), self.C("bad", "c", "P3"), self.C("warn", "d"),
              self.C("warn", "e", "P4"), self.C("warn", "f", "P5")]
        self.assertEqual([c.text for c in healthscore.top_actions(cs)], ["c", "a", "e"])

    def test_slow_checks(self):
        now = 2_000_000_000
        with mock.patch("nexo.core.snapshot.backend", return_value=None):
            texts = {c.text: c for c in healthscore.slow_checks(now)}
        self.assertIn("Ainda não fez nenhuma análise antivírus.", texts)
        util.set_setting("av_last_scan", {"when": now - 40 * 86400, "bad": 0})
        util.save_json("updates.json", {"time": now - 8 * 86400, "items": [{"name": "x"}] * 3})
        util.save_json("drivers.json", {"items": [{"component": "Mesa", "version": "24.0", "status": "warn"}]})
        with mock.patch("nexo.core.snapshot.backend", return_value="snapper"):
            util.set_setting("snapshot_before", False)
            cs = healthscore.slow_checks(now)
        kinds = {c.text: c.kind for c in cs}
        self.assertEqual(kinds["Última análise antivírus há 40 dias."], "warn")
        self.assertEqual(kinds["3 atualizações disponíveis."], "warn")
        self.assertEqual(kinds["Driver desatualizado: Mesa 24.0."], "warn")
        self.assertTrue(any("Pontos de restauro" in t for t in kinds))
        util.set_setting("av_last_scan", {"when": now, "bad": 2})
        with mock.patch("nexo.core.snapshot.backend", return_value=None):
            self.assertEqual(healthscore.slow_checks(now)[1].kind, "bad")


class Schedule(TempConfig):
    def test_defaults_do_not_run_on_first_start(self):
        now = 2_000_000_000
        self.assertEqual(schedule.due_tasks(now), [])          # antivírus (7 dias) começa a contar agora
        av = schedule.get("antivirus")
        self.assertEqual(schedule.last_run(av), now)
        self.assertEqual([t.id for t in schedule.due_tasks(now + 7 * 86400)], ["antivirus"])

    def test_interval_and_next(self):
        now = 2_000_000_000
        clean = schedule.get("clean")
        self.assertIsNone(schedule.next_run(clean, now))      # desligada por omissão
        schedule.set_interval(clean, 7, now)
        self.assertEqual(schedule.next_run(clean, now), now + 7 * 86400)
        self.assertEqual(util.get_setting("auto_clean_days"), 7)   # a mesma definição da limpeza automática
        schedule.set_interval(clean, 0, now)
        self.assertIsNone(schedule.next_run(clean, now))

    def test_run_clean_and_record(self):
        clean = schedule.get("clean")
        with mock.patch("nexo.core.autoclean.run", return_value=(2048, "Limpeza automática: 2 KB libertados.")):
            msg, kind = schedule.run_task(clean)
        self.assertEqual(kind, "ok")
        self.assertTrue(schedule.result(clean)["ok"])
        self.assertIn("2 KB", schedule.result(clean)["msg"])

    def test_antivirus_report_round_trip(self):
        from nexo.core import antivirus as av
        rep = av.Report("quick", findings=[av.Finding(av.BAD, "Ficheiro", "Minerador", "x", path="/tmp/m")],
                        files_scanned=10)
        with mock.patch.object(av, "scan", return_value=rep):
            msg, kind = schedule.run_task(schedule.get("antivirus"))
        self.assertEqual(kind, "bad")
        self.assertIn("1 ameaça", msg)
        back = schedule.load_report()
        self.assertEqual(back.findings[0].title, "Minerador")
        self.assertEqual(back.files_scanned, 10)

    @unittest.skipIf(util.IS_WIN, "no Linux a leitura S.M.A.R.T. só lembra")
    def test_smart_is_only_a_reminder_on_linux(self):
        t = schedule.get("smart")
        self.assertTrue(t.reminder)
        with mock.patch("nexo.core.smart.read_all", side_effect=AssertionError("pediu root")):
            msg, kind = schedule.run_task(t)
        self.assertEqual(kind, "info")


if __name__ == "__main__":
    unittest.main()
