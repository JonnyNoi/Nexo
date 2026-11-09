"""Análise de espaço em disco: maiores ficheiros e pastas, tipos, duplicados e sugestões."""
from __future__ import annotations

import hashlib
import heapq
import os
import stat
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import disksafety as ds
from .util import IS_WIN, human_bytes

TYPES = {
    "Vídeo": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".ts", ".mts"},
    "Imagens": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".heic", ".raw", ".cr2", ".nef", ".tif", ".tiff", ".psd", ".svg"},
    "Áudio": {".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".opus", ".wma"},
    "Arquivos comprimidos": {".zip", ".rar", ".7z", ".tar", ".gz", ".xz", ".zst", ".bz2", ".tgz"},
    "Instaladores / imagens de disco": {".iso", ".img", ".exe", ".msi", ".dmg", ".deb", ".rpm", ".appimage", ".vhd", ".vhdx", ".vdi", ".vmdk", ".qcow2"},
    "Documentos": {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".odt", ".ods", ".txt", ".epub", ".md"},
    "Código / programação": {".py", ".js", ".ts", ".c", ".cpp", ".h", ".rs", ".go", ".java", ".class", ".jar", ".o", ".so", ".dll", ".a", ".lib", ".pyc", ".node"},
    "Jogos / dados": {".pak", ".vpk", ".bin", ".dat", ".assets", ".bundle", ".wad", ".pck", ".ucas", ".utoc"},
    "Logs / temporários": {".log", ".tmp", ".temp", ".bak", ".old", ".dmp", ".etl", ".swp", ".crdownload", ".part"},
}
EXT_TYPE = {e: t for t, exts in TYPES.items() for e in exts}

_SKIP_LINUX = {"/proc", "/sys", "/dev", "/run", "/tmp/.X11-unix", "/var/lib/docker/overlay2", "/snap"}
_DEV_DIRS = {"node_modules", "__pycache__", ".venv", "venv", ".gradle", ".tox", ".mypy_cache", ".pytest_cache", ".next", ".nuxt"}

DOWNLOAD_NAMES = {"downloads", "transferências", "transferencias", "descargas", "téléchargements"}


def file_type(name: str) -> str:
    # chamado para cada ficheiro do disco (centenas de milhares): evita os.path.splitext
    i = name.rfind(".")
    if i <= 0:
        return "Outros"
    lower = name[i:].lower()
    if lower in (".zst", ".xz") and name.lower().endswith((".pkg.tar.zst", ".pkg.tar.xz")):
        return "Instaladores / imagens de disco"
    return EXT_TYPE.get(lower, "Outros")


@dataclass
class FileEntry:
    path: str
    size: int
    mtime: float
    type: str
    suggestion: str = ""
    level: str = ""
    is_dir: bool = False
    steam_appid: str = ""


@dataclass
class DirEntry:
    path: str
    size: int
    files: int
    suggestion: str = ""
    level: str = ""


@dataclass
class ScanResult:
    root: str
    total: int = 0
    files: int = 0
    dirs: int = 0
    errors: int = 0
    seconds: float = 0
    largest: list[FileEntry] = field(default_factory=list)
    folders: list[DirEntry] = field(default_factory=list)
    by_type: dict[str, list[int]] = field(default_factory=dict)  # tipo -> [bytes, ficheiros]
    duplicates: list[list[FileEntry]] = field(default_factory=list)
    suggestions: list[FileEntry] = field(default_factory=list)
    cancelled: bool = False
    # árvore de pastas (só as que têm >= TREE_MIN): tamanho, nº de ficheiros, filhos e grandes ficheiros
    sizes: dict[str, int] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    children: dict[str, list[str]] = field(default_factory=dict)
    big_files: dict[str, list[FileEntry]] = field(default_factory=dict)
    verdicts: dict[str, ds.Verdict] = field(default_factory=dict)
    by_level: dict[str, int] = field(default_factory=dict)       # nível -> bytes
    recommended: list[FileEntry] = field(default_factory=list)   # o que pode sair, já sem sobreposições
    skipped: list[str] = field(default_factory=list)
    dup_candidates: dict = field(default_factory=dict, repr=False)


TREE_MIN = 1024**2          # pastas mais pequenas não entram na árvore (contam na pasta-mãe)
BIG_FILE = 50 * 1024**2     # ficheiros que aparecem na árvore
RECOMMEND_MIN = 50 * 1024**2


def _age(mtime: float) -> str:
    days = (time.time() - mtime) / 86400
    if days >= 730:
        return f"{days / 365:.0f} anos"
    if days >= 60:
        return f"{days / 30:.0f} meses"
    return f"{days:.0f} dias"


