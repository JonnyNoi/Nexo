"""Saúde dos discos (S.M.A.R.T.): vida restante, temperatura, horas ligado, dados escritos e erros.

Linux: `smartctl` (smartmontools) — ler os discos precisa de root, por isso todos os discos são lidos
numa única chamada ao pkexec (a palavra-passe é pedida uma vez) e o resultado fica em cache.
Windows: `smartctl` se estiver instalado (mais completo); senão Get-PhysicalDisk +
Get-StorageReliabilityCounter do PowerShell (precisa de administrador, que o .exe já pede).
"""
from __future__ import annotations

import json
import os
import time

from .util import IS_WIN, as_list, is_admin, load_json, ps_json, run, run_root, save_json, which

CACHE = "smart.json"

# atributos ATA que indicam setores estragados / erros (raw > 0 é mau sinal)
_ATA_BAD_SECTORS = {5: "setores realocados", 197: "setores pendentes", 198: "setores ilegíveis"}
_ATA_ERRORS = {187: "erros de leitura não corrigidos", 188: "comandos expirados"}
# atributos de desgaste dos SSD — o valor normalizado é a vida restante (100 → 0)
_ATA_WEAR = (231, 233, 202, 169, 177, 173)

_ATA_NAMES = {
    1: "Taxa de erros de leitura", 3: "Tempo de arranque do motor", 4: "Arranques/paragens",
    5: "Setores realocados", 7: "Erros de posicionamento", 9: "Horas ligado", 10: "Tentativas de arranque",
    12: "Ciclos de energia", 169: "Vida restante", 170: "Blocos de reserva", 171: "Falhas de programação",
    172: "Falhas de apagamento", 173: "Desgaste médio", 174: "Cortes de energia inesperados",
    175: "Falhas de programação", 177: "Nivelamento de desgaste", 179: "Blocos de reserva usados",
    180: "Blocos de reserva livres", 181: "Falhas de programação", 182: "Falhas de apagamento",
    183: "Erros SATA (downshift)", 184: "Erros fim-a-fim", 187: "Erros não corrigidos", 188: "Comandos expirados",
    189: "Escritas fora do lugar", 190: "Temperatura (fluxo de ar)", 191: "Choques (G-sense)",
    192: "Desligamentos forçados", 193: "Ciclos da cabeça", 194: "Temperatura", 195: "Erros corrigidos (ECC)",
    196: "Eventos de realocação", 197: "Setores pendentes", 198: "Setores ilegíveis",
    199: "Erros no cabo SATA (CRC)", 200: "Erros de escrita", 202: "Vida restante",
    206: "Erros de altura de voo", 231: "Vida restante do SSD", 232: "Reserva disponível",
    233: "Indicador de desgaste", 235: "Cortes de energia (SSD)", 240: "Horas de voo da cabeça",
    241: "Total escrito", 242: "Total lido", 246: "Setores escritos pelo sistema", 247: "Páginas escritas (host)",
    248: "Páginas escritas (FTL)",
}


# =========================================================================== disponibilidade
def smartctl_path() -> str | None:
    p = which("smartctl")
    if p:
        return p
    if IS_WIN:
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"),
                     os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")):
            cand = os.path.join(base, "smartmontools", "bin", "smartctl.exe")
            if os.path.isfile(cand):
                return cand
    return None


def needs_password() -> bool:
    """Linux sem root: cada leitura passa pelo pkexec."""
    return not IS_WIN and not is_admin()


def install_smartmontools() -> tuple[bool, str]:
    if IS_WIN:
        if not which("winget"):
            return False, "O winget não está disponível — instale o smartmontools a partir de smartmontools.org."
        code, out = run(["winget", "install", "-e", "--id", "smartmontools.smartmontools",
                         "--accept-package-agreements", "--accept-source-agreements", "--silent"], timeout=900)
        if smartctl_path():
            return True, "smartmontools instalado."
        return False, _tail(out)
    cmds = {"pacman": "pacman -S --noconfirm --needed smartmontools",
            "apt-get": "DEBIAN_FRONTEND=noninteractive apt-get install -y smartmontools",
            "dnf": "dnf install -y smartmontools",
            "zypper": "zypper -n install smartmontools"}
    pm = next((p for p in cmds if which(p)), None)
    if not pm:
        return False, "Gestor de pacotes não reconhecido — instale o pacote \"smartmontools\" manualmente."
    code, out = run_root(cmds[pm], timeout=900)
    if code != 0 or not smartctl_path():
        return False, _tail(out)
    return True, "smartmontools instalado."


