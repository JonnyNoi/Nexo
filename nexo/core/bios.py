"""BIOS/UEFI: versão instalada, idade e onde procurar uma versão mais recente.

Os fabricantes de placas-mãe não têm uma forma pública e estável de perguntar «qual é a última versão do
BIOS desta placa», por isso o Nexo:
  • mostra a versão e a data do BIOS instalado e há quanto tempo saiu;
  • no Linux pergunta ao fwupd (LVFS) — funciona em muitos portáteis e PCs de marca (Dell, Lenovo, HP,
    Framework…), que publicam o firmware lá; quando há uma versão nova diz qual;
  • abre a página de suporte da placa-mãe/portátil no site do fabricante (pesquisa pelo modelo).
Atualizar o BIOS faz-se sempre com a ferramenta do fabricante (ou pelo fwupd) — o Nexo não o faz."""
from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from urllib.parse import quote_plus

from .util import IS_LINUX, IS_WIN, load_json, ps_json, read_text, run, save_json, which

CACHE = "bios.json"
OLD_YEARS = 3


@dataclass
class BiosInfo:
    vendor: str = ""          # fabricante do BIOS (AMI, Insyde, Phoenix…)
    version: str = ""
    date: str = ""            # AAAA-MM-DD
    board_vendor: str = ""
    board: str = ""
    system_vendor: str = ""
    system: str = ""

    @property
    def age_days(self) -> float | None:
        try:
            return (time.time() - time.mktime(time.strptime(self.date, "%Y-%m-%d"))) / 86400
        except (ValueError, OverflowError):
            return None


def _norm_date(s: str) -> str:
    s = (s or "").strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)          # Linux DMI: MM/DD/AAAA
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    m = re.match(r"(\d{4})-?(\d{2})-?(\d{2})", s)             # 2023-05-17 ou 20230517 (WMI)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


_JUNK = re.compile(r"^(to be filled by o\.?e\.?m\.?|default string|system product name|system manufacturer|"
                   r"not applicable|none|o\.?e\.?m\.?|\s*)$", re.I)


def _clean(s: str) -> str:
    s = (s or "").strip()
    return "" if _JUNK.match(s) else s


def read() -> BiosInfo:
    if IS_LINUX:
        f = lambda n: _clean(read_text(f"/sys/class/dmi/id/{n}"))  # noqa: E731
        return BiosInfo(f("bios_vendor"), f("bios_version"), _norm_date(f("bios_date")), f("board_vendor"),
                        f("board_name"), f("sys_vendor"), f("product_name"))
    if IS_WIN:
        d = ps_json("$b = Get-CimInstance Win32_BIOS; $m = Get-CimInstance Win32_BaseBoard; "
                    "$c = Get-CimInstance Win32_ComputerSystem; [pscustomobject]@{V=$b.Manufacturer; "
                    "Ver=$b.SMBIOSBIOSVersion; D=$b.ReleaseDate.ToString('yyyy-MM-dd'); BV=$m.Manufacturer; "
                    "B=$m.Product; SV=$c.Manufacturer; S=$c.Model} | ConvertTo-Json", timeout=30) or {}
        if isinstance(d, dict):
            g = lambda k: _clean(str(d.get(k) or ""))  # noqa: E731
            return BiosInfo(g("V"), g("Ver"), _norm_date(g("D")), g("BV"), g("B"), g("SV"), g("S"))
    return BiosInfo()


# --------------------------------------------------------------------------- página de suporte
_OEMS = ("dell", "lenovo", "hp", "hewlett", "acer", "framework", "microsoft", "samsung", "toshiba", "fujitsu",
         "huawei", "xiaomi", "medion", "clevo", "tuxedo", "system76", "lg")


def _brand(s: str) -> str:
    s = s.lower()
    for k in ("asus", "msi", "micro-star", "gigabyte", "asrock", "biostar", "evga", "nzxt", *_OEMS):
        if k in s:
            return {"micro-star": "msi", "hewlett": "hp"}.get(k, k)
    return ""


def is_oem(info: BiosInfo) -> bool:
    """PC de marca/portátil: o BIOS é do modelo do sistema, não da placa-mãe."""
    return _brand(info.system_vendor) in _OEMS


