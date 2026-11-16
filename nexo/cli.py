"""Linha de comandos: usar o Nexo sem abrir a janela (scripts, SSH, tarefas do sistema).

    nexo --saude [--json]            pontuação da Saúde do PC e o que fazer
    nexo --limpar                    limpeza segura (só o que é 100 % seguro e sem palavra-passe)
    nexo --relatorio FICHEIRO        relatório do sistema (.html ou .json)
    nexo --relatorio-semanal [FICH]  relatório da semana (texto; .html se indicar ficheiro)
    nexo --bateria                   saúde da bateria
    nexo --arranque                  tempo do último arranque e o que o atrasou
    nexo --versao | --ajuda

Código de saída de --saude: 0 = bom (≥ 75), 1 = precisa de atenção, 2 = mau (< 50)."""
from __future__ import annotations

import json
import sys

COMMANDS = ("--saude", "--limpar", "--relatorio", "--relatorio-semanal", "--bateria", "--arranque", "--versao",
            "--ajuda", "--help", "--version", "-h")


def wants_cli(argv: list[str]) -> bool:
    return any(a in COMMANDS for a in argv[1:])


def _attach_console() -> None:
    """Windows: o Nexo.exe é uma aplicação de janela — liga-se à consola de onde foi chamado para o print aparecer."""
    if not sys.platform.startswith("win") or not getattr(sys, "frozen", False):
        return
    try:
        import ctypes
        if ctypes.windll.kernel32.AttachConsole(-1):
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")  # noqa: SIM115
            sys.stderr = sys.stdout
    except (OSError, AttributeError):
        pass


def _arg_after(argv: list[str], flag: str) -> str | None:
    try:
        v = argv[argv.index(flag) + 1]
    except (ValueError, IndexError):
        return None
    return None if v.startswith("--") else v


def health_checks() -> list:
    """As verificações da Saúde do PC que não precisam da janela (sem sensores ao vivo)."""
    import os
    import time

    import psutil

    from .core import healthscore, smart
    from .core.healthscore import Check
    from .core.util import human_bytes, human_duration
    out: list[Check] = []
    vm = psutil.virtual_memory()
    if vm.percent >= 90:
        out.append(Check("warn", f"Memória RAM quase cheia ({vm.percent:.0f}%).", "Processos"))
    root = os.environ.get("SystemDrive", "C:") + "\\" if sys.platform.startswith("win") else "/"
    try:
        du = psutil.disk_usage(root)
        free_pct = 100 - du.percent
        if free_pct < 10:
            out.append(Check("bad", f"Disco do sistema quase cheio ({human_bytes(du.free)} livres).", "Espaço em disco"))
        elif free_pct < 20:
            out.append(Check("warn", f"Pouco espaço no disco do sistema ({human_bytes(du.free)} livres).",
                             "Espaço em disco"))
    except OSError:
        pass
    up = time.time() - psutil.boot_time()
    if up > 7 * 86400:
        out.append(Check("warn", f"Ligado há {human_duration(up)} — reiniciar aplica atualizações."))
    for d in (smart.cached() or {}).get("disks", []):
        if d.get("verdict") in ("bad", "warn"):
            why = next((t for k, t in d.get("reasons", []) if k == d["verdict"]), "")
            out.append(Check(d["verdict"], f"Disco {d.get('model', '')}: {why}", "Saúde dos discos"))
    out += healthscore.slow_checks()
    return out


def cmd_health(as_json: bool) -> int:
    from .core import healthscore
    checks = health_checks()
    s = healthscore.score(checks)
    txt, _kind = healthscore.grade(s)
    if as_json:
        print(json.dumps({"score": s, "grade": txt, "checks": [c.__dict__ for c in checks]}, ensure_ascii=False,
                         indent=2))
    else:
        print(f"Saúde do PC: {s}/100 — {txt}")
        sym = {"ok": "✓", "warn": "!", "bad": "✗"}
        for c in sorted(checks, key=lambda c: {"bad": 0, "warn": 1, "ok": 2}[c.kind]):
            where = f"  → {c.page}" if c.page and c.kind != "ok" else ""
            print(f" {sym[c.kind]} {c.text}{where}")
    return 0 if s >= 75 else (1 if s >= 50 else 2)


