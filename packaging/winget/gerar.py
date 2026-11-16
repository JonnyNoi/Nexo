"""Gera os manifestos do winget para a versão atual do Nexo (depois de publicar a release no GitHub).

    python packaging/winget/gerar.py               → packaging/winget/saida/manifests/…
    python packaging/winget/gerar.py --id Dono.Nexo

Lê APP_VERSION e UPDATE_REPO de nexo/core/util.py e o SHA-256 do instalador do SHA256SUMS da release.
Depois valide com `winget validate` e envie com `wingetcreate submit` (ver LEIA-ME.md)."""
from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
SCHEMA = "1.6.0"
PRODUCT_CODE = "{6F0B7E43-2C1A-4E6B-9F3D-6E5C0A1B9D27}_is1"   # AppId do packaging/windows/nexo.iss + "_is1"


def _util_value(name: str) -> str:
    text = (ROOT / "nexo/core/util.py").read_text(encoding="utf-8")
    m = re.search(rf'^{name} = "(.*?)"', text, re.M)
    return m.group(1) if m else ""


def _sha256(repo: str, version: str, filename: str) -> str:
    url = f"https://github.com/{repo}/releases/download/v{version}/SHA256SUMS"
    with urllib.request.urlopen(url, timeout=30) as r:  # noqa: S310 — URL fixo do GitHub
        for line in r.read().decode().splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[1].lstrip("*") == filename:
                return parts[0].upper()
    raise SystemExit(f"{filename} não está no SHA256SUMS da release v{version}")


def manifests(pkg_id: str, repo: str, version: str, sha: str) -> dict[str, str]:
    owner = repo.split("/")[0]
    installer = f"Nexo-Instalador-{version}.exe"
    head = f"# yaml-language-server: $schema=https://aka.ms/winget-manifest.{{}}.{SCHEMA}.schema.json\n"
    common = f"PackageIdentifier: {pkg_id}\nPackageVersion: \"{version}\"\n"
    return {
        f"{pkg_id}.yaml": head.format("version") + common
        + f"DefaultLocale: pt-PT\nManifestType: version\nManifestVersion: {SCHEMA}\n",
        f"{pkg_id}.installer.yaml": head.format("installer") + common
        + "InstallerType: inno\nScope: machine\nElevationRequirement: elevatesSelf\n"
        + f"ProductCode: \"{PRODUCT_CODE}\"\nInstallers:\n"
        + "- Architecture: x64\n"
        + f"  InstallerUrl: https://github.com/{repo}/releases/download/v{version}/{installer}\n"
        + f"  InstallerSha256: {sha}\n"
        + f"ManifestType: installer\nManifestVersion: {SCHEMA}\n",
        f"{pkg_id}.locale.pt-PT.yaml": head.format("defaultLocale") + common
        + f"PackageLocale: pt-PT\nPublisher: {owner}\nPackageName: Nexo\n"
        + f"PackageUrl: https://github.com/{repo}\nLicense: MIT\nLicenseUrl: https://github.com/{repo}/blob/main/LICENSE\n"
        + "ShortDescription: Utilitário do PC — sensores, saúde dos discos, otimização, modo jogo, limpeza, "
          "antivírus e benchmarks.\n"
        + "Tags:\n- benchmark\n- limpeza\n- otimizacao\n- sensores\n- jogos\n"
        + f"ManifestType: defaultLocale\nManifestVersion: {SCHEMA}\n",
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", help="PackageIdentifier (por omissão: <dono do repositório>.Nexo)")
    a = ap.parse_args(argv)
    repo, version = _util_value("UPDATE_REPO"), _util_value("APP_VERSION")
    if not repo:
        print("UPDATE_REPO está vazio em nexo/core/util.py — indique o repositório primeiro.", file=sys.stderr)
        return 1
    pkg_id = a.id or f"{repo.split('/')[0]}.Nexo"
    sha = _sha256(repo, version, f"Nexo-Instalador-{version}.exe")
    first = pkg_id[0].lower()
    out = HERE / "saida" / "manifests" / first / Path(*pkg_id.split(".")) / version
    out.mkdir(parents=True, exist_ok=True)
    for name, text in manifests(pkg_id, repo, version, sha).items():
        (out / name).write_text(text, encoding="utf-8")
    print(f"Manifestos em {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
