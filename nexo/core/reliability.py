"""Fiabilidade: o histórico do que correu mal no PC (crashes, desligares sem aviso, erros de hardware…).

Linux (sem palavra-passe — o journal do sistema é legível pelo grupo wheel/adm/systemd-journal; se não
for, só aparecem os eventos do próprio utilizador e a página avisa):
  • arranques que acabaram sem o registo normal de encerramento → desligou-se sem aviso / bloqueou;
  • mensagens do kernel: reinícios do controlador gráfico (amdgpu/i915/nouveau, Xid da NVIDIA), erros de
    hardware (MCE), OOM killer, oops/BUG/soft lockup, erros de E/S nos discos, temperatura crítica;
  • programas que fecharam com erro (coredumpctl).
Windows (Get-WinEvent, sem administrador):
  • Kernel-Power 41 / EventLog 6008 (desligou-se sem aviso), BugCheck 1001 (ecrã azul), WHEA-Logger,
    Display 4101 / nvlddmkm / amdkmdag (controlador gráfico), Resource-Exhaustion 2004 (memória),
    disk/Ntfs (erros de disco) e Application Error 1000 (programas que fecharam com erro).

O resultado fica em config_dir()/fiabilidade.json (lido pela Saúde do PC sem voltar a perguntar ao sistema).
As funções de análise (classify_kernel, parse_windows, unclean_boots) são puras para poderem ser testadas.
"""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass

from .util import IS_LINUX, IS_WIN, load_json, run, save_json, which

CACHE = "fiabilidade.json"
DAYS = 30


@dataclass
class Event:
    when: float
    cat: str           # shutdown | crash | gpu | hardware | memory | disk | thermal | app
    title: str
    detail: str = ""
    count: int = 1

    @property
    def kind(self) -> str:
        return CATEGORIES[self.cat][1]


# categoria → (nome, gravidade, explicação/conselho)
CATEGORIES: dict[str, tuple[str, str, str]] = {
    "shutdown": ("Desligou-se sem aviso", "bad",
                 "O PC reiniciou ou desligou-se sem encerrar normalmente (corte de luz, botão, bloqueio total). "
                 "Se acontece sem ter carregado no botão: verifique temperaturas (Stress test), a fonte de "
                 "alimentação e overclocks/XMP instáveis."),
    "crash": ("Falha do sistema", "bad",
              "O núcleo do sistema parou (ecrã azul no Windows, kernel panic/oops no Linux). Causas comuns: "
              "controladores, memória RAM instável (XMP/overclock) ou hardware com defeito."),
    "gpu": ("Controlador gráfico", "warn",
            "A placa gráfica deixou de responder e o controlador teve de a reiniciar (ecrã preto, jogo fechado). "
            "Atualize os drivers; se repetir com temperaturas normais, retire overclocks/undervolts da GPU."),
    "hardware": ("Erro de hardware", "bad",
                 "O processador ou a memória comunicou um erro de hardware (WHEA/MCE). Um isolado pode ser "
                 "inofensivo; vários seguidos apontam para RAM, CPU ou tensões instáveis — teste a RAM no "
                 "Stress test e desligue overclocks."),
    "memory": ("Falta de memória", "warn",
               "A RAM esgotou-se e o sistema teve de fechar programas à força. Feche separadores/programas, "
               "aumente a swap/ficheiro de paginação ou instale mais RAM."),
    "disk": ("Erros de disco", "bad",
             "O sistema não conseguiu ler ou escrever no disco. Veja a Saúde dos discos (S.M.A.R.T.), o cabo "
             "SATA e faça cópia de segurança dos ficheiros importantes."),
    "thermal": ("Temperatura crítica", "bad",
                "O hardware atingiu a temperatura crítica e reduziu o desempenho ou desligou-se. Limpe o pó, "
                "verifique as ventoinhas e a pasta térmica."),
    "app": ("Programas que fecharam com erro", "warn",
            "Programas que terminaram de forma inesperada. Se for sempre o mesmo, atualize-o ou reinstale-o; "
            "se forem muitos diferentes, pode ser instabilidade de RAM."),
}
ORDER = ("shutdown", "crash", "hardware", "thermal", "disk", "gpu", "memory", "app")

# ------------------------------------------------------------------------------------------- Linux
# encerramento normal: o systemd escreve sempre uma destas linhas nos últimos instantes do arranque
_CLEAN_RE = re.compile(r"Stopping Flush Journal to Persistent Storage|System is (?:powering down|rebooting|halting)"
                       r"|Reached target .*(?:Shutdown|Power-Off|Reboot|Halt|Kexec)|Journal stopped|Unmounting /"
                       r"|systemd-logind.*(?:Power key pressed|The system will (?:power off|reboot))"
                       r"|PM: suspend entry|Hibernat", re.I)

