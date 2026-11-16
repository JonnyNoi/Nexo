"""Quarentena do antivírus: os ficheiros ficam codificados (XOR — não é cifra) e sem permissão de execução,
com SHA-256 para confirmar a integridade ao restaurar. Nada é apagado sem o utilizador pedir."""

import os
import shlex
import shutil
import stat
import threading
import time
from pathlib import Path


from .util import IS_WIN, _save_lock, config_dir, load_json, run_root, save_json

from .av_model import _tail


# --------------------------------------------------------------------------- quarentena
# Codificação (não é cifra): impede que o ficheiro seja executado ou reconhecido por outros programas.
_KEY = 0xA5
_qid_lock = threading.Lock()


def _qdir() -> Path:
    d = config_dir() / "quarentena"
    d.mkdir(parents=True, exist_ok=True)
    return d


def quarantine_list() -> list[dict]:
    lst = load_json("quarentena.json", [])
    return lst if isinstance(lst, list) else []


def _xor_copy(src: str, dst: str, decode: bool = False) -> str:
    """Copia src → dst aplicando o XOR. Devolve o SHA-256 do conteúdo ORIGINAL (descodificado)."""
    import hashlib
    h = hashlib.sha256()
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        while True:
            b = fi.read(1 << 20)
            if not b:
                break
            x = _xor_fast(b)
            h.update(x if decode else b)
            fo.write(x)
        fo.flush()
        os.fsync(fo.fileno())
    return h.hexdigest()


def _xor_fast(b: bytes) -> bytes:
    n = int.from_bytes(b, "little")
    mask = int.from_bytes(bytes([_KEY]) * len(b), "little")
    return (n ^ mask).to_bytes(len(b), "little")


def _new_qid() -> str:
    """Identificador único (duas quarentenas no mesmo milissegundo não se podem sobrepor)."""
    with _qid_lock:
        base = int(time.time() * 1000)
        n = 0
        while True:
            qid = f"{base}" if n == 0 else f"{base}-{n}"
            if not (_qdir() / f"{qid}.nexoq").exists() and not any(x.get("id") == qid for x in quarantine_list()):
                # reserva já o nome (outra thread não o pode escolher)
                try:
                    with open(_qdir() / f"{qid}.nexoq", "xb"):
                        pass
                    return qid
                except FileExistsError:
                    pass
            n += 1


def quarantine(path: str, reason: str) -> tuple[bool, str]:
    if not path or not os.path.isfile(path):
        return False, "O ficheiro já não existe."
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        size = os.path.getsize(path)
    except OSError as e:
        return False, str(e)
    qid = _new_qid()
    dst = _qdir() / f"{qid}.nexoq"
    try:
        digest = _xor_copy(path, str(dst))
        os.remove(path)
    except PermissionError:
        dst.unlink(missing_ok=True)
        if IS_WIN:
            return False, "Sem permissão — execute o Nexo como administrador."
        plain = _qdir() / f"{qid}.tmp"
        code, out = run_root(f"cat -- {shlex.quote(path)} > {shlex.quote(str(plain))} && "
                             f"chown {os.getuid()}:{os.getgid()} {shlex.quote(str(plain))} && "
                             f"rm -f -- {shlex.quote(path)}", timeout=300)
        if code != 0:
            plain.unlink(missing_ok=True)
            return False, _tail(out)
        try:
            digest = _xor_copy(str(plain), str(dst))
        except OSError as e:
            # o original já foi apagado pelo root: o texto simples fica onde está para não se perder
            return False, f"{e} — o ficheiro ficou em {plain}"
        plain.unlink(missing_ok=True)
    except OSError as e:
        dst.unlink(missing_ok=True)
        return False, str(e)
    try:
        os.chmod(dst, 0o400)
    except OSError:
        pass
    with _save_lock:  # várias ações em paralelo não podem perder entradas (o ficheiro ficaria órfão)
        lst = quarantine_list()
        lst.append({"id": qid, "name": os.path.basename(path), "original": path, "mode": mode, "size": size,
                    "sha256": digest, "when": time.time(), "reason": reason})
        save_json("quarentena.json", lst)
    return True, f"{os.path.basename(path)} foi para a quarentena (já não pode ser executado)."


def quarantine_restore(qid: str) -> tuple[bool, str]:
    it = next((x for x in quarantine_list() if x.get("id") == qid), None)
    if not it:
        return False, "Item não encontrado."
    src = _qdir() / f"{qid}.nexoq"
    if not src.is_file():
        return False, "O ficheiro da quarentena desapareceu."
    orig = it["original"]
    if os.path.lexists(orig):
        return False, f"Já existe um ficheiro em {orig}."
    plain = _qdir() / f"{qid}.restaurar"
    try:
        digest = _xor_copy(str(src), str(plain), decode=True)
    except OSError as e:
        plain.unlink(missing_ok=True)
        return False, str(e)
    if it.get("sha256") and digest != it["sha256"]:
        plain.unlink(missing_ok=True)
        return False, "O ficheiro da quarentena está danificado (SHA-256 diferente) — não foi restaurado."
    mode = int(it.get("mode", 0o644)) & 0o7777
    tmp = os.path.join(os.path.dirname(orig) or ".", f".{os.path.basename(orig)}.nexo-restaurar")
    try:
        os.makedirs(os.path.dirname(orig) or ".", exist_ok=True)
        shutil.copyfile(plain, tmp)           # escreve ao lado e só no fim troca (nunca fica meio ficheiro)
        os.chmod(tmp, mode)
        os.replace(tmp, orig)
    except PermissionError:
        _unlink(tmp)
        if IS_WIN:
            plain.unlink(missing_ok=True)
            return False, "Sem permissão — execute o Nexo como administrador."
        code, out = run_root(["install", "-m", f"{mode:o}", "--", str(plain), orig], timeout=120)
        if code != 0:
            plain.unlink(missing_ok=True)
            return False, _tail(out)
    except OSError as e:
        _unlink(tmp)
        plain.unlink(missing_ok=True)
        return False, str(e)
    plain.unlink(missing_ok=True)
    _q_remove(qid)
    return True, f"{it['name']} restaurado em {orig}."


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def quarantine_delete(qid: str) -> tuple[bool, str]:
    if not _q_remove(qid):
        return False, "Não foi possível apagar o ficheiro da quarentena."
    return True, "Apagado definitivamente."


def _q_remove(qid: str) -> bool:
    p = _qdir() / f"{qid}.nexoq"
    ok = True
    try:
        os.chmod(p, 0o600)
        p.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        ok = False
    if ok:
        with _save_lock:
            save_json("quarentena.json", [x for x in quarantine_list() if x.get("id") != qid])
    return ok
