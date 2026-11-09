#!/usr/bin/env sh
# Executa o Nexo no Linux (cria o ambiente virtual na primeira vez)
cd "$(dirname "$0")" || exit 1
if [ ! -x .venv/bin/python ]; then
    python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt || exit 1
fi
exec .venv/bin/python run_nexo.py "$@"
