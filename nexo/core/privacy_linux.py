"""Privacidade no Linux: o equivalente ao "debloat" do Windows, mas para o que existe nas distribuições.

O Linux não tem telemetria do sistema como o Windows, mas há algumas coisas que guardam ou enviam dados:
- histórico de ficheiros recentes (GNOME, KDE) e o "uso de aplicações" do KDE (kactivitymanagerd);
- relatórios de problemas e estatísticas de uso (GNOME, KUserFeedback do KDE);
- serviço de localização (GNOME);
- relatórios de erros da distribuição (apport/whoopsie no Ubuntu, abrt no Fedora) e estatísticas de
  pacotes (pkgstats no Arch, popularity-contest no Debian/Ubuntu).

Cada ajuste guarda o valor original (tweaks_backup.json) e desligá-lo repõe-no."""
from __future__ import annotations

import glob
import os
import re

from .tweaks import Tweak
from .util import IS_LINUX, run, run_root, which

P = "Privacidade"


# --------------------------------------------------------------------------- GNOME (gsettings)
class GsettingsTweak(Tweak):
    def __init__(self, id, name, desc, values: list[tuple[str, str, str]]):
        """values = [(schema, chave, valor quando ligado)] — valores no formato do gsettings (false, true…)"""
        self.id, self.name, self.desc, self.values, self.category = id, name, desc, values, P

    def available(self) -> bool:
        if not (IS_LINUX and which("gsettings")) or "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            return False   # no KDE os esquemas do GNOME existem mas o Plasma não os usa
        schema, key, _v = self.values[0]
        code, _ = run(["gsettings", "writable", schema, key], timeout=5)
        return code == 0

    def is_on(self) -> bool | None:
        return all(run(["gsettings", "get", s, k], timeout=5)[1].strip() == v for s, k, v in self.values)

    def set(self, on: bool) -> tuple[bool, str]:
        for s, k, v in self.values:
            if on:
                self._backup_set(f"{s}:{k}", run(["gsettings", "get", s, k], timeout=5)[1].strip())
                code, out = run(["gsettings", "set", s, k, v], timeout=5)
            else:
                orig = self._backup_get(f"{s}:{k}")
                code, out = run(["gsettings", "set", s, k, orig] if orig else ["gsettings", "reset", s, k], timeout=5)
                self._backup_clear(f"{s}:{k}")
            if code != 0:
                return False, out.strip() or "gsettings falhou"
        return True, "Feito"


# --------------------------------------------------------------------------- KDE (kwriteconfig)
def _kcfg(tool: str) -> str | None:
    return which(f"{tool}6") or which(f"{tool}5")


class KConfigTweak(Tweak):
    def __init__(self, id, name, desc, values: list[tuple[str, str, str, str]], default_on: bool = False):
        """values = [(ficheiro, grupo, chave, valor quando ligado)]; default_on = o valor por omissão já é o
        "ligado" (chave ausente conta como ligado)."""
        self.id, self.name, self.desc, self.values, self.category = id, name, desc, values, P
        self.default_on = default_on

    def available(self) -> bool:
        return IS_LINUX and bool(_kcfg("kwriteconfig")) and "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper()

    def _get(self, f, g, k) -> str:
        return run([_kcfg("kreadconfig"), "--file", f, "--group", g, "--key", k], timeout=5)[1].strip()

    def is_on(self) -> bool | None:
        vals = [(self._get(f, g, k), v) for f, g, k, v in self.values]
        return all(cur == v or (not cur and self.default_on) for cur, v in vals)

    def set(self, on: bool) -> tuple[bool, str]:
        w = _kcfg("kwriteconfig")
        for f, g, k, v in self.values:
            if on:
                self._backup_set(f"{f}:{g}:{k}", self._get(f, g, k))
                cmd = [w, "--file", f, "--group", g, "--key", k, v]
            else:
                orig = self._backup_get(f"{f}:{g}:{k}")
                cmd = [w, "--file", f, "--group", g, "--key", k] + ([orig] if orig else ["--delete"])
                self._backup_clear(f"{f}:{g}:{k}")
            code, out = run(cmd, timeout=5)
            if code != 0:
                return False, out.strip() or "kwriteconfig falhou"
        return True, "Feito (pode ser preciso terminar a sessão)"


# --------------------------------------------------------------------------- serviços da distribuição
def _unit_exists(unit: str) -> bool:
    return any(os.path.exists(f"{d}/{unit}") for d in ("/usr/lib/systemd/system", "/lib/systemd/system",
                                                        "/etc/systemd/system"))


class UnitsTweak(Tweak):
    """Desliga serviços/timers do systemd (ligado = desligados)."""
    needs_admin = True

    def __init__(self, id, name, desc, units: list[str]):
        self.id, self.name, self.desc, self.category = id, name, desc, P
        self.units = units

    def _present(self) -> list[str]:
        return [u for u in self.units if _unit_exists(u)]

    def available(self) -> bool:
        return IS_LINUX and which("systemctl") is not None and bool(self._present())

    def is_on(self) -> bool | None:
        return all(run(["systemctl", "is-enabled", u], timeout=5)[1].strip() in ("disabled", "masked")
                   for u in self._present())

    def set(self, on: bool) -> tuple[bool, str]:
        units = self._present()
        if on:
            was = [u for u in units if run(["systemctl", "is-enabled", u], timeout=5)[1].strip() == "enabled"]
            self._backup_set("enabled", was)
            code, out = run_root(["systemctl", "disable", "--now", *units], timeout=120)
        else:
            was = self._backup_get("enabled") or units
            code, out = run_root(["systemctl", "enable", "--now", *was], timeout=120)
            if code == 0:
                self._backup_clear("enabled")
        return code == 0, "Feito" if code == 0 else out.strip()[:300]


