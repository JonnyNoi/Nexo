"""Janela "Ocorreu um erro" para exceções não tratadas — o Nexo continua a funcionar."""
from __future__ import annotations

import time

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QMessageBox

from ..core import log as nlog
from ..core.util import open_path

_open = False
_seen: dict[str, float] = {}


def install(parent_getter=lambda: None) -> None:
    def handler(summary: str, details: str):
        global _open
        # o mesmo erro repetido (ex.: num temporizador) só abre a janela uma vez por sessão
        key = details.strip().splitlines()[-1] if details.strip() else summary
        first = key not in _seen
        _seen[key] = time.time()
        if _open or not first:
            return
        _open = True
        try:
            box = QMessageBox(parent_getter())
            box.setIcon(QMessageBox.Warning)
            box.setWindowTitle("Ocorreu um erro")
            box.setText("O Nexo encontrou um erro inesperado, mas continua a funcionar.")
            box.setInformativeText(f"{summary}\n\nO erro ficou registado em:\n{nlog.log_path()}")
            box.setDetailedText(f"{nlog.system_summary()}\n\n{details}")
            b_copy = box.addButton("Copiar detalhes", QMessageBox.ActionRole)
            b_log = box.addButton("Abrir registo", QMessageBox.ActionRole)
            box.addButton("Fechar", QMessageBox.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is b_copy:
                QGuiApplication.clipboard().setText(f"{nlog.system_summary()}\n\n{details}")
            elif clicked is b_log:
                open_path(nlog.log_path())
        finally:
            _open = False
    nlog.set_error_handler(handler)
