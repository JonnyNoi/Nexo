"""Funcionalidades da 2.4: energia, sessões com frametimes, histórico S.M.A.R.T., BIOS, «O que melhorar»,
snapshots, código QR, painel no telemóvel, MangoHud e traduções."""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from unittest import mock

from nexo.core import util


class _TmpConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for p in (mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name}),
                  mock.patch.object(util, "_settings", None)):
            p.start()
            self.addCleanup(p.stop)
        self.db = os.path.join(self.tmp.name, "h.db")


class Energy(_TmpConfig):
    def test_meter_days_totals(self):
        from nexo.core import energy
        m = energy.Meter(self.db)
        t0 = time.mktime(time.strptime("2026-11-10 12:00", "%Y-%m-%d %H:%M"))
        for i in range(3600):                       # 1 h a 100 W de CPU + 200 W de GPU, meia hora a jogar
            m.add(100, 200, gaming=i >= 1800, now=t0 + i)
        m.add(100, 200, now=t0 + 3600 + 600)          # salto de 10 min (suspensão): não conta
        m.add(5000, None, now=t0 + 3601 + 600)        # leitura absurda: conta como 0 W
        m.flush()
        rows = energy.days(3, path=self.db, now=t0 + 86400)
        self.assertEqual([d.day for d in rows], ["2026-11-09", "2026-11-10", "2026-11-11"])
        d = rows[1]
        self.assertAlmostEqual(d.cpu_wh, 100, places=1)       # a 1.ª leitura conta como 1 s
        self.assertAlmostEqual(d.gpu_wh, 200, places=1)
        self.assertEqual(d.seconds, 3601)
        self.assertAlmostEqual(d.game_wh, 150, delta=1)
        t = energy.totals(rows, rest=50)
        self.assertAlmostEqual(t.wh, 300 + 50, delta=2)
        self.assertAlmostEqual(t.avg_w, 350, delta=2)
        util.set_setting("energy_price", 0.25)
        self.assertAlmostEqual(energy.cost(1000), 0.25)
        self.assertAlmostEqual(energy.month_estimate(rows, rest=50), 0.35 * 0.25 * 30, delta=0.05)

    def test_pending_counts_today(self):
        from nexo.core import energy
        m = energy.Meter(self.db)
        now = time.time()
        for i in range(10):
            m.add(360, 0, now=now - 10 + i)
        rows = energy.days(1, path=self.db, pending=m.pending(), now=now)
        self.assertAlmostEqual(rows[-1].cpu_wh, 1.0, places=3)

    def test_money_format(self):
        from nexo.core import energy
        self.assertEqual(energy.fmt_money(1.5), "1,50 €")
        self.assertEqual(energy.fmt_money(0.05), "0,050 €")
        self.assertEqual(energy.fmt_money(0.004), "0,0040 €")
        util.set_setting("energy_currency", "$")
        self.assertEqual(energy.fmt_money(12), "$12,00")
        self.assertEqual(energy.fmt_energy(1500), "1,5 kWh")


class SessionsV24(_TmpConfig):
    def test_stutters_and_timeline(self):
        from nexo.core import sessions
        tl = [[100.0, 12.0]] * 200
        tl[50] = [90.0, 80.0]
        tl[120] = [95.0, 70.0]
        self.assertEqual(sessions.count_stutters(tl), 2)
        self.assertIsNone(sessions.count_stutters([[100.0, None]] * 50))   # sem fotograma mais lento
        long = [[100.0, 10.0]] * 5000
        long[2500] = [20.0, 300.0]
        c = sessions.compact_timeline(long, 100)
        self.assertEqual(len(c), 100)
        self.assertIn([20.0, 300.0], c)               # o engasgo não desaparece ao reduzir

    def test_migrates_old_db_and_reads_back(self):
        from nexo.core import sessions
        db = sqlite3.connect(self.db)
        db.execute("CREATE TABLE sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, game TEXT NOT NULL, start REAL "
                   "NOT NULL, end REAL NOT NULL, cpu_max REAL, gpu_max REAL, fps_avg REAL, fps_low1 REAL, "
                   "fps_min REAL)")
        db.execute("INSERT INTO sessions (game, start, end) VALUES ('Antigo', 1, 4000)")
        db.commit()
        db.close()
        t = time.time() - 4000
        tl = [[60.0, 20.0]] * 30
        sessions.add(sessions.Session("Novo", t, t + 3600, cpu_load=50, gpu_load=99, wh=120, stutters=0,
                                      timeline=tl), self.db)
        rec = sessions.recent(path=self.db)
        self.assertEqual([r.game for r in rec], ["Novo", "Antigo"])
        self.assertEqual(rec[0].gpu_load, 99)
        self.assertIsNone(rec[1].wh)
        full = sessions.get(rec[0].id, self.db)
        self.assertEqual(full.timeline, tl)
        self.assertEqual([s.game for s in sessions.since(t - 1, self.db)], ["Novo"])