def cmd_clean() -> int:
    from .core import autoclean
    from .core.util import human_bytes
    cats = autoclean.categories()
    print(f"A limpar ({', '.join(c.name for c in cats)})…")
    freed, msg = autoclean.run()
    print(msg if freed else "Não havia nada para limpar.")
    if freed:
        from .core import changes
        changes.mark("limpeza", f"Limpeza pela linha de comandos ({human_bytes(freed)})")
    return 0


def cmd_report(path: str | None) -> int:
    if not path:
        print("Indique o ficheiro: nexo --relatorio relatorio.html (ou .json)", file=sys.stderr)
        return 64
    from .core import sysinfo
    data = sysinfo.collect()
    text = sysinfo.report_json(data) if path.lower().endswith(".json") else sysinfo.report_html(data)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"Relatório guardado em {path}")
    return 0


def cmd_weekly(path: str | None) -> int:
    from .core import weekly
    rep = weekly.build()
    if path:
        with open(path, "w", encoding="utf-8") as f:
            f.write(weekly.to_html(rep))
        print(f"Relatório da semana guardado em {path}")
    else:
        print(weekly.to_text(rep))
    return 0


def cmd_battery() -> int:
    from .core import battery
    bats = battery.batteries()
    if not bats:
        print("Sem bateria (PC de secretária).")
        return 0
    for b in bats:
        h = b.health_pct
        print(f"{' '.join(x for x in (b.manufacturer, b.model) if x) or b.name}")
        if h is not None:
            print(f"  Saúde: {h:.0f} % ({b.full:.1f} de {b.design:.1f} {b.unit})")
        if b.cycles:
            print(f"  Ciclos: {b.cycles}")
        if b.percent is not None:
            print(f"  Carga: {b.percent:.0f} % {b.status}".rstrip())
        print(f"  {b.verdict()[1]}")
    return 0


def cmd_boot() -> int:
    from .core import boottime
    b = boottime.record()
    if b is None:
        print("Tempo de arranque indisponível" + (" (precisa de administrador)." if sys.platform.startswith("win")
                                                   else " (o arranque ainda não terminou?)."))
        return 1
    tr = boottime.trend()
    print(f"Último arranque: {tr.text() if tr else f'{b.total:.1f} s'}")
    for k, v in b.phases.items():
        print(f"  {boottime.PHASE_NAMES.get(k, k)}: {v:.1f} s")
    if b.delays:
        print("O que atrasou:")
        for d in b.delays[:8]:
            print(f"  {d.seconds:6.2f} s  {d.name}")
    for kind, text in boottime.advice(b):
        if kind != "ok":
            print(f" ! {text}")
    return 0


def main(argv: list[str]) -> int:
    _attach_console()
    from .core import log as nlog
    nlog.setup("cli")
    from .core.util import APP_NAME, APP_VERSION
    a = argv[1:]
    try:
        if "--versao" in a or "--version" in a:
            print(f"{APP_NAME} {APP_VERSION}")
            return 0
        if "--ajuda" in a or "--help" in a or "-h" in a:
            print(__doc__)
            return 0
        if "--saude" in a:
            return cmd_health("--json" in a)
        if "--limpar" in a:
            return cmd_clean()
        if "--relatorio-semanal" in a:
            return cmd_weekly(_arg_after(argv, "--relatorio-semanal"))
        if "--relatorio" in a:
            return cmd_report(_arg_after(argv, "--relatorio"))
        if "--bateria" in a:
            return cmd_battery()
        if "--arranque" in a:
            return cmd_boot()
    except KeyboardInterrupt:
        return 130
    print(__doc__)
    return 64
