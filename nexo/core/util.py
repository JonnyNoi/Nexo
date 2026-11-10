"""Utilitários partilhados entre Linux e Windows."""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import threading
from pathlib import Path

IS_WIN = sys.platform.startswith("win")
IS_LINUX = sys.platform.startswith("linux")

APP_NAME = "Nexo"
LEGACY_NAME = "PCForge"  # nome antigo (para migrar definições)
APP_VERSION = "2.1"
# repositório GitHub ("dono/nome") de onde o Nexo procura versões novas (releases com os ficheiros
# "Nexo" e "Nexo.exe"). Vazio = sem verificação de atualizações do próprio Nexo.
UPDATE_REPO = ""


class TaskCancelled(Exception):
    """Cancelamento pedido pelo utilizador: não é um erro (não vai para o nexo.log como ERROR)."""

# No Windows, evita que cada subprocesso abra uma janela de consola.
_NO_WINDOW = 0x08000000 if IS_WIN else 0


def config_dir() -> Path:
    if IS_WIN:
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    d = base / APP_NAME
    if not d.exists():
        legacy = base / LEGACY_NAME  # versões antigas chamavam-se PCForge: traz as definições
        if legacy.is_dir():
            import shutil as _sh
            try:
                _sh.copytree(legacy, d)
            except OSError:
                pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_json(name: str, default):
    p = config_dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception:  # noqa: BLE001 — ficheiro corrompido: guardar uma cópia antes que seja reescrito
        import logging
        logging.getLogger("nexo.config").warning("%s ilegível — copiado para %s.corrompido", name, name, exc_info=True)
        try:
            shutil.copy2(p, p.with_name(p.name + ".corrompido"))
        except OSError:
            pass
        return default


# várias threads (interface, testes de velocidade, antivírus…) gravam ficheiros de configuração
_save_lock = threading.RLock()


def save_json(name: str, data) -> None:
    """Grava de forma atómica: escreve num temporário único e só depois substitui o ficheiro."""
    p = config_dir() / name
    with _save_lock:
        text = json.dumps(data, indent=2, ensure_ascii=False)
        tmp = p.with_name(f".{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            tmp.write_text(text, encoding="utf-8")
            tmp.replace(p)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass


# ---------------------------------------------------------------- Definições
DEFAULT_SETTINGS = {
    "theme": "escuro",
    # aparência / fundo
    "wallpaper": "",             # imagem, GIF ou vídeo
    "accent_from_wallpaper": False,  # cor de destaque tirada do fundo
    "wp_auto": 0,                    # troca automática do fundo (minutos; 0 = desligada)
    "wp_auto_source": "local",       # "local" (os meus fundos) | "wallhaven"
    "wp_auto_last": 0,
    "alerts": True,          # avisar quando a CPU/GPU aquecem demais
    "alert_cpu": 90,
    "alert_gpu": 85,
    "alert_ram": True,       # avisar quando a RAM fica quase cheia durante 2 minutos
    "alert_ram_pct": 92,
    "alert_disk": True,      # avisar quando um disco fica com pouco espaço livre
    "alert_disk_pct": 10,    # % livre mínima
    "alert_smart": True,     # avisar quando a saúde de um disco (S.M.A.R.T.) piora
    "history": True,         # guardar o histórico dos sensores (média por minuto, 7 dias)
    "snapshot_before": True,  # criar ponto de restauro antes de alterar o sistema
    "snapshot_last": 0,
    "tray": True,            # ícone na bandeja do sistema
    "close_to_tray": False,  # fechar a janela deixa o Nexo a correr na bandeja
    "start_minimized": False,
    "remember_page": True,
    "page_fade": True,
    # modo jogo
    "game_detect": True,             # vigiar se há um jogo a correr
    "overlay_auto": True,            # mostrar o overlay quando um jogo arranca
    "overlay_pos": "top-left",
    "overlay_size": "detalhado",     # "detalhado" | "compacto"
    "overlay_opacity": 80,
    "overlay_items": ["game", "fps", "cpu", "gpu", "ram", "vram", "clock"],
    "game_processes": [],            # nomes de processos que o utilizador marcou como jogo
    "game_notify": True,             # avisar quando um jogo começa/acaba (com resumo da sessão)
    # limpeza automática (só categorias seguras e sem palavra-passe; ver core/autoclean.py)
    "auto_clean_days": 0,            # 0 = desligada; 7, 14 ou 30
    "auto_clean_last": 0,
    "auto_clean_freed": 0,           # total libertado desde que foi ligada (bytes)
    # atualizações do próprio Nexo
    "self_update_check": True,
    "self_update_last": 0,
    "self_update_skip": "",          # versão que o utilizador mandou ignorar
}
_settings: dict | None = None


def settings() -> dict:
    """Definições do utilizador (lidas uma vez e mantidas em memória)."""
    global _settings
    if _settings is not None:
        return _settings
    with _save_lock:
        if _settings is not None:
            return _settings
        data = load_json("settings.json", {})
        _settings = {**DEFAULT_SETTINGS, **(data if isinstance(data, dict) else {})}
        # versões antigas não tinham o contador de FPS: acrescenta-o uma vez à lista do overlay
        if not _settings.get("overlay_fps_added"):
            items = list(_settings.get("overlay_items") or [])
            if "fps" not in items:
                items.insert(1 if "game" in items else 0, "fps")
            _settings["overlay_items"], _settings["overlay_fps_added"] = items, True
    return _settings


def get_setting(key: str, default=None):
    return settings().get(key, DEFAULT_SETTINGS.get(key, default))


def set_setting(key: str, value) -> None:
    s = settings()
    with _save_lock:
        if s.get(key) == value:
            return
        s[key] = value
        try:
            save_json("settings.json", dict(s))
        except OSError:
            pass


def run(cmd: list[str] | str, timeout: float = 30, shell: bool = False) -> tuple[int, str]:
    """Executa um comando e devolve (código, stdout+stderr). Nunca lança exceção."""
    try:
        p = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, shell=shell,
            creationflags=_NO_WINDOW, encoding="utf-8", errors="replace",
        )
        out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
        return p.returncode, out.strip()
    except FileNotFoundError:
        return 127, f"comando não encontrado: {cmd if isinstance(cmd, str) else cmd[0]}"
    except subprocess.TimeoutExpired:
        return 124, "tempo esgotado"
    except Exception as e:  # noqa: BLE001
        return 1, str(e)