def _tail(out: str, n: int = 3) -> str:
    lines = [x for x in (out or "").splitlines() if x.strip()]
    return " · ".join(lines[-n:]) or "falhou"


# =========================================================================== discos
def list_block_disks() -> list[dict]:
    """Linux: discos físicos (sem zram, loop, leitores óticos)."""
    code, out = run(["lsblk", "-J", "-d", "-b", "-o", "NAME,TYPE,TRAN,ROTA,MODEL,SIZE,SERIAL"], timeout=10)
    if code != 0:
        return []
    try:
        devs = json.loads(out).get("blockdevices", [])
    except ValueError:
        return []
    keep = []
    for d in devs:
        name = d.get("name") or ""
        if d.get("type") != "disk" or name.startswith(("zram", "loop", "ram", "sr", "fd")):
            continue
        if not int(d.get("size") or 0):
            continue
        keep.append(d)
    return keep


def read_all() -> dict:
    """Lê todos os discos e guarda em cache. Devolve {"time", "disks": [...], "error"}."""
    exe = smartctl_path()
    if IS_WIN:
        disks = _read_windows_smartctl(exe) if exe else []
        if not disks:
            disks = _read_windows_ps()
        res = {"time": time.time(), "disks": disks, "error": "" if disks else "Nenhum disco encontrado."}
    else:
        res = _read_linux(exe)
    if res.get("disks"):
        try:
            save_json(CACHE, res)
        except OSError:
            pass
    return res


def cached() -> dict | None:
    data = load_json(CACHE, None)
    return data if isinstance(data, dict) and data.get("disks") else None


def _read_linux(exe: str | None) -> dict:
    now = time.time()
    if not exe:
        return {"time": now, "disks": [], "error": "smartctl não está instalado."}
    blk = list_block_disks()
    if not blk:
        return {"time": now, "disks": [], "error": "Nenhum disco encontrado."}
    names = [d["name"] for d in blk if all(c.isalnum() or c in "-_" for c in d["name"])]
    script = "; ".join(f"echo '@@NEXO {n}'; {exe} -j -x /dev/{n}" for n in names)
    code, out = run_root(script, timeout=120)
    if "@@NEXO" not in out:
        msg = "Pedido de permissão cancelado." if code in (126, 127) else _tail(out)
        return {"time": now, "disks": [], "error": msg}
    by_name = {d["name"]: d for d in blk}
    disks = []
    for chunk in out.split("@@NEXO ")[1:]:
        name, _, body = chunk.partition("\n")
        name = name.strip()
        j = _json_from(body)
        info = by_name.get(name, {})
        if j is None:
            disks.append(_unreadable(f"/dev/{name}", info.get("model") or name, int(info.get("size") or 0),
                                     "smartctl não devolveu dados."))
            continue
        disks.append(parse_smartctl(j, f"/dev/{name}", info))
    return {"time": now, "disks": disks, "error": ""}


def _read_windows_smartctl(exe: str) -> list[dict]:
    code, out = run([exe, "--scan", "-j"], timeout=30)
    scan = _json_from(out) or {}
    disks = []
    for d in scan.get("devices", []):
        name, typ = d.get("name"), d.get("type")
        if not name:
            continue
        code, out = run([exe, "-j", "-x", "-d", typ or "auto", name], timeout=60)
        j = _json_from(out)
        if j:
            disks.append(parse_smartctl(j, name, {}))
    return disks


