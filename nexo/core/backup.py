"""Exportar e importar as definições do Nexo (para mudar de PC ou depois de reinstalar).

O ficheiro é um .zip com:
  manifest.json      — aplicação, versão, data e sistema de origem
  settings.json      — definições (sem o que só faz sentido nesta máquina/sessão: posição da janela, datas…)
  bench_history.json — histórico dos benchmarks
  sessions.json      — histórico das sessões de jogo
Ao importar, as definições atuais ficam copiadas para settings.json.antes-de-importar."""
from __future__ import annotations

import json
import platform
import shutil
import time
import zipfile
from pathlib import Path

from . import util
from .util import APP_NAME, APP_VERSION, DEFAULT_SETTINGS, _save_lock, config_dir, load_json, save_json

# definições que pertencem a esta sessão/máquina e nunca viajam
LOCAL_KEYS = {"geometry", "last_page_name", "snapshot_last", "wp_auto_last", "tray_hint_shown", "wallpaper",
              "desktop_wp", "av_last_scan", "speed_history", "rel_seen", "web_token"}
LOCAL_SUFFIXES = ("_last", "_at", "_time")
MAX_BYTES = 20 * 1024 * 1024


class ImportErrorNexo(Exception):
    pass


def _portable(settings: dict) -> dict:
    return {k: v for k, v in settings.items() if k not in LOCAL_KEYS and not k.endswith(LOCAL_SUFFIXES)}


def export(dest: str | Path) -> Path:
    from . import sessions
    dest = Path(dest)
    if dest.suffix.lower() != ".zip":
        dest = dest.with_suffix(".zip")
    manifest = {"app": APP_NAME, "version": APP_VERSION, "created": time.strftime("%Y-%m-%d %H:%M:%S"),
                "system": f"{platform.system()} {platform.release()}", "format": 1}
    sess = [s.__dict__ for s in sessions.recent(limit=sessions.KEEP)]
    tmp = dest.with_name(dest.name + ".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        z.writestr("settings.json", json.dumps(_portable(dict(util.settings())), indent=2, ensure_ascii=False))
        z.writestr("bench_history.json", json.dumps(load_json("bench_history.json", []), ensure_ascii=False))
        z.writestr("sessions.json", json.dumps(sess, ensure_ascii=False))
    tmp.replace(dest)
    return dest


def read_backup(path: str | Path) -> dict:
    """Lê e valida o ficheiro. Devolve {"manifest", "settings", "bench", "sessions"}."""
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "manifest.json" not in names or "settings.json" not in names:
                raise ImportErrorNexo("Este ficheiro não é uma cópia das definições do Nexo.")
            if sum(i.file_size for i in z.infolist()) > MAX_BYTES:
                raise ImportErrorNexo("O ficheiro é demasiado grande para ser uma cópia de definições.")

            def get(name, default):
                if name not in names:
                    return default
                return json.loads(z.read(name).decode("utf-8"))
            data = {"manifest": get("manifest.json", {}), "settings": get("settings.json", {}),
                    "bench": get("bench_history.json", []), "sessions": get("sessions.json", [])}
    except (zipfile.BadZipFile, OSError, ValueError, UnicodeDecodeError) as e:
        raise ImportErrorNexo(f"Não foi possível ler o ficheiro: {e}") from e
    if data["manifest"].get("app") not in (APP_NAME, "PCForge") or not isinstance(data["settings"], dict):
        raise ImportErrorNexo("Este ficheiro não é uma cópia das definições do Nexo.")
    return data


def _clean_settings(incoming: dict) -> dict:
    """Só aceita valores do mesmo tipo que os predefinidos (um ficheiro estragado não parte o Nexo)."""
    out = {}
    for k, v in _portable(incoming).items():
        if not isinstance(k, str) or len(k) > 80:
            continue
        ref = DEFAULT_SETTINGS.get(k)
        if ref is not None and not isinstance(v, type(ref)) and not (isinstance(ref, (int, float))
                                                                    and isinstance(v, (int, float))
                                                                    and not isinstance(v, bool)):
            continue
        out[k] = v
    return out


def import_backup(path: str | Path, include_history: bool = True) -> dict:
    """Aplica a cópia. Devolve um resumo {"settings": n, "bench": n, "sessions": n, "from": "..."}."""
    from . import sessions
    data = read_backup(path)
    new = _clean_settings(data["settings"])
    with _save_lock:
        cur = config_dir() / "settings.json"
        if cur.exists():
            shutil.copy2(cur, cur.with_name("settings.json.antes-de-importar"))
        s = util.settings()
        keep_local = {k: v for k, v in s.items() if k in LOCAL_KEYS or k.endswith(LOCAL_SUFFIXES)}
        s.clear()
        s.update({**DEFAULT_SETTINGS, **new, **keep_local})
        save_json("settings.json", dict(s))
    n_bench = n_sess = 0
    if include_history:
        bench = [b for b in data["bench"] if isinstance(b, dict) and "score" in b]
        if bench:
            with _save_lock:
                old = load_json("bench_history.json", [])
                seen = {(b.get("date"), b.get("mode"), b.get("score")) for b in old}
                add = [b for b in bench if (b.get("date"), b.get("mode"), b.get("score")) not in seen]
                save_json("bench_history.json", (old + add)[-30:])
                n_bench = len(add)
        have = {(x.game, round(x.start)) for x in sessions.recent(limit=sessions.KEEP)}
        for row in data["sessions"]:
            try:
                sess = sessions.Session(**{k: row.get(k) for k in ("game", "start", "end", "cpu_max", "gpu_max",
                                                                     "fps_avg", "fps_low1", "fps_min")})
                for k in ("cpu_load", "gpu_load", "vram_max", "ram_max", "wh", "stutters"):   # 2.4+
                    if isinstance(row.get(k), (int, float)) and not isinstance(row.get(k), bool):
                        setattr(sess, k, row[k])
            except TypeError:
                continue
            if not isinstance(sess.game, str) or not isinstance(sess.start, (int, float)) \
                    or not isinstance(sess.end, (int, float)) or (sess.game, round(sess.start)) in have:
                continue
            if sessions.add(sess):
                n_sess += 1
    return {"settings": len(new), "bench": n_bench, "sessions": n_sess,
            "from": f"{data['manifest'].get('system', '?')} · {data['manifest'].get('created', '?')}"}
