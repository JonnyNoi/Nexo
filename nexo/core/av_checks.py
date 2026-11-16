"""Verificações próprias do antivírus do Nexo (heurísticas): processos disfarçados e mineradores, ligações
suspeitas, persistência no arranque/cron/tarefas agendadas/WMI, definições de segurança do sistema, ficheiros
com extensão dupla ou em pastas temporárias, rootkits conhecidos e pens USB com autorun.

Cada verificação recebe `add(Finding)` e não altera nada no sistema."""

import os
import re
import stat
import sys
import time
from pathlib import Path

import psutil

from .util import IS_LINUX, IS_WIN, as_list, ps_json, run, which


from .av_model import BAD, INFO, LEVEL_ORDER, WARN, Finding

# =========================================================================== padrões suspeitos
# (regex, nível, explicação, aplica-se a ficheiros de shell como .bashrc?)
_CMD_PATTERNS = [
    (r"/dev/tcp/|\bnc(at)?\b[^\n]*\s-e\s|bash\s+-i\s*>&|socat\s+exec:", BAD,
     "Shell reversa — dá controlo remoto do computador a outra pessoa", True),
    (r"xmrig|xmr-stak|minerd|cpuminer|stratum\+(tcp|ssl)|cryptonight|kdevtmpfsi|kinsing|nicehash", BAD,
     "Minerador de criptomoedas", True),
    (r"(curl|wget)\b[^|;&\n]*\|\s*(sudo\s+)?(ba|z|da)?sh\b", WARN, "Descarrega e executa código da Internet", True),
    (r"base64\s+(-d|--decode)[^\n]*\|\s*(ba|z|da)?sh|echo\s+[A-Za-z0-9+/=]{60,}\s*\|\s*base64", BAD,
     "Executa código escondido (ofuscado em base64)", True),
    (r"\balias\s+sudo=", BAD, "Substitui o comando sudo (técnica para roubar a palavra-passe)", True),
    (r"\bLD_PRELOAD=", WARN, "Injeta uma biblioteca em todos os programas (LD_PRELOAD)", True),
    (r"(^|[\s'\"=])/(tmp|dev/shm|var/tmp)/\S+", WARN, "Executa um programa a partir de uma pasta temporária", False),
]
_WIN_PATTERNS = [
    (r"powershell[^\n]*\s-e(nc(odedcommand)?)?\s+[A-Za-z0-9+/=]{40,}", BAD,
     "PowerShell com comando codificado (ofuscado)"),
    (r"\b(iex|invoke-expression)\b[^\n]*(downloadstring|net\.webclient|iwr|invoke-webrequest|irm\b)", BAD,
     "Descarrega e executa código da Internet"),
    (r"mshta(\.exe)?\s+[\"']?(https?:|javascript:|vbscript:)", BAD, "mshta a executar código remoto"),
    (r"regsvr32(\.exe)?[^\n]*/i:\s*https?:", BAD, "regsvr32 a carregar código remoto"),
    (r"rundll32(\.exe)?[^\n]*javascript:", BAD, "rundll32 a executar JavaScript"),
    (r"xmrig|xmr-stak|minerd|cpuminer|stratum\+(tcp|ssl)|nicehash|phoenixminer|nbminer|t-rex", BAD,
     "Minerador de criptomoedas"),
    (r"downloadstring|downloadfile|net\.webclient|start-bitstransfer|bitsadmin(\.exe)?\s+/transfer|"
     r"certutil(\.exe)?[^\n]*-urlcache", WARN, "Descarrega ficheiros da Internet ao arrancar"),
    (r"powershell[^\n]*\s-w(indowstyle)?\s+h(idden)?\b", WARN, "PowerShell a correr escondido"),
    (r"\\appdata\\local\\temp\\|\\windows\\temp\\|%temp%", WARN, "Arranca a partir de uma pasta temporária"),
    (r"(wscript|cscript)(\.exe)?[^\n]*\\(appdata|temp|users\\public)\\", WARN, "Script em pasta de utilizador"),
    (r"\\users\\public\\[^\n]*\.(exe|dll|vbs|js|bat|cmd|ps1)", WARN, "Programa na pasta Pública"),
]