def _read_windows_ps() -> list[dict]:
    script = (
        "Get-PhysicalDisk | ForEach-Object { $r = $_ | Get-StorageReliabilityCounter -ErrorAction "
        "SilentlyContinue; [pscustomobject]@{ Name=$_.FriendlyName; Serial=$_.SerialNumber; "
        "Media=[string]$_.MediaType; Bus=[string]$_.BusType; Size=[int64]$_.Size; "
        "Health=[string]$_.HealthStatus; Op=(($_.OperationalStatus | ForEach-Object { [string]$_ }) -join ', '); "
        "Fw=$_.FirmwareVersion; Dev=[string]$_.DeviceId; Temp=$r.Temperature; Wear=$r.Wear; "
        "Hours=$r.PowerOnHours; Cycles=$r.StartStopCycleCount; ReadErr=$r.ReadErrorsUncorrected; "
        "WriteErr=$r.WriteErrorsUncorrected } }")
    disks = []
    for d in as_list(ps_json(script, timeout=60)):
        if isinstance(d, dict):
            disks.append(parse_windows_ps(d))
    return disks


def _json_from(text: str):
    i, k = text.find("{"), text.rfind("}")
    if i < 0 or k <= i:
        return None
    try:
        return json.loads(text[i:k + 1])
    except ValueError:
        return None


# =========================================================================== interpretação
def _base(dev: str, model: str, size: int) -> dict:
    return {"dev": dev, "model": model, "serial": "", "firmware": "", "size": size, "kind": "Disco",
            "interface": "", "passed": None, "temp": None, "hours": None, "cycles": None, "unsafe": None,
            "written": None, "read": None, "life": None, "selftest": "", "can_selftest": False,
            "attrs": [], "verdict": "unknown", "reasons": [], "error": ""}


def _unreadable(dev: str, model: str, size: int, why: str) -> dict:
    d = _base(dev, model, size)
    d["error"] = why
    d["reasons"] = [("warn", why)]
    return d


def parse_smartctl(j: dict, dev: str, blk: dict | None = None) -> dict:
    """Converte o JSON do `smartctl -j -x` num resumo com veredicto."""
    blk = blk or {}
    d = _base(dev, j.get("model_name") or blk.get("model") or dev,
              int((j.get("user_capacity") or {}).get("bytes") or blk.get("size") or 0))
    nvme = j.get("nvme_namespaces") is not None or (j.get("device") or {}).get("protocol") == "NVMe" \
        or "nvme_smart_health_information_log" in j
    if not d["size"] and nvme:
        d["size"] = int((j.get("nvme_total_capacity") or 0))
    rot = j.get("rotation_rate")
    if nvme:
        d["kind"] = "SSD NVMe"
    elif rot == 0 or (rot is None and blk.get("rota") is False):
        d["kind"] = "SSD"
    elif isinstance(rot, int) and rot > 0:
        d["kind"] = f"HDD {rot} rpm"
    elif blk.get("rota"):
        d["kind"] = "HDD"
    d["serial"] = j.get("serial_number") or blk.get("serial") or ""
    d["firmware"] = j.get("firmware_version") or ""
    d["interface"] = (blk.get("tran") or (j.get("device") or {}).get("protocol") or "").upper()

    status = int((j.get("smartctl") or {}).get("exit_status") or 0)
    msgs = [m.get("string", "") for m in (j.get("smartctl") or {}).get("messages", [])]
    if status & 0b11 and not (j.get("smart_status") or j.get("nvme_smart_health_information_log")
                              or j.get("ata_smart_attributes")):
        why = next((m for m in msgs if m), "Não foi possível ler este disco.")
        if "Permission denied" in why:
            why = "Sem permissão para ler o disco."
        elif "Unknown USB bridge" in why or "unsupported" in why.lower():
            why = "O adaptador USB deste disco não deixa ler os dados S.M.A.R.T."
        d["error"] = why
        d["reasons"] = [("warn", why)]
        return d

    ss = j.get("smart_status") or {}
    if "passed" in ss:
        d["passed"] = bool(ss["passed"])
    d["temp"] = (j.get("temperature") or {}).get("current")
    d["hours"] = (j.get("power_on_time") or {}).get("hours")
    d["cycles"] = j.get("power_cycle_count")
    reasons: list[tuple[str, str]] = []
    if d["passed"] is False or status & 8:
        reasons.append(("bad", "O próprio disco reporta que está a FALHAR — copie os seus dados já."))

    if nvme:
        _parse_nvme(j, d, reasons)
    else:
        _parse_ata(j, d, reasons, status)

    # temperatura
    t = d["temp"]
    if isinstance(t, (int, float)) and t > 0:
        warn, bad = (70, 80) if nvme else (50, 60) if d["kind"].startswith("HDD") else (60, 70)
        if t >= bad:
            reasons.append(("bad", f"Muito quente: {t:.0f} °C — melhore a ventilação do disco."))
        elif t >= warn:
            reasons.append(("warn", f"Quente: {t:.0f} °C."))

    life = d["life"]
    if life is not None:
        if life <= 10:
            reasons.append(("bad", f"Vida útil quase esgotada ({life:.0f}% restante) — planeie a substituição."))
        elif life <= 25:
            reasons.append(("warn", f"Desgaste elevado ({life:.0f}% de vida restante)."))
    if status & 16:
        reasons.append(("bad", "Há atributos abaixo do limite de falha do fabricante."))
    elif status & 32:
        reasons.append(("warn", "Algum atributo já esteve abaixo do limite de falha no passado."))
    if status & 128:
        reasons.append(("warn", "O último autoteste do disco encontrou erros."))

    d["reasons"] = reasons
    d["verdict"] = _verdict(reasons, d["passed"])
    return d


