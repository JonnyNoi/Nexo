"""Atualizações pendentes do sistema e das aplicações (só leitura — instalar fica a pedido do utilizador).

Linux: pacman (checkupdates, base de dados temporária — não precisa de root), AUR (paru/yay -Qua),
apt (apt list --upgradable), dnf (check-update), zypper (list-updates) e Flatpak.
Windows: winget upgrade.
"""
from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass

import shutil
import subprocess

from .util import IS_WIN, load_json, run, save_json, which

CACHE = "updates.json"


@dataclass
class Update:
    name: str
    current: str
    new: str
    source: str          # "Sistema", "AUR", "Flatpak", "winget"


def _arrow_lines(out: str, source: str) -> list[Update]:
    """Formato "nome versão-antiga -> versão-nova" (checkupdates, paru/yay -Qua)."""
    res = []
    for ln in out.splitlines():
        m = re.match(r"^(\S+)\s+(\S+)\s+->\s+(\S+)", ln.strip())
        if m:
            res.append(Update(m.group(1), m.group(2), m.group(3), source))
    return res


def _pacman() -> tuple[list[Update], str]:
    if which("checkupdates"):
        code, out = run(["checkupdates"], timeout=90)
        if code == 2:            # sem atualizações
            return [], ""
        if code == 0:
            return _arrow_lines(out, "Sistema"), ""
        why = "os servidores (mirrors) não responderam a tempo" if code == 124 else "não foi possível contactar os mirrors"
    else:
        why = "o checkupdates não está instalado (pacote «pacman-contrib»)"
    # plano B: base de dados local (instantâneo, mas só tão recente como o último "pacman -Sy")
    _c, out = run(["pacman", "-Qu"], timeout=30)
    return _arrow_lines(out, "Sistema"), f"Pacman: {why} — a lista usa a última sincronização do sistema."


def _aur() -> tuple[list[Update], str]:
    for helper in ("paru", "yay"):
        if which(helper):
            code, out = run([helper, "-Qua"], timeout=180)
            return _arrow_lines(out, "AUR"), ""
    return [], ""


def _apt() -> tuple[list[Update], str]:
    code, out = run(["apt", "list", "--upgradable"], timeout=120)
    res = []
    for ln in out.splitlines():
        m = re.match(r"^([^/\s]+)/\S+\s+(\S+)\s+\S+\s+\[[^:]*:\s*([^\]]+)\]", ln)
        if m:
            res.append(Update(m.group(1), m.group(3).strip(), m.group(2), "Sistema"))
    return res, "A lista do apt é a da última vez que o sistema procurou atualizações (apt update)."


def _dnf() -> tuple[list[Update], str]:
    code, out = run(["dnf", "-q", "check-update"], timeout=300)
    if code not in (0, 100):
        return [], f"dnf check-update falhou ({code})."
    res = []
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) == 3 and "." in parts[0] and not ln.startswith(" "):
            res.append(Update(parts[0].rsplit(".", 1)[0], "", parts[1], "Sistema"))
    return res, ""


def _zypper() -> tuple[list[Update], str]:
    code, out = run(["zypper", "-q", "--non-interactive", "list-updates"], timeout=300)
    res = []
    for ln in out.splitlines():
        cols = [c.strip() for c in ln.split("|")]
        if len(cols) >= 6 and cols[0] == "v":
            res.append(Update(cols[2], cols[3], cols[4], "Sistema"))
    return res, ""


def _flatpak() -> tuple[list[Update], str]:
    if not which("flatpak"):
        return [], ""
    code, out = run(["flatpak", "remote-ls", "--updates", "--columns=name,application,version"], timeout=180)
    if code != 0:
        return [], ""
    cur = {}
    _c, inst = run(["flatpak", "list", "--columns=application,version"], timeout=60)
    for ln in inst.splitlines():
        p = ln.split("\t")
        if len(p) >= 2:
            cur[p[0].strip()] = p[1].strip()
    res = []
    for ln in out.splitlines():
        p = ln.split("\t")
        if len(p) >= 2 and p[1].strip():
            app = p[1].strip()
            res.append(Update(p[0].strip() or app, cur.get(app, ""), p[2].strip() if len(p) > 2 else "", "Flatpak"))
    return res, ""


def parse_winget(out: str) -> list[Update]:
    """Tabela do `winget upgrade` (colunas de largura fixa; cabeçalhos traduzidos conforme o idioma)."""
    lines = [ln.split("\r")[-1].rstrip() for ln in out.splitlines()]
    sep = next((i for i, ln in enumerate(lines) if re.fullmatch(r"-{10,}", ln.strip())), None)
    if sep is None or sep == 0:
        return []
    header = lines[sep - 1]
    starts = [m.start() for m in re.finditer(r"\S+", header)]
    if len(starts) < 4:
        return []
    res = []
    for ln in lines[sep + 1:]:
        if not ln.strip() or len(ln) < starts[3]:
            break      # fim da tabela ("N atualizações disponíveis.")
        cols = [ln[a:b].strip() for a, b in zip(starts, starts[1:] + [None])]
        name, pkg_id, cur, new = cols[0], cols[1], cols[2], cols[3]
        if pkg_id and new:
            res.append(Update(name or pkg_id, cur, new, "winget"))
    return res