def _match(text: str, shell_rc: bool = False) -> tuple[str, str] | None:
    """Devolve (nível, explicação) do padrão mais grave encontrado, ou None."""
    low = text.lower()
    best = None
    pats = [(r, lv, why) for r, lv, why in _WIN_PATTERNS] if IS_WIN else \
        [(r, lv, why) for r, lv, why, rc in _CMD_PATTERNS if rc or not shell_rc]
    for rx, lv, why in pats:
        if re.search(rx, low, re.M):
            if best is None or LEVEL_ORDER.index(lv) < LEVEL_ORDER.index(best[0]):
                best = (lv, why)
    return best


# =========================================================================== processos
_MINER_NAMES = {"xmrig", "xmr-stak", "minerd", "cpuminer", "kdevtmpfsi", "kinsing", "kworkerds", "ddgs",
                "watchbog", "dbused", "sysrv", "phoenixminer", "nbminer", "t-rex", "lolminer", "gminer",
                "nanominer", "teamredminer", "ethminer", "srbminer"}
# processos do Windows que só podem existir numa pasta concreta
_WIN_SYS = {"svchost.exe": ("system32", "syswow64"), "csrss.exe": ("system32",), "lsass.exe": ("system32",),
            "winlogon.exe": ("system32",), "services.exe": ("system32",), "smss.exe": ("system32",),
            "wininit.exe": ("system32",), "spoolsv.exe": ("system32",), "taskhostw.exe": ("system32",),
            "dwm.exe": ("system32",), "lsm.exe": ("system32",), "conhost.exe": ("system32",),
            "explorer.exe": ("windows", "system32", "syswow64"), "rundll32.exe": ("system32", "syswow64")}
_WIN_TYPOS = {"scvhost.exe", "svch0st.exe", "svchosts.exe", "svhost.exe", "svchost32.exe", "lsas.exe",
              "lsasss.exe", "isass.exe", "csrsss.exe", "crss.exe", "winlogin.exe", "explore.exe",
              "expl0rer.exe", "explorer32.exe", "taskmgr32.exe", "smss32.exe", "windowsupdate.exe",
              "wuauclt32.exe"}
_POOL_PORTS = {3333, 14433, 14444, 45560, 45700, 20535, 20580}