def _parse_nvme(j: dict, d: dict, reasons: list) -> None:
    h = j.get("nvme_smart_health_information_log") or {}
    d["can_selftest"] = bool((j.get("nvme_optional_admin_commands") or {}).get("self_test"))
    if d["temp"] is None:
        d["temp"] = h.get("temperature")
    d["hours"] = d["hours"] if d["hours"] is not None else h.get("power_on_hours")
    d["cycles"] = d["cycles"] if d["cycles"] is not None else h.get("power_cycles")
    d["unsafe"] = h.get("unsafe_shutdowns")
    if h.get("data_units_written") is not None:
        d["written"] = int(h["data_units_written"]) * 512_000
    if h.get("data_units_read") is not None:
        d["read"] = int(h["data_units_read"]) * 512_000
    if h.get("percentage_used") is not None:
        d["life"] = max(0, 100 - int(h["percentage_used"]))
    cw = int(h.get("critical_warning") or 0)
    if cw:
        parts = []
        if cw & 1:
            parts.append("reserva abaixo do limite")
        if cw & 2:
            parts.append("temperatura fora dos limites")
        if cw & 4:
            parts.append("fiabilidade degradada")
        if cw & 8:
            parts.append("ficou só de leitura")
        if cw & 16:
            parts.append("falha da memória volátil de reserva")
        reasons.append(("bad", "Aviso crítico do disco: " + (", ".join(parts) or f"código {cw}") + "."))
    spare, thr = h.get("available_spare"), h.get("available_spare_threshold")
    if spare is not None and thr is not None and spare <= thr:
        reasons.append(("bad", f"Blocos de reserva esgotados ({spare}% ≤ limite {thr}%)."))
    me = int(h.get("media_errors") or 0)
    if me:
        reasons.append(("warn" if me < 10 else "bad", f"{me} erro(s) de integridade dos dados registados."))
    labels = [("critical_warning", "Aviso crítico", lambda v: "nenhum" if not v else str(v),
               lambda v: "bad" if v else "ok"),
              ("temperature", "Temperatura", lambda v: f"{v} °C", None),
              ("available_spare", "Reserva disponível", lambda v: f"{v}%", None),
              ("available_spare_threshold", "Limite da reserva", lambda v: f"{v}%", None),
              ("percentage_used", "Desgaste (vida usada)", lambda v: f"{v}%",
               lambda v: "bad" if v >= 90 else "warn" if v >= 75 else "ok"),
              ("data_units_written", "Dados escritos", lambda v: _hb(int(v) * 512_000), None),
              ("data_units_read", "Dados lidos", lambda v: _hb(int(v) * 512_000), None),
              ("power_cycles", "Ciclos de energia", str, None),
              ("power_on_hours", "Horas ligado", lambda v: f"{v} h", None),
              ("unsafe_shutdowns", "Desligamentos inesperados", str, None),
              ("media_errors", "Erros de integridade", str, lambda v: "warn" if v else "ok"),
              ("num_err_log_entries", "Entradas no registo de erros", str, None)]
    for key, name, fmt, judge in labels:
        if key in h:
            v = h[key]
            d["attrs"].append([name, fmt(v), "", judge(v) if judge else ""])
    st = (j.get("nvme_self_test_log") or {}).get("table") or []
    if st:
        r = (st[0].get("self_test_result") or {}).get("string") or ""
        d["selftest"] = r


