"""Antivírus: procura vírus e sinais de infeção no Windows e no Linux.

Duas camadas:
  1. Motor antivírus do sistema — Microsoft Defender (Windows) ou ClamAV (Linux) — para as assinaturas.
  2. Verificações próprias do Nexo (heurísticas): processos disfarçados, mineradores, persistência
     no arranque/cron/tarefas agendadas, ficheiro hosts sequestrado, ficheiros com extensão dupla,
     executáveis em pastas temporárias, rootkits conhecidos, etc.

Nada é apagado automaticamente: os ficheiros vão para uma quarentena e podem ser restaurados. Lá ficam
codificados com XOR e sem permissão de execução — isto NÃO é cifra (quem tiver acesso à pasta consegue
descodificá-los); serve só para que não possam ser executados nem apanhados por outros programas.
A integridade é confirmada por SHA-256 ao restaurar.
"""
from __future__ import annotations

import os
import queue
import re
import subprocess
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import psutil

from .util import IS_WIN, _NO_WINDOW, _save_lock, as_list, config_dir, load_json, ps_json, run, run_ps, run_root, save_json, which


from .av_checks import (_match, _temp_dirs, check_files, check_network, check_processes, check_removable,  # noqa: F401
                        check_startup, check_system, _user_dirs)
from .av_model import BAD, INFO, LEVEL_NAMES, LEVEL_ORDER, WARN, Finding, Report, _tail  # noqa: F401
from .av_quarantine import (_qdir, quarantine, quarantine_delete, quarantine_list,  # noqa: F401
                            quarantine_restore)


# =========================================================================== motor do sistema
@dataclass
class EngineStatus:
    name: str = ""              # "Microsoft Defender" | "ClamAV" | ""
    installed: bool = False
    active: bool = False        # proteção em tempo real ligada (Windows) / pronto a usar (Linux)
    signatures: str = ""        # data/versão das assinaturas
    note: str = ""
    others: list[str] = field(default_factory=list)  # outros antivírus registados (Windows)
    can_install: bool = False


def _defender_exe() -> str | None:
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),):
        p = Path(base) / "Windows Defender" / "MpCmdRun.exe"
        if p.exists():
            return str(p)
    plat = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft" / "Windows Defender" / "Platform"
    try:
        vers = sorted(plat.iterdir(), reverse=True)
        for v in vers:
            if (v / "MpCmdRun.exe").exists():
                return str(v / "MpCmdRun.exe")
    except OSError:
        pass
    return None


def _clam_bin() -> str | None:
    return which("clamscan")


def _pkg_manager() -> str | None:
    for pm in ("pacman", "apt-get", "dnf", "zypper"):
        if which(pm):
            return pm
    return None


def engine_status() -> EngineStatus:
    st = EngineStatus()
    if IS_WIN:
        st.name = "Microsoft Defender"
        others = ps_json("Get-CimInstance -Namespace root/SecurityCenter2 -ClassName AntivirusProduct "
                         "| Select-Object displayName", timeout=30)
        st.others = [o.get("displayName", "") for o in as_list(others)
                     if o and "defender" not in str(o.get("displayName", "")).lower()]
        s = ps_json("Get-MpComputerStatus | Select-Object AntivirusEnabled,RealTimeProtectionEnabled,"
                    "AMRunningMode,@{n='Sig';e={$_.AntivirusSignatureLastUpdated.ToString('yyyy-MM-dd HH:mm')}},"
                    "AntivirusSignatureVersion", timeout=40)
        st.installed = bool(_defender_exe())
        if isinstance(s, dict):
            st.active = bool(s.get("AntivirusEnabled")) and bool(s.get("RealTimeProtectionEnabled"))
            st.signatures = f"{s.get('Sig') or '?'} (v{s.get('AntivirusSignatureVersion') or '?'})"
            mode = str(s.get("AMRunningMode") or "")
            if not s.get("AntivirusEnabled") or mode.lower() in ("passive mode", "not running", "sidebyside passive"):
                st.note = ("O Defender está em modo passivo/desligado"
                           + (f" — o antivírus ativo é: {', '.join(st.others)}." if st.others else "."))
            elif not s.get("RealTimeProtectionEnabled"):
                st.note = "A proteção em tempo real está DESLIGADA."
        elif not st.installed:
            st.note = "O Microsoft Defender não foi encontrado."
        else:
            st.note = "Não foi possível ler o estado do Defender (experimente executar como administrador)."
        return st

    st.name = "ClamAV"
    exe = _clam_bin()
    st.installed = bool(exe)
    if not exe:
        st.can_install = bool(_pkg_manager())
        st.note = ("O ClamAV não está instalado — sem ele só correm as verificações próprias do Nexo "
                   "(processos, arranque, rootkits, ficheiros suspeitos).")
        return st
    code, out = run([exe, "--version"], timeout=30)
    # "ClamAV 1.4.1/27450/Tue Nov  4 08:24:01 2026"
    parts = out.strip().split("/")
    if len(parts) >= 3:
        st.signatures = f"{parts[2].strip()} (base {parts[1].strip()})"
        st.active = True
    else:
        st.note = "O ClamAV não tem assinaturas — carregue em \"Atualizar assinaturas\"."
    return st