def _temp_dirs() -> list[str]:
    if IS_WIN:
        out = {os.environ.get("TEMP", ""), os.environ.get("TMP", ""),
               os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Temp")}
        return [os.path.normcase(os.path.abspath(p)) for p in out if p]
    return ["/tmp", "/var/tmp", "/dev/shm"]


def _skip_tmp(path: str) -> bool:
    """Pastas temporárias legítimas: AppImages montadas e programas PyInstaller (incluindo o próprio Nexo)."""
    return "/.mount_" in path or "/_MEI" in path or "\\_MEI" in path or \
        bool(getattr(sys, "_MEIPASS", None) and path.startswith(sys._MEIPASS))


def check_processes(add) -> None:
    tmp = _temp_dirs()
    me = os.getpid()
    for p in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
        try:
            info = p.info
            pid, name = info["pid"], (info["name"] or "")
            if pid == me:
                continue
            exe = info["exe"] or ""
            cmd = " ".join(info["cmdline"] or [])
            low = name.lower()
            base = low.removesuffix(".exe")
            if base in _MINER_NAMES or re.search(r"stratum\+(tcp|ssl)://|--donate-level|-o\s+\S*pool", cmd.lower()):
                add(Finding(BAD, "Processo", f"Minerador de criptomoedas a correr: {name}",
                            "Usa o processador/placa gráfica para ganhar dinheiro para outra pessoa. "
                            "Termine o processo e ponha o ficheiro em quarentena.", exe, pid))
                continue
            if IS_WIN:
                if low in _WIN_TYPOS:
                    add(Finding(BAD, "Processo", f"Nome que imita um processo do Windows: {name}",
                                "Os vírus usam nomes parecidos com os do sistema para passar despercebidos.", exe, pid))
                    continue
                if low in _WIN_SYS and exe:
                    sysroot = os.path.normcase(os.environ.get("SystemRoot", r"C:\Windows"))
                    ok_dirs = {os.path.normcase(sysroot if d == "windows" else os.path.join(sysroot, d))
                               for d in _WIN_SYS[low]}
                    if os.path.normcase(os.path.dirname(exe)) not in ok_dirs:
                        add(Finding(BAD, "Processo", f"{name} fora da pasta do Windows",
                                    f"O verdadeiro {name} só corre a partir de C:\\Windows. Este está em outro "
                                    "sítio — é quase de certeza um vírus disfarçado.", exe, pid))
                        continue
            else:
                if exe.endswith(" (deleted)"):
                    real = exe[:-10]
                    if any(real.startswith(t + "/") for t in tmp) and not _skip_tmp(real):
                        add(Finding(BAD, "Processo", f"Processo cujo ficheiro foi apagado: {name}",
                                    "Correu a partir de uma pasta temporária e apagou o próprio ficheiro — "
                                    "técnica típica de malware para não deixar rasto.", real, pid))
                        continue
                if exe.startswith("/memfd:") and not re.search(r"runc|crun|containerd|wine|electron|chrome",
                                                               (name + cmd).lower()):
                    add(Finding(WARN, "Processo", f"Processo a correr só em memória: {name}",
                                "O programa não existe no disco (memfd). Alguns programas legítimos fazem isto, "
                                "mas também é usado por malware para não deixar ficheiros.", "", pid))
                    continue
            if exe:
                ne = os.path.normcase(exe)
                if any(ne.startswith(t + os.sep) for t in tmp) and not _skip_tmp(exe):
                    hidden = os.path.basename(exe).startswith(".")
                    add(Finding(WARN, "Processo",
                                f"Programa a correr de uma pasta temporária: {name}",
                                ("Nome escondido (começa por ponto). " if hidden else "") +
                                ("Instaladores fazem isto às vezes, mas é também típico de vírus. "
                                 "Se não reconhece o programa, termine-o e ponha-o em quarentena."), exe, pid))
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, OSError):
            continue


def check_network(add) -> None:
    try:
        conns = psutil.net_connections("inet")
    except (psutil.AccessDenied, OSError):
        return
    seen = set()
    for c in conns:
        if not c.raddr or c.raddr.port not in _POOL_PORTS:
            continue
        name = ""
        try:
            name = psutil.Process(c.pid).name() if c.pid else ""
        except (psutil.Error, OSError):
            pass
        k = (c.pid, c.raddr.port)
        if k in seen:
            continue
        seen.add(k)
        add(Finding(WARN, "Rede", f"Ligação para uma porta típica de mineração ({c.raddr.ip}:{c.raddr.port})",
                    f"Processo: {name or '?'} (PID {c.pid or '?'}). As portas {', '.join(map(str, sorted(_POOL_PORTS)))} "
                    "são usadas por pools de mineração de criptomoedas.", "", c.pid or 0))


# =========================================================================== arranque / persistência
def check_startup(add) -> None:
    from . import startup
    try:
        items = startup.list_items()
    except Exception:  # noqa: BLE001
        items = []
    for it in items:
        m = _match(it.command)
        if m:
            add(Finding(m[0], "Arranque", f"{m[1]}: {it.name}", f"Origem: {it.source}\nComando: {it.command}",
                        it.ref.get("path", "") if isinstance(it.ref, dict) else ""))
    if IS_WIN:
        _win_tasks(add)
        _win_wmi(add)
    else:
        _linux_persistence(add)


def _win_tasks(add) -> None:
    tasks = ps_json("Get-ScheduledTask | Where-Object {$_.State -ne 'Disabled'} | ForEach-Object { "
                    "$t=$_; $t.Actions | Where-Object {$_.Execute} | ForEach-Object { [pscustomobject]@{"
                    "N=$t.TaskName; P=$t.TaskPath; E=[string]$_.Execute; A=[string]$_.Arguments} } }", timeout=90)
    for t in as_list(tasks):
        if not isinstance(t, dict):
            continue
        cmd = f"{t.get('E', '')} {t.get('A', '')}".strip()
        m = _match(cmd)
        if m:
            add(Finding(m[0], "Arranque", f"Tarefa agendada — {m[1]}: {t.get('N')}",
                        f"Tarefa: {t.get('P', '')}{t.get('N', '')}\nComando: {cmd}"))