def _parse_ata(j: dict, d: dict, reasons: list, status: int) -> None:
    table = (j.get("ata_smart_attributes") or {}).get("table") or []
    d["can_selftest"] = bool(((j.get("ata_smart_data") or {}).get("capabilities") or {})
                             .get("self_tests_supported"))
    lbs = int(j.get("logical_block_size") or 512)
    attrs = {a.get("id"): a for a in table}
    is_ssd = d["kind"].startswith("SSD")

    def raw(i):
        a = attrs.get(i)
        return int((a.get("raw") or {}).get("value") or 0) if a else None

    for i, what in _ATA_BAD_SECTORS.items():
        v = raw(i)
        if v:
            reasons.append(("bad" if v >= 50 or i == 197 and v >= 10 else "warn", f"{v} {what}."))
    for i, what in _ATA_ERRORS.items():
        v = raw(i)
        if v and (i != 188 or v > 10):
            reasons.append(("warn", f"{v} {what}."))
    crc = raw(199)
    if crc:
        reasons.append(("warn", f"{crc} erros de comunicação (CRC) — normalmente é o cabo SATA ou a ligação, "
                                f"não o disco."))
    failed = [a for a in table if a.get("when_failed") in ("now",)]
    for a in failed:
        reasons.append(("bad", f"Atributo «{_attr_name(a)}» abaixo do limite de falha."))

    # desgaste dos SSD
    stats = j.get("ata_device_statistics") or {}
    for page in stats.get("pages", []):
        for e in page.get("table", []):
            name = e.get("name", "")
            if name == "Percentage Used Endurance Indicator" and e.get("value") is not None and is_ssd:
                d["life"] = max(0, 100 - int(e["value"]))
            elif name == "Logical Sectors Written" and e.get("value"):
                d["written"] = int(e["value"]) * lbs
            elif name == "Logical Sectors Read" and e.get("value"):
                d["read"] = int(e["value"]) * lbs
    if d["life"] is None and is_ssd:
        for i in _ATA_WEAR:
            a = attrs.get(i)
            if a and isinstance(a.get("value"), int) and 0 <= a["value"] <= 100:
                d["life"] = a["value"]
                break
    if d["written"] is None:
        for i in (241, 246):
            a = attrs.get(i)
            if not a:
                continue
            v = raw(i) or 0
            n = (a.get("name") or "").lower()
            unit = 32 * 1024**2 if "32mib" in n else 1024**3 if "gib" in n or n.endswith("_gb") else lbs
            if v:
                d["written"] = v * unit
                break
    d["unsafe"] = raw(192) if raw(192) is not None else raw(174)

    for a in table:
        i = a.get("id")
        r = (a.get("raw") or {}).get("string") or str((a.get("raw") or {}).get("value", ""))
        kind = ""
        if a.get("when_failed") == "now":
            kind = "bad"
        elif a.get("when_failed"):
            kind = "warn"
        elif i in _ATA_BAD_SECTORS or i in (187, 199):
            kind = "warn" if raw(i) else "ok"
        norm = f"{a.get('value', '')} (pior {a.get('worst', '')}, limite {a.get('thresh', '')})"
        d["attrs"].append([f"{i} · {_attr_name(a)}", r, norm, kind])

    log = ((j.get("ata_smart_self_test_log") or {}).get("standard") or {}).get("table") or []
    if log:
        d["selftest"] = (log[0].get("status") or {}).get("string") or ""


