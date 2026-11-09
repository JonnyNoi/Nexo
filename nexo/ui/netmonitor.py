"""Monitor da ligação à internet para a interface.

- testa em segundo plano: a cada 30 s com internet, a cada 6 s sem ela (deteta logo quando volta);
- reage na hora quando o sistema avisa que a rede mudou (QNetworkInformation: NetworkManager no Linux,
  Network List Manager no Windows), se esse suporte existir;
- só declara "sem internet" depois de duas falhas seguidas, para não dar alarmes falsos numa falha breve;
- `require_online()` deixa as funções que descarregam ficheiros avisar o utilizador antes de tentar.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from ..core import network as net
from .widgets import notify, run_async

ONLINE_EVERY = 30_000
OFFLINE_EVERY = 6_000


class NetMonitor(QObject):
    changed = Signal(object)  # NetStatus — só quando o estado muda
    checked = Signal(object)  # NetStatus — a cada teste concluído

    _inst: "NetMonitor | None" = None

    @classmethod
    def instance(cls) -> "NetMonitor":
        if cls._inst is None:
            cls._inst = NetMonitor()
        return cls._inst

    def __init__(self):
        super().__init__()
        self.status: net.NetStatus | None = None
        self._busy = False
        self._again = False
        self._fails = 0
        self._started = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(lambda: self.refresh(full=False))
        self._soon = QTimer(self)
        self._soon.setSingleShot(True)
        self._soon.timeout.connect(lambda: self.refresh(full=True))
        self._watch_os()

    def start(self):
        if not self._started:
            self._started = True
            self.refresh(full=True)
            self._timer.start(ONLINE_EVERY)

    @property
    def online(self) -> bool | None:
        """True/False, ou None se ainda não houve nenhum teste."""
        return None if self.status is None else self.status.online

    # ------------------------------------------------------------------
    def _watch_os(self):
        try:
            from PySide6.QtNetwork import QNetworkInformation
            if QNetworkInformation.loadDefaultBackend() and QNetworkInformation.instance():
                info = QNetworkInformation.instance()
                info.reachabilityChanged.connect(lambda *_a: self._soon.start(1500))
                if hasattr(info, "isBehindCaptivePortalChanged"):
                    info.isBehindCaptivePortalChanged.connect(lambda *_a: self._soon.start(500))
        except Exception:  # noqa: BLE001 — sem suporte, fica só o teste periódico
            pass

    def refresh(self, full: bool = True):
        if self._busy:
            self._again = True
            return
        self._busy = True
        # com internet basta o teste rápido; sem ela fazemos sempre o completo (para detetar portais)
        if self.status is not None and not self.status.online:
            full = True
        run_async(net.check, full, on_done=self._done, on_fail=self._fail)

    def _fail(self, _msg):
        self._busy = False

    def _done(self, st: net.NetStatus):
        self._busy = False
        old = self.status
        if not st.online and old is not None and old.online and self._fails == 0:
            # primeira falha depois de estar ligado: confirma daqui a 3 s antes de avisar
            self._fails = 1
            self._soon.start(3000)
            return
        self._fails = 0
        self.status = st
        self._timer.setInterval(ONLINE_EVERY if st.online else OFFLINE_EVERY)
        self.checked.emit(st)
        if old is None or old.state != st.state or old.short() != st.short():
            self.changed.emit(st)
        if old is not None and old.state != st.state:
            self._announce(old, st)
        elif old is None and not st.online:
            notify(f"{st.label}: as funções que descarregam ficheiros ficam indisponíveis até a ligação voltar.",
                   st.level)
        if self._again:
            self._again = False
            self._soon.start(200)

    @staticmethod
    def _announce(old: net.NetStatus, st: net.NetStatus):
        if st.online:
            notify("Ligação à internet restabelecida." if not old.online else
                   f"Ligação à internet: {st.short()}.", "ok")
        elif st.state == net.PORTAL:
            notify("Esta rede pede início de sessão no navegador antes de dar acesso à internet.", "warn")
        elif st.state == net.NO_DNS:
            notify("O DNS deixou de responder — os sites não abrem. Pode trocar o DNS em Utilitários.", "warn")
        elif st.state == net.OFFLINE:
            notify("Perdeu a ligação à rede (Wi-Fi ou cabo desligado).", "bad")
        else:
            notify("Perdeu o acesso à internet — a rede local continua ligada.", "warn")


def monitor() -> NetMonitor:
    return NetMonitor.instance()


def require_online(what: str = "Esta função") -> bool:
    """Para chamar antes de descarregar algo. Se o último teste disse que não há internet, avisa,
    volta a testar e devolve False. Se ainda não houve teste (ou há internet), devolve True."""
    m = monitor()
    st = m.status
    if st is None or st.online:
        return True
    notify(f"{what} precisa de internet — {st.label.lower()}. {st.detail}", st.level)
    m.refresh(full=True)
    return False