def _win_wmi(add) -> None:
    subs = ps_json("Get-CimInstance -Namespace root/subscription -ClassName CommandLineEventConsumer "
                   "-ErrorAction SilentlyContinue | Select-Object Name,CommandLineTemplate", timeout=40)
    for s in as_list(subs):
        if isinstance(s, dict) and s.get("Name") not in ("SCM Event Log Consumer",):
            add(Finding(WARN, "Arranque", f"Subscrição WMI que executa comandos: {s.get('Name')}",
                        "Malware avançado usa subscrições WMI para se reativar sem aparecer no Arranque.\n"
                        f"Comando: {s.get('CommandLineTemplate') or '?'}"))


def _read(p: Path, limit: int = 512_000) -> str:
    try:
        with open(p, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit)
    except OSError:
        return ""


def _linux_persistence(add) -> None:
    home = Path.home()
    # cron
    code, out = run(["crontab", "-l"], timeout=10)
    crons = [("crontab do utilizador", out if code == 0 else "")]
    cron_files = [Path("/etc/crontab")]
    if Path("/etc/cron.d").is_dir():
        cron_files += sorted(Path("/etc/cron.d").glob("*"))
    crons += [(str(p), _read(p)) for p in cron_files]
    for src, text in crons:
        for line in text.splitlines():
            if line.strip().startswith("#") or not line.strip():
                continue
            m = _match(line)
            if m:
                add(Finding(m[0], "Arranque", f"Tarefa cron — {m[1]}", f"{src}:\n{line.strip()}",
                            src if src.startswith("/") else ""))
    # serviços systemd criados pelo administrador / utilizador
    unit_dirs = [Path("/etc/systemd/system"), home / ".config/systemd/user"]
    for d in unit_dirs:
        if not d.is_dir():
            continue
        try:
            units = list(d.rglob("*.service"))[:500]
        except OSError:
            continue
        for u in units:
            text = _read(u, 64_000)
            for line in text.splitlines():
                if line.strip().startswith(("ExecStart", "ExecStartPre", "ExecStartPost")):
                    m = _match(line.split("=", 1)[-1])
                    if m:
                        add(Finding(m[0], "Arranque", f"Serviço systemd — {m[1]}: {u.name}",
                                    f"{u}:\n{line.strip()}", str(u)))
                        break
    # ficheiros de arranque da shell
    rc = [home / n for n in (".bashrc", ".bash_profile", ".profile", ".zshrc", ".zprofile", ".bash_login",
                             ".config/fish/config.fish", ".xprofile", ".xinitrc")]
    rc += [Path("/etc/profile"), Path("/etc/bash.bashrc"), Path("/etc/rc.local"), Path("/etc/environment")]
    if Path("/etc/profile.d").is_dir():
        rc += sorted(Path("/etc/profile.d").glob("*"))
    for p in rc:
        text = _read(p)
        for line in text.splitlines():
            s = line.strip()
            if not s or s.startswith("#"):
                continue
            m = _match(s, shell_rc=True)
            if m:
                add(Finding(m[0], "Arranque", f"{m[1]} em {p.name}", f"{p}:\n{s[:300]}", str(p)))
                break
    # /etc/ld.so.preload: carrega uma biblioteca em todos os programas — truque clássico de rootkits
    pre = _read(Path("/etc/ld.so.preload")).strip()
    if pre and not all(x.strip().startswith("#") for x in pre.splitlines()):
        add(Finding(WARN, "Sistema", "Biblioteca carregada em todos os programas (/etc/ld.so.preload)",
                    "É uma técnica comum de rootkits. Alguns programas legítimos (ex.: hardened_malloc) também a usam "
                    f"— confirme que reconhece:\n{pre[:300]}", "/etc/ld.so.preload"))


# =========================================================================== sistema
_ROOTKIT_MODULES = {"diamorphine", "reptile", "suterusu", "adore", "adore_ng", "knark", "kovid", "rootfoo",
                    "enyelkm", "phalanx", "azazel", "jynx", "nurupo", "khook", "brootus", "puszek", "vlany",
                    "bdvl", "beurk", "kbeast", "sutekh", "rkduck", "hiddenwasp"}