def support_url(info: BiosInfo) -> str:
    """Página onde se descarrega o BIOS (pesquisa pelo modelo no site do fabricante)."""
    if is_oem(info):
        brand, model = _brand(info.system_vendor), info.system
    else:
        brand, model = _brand(info.board_vendor) or _brand(info.system_vendor), info.board or info.system
    model = re.sub(r"\s*\(.*?\)", "", model).strip() or model     # "B760M GAMING PLUS WIFI (MS-7D99)"
    q = quote_plus(model)
    urls = {
        "asus": f"https://www.asus.com/support/search-result/?keyword={q}",
        "msi": f"https://www.msi.com/search/{quote_plus(model)}",
        "gigabyte": f"https://www.gigabyte.com/Search?kw={q}",
        "asrock": f"https://www.asrock.com/search/index.asp?Keyword={q}",
        "biostar": f"https://www.biostar.com.tw/app/en/search/?keyword={q}",
        "dell": "https://www.dell.com/support/home/",
        "lenovo": f"https://pcsupport.lenovo.com/search?query={q}",
        "hp": "https://support.hp.com/drivers",
        "acer": "https://www.acer.com/support",
        "framework": "https://knowledgebase.frame.work/en_us/bios-and-drivers-downloads-rJ3PaCexh",
        "microsoft": "https://support.microsoft.com/surface/download-drivers-and-firmware-for-surface",
    }
    if brand in urls:
        return urls[brand]
    who = info.system_vendor if is_oem(info) else info.board_vendor or info.system_vendor
    return "https://duckduckgo.com/?q=" + quote_plus(f"{who} {model} BIOS download".strip())


# --------------------------------------------------------------------------- fwupd (Linux)
def parse_fwupd_updates(text: str) -> str:
    """Do `fwupdmgr get-updates --json`: versão nova do firmware do sistema (UEFI), ou ""."""
    try:
        data = json.loads(text)
    except ValueError:
        return ""
    for dev in data.get("Devices", []) if isinstance(data, dict) else []:
        name = str(dev.get("Name", ""))
        plugin = str(dev.get("Plugin", ""))
        flags = dev.get("Flags") or []
        system = "uefi" in plugin.lower() or "system firmware" in name.lower() or "uefi" in name.lower() \
            or "internal" in flags and "bios" in name.lower()
        rels = dev.get("Releases") or []
        if system and rels:
            v = rels[0].get("Version") or ""
            return f"{name} {v}".strip()
    return ""


def fwupd_check() -> tuple[bool, str]:
    """(o fwupd funciona aqui, atualização disponível)."""
    if not IS_LINUX or not which("fwupdmgr"):
        return False, ""
    code, out = run(["fwupdmgr", "get-updates", "--json", "--no-unreported-check"], timeout=45)
    if code not in (0, 2) or "{" not in out:     # 2 = sem atualizações
        return code == 2, ""
    return True, parse_fwupd_updates(out[out.index("{"):])


# --------------------------------------------------------------------------- resultado
def verdict(info: BiosInfo, fw_update: str = "") -> tuple[str, str]:
    if fw_update:
        return "warn", f"Há uma versão nova do firmware: {fw_update}. Instale-a pelo fwupd (Atualizar o BIOS)."
    age = info.age_days
    if age is None:
        return "info", "Não foi possível saber a data do BIOS."
    years = age / 365
    if years >= OLD_YEARS:
        return "warn", (f"O BIOS tem {years:.0f} anos. Os fabricantes costumam lançar versões com correções "
                        "de segurança, estabilidade e suporte para processadores/memórias mais recentes — "
                        "veja na página de suporte se há uma versão nova.")
    if years >= 1:
        return "info", f"O BIOS tem {years:.1f} anos. Vale a pena confirmar se há uma versão nova."
    return "ok", "BIOS recente (menos de 1 ano)."


def check() -> dict:
    """Lê o BIOS, pergunta ao fwupd e guarda o resultado (a Saúde do PC lê a cache)."""
    info = read()
    fw_ok, fw = fwupd_check()
    kind, text = verdict(info, fw)
    res = {"time": time.time(), "info": asdict(info), "fwupd": fw_ok, "fwupd_update": fw, "kind": kind,
           "text": text, "url": support_url(info), "oem": is_oem(info)}
    try:
        save_json(CACHE, res)
    except OSError:
        pass
    return res


def cached() -> dict | None:
    d = load_json(CACHE, None)
    return d if isinstance(d, dict) else None