def suggest_file(path: str, size: int, mtime: float, typ: str) -> str:
    parts = {p.lower() for p in Path(path).parts}
    name = os.path.basename(path).lower()
    in_downloads = bool(parts & DOWNLOAD_NAMES)
    age_days = (time.time() - mtime) / 86400
    if typ == "Instaladores / imagens de disco":
        if name.endswith((".vdi", ".vmdk", ".qcow2", ".vhd", ".vhdx")):
            return "Disco de máquina virtual — apague a VM se já não a usa"
        if in_downloads:
            return "Instalador nas Transferências — pode apagar se já instalou"
        if name.endswith((".iso", ".img")):
            return "Imagem de disco — normalmente pode ser apagada depois de usar"
    if typ == "Arquivos comprimidos" and in_downloads and age_days > 14:
        return f"Arquivo nas Transferências há {_age(mtime)} — se já extraiu, pode apagar"
    if typ == "Logs / temporários":
        return "Log / temporário / backup — normalmente pode ser apagado"
    if name in ("core",) or name.startswith("core.") and name[5:].isdigit():
        return "Core dump (relatório de crash) — pode apagar"
    if in_downloads and age_days > 90:
        return f"Nas Transferências há {_age(mtime)} — reveja se ainda precisa"
    if typ == "Vídeo" and age_days > 365 and size > 1024**3:
        return f"Vídeo grande sem alterações há {_age(mtime)} — mova para um disco externo/nuvem"
    if age_days > 730 and size > 500 * 1024**2:
        return f"Não é modificado há {_age(mtime)}"
    return ""


def suggest_dir(path: str) -> str:
    base = os.path.basename(path)
    low = path.lower().replace("\\", "/")
    if base in _DEV_DIRS:
        return "Dependências/cache de projeto — reinstala-se com npm/pip quando precisar"
    if base == "target" and os.path.exists(os.path.join(os.path.dirname(path), "Cargo.toml")):
        return "Compilação Rust — 'cargo clean' liberta isto"
    if os.path.dirname(low).endswith("steamapps/common"):
        return "Jogo da Steam — desinstale pela Steam se já não joga"
    if low.endswith("/steamapps/shadercache"):
        return "Cache de shaders da Steam — a Steam volta a criá-la"
    if low.endswith(("/.cache", "/appdata/local/temp")):
        return "Cache/temporários — veja a aba Limpeza"
    if low.endswith("/.local/share/trash") or "$recycle.bin" in low:
        return "Reciclagem — esvazie na aba Limpeza"
    if base.lower() == "windows.old":
        return "Windows antigo — use a Limpeza de Disco do Windows para remover"
    return ""


# ficheiros de programas/jogos/prefixos Wine repetem-se de propósito: não os mostrar como duplicados
_DUP_EXCLUDE = ("/steamapps/", "/.wine", "/pfx/", "/node_modules/", "/.local/lib/", "/.local/share/steam/",
                "/.var/app/", "/.cache/", "site-packages", "/usr/", "/opt/", "/.rustup/", "/.cargo/",
                "/windows/", "/program files", "/programdata/", "/appdata/", "/$recycle.bin/", "/.git/",
                "/snapshots/", "/.local/share/trash/", "/flatpak/")


def _dup_excluded(path: str) -> bool:
    low = path.lower().replace("\\", "/")
    return any(x in low for x in _DUP_EXCLUDE)


_NET_FS = {"nfs", "nfs4", "cifs", "smb3", "smbfs", "fuse.sshfs", "fuse.rclone", "9p", "fuse.gvfsd-fuse",
           "davfs", "fuse.s3fs", "afs", "ceph", "glusterfs", "fuse.portal", "fuse.xdg-document-portal"}


def _skip_set(root: str) -> set[str]:
    """Pastas a não percorrer: rede, snapshots e (ao analisar '/') os outros discos montados."""
    if IS_WIN:
        return set()
    skip = set(_SKIP_LINUX)
    root_n = os.path.normpath(root)
    try:
        import psutil
        for p in psutil.disk_partitions(all=True):
            mp = p.mountpoint
            if mp == root_n:
                continue
            if p.fstype in _NET_FS or p.fstype.startswith("fuse.") and p.fstype != "fuse.ntfs-3g":
                skip.add(mp)
            elif root_n == "/" and mp.startswith(("/mnt/", "/media/", "/run/media/")):
                skip.add(mp)
    except Exception:  # noqa: BLE001
        pass
    if root_n == "/":
        skip |= {"/mnt", "/media", "/.snapshots", "/home/.snapshots"}
    skip.discard(root_n)
    return skip