_SEC_DOMAINS = ("windowsupdate", "update.microsoft", "definitionupdates", "wdcp.microsoft", "clamav", "virustotal",
                "malwarebytes", "kaspersky", "eset", "avast", "avg.com", "bitdefender", "norton", "mcafee",
                "sophos", "f-secure", "trendmicro", "safebrowsing")
_PHISH_DOMAINS = ("google.", "microsoft.", "live.com", "outlook.", "facebook.", "paypal.", "apple.", "icloud.",
                  "amazon.", "github.", "steam", "discord", "instagram.", "whatsapp.", "netflix.", "cgd.pt",
                  "millenniumbcp", "novobanco", "santander", "bancobpi", "montepio", "creditoagricola", "bancoctt",
                  "activobank", "portaldasfinancas", "seg-social", "gov.pt")


def check_system(add) -> None:
    # ficheiro hosts
    hosts = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/drivers/etc/hosts" if IS_WIN \
        else Path("/etc/hosts")
    for line in _read(hosts).splitlines():
        s = line.split("#", 1)[0].split()
        if len(s) < 2:
            continue
        ip, names = s[0], [n.lower() for n in s[1:]]
        sink = ip in ("0.0.0.0", "127.0.0.1", "::1", "::", "0:0:0:0:0:0:0:0")
        for n in names:
            if n in ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback", "broadcasthost") \
                    or n.endswith(".local") or n.endswith(".localdomain"):
                continue
            if not sink and any(d in n for d in _PHISH_DOMAINS + _SEC_DOMAINS):
                add(Finding(BAD, "Sistema", f"Ficheiro hosts redireciona {n} para {ip}",
                            "Ao abrir este site vai parar a outro servidor — técnica usada para roubar "
                            "palavras-passe (phishing).", str(hosts)))
            elif sink and any(d in n for d in _SEC_DOMAINS):
                add(Finding(WARN, "Sistema", f"Ficheiro hosts bloqueia {n}",
                            "Bloquear sites de antivírus/atualizações é um truque de malware para não ser removido.",
                            str(hosts)))
    if IS_WIN:
        _win_system(add)
    else:
        _linux_system(add)


def _win_system(add) -> None:
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System") as k:
            if winreg.QueryValueEx(k, "EnableLUA")[0] == 0:
                add(Finding(WARN, "Sistema", "O Controlo de Conta de Utilizador (UAC) está desligado",
                            "Sem UAC qualquer programa ganha permissões de administrador sem perguntar."))
    except OSError:
        pass
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            try:
                pac = winreg.QueryValueEx(k, "AutoConfigURL")[0]
                if pac:
                    add(Finding(WARN, "Rede", "Proxy automático configurado",
                                f"Todo o tráfego web pode estar a passar por: {pac}\nSe não foi o seu trabalho "
                                "ou escola que configurou, é suspeito."))
            except OSError:
                pass
    except OSError:
        pass
    fw = ps_json("Get-NetFirewallProfile | Select-Object Name,Enabled", timeout=30)
    off = [f.get("Name") for f in as_list(fw) if isinstance(f, dict) and not f.get("Enabled")]
    if off:
        add(Finding(WARN, "Sistema", f"Firewall do Windows desligada ({', '.join(map(str, off))})",
                    "Sem firewall, o computador fica exposto na rede. Ative-a nas Definições do Windows."))
    pref = ps_json("Get-MpPreference | Select-Object ExclusionPath,ExclusionProcess,ExclusionExtension", timeout=30)
    if isinstance(pref, dict):
        ex = [str(x) for k in ("ExclusionPath", "ExclusionProcess", "ExclusionExtension")
              for x in as_list(pref.get(k)) if x and "N/A" not in str(x)]
        risky = [x for x in ex if re.fullmatch(r"[a-z]:\\?|\*|\.exe|exe|\.dll|.*\\(temp|appdata)\\?", x.lower())]
        if risky:
            add(Finding(BAD, "Antivírus", "O Defender tem exclusões perigosas",
                        "Estas exclusões fazem o Defender ignorar quase tudo — malware adiciona-as para se "
                        "esconder:\n" + "\n".join(risky)))
        elif ex:
            add(Finding(INFO, "Antivírus", f"O Defender ignora {len(ex)} pasta(s)/programa(s)",
                        "Confirme que reconhece estas exclusões:\n" + "\n".join(ex[:30])))