def update_signatures() -> tuple[bool, str]:
    if IS_WIN:
        exe = _defender_exe()
        if not exe:
            return False, "Microsoft Defender não encontrado."
        code, out = run([exe, "-SignatureUpdate"], timeout=900)
        return code == 0, "Assinaturas atualizadas." if code == 0 else _tail(out)
    if not which("freshclam"):
        return False, "O freshclam não está instalado (vem com o ClamAV)."
    code, out = run_root(["freshclam"], timeout=900)
    if code == 0:
        return True, "Assinaturas do ClamAV atualizadas."
    if "locked by another process" in out or "lock" in out.lower():
        return True, "O serviço clamav-freshclam já está a atualizar as assinaturas automaticamente."
    return False, _tail(out)


def install_engine() -> tuple[bool, str]:
    """Linux: instala o ClamAV com o gestor de pacotes e descarrega as assinaturas."""
    if IS_WIN:
        return False, "No Windows o Microsoft Defender já vem instalado."
    cmds = {"pacman": "pacman -S --noconfirm --needed clamav",
            "apt-get": "DEBIAN_FRONTEND=noninteractive apt-get install -y clamav clamav-freshclam",
            "dnf": "dnf install -y clamav clamav-update",
            "zypper": "zypper -n install clamav"}
    pm = _pkg_manager()
    if not pm:
        return False, "Gestor de pacotes não reconhecido — instale o pacote \"clamav\" manualmente."
    code, out = run_root(f"{cmds[pm]} && (freshclam || true)", timeout=1800)
    if code != 0 or not _clam_bin():
        return False, _tail(out)
    return True, "ClamAV instalado e assinaturas descarregadas."


# =========================================================================== execução com cancelamento
def _stream(cmd: list[str], on_line, cancelled, timeout: float) -> tuple[int, bool]:
    """Executa cmd lendo stdout linha a linha. Devolve (código, cancelado).
    Para cancelar fecha o pipe: funciona mesmo com processos de root (morrem com SIGPIPE)."""
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                             text=True, encoding="utf-8", errors="replace", creationflags=_NO_WINDOW)
    except OSError as e:
        on_line(f"__erro__ {e}")
        return 127, False
    q: queue.Queue = queue.Queue()

    def reader():
        try:
            for line in p.stdout:
                q.put(line.rstrip("\n"))
        except (OSError, ValueError):
            pass
        q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    t0 = time.time()
    while True:
        if cancelled() or time.time() - t0 > timeout:
            try:
                p.terminate()
            except OSError:
                pass
            try:
                p.stdout.close()
            except OSError:
                pass
            try:
                p.wait(5)
            except subprocess.TimeoutExpired:
                pass
            return -1, True
        try:
            line = q.get(timeout=0.25)
        except queue.Empty:
            on_line(None)  # batimento (atualiza o tempo decorrido)
            continue
        if line is None:
            break
        on_line(line)
    return p.wait(), False


# =========================================================================== análise com o motor
def _engine_scan(mode: str, target: str, add, progress, cancelled, report: Report) -> None:
    if IS_WIN:
        _defender_scan(mode, target, add, progress, cancelled, report)
    else:
        _clam_scan(mode, target, add, progress, cancelled, report)


