from __future__ import annotations

import multiprocessing
import sys


def main() -> int:
    multiprocessing.freeze_support()  # necessário no .exe do Windows (PyInstaller)
    from .core import log as nlog
    if "--gpubench" in sys.argv:
        nlog.setup("gpubench")  # benchmark da placa gráfica (processo à parte, ver core/gpubench.py)
        from .core.gpubench import main_from_argv
        return main_from_argv(sys.argv)
    if "--overlay" in sys.argv:
        nlog.setup("overlay")  # processo do overlay de jogo (lançado pela janela principal)
        from .ui.overlay import run
        return run()
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication

    from .core.util import APP_NAME, get_setting
    from .ui import theme

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setDesktopFileName("nexo")

    # instância única: se já houver um Nexo aberto, pede-lhe para aparecer e sai
    server_name = f"{APP_NAME}-single-instance"
    sock = QLocalSocket()
    sock.connectToServer(server_name)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return 0
    QLocalServer.removeServer(server_name)  # limpa um socket órfão (o programa terminou mal)
    server = QLocalServer()
    server.listen(server_name)

    nlog.setup()
    from .ui import crash
    from .ui.main_window import MainWindow

    theme.apply(app)
    minimized = "--minimized" in sys.argv or get_setting("start_minimized")
    win = MainWindow(start_hidden=minimized)
    app.setQuitOnLastWindowClosed(False)  # a janela decide quando sair (pode ficar na bandeja)
    app.setWindowIcon(win.windowIcon())
    crash.install(lambda: win if win.isVisible() else None)

    def on_connection():
        c = server.nextPendingConnection()
        if c is not None:
            c.disconnected.connect(c.deleteLater)
        win.show_window()
    server.newConnection.connect(on_connection)

    if not win._start_hidden:
        win.show()
    code = app.exec()
    nlog.log.info("Nexo terminou (código %s)", code)
    return code


if __name__ == "__main__":
    sys.exit(main())
