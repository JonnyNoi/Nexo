"""Atualizações do próprio Nexo, a partir das releases do GitHub (UPDATE_REPO em util.py).

  • check() lê a última release (tag "v2.1" ou "2.1"), compara com APP_VERSION e devolve as novidades.
  • install() descarrega o executável deste sistema (Nexo / Nexo.exe), confirma o SHA-256 que o GitHub
    publica para o ficheiro e troca o executável:
      Linux   — substitui o ficheiro (um programa a correr pode ser substituído) e reinicia;
      Windows — o .exe a correr não pode ser apagado mas pode mudar de nome: Nexo.exe → Nexo.old.exe,
                o novo fica como Nexo.exe; o .old é apagado no arranque seguinte.
Só funciona no executável (PyInstaller). A correr a partir do código mostra a versão nova mas não instala."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from .util import APP_NAME, APP_VERSION, IS_WIN, UPDATE_REPO

API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class Release:
    version: str
    notes: str
    url: str              # página da release
    asset_url: str = ""
    asset_name: str = ""
    asset_size: int = 0
    sha256: str = ""


def configured() -> bool:
    return bool(re.fullmatch(r"[\w.-]+/[\w.-]+", UPDATE_REPO or ""))


def frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4]) or (0,)


def newer(remote: str, local: str = APP_VERSION) -> bool:
    return vt(remote) > vt(local)


def _get(url: str, timeout: float = 15):
    req = urllib.request.Request(url, headers={"User-Agent": f"{APP_NAME}/{APP_VERSION}",
                                               "Accept": "application/vnd.github+json"})
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310 (https fixo)


def parse_release(data: dict) -> Release:
    tag = str(data.get("tag_name") or "").lstrip("vV")
    want = "Nexo.exe" if IS_WIN else "Nexo"
    rel = Release(tag, (data.get("body") or "").strip(), data.get("html_url") or "")
    for a in data.get("assets") or []:
        if a.get("name") == want:
            rel.asset_url = a.get("browser_download_url") or ""
            rel.asset_name = want
            rel.asset_size = int(a.get("size") or 0)
            dig = a.get("digest") or ""
            if dig.startswith("sha256:"):
                rel.sha256 = dig[7:].lower()
    return rel


def check() -> Release | None:
    """Release mais recente se for mais nova do que esta versão; None se estiver atualizado."""
    if not configured():
        return None
    with _get(API.format(repo=UPDATE_REPO)) as r:
        rel = parse_release(json.loads(r.read().decode("utf-8", "replace")))
    return rel if rel.version and newer(rel.version) else None


def install(rel: Release, progress=None) -> Path:
    """Descarrega, verifica e troca o executável. Devolve o caminho do novo executável."""
    if not frozen():
        raise RuntimeError("A atualização automática só funciona no executável do Nexo (não a partir do código).")
    if not rel.asset_url:
        raise RuntimeError(f"A versão {rel.version} não tem o ficheiro {'Nexo.exe' if IS_WIN else 'Nexo'} para "
                           "este sistema. Transfira-a manualmente da página da versão.")
    if not rel.sha256:
        raise RuntimeError("A versão nova não tem soma de verificação (SHA-256) publicada — por segurança, "
                           "não é instalada automaticamente.")
    exe = Path(sys.executable).resolve()
    new = exe.with_name(exe.name + ".novo")
    h = hashlib.sha256()
    got = 0
    with _get(rel.asset_url, timeout=60) as r, open(new, "wb") as f:
        while chunk := r.read(256 * 1024):
            f.write(chunk)
            h.update(chunk)
            got += len(chunk)
            if progress and rel.asset_size:
                progress(got / rel.asset_size)
    if h.hexdigest() != rel.sha256:
        new.unlink(missing_ok=True)
        raise RuntimeError("O ficheiro transferido não corresponde à soma de verificação publicada. Não foi instalado.")
    if IS_WIN:
        old = exe.with_name(exe.stem + ".old" + exe.suffix)
        old.unlink(missing_ok=True)
        os.replace(exe, old)
        os.replace(new, exe)
    else:
        os.chmod(new, 0o755)
        os.replace(new, exe)
    return exe


def cleanup_old() -> None:
    """Apaga o executável antigo deixado por uma atualização no Windows."""
    if not (IS_WIN and frozen()):
        return
    exe = Path(sys.executable).resolve()
    for p in (exe.with_name(exe.stem + ".old" + exe.suffix), exe.with_name(exe.name + ".novo")):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
