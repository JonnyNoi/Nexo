"""Classifica pastas/ficheiros pela segurança de os apagar (Windows e Linux).

Níveis:
  SAFE    — pode apagar: caches, temporários, lixo, logs, dependências de projetos…
  APP     — jogos e programas: seguro remover, de preferência pelo launcher/desinstalador
  REVIEW  — dados pessoais ou de apps: veja antes de apagar
  SYSTEM  — sistema operativo: NÃO apagar

As regras usam um glob simples sobre o caminho normalizado (minúsculas, '/', sem letra de unidade,
pasta pessoal = '~'): '*' = um nível, '**' = qualquer profundidade, '{a,b}' = alternativas.
Ganha a regra que casa com a parte mais longa do caminho; regras "em qualquer lado" ('**/…') não
sobrepõem uma regra de sistema (ex.: uma pasta 'cache' dentro de System32 continua a ser sistema).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .util import IS_WIN

SAFE, APP, REVIEW, SYSTEM, UNKNOWN = "safe", "app", "review", "system", ""

LEVELS = {
    SAFE: ("Seguro apagar", "ok"),
    APP: ("Seguro (desinstalar)", "info"),
    REVIEW: ("Rever antes", "warn"),
    SYSTEM: ("Sistema — não apagar", "bad"),
    UNKNOWN: ("—", "muted"),
}
LEVEL_ORDER = [SAFE, APP, REVIEW, SYSTEM, UNKNOWN]

CACHE_ROOT_REASON = "Cache das aplicações — elas voltam a criá-la (feche as apps antes)"

# (padrão, nível, motivo, marcas)  marcas: "group" = contentor (as recomendações descem aos filhos),
# "game" = jogo (procura o nome na Steam), "dev" = dependências de programação
_HOME = "~/{downloads,transferências,transferencias}"
_RULES: list[tuple[str, str, str, str]] = [
    # ------------------------------------------------------------------ pasta pessoal (ambos)
    ("~", REVIEW, "Pasta pessoal — os seus ficheiros; reveja antes de apagar", ""),
    (_HOME, REVIEW, "Transferências — instaladores e arquivos antigos costumam poder ir (veja 'Pode ser apagado')", ""),
    ("~/{documents,documentos,desktop,área de trabalho,ambiente de trabalho,secretária}", REVIEW,
     "Documentos pessoais — não apagar sem ver", ""),
    ("~/{pictures,imagens,fotografias,videos,vídeos,music,música,musica}", REVIEW,
     "Fotos / vídeos / música pessoais — faça cópia antes de apagar", ""),
    ("~/onedrive*", REVIEW, "OneDrive — apagar aqui também apaga na nuvem", ""),
    ("~/{dropbox,google drive,mega,nextcloud}", REVIEW, "Pasta sincronizada com a nuvem — apagar aqui apaga lá", ""),
    ("~/{.ssh,.gnupg,.password-store,.pki}", SYSTEM, "Chaves e certificados — NUNCA apagar", ""),
    ("~/{ntuser.dat,ntuser.dat.log1,ntuser.dat.log2,ntuser.ini}", SYSTEM, "Registo do seu utilizador — NÃO apagar", ""),
    ("~/.cache", SAFE, CACHE_ROOT_REASON, ""),
    ("~/.cache/{thumbnails,mesa_shader_cache,nvidia,fontconfig,pip,yay,paru,go-build,mozilla,chromium,"
     "google-chrome,spotify,jetbrains,electron,ms-playwright,huggingface}", SAFE, "Cache — volta a ser criada", ""),
    ("~/.local/share/trash", SAFE, "Lixo — esvazie (Limpeza rápida)", ""),
    ("~/.local/share", REVIEW, "Dados das aplicações (jogos guardados, bases de dados…) — não apagar em bloco", ""),
    ("~/.local/share/{recently-used.xbel,baloo,tracker,tracker3}", SAFE, "Índices / histórico — recriam-se", ""),
    ("~/.local/share/steam", APP, "Steam (cliente e jogos) — remova os jogos pela Steam", "group"),
    ("~/.steam", APP, "Steam — remova os jogos pela Steam", "group"),
    ("~/.local/share/{lutris,bottles,heroic}", APP, "Launcher de jogos — remova os jogos pelo próprio launcher", "group"),
    ("~/.var/app/com.valvesoftware.steam", APP, "Steam (Flatpak) — remova os jogos pela Steam", "group"),
    ("~/{games,jogos}", APP, "Jogos instalados — seguro remover os que já não joga", "group"),
    ("~/{games,jogos}/*", APP, "Jogo — seguro remover se já não joga (as gravações podem estar aqui)", "game"),
    ("~/games/heroic", APP, "Jogos do Heroic (Epic/GOG) — desinstale pelo Heroic", "group"),
    ("~/games/heroic/*", APP, "Jogo do Heroic — desinstale pelo Heroic", "game"),
    ("~/.local/share/lutris/runners", APP, "Runners do Lutris (Wine/Proton) — o Lutris volta a transferir", ""),
    ("~/.wine", APP, "Prefixo Wine — contém os programas Windows instalados nele", ""),
    ("**/{wineprefix,pfx,drive_c,dosdevices}", APP, "Prefixo Wine — contém programas Windows instalados, não é cache", ""),
    ("~/.local/share/flatpak", APP, "Apps Flatpak do utilizador — 'flatpak uninstall --unused' remove o que sobra", ""),
    ("~/.var/app", APP, "Dados das apps Flatpak — apague a pasta de uma app que já desinstalou", "group"),
    ("~/.var/app/*/cache", SAFE, "Cache de uma app Flatpak — volta a ser criada", ""),
    ("~/.config", REVIEW, "Definições das aplicações — não apagar sem saber o que é", ""),
    ("~/{.mozilla,.thunderbird,.config/google-chrome,.config/chromium,.config/bravesoftware,.config/microsoft-edge,"
     ".config/vivaldi}", REVIEW, "Perfil do navegador / e-mail (marcadores, palavras-passe) — não apagar", ""),
    ("~/.local/share/containers", REVIEW, "Imagens do Podman — use 'podman system prune'", ""),
    ("~/.local/share/gnome-boxes", REVIEW, "Máquinas virtuais (GNOME Boxes) — apague a VM se já não usa", ""),
    ("~/.npm", SAFE, "Cache do npm — volta a transferir quando precisar", "dev"),
    ("~/{.yarn/cache,.pnpm-store,.local/share/pnpm/store,.bun/install/cache}", SAFE, "Cache de pacotes JS", "dev"),
    ("~/.cargo/registry", SAFE, "Cache de crates do Rust — 'cargo cache' / volta a transferir", "dev"),
    ("~/.cargo/git", SAFE, "Cache git do Cargo — volta a transferir", "dev"),
    ("~/.local/lib", REVIEW, "Pacotes instalados para o seu utilizador (pip/npm) — remova pelo pip/npm", ""),
    ("~/.local/lib/node_modules", APP, "Pacotes npm globais — 'npm uninstall -g <pacote>'", "dev"),
    ("~/.rustup", APP, "Toolchains do Rust — 'rustup toolchain uninstall <versão>' para as antigas", "dev"),
    ("~/{.gradle/caches,.gradle/wrapper/dists,.m2/repository,.nuget/packages,go/pkg/mod,.ivy2/cache,.sbt,"
     ".conda/pkgs,miniconda3/pkgs,anaconda3/pkgs,.platformio/.cache,.expo,.android/cache}",
     SAFE, "Cache de pacotes de programação — volta a transferir", "dev"),
    ("~/{android/sdk,appdata/local/android/sdk}", APP, "Android SDK — remova versões antigas no SDK Manager", "dev"),
    ("~/.android/avd", REVIEW, "Emuladores Android — apague os que não usa no Device Manager", "dev"),
    ("~/{virtualbox vms,vmware,vms}", REVIEW, "Máquinas virtuais — apague as VMs que já não usa", ""),
    # ------------------------------------------------------------------ pasta pessoal (Windows)
    ("~/appdata", REVIEW, "Definições e dados das aplicações — não apagar em bloco", ""),
    ("~/appdata/local", REVIEW, "Dados locais das aplicações — só caches e temporários são seguros", ""),
    ("~/appdata/roaming", REVIEW, "Definições das aplicações (perfis, jogos guardados) — não apagar", ""),
    ("~/appdata/local/temp", SAFE, "Temporários do utilizador — seguro apagar (Limpeza rápida)", ""),
    ("~/appdata/local/{crashdumps,microsoft/windows/wer,squirreltemp}", SAFE, "Relatórios de erros / temporários", ""),
    ("~/appdata/local/microsoft/windows/{inetcache,explorer,webcache,inetcookies}", SAFE,
     "Cache do Windows (miniaturas, Internet) — volta a ser criada", ""),
    ("~/appdata/local/{d3dscache,nvidia,amd,intel/shadercache,nvidia corporation/nv_cache}", SAFE,
     "Cache de shaders da placa gráfica — volta a ser criada", ""),
    ("~/appdata/local/packages", APP, "Dados das apps da Microsoft Store — remova a app nas Definições", "group"),
    ("~/appdata/local/packages/*/{ac/temp,localcache,tempstate}", SAFE, "Cache de uma app da Store", ""),
    ("~/appdata/local/microsoft/windowsapps", SYSTEM, "Atalhos das apps da Store — não apagar", ""),
    ("~/appdata/local/programs", APP, "Programas instalados só para si — desinstale nas Definições", "group"),
    ("~/appdata/local/programs/*", APP, "Programa instalado — desinstale em Definições › Aplicações", ""),
    ("~/appdata/local/{pip/cache,npm-cache,yarn/cache,nuget/v3-cache,go-build,electron/cache}", SAFE,
     "Cache de programação — volta a ser criada", "dev"),
    ("~/appdata/roaming/npm-cache", SAFE, "Cache do npm", "dev"),
    ("~/appdata/local/{google/chrome,microsoft/edge,bravesoftware,vivaldi}/user data", REVIEW,
     "Perfil do navegador (marcadores, palavras-passe) — não apagar; a cache dentro dele é segura", ""),
    ("~/appdata/roaming/mozilla", REVIEW, "Perfil do Firefox — não apagar", ""),
    ("~/appdata/local/mozilla/firefox/profiles/*/cache2", SAFE, "Cache do Firefox", ""),
    # ------------------------------------------------------------------ Windows (unidade do sistema)
    ("/windows", SYSTEM, "Pasta do Windows — NÃO apagar nada à mão", ""),
    ("/windows/{system32,syswow64,sysnative}", SYSTEM, "Ficheiros vitais do Windows — NÃO apagar", ""),
    ("/windows/winsxs", SYSTEM, "Componentes do Windows — não apagar; use 'Limpar componentes (DISM)' em Utilitários", ""),
    ("/windows/installer", SYSTEM, "Cache de instaladores MSI — apagar parte desinstalações e atualizações", ""),
    ("/windows/{servicing,assembly,microsoft.net,fonts,systemapps,immersivecontrolpanel,boot,inf,"
     "systemresources,shellexperiences,globalization,diagnostics,security,policydefinitions}",
     SYSTEM, "Componente do Windows — NÃO apagar", ""),
    ("/windows/{temp,downloaded program files,ccmcache}", SAFE, "Temporários do Windows — seguro apagar (Limpeza rápida)", ""),
    ("/windows/softwaredistribution", SYSTEM, "Windows Update — use 'Repor Windows Update' em Utilitários", ""),
    ("/windows/softwaredistribution/{download,deliveryoptimization}", SAFE,
     "Transferências do Windows Update — seguro apagar (Limpeza rápida)", ""),
    ("/windows/{logs,panther,minidump,livekernelreports,memory.dmp,prefetch}", SAFE,
     "Logs / relatórios de erro / cache de arranque — o Windows recria", ""),
    ("/windows/system32/{logfiles,winevt/logs}", REVIEW, "Registos do sistema — limpe pelo Visualizador de Eventos", ""),
    ("/windows.old", SAFE, "Windows anterior — remova com a Limpeza rápida (perde a opção de voltar atrás)", ""),
    ("/{$windows.~bt,$windows.~ws,$winreagent,$getcurrent,$sysreset,esd}", SAFE,
     "Restos de atualizações do Windows — seguro remover com a Limpeza de Disco", ""),
    ("/$recycle.bin", SAFE, "Reciclagem — esvazie", ""),
    ("/system volume information", SYSTEM, "Pontos de restauro — gira em Proteção do Sistema, não apague", ""),
    ("/pagefile.sys", SYSTEM, "Memória virtual — NÃO apagar (ajuste em Sistema › Definições avançadas)", ""),
    ("/swapfile.sys", SYSTEM, "Memória virtual das apps — NÃO apagar", ""),
    ("/hiberfil.sys", SYSTEM, "Hibernação — liberta-se desligando a hibernação (Otimização), não apagando", ""),
    ("/{recovery,boot,efi,bootmgr,bootnxt,$winre_backup_partition.marker,dumpstack.log.tmp,documents and settings,"
     "config.msi,$sysreset}", SYSTEM, "Arranque / recuperação do Windows — NÃO apagar", ""),
    ("/{program files,program files (x86)}", SYSTEM, "Programas instalados — desinstale pelas Definições, não apague a pasta", "group"),
    ("/{program files,program files (x86)}/*", APP, "Programa instalado — desinstale em Definições › Aplicações", ""),
    ("/{program files,program files (x86)}/{windowsapps,common files,windows defender,windows defender advanced threat protection,"
     "windows nt,windows mail,windows media player,windows photo viewer,windows portable devices,windows security,"
     "windows sidebar,windowspowershell,internet explorer,microsoft update health tools,modifiablewindowsapps,"
     "reference assemblies,msbuild,dotnet,microsoft.net,windows kits,uninstall information}",
     SYSTEM, "Componente do Windows / partilhado — NÃO apagar", ""),
    ("/{program files,program files (x86)}/{steam,epic games,gog galaxy,ubisoft,ea games,ea,electronic arts,"
     "riot games,battle.net,rockstar games}", APP, "Launcher de jogos — remova os jogos pelo launcher", "group"),
    ("/programdata", SYSTEM, "Dados partilhados dos programas — não apagar à mão", ""),
    ("/programdata/package cache", SYSTEM, "Cache de instaladores — necessária para desinstalar/reparar programas", ""),
    ("/programdata/microsoft/windows/wer", SAFE, "Relatórios de erros do Windows — seguro apagar", ""),
    ("/programdata/{nvidia corporation/downloader,nvidia corporation/nv_cache,amd/dxcache,amd/dx9cache}", SAFE,
     "Cache / transferências de drivers da placa gráfica", ""),
    ("/users", REVIEW, "Pastas pessoais de todos os utilizadores", ""),
    ("/users/{public,default,default user,all users}", SYSTEM, "Perfil partilhado/modelo do Windows — não apagar", ""),
    ("/{perflogs,intel,amd,nvidia,msocache,swsetup,drivers,onedrivetemp}", SAFE,
     "Restos de instalações de drivers / logs — normalmente seguro apagar", ""),
    ("/{xboxgames,xbox games}", APP, "Jogos Xbox / Game Pass — desinstale pela app Xbox", "group"),
    ("/{xboxgames,xbox games}/*", APP, "Jogo Xbox / Game Pass — desinstale pela app Xbox", "game"),
    # ------------------------------------------------------------------ Linux
    ("/{usr,bin,sbin,lib,lib32,lib64,libx32,etc}", SYSTEM, "Sistema operativo — NÃO apagar (remova pacotes pelo gestor)", ""),
    ("/{boot,efi}", SYSTEM, "Arranque (kernel, bootloader) — NÃO apagar", ""),
    ("/{root,srv,sys,proc,dev,run}", SYSTEM, "Sistema — NÃO apagar", ""),
    ("/{swapfile,swap,swap.img}", SYSTEM, "Ficheiro de swap — NÃO apagar (desative-o primeiro)", ""),
    ("/.snapshots", SYSTEM, "Snapshots btrfs — gira-os com o Snapper/btrfs-assistant, não apague à mão", ""),
    ("/home", REVIEW, "Pastas pessoais de todos os utilizadores", ""),
    ("/opt", APP, "Programas instalados à parte — desinstale pelo gestor de pacotes", "group"),
    ("/opt/*", APP, "Programa instalado — desinstale pelo gestor de pacotes", ""),
    ("/var", SYSTEM, "Dados variáveis do sistema — não apagar em bloco", ""),
    ("/var/lib", SYSTEM, "Estado dos pacotes e serviços — NÃO apagar", ""),
    ("/var/lib/flatpak", APP, "Apps Flatpak — remova em 'Instalar aplicações' ou 'flatpak uninstall --unused'", ""),
    ("/var/lib/snapd", APP, "Apps Snap — 'snap remove' as que não usa", ""),
    ("/var/lib/{docker,containers}", REVIEW, "Contentores/imagens — 'docker system prune' (Limpeza rápida)", ""),
    ("/var/lib/libvirt/images", REVIEW, "Discos de máquinas virtuais — apague as VMs que não usa", ""),
    ("/var/lib/systemd/coredump", SAFE, "Relatórios de crash — seguro apagar", ""),
    ("/var/cache", SAFE, "Cache do sistema — use a Limpeza rápida (precisa de admin)", ""),
    ("/var/cache/{pacman/pkg,apt/archives,dnf,yum,zypp/packages,xbps}", SAFE,
     "Pacotes já instalados guardados — seguro limpar (Limpeza rápida)", ""),
    ("/var/{log,tmp,crash}", SAFE, "Logs / temporários / relatórios de crash — seguro limpar (Limpeza rápida)", ""),
    ("/var/log/journal", SAFE, "Journal do systemd — reduza com a Limpeza rápida (journalctl --vacuum)", ""),
    ("/tmp", SAFE, "Temporários — limpam-se ao reiniciar", ""),
    ("/{mnt,media}", REVIEW, "Outros discos montados", ""),
    # ------------------------------------------------------------------ em qualquer lado
    ("**/lost+found", SYSTEM, "Recuperação do sistema de ficheiros — não apagar", ""),
    ("**/system volume information", SYSTEM, "Pontos de restauro — não apagar", ""),
    ("**/windows/{system32,syswow64,winsxs}", SYSTEM, "Ficheiros do Windows (outro disco) — NÃO apagar", ""),
    ("**/{$recycle.bin,.trash-*,.trashes}", SAFE, "Reciclagem / lixo desta unidade — esvazie", ""),
    ("**/{cache,caches,cache2,code cache,gpucache,shadercache,dxcache,glcache,cache_data,grshadercache,dawncache,"
     "dawngraphitecache,dawnwebgpucache,service worker/cachestorage,crashpad/completed,crash reports}", SAFE,
     "Cache — volta a ser criada (feche a aplicação antes)", ""),
    ("**/{node_modules,__pycache__,.venv,venv,.tox,.mypy_cache,.pytest_cache,.ruff_cache,.next,.nuxt,"
     ".parcel-cache,.turbo,.angular,.gradle,.dart_tool,.svelte-kit,bower_components}", SAFE,
     "Dependências/cache de projeto — reinstala-se com npm/pip quando precisar", "dev"),
    ("**/.git", REVIEW, "Histórico do repositório git — não apagar", "dev"),
    ("**/{steamapps,steamlibrary,steam library}", APP, "Biblioteca da Steam — remova os jogos pela Steam", "group"),
    ("**/steamapps/common", APP, "Jogos da Steam — seguro remover os que já não joga", "group"),
    ("**/steamapps/common/*", APP, "Jogo da Steam — seguro remover (desinstale pela Steam)", "game"),
    ("**/steamapps/common/{steamworks shared,steam controller configs,steamlinuxruntime,steamlinuxruntime_soldier,"
     "steamlinuxruntime_sniper,proton*}", APP, "Componente da Steam/Proton — a Steam volta a instalar se precisar", ""),
    ("**/steamapps/{shadercache,downloading,temp}", SAFE, "Cache / transferências da Steam — a Steam volta a criar", ""),
    ("**/steamapps/workshop", APP, "Mods da Workshop — cancele a subscrição na Steam", ""),
    ("**/steamapps/compatdata", REVIEW, "Prefixos Proton — podem ter gravações dos jogos", ""),
    ("**/{epic games,gog games,gog galaxy/games,riot games,ea games,ubisoft game launcher/games,"
     "rockstar games,battlestate games,xboxgames}", APP, "Jogos instalados — desinstale pelo launcher", "group"),
    ("**/{epic games,gog games,gog galaxy/games,riot games,ea games,ubisoft game launcher/games,rockstar games,"
     "battlestate games,xboxgames}/*", APP, "Jogo — seguro remover; desinstale pelo launcher", "game"),
    ("**/{virtualbox vms,vmware virtual machines}", REVIEW, "Máquinas virtuais — apague as VMs que já não usa", ""),
]


def _expand(pat: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", pat)
    if not m:
        return [pat]
    out = []
    for alt in m.group(1).split(","):
        out += _expand(pat[:m.start()] + alt + pat[m.end():])
    return out


def _seg(s: str) -> str:
    if s == "*":
        return "[^/]+"
    return "".join("[^/]*" if c == "*" else re.escape(c) for c in s)


@dataclass
class _Rule:
    rx: re.Pattern
    level: str
    reason: str
    flags: str
    anywhere: bool
    spec: int  # nº de caracteres literais: em empate de comprimento ganha a regra mais específica


def _compile() -> dict[str, list[_Rule]]:
    groups: dict[str, list[_Rule]] = {}
    for pat, level, reason, flags in _RULES:
        for p in _expand(pat.lower()):
            segs = p.split("/")
            anywhere = segs[0] == "**"
            if anywhere:
                body = "(?:.*/)?" + "/".join(_seg(s) for s in segs[1:])
                key = "*"
            else:
                body = "/".join(_seg(s) if s != "~" else "~" for s in segs)
                key = "~" if segs[0] == "~" else (segs[1] if len(segs) > 1 else "")
            rx = re.compile("^" + body + "(?=/|$)")
            groups.setdefault(key, []).append(_Rule(rx, level, reason, flags, anywhere, len(p.replace('*', ''))))
    return groups


_GROUPS = _compile()
_HOME_NORM = str(Path.home()).replace("\\", "/").lower().rstrip("/")
_WIN_SHARED = {"public", "default", "default user", "all users"}


def normalize(path: str) -> str:
    p = path.replace("\\", "/").lower().rstrip("/")
    if IS_WIN or (len(p) >= 2 and p[1] == ":"):
        if len(p) >= 2 and p[1] == ":":
            p = p[2:]
        m = re.match(r"/users/([^/]+)", p)
        if m and m.group(1) not in _WIN_SHARED:
            p = "~" + p[m.end():]
        return p
    if p == _HOME_NORM or p.startswith(_HOME_NORM + "/"):
        return "~" + p[len(_HOME_NORM):]
    m = re.match(r"/home/[^/]+", p)
    if m and p != "/home":
        return "~" + p[m.end():]
    return p


@dataclass
class Verdict:
    level: str = UNKNOWN
    reason: str = ""
    flags: str = ""
    steam_appid: str = ""
    name: str = ""      # nome legível (ex.: nome do jogo da Steam)
    extra: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return LEVELS[self.level][0]

    @property
    def color(self) -> str:
        return LEVELS[self.level][1]

    @property
    def is_game(self) -> bool:
        return "game" in self.flags


_steam_cache: dict[str, dict[str, tuple[str, str]]] = {}


def steam_games(steamapps: str) -> dict[str, tuple[str, str]]:
    """{installdir em minúsculas: (appid, nome)} lido dos appmanifest_*.acf."""
    if steamapps in _steam_cache:
        return _steam_cache[steamapps]
    out: dict[str, tuple[str, str]] = {}
    try:
        for f in os.listdir(steamapps):
            if f.startswith("appmanifest_") and f.endswith(".acf"):
                try:
                    txt = Path(steamapps, f).read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                kv = dict(re.findall(r'^\s*"(appid|name|installdir)"\s+"([^"]*)"', txt, re.M | re.I))
                kv = {k.lower(): v for k, v in kv.items()}
                if kv.get("installdir"):
                    out[kv["installdir"].lower()] = (kv.get("appid", ""), kv.get("name", ""))
    except OSError:
        pass
    _steam_cache[steamapps] = out
    return out


def classify(path: str, is_dir: bool | None = None) -> Verdict:
    p = normalize(path)
    if not p:
        return Verdict()
    key = "~" if p.startswith("~") else p.split("/")[1] if p.count("/") >= 1 else ""
    best = None   # (end, rule)
    for r in _GROUPS.get(key, ()):
        m = r.rx.match(p)
        if m and (best is None or (m.end(), r.spec) > (best[0], best[1].spec)):
            best = (m.end(), r)
    any_best = None
    for r in _GROUPS.get("*", ()):
        m = r.rx.match(p)
        if m and (any_best is None or (m.end(), r.spec) > (any_best[0], any_best[1].spec)):
            any_best = (m.end(), r)
    if any_best and (best is None or (any_best[0] > best[0] and
                                      (best[1].level != SYSTEM or any_best[1].level == SYSTEM))):
        best = any_best
    v = Verdict()
    if best:
        r = best[1]
        v = Verdict(r.level, r.reason, r.flags if best[0] == len(p) else r.flags.replace("group", ""))
        # um ficheiro/pasta DENTRO de um jogo/programa herda o nível mas não é ele próprio "o jogo"
        if best[0] != len(p):
            v.flags = v.flags.replace("game", "")
    # compilação Rust: pasta target ao lado de um Cargo.toml
    base = os.path.basename(path.rstrip("/\\"))
    if base == "target" and v.level in (UNKNOWN, REVIEW) and os.path.isfile(os.path.join(os.path.dirname(path), "Cargo.toml")):
        v = Verdict(SAFE, "Compilação Rust — 'cargo clean' liberta isto", "dev")
    if v.is_game and "/steamapps/common/" in p:
        common = os.path.dirname(path.rstrip("/\\"))
        info = steam_games(os.path.dirname(common)).get(base.lower())
        if info:
            v.steam_appid, v.name = info
            v.reason = f"Jogo da Steam «{info[1]}» — seguro remover: desinstale pela Steam"
    return v
