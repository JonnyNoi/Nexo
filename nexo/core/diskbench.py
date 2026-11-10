"""Teste de velocidade do disco: sequencial (blocos de 1 MiB) e aleatório (blocos de 4 KiB, um pedido de
cada vez — QD1, o caso mais comum no dia a dia: abrir programas, carregar jogos).

Para medir o disco e não a memória RAM, os dados não passam pela cache do sistema:
  • Linux: O_DIRECT (se o sistema de ficheiros não o suportar: fsync + posix_fadvise DONTNEED);
  • Windows: CreateFile com FILE_FLAG_NO_BUFFERING | FILE_FLAG_WRITE_THROUGH.
O ficheiro de teste é apagado no fim (também se for cancelado ou der erro)."""
from __future__ import annotations

import mmap
import os
import random
import time
from dataclasses import dataclass, field

import psutil

from .util import IS_WIN, TaskCancelled, config_dir

MiB = 1024 * 1024
SEQ_BLOCK = MiB
RND_BLOCK = 4096
RND_SECONDS = 5.0
FILE_NAME = "nexo-teste-velocidade.tmp"


class Cancelled(TaskCancelled):
    pass


@dataclass
class BenchResult:
    path: str
    size: int
    seq_read: float = 0.0       # MB/s
    seq_write: float = 0.0
    rnd_read: float = 0.0       # MB/s com blocos de 4 KiB
    rnd_write: float = 0.0
    rnd_read_iops: float = 0.0
    rnd_write_iops: float = 0.0
    cached: bool = False        # True se não foi possível evitar a cache (valores de leitura otimistas)
    notes: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- onde testar
def targets() -> list[tuple[str, str, int]]:
    """[(rótulo, pasta onde escrever, espaço livre)] — uma por disco/partição com escrita possível.
    Agrupa por dispositivo (os subvolumes btrfs aparecem como várias montagens do mesmo disco)."""
    try:
        parts = psutil.disk_partitions(all=False)
    except OSError:
        parts = []
    parts = [p for p in parts if "ro" not in p.opts.split(",") and "cdrom" not in p.opts
             and p.fstype.lower() not in ("squashfs", "iso9660", "udf", "tmpfs", "devtmpfs", "overlay", "")]

    def owner(path: str):
        """Partição (a montagem mais longa que contém o caminho)."""
        path = os.path.normcase(os.path.realpath(path))
        best = None
        for p in parts:
            mp = os.path.normcase(p.mountpoint)
            if path == mp or path.startswith(mp.rstrip("\\/") + os.sep) or mp in ("/", "\\"):
                if best is None or len(mp) > len(os.path.normcase(best.mountpoint)):
                    best = p
        return best

    home_dev = getattr(owner(os.path.expanduser("~")), "device", None)
    tmp = os.environ.get("TEMP", "") if IS_WIN else ""
    tmp_dev = getattr(owner(tmp), "device", None) if tmp else None
    by_dev: dict[str, list] = {}
    for p in parts:
        by_dev.setdefault(p.device, []).append(p)
    out = []
    for dev, plist in by_dev.items():
        mps = sorted((p.mountpoint for p in plist), key=len)
        cand = []
        if dev == home_dev:
            cand.append(str(config_dir()))
        if tmp and dev == tmp_dev:
            cand.append(tmp)
        cand += mps
        where = next((c for c in cand if os.path.isdir(c) and os.access(c, os.W_OK)), None)
        if not where:
            continue
        try:   # restos de um teste interrompido (o Nexo fechou a meio)
            os.remove(os.path.join(where, FILE_NAME))
        except OSError:
            pass
        try:
            free = psutil.disk_usage(where).free
        except OSError:
            continue
        label = mps[0].rstrip("\\") if IS_WIN else mps[0]
        out.append((f"{label}  ({plist[0].fstype}, {dev})", where, free))
    return out