def _attr_name(a: dict) -> str:
    return _ATA_NAMES.get(a.get("id"), (a.get("name") or "?").replace("_", " "))


def parse_windows_ps(p: dict) -> dict:
    d = _base(p.get("Dev") or "", p.get("Name") or "Disco", int(p.get("Size") or 0))
    media, bus = p.get("Media") or "", p.get("Bus") or ""
    d["kind"] = ("SSD NVMe" if bus == "NVMe" else "SSD" if media == "SSD" else
                 "HDD" if media == "HDD" else bus or "Disco")
    d["interface"] = bus
    d["serial"] = (p.get("Serial") or "").strip()
    d["firmware"] = p.get("Fw") or ""
    d["temp"] = p.get("Temp") or None
    d["hours"] = p.get("Hours")
    d["cycles"] = p.get("Cycles")
    if p.get("Wear") is not None and d["kind"].startswith("SSD"):
        d["life"] = max(0, 100 - int(p["Wear"]))
    health = p.get("Health") or ""
    reasons = []
    if health == "Unhealthy":
        d["passed"] = False
        reasons.append(("bad", "O Windows marca este disco como com falhas — copie os seus dados já."))
    elif health == "Warning":
        reasons.append(("warn", f"O Windows reporta um aviso para este disco ({p.get('Op') or 'ver detalhes'})."))
    elif health == "Healthy":
        d["passed"] = True
    for key, what in (("ReadErr", "erros de leitura não corrigidos"), ("WriteErr", "erros de escrita não corrigidos")):
        v = int(p.get(key) or 0)
        if v:
            reasons.append(("warn", f"{v} {what}."))
    t = d["temp"]
    if isinstance(t, (int, float)) and t >= 70:
        reasons.append(("warn", f"Quente: {t:.0f} °C."))
    life = d["life"]
    if life is not None and life <= 25:
        reasons.append(("bad" if life <= 10 else "warn", f"Desgaste elevado ({life:.0f}% de vida restante)."))
    if d["passed"] is None and not d["hours"] and d["temp"] is None:
        reasons.append(("warn", "O Windows não deu dados de fiabilidade — instale o smartmontools para ver tudo."))
    for name, key in (("Estado (Windows)", "Health"), ("Estado operacional", "Op"), ("Barramento", "Bus"),
                      ("Temperatura", "Temp"), ("Desgaste", "Wear"), ("Horas ligado", "Hours"),
                      ("Arranques/paragens", "Cycles"), ("Erros de leitura", "ReadErr"),
                      ("Erros de escrita", "WriteErr")):
        if p.get(key) not in (None, ""):
            d["attrs"].append([name, str(p[key]), "", ""])
    d["reasons"] = reasons
    d["verdict"] = _verdict(reasons, d["passed"])
    return d


def _verdict(reasons: list, passed) -> str:
    kinds = {k for k, _t in reasons}
    if "bad" in kinds:
        return "bad"
    if "warn" in kinds:
        return "warn"
    return "ok" if passed is not False else "bad"


def _hb(n: int) -> str:
    from .util import human_bytes
    return human_bytes(n)


# =========================================================================== autoteste
def start_selftest(dev: str) -> tuple[bool, str]:
    """Inicia o autoteste curto (~2 min). Corre dentro do disco; pode continuar a usar o PC."""
    exe = smartctl_path()
    if not exe:
        return False, "smartctl não está instalado."
    if not dev.replace("/", "").replace("_", "").replace("-", "").replace("\\", "").replace(".", "").isalnum():
        return False, "Dispositivo inválido."
    if IS_WIN:
        code, out = run([exe, "-t", "short", dev], timeout=60)
    else:
        code, out = run_root(f"{exe} -t short {dev}", timeout=60)
    if code & 0b11 or "has begun" not in out:
        return False, _tail(out)
    return True, "Autoteste iniciado — demora cerca de 2 minutos. Depois carregue em «Ler discos»."
