"""Pesquisa e descarga de fundos do wallhaven.cc (API pública, sem conta).

Só pede conteúdo "SFW" (purity=100). As imagens pertencem aos respetivos autores: o Nexo apenas
as descarrega para uso pessoal como fundo, a pedido do utilizador, e guarda a ligação para a origem."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from .util import APP_NAME, APP_VERSION, config_dir

API = "https://wallhaven.cc/api/v1/search"
UA = f"{APP_NAME}/{APP_VERSION}"
SUGGESTIONS = {
    "Anime": ["anime scenery", "anime city", "anime night", "anime sky", "sakura", "lofi", "anime rain",
              "anime girls", "anime boys", "cyberpunk anime", "fantasy anime", "pixel art"],
    "Geral": ["cyberpunk", "synthwave", "neon city", "space", "landscape", "minimalist", "night", "abstract",
              "mountains", "rain", "nature", "cars"],
}
CATEGORIES = {"Anime": "010", "Geral": "100", "Tudo": "110"}
SORTS = {"Mais populares": "toplist", "Relevância": "relevance", "Mais vistas": "views", "Aleatório": "random",
         "Recentes": "date_added"}


def _get(url: str, timeout: float = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (URL https fixa)
        return r.read()


def search(query: str, sorting: str = "toplist", page: int = 1, min_res: str = "1920x1080",
           categories: str = "110", ultrawide: bool = False, seed: str | None = None) -> tuple[list[dict], int]:
    """Devolve ([{id, thumb, full, res, url, size, colors}], última página). Só conteúdo SFW."""
    params = {"q": query, "categories": categories, "purity": "100", "sorting": sorting, "page": page,
              "atleast": min_res, "topRange": "1y"}
    params["ratios"] = "21x9,32x9,48x9" if ultrawide else "landscape"  # nada de imagens ao alto
    if seed and sorting == "random":
        params["seed"] = seed
    data = json.loads(_get(f"{API}?{urllib.parse.urlencode(params)}"))
    out = [{"id": d["id"], "thumb": d["thumbs"]["small"], "full": d["path"], "res": d["resolution"],
            "url": d["url"], "size": d.get("file_size", 0), "colors": d.get("colors", [])}
           for d in data.get("data", [])]
    return out, int(data.get("meta", {}).get("last_page", 1))


def thumbnail(url: str) -> bytes:
    return _get(url, timeout=15)


def wallpapers_dir():
    d = config_dir() / "wallpapers"
    d.mkdir(exist_ok=True)
    return d


def download(item: dict) -> str:
    """Descarrega a imagem completa (se ainda não existir) e devolve o caminho local."""
    ext = os.path.splitext(item["full"])[1] or ".jpg"
    path = wallpapers_dir() / f"wallhaven-{item['id']}{ext}"
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(_get(item["full"], timeout=120))
        tmp.replace(path)
    return str(path)


def source_of(path: str) -> str | None:
    """Ligação para a página original, se o fundo veio do wallhaven."""
    name = os.path.basename(path or "")
    if name.startswith("wallhaven-"):
        return "https://wallhaven.cc/w/" + os.path.splitext(name)[0][len("wallhaven-"):]
    return None


MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".mp4", ".webm", ".mkv", ".mov", ".m4v")


def list_local() -> list[str]:
    """Fundos guardados (descarregados ou escolhidos), mais recentes primeiro."""
    d = wallpapers_dir()
    files = [f for f in d.iterdir() if f.is_file() and f.suffix.lower() in MEDIA_EXT]
    return [str(f) for f in sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)]


def random_from_wallhaven(query: str, categories: str, min_res: str, ultrawide: bool = False) -> str:
    """Escolhe um fundo aleatório (que ainda não tenha) e descarrega-o. Usado na troca automática."""
    import random
    items, _ = search(query, "random", 1, min_res, categories, ultrawide, seed=f"{random.randint(0, 999999):06d}")
    have = {os.path.basename(p) for p in list_local()}
    fresh = [i for i in items if not any(h.startswith(f"wallhaven-{i['id']}") for h in have)] or items
    if not fresh:
        raise RuntimeError("sem resultados para esta pesquisa")
    return download(random.choice(fresh))