class SmartHistory(_TmpConfig):
    def _day(self, d):
        return time.mktime(time.strptime(d, "%Y-%m-%d")) + 3600

    def test_rising_sectors_and_life(self):
        from nexo.core import smarthist
        data: dict = {}
        disk = {"serial": "S1", "model": "SSD", "life": 90, "realloc": 0, "pending": 0, "written": 0, "attrs": [1]}
        for i, (day, life, realloc, written) in enumerate((("2026-01-01", 90, 0, 0), ("2026-04-01", 88, 0, 9e12),
                                                           ("2026-10-01", 84, 4, 27e12), ("2026-10-20", 84, 20, 28e12))):
            smarthist.record([{**disk, "life": life, "realloc": realloc, "written": written}], self._day(day),
                             data, save=False)
        tr = smarthist.for_disk(disk, data)
        self.assertGreater(tr.days, 280)
        kinds = dict((k, t) for k, t in tr.notes if "setores realocados" in t)
        self.assertIn("bad", kinds)                  # 0 → 20 e a subir no último mês
        self.assertIsNotNone(tr.life_eta_days)
        self.assertAlmostEqual(tr.life_per_year, 7.8, delta=1.5)
        self.assertGreater(tr.written_per_day, 0)

    def test_same_day_replaced_and_errors_skipped(self):
        from nexo.core import smarthist
        data: dict = {}
        d = {"serial": "X", "life": 50, "attrs": [1]}
        smarthist.record([d], self._day("2026-05-05"), data, save=False)
        smarthist.record([{**d, "life": 49}], self._day("2026-05-05"), data, save=False)
        smarthist.record([{"serial": "Y", "error": "sem permissão", "attrs": []}], self._day("2026-05-05"), data,
                         save=False)
        self.assertEqual(len(data["X"]), 1)
        self.assertEqual(data["X"][0]["life"], 49)
        self.assertNotIn("Y", data)
        self.assertEqual(smarthist.trend([]).notes, [])


class Bios(unittest.TestCase):
    def test_dates_and_support_page(self):
        from nexo.core import bios
        self.assertEqual(bios._norm_date("09/29/2024"), "2024-09-29")
        self.assertEqual(bios._norm_date("20230517000000.000000+000"), "2023-05-17")
        self.assertEqual(bios._clean("To be filled by O.E.M."), "")
        msi = bios.BiosInfo("AMI", "H.60", "2024-09-29", "Micro-Star International Co., Ltd.",
                            "B760M GAMING PLUS WIFI (MS-7D99)", "Micro-Star International Co., Ltd.", "MS-7D99")
        self.assertEqual(bios.support_url(msi), "https://www.msi.com/search/B760M+GAMING+PLUS+WIFI")
        dell = bios.BiosInfo(system_vendor="Dell Inc.", system="XPS 13 9310", board_vendor="Dell Inc.", board="0F1")
        self.assertTrue(bios.is_oem(dell))
        self.assertIn("dell.com", bios.support_url(dell))
        other = bios.BiosInfo(board_vendor="Foo", board="X1")
        self.assertIn("duckduckgo", bios.support_url(other))

    def test_verdict_and_fwupd(self):
        from nexo.core import bios
        old = bios.BiosInfo(date=time.strftime("%Y-%m-%d", time.localtime(time.time() - 5 * 365 * 86400)))
        self.assertEqual(bios.verdict(old)[0], "warn")
        new = bios.BiosInfo(date=time.strftime("%Y-%m-%d"))
        self.assertEqual(bios.verdict(new)[0], "ok")
        self.assertEqual(bios.verdict(new, "System Firmware 1.2")[0], "warn")
        out = json.dumps({"Devices": [{"Name": "SSD", "Plugin": "nvme", "Releases": [{"Version": "2"}]},
                                      {"Name": "System Firmware", "Plugin": "uefi_capsule",
                                       "Releases": [{"Version": "1.18.0"}]}]})
        self.assertEqual(bios.parse_fwupd_updates(out), "System Firmware 1.18.0")
        self.assertEqual(bios.parse_fwupd_updates("lixo"), "")