def _winget() -> tuple[list[Update], str]:
    if not which("winget"):
        return [], "O winget não está instalado (Instalador de Aplicações da Microsoft Store)."
    code, out = run(["winget", "upgrade", "--include-unknown", "--accept-source-agreements",
                     "--disable-interactivity"], timeout=180)
    return parse_winget(out), ""


def check() -> dict:
    """Procura atualizações em todas as fontes disponíveis e guarda o resultado em cache."""
    found: list[Update] = []
    notes: list[str] = []
    if IS_WIN:
        sources = [_winget]
    else:
        pm = next((p for p in ("pacman", "apt", "dnf", "zypper") if which(p)), None)
        sources = {"pacman": [_pacman, _aur], "apt": [_apt], "dnf": [_dnf], "zypper": [_zypper]}.get(pm, [])
        sources.append(_flatpak)
    def safe(fn):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001 — uma fonte com problemas não estraga as outras
            return [], f"{fn.__name__.strip('_')}: {e}"
    with ThreadPoolExecutor(max_workers=max(1, len(sources))) as ex:   # as fontes correm em paralelo
        for ups, note in ex.map(safe, sources):
            found += ups
            if note:
                notes.append(note)
    data = {"time": time.time(), "items": [asdict(u) for u in found], "notes": notes}
    save_json(CACHE, data)
    return data


def cached() -> dict:
    d = load_json(CACHE, {})
    return d if isinstance(d, dict) else {}


def items(data: dict) -> list[Update]:
    out = []
    for it in data.get("items", []):
        try:
            out.append(Update(**it))
        except TypeError:
            pass
    return out


def has_aur_helper() -> str | None:
    return next((h for h in ("paru", "yay") if which(h)), None)


def update_all(sources: set[str]) -> tuple[bool, str]:
    """Instala as atualizações das origens indicadas (o AUR fica para o terminal: precisa de interação)."""
    from . import apps, systools
    done, problems = [], []
    if IS_WIN:
        if "winget" in sources:
            ok, msg = apps.upgrade_all()
            (done if ok else problems).append("winget" if ok else f"winget: {msg}")
    else:
        if "Sistema" in sources:
            ok, msg = systools.linux_update_system()
            (done if ok else problems).append("sistema" if ok else f"sistema: {msg}")
        if "Flatpak" in sources and which("flatpak"):
            code, out = run(["flatpak", "update", "-y", "--noninteractive"], timeout=3600)
            (done if code == 0 else problems).append("Flatpak" if code == 0 else f"Flatpak: {out[-200:]}")
    if problems:
        return False, " · ".join(problems)
    return True, ("Atualizado: " + ", ".join(done) + ".") if done else "Nada para atualizar."


_TERMINALS = [("konsole", ["--hold", "-e"]), ("gnome-terminal", ["--"]), ("kgx", ["--"]), ("kitty", ["--hold"]),
              ("alacritty", ["--hold", "-e"]), ("wezterm", ["start", "--"]), ("foot", ["--hold"]),
              ("xfce4-terminal", ["--hold", "-x"]), ("tilix", ["-e"]), ("xterm", ["-hold", "-e"])]


def update_command() -> str:
    """Comando de atualização completa para correr num terminal (interativo)."""
    if IS_WIN:
        return "winget upgrade --all --include-unknown"
    aur = has_aur_helper()
    cmds = []
    if aur:
        cmds.append(f"{aur} -Syu")
    else:
        pm = next((p for p in ("pacman", "apt", "dnf", "zypper") if which(p)), None)
        cmds.append({"pacman": "sudo pacman -Syu", "apt": "sudo apt update && sudo apt upgrade",
                     "dnf": "sudo dnf upgrade --refresh", "zypper": "sudo zypper update"}.get(pm, "true"))
    if which("flatpak"):
        cmds.append("flatpak update")
    return " ; ".join(cmds)


def open_terminal_update() -> tuple[bool, str]:
    return open_terminal(update_command())


def open_terminal(cmd: str) -> tuple[bool, str]:
    """Abre um terminal a correr `cmd` (interativo: pode pedir a palavra-passe ou confirmações)."""
    if IS_WIN:
        subprocess.Popen(["cmd", "/c", "start", "", "cmd", "/k", cmd])
        return True, f"Abri uma janela de comandos com: {cmd}"
    script = f"{cmd} ; echo ; echo 'Concluído — pode fechar esta janela.'"
    for term, args in _TERMINALS:
        if shutil.which(term):
            try:
                subprocess.Popen([term, *args, "sh", "-c", script], start_new_session=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return True, f"Abri o {term} com: {cmd}"
            except OSError:
                continue
    return False, f"Não encontrei nenhum terminal. Execute à mão: {cmd}"
