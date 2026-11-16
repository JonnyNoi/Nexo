"""Idioma da interface: português (original) ou inglês.

O texto continua escrito em português no código; em inglês, `tr()` procura a tradução:
  1. correspondência exata no catálogo (`nexo/core/i18n_en.py` → EN);
  2. modelos com `{}` (TEMPLATES) para textos com valores no meio ("Saúde do PC: {}" → "PC health: {}");
     os valores apanhados também passam pelo catálogo.
O que não estiver traduzido aparece em português. `python -m nexo.core.i18n` lista o que falta traduzir
nos ficheiros indicados (ou em todo o nexo/).

A interface Qt aplica `tr()` automaticamente (ver ui/i18n_qt.py), por isso o código não precisa de mudar.
Mudar o idioma pede um reinício do Nexo."""
from __future__ import annotations

import re
from functools import lru_cache

from .util import get_setting

LANGS = {"pt": "Português", "en": "English (beta)"}
_lang: str | None = None


def lang() -> str:
    global _lang
    if _lang is None:
        v = get_setting("language") or "pt"
        _lang = v if v in LANGS else "pt"
    return _lang


def set_lang_for_tests(v: str | None) -> None:
    global _lang
    _lang = v
    _templates.cache_clear()


@lru_cache(maxsize=1)
def _catalog() -> dict[str, str]:
    from .i18n_en import EN
    from .i18n_en_more import EN_MORE
    return {**EN_MORE, **EN}


@lru_cache(maxsize=1)
def _upper() -> dict[str, str]:
    """Títulos em maiúsculas ("PROCESSADOR") → tradução em maiúsculas."""
    return {k.upper(): v.upper() for k, v in _catalog().items()}


@lru_cache(maxsize=1)
def _templates() -> list[tuple[re.Pattern, str]]:
    from .i18n_en import TEMPLATES
    from .i18n_en_more import TEMPLATES_MORE
    out = []
    for src, dst in {**TEMPLATES_MORE, **TEMPLATES}.items():
        out.append((re.compile("(.+?)".join(re.escape(p) for p in src.split("{}")), re.S), dst))
    # os modelos mais compridos primeiro (mais específicos)
    out.sort(key=lambda t: -len(t[0].pattern))
    return out


def tr(s: str) -> str:
    if not s or lang() == "pt" or not isinstance(s, str):
        return s
    return _tr(s, 0)


def _tr(s: str, depth: int) -> str:
    cat = _catalog()
    t = cat.get(s)
    if t is not None:
        return t
    if s.isupper() and s in _upper():
        return _upper()[s]
    stripped = s.strip()
    if stripped != s and stripped in cat:     # "  Procurar…" (espaços para o ícone)
        lead = s[:len(s) - len(s.lstrip())]
        trail = s[len(s.rstrip()):]
        return lead + cat[stripped] + trail
    if depth < 2:
        for rx, dst in _templates():
            m = rx.fullmatch(s)
            if m:
                return dst.format(*(_tr(g, depth + 1) for g in m.groups()))
        if "<br>" in s:                      # texto rico com várias linhas: linha a linha
            parts = s.split("<br>")
            out = [_tr(p, depth + 1) for p in parts]
            if out != parts:
                return "<br>".join(out)
    return s


def missing(strings) -> list[str]:
    """Textos (com letras) que ainda não têm tradução."""
    prev = _lang
    set_lang_for_tests("en")
    try:
        return [s for s in strings if re.search(r"[A-Za-zÀ-ÿ]{3,}", s) and tr(s) == s]
    finally:
        set_lang_for_tests(prev)


_LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
_VISIBLE = re.compile(r"[a-zçãõáéíóúâêô]{3,} [a-zçãõáéíóúâêô]{2,}", re.I)


def _template(node) -> str | None:
    """f-string → modelo com {} (como em TEMPLATES): f"Ligado há {x}" → "Ligado há {}"."""
    import ast
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            parts.append(v.value.replace("{", "{{").replace("}", "}}"))
        else:
            parts.append("{}")
    return "".join(parts)


def _scan(paths) -> list[str]:
    """Textos que parecem frases visíveis (heurística). As f-strings aparecem como modelos com {};
    mensagens do registo (log.warning(…)) e docstrings ficam de fora."""
    import ast
    from pathlib import Path
    out: list[str] = []
    seen: set[str] = set()
    for p in paths:
        for f in ([Path(p)] if str(p).endswith(".py") else Path(p).rglob("*.py")):
            if f.name.startswith("i18n"):
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            skip: set[int] = set()
            for n in ast.walk(tree):
                if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)) and n.body \
                        and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant):
                    skip.add(id(n.body[0].value))
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in _LOG_METHODS:
                    for a in n.args:
                        for sub in ast.walk(a):
                            skip.add(id(sub))
                if isinstance(n, ast.JoinedStr):
                    for v in n.values:
                        skip.add(id(v))
            for n in ast.walk(tree):
                if id(n) in skip:
                    continue
                if isinstance(n, ast.JoinedStr):
                    val = _template(n)
                elif isinstance(n, ast.Constant) and isinstance(n.value, str):
                    val = n.value
                else:
                    continue
                if (val and _VISIBLE.search(val) and not val.startswith(("http", "/", "$", "-", "Q", "%"))
                        and val not in seen):
                    seen.add(val)
                    out.append(val)
    return out


if __name__ == "__main__":   # python -m nexo.core.i18n [ficheiros…]
    import sys
    todo = missing(_scan(sys.argv[1:] or ["nexo"]))
    for s in todo:
        print(repr(s))
    print(f"\n{len(todo)} textos por traduzir", file=sys.stderr)