# --------------------------------------------------------------------------- ficheiro sem cache
class _File:
    """Abre o ficheiro de teste sem cache do sistema (se possível). Buffers alinhados com mmap."""

    def __init__(self, path: str, size: int):
        self.path, self.size = path, size
        self.cached = False
        self.h = None
        self.fd = -1
        if IS_WIN:
            self._open_win()
        else:
            flags = os.O_RDWR | os.O_CREAT
            direct = getattr(os, "O_DIRECT", 0)
            try:
                self.fd = os.open(path, flags | direct, 0o600)
                # alguns sistemas de ficheiros aceitam a flag no open e falham só na escrita: testa já
                buf = mmap.mmap(-1, RND_BLOCK)
                os.pwrite(self.fd, buf, 0)
            except OSError:
                if self.fd >= 0:
                    os.close(self.fd)
                self.fd = os.open(path, flags, 0o600)
                self.cached = True

    # ---- Windows (ctypes) ------------------------------------------------
    def _open_win(self):
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateFileW.restype = wintypes.HANDLE
        k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
                                    wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        k32.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                 ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k32.WriteFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
                                  ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID]
        k32.SetFilePointerEx.argtypes = [wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD]
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        GENERIC_RW = 0x80000000 | 0x40000000
        OPEN_ALWAYS = 4
        NO_BUFFERING, WRITE_THROUGH, ATTR_TEMP = 0x20000000, 0x80000000, 0x100
        h = k32.CreateFileW(self.path, GENERIC_RW, 0, None, OPEN_ALWAYS, NO_BUFFERING | WRITE_THROUGH | ATTR_TEMP,
                            None)
        if h in (None, wintypes.HANDLE(-1).value):
            raise OSError(ctypes.get_last_error(), "Não foi possível criar o ficheiro de teste")
        self.k32, self.h, self._ct, self._wt = k32, h, ctypes, wintypes

    def _win_io(self, write: bool, buf: mmap.mmap, offset: int, n: int) -> int:
        ct = self._ct
        if not self.k32.SetFilePointerEx(self.h, offset, None, 0):
            raise OSError(ct.get_last_error(), "SetFilePointerEx falhou")
        done = self._wt.DWORD(0)
        addr = ct.addressof(ct.c_char.from_buffer(buf))
        ok = (self.k32.WriteFile if write else self.k32.ReadFile)(self.h, addr, n, ct.byref(done), None)
        if not ok:
            raise OSError(ct.get_last_error(), "Erro de leitura/escrita")
        return done.value

    # ---- comum -----------------------------------------------------------
    def write(self, buf: mmap.mmap, offset: int, n: int) -> int:
        if IS_WIN:
            return self._win_io(True, buf, offset, n)
        return os.pwrite(self.fd, memoryview(buf)[:n], offset)

    def read(self, buf: mmap.mmap, offset: int, n: int) -> int:
        if IS_WIN:
            return self._win_io(False, buf, offset, n)
        return os.preadv(self.fd, [memoryview(buf)[:n]], offset)

    def sync_and_drop(self):
        """Sem O_DIRECT: garante que os dados foram para o disco e tira-os da cache antes de ler."""
        if IS_WIN or not self.cached:
            return
        os.fsync(self.fd)
        if hasattr(os, "posix_fadvise"):
            os.posix_fadvise(self.fd, 0, 0, os.POSIX_FADV_DONTNEED)

    def close(self):
        if IS_WIN and self.h is not None:
            self.k32.CloseHandle(self.h)
            self.h = None
        elif self.fd >= 0:
            os.close(self.fd)
            self.fd = -1


