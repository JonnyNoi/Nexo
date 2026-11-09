"""Ponto de entrada (usado também pelo PyInstaller para gerar o executável)."""
import multiprocessing
import sys

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from nexo.app import main
    sys.exit(main())