def _is_reparse(entry: os.DirEntry) -> bool:
    if not IS_WIN:
        return False
    try:
        return bool(entry.stat(follow_symlinks=False).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    except OSError:
        return True


def scan(root: str, progress=None, cancelled=lambda: False, top_files: int = 300, top_dirs: int = 200,
         find_duplicates: bool = True, collect_duplicates: bool = False) -> ScanResult:
    """Percorre `root`. progress(n_ficheiros, bytes, pasta_actual) é chamado ~5×/s."""
    t0 = time.monotonic()
    res = ScanResult(root=root)
    want_dups = find_duplicates or collect_duplicates
    heap: list[tuple[int, str, float]] = []
    dir_size: dict[str, int] = {}
    dir_files: dict[str, int] = {}
    parent: dict[str, str] = {}
    by_size: dict[int, list[tuple[str, float]]] = {}
    sugg: list[FileEntry] = []
    stack = [root]
    last = 0.0
    root_norm = os.path.normpath(root)
    skip = _skip_set(root)
    big: dict[str, list[tuple[int, str, float]]] = {}
    while stack:
        if cancelled():
            res.cancelled = True
            break
        d = stack.pop()
        res.dirs += 1
        local, nfiles = 0, 0
        try:
            it = os.scandir(d)
        except OSError:
            res.errors += 1
            continue
        with it:
            for e in it:
                try:
                    if e.is_symlink():
                        continue
                    if e.is_dir(follow_symlinks=False):
                        p = e.path
                        if (not IS_WIN and p in skip) or _is_reparse(e):
                            if p in skip and p not in _SKIP_LINUX and os.path.isdir(p):
                                res.skipped.append(p)
                            continue
                        parent[p] = d
                        stack.append(p)
                        continue
                    st = e.stat(follow_symlinks=False)
                except OSError:
                    res.errors += 1
                    continue
                size = st.st_blocks * 512 if hasattr(st, "st_blocks") else st.st_size
                size = min(size, st.st_size) if st.st_size else size  # ficheiros esparsos / compressão btrfs
                local += size
                nfiles += 1
                typ = file_type(e.name)
                bt = res.by_type.setdefault(typ, [0, 0])
                bt[0] += size
                bt[1] += 1
                if len(heap) < top_files:
                    heapq.heappush(heap, (size, e.path, st.st_mtime))
                elif size > heap[0][0]:
                    heapq.heapreplace(heap, (size, e.path, st.st_mtime))
                if size >= BIG_FILE:
                    big.setdefault(d, []).append((size, e.path, st.st_mtime))
                if want_dups and size >= 8 * 1024**2 and not _dup_excluded(e.path):
                    by_size.setdefault(st.st_size, []).append((e.path, st.st_mtime))
                if size >= 20 * 1024**2 and len(sugg) < 2000:
                    s = suggest_file(e.path, size, st.st_mtime, typ)
                    if s:
                        sugg.append(FileEntry(e.path, size, st.st_mtime, typ, s))
        dir_size[d] = local
        dir_files[d] = nfiles
        res.files += nfiles
        res.total += local
        now = time.monotonic()
        if progress and now - last > 0.2:
            last = now
            progress(res.files, res.total, d)

    # agrega o tamanho de cada pasta nas pastas-mãe (das mais fundas para as de cima)
    if progress:
        progress(-1, 0, "A classificar o que é seguro apagar…")
    agg = dict(dir_size)
    agg_files = dict(dir_files)
    for p in sorted(parent, key=lambda x: -x.count(os.sep)):
        q = parent[p]
        if p in agg and q in agg:
            agg[q] += agg[p]
            agg_files[q] += agg_files[p]
    _build_tree(res, root, agg, agg_files, parent, big)

    # pastas mais pesadas, sem repetir a raiz
    dirs_sorted = heapq.nlargest(top_dirs, ((s, p) for p, s in agg.items() if os.path.normpath(p) != root_norm))
    res.folders = [_dir_entry(res, p, s, agg_files.get(p, 0)) for s, p in dirs_sorted]
    # pastas de dependências / caches em qualquer lado (mesmo que não estejam no top)
    extra = [_dir_entry(res, p, s, agg_files.get(p, 0)) for p, s in agg.items()
             if s > 50 * 1024**2 and os.path.basename(p) in _DEV_DIRS
             and os.path.basename(parent.get(p, "")) not in _DEV_DIRS]
    have = {f.path for f in res.folders}
    res.folders += [x for x in sorted(extra, key=lambda x: -x.size)[:100] if x.path not in have]

    res.largest = [_file_entry(p, s, m) for s, p, m in sorted(heap, reverse=True)]
    # sugestões de ficheiros: nunca dentro do sistema
    keep = []
    for f in sorted(sugg, key=lambda f: -f.size):
        v = ds.classify(f.path)
        if v.level == ds.SYSTEM:
            continue
        f.level = v.level or ds.REVIEW
        keep.append(f)
    res.suggestions = keep
    _recommend(res, root)
    if find_duplicates and not res.cancelled:
        res.duplicates = _find_duplicates(by_size, cancelled, progress)
    elif collect_duplicates:
        res.dup_candidates = by_size
    res.seconds = time.monotonic() - t0
    return res


def _file_entry(p: str, s: int, m: float) -> FileEntry:
    t = file_type(p)
    v = ds.classify(p)
    sug = suggest_file(p, s, m, t) if v.level != ds.SYSTEM else ""
    if v.level in (ds.SAFE, ds.SYSTEM, ds.APP) or not sug:
        sug = v.reason or sug
    return FileEntry(p, s, m, t, sug, v.level, False, v.steam_appid)


def _dir_entry(res: ScanResult, p: str, s: int, n: int) -> DirEntry:
    v = res.verdicts.get(p) or ds.classify(p, True)
    return DirEntry(p, s, n, v.reason or suggest_dir(p), v.level)


def _build_tree(res: ScanResult, root: str, agg, agg_files, parent, big) -> None:
    keep = {p for p, s in agg.items() if s >= TREE_MIN}
    keep.add(root)
    if root not in agg:
        agg[root] = 0
    for p in keep:
        res.sizes[p] = agg.get(p, 0)
        res.counts[p] = agg_files.get(p, 0)
        q = parent.get(p)
        if q is not None and q in keep:
            res.children.setdefault(q, []).append(p)
    for lst in res.children.values():
        lst.sort(key=lambda x: -res.sizes[x])
    for d, files in big.items():
        res.big_files[d] = [FileEntry(p, s, m, file_type(p)) for s, p, m in sorted(files, reverse=True)]
    # classifica cada pasta da árvore e soma os bytes por nível (cada byte conta uma vez)
    by = dict.fromkeys(ds.LEVEL_ORDER, 0)
    stack = [root]
    while stack:
        d = stack.pop()
        v = ds.classify(d, True)
        res.verdicts[d] = v
        own = res.sizes[d] - sum(res.sizes[c] for c in res.children.get(d, ()))
        by[v.level] += max(own, 0)
        stack.extend(res.children.get(d, ()))
    _protect_installs(res)
    by = dict.fromkeys(ds.LEVEL_ORDER, 0)
    for d, v in res.verdicts.items():
        own = res.sizes[d] - sum(res.sizes[c] for c in res.children.get(d, ()))
        by[v.level] += max(own, 0)
    res.by_level = by
    for d, files in res.big_files.items():
        for f in files:
            v = ds.classify(f.path)
            f.level, f.suggestion, f.steam_appid = v.level, v.reason, v.steam_appid


# sinais de que uma pasta tem software instalado (não é cache, mesmo que esteja em ~/.cache)
_INSTALL_MARKERS = {"drive_c", "dosdevices", "site-packages", "bin", "lib64", "python312", "python311", "python313"}


def _protect_installs(res: ScanResult) -> None:
    """Uma pasta "segura" que contém um prefixo Wine, um Python ou binários passa a "Rever antes".

    Ex.: um Python do Windows instalado em ~/.cache/<algo>/wineprefix — apagar a cache parte-o."""
    protect = ds.Verdict(ds.REVIEW, "Contém programas instalados (Wine/Python/binários) — "
                                    "não apagar em bloco; veja o que está lá dentro")
    for d in list(res.verdicts):
        if os.path.basename(d).lower() not in _INSTALL_MARKERS:
            continue
        # a própria pasta e o que herdou o "seguro" genérico de ~/.cache deixam de ser seguros
        stack = [d]
        while stack:
            x = stack.pop()
            v = res.verdicts.get(x)
            if v and v.level == ds.SAFE and v.reason == ds.CACHE_ROOT_REASON:
                res.verdicts[x] = protect
            stack.extend(res.children.get(x, ()))
        p = os.path.dirname(d)
        while p in res.verdicts:
            if os.path.basename(p) in _DEV_DIRS:
                break  # .venv / node_modules têm bin/ e site-packages mas recriam-se
            v = res.verdicts[p]
            if v.level == ds.SAFE:
                res.verdicts[p] = protect
            nxt = os.path.dirname(p)
            if nxt == p:
                break
            p = nxt


def _own_paths() -> list[str]:
    """Pastas do próprio Nexo em execução (ambiente Python, executável): nunca sugerir apagá-las."""
    import sys
    paths = {os.path.realpath(sys.prefix), os.path.realpath(os.path.dirname(sys.executable)),
             os.path.realpath(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))}
    return [os.path.join(p, "") for p in paths]