_KERNEL_RULES: list[tuple[str, re.Pattern, str]] = [
    ("crash", re.compile(r"Kernel panic|general protection fault|Oops[: ]|BUG: (?!.*soft lockup)|"
                         r"watchdog: BUG: soft lockup|hard LOCKUP|kernel BUG at", re.I), "Falha do núcleo do Linux"),
    ("hardware", re.compile(r"Machine check|mce: \[Hardware Error\]|\[Hardware Error\]|EDAC .*(?:CE|UE) |"
                            r"PCIe Bus Error.*severity=(?:Uncorrected|Fatal)", re.I), "Erro de hardware (MCE/AER)"),
    ("thermal", re.compile(r"critical temperature reached|temperature above threshold|"
                           r"thermal.*(?:shutdown|critical)", re.I), "Temperatura crítica"),
    ("gpu", re.compile(r"amdgpu.*(?:GPU reset|ring \S+ timeout|GPU recovery|soft recovered)|NVRM: Xid|"
                       r"i915.*(?:GPU HANG|Resetting chip)|nouveau.*(?:fifo: fault|timeout)|xe .*GT\d+: reset", re.I),
     "Reinício do controlador gráfico"),
    ("memory", re.compile(r"Out of memory: Killed process|invoked oom-killer", re.I), "Falta de memória (OOM)"),
    ("disk", re.compile(r"I/O error, dev |Buffer I/O error|blk_update_request: (?:I/O|critical medium) error|"
                        r"ata\d+(?:\.\d+)?: (?:failed command|exception Emask)|nvme\d+: .*(?:timeout|I/O \d+ QID)|"
                        r"EXT4-fs error|BTRFS (?:error|critical)|XFS .*(?:metadata I/O error|Corruption)", re.I),
     "Erro de leitura/escrita no disco"),
]
_KERNEL_GREP = "|".join(p.pattern for _c, p, _t in _KERNEL_RULES)


def classify_kernel(msg: str) -> tuple[str, str] | None:
    """(categoria, título) de uma mensagem do kernel, ou None se não interessar."""
    for cat, pat, title in _KERNEL_RULES:
        if pat.search(msg):
            return cat, title
    return None


def unclean_boots(boots: list[dict], tails: dict[str, str]) -> list[Event]:
    """boots = `journalctl --list-boots -o json` (o último é o atual); tails[boot_id] = últimas linhas.
    Um arranque anterior sem nenhuma linha de encerramento normal → desligou-se sem aviso."""
    out = []
    for b in boots[:-1]:
        bid = b.get("boot_id", "")
        tail = tails.get(bid)
        if tail is None or not tail.strip():   # sem registos (journal volátil/rodado) → não sabemos
            continue
        if not _CLEAN_RE.search(tail):
            last = (b.get("last_entry") or 0) / 1e6
            out.append(Event(last, "shutdown", "O PC desligou-se ou reiniciou sem encerrar normalmente"))
    return out


def _linux_boots(since: float) -> list[Event]:
    code, out = run(["journalctl", "--list-boots", "-o", "json", "--no-pager"], timeout=30)
    if code != 0:
        return []
    try:
        boots = [b for b in json.loads(out or "[]") if (b.get("last_entry") or 0) / 1e6 >= since]
    except ValueError:
        return []
    tails = {}
    for b in boots[-16:-1]:    # no máximo os últimos 15 arranques anteriores
        c, t = run(["journalctl", "-b", b["boot_id"], "-n", "300", "-o", "cat", "-q", "--no-pager"], timeout=20)
        if c == 0:
            tails[b["boot_id"]] = t
    return unclean_boots(boots[-16:], tails)


def _linux_kernel(since: float) -> list[Event]:
    args = ["journalctl", "-k", "--since", f"@{int(since)}", "-q", "-o", "json", "--no-pager",
            "--output-fields=MESSAGE", "--case-sensitive=false", "--grep", _KERNEL_GREP]
    code, out = run(args, timeout=60)
    if code not in (0, 1):   # 1 = nada encontrado
        return []
    return group_events(_kernel_from_json(out))


def _kernel_from_json(out: str) -> list[Event]:
    evs = []
    for ln in out.splitlines():
        try:
            j = json.loads(ln)
        except ValueError:
            continue
        msg = j.get("MESSAGE")
        if isinstance(msg, list):   # mensagens binárias vêm como lista de bytes
            msg = bytes(x for x in msg if isinstance(x, int)).decode("utf-8", "replace")
        if not isinstance(msg, str):
            continue
        c = classify_kernel(msg)
        if c:
            evs.append(Event(int(j.get("__REALTIME_TIMESTAMP", 0)) / 1e6, c[0], c[1], msg.strip()[:300]))
    return evs


