"""Limpeza de ficheiros dispensáveis: caches, temporários, reciclagem, pacotes antigos..."""
from __future__ import annotations

import glob
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from .util import IS_LINUX, IS_WIN, is_admin, run, run_root, which


@dataclass
class CleanCategory:
    id: str
    name: str
    desc: str
    patterns: list[str] = field(default_factory=list)   # globs; o conteúdo é apagado
    command: str | None = None                           # alternativa: comando de shell
    size_command: list[str] | None = None
    needs_admin: bool = False
    recommended: bool = True
    min_age_days: float = 0                               # só apaga ficheiros mais antigos que isto
    size: int = -1                                        # -1 = ainda não calculado; -2 = desconhecido
    caution: bool = False                                 # True = seguro, mas com uma consequência a saber
    note: str = ""                                        # o que se perde ao limpar (mostrado na coluna Segurança)

    def targets(self) -> list[str]:
        out = []
        for pat in self.patterns:
            out += glob.glob(os.path.expandvars(os.path.expanduser(pat)))
        return out


def _du(path: str, min_age: float = 0) -> int:
    total = 0
    cutoff = time.time() - min_age * 86400
    if os.path.isfile(path) or os.path.islink(path):
        try:
            st = os.lstat(path)
            return st.st_size if st.st_mtime <= cutoff or not min_age else 0
        except OSError:
            return 0
    for root, _dirs, files in os.walk(path, onerror=lambda e: None):
        for f in files:
            try:
                st = os.lstat(os.path.join(root, f))
                if not min_age or st.st_mtime <= cutoff:
                    total += st.st_size
            except OSError:
                pass
    return total


def _pacman_unused_size() -> int:
    """Bytes que 'pacman -Sc' liberta: pacotes em cache cuja versão não é a instalada."""
    code, out = run(["pacman", "-Q"], timeout=30)
    if code != 0:
        return -2
    installed = {f"{n}-{v}-" for n, v in (ln.split()[:2] for ln in out.splitlines() if len(ln.split()) >= 2)}
    total = 0
    for f in glob.glob("/var/cache/pacman/pkg/*.pkg.tar.*"):
        base = os.path.basename(f)
        if not any(base.startswith(p) for p in installed):
            try:
                total += os.path.getsize(f)
            except OSError:
                pass
    return total


def compute_size(cat: CleanCategory) -> int:
    if cat.id == "win_recycle":
        return _win_recycle_size()
    if cat.id == "lx_pacman" and not cat.size_command:
        return _pacman_unused_size()
    if cat.size_command:
        code, out = run(cat.size_command, timeout=60)
        if code != 0 or not out.strip():
            return 0
        m = re.search(r"([\d.,]+)\s*([BKMGT])", out.split("saved:")[-1])
        if m:
            n = float(m.group(1).replace(",", "."))
            mult = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}[m.group(2)[0]]
            return int(n * mult)
    if cat.patterns:
        return sum(_du(t, cat.min_age_days) for t in cat.targets())
    return -2


def clean(cat: CleanCategory) -> tuple[bool, str]:
    if cat.id == "win_recycle":
        return _win_empty_recycle()
    if cat.needs_admin and IS_WIN and not is_admin():
        return False, "Precisa de executar como administrador."
    if cat.command:
        code, out = run_root(cat.command, timeout=900) if cat.needs_admin else run(cat.command, timeout=900, shell=True)
        return code == 0, (out[-400:] if out else "Feito")
    if cat.needs_admin and IS_LINUX and os.geteuid() != 0:
        targets = list(cat.targets())
        if not targets:
            return True, "Nada para limpar"
        code, out = run_root(["rm", "-rf", "--", *targets])
        return code == 0, out or "Feito"
    removed, failed = 0, 0
    cutoff = time.time() - cat.min_age_days * 86400
    for t in cat.targets():
        r, f = _remove(t, cat.min_age_days, cutoff)
        removed += r
        failed += f
    msg = f"{removed} itens apagados"
    if failed:
        msg += f", {failed} em uso ou sem permissão (ignorados)"
    return True, msg