class Upgrade(unittest.TestCase):
    def _facts(self, **kw):
        from nexo.core import upgrade as up
        base = dict(cpu="CPU", cores=6, threads=12, ram_gb=32, gpu="GPU", vram_gb=8, sys_disk="NVMe",
                    cpu_multi=1300, cpu_single=200, gpu_score=3000, monitor_hz=144, monitor_max_hz=144)
        base.update(kw)
        return up.Facts(**base)

    def test_gpu_bound(self):
        from nexo.core import upgrade as up
        f = self._facts(games=[up.GameLoad("A", 120, 40, 98, 50, 30, 99, 60)])
        b, adv = up.advise(f)
        self.assertEqual(b.who, "gpu")
        first = [a for a in adv if a.kind == "upgrade"][0]
        self.assertEqual(first.part, "Placa gráfica")
        self.assertIn("8 GB de VRAM", first.why)

    def test_cpu_bound_and_free_fixes_first(self):
        from nexo.core import upgrade as up
        f = self._facts(threads=4, cpu_multi=500, ram_xmp_off=True, ram_current=4800, ram_rated=6000,
                        monitor_hz=60, monitor_max_hz=165, sys_disk="HDD",
                        games=[up.GameLoad("B", 90, 95, 55, 70, 40, 50, 70)])
        b, adv = up.advise(f)
        self.assertEqual(b.who, "cpu")
        self.assertEqual([a.kind for a in adv[:2]], ["free", "free"])
        parts = [a.part for a in adv if a.kind == "upgrade"]
        self.assertEqual(parts[0], "Disco")
        self.assertIn("CPU", parts)

    def test_capped_fps_is_not_cpu_bound(self):
        from nexo.core import upgrade as up
        f = self._facts(games=[up.GameLoad("C", 100, 30, 50, 143, 120, 40, 40)])
        b, adv = up.advise(f)
        self.assertEqual(b.who, "none")
        self.assertEqual(adv[-1].kind, "ok")

    def test_not_enough_data(self):
        from nexo.core import upgrade as up
        b, adv = up.advise(self._facts())
        self.assertEqual(b.who, "unknown")
        self.assertEqual([a.kind for a in adv], ["ok"])


class Snapshots(unittest.TestCase):
    def test_parsers(self):
        from nexo.core import snapshot
        out = json.dumps({"root": [{"number": 0, "description": "current"},
                                   {"number": 5, "type": "pre", "date": "2026-11-01 10:00:00", "description": "pacman",
                                    "used-space": 1024},
                                   {"number": 6, "type": "single", "date": "2026-11-02 11:00:00",
                                    "description": "Nexo: antes de X"}]})
        snaps = snapshot.parse_snapper_json(out)
        self.assertEqual([s.id for s in snaps], ["5", "6"])
        self.assertEqual(snaps[0].size, 1024)
        self.assertTrue(snaps[1].by_nexo)
        ts = ("Num     Name                 Tags  Description\n"
              "------------------------------------------------------------------------------\n"
              "0    >  2026-11-01_10-00-01  O     antes da atualização\n"
              "1    >  2026-11-02_12-30-00  D\n")
        t = snapshot.parse_timeshift_list(ts)
        self.assertEqual([s.id for s in t], ["2026-11-01_10-00-01", "2026-11-02_12-30-00"])
        self.assertEqual(t[0].date, "2026-11-01 10:00")
        self.assertEqual(t[0].desc, "antes da atualização")

    def test_delete_rejects_odd_ids(self):
        from nexo.core import snapshot
        with mock.patch.object(snapshot, "backend", return_value="snapper"), \
                mock.patch.object(snapshot, "run_root", return_value=(0, "")) as rr:
            ok, _ = snapshot.delete(["3", "4; rm -rf /"])
        self.assertTrue(ok)
        self.assertEqual(rr.call_args[0][0], ["snapper", "-c", "root", "delete", "3"])