def _linux_coredumps(since: float) -> list[Event]:
    if not which("coredumpctl"):
        return []
    code, out = run(["coredumpctl", "list", "--since", f"@{int(since)}", "--json=short", "--no-pager", "-q"],
                    timeout=30)
    if code != 0:
        return []
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return []
    sig = {4: "instrução ilegal", 6: "abortou", 7: "erro de barramento", 8: "erro aritmético", 11: "acesso inválido "
           "à memória"}
    evs = []
    for r in rows:
        exe = os.path.basename(str(r.get("exe") or "?"))
        evs.append(Event(int(r.get("time", 0)) / 1e6, "app", exe,
                         f"Sinal {r.get('sig')}: {sig.get(r.get('sig'), 'terminado')}"))
    return group_events(evs)


def journal_readable() -> bool:
    """O journal do sistema é legível sem root? (senão só se veem os registos do utilizador)"""
    code, out = run(["journalctl", "-k", "-n", "1", "-q", "--no-pager"], timeout=10)
    return code == 0 and bool(out.strip())


# ------------------------------------------------------------------------------------------ Windows
_WIN_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$start = (Get-Date).AddDays(-%DAYS%)
$sys = @(
  @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Power'; Id=41; StartTime=$start},
  @{LogName='System'; ProviderName='EventLog'; Id=6008; StartTime=$start},
  @{LogName='System'; ProviderName='Microsoft-Windows-WER-SystemErrorReporting'; Id=1001; StartTime=$start},
  @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=$start},
  @{LogName='System'; ProviderName='Display'; Id=4101; StartTime=$start},
  @{LogName='System'; ProviderName='nvlddmkm'; StartTime=$start},
  @{LogName='System'; ProviderName='amdkmdag'; StartTime=$start},
  @{LogName='System'; ProviderName='Microsoft-Windows-Resource-Exhaustion-Detector'; Id=2004; StartTime=$start},
  @{LogName='System'; ProviderName='disk'; Id=7,11,51,153; StartTime=$start},
  @{LogName='System'; ProviderName='Ntfs'; Id=55,98,137; StartTime=$start},
  @{LogName='System'; ProviderName='Microsoft-Windows-Kernel-Processor-Power'; Id=37; StartTime=$start},
  @{LogName='Application'; ProviderName='Application Error'; Id=1000; StartTime=$start}
)
$all = foreach ($f in $sys) { Get-WinEvent -FilterHashtable $f -MaxEvents 200 }
$all | ForEach-Object {
  $m = $_.Message; if ($m) { $m = $m.Substring(0, [Math]::Min(300, $m.Length)) }
  [pscustomobject]@{ t = [int64](($_.TimeCreated.ToUniversalTime() - [datetime]'1970-01-01').TotalSeconds);
                     p = $_.ProviderName; id = $_.Id; m = $m; a = ($_.Properties | Select-Object -First 1).Value }
} | ConvertTo-Json -Compress
"""


def classify_windows(provider: str, eid: int, msg: str = "", first_prop=None) -> tuple[str, str] | None:
    p = (provider or "").lower()
    if p == "microsoft-windows-kernel-power" and eid == 41:
        return "shutdown", "O Windows reiniciou sem encerrar normalmente (Kernel-Power 41)"
    if p == "eventlog" and eid == 6008:
        return "shutdown", "Encerramento inesperado anterior"
    if p == "microsoft-windows-wer-systemerrorreporting" and eid == 1001:
        return "crash", "Ecrã azul (BugCheck)"
    if p == "microsoft-windows-whea-logger":
        return "hardware", "Erro de hardware (WHEA)"
    if p in ("display", "nvlddmkm", "amdkmdag"):
        return "gpu", "O controlador gráfico deixou de responder e recuperou"
    if p == "microsoft-windows-resource-exhaustion-detector":
        return "memory", "Memória virtual quase esgotada"
    if p in ("disk", "ntfs"):
        return "disk", "Erro de disco / sistema de ficheiros"
    if p == "microsoft-windows-kernel-processor-power" and eid == 37:
        return "thermal", "O processador foi limitado pelo firmware (temperatura/energia)"
    if p == "application error" and eid == 1000:
        app = str(first_prop or "").strip() or "Programa"
        return "app", app
    return None


def parse_windows(out: str) -> list[Event]:
    try:
        rows = json.loads(out or "[]")
    except ValueError:
        return []
    if isinstance(rows, dict):
        rows = [rows]
    evs = []
    for r in rows if isinstance(rows, list) else []:
        c = classify_windows(r.get("p", ""), int(r.get("id") or 0), r.get("m") or "", r.get("a"))
        if c:
            evs.append(Event(float(r.get("t") or 0), c[0], c[1], (r.get("m") or "").strip().split("\n")[0][:300]))
    return group_events(evs)


# ------------------------------------------------------------------------------------------- comum
def group_events(evs: list[Event], window: float = 600) -> list[Event]:
    """Junta eventos iguais (mesma categoria e título) com menos de `window` s entre si — uma rajada de 50
    erros de E/S do mesmo minuto conta como um evento com count=50."""
    evs = sorted(evs, key=lambda e: e.when)
    out: list[Event] = []
    last: dict[tuple[str, str], Event] = {}
    for e in evs:
        k = (e.cat, e.title)
        prev = last.get(k)
        if prev is not None and e.when - prev.when <= window:
            prev.count += e.count
            prev.when = e.when
            continue
        last[k] = e
        out.append(e)
    return out


def scan(days: int = DAYS) -> dict:
    """Lê os registos do sistema (pode demorar alguns segundos) e grava a cache."""
    since = time.time() - days * 86400
    evs: list[Event] = []
    limited = False
    if IS_LINUX and which("journalctl"):
        limited = not journal_readable()
        evs += _linux_boots(since)
        evs += _linux_kernel(since)
        evs += _linux_coredumps(since)
    elif IS_WIN:
        code, out = run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                         _WIN_PS.replace("%DAYS%", str(days))], timeout=120)
        evs += parse_windows(out if code == 0 else "")
    evs.sort(key=lambda e: e.when, reverse=True)
    data = {"when": time.time(), "days": days, "limited": limited, "events": [asdict(e) for e in evs[:500]]}
    save_json(CACHE, data)
    return data


def cached() -> dict:
    d = load_json(CACHE, {})
    return d if isinstance(d, dict) else {}


def events(data: dict | None = None) -> list[Event]:
    data = cached() if data is None else data
    out = []
    for e in data.get("events") or []:
        try:
            out.append(Event(**e))
        except TypeError:
            continue
    return out


def summary(evs: list[Event], now: float | None = None, days: int = 7) -> dict[str, int]:
    """Quantos eventos (somando count) de cada categoria nos últimos `days` dias."""
    now = time.time() if now is None else now
    out: dict[str, int] = {}
    for e in evs:
        if now - e.when <= days * 86400:
            out[e.cat] = out.get(e.cat, 0) + (1 if e.cat == "shutdown" else e.count)
    return out


def stability_index(evs: list[Event], now: float | None = None) -> float:
    """0–10, como o Monitor de Fiabilidade do Windows: começa em 10 e cada evento recente tira pontos
    (os mais antigos pesam menos; cada tipo tem um teto para uma rajada não levar tudo)."""
    now = time.time() if now is None else now
    weight = {"shutdown": 2.0, "crash": 2.5, "hardware": 1.5, "thermal": 1.5, "disk": 1.5, "gpu": 1.0,
              "memory": 0.7, "app": 0.15}
    cap = {"app": 1.5, "gpu": 3.0, "memory": 2.0}
    lost: dict[str, float] = {}
    for e in evs:
        age_d = max(0.0, (now - e.when) / 86400)
        if age_d > DAYS:
            continue
        decay = max(0.0, 1 - age_d / DAYS)
        n = 1 if e.cat == "shutdown" else min(e.count, 3)
        lost[e.cat] = lost.get(e.cat, 0.0) + weight.get(e.cat, 0.5) * decay * n
    total = sum(min(v, cap.get(k, 5.0)) for k, v in lost.items())
    return round(max(0.0, 10.0 - total), 1)


def per_day(evs: list[Event], now: float | None = None, days: int = DAYS) -> list[str]:
    """Para cada dia (mais antigo → hoje): "ok" | "warn" | "bad" — a faixa de cores da página."""
    from datetime import date
    now = time.time() if now is None else now
    today = date.fromtimestamp(now)
    out = ["ok"] * days
    for e in evs:
        idx = days - 1 - (today - date.fromtimestamp(e.when)).days
        if 0 <= idx < days:
            k = e.kind
            if k == "bad" or out[idx] == "ok":
                out[idx] = k
    return out


def new_since(evs: list[Event], ts: float) -> list[Event]:
    """Eventos importantes (não "app") mais recentes do que ts — para avisar no arranque."""
    return [e for e in evs if e.when > ts and e.cat != "app"]