def _defender_scan(mode, target, add, progress, cancelled, report) -> None:
    exe = _defender_exe()
    if not exe:
        report.engine_note = "Microsoft Defender não encontrado — só correram as verificações do Nexo."
        return
    report.engine = "Microsoft Defender"
    st = {"quick": "1", "full": "2", "folder": "3"}[mode]
    cmd = [exe, "-Scan", "-ScanType", st] + (["-File", target] if mode == "folder" else [])
    t0 = time.time()
    label = {"quick": "análise rápida", "full": "análise completa (pode demorar horas)", "folder": "análise da pasta"}

    def on_line(_line):
        progress(None, f"Microsoft Defender: {label[mode]} — {int(time.time() - t0) // 60} min "
                       f"{int(time.time() - t0) % 60:02d} s")

    code, canc = _stream(cmd, on_line, cancelled, timeout=12 * 3600)
    if canc:
        report.cancelled = True
        run([exe, "-Scan", "-Cancel"], timeout=30)
        return
    if code not in (0, 2):
        report.engine_note = (f"O Defender devolveu o código {code} — pode estar desligado ou ser preciso "
                              "executar o Nexo como administrador.")
    minutes = int((time.time() - t0) / 60) + 2
    script = ("$t=@{}; Get-MpThreat -ErrorAction SilentlyContinue | ForEach-Object { $t[[string]$_.ThreatID]=$_ }; "
              "Get-MpThreatDetection -ErrorAction SilentlyContinue | Where-Object { "
              f"$_.InitialDetectionTime -ge (Get-Date).AddMinutes(-{minutes}) -or "
              "($t[[string]$_.ThreatID] -and $t[[string]$_.ThreatID].IsActive) } | ForEach-Object { "
              "$x=$t[[string]$_.ThreatID]; [pscustomobject]@{Id=[string]$_.ThreatID; "
              "Name=[string]$x.ThreatName; Res=(@($_.Resources) -join ' | '); S=[int]$_.ThreatStatusID; "
              "Act=[bool]$x.IsActive} }")
    status = {1: "detetada", 2: "limpa", 3: "em quarentena", 4: "removida", 5: "permitida",
              6: "bloqueada", 102: "falhou a limpeza", 103: "falhou a quarentena", 104: "falhou a remoção",
              105: "falhou permitir", 106: "abandonada", 107: "falhou bloquear"}
    seen = set()
    for d in as_list(ps_json(script, timeout=120)):
        if not isinstance(d, dict) or (d.get("Id"), d.get("Res")) in seen:
            continue
        seen.add((d.get("Id"), d.get("Res")))
        res = re.sub(r"^\w+:_", "", str(d.get("Res") or "")).split(" | ")[0]
        s = status.get(d.get("S"), f"estado {d.get('S')}")
        active = d.get("Act") or d.get("S") in (1, 5, 102, 103, 104, 106)
        add(Finding(BAD if active else INFO, "Antivírus", f"{d.get('Name') or 'Ameaça'} — {s}",
                    ("O Defender detetou esta ameaça e ainda NÃO a removeu. Use \"Remover com o Defender\"."
                     if active else "O Defender já tratou desta ameaça.") + f"\nRecurso: {d.get('Res')}",
                    res, engine="defender"))


def _clam_scan(mode, target, add, progress, cancelled, report) -> None:
    exe = _clam_bin()
    if not exe:
        report.engine_note = ("O ClamAV não está instalado — só correram as verificações do Nexo. "
                              "Instale-o no cartão \"Proteção\" para procurar vírus por assinatura.")
        return
    report.engine = "ClamAV"
    args = [exe, "-r", "--stdout", "--no-summary", "--max-filesize=200M", "--max-scansize=400M",
            "--cross-fs=yes"]
    listfile = None
    as_root = False
    if mode == "full":
        for ex in ("/proc", "/sys", "/dev", "/run", "/var/lib/clamav", "/var/lib/docker/overlay2",
                   "/var/lib/containers", "/var/cache/pacman", "/var/cache/apt", "/snap", "/var/lib/flatpak/repo"):
            args.append(f"--exclude-dir=^{re.escape(ex)}")
        args.append("--exclude-dir=/\\.mount_")
        args.append("/")
        as_root = os.geteuid() != 0 and bool(which("pkexec"))
    else:
        paths: list[str] = []
        if mode == "folder":
            paths = [target]
        else:
            home = Path.home()
            paths = list(_user_dirs().values()) + [str(home / ".local/bin"), str(home / "bin"),
                                                   str(home / ".config/autostart"), "/tmp", "/var/tmp", "/dev/shm"]
            for p in psutil.process_iter(["exe"]):  # programas a correr agora
                try:
                    e = p.info["exe"]
                    if e and os.path.isfile(e):
                        paths.append(e)
                except (psutil.Error, OSError):
                    pass
        paths = sorted({p for p in paths if os.path.exists(p)})
        listfile = config_dir() / "av_lista.txt"
        listfile.write_text("\n".join(paths), encoding="utf-8")
        args.append(f"--file-list={listfile}")
    if as_root:
        args = ["pkexec", *args]
    found_db_error = {"x": False}

    def on_line(line):
        if line is None:
            return
        if line.startswith("__erro__"):
            report.engine_note = line[9:]
            return
        if "No supported database" in line or "cl_load" in line:
            found_db_error["x"] = True
            return
        if line.endswith(" FOUND") and ": " in line:
            path, sig = line[:-6].rsplit(": ", 1)
            add(Finding(BAD, "Ficheiro", f"{sig} — {os.path.basename(path)}",
                        f"O ClamAV identificou este ficheiro como malicioso ({sig}).", path))
        elif line.endswith(": OK"):
            report.files_scanned += 1
            if report.files_scanned % 25 == 0:
                progress(None, f"ClamAV: {report.files_scanned:,} ficheiros · {line[:-4]}".replace(",", "."))

    progress(None, "ClamAV: a carregar as assinaturas (demora uns segundos)…" +
             (" — confirme a palavra-passe de administrador" if as_root else ""))
    code, canc = _stream(args, on_line, cancelled, timeout=24 * 3600)
    if listfile:
        try:
            listfile.unlink()
        except OSError:
            pass
    if canc:
        report.cancelled = True
    elif found_db_error["x"] or (code == 2 and report.files_scanned == 0):
        report.engine_note = ("O ClamAV não conseguiu correr — normalmente faltam as assinaturas. "
                              "Carregue em \"Atualizar assinaturas\".") if code != 126 else \
            "A autorização de administrador foi recusada — a análise do ClamAV não correu."