class QRCode(unittest.TestCase):
    def test_sizes(self):
        from nexo.core import qr
        self.assertEqual(len(qr.encode("x")), 21)                      # versão 1
        self.assertEqual(len(qr.encode("http://192.168.1.20:8765/?k=abcdefgh")), 29)   # versão 3
        with self.assertRaises(ValueError):
            qr.encode("x" * 500)

    @unittest.skipUnless(shutil.which("zbarimg"), "zbarimg não instalado")
    def test_decodes(self):
        from nexo.core import qr
        with tempfile.TemporaryDirectory() as d:
            for text in ("http://10.0.0.2:8765/?k=a2b3c4d5", "z" * 150):
                p = os.path.join(d, "q.pbm")
                with open(p, "wb") as f:
                    f.write(qr.to_pbm(qr.encode(text)))
                out = subprocess.run(["zbarimg", "-q", "--raw", p], capture_output=True, text=True).stdout.strip()
                self.assertEqual(out, text)


class WebPanel(_TmpConfig):
    def test_token_required(self):
        import socket

        from nexo.core import webpanel
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        p = webpanel.Panel()
        ok, url = p.start(port)
        self.assertTrue(ok, url)
        self.addCleanup(p.stop)
        p.update({"cpu_t": 55.0})
        base = f"http://127.0.0.1:{port}"
        data = json.loads(urllib.request.urlopen(f"{base}/api?k={p.token}", timeout=5).read())
        self.assertEqual(data["cpu_t"], 55.0)
        self.assertIn(b"<canvas", urllib.request.urlopen(f"{base}/?k={p.token}", timeout=5).read())
        for path in ("/api", "/api?k=errado", "/?k="):
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(base + path, timeout=5)
            self.assertEqual(cm.exception.code, 403)
            cm.exception.close()
        self.assertEqual(len(webpanel.token()), webpanel.TOKEN_LEN)


class MangoHudWorstFrame(_TmpConfig):
    @unittest.skipIf(util.IS_WIN, "MangoHud é do Linux")
    def test_reads_last_second(self):
        from nexo.core import fps
        d = fps.mangohud_dir()
        with open(d / "jogo_2026.csv", "w") as f:
            f.write("os,cpu,gpu\nfps,frametime,cpu_load,gpu_load,cpu_temp,gpu_temp,a,b,c,d\n")
            for ft in (8, 9, 40, 8.5, 8.2):
                f.write(f"{1000 / ft:.1f},{ft},1,2,3,4,5,6,7,8\n")
        r = fps._read_mangohud()
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r[1], 8.2)
        self.assertEqual(r[2], 40.0)                  # pior das últimas 4 linhas


class PeripheralTone(unittest.TestCase):
    def test_tone_channels(self):
        import struct

        from nexo.ui.periph_tests import tone_pcm
        pcm = tone_pcm(440, 0.1, 8000, left=True, right=False)
        self.assertEqual(len(pcm), 800 * 4)
        frames = [struct.unpack_from("<hh", pcm, i * 4) for i in range(800)]
        self.assertTrue(any(left for left, _r in frames))
        self.assertFalse(any(r for _l, r in frames))


class Translations(unittest.TestCase):
    def test_v24_files_translated(self):
        import re
        from pathlib import Path

        from nexo.core.i18n import _scan, missing
        from nexo.core.i18n_en_v24 import EN_V24, TEMPLATES_V24
        for k, v in EN_V24.items():
            self.assertTrue(v.strip(), k)
            self.assertNotIn("{}", k)
        for k, v in TEMPLATES_V24.items():
            self.assertEqual(k.count("{}"), v.count("{}"), k)
        root = Path(__file__).resolve().parent.parent / "nexo"
        files = [root / f for f in ("core/energy.py", "core/bios.py", "core/smarthist.py", "core/upgrade.py",
                                    "ui/charts.py", "ui/periph_tests.py", "ui/session_dialog.py",
                                    "ui/webpanel_card.py", "ui/bios_card.py", "ui/pages/energy.py",
                                    "ui/pages/upgrade.py", "ui/pages/snapshots.py")]
        pt = re.compile(r"[ãõçáéíóúâêô]|\b(de|do|da|em|não|para|com|que|os|as)\b", re.I)
        todo = [s for s in missing(_scan(files)) if pt.search(s) and "{{" not in s and "\\" not in s
                and not s.startswith(("INSERT ", "<!doctype"))]
        # pedaços de frases que só aparecem já juntos (a frase inteira está no catálogo)
        todo = [s for s in todo if s not in ("O processador e a placa gráfica baixaram", "A placa gráfica baixou",
                                             "{} o clock por temperatura este mês.")]
        self.assertEqual(todo, [])


if __name__ == "__main__":
    unittest.main()
