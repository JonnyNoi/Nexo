"""LibreHardwareMonitor no Windows: o Windows não expõe a temperatura da CPU, as rotações das ventoinhas
nem a maioria dos sensores da motherboard. O LHM (código aberto) lê-os e publica-os por WMI
(root/LibreHardwareMonitor), que o Nexo já sabe ler (core/sensors.py).

Aqui: transferir a versão oficial (fixa, com SHA-256 verificado), abri-la escondida na bandeja quando o
Nexo arranca e fechá-la quando o Nexo sai (se foi o Nexo que a abriu)."""
from __future__ import annotations

import hashlib
import subprocess
import urllib.request
import zipfile
from pathlib import Path

import psutil

from .util import APP_NAME, APP_VERSION, IS_WIN, config_dir

VERSION = "0.9.6"
URL = f"https://github.com/LibreHardwareMonitor/LibreHardwareMonitor/releases/download/v{VERSION}/LibreHardwareMonitor.zip"
SHA256 = "086d9f1b5a99e643edc2cfaaac16051685b551e4c5ac0b32a57c58c0e529c001"
EXE = "LibreHardwareMonitor.exe"
# definições do próprio LHM: arrancar minimizado, minimizar e fechar para a bandeja, servidor WMI ligado
_CONFIG = """<?xml version="1.0" encoding="utf-8"?>
<configuration>
  <appSettings>
    <add key="startMinMenuItem" value="true" />
    <add key="minTrayMenuItem" value="true" />
    <add key="minCloseMenuItem" value="true" />
    <add key="runWebServerMenuItem" value="false" />
  </appSettings>
</configuration>
"""
_started: subprocess.Popen | None = None


def folder() -> Path:
    return config_dir() / "ferramentas" / "LibreHardwareMonitor"


def exe_path() -> Path:
    return folder() / EXE


def installed() -> bool:
    return exe_path().is_file()


def running() -> bool:
    for p in psutil.process_iter(["name"]):
        if (p.info.get("name") or "").lower() == EXE.lower():
            return True
    return False


def _safe_extract(z: zipfile.ZipFile, dest: Path) -> None:
    root = dest.resolve()
    for m in z.infolist():
        target = (dest / m.filename).resolve()
        if root != target and root not in target.parents:
            raise RuntimeError(f"Caminho inválido dentro do ficheiro: {m.filename}")
    z.extractall(dest)


def install(progress=None) -> Path:
    """Transfere e instala na pasta de dados do Nexo (sem instalador, sem mexer no sistema)."""
    dest = folder()
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.parent / "lhm.zip.part"
    h = hashlib.sha256()
    req = urllib.request.Request(URL, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}"})
    got = 0
    with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:  # noqa: S310 (URL https fixa)
        total = int(r.headers.get("Content-Length") or 0)
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and total:
                progress(got / total)
    if h.hexdigest() != SHA256:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("O ficheiro transferido não corresponde ao LibreHardwareMonitor oficial (SHA-256). "
                           "Não foi instalado.")
    try:
        with zipfile.ZipFile(tmp) as z:
            _safe_extract(z, dest)
    finally:
        tmp.unlink(missing_ok=True)
    cfg = dest / "LibreHardwareMonitor.config"
    if not cfg.exists():
        cfg.write_text(_CONFIG, encoding="utf-8")
    if not exe_path().is_file():
        raise RuntimeError("A transferência não contém o LibreHardwareMonitor.exe.")
    return exe_path()


def start() -> bool:
    """Abre o LHM minimizado na bandeja (herda os privilégios de administrador do Nexo)."""
    global _started
    if not IS_WIN or not installed() or running():
        return False
    cfg = folder() / "LibreHardwareMonitor.config"
    if not cfg.exists():
        cfg.write_text(_CONFIG, encoding="utf-8")
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 7   # SW_SHOWMINNOACTIVE
    _started = subprocess.Popen([str(exe_path())], cwd=str(folder()), startupinfo=si,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return True


def stop_if_started() -> None:
    """Fecha o LHM se foi o Nexo que o abriu."""
    global _started
    if _started is not None and _started.poll() is None:
        try:
            _started.terminate()
        except OSError:
            pass
    _started = None


def remove() -> None:
    import shutil
    stop_if_started()
    if folder().exists():
        shutil.rmtree(folder(), ignore_errors=True)


def status_text() -> str:
    if not IS_WIN:
        return ""
    if running():
        return "O LibreHardwareMonitor está aberto — os sensores dele aparecem no Nexo."
    if installed():
        return "Instalado, mas não está aberto."
    return "Não instalado."

