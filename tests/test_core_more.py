"""Testes das partes que mexem no sistema ou interpretam a saída de outros programas.

Nada aqui toca no sistema real: os comandos (run/run_root), o registo e a rede são simulados e
os ficheiros vivem em pastas temporárias.
"""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from nexo.core import cleanup, disksafety, diskscan, games, network, startup, tweaks, updates, util


class TempConfig(unittest.TestCase):
    """Isola config_dir() numa pasta temporária."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": self.tmp.name, "APPDATA": self.tmp.name})
        p.start()
        self.addCleanup(p.stop)
        q = mock.patch.object(util, "_settings", None)
        q.start()
        self.addCleanup(q.stop)


# =========================================================================== atualizações
class UpdateParsers(unittest.TestCase):
    def test_arrow_lines(self):
        out = "linux 6.10.1-1 -> 6.10.2-1\nmesa 1:24.1-1 -> 1:24.2-1\nlixo sem seta\n"
        ups = updates._arrow_lines(out, "Sistema")
        self.assertEqual([(u.name, u.current, u.new) for u in ups],
                         [("linux", "6.10.1-1", "6.10.2-1"), ("mesa", "1:24.1-1", "1:24.2-1")])

    def test_winget_table_pt(self):
        out = ("\r   - \r   \\ \r"
               "Nome                       ID                      Versão       Disponível   Origem\n"
               "------------------------------------------------------------------------------------\n"
               "Mozilla Firefox (x64 pt-PT) Mozilla.Firefox          130.0        131.0.2      winget\n"
               "7-Zip 23.01 (x64)           7zip.7zip                23.01        24.08        winget\n"
               "2 atualizações disponíveis.\n")
        ups = updates.parse_winget(out)
        self.assertEqual(len(ups), 2)
        self.assertEqual(ups[0].current, "130.0")
        self.assertEqual(ups[1].new, "24.08")
        self.assertTrue(all(u.source == "winget" for u in ups))

    def test_winget_no_table(self):
        self.assertEqual(updates.parse_winget("Nenhuma atualização disponível."), [])

    def test_pacman_fallback_when_mirrors_hang(self):
        calls = []

        def fake_run(cmd, timeout=0, **_k):
            calls.append(cmd[0])
            if cmd[0] == "checkupdates":
                return 124, ""
            return 0, "firefox 130-1 -> 131-1\n"
        with mock.patch.object(updates, "which", return_value="/usr/bin/x"), \
                mock.patch.object(updates, "run", side_effect=fake_run):
            ups, note = updates._pacman()
        self.assertEqual(calls, ["checkupdates", "pacman"])
        self.assertEqual(ups[0].name, "firefox")
        self.assertIn("não responderam", note)

    def test_pacman_no_updates(self):
        with mock.patch.object(updates, "which", return_value="/usr/bin/x"), \
                mock.patch.object(updates, "run", return_value=(2, "")):
            self.assertEqual(updates._pacman(), ([], ""))

    def test_apt(self):
        out = ("A listar...\n"
               "firefox/noble-updates 131.0+build1 amd64 [atualizável de: 130.0+build2]\n"
               "libc6/noble-updates,noble-security 2.39-0ubuntu8.3 amd64 [upgradable from: 2.39-0ubuntu8.2]\n")
        with mock.patch.object(updates, "run", return_value=(0, out)):
            ups, _ = updates._apt()
        self.assertEqual([(u.name, u.current, u.new) for u in ups],
                         [("firefox", "130.0+build2", "131.0+build1"), ("libc6", "2.39-0ubuntu8.2", "2.39-0ubuntu8.3")])

    def test_dnf_exit_100_means_updates(self):
        out = "\nkernel.x86_64    6.10.3-200.fc40    updates\nObsoleting Packages\n"
        with mock.patch.object(updates, "run", return_value=(100, out)):
            ups, note = updates._dnf()
        self.assertEqual([(u.name, u.new) for u in ups], [("kernel", "6.10.3-200.fc40")])
        self.assertEqual(note, "")

    def test_zypper(self):
        out = ("S | Repository | Name  | Current Version | Available Version | Arch\n"
               "--+------------+-------+-----------------+-------------------+-------\n"
               "v | repo-oss   | vim   | 9.1.0-1.1       | 9.1.1-1.1         | x86_64\n")
        with mock.patch.object(updates, "run", return_value=(0, out)):
            ups, _ = updates._zypper()
        self.assertEqual([(u.name, u.current, u.new) for u in ups], [("vim", "9.1.0-1.1", "9.1.1-1.1")])

    def test_one_broken_source_does_not_break_others(self):
        def boom():
            raise RuntimeError("partiu")
        boom.__name__ = "_boom"
        ok = lambda: ([updates.Update("a", "1", "2", "Flatpak")], "")  # noqa: E731
        with mock.patch.object(updates, "IS_WIN", True), mock.patch.object(updates, "_winget", boom), \
                mock.patch.object(updates, "save_json"):
            data = updates.check()
        self.assertEqual(data["items"], [])
        self.assertTrue(any("partiu" in n for n in data["notes"]))
        with mock.patch.object(updates, "IS_WIN", True), mock.patch.object(updates, "_winget", ok), \
                mock.patch.object(updates, "save_json"):
            self.assertEqual(len(updates.check()["items"]), 1)

    def test_items_ignores_bad_cache_rows(self):
        data = {"items": [{"name": "a", "current": "1", "new": "2", "source": "AUR"}, {"lixo": 1}]}
        self.assertEqual([u.name for u in updates.items(data)], ["a"])


# =========================================================================== ajustes (reversíveis)
class TweakBackups(TempConfig):
    def test_sysctl_restores_original_value(self):
        t = tweaks.LinuxSysctl("bbr", "BBR", "", "net.ipv4.tcp_congestion_control", "bbr")
        cmds = []
        with mock.patch.object(tweaks, "read_text", return_value="cubic"), \
                mock.patch.object(tweaks, "run_root", side_effect=lambda c, *a, **k: (cmds.append(c), (0, ""))[1]), \
                mock.patch.object(tweaks.snapshot, "with_snapshot", side_effect=lambda c, *_a: c):
            self.assertTrue(t.set(True)[0])
            self.assertTrue(t.set(True)[0])          # ligar 2× não pode perder o original
            self.assertTrue(t.set(False)[0])
        self.assertIn("sysctl -w net.ipv4.tcp_congestion_control=bbr", cmds[0])
        self.assertIn("sysctl -w net.ipv4.tcp_congestion_control=cubic", cmds[-1])
        self.assertIsNone(t._backup_get("v"))       # limpo depois de repor

    def test_sysctl_failed_revert_keeps_backup(self):
        t = tweaks.LinuxSysctl("x", "X", "", "vm.swappiness", "10")
        with mock.patch.object(tweaks, "read_text", return_value="60"), \
                mock.patch.object(tweaks.snapshot, "with_snapshot", side_effect=lambda c, *_a: c), \
                mock.patch.object(tweaks, "run_root", return_value=(0, "")):
            t.set(True)
        with mock.patch.object(tweaks, "run_root", return_value=(126, "cancelado")):
            self.assertFalse(t.set(False)[0])
        self.assertEqual(t._backup_get("v"), "60")

    def test_registry_tweak_round_trip(self):
        reg = {("HKCU", "P", "A"): 5}
        fake = {
            "reg_get": lambda h, p, n: reg.get((h, p, n)),
            "reg_set": lambda h, p, n, _t, v: reg.__setitem__((h, p, n), v),
            "reg_del": lambda h, p, n: reg.pop((h, p, n), None),
        }
        patches = [mock.patch.object(tweaks, k, v, create=True) for k, v in fake.items()]
        patches.append(mock.patch.object(tweaks, "IS_WIN", True))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        t = tweaks.RegTweak("t1", "T", "", [("HKCU", "P", "A", "dword", 1), ("HKCU", "P", "B", "dword", 1)])
        self.assertFalse(t.is_on())
        self.assertTrue(t.set(True)[0])
        self.assertTrue(t.is_on())
        self.assertTrue(t.set(False)[0])
        self.assertEqual(reg, {("HKCU", "P", "A"): 5})   # A volta ao original, B (não existia) é apagado

    def test_catalogs_have_unique_ids(self):
        allt = tweaks.performance_tweaks() + tweaks.privacy_tweaks()
        ids = [t.id for t in allt]
        self.assertEqual(len(ids), len(set(ids)))


# =========================================================================== limpeza
class CleanupSafety(TempConfig):
    def test_no_category_targets_system_or_home(self):
        home = os.path.realpath(os.path.expanduser("~"))
        for cat in cleanup.categories():
            for pat in cat.patterns:
                expanded = os.path.expandvars(os.path.expanduser(pat))
                self.assertTrue(expanded.endswith(("*", "*.db", "*.log")) or "*" in expanded or "?" in expanded
                                or os.path.basename(expanded), f"{cat.id}: {pat}")
                base = expanded.split("*")[0].rstrip("/\\")
                self.assertNotEqual(os.path.realpath(base or "/"), "/", f"{cat.id} aponta para a raiz: {pat}")
                self.assertNotEqual(os.path.realpath(base), home, f"{cat.id} apagaria a pasta pessoal: {pat}")
            for t in cat.targets():
                self.assertNotEqual(disksafety.classify(t).level, disksafety.SYSTEM,
                                    f"{cat.id} incluiria um item do sistema: {t}")

    def test_no_mtime_based_cache_wipe(self):
        """Regra: nunca usar a idade (mtime) da ~/.cache inteira como «não usado» (partiu Pythons do wine)."""
        for cat in cleanup.categories():
            if cat.min_age_days:
                for pat in cat.patterns:
                    self.assertNotRegex(os.path.expanduser(pat).replace("\\", "/"), r"/\.cache/\*$", cat.id)

    def test_clean_respects_min_age(self):
        d = Path(self.tmp.name) / "lixo"
        d.mkdir()
        old, new = d / "velho.tmp", d / "novo.tmp"
        old.write_text("x")
        new.write_text("y")
        os.utime(old, (1, 1))
        cat = cleanup.CleanCategory("t", "T", "", [str(d / "*")], min_age_days=1)
        ok, _msg = cleanup.clean(cat)
        self.assertTrue(ok)
        self.assertFalse(old.exists())
        self.assertTrue(new.exists())

    def test_admin_clean_quotes_paths(self):
        d = Path(self.tmp.name) / "a pasta's"
        d.mkdir()
        (d / "f").write_text("x")
        cat = cleanup.CleanCategory("t", "T", "", [str(d / "*")], needs_admin=True)
        with mock.patch.object(cleanup, "run_root", return_value=(0, "")) as rr, \
                mock.patch.object(cleanup, "IS_LINUX", True), mock.patch("os.geteuid", return_value=1000, create=True):
            cleanup.clean(cat)
        cmd = rr.call_args[0][0]
        self.assertEqual(cmd[:3], ["rm", "-rf", "--"])   # lista de argumentos: sem shell, sem citações
        self.assertTrue(all(c.startswith(str(d)) for c in cmd[3:]))


# =========================================================================== arranque
class StartupLinux(TempConfig):
    def test_disable_and_enable_xdg_entry(self):
        sysdir = Path(self.tmp.name) / "xdg" / "autostart"
        sysdir.mkdir(parents=True)
        src = sysdir / "app.desktop"
        src.write_text("[Desktop Entry]\nName=App\nExec=app --tray\nHidden=false\n\n[Desktop Action x]\nName=X\n")
        item = startup.StartupItem("App", "app --tray", str(sysdir), True, "xdg",
                                   {"file": "app.desktop", "path": str(src)})
        ok, _ = startup._linux_set(item, False)
        self.assertTrue(ok)
        user = Path(self.tmp.name) / "autostart" / "app.desktop"
        txt = user.read_text()
        self.assertIn("Hidden=true", txt)
        self.assertEqual(txt.count("Hidden="), 1)
        self.assertLess(txt.index("Hidden=true"), txt.index("[Desktop Action x]"))  # dentro da secção certa
        self.assertIn("Hidden=false", src.read_text())                           # o original não muda
        startup._linux_set(item, True)
        self.assertIn("Hidden=false", user.read_text())

    def test_essential_detection(self):
        self.assertTrue(startup._is_essential("/usr/bin/plasmashell"))
        self.assertTrue(startup._is_essential("/usr/lib/polkit-kde-authentication-agent-1"))
        self.assertFalse(startup._is_essential("discord --start-minimized"))


# =========================================================================== jogos
class SteamManifests(unittest.TestCase):
    def test_acf_and_tools_filtered(self):
        with tempfile.TemporaryDirectory() as lib:
            Path(lib, "appmanifest_1.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"1091500"\n\t"name"\t\t"Cyber Jogo"\n\t"installdir"\t\t"Cyber"\n'
                '\t"SizeOnDisk"\t\t"1000"\n}\n')
            Path(lib, "appmanifest_2.acf").write_text(
                '"AppState"\n{\n\t"appid"\t\t"1493710"\n\t"name"\t\t"Proton Experimental"\n}\n')
            with mock.patch.object(games, "steam_libraries", return_value=[lib]):
                gs = games._steam_games()
        self.assertEqual([(g.name, g.size) for g in gs], [("Cyber Jogo", 1000)])
        self.assertTrue(gs[0].path.endswith(os.path.join("common", "Cyber")))


# =========================================================================== rede
class NetworkCheck(unittest.TestCase):
    def _check(self, ifs, tcp, dns, portal):
        with mock.patch.object(network, "interfaces", return_value=ifs), \
                mock.patch.object(network, "reach_internet", return_value=tcp), \
                mock.patch.object(network, "resolves", return_value=dns), \
                mock.patch.object(network, "portal_check", return_value=portal):
            return network.check()

    def test_states(self):
        eth = [("eth0", "Cabo")]
        self.assertEqual(self._check([], None, False, "erro").state, network.OFFLINE)
        self.assertEqual(self._check(eth, 12.0, True, "ok").state, network.ONLINE)
        self.assertEqual(self._check(eth, 12.0, False, "ok").state, network.NO_DNS)
        self.assertEqual(self._check(eth, None, True, "portal").state, network.PORTAL)
        self.assertEqual(self._check(eth, 12.0, True, "portal").state, network.PORTAL)
        self.assertEqual(self._check(eth, None, True, "ok").state, network.ONLINE)  # via proxy

    def test_dns_alone_is_not_online(self):
        st = self._check([("wlan0", "Wi-Fi")], None, True, "erro")
        self.assertEqual(st.state, network.LIMITED)
        self.assertFalse(st.online)

    def test_friendly_error(self):
        self.assertIn("internet", network.friendly_error("Temporary failure in name resolution"))
        self.assertIn("demorou", network.friendly_error("timed out"))
        self.assertEqual(network.friendly_error("algo raro"), "algo raro")


# =========================================================================== análise do disco
class DiskScan(unittest.TestCase):
    def test_scan_counts_and_largest(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "sub").mkdir()
            mb = 1024**2
            dup = os.urandom(9 * mb)   # o scan conta o espaço ocupado (ficheiros esparsos dariam 0)
            Path(root, "a.bin").write_bytes(os.urandom(12 * mb))
            Path(root, "sub", "b.txt").write_bytes(dup)
            Path(root, "sub", "c.txt").write_bytes(dup)   # duplicado de b.txt
            with mock.patch.object(diskscan, "_DUP_EXCLUDE", ()):   # no Windows o Temp está excluído
                res = diskscan.scan(root, find_duplicates=False, collect_duplicates=True)  # como a página
            dups = diskscan.find_duplicates(res)
        self.assertEqual(res.files, 3)
        self.assertEqual(res.total, 30 * mb)
        self.assertEqual(res.largest[0].path, os.path.join(root, "a.bin"))
        self.assertEqual(len(dups), 1)
        self.assertEqual(sorted(os.path.basename(f.path) for f in dups[0]), ["b.txt", "c.txt"])

    def test_cancel(self):
        with tempfile.TemporaryDirectory() as root:
            Path(root, "x").write_text("x")
            res = diskscan.scan(root, cancelled=lambda: True)
        self.assertTrue(res.cancelled)


# =========================================================================== definições corrompidas
class CorruptJson(TempConfig):
    def test_corrupt_file_is_kept_aside(self):
        p = util.config_dir() / "coisa.json"
        p.write_text("{isto não é json", encoding="utf-8")
        with self.assertLogs("nexo.config", "WARNING"):
            self.assertEqual(util.load_json("coisa.json", {"d": 1}), {"d": 1})
        self.assertTrue((util.config_dir() / "coisa.json.corrompido").exists())

    def test_missing_file_is_silent(self):
        self.assertEqual(util.load_json("nao-existe.json", []), [])


if __name__ == "__main__":
    unittest.main()