def _remove(path: str, min_age: float, cutoff: float) -> tuple[int, int]:
    if os.path.isdir(path) and not os.path.islink(path):
        if not min_age:
            n = [0, 0]

            def onerr(*_a):
                n[1] += 1
            cnt = sum(len(f) for _r, _d, f in os.walk(path))
            if sys.version_info >= (3, 12):
                shutil.rmtree(path, onexc=onerr)
            else:
                shutil.rmtree(path, onerror=onerr)
            return max(cnt - n[1], 0), n[1]
        ok = bad = 0
        for root, _dirs, files in os.walk(path, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    if os.lstat(fp).st_mtime <= cutoff:
                        os.remove(fp)
                        ok += 1
                except OSError:
                    bad += 1
            if root != path:
                try:
                    os.rmdir(root)  # só remove subpastas que ficaram vazias
                except OSError:
                    pass
        return ok, bad
    try:
        if not min_age or os.lstat(path).st_mtime <= cutoff:
            os.remove(path)
            return 1, 0
    except OSError:
        return 0, 1
    return 0, 0


# --------------------------------------------------------------------------- Windows: reciclagem
def _win_recycle_size() -> int:
    if not IS_WIN:
        return 0
    import ctypes

    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("i64Size", ctypes.c_longlong), ("i64NumItems", ctypes.c_longlong)]
    info = SHQUERYRBINFO(ctypes.sizeof(SHQUERYRBINFO), 0, 0)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) == 0:
        return int(info.i64Size)
    return -2


def _win_empty_recycle() -> tuple[bool, str]:
    import ctypes
    flags = 0x1 | 0x2 | 0x4  # sem confirmação, sem progresso, sem som
    rc = ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, flags)
    return rc in (0, -2147418113), "Reciclagem esvaziada"  # E_UNEXPECTED = já vazia


