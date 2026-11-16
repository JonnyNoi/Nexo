"""Registo de erros: ficheiro nexo.log (rotativo) na pasta de dados e captura de exceções não tratadas.

- `setup()` é chamado logo no arranque (também no processo do overlay, com outro ficheiro).
- Exceções não tratadas (thread principal, slots do Qt e threads) ficam no registo com o traceback.
- Falhas graves do interpretador (segfault no Qt, etc.) ficam em nexo-crash.log via faulthandler.
- A interface regista `set_error_handler()` para mostrar uma janela ao utilizador.
"""
from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import platform
import sys
import threading
import traceback

from .util import APP_NAME, APP_VERSION, config_dir

log = logging.getLogger("nexo")
_handler = None          # fn(titulo, detalhes) chamada na thread principal
_crash_file = None       # mantido aberto para o faulthandler
_log_path = None


def log_path():
    return _log_path or (config_dir() / "nexo.log")


def setup(name: str = "nexo") -> None:
    global _crash_file, _log_path
    d = config_dir()
    _log_path = d / f"{name}.log"
    root = logging.getLogger()
    if any(getattr(h, "_nexo", False) for h in root.handlers):
        return
    root.setLevel(logging.INFO)
    try:
        fh = logging.handlers.RotatingFileHandler(_log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s"))
        fh._nexo = True
        root.addHandler(fh)
    except OSError:
        pass
    if sys.stderr is not None:  # no .exe sem consola o stderr é None
        sh = logging.StreamHandler(sys.stderr)
        sh.setLevel(logging.WARNING)
        sh.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        sh._nexo = True
        root.addHandler(sh)

    try:
        crash = d / f"{name}-crash.log"
        if crash.exists() and crash.stat().st_size > 512_000:
            crash.write_text("", encoding="utf-8")
        _crash_file = open(crash, "a", encoding="utf-8")  # noqa: SIM115 — fica aberto até ao fim
        faulthandler.enable(_crash_file)
    except (OSError, RuntimeError, ValueError):
        pass

    sys.excepthook = _excepthook
    threading.excepthook = _thread_excepthook
    log.info("%s %s a arrancar · %s %s · Python %s%s", APP_NAME, APP_VERSION, platform.system(), platform.release(),
             platform.python_version(), " · executável" if getattr(sys, "frozen", False) else "")


def set_error_handler(fn) -> None:
    """fn(resumo: str, detalhes: str) — chamado na thread principal para exceções não tratadas."""
    global _handler
    _handler = fn


def _excepthook(etype, value, tb):
    if issubclass(etype, KeyboardInterrupt):
        sys.__excepthook__(etype, value, tb)
        return
    details = "".join(traceback.format_exception(etype, value, tb))
    log.error("Erro não tratado:\n%s", details.rstrip())
    if _handler is not None:
        try:
            _handler(f"{etype.__name__}: {value}", details)
        except Exception:  # noqa: BLE001 — nunca deixar o próprio aviso rebentar
            log.exception("Falha ao mostrar o aviso de erro")


def _thread_excepthook(args):
    if args.exc_type is SystemExit:
        return
    details = "".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback))
    name = args.thread.name if args.thread else "?"
    log.error("Erro não tratado na thread %s:\n%s", name, details.rstrip())


def system_summary() -> str:
    return (f"{APP_NAME} {APP_VERSION} · {platform.system()} {platform.release()} ({platform.machine()}) · "
            f"Python {platform.python_version()}" + (" · executável" if getattr(sys, "frozen", False) else ""))


def diagnostic_report(n: int = 150) -> str:
    """Texto para colar num relatório de problema: versão, sistema, últimas linhas do registo e da
    última falha grave. Os caminhos da pasta pessoal ficam como ~ (não expõe o nome de utilizador)."""
    import os
    parts = [system_summary(), "", f"--- últimas {n} linhas do registo ---", tail(n) or "(registo vazio)"]
    crash = log_path().with_name(log_path().stem + "-crash.log")
    try:
        c = crash.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        c = ""
    if c:
        parts += ["", "--- última falha grave ---", "\n".join(c.splitlines()[-60:])]
    text = "\n".join(parts)
    home = os.path.expanduser("~")
    return text.replace(home, "~") if len(home) > 1 else text


def tail(n: int = 200) -> str:
    try:
        lines = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-n:])