def _linux_system(add) -> None:
    mods = {ln.split()[0].lower() for ln in _read(Path("/proc/modules")).splitlines() if ln.strip()}
    try:
        mods |= {m.lower() for m in os.listdir("/sys/module")}
    except OSError:
        pass
    for m in sorted(mods & _ROOTKIT_MODULES):
        add(Finding(BAD, "Sistema", f"Módulo de rootkit conhecido carregado no kernel: {m}",
                    "Um rootkit esconde ficheiros e processos do próprio sistema. A forma segura de o remover "
                    "é reinstalar o sistema."))
    for line in _read(Path("/etc/passwd")).splitlines():
        f = line.split(":")
        if len(f) > 3 and f[2] == "0" and f[0] != "root":
            add(Finding(BAD, "Sistema", f"Conta com poderes de root: {f[0]}",
                        "Só a conta root deve ter UID 0. Uma conta extra com UID 0 é uma porta das traseiras.",
                        "/etc/passwd"))
    # chaves SSH que permitem entrar nesta conta
    ak = Path.home() / ".ssh/authorized_keys"
    keys = [ln for ln in _read(ak).splitlines() if ln.strip() and not ln.startswith("#")]
    if keys:
        add(Finding(INFO, "Sistema", f"{len(keys)} chave(s) SSH podem entrar nesta conta sem palavra-passe",
                    "Confirme que reconhece todas:\n" + "\n".join(k.split()[-1][:60] for k in keys[:20]), str(ak)))
    # programas SUID em pastas temporárias (dão root a quem os executar)
    for t in _temp_dirs():
        for root, dirs, files in _walk(t, 3):
            for fn in files:
                p = os.path.join(root, fn)
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and st.st_mode & stat.S_ISUID and st.st_uid == 0:
                    add(Finding(BAD, "Ficheiro", f"Programa SUID-root numa pasta temporária: {fn}",
                                "Qualquer pessoa que o execute fica com poderes de root — típico de quem já "
                                "invadiu o sistema.", p))


# =========================================================================== ficheiros
_RISKY_EXT = {".exe", ".scr", ".pif", ".com", ".bat", ".cmd", ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh",
              ".hta", ".ps1", ".lnk", ".jar", ".msi", ".dll", ".cpl", ".appimage", ".sh", ".desktop"}
_RARE_EXT = {".scr", ".pif", ".vbe", ".jse", ".wsf", ".wsh", ".hta", ".cpl"}  # quase nunca legítimos
_DOC_EXT = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".jpg", ".jpeg", ".png", ".gif", ".txt",
            ".mp3", ".mp4", ".avi", ".mkv", ".zip", ".rar", ".odt", ".rtf", ".csv", ".webp"}
_EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"
_SKIP_DIRS = {"node_modules", ".git", "__pycache__", ".cache", "site-packages", "dist-packages", ".venv", "venv",
              ".cargo", ".rustup", ".npm", ".gradle", ".m2", "steamapps", "Steam", ".wine", "drive_c",
              "AppData", "$Recycle.Bin", "System Volume Information", ".local/share/Trash", "proc", "sys"}


def _walk(top: str, max_depth: int):
    top = top.rstrip(os.sep) or os.sep
    base = top.count(os.sep)
    for root, dirs, files in os.walk(top, onerror=lambda e: None):
        if root.count(os.sep) - base >= max_depth:
            dirs[:] = []
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(("_MEI", ".mount_"))]
        yield root, dirs, files