# --------------------------------------------------------------------------- catálogos
def categories() -> list[CleanCategory]:
    if IS_WIN:
        L = "%LOCALAPPDATA%"
        cats = [
            CleanCategory("win_temp_user", "Temporários do utilizador", "Pasta %TEMP% (ficheiros com mais de 1 dia).",
                          [r"%TEMP%\*"], min_age_days=1),
            CleanCategory("win_temp_sys", "Temporários do Windows", r"C:\Windows\Temp.",
                          [r"%SystemRoot%\Temp\*"], needs_admin=True, min_age_days=1),
            CleanCategory("win_recycle", "Reciclagem", "Esvazia a Reciclagem de todas as unidades."),
            CleanCategory("win_update", "Cache do Windows Update",
                          "Atualizações já instaladas que ficaram descarregadas.",
                          [r"%SystemRoot%\SoftwareDistribution\Download\*"], needs_admin=True),
            CleanCategory("win_delivery", "Otimização de Entrega",
                          "Cache de partilha de atualizações entre PCs.",
                          [r"%SystemRoot%\ServiceProfiles\NetworkService\AppData\Local\Microsoft\Windows\DeliveryOptimization\Cache\*"],
                          needs_admin=True),
            CleanCategory("win_thumbs", "Cache de miniaturas", "O Explorador volta a criar as miniaturas.",
                          [L + r"\Microsoft\Windows\Explorer\thumbcache_*.db", L + r"\Microsoft\Windows\Explorer\iconcache_*.db"]),
            CleanCategory("win_wer", "Relatórios de erros e dumps", "Relatórios de crashes já enviados/antigos.",
                          [L + r"\CrashDumps\*", r"%ProgramData%\Microsoft\Windows\WER\ReportArchive\*",
                           r"%ProgramData%\Microsoft\Windows\WER\ReportQueue\*", L + r"\Microsoft\Windows\WER\*"]),
            CleanCategory("win_shader", "Cache de shaders (DirectX/NVIDIA/AMD)",
                          "Os jogos recompilam os shaders (1.º arranque um pouco mais lento).",
                          [L + r"\D3DSCache\*", L + r"\NVIDIA\DXCache\*", L + r"\NVIDIA\GLCache\*",
                           L + r"\AMD\DxCache\*", L + r"\AMD\DxcCache\*", L + r"\AMD\VkCache\*"], recommended=False),
            CleanCategory("win_browser", "Cache dos navegadores", "Chrome, Edge, Brave, Firefox, Opera (feche-os antes).",
                          [L + r"\Google\Chrome\User Data\*\Cache\*", L + r"\Google\Chrome\User Data\*\Code Cache\*",
                           L + r"\Microsoft\Edge\User Data\*\Cache\*", L + r"\Microsoft\Edge\User Data\*\Code Cache\*",
                           L + r"\BraveSoftware\Brave-Browser\User Data\*\Cache\*",
                           L + r"\Mozilla\Firefox\Profiles\*\cache2\*", r"%APPDATA%\Opera Software\*\Cache\*"],
                          recommended=False),
            CleanCategory("win_apps", "Cache de apps (Discord, Teams, Spotify, VS Code)", "Caches que as apps refazem.",
                          [r"%APPDATA%\discord\Cache\*", r"%APPDATA%\discord\Code Cache\*",
                           L + r"\Packages\MSTeams_*\LocalCache\Microsoft\MSTeams\EBWebView\*\Cache\*",
                           L + r"\Spotify\Storage\*", r"%APPDATA%\Code\Cache\*", r"%APPDATA%\Code\CachedData\*"]),
            CleanCategory("win_dev", "Cache de programação (pip, npm, NuGet)", "Pacotes descarregados que voltam a descarregar-se.",
                          [L + r"\pip\Cache\*", L + r"\npm-cache\*", r"%USERPROFILE%\.nuget\packages\*",
                           L + r"\Yarn\Cache\*"], recommended=False),
            CleanCategory("win_logs", "Logs antigos do Windows", "CBS/DISM e logs de instalação com mais de 7 dias.",
                          [r"%SystemRoot%\Logs\CBS\*.log", r"%SystemRoot%\Logs\DISM\*.log", r"%SystemRoot%\Panther\*.log"],
                          needs_admin=True, min_age_days=7),
            CleanCategory("win_winsxs", "Limpeza de componentes (WinSxS)",
                          "Remove versões antigas de componentes do Windows (DISM). Demora vários minutos.",
                          command="Dism.exe /Online /Cleanup-Image /StartComponentCleanup", needs_admin=True,
                          recommended=False),
        ]
        if os.path.isdir(os.path.expandvars(r"%SystemDrive%\Windows.old")):
            cats.append(CleanCategory("win_old", "Windows.old (instalação anterior)",
                                      "Só se não pretende voltar à versão anterior do Windows.",
                                      [r"%SystemDrive%\Windows.old"], needs_admin=True, recommended=False,
                                      command=r'takeown /F "%SystemDrive%\Windows.old" /R /A /D Y >nul & '
                                              r'icacls "%SystemDrive%\Windows.old" /grant *S-1-5-32-544:F /T /C /Q >nul & '
                                              r'rd /s /q "%SystemDrive%\Windows.old"'))
        return _annotate(cats)

    # ------------------------------------------------------------------ Linux
    cats = [
        CleanCategory("lx_trash", "Lixo", "Ficheiros que estão no Lixo.",
                      ["~/.local/share/Trash/files/*", "~/.local/share/Trash/info/*", "~/.local/share/Trash/expunged/*"]),
        CleanCategory("lx_thumbs", "Cache de miniaturas", "O gestor de ficheiros volta a criá-las.",
                      ["~/.cache/thumbnails/*"]),
        CleanCategory("lx_browser", "Cache dos navegadores", "Firefox, Chrome, Chromium, Brave, Vivaldi, Opera (feche-os antes).",
                      ["~/.cache/mozilla/firefox/*/cache2", "~/.cache/google-chrome/*/Cache", "~/.cache/google-chrome/*/Code Cache",
                       "~/.cache/chromium/*/Cache", "~/.cache/BraveSoftware/Brave-Browser/*/Cache",
                       "~/.cache/BraveSoftware/Brave-Browser/*/Code Cache", "~/.cache/vivaldi/*/Cache",
                       "~/.cache/opera/Cache", "~/.var/app/*/cache/*/Cache"], recommended=False),
        CleanCategory("lx_apps", "Cache de apps Electron (Discord, VS Code, Teams, Slack)", "Caches que as apps refazem.",
                      ["~/.config/discord/Cache", "~/.config/discord/Code Cache", "~/.config/Code/Cache",
                       "~/.config/Code/CachedData", "~/.config/code-oss/Cache", "~/.config/Code - OSS/CachedData",
                       "~/.config/teams-for-linux/Partitions/*/Cache", "~/.config/Slack/Cache",
                       "~/.config/Slack/Service Worker/CacheStorage", "~/.config/spotify/Data"]),
        CleanCategory("lx_dev", "Cache de programação", "pip, npm, yarn, pnpm, go, Gradle — voltam a descarregar quando preciso.",
                      ["~/.cache/pip", "~/.npm/_cacache", "~/.cache/yarn", "~/.local/share/pnpm/store",
                       "~/.cache/go-build", "~/.gradle/caches", "~/.cache/pypoetry/cache", "~/.cache/uv"],
                      recommended=False),
        CleanCategory("lx_aur", "Cache de compilação do AUR (paru/yay)", "Repositórios e pacotes compilados do AUR.",
                      ["~/.cache/paru/clone/*", "~/.cache/yay/*"]),
        CleanCategory("lx_shader", "Cache de shaders (Mesa/NVIDIA)", "Jogos recompilam os shaders no 1.º arranque.",
                      ["~/.cache/mesa_shader_cache", "~/.cache/mesa_shader_cache_db", "~/.cache/radv_builtin_shaders*",
                       "~/.cache/nvidia/GLCache", "~/.nv/GLCache"], recommended=False),
        CleanCategory("lx_coredump", "Core dumps", "Relatórios de crash do systemd-coredump.",
                      ["/var/lib/systemd/coredump/*"], needs_admin=True),
    ]
    if which("pacman"):
        cmd = "paccache -rk1 && paccache -ruk0" if which("paccache") else "pacman -Sc --noconfirm"
        cats.append(CleanCategory("lx_pacman", "Pacotes antigos do pacman",
                                  "Mantém só a última versão de cada pacote" + ("" if which("paccache") else
                                                                                " (instale pacman-contrib para manter 1 versão)") + ".",
                                  [], command=cmd,
                                  size_command=["sh", "-c", "paccache -dk1 2>&1 | grep 'disk space'"]
                                  if which("paccache") else None, needs_admin=True))
    if which("apt-get"):
        cats.append(CleanCategory("lx_apt", "Cache do APT", "Pacotes .deb já instalados + dependências órfãs.",
                                  ["/var/cache/apt/archives/*.deb"], command="apt-get clean && apt-get -y autoremove",
                                  needs_admin=True))
    if which("dnf"):
        cats.append(CleanCategory("lx_dnf", "Cache do DNF", "Metadados e pacotes descarregados.",
                                  ["/var/cache/dnf/*"], command="dnf clean all", needs_admin=True))
    if which("zypper"):
        cats.append(CleanCategory("lx_zypper", "Cache do Zypper", "Pacotes descarregados.",
                                  ["/var/cache/zypp/packages/*"], command="zypper clean --all", needs_admin=True))
    if which("journalctl"):
        cats.append(CleanCategory("lx_journal", "Logs do sistema (journal)", "Reduz os logs para no máximo 200 MB.",
                                  command="journalctl --vacuum-size=200M", size_command=["journalctl", "--disk-usage"],
                                  needs_admin=True))
    if which("flatpak"):
        cats.append(CleanCategory("lx_flatpak", "Runtimes Flatpak sem uso", "Remove runtimes que nenhuma app usa.",
                                  command="flatpak uninstall --unused -y --noninteractive"))
    if which("docker"):
        cats.append(CleanCategory("lx_docker", "Docker: imagens e contentores parados",
                                  "docker system prune (não apaga volumes).", command="docker system prune -f",
                                  recommended=False))
    snap = Path("/var/lib/snapd/snaps")
    if snap.is_dir():
        cats.append(CleanCategory("lx_snap", "Versões antigas de Snaps", "Remove revisões desativadas.",
                                  command="snap list --all | awk '/disabled/{print $1, $3}' | "
                                          "while read n r; do snap remove \"$n\" --revision=\"$r\"; done",
                                  needs_admin=True))
    return _annotate(cats)