def read_text(path: str | Path, default: str = "") -> str:
    try:
        return Path(path).read_text(encoding="utf-8", errors="replace").strip()
    except (OSError, ValueError):  # sysfs/proc: ficheiros que desaparecem ou não se deixam ler são normais
        return default


def which(name: str) -> str | None:
    return shutil.which(name)


# ---------------------------------------------------------------- PowerShell
def run_ps(script: str, timeout: float = 60) -> tuple[int, str]:
    """Executa um script PowerShell (só Windows)."""
    exe = which("pwsh") or which("powershell") or "powershell"
    return run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                "-Command", "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + script],
               timeout=timeout)


def ps_json(script: str, timeout: float = 60):
    """Executa PowerShell e interpreta o resultado como JSON (usa ConvertTo-Json)."""
    code, out = run_ps(f"{script} | ConvertTo-Json -Depth 4 -Compress", timeout=timeout)
    if code != 0 or not out:
        return None
    try:
        # pode haver lixo antes do JSON (avisos); procura o primeiro { ou [
        i = min([x for x in (out.find("{"), out.find("[")) if x >= 0], default=0)
        return json.loads(out[i:])
    except ValueError:
        import logging
        logging.getLogger("nexo.ps").debug("Saída do PowerShell não é JSON: %.300s", out)
        return None


def as_list(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# ---------------------------------------------------------------- Privilégios
def is_admin() -> bool:
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except (OSError, AttributeError):
            return False
    return os.geteuid() == 0


def relaunch_as_admin() -> bool:
    """Windows: reabre o programa a pedir elevação (UAC). Devolve True se lançou."""
    if not IS_WIN:
        return False
    import ctypes
    if getattr(sys, "frozen", False):
        exe, params = sys.executable, " ".join(f'"{a}"' for a in sys.argv[1:])
    else:
        exe = sys.executable
        params = " ".join(f'"{a}"' for a in ["-m", "nexo", *sys.argv[1:]])
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, params, os.getcwd(), 1)
    return rc > 32