# =========================================================================== análise completa
def scan(mode: str = "quick", target: str = "", use_engine: bool = True, progress=None,
         cancelled=lambda: False) -> Report:
    """mode: quick | full | folder. progress(fração 0–1 ou None, texto)."""
    progress = progress or (lambda *_a: None)
    rep = Report(mode, started=time.time())
    ignored = set(load_json("av_ignorar.json", []))
    keys = set()

    def add(f: Finding):
        if f.key in keys:
            return
        keys.add(f.key)
        if f.key in ignored:
            rep.ignored += 1
            return
        rep.findings.append(f)

    if mode == "folder":
        steps = [("Ficheiros da pasta", lambda: _files_step(add, [(target, 64)]))]
    else:
        ud = _user_dirs()
        if mode == "full":
            roots = [(str(Path.home()), 64)] + [(t, 6) for t in _temp_dirs()]
        else:
            roots = [(p, 4) for p in ud.values()] + [(t, 3) for t in _temp_dirs()]
        steps = [("Processos em execução", lambda: check_processes(add)),
                 ("Ligações de rede", lambda: check_network(add)),
                 ("Programas de arranque e tarefas agendadas", lambda: check_startup(add)),
                 ("Definições de segurança do sistema", lambda: check_system(add)),
                 ("Pens e discos externos", lambda: check_removable(add)),
                 ("Ficheiros suspeitos", lambda: _files_step(add, roots))]
    if use_engine:
        steps.append(("Motor antivírus", lambda: _engine_scan(mode, target, add, sub, cancelled, rep)))

    state = {"i": 0}

    def sub(_frac, text):
        progress(state["i"] / len(steps), text)

    def _files_step(add_, roots_):
        rep.files_scanned += check_files(add_, roots_, sub, cancelled)

    for i, (name, fn) in enumerate(steps):
        if cancelled():
            rep.cancelled = True
            break
        state["i"] = i
        progress(i / len(steps), f"{name}…")
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            rep.findings.append(Finding(INFO, "Sistema", f"Não foi possível verificar: {name}", str(e)))
    rep.cancelled = rep.cancelled or cancelled()
    rep.findings.sort(key=lambda f: (LEVEL_ORDER.index(f.level), f.category, f.title))
    rep.duration = time.time() - rep.started
    progress(1.0, "Concluído")
    from .util import set_setting
    set_setting("av_last_scan", {"when": rep.started, "mode": mode, "bad": rep.count(BAD),
                                 "warn": rep.count(WARN), "cancelled": rep.cancelled})
    return rep


# =========================================================================== ações
def ignore(f: Finding) -> None:
    with _save_lock:
        lst = load_json("av_ignorar.json", [])
        if f.key not in lst:
            lst.append(f.key)
            save_json("av_ignorar.json", lst)


def clear_ignored() -> int:
    n = len(load_json("av_ignorar.json", []))
    save_json("av_ignorar.json", [])
    return n


def kill_process(pid: int) -> tuple[bool, str]:
    try:
        p = psutil.Process(pid)
        name = p.name()
        p.kill()
        return True, f"Processo {name} (PID {pid}) terminado."
    except psutil.NoSuchProcess:
        return True, "O processo já tinha terminado."
    except psutil.AccessDenied:
        if not IS_WIN:
            code, out = run_root(["kill", "-9", str(int(pid))], timeout=60)
            return code == 0, "Processo terminado." if code == 0 else _tail(out)
        return False, "Sem permissão — execute o Nexo como administrador."


def defender_remove() -> tuple[bool, str]:
    code, out = run_ps("Remove-MpThreat", timeout=600)
    return code == 0, "O Defender removeu as ameaças ativas." if code == 0 else _tail(out)


def finding_dict(f: Finding) -> dict:
    return asdict(f)