class PopconTweak(Tweak):
    """popularity-contest (Debian/Ubuntu): envia semanalmente a lista dos pacotes usados."""
    id, name, category, needs_admin = "lx_popcon", "Não participar no popularity-contest", P, True
    desc = "O Debian/Ubuntu deixa de enviar todas as semanas a lista dos pacotes que usa."
    CONF = "/etc/popularity-contest.conf"

    def available(self) -> bool:
        return IS_LINUX and os.path.exists(self.CONF)

    def _participates(self) -> bool:
        try:
            with open(self.CONF, encoding="utf-8", errors="replace") as fh:
                return bool(re.search(r'^\s*PARTICIPATE\s*=\s*"?yes', fh.read(), re.M))
        except OSError:
            return False

    def is_on(self) -> bool | None:
        return not self._participates()

    def set(self, on: bool) -> tuple[bool, str]:
        new = "no" if on else "yes"
        code, out = run_root(["sed", "-i", f's/^\\s*PARTICIPATE\\s*=.*/PARTICIPATE="{new}"/', self.CONF], timeout=60)
        return code == 0, "Feito" if code == 0 else out.strip()[:300]


# --------------------------------------------------------------------------- catálogo
def linux_privacy_tweaks() -> list[Tweak]:
    if not IS_LINUX:
        return []
    tw: list[Tweak] = [
        GsettingsTweak("lx_gnome_recent", "Não guardar ficheiros recentes (GNOME)",
                       "O ambiente de trabalho deixa de registar os ficheiros que abre.",
                       [("org.gnome.desktop.privacy", "remember-recent-files", "false")]),
        GsettingsTweak("lx_gnome_reports", "Não enviar relatórios de problemas nem estatísticas (GNOME)",
                       "Desliga o envio automático de relatórios técnicos e estatísticas de uso de software.",
                       [("org.gnome.desktop.privacy", "report-technical-problems", "false"),
                        ("org.gnome.desktop.privacy", "send-software-usage-stats", "false")]),
        GsettingsTweak("lx_gnome_location", "Desligar o serviço de localização (GNOME)",
                       "As aplicações deixam de poder pedir a sua localização aproximada.",
                       [("org.gnome.system.location", "enabled", "false")]),
        GsettingsTweak("lx_gnome_trash", "Esvaziar lixo e temporários com mais de 30 dias (GNOME)",
                       "Apaga sozinho o que está no lixo e nos temporários há mais de 30 dias.",
                       [("org.gnome.desktop.privacy", "remove-old-trash-files", "true"),
                        ("org.gnome.desktop.privacy", "remove-old-temp-files", "true")]),
        KConfigTweak("lx_kde_recent", "Não guardar documentos recentes nem o uso de aplicações (KDE)",
                     "O Plasma deixa de registar os ficheiros abertos e as aplicações mais usadas "
                     "(kactivitymanagerd).",
                     [("kdeglobals", "RecentDocuments", "UseRecent", "false"),
                      ("kactivitymanagerd-pluginsrc", "Plugin-org.kde.ActivityManager.Resources.Scoring",
                       "what-to-remember", "2")]),
        KConfigTweak("lx_kde_feedback", "Telemetria do KDE desligada (KUserFeedback)",
                     "O Plasma não envia estatísticas de utilização. Já vem desligada por omissão — este "
                     "interruptor garante que fica assim.",
                     [("PlasmaUserFeedback", "Global", "FeedbackLevel", "0")], default_on=True),
        UnitsTweak("lx_crash_reports", "Desligar relatórios de erros da distribuição",
                   "apport/whoopsie (Ubuntu) ou abrt (Fedora): deixam de recolher e enviar dados quando um "
                   "programa falha.",
                   ["apport.service", "whoopsie.service", "abrtd.service", "abrt-journal-core.service",
                    "abrt-oops.service"]),
        UnitsTweak("lx_pkgstats", "Não enviar estatísticas de pacotes (pkgstats)",
                   "Arch: o pkgstats envia todas as semanas a lista dos pacotes instalados.",
                   ["pkgstats.timer"]),
        PopconTweak(),
    ]
    return [t for t in tw if t.available()]


# --------------------------------------------------------------------------- histórico de ficheiros recentes
def recent_files() -> list[str]:
    home = os.path.expanduser("~")
    out = [p for p in (os.path.join(home, ".local/share/recently-used.xbel"),) if os.path.exists(p)]
    out += glob.glob(os.path.join(home, ".local/share/RecentDocuments/*.desktop"))
    return out


def clear_recent() -> tuple[bool, str]:
    """Apaga o histórico de ficheiros recentes (GTK e KDE) e as estatísticas de uso do Plasma."""
    n = 0
    for p in recent_files():
        try:
            os.remove(p)
            n += 1
        except OSError:
            pass
    q = which("qdbus6") or which("qdbus")
    kde = False
    if q:
        code, _ = run([q, "org.kde.ActivityManager", "/ActivityManager/Resources/Scoring",
                       "org.kde.ActivityManager.ResourcesScoring.DeleteRecentStats", "", "0", "everything"], timeout=10)
        kde = code == 0
    if not n and not kde:
        return True, "Não havia histórico de ficheiros recentes."
    return True, "Histórico de ficheiros recentes apagado" + (" (incluindo o do Plasma)." if kde else ".")