def _user_dirs() -> dict[str, str]:
    home = Path.home()
    out = {}
    if IS_LINUX and which("xdg-user-dir"):
        for k in ("DOWNLOAD", "DESKTOP", "DOCUMENTS"):
            code, p = run(["xdg-user-dir", k], timeout=5)
            if code == 0 and p.strip() and Path(p.strip()) != home:
                out[k] = p.strip()
    for k, n in (("DOWNLOAD", "Downloads"), ("DESKTOP", "Desktop"), ("DOCUMENTS", "Documents")):
        out.setdefault(k, str(home / n))
    return {k: v for k, v in out.items() if os.path.isdir(v)}


def check_files(add, roots: list[tuple[str, int]], progress, cancelled, limit: int = 400_000) -> int:
    """Procura ficheiros suspeitos pelo nome/conteúdo. roots = [(pasta, profundidade)]. Devolve n.º visto."""
    n, last = 0, 0.0
    tmp = _temp_dirs()
    for top, depth in roots:
        for root, dirs, files in _walk(top, depth):
            if cancelled() or n >= limit:
                return n
            in_tmp = any(os.path.normcase(root).startswith(t) for t in tmp)
            for fn in files:
                n += 1
                p = os.path.join(root, fn)
                low = fn.lower()
                stem, ext = os.path.splitext(low)
                if "\u202e" in fn:
                    add(Finding(BAD, "Ficheiro", f"Nome com caracteres invertidos: {fn!r}",
                                "O carácter RTLO inverte o texto para esconder a extensão verdadeira "
                                "(ex.: \"fotogpj.exe\" aparece como \"fotoexe.jpg\").", p))
                    continue
                if ext in _RISKY_EXT and os.path.splitext(stem)[1] in _DOC_EXT:
                    add(Finding(BAD, "Ficheiro", f"Extensão dupla: {fn}",
                                "Parece um documento/imagem mas é um programa. Não o abra.", p))
                    continue
                if IS_WIN and ext in _RARE_EXT and not in_tmp:
                    add(Finding(WARN, "Ficheiro", f"Tipo de ficheiro quase sempre malicioso: {fn}",
                                f"Ficheiros {ext} raramente são legítimos fora do sistema.", p))
                try:
                    st = os.lstat(p)
                except OSError:
                    continue
                if not stat.S_ISREG(st.st_mode):
                    continue
                if 68 <= st.st_size <= 256:
                    try:
                        with open(p, "rb") as f:
                            if f.read(256).lstrip().startswith(_EICAR[:40]):
                                add(Finding(BAD, "Ficheiro", f"Ficheiro de teste EICAR: {fn}",
                                            "É o ficheiro de teste padrão dos antivírus (inofensivo). "
                                            "Se não foi criado por si, ponha-o em quarentena.", p))
                                continue
                    except OSError:
                        pass
                if not IS_WIN and in_tmp and st.st_mode & 0o111 and not _skip_tmp(p):
                    try:
                        with open(p, "rb") as f:
                            magic = f.read(4)
                    except OSError:
                        continue
                    if magic == b"\x7fELF":
                        hidden = fn.startswith(".") or "/." in root
                        add(Finding(BAD if hidden else WARN, "Ficheiro",
                                    f"Programa {'escondido ' if hidden else ''}numa pasta temporária: {fn}",
                                    "Malware para Linux costuma instalar-se em /tmp, /var/tmp ou /dev/shm. "
                                    "Se não reconhece o ficheiro, ponha-o em quarentena.", p))
            now = time.time()
            if progress and now - last > 0.25:
                last = now
                progress(None, f"{n:,} ficheiros · {root}".replace(",", "."))
    return n


def check_removable(add) -> None:
    try:
        parts = psutil.disk_partitions(all=False)
    except OSError:
        return
    for p in parts:
        mp = p.mountpoint
        rem = "removable" in (p.opts or "") if IS_WIN else mp.startswith(("/media/", "/run/media/"))
        if not rem:
            continue
        ar = Path(mp) / "autorun.inf"
        text = _read(ar, 8000).lower()
        if re.search(r"^\s*(open|shellexecute|shell\\[^=]*\\command)\s*=", text, re.M):
            add(Finding(WARN, "Ficheiro", f"autorun.inf numa pen/disco externo ({mp})",
                        "Executa um programa ao ligar a pen — técnica antiga de vírus de pens USB.", str(ar)))