def _recommend(res: ScanResult, root: str) -> None:
    """Pastas seguras / jogos sem sobreposição + ficheiros sugeridos que não estão dentro delas."""
    own = _own_paths()
    out: list[FileEntry] = []
    taken: list[str] = []
    stack = [root]
    while stack:
        d = stack.pop()
        v = res.verdicts.get(d)
        size = res.sizes.get(d, 0)
        if size < RECOMMEND_MIN:
            continue
        dn = os.path.join(os.path.realpath(d), "")
        if any(dn.startswith(o) for o in own):
            continue                                # dentro do Nexo: nada a sugerir
        if any(o.startswith(dn) for o in own):
            stack.extend(res.children.get(d, ()))   # contém o Nexo: só desce, nunca recomenda a pasta inteira
            continue
        if v and d != root and v.level in (ds.SAFE, ds.APP) and "group" not in v.flags \
                and (v.level == ds.SAFE or v.is_game):
            try:
                mt = os.stat(d).st_mtime
            except OSError:
                mt = 0
            out.append(FileEntry(d, size, mt, "Jogo" if v.is_game else "Pasta", v.reason, v.level, True,
                                 v.steam_appid))
            taken.append(os.path.join(d, ""))
            continue
        stack.extend(res.children.get(d, ()))
    for f in res.suggestions:
        if not any(f.path.startswith(t) for t in taken) and not any(os.path.realpath(f.path).startswith(o) for o in own):
            out.append(f)
    out.sort(key=lambda f: -f.size)
    res.recommended = out


