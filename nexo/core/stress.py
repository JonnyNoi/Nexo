"""Stress test de CPU (todos os threads) e RAM (escreve e verifica padrões).

Os trabalhadores correm em processos separados (multiprocessing) para contornar o GIL
e ocupar 100% de cada núcleo. As funções de trabalho estão ao nível do módulo para
funcionarem com o método "spawn" do Windows.
"""
from __future__ import annotations

import math
import multiprocessing as mp
import os
import queue
import time

import psutil


# ------------------------------------------------------------------ trabalhadores
def _cpu_worker(stop, counter) -> None:
    try:
        p = psutil.Process()
        p.nice(10 if os.name != "nt" else psutil.BELOW_NORMAL_PRIORITY_CLASS)  # mantém o PC utilizável
    except Exception:
        pass
    x, y, n = 1.0001, 0.9999, 0
    a, b = 0x12345678, 0x9ABCDEF
    while not stop.is_set():
        for _ in range(20000):
            # vírgula flutuante (FPU) …
            x = x * y + math.sqrt(x) * 1e-9
            y = math.sin(y) + 0.9999
            # … e inteiros
            a = (a * 1103515245 + 12345) & 0xFFFFFFFF
            b ^= (a << 7) & 0xFFFFFFFF
        n += 1
        with counter.get_lock():
            counter.value += 1
    _ = (x, y, a, b, n)


def _ram_worker(stop, size_bytes: int, q) -> None:
    chunk = 64 * 1024**2
    chunks: list[bytearray] = []
    try:
        for _ in range(max(1, size_bytes // chunk)):
            if stop.is_set():
                return
            chunks.append(bytearray(chunk))
    except MemoryError:
        q.put(("log", f"Só foi possível reservar {len(chunks) * 64} MB de RAM."))
    q.put(("log", f"RAM reservada: {len(chunks) * 64} MB em {len(chunks)} blocos."))
    patterns = [b"\x55", b"\xAA", b"\x00", b"\xFF", bytes(range(256)), b"\xDE\xAD\xBE\xEF", b"\x0F\xF0"]
    passes = 0
    while not stop.is_set():
        for pat in patterns:
            ref = (pat * (chunk // len(pat) + 1))[:chunk]
            for c in chunks:
                if stop.is_set():
                    return
                c[:] = ref
            for i, c in enumerate(chunks):
                if stop.is_set():
                    return
                if c != ref:
                    bad = sum(1 for j in range(0, chunk, 4096) if c[j:j + 4096] != ref[j:j + 4096])
                    q.put(("error", f"Erro de memória no bloco {i} (padrão {pat[:4].hex()}): {bad} páginas diferentes"))
            del ref
        passes += 1
        q.put(("pass", passes))


# ------------------------------------------------------------------ controlador
class StressTest:
    def __init__(self) -> None:
        self._ctx = mp.get_context("spawn")
        self._procs: list[mp.Process] = []
        self._stop = None
        self.counter = None
        self.q = None
        self.started = 0.0

    @property
    def running(self) -> bool:
        return any(p.is_alive() for p in self._procs)

    def start(self, cpu_threads: int, ram_percent: int) -> None:
        self.stop()
        self._stop = self._ctx.Event()
        self.counter = self._ctx.Value("Q", 0)
        self.q = self._ctx.Queue()
        for _ in range(cpu_threads):
            p = self._ctx.Process(target=_cpu_worker, args=(self._stop, self.counter), daemon=True)
            p.start()
            self._procs.append(p)
        if ram_percent > 0:
            size = int(psutil.virtual_memory().available * ram_percent / 100)
            p = self._ctx.Process(target=_ram_worker, args=(self._stop, size, self.q), daemon=True)
            p.start()
            self._procs.append(p)
        self.started = time.monotonic()

    def poll_messages(self) -> list[tuple[str, object]]:
        msgs = []
        if not self.q:
            return msgs
        while True:
            try:
                msgs.append(self.q.get_nowait())
            except (queue.Empty, OSError, ValueError):
                break
        return msgs

    def ops(self) -> int:
        return self.counter.value if self.counter else 0

    def stop(self) -> None:
        if self._stop is not None:
            self._stop.set()
        for p in self._procs:
            p.join(timeout=2)
            if p.is_alive():
                p.terminate()
        self._procs.clear()
