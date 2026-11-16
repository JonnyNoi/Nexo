"""Tipos partilhados do antivírus (resultados e relatório)."""
from __future__ import annotations

from dataclasses import dataclass, field

BAD, WARN, INFO = "bad", "warn", "info"
LEVEL_NAMES = {BAD: "Ameaça", WARN: "Suspeito", INFO: "Informação"}
LEVEL_ORDER = [BAD, WARN, INFO]


@dataclass
class Finding:
    level: str              # bad | warn | info
    category: str           # Ficheiro, Processo, Arranque, Rede, Sistema, Antivírus
    title: str
    detail: str = ""
    path: str = ""
    pid: int = 0
    engine: str = ""        # "defender" quando foi o Defender a detetar

    @property
    def key(self) -> str:
        return f"{self.category}|{self.title}|{self.path}"


@dataclass
class Report:
    mode: str
    findings: list[Finding] = field(default_factory=list)
    engine: str = ""            # motor usado (ou "" se nenhum)
    engine_note: str = ""       # aviso sobre o motor (não instalado, sem assinaturas…)
    files_scanned: int = 0
    started: float = 0.0
    duration: float = 0.0
    cancelled: bool = False
    ignored: int = 0

    def count(self, level: str) -> int:
        return sum(1 for f in self.findings if f.level == level)


def _tail(out: str, n: int = 3) -> str:
    lines = [x for x in (out or "").splitlines() if x.strip()]
    return " · ".join(lines[-n:]) or "falhou"