# (cuidado?, nota) — o que acontece ao limpar cada categoria
_NOTES = {
    "lx_trash": (True, "Apaga de vez o que está no Lixo — veja antes se não há lá nada que queira."),
    "win_recycle": (True, "Apaga de vez o que está na Reciclagem — veja antes se não há lá nada que queira."),
    "lx_thumbs": (False, "Seguro: as miniaturas voltam a ser criadas."),
    "win_thumbs": (False, "Seguro: as miniaturas voltam a ser criadas."),
    "lx_browser": (False, "Seguro: não apaga palavras-passe, histórico nem sessões. Feche o navegador antes."),
    "win_browser": (False, "Seguro: não apaga palavras-passe, histórico nem sessões. Feche o navegador antes."),
    "lx_apps": (False, "Seguro: as apps refazem a cache. Feche-as antes."),
    "win_apps": (False, "Seguro: as apps refazem a cache. Feche-as antes."),
    "lx_dev": (False, "Seguro: os pacotes voltam a ser descarregados na próxima instalação."),
    "win_dev": (False, "Seguro: os pacotes voltam a ser descarregados na próxima instalação."),
    "lx_aur": (False, "Seguro: o paru/yay volta a descarregar e compilar quando atualizar."),
    "lx_shader": (False, "Seguro: os jogos podem engasgar um pouco no 1.º arranque enquanto recompilam."),
    "win_shader": (False, "Seguro: os jogos podem engasgar um pouco no 1.º arranque enquanto recompilam."),
    "lx_coredump": (False, "Seguro: só relatórios de programas que já falharam."),
    "win_wer": (False, "Seguro: só relatórios de programas que já falharam."),
    "lx_pacman": (False, "Seguro: os programas instalados não são tocados. Só deixa de poder voltar a uma versão "
                         "anterior sem internet (se uma atualização correr mal, use os snapshots ou volte a "
                         "descarregar a versão antiga)."),
    "lx_apt": (True, "Os .deb guardados são seguros; o 'autoremove' remove pacotes órfãos — confira a lista no "
                     "terminal se tiver dúvidas."),
    "lx_dnf": (False, "Seguro: metadados e pacotes voltam a ser descarregados."),
    "lx_zypper": (False, "Seguro: pacotes voltam a ser descarregados."),
    "lx_journal": (False, "Seguro: perde só logs antigos (úteis apenas para investigar problemas passados)."),
    "lx_flatpak": (False, "Seguro: só runtimes que nenhuma app instalada usa."),
    "lx_docker": (True, "Apaga contentores parados e imagens sem uso — os volumes (dados) ficam."),
    "lx_snap": (False, "Seguro: só versões antigas desativadas."),
    "win_temp_user": (False, "Seguro: só temporários com mais de 1 dia; ficheiros em uso são ignorados."),
    "win_temp_sys": (False, "Seguro: só temporários com mais de 1 dia; ficheiros em uso são ignorados."),
    "win_update": (False, "Seguro: atualizações já instaladas; o Windows volta a descarregar se precisar."),
    "win_delivery": (False, "Seguro: cache de partilha de atualizações."),
    "win_logs": (False, "Seguro: logs com mais de 7 dias."),
    "win_winsxs": (True, "Seguro, mas depois deixa de poder desinstalar as atualizações já instaladas. Demora."),
    "win_old": (True, "Deixa de poder voltar à versão anterior do Windows."),
}


def _annotate(cats: list[CleanCategory]) -> list[CleanCategory]:
    for c in cats:
        c.caution, c.note = _NOTES.get(c.id, (False, "Seguro."))
    return cats