def run_root(shell_cmd: str, timeout: float = 300) -> tuple[int, str]:
    """Linux: executa um comando de shell como root (pkexec mostra o pedido de palavra-passe).
    Windows: executa no shell normal (as ações que precisam de admin verificam is_admin antes)."""
    if IS_WIN:
        return run(shell_cmd, timeout=timeout, shell=True)
    if os.geteuid() == 0:
        return run(["sh", "-c", shell_cmd], timeout=timeout)
    if which("pkexec"):
        return run(["pkexec", "sh", "-c", shell_cmd], timeout=timeout)
    return 126, "pkexec não está instalado; execute o Nexo como root para esta ação."


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _refuse_delete(path: str) -> bool:
    """Segunda barreira (além da interface): nunca apagar raízes de discos, a pasta pessoal
    inteira nem nada que as regras de segurança classifiquem como sistema."""
    real = os.path.realpath(path)
    if os.path.dirname(real) == real or real == os.path.realpath(os.path.expanduser("~")):
        return True
    from . import disksafety  # importação tardia: disksafety importa este módulo
    return any(disksafety.classify(x).level == disksafety.SYSTEM for x in {path, real})


def _win_force_delete(path: str) -> None:
    """Windows (já como administrador): toma posse, dá controlo total aos Administradores e apaga.
    Argumentos em lista, sem passar pela linha de comandos (nada de %VAR% ou & a ser interpretado)."""
    is_dir = os.path.isdir(path) and not os.path.islink(path)
    run(["takeown", "/F", path, "/A", *(["/R", "/D", "Y"] if is_dir else [])], timeout=600)
    run(["icacls", path, "/grant", "*S-1-5-32-544:F", "/C", "/Q", *(["/T"] if is_dir else [])], timeout=600)

    def _retry(func, p, _exc):
        try:
            os.chmod(p, 0o777)
            func(p)
        except OSError:
            pass
    try:
        if is_dir:
            shutil.rmtree(path, onerror=_retry)
        else:
            try:
                os.chmod(path, 0o777)
            except OSError:
                pass
            os.remove(path)
    except OSError:
        pass


def delete_as_admin(paths: list[str]) -> tuple[list[str], str]:
    """Apaga definitivamente ficheiros/pastas que precisam de privilégios.
    Linux: um único pedido de palavra-passe (pkexec) para todos. Windows: só funciona se o Nexo
    já estiver como administrador (toma posse e apaga). Devolve (apagados, mensagem de erro)."""
    paths = [p for p in paths if p and os.path.lexists(p)]
    refused = [p for p in paths if _refuse_delete(p)]
    paths = [p for p in paths if p not in refused]
    note = f"{len(refused)} itens de sistema foram recusados" if refused else ""
    if not paths:
        return [], note
    if IS_WIN:
        if not is_admin():
            return [], "admin"
        for p in paths:
            _win_force_delete(p)
        out = ""
    else:
        code, out = run_root("rm -rf -- " + " ".join(_sh_quote(p) for p in paths), timeout=900)
        if code in (126, 127) and all(os.path.lexists(p) for p in paths):
            return [], out or "Pedido de palavra-passe cancelado."
    done = [p for p in paths if not os.path.lexists(p)]
    err = "" if len(done) == len(paths) else (out[-300:] if out else "alguns itens continuam em uso")
    return done, "; ".join(x for x in (err, note) if x)


# ---------------------------------------------------------------- Formatação
def human_bytes(n: float, decimals: int = 1) -> str:
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.{decimals}f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def human_duration(seconds: float) -> str:
    seconds = int(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}min"
    if h:
        return f"{h}h {m}min"
    if m:
        return f"{m}min {s}s"
    return f"{s}s"


def os_label() -> str:
    if IS_WIN:
        return f"Windows {platform.release()}"
    rel = {}
    for line in read_text("/etc/os-release").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            rel[k] = v.strip('"')
    return rel.get("PRETTY_NAME") or f"Linux {platform.release()}"


def open_path(path: str | Path) -> None:
    """Abre um ficheiro/pasta no gestor de ficheiros do sistema."""
    path = str(path)
    if IS_WIN:
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606
    else:
        subprocess.Popen(["xdg-open", path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