# --------------------------------------------------------------------------- teste
def run(folder: str, size: int = 1024 * MiB, progress=None, stop=None) -> BenchResult:
    """progress(fase, fração 0–1, MB/s atual). stop: threading.Event para cancelar."""
    size = max(64 * MiB, size // SEQ_BLOCK * SEQ_BLOCK)
    free = psutil.disk_usage(folder).free
    if free < size + 512 * MiB:
        raise RuntimeError(f"Espaço livre insuficiente: são precisos {(size + 512 * MiB) // MiB} MiB.")
    path = os.path.join(folder, FILE_NAME)
    res = BenchResult(path=folder, size=size)
    f = _File(path, size)
    res.cached = f.cached
    if f.cached:
        res.notes.append("Este sistema de ficheiros não permite ignorar a cache (O_DIRECT); a leitura sequencial "
                         "pode aparecer mais rápida do que o disco é.")
    prog = progress or (lambda *_a: None)

    def check_stop():
        if stop is not None and stop.is_set():
            raise Cancelled

    try:
        buf = mmap.mmap(-1, SEQ_BLOCK)
        buf.write(os.urandom(SEQ_BLOCK))          # dados aleatórios: discos com compressão não fazem batota
        blocks = size // SEQ_BLOCK

        # escrita sequencial
        t0 = last = time.perf_counter()
        for i in range(blocks):
            check_stop()
            f.write(buf, i * SEQ_BLOCK, SEQ_BLOCK)
            now = time.perf_counter()
            if now - last > 0.2:
                last = now
                prog("seq_write", (i + 1) / blocks, (i + 1) * SEQ_BLOCK / MiB / (now - t0))
        f.sync_and_drop()
        res.seq_write = size / MiB / (time.perf_counter() - t0)
        prog("seq_write", 1.0, res.seq_write)

        # leitura sequencial
        t0 = last = time.perf_counter()
        for i in range(blocks):
            check_stop()
            f.read(buf, i * SEQ_BLOCK, SEQ_BLOCK)
            now = time.perf_counter()
            if now - last > 0.2:
                last = now
                prog("seq_read", (i + 1) / blocks, (i + 1) * SEQ_BLOCK / MiB / (now - t0))
        res.seq_read = size / MiB / (time.perf_counter() - t0)
        prog("seq_read", 1.0, res.seq_read)

        # aleatório 4 KiB QD1 (tempo fixo)
        small = mmap.mmap(-1, RND_BLOCK)
        small.write(os.urandom(RND_BLOCK))
        n_slots = size // RND_BLOCK
        rnd = random.Random(1234)
        for phase, write in (("rnd_read", False), ("rnd_write", True)):
            f.sync_and_drop()
            ops = 0
            t0 = last = time.perf_counter()
            while True:
                now = time.perf_counter()
                if now - t0 >= RND_SECONDS:
                    break
                if ops % 64 == 0:
                    check_stop()
                off = rnd.randrange(n_slots) * RND_BLOCK
                (f.write if write else f.read)(small, off, RND_BLOCK)
                ops += 1
                if now - last > 0.2:
                    last = now
                    prog(phase, (now - t0) / RND_SECONDS, ops * RND_BLOCK / MiB / (now - t0))
            dt = time.perf_counter() - t0
            if write and f.cached:
                os.fsync(f.fd)
                dt = time.perf_counter() - t0
            iops = ops / dt
            mbs = iops * RND_BLOCK / MiB
            if write:
                res.rnd_write, res.rnd_write_iops = mbs, iops
            else:
                res.rnd_read, res.rnd_read_iops = mbs, iops
            prog(phase, 1.0, mbs)
        return res
    finally:
        f.close()
        try:
            os.remove(path)
        except OSError:
            pass


# --------------------------------------------------------------------------- interpretação
def verdict(r: BenchResult) -> str:
    """Frase simples sobre que tipo de disco os números indicam."""
    s = r.seq_read
    if s >= 2500:
        kind = "SSD NVMe rápido (PCIe 4.0 ou superior)"
    elif s >= 1200:
        kind = "SSD NVMe"
    elif s >= 350:
        kind = "SSD SATA"
    elif s >= 90:
        kind = "disco rígido (HDD) ou SSD/pen USB"
    else:
        kind = "disco lento (pen USB, cartão de memória ou disco com problemas)"
    tip = ""
    if r.rnd_read and r.rnd_read < 5 and s >= 350:
        tip = " Leitura aleatória baixa para um SSD — verifique se o disco está quase cheio ou a aquecer."
    return f"Velocidades típicas de {kind}.{tip}"