def _hash(path: str, full: bool) -> str | None:
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            if not full:
                h.update(f.read(1024 * 1024))
                f.seek(-min(1024 * 1024, os.path.getsize(path)), os.SEEK_END)
                h.update(f.read(1024 * 1024))
            else:
                for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
                    h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def find_duplicates(res: ScanResult, cancelled=lambda: False, progress=None) -> list[list[FileEntry]]:
    """2.ª fase (opcional): compara os candidatos guardados por scan(collect_duplicates=True)."""
    res.duplicates = _find_duplicates(res.dup_candidates, cancelled, progress)
    res.dup_candidates = {}
    return res.duplicates


def system_root() -> str:
    if IS_WIN:
        return os.environ.get("SystemDrive", "C:") + "\\"
    return "/"


def _find_duplicates(by_size, cancelled, progress) -> list[list[FileEntry]]:
    groups: list[list[FileEntry]] = []
    cands = [(s, lst) for s, lst in by_size.items() if len(lst) > 1]
    cands.sort(key=lambda x: -x[0] * (len(x[1]) - 1))
    budget = 12 * 1024**3  # máximo lido em hashes completos (o resto fica pela amostra do início/fim)
    for size, lst in cands[:400]:
        if cancelled():
            break
        if progress:
            progress(-1, size, f"A comparar duplicados ({human_bytes(size)})")
        quick: dict[str, list] = {}
        for path, m in lst:
            k = _hash(path, False)
            if k:
                quick.setdefault(k, []).append((path, m))
        for same in quick.values():
            if len(same) < 2:
                continue
            # confirma com hash completo só para ficheiros até 2 GB (os maiores ficam pela amostra)
            if size <= 2 * 1024**3 and budget > 0:
                budget -= size * len(same)
                full: dict[str, list] = {}
                for path, m in same:
                    k = _hash(path, True)
                    if k:
                        full.setdefault(k, []).append((path, m))
                sets = [v for v in full.values() if len(v) > 1]
            else:
                sets = [same]
            for v in sets:
                groups.append([FileEntry(p, size, m, file_type(p),
                                         "Cópia — pode apagar e manter só uma" if i else "Original (mais antigo)")
                               for i, (p, m) in enumerate(sorted(v, key=lambda x: x[1]))])
    groups.sort(key=lambda g: -g[0].size * (len(g) - 1))
    return groups


def default_roots() -> list[str]:
    if IS_WIN:
        import string
        drives = [f"{d}:\\" for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
        sysd = system_root()
        return [sysd] + [d for d in drives if d.upper() != sysd.upper()] + [str(Path.home())]
    roots = ["/", str(Path.home())]
    for base in ("/mnt", "/media", f"/run/media/{os.environ.get('USER', '')}"):
        if os.path.isdir(base):
            roots += [os.path.join(base, x) for x in sorted(os.listdir(base))]
    return roots
