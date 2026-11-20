"""Cartão «BIOS / UEFI» (página Atualizações): versão, idade, fwupd e página de suporte do fabricante."""
from __future__ import annotations

import time

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QPushButton

from ..core import bios
from .widgets import Card, StatTile, Tip, hbox, label, notify, run_async


class BiosCard(Card):
    def __init__(self):
        super().__init__("BIOS / UEFI", "Versão instalada, há quanto tempo saiu e onde procurar uma mais recente. "
                         "Versões novas trazem correções de segurança e estabilidade e suporte para "
                         "processadores e memórias novos.", icon="cpu")
        self.btn = QPushButton("Verificar")
        self.btn.clicked.connect(self.check)
        self.head.addWidget(self.btn)
        row = hbox()
        self.t_ver = StatTile("Versão", "—", "")
        self.t_date = StatTile("Data", "—", "")
        self.t_board = StatTile("Placa-mãe", "—", "")
        for t in (self.t_ver, self.t_date, self.t_board):
            row.addWidget(t, 1)
        self.add(row)
        self.tip = Tip("Ainda não verificado.", "info")
        self.add(self.tip)
        self.btn_site = QPushButton("Página de suporte do fabricante")
        self.btn_site.setObjectName("Primary")
        self.btn_site.clicked.connect(self._open_site)
        self.btn_fw = QPushButton("Atualizar pelo fwupd")
        self.btn_fw.setToolTip("Abre um terminal com «fwupdmgr update» — confirme lá cada passo. Não desligue o PC "
                               "durante a atualização.")
        self.btn_fw.clicked.connect(self._fwupd)
        self.btn_fw.hide()
        self.note = label("O Nexo não instala o BIOS: use a ferramenta do fabricante (ex.: M-Flash, EZ Flash, "
                          "Q-Flash) ou o fwupd. Não desligue o PC durante uma atualização do BIOS.", "Muted", wrap=True)
        self.add(hbox(self.btn_site, self.btn_fw, None))
        self.add(self.note)
        self._url = ""
        self._busy = False
        c = bios.cached()
        if c:
            self._show(c)

    def ensure_checked(self):
        c = bios.cached()
        if not c or time.time() - c.get("time", 0) > 86400:
            self.check()

    def check(self):
        if self._busy:
            return
        self._busy = True
        self.btn.setEnabled(False)

        def done(res):
            self._busy = False
            self.btn.setEnabled(True)
            self._show(res)

        def fail(m):
            self._busy = False
            self.btn.setEnabled(True)
            notify(f"Não foi possível ler o BIOS: {m}", "bad")
        run_async(bios.check, on_done=done, on_fail=fail)

    def _show(self, res: dict):
        info = bios.BiosInfo(**{k: v for k, v in (res.get("info") or {}).items()
                                if k in bios.BiosInfo.__dataclass_fields__})
        self.t_ver.set(info.version or "—", info.vendor)
        age = info.age_days
        sub = ""
        if age is not None:
            sub = f"há {age / 365:.1f} anos" if age >= 365 else f"há {max(1, int(age / 30))} meses"
        self.t_date.set(info.date or "—", sub, "warn" if age and age >= bios.OLD_YEARS * 365 else None)
        if res.get("oem"):
            self.t_board.set(info.system or "—", info.system_vendor)
        else:
            self.t_board.set(info.board or "—", info.board_vendor)
        kind = res.get("kind", "info")
        self._set_tip(res.get("text", ""), kind if kind in ("warn", "ok") else "info")
        self._url = res.get("url") or ""
        self.btn_site.setVisible(bool(self._url))
        self.btn_fw.setVisible(bool(res.get("fwupd_update")))

    def _set_tip(self, text: str, kind: str):
        """O ícone do Tip depende do tipo: troca a caixa inteira."""
        new = Tip(text, kind)
        self.lay.replaceWidget(self.tip, new)
        self.tip.hide()
        self.tip.deleteLater()
        self.tip = new

    def _open_site(self):
        if self._url:
            QDesktopServices.openUrl(QUrl(self._url))

    def _fwupd(self):
        from ..core.updates import open_terminal
        ok, msg = open_terminal("fwupdmgr update")
        notify(msg, "info" if ok else "bad")
