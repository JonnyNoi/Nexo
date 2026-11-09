"""Página "Saúde dos discos": S.M.A.R.T. de cada disco — vida restante, temperatura, erros e veredicto."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QGridLayout, QHeaderView, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ...core import smart
from ...core.util import IS_WIN, human_bytes, human_duration
from .. import theme
from ..widgets import Bar, Card, Page, Tip, hbox, icon_badge, label, notify, run_async, separator, status_dot

VERDICT = {"ok": ("Bom", "check"), "warn": ("Atenção", "alert"), "bad": ("Mau", "alert"),
           "unknown": ("Sem dados", "info")}


class DiskHealthPage(Page):
    def __init__(self):
        super().__init__("Saúde dos discos", "Lê os dados S.M.A.R.T. que cada disco regista sobre si próprio e diz se "
                                             "está de boa saúde, quanto já gastou e se há sinais de avaria.")
        self.btn_read = QPushButton("Ler discos")
        self.btn_read.setObjectName("Primary")
        self.btn_read.clicked.connect(self.read)
        self.head.addWidget(self.btn_read)

        top = Card("Estado", icon="hdd")
        self.status = label("", "Muted", wrap=True)
        top.add(self.status)
        self.install_row = QWidget()
        self.install_row.setObjectName("Transparent")
        self.btn_install = QPushButton("Instalar smartmontools")
        self.btn_install.clicked.connect(self._install)
        self.install_row.setLayout(hbox(Tip("Para ler os discos o Nexo usa o <b>smartctl</b> (pacote "
                                            "<b>smartmontools</b>), que não está instalado." +
                                            (" Sem ele mostra só o que o Windows reporta." if IS_WIN else ""),
                                            "warn"), self.btn_install))
        top.add(self.install_row)
        if smart.needs_password():
            top.add(label("Ler os dados dos discos precisa de permissões de administrador: a palavra-passe é "
                          "pedida uma vez por leitura. O resultado fica guardado e aparece também na "
                          "Saúde do sistema da Visão geral.", "Muted", wrap=True))
        self.add(top)

        self.list_holder = QWidget()
        self.list_holder.setObjectName("Transparent")
        self.list_lay = QVBoxLayout(self.list_holder)
        self.list_lay.setContentsMargins(0, 0, 0, 0)
        self.list_lay.setSpacing(16)
        self.add(self.list_holder)

        help_ = Card("Como ler isto", icon="info")
        help_.add(label(
            "• <b>Vida restante</b>: os SSD aguentam um número limitado de escritas; 100% é novo. Abaixo de 10% "
            "convém substituir.<br>"
            "• <b>Setores realocados / pendentes</b> (discos SATA): zonas estragadas. Se o número sobe de uma "
            "leitura para a outra, o disco está a degradar-se — faça cópia de segurança.<br>"
            "• <b>Erros CRC</b>: quase sempre o cabo SATA ou a ficha, não o disco.<br>"
            "• <b>Desligamentos inesperados</b>: cortes de energia ou desligar à força. Não é avaria, mas pode "
            "corromper ficheiros.<br>"
            "• Um veredicto «Bom» não garante que o disco nunca falha — tenha sempre cópia do que é importante.",
            "Muted", wrap=True))
        self.add(help_)
        self.body.addStretch(1)
        self._busy = False
        self._shown_time = None

    # ------------------------------------------------------------------
    def on_show(self):
        self.install_row.setVisible(not smart.smartctl_path())
        data = smart.cached()
        if data and data.get("time") != self._shown_time:
            self._show(data)
        elif not data:
            self.status.setText("Ainda não leu os discos. Carregue em «Ler discos»." if smart.needs_password()
                                else "A ler os discos…")
            if not smart.needs_password() and not self._busy:
                self.read()

    def refresh(self):
        self.read()

    def read(self):
        if self._busy:
            return
        if not smart.smartctl_path() and not IS_WIN:
            notify("Instale primeiro o smartmontools.", "warn")
            return
        self._busy = True
        self.btn_read.setEnabled(False)
        self.btn_read.setText("A ler…")
        self.status.setText("A ler os dados S.M.A.R.T. dos discos…")

        def done(res):
            self._busy = False
            self.btn_read.setEnabled(True)
            self.btn_read.setText("Ler discos")
            if res.get("disks"):
                self._show(res)
                bad = [d for d in res["disks"] if d["verdict"] in ("bad", "warn")]
                notify(f"{len(bad)} disco(s) precisam de atenção." if bad else "Os discos estão de boa saúde.",
                       "warn" if bad else "ok")
                win = self.window()
                if hasattr(win, "set_nav_badge"):
                    win.set_nav_badge("Saúde dos discos", str(len(bad)) if bad else None, "bad")
            else:
                self.status.setText(res.get("error") or "Não foi possível ler os discos.")

        def fail(msg):
            self._busy = False
            self.btn_read.setEnabled(True)
            self.btn_read.setText("Ler discos")
            self.status.setText(f"Erro: {msg}")
        run_async(smart.read_all, on_done=done, on_fail=fail)

    def _install(self):
        self.btn_install.setEnabled(False)
        self.btn_install.setText("A instalar…")

        def done(res):
            ok, msg = res
            self.btn_install.setEnabled(True)
            self.btn_install.setText("Instalar smartmontools")
            notify(msg, "ok" if ok else "bad")
            if ok:
                self.install_row.hide()
                self.read()
        run_async(smart.install_smartmontools, on_done=done)

    # ------------------------------------------------------------------
    def _show(self, data: dict):
        self._shown_time = data.get("time")
        while self.list_lay.count():
            w = self.list_lay.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        disks = data.get("disks", [])
        ago = time.time() - (data.get("time") or time.time())
        when = "agora mesmo" if ago < 60 else f"há {human_duration(ago).split(' ')[0]}"
        counts = {k: sum(1 for d in disks if d["verdict"] == k) for k in VERDICT}
        parts = [f"{status_dot('ok')} {counts['ok']} bom"]
        if counts["warn"]:
            parts.append(f"{status_dot('warn')} {counts['warn']} com atenção")
        if counts["bad"]:
            parts.append(f"{status_dot('bad')} {counts['bad']} com problemas")
        if counts["unknown"]:
            parts.append(f"{status_dot('muted')} {counts['unknown']} sem dados")
        self.status.setTextFormat(Qt.RichText)
        self.status.setText(f"{len(disks)} disco(s) · última leitura {when} &nbsp; " + " &nbsp; ".join(parts))
        order = {"bad": 0, "warn": 1, "unknown": 2, "ok": 3}
        for d in sorted(disks, key=lambda x: order.get(x["verdict"], 9)):
            self.list_lay.addWidget(self._disk_card(d))

    def _disk_card(self, d: dict) -> Card:
        sub = " · ".join(x for x in (d["kind"], human_bytes(d["size"], 0) if d["size"] else "", d["dev"],
                                     f"firmware {d['firmware']}" if d["firmware"] else "") if x)
        card = Card(d["model"], sub, icon="hdd")
        verdict, ic = VERDICT.get(d["verdict"], VERDICT["unknown"])
        kind = d["verdict"] if d["verdict"] in ("ok", "warn", "bad") else "info"
        v = label(verdict, "Big")
        v.setStyleSheet(f"color: {theme.C.get(kind, theme.C['muted'])}")
        card.head.addWidget(icon_badge(ic, 34, 18, kind), 0, Qt.AlignVCenter)
        card.head.addWidget(v, 0, Qt.AlignVCenter)

        if d.get("error") and not d["attrs"]:
            card.add(Tip(d["error"], "warn"))
            return card

        grid = QGridLayout()
        grid.setHorizontalSpacing(28)
        grid.setVerticalSpacing(2)
        tiles = []
        if d["life"] is not None:
            tiles.append(("Vida restante", f"{d['life']:.0f}%"))
        t = d["temp"]
        if isinstance(t, (int, float)) and t > 0:
            tiles.append(("Temperatura", f"{t:.0f} °C"))
        if d["hours"] is not None:
            h = int(d["hours"])
            tiles.append(("Tempo ligado", f"{h:,} h".replace(",", " ") + (f" (~{h / 8760:.1f} anos)" if h >= 8760
                                                                             else "")))
        if d["written"]:
            tiles.append(("Dados escritos", human_bytes(d["written"])))
        if d["read"]:
            tiles.append(("Dados lidos", human_bytes(d["read"])))
        if d["cycles"] is not None:
            tiles.append(("Ligado/desligado", f"{d['cycles']}×"))
        if d["unsafe"]:
            tiles.append(("Desligamentos inesperados", str(d["unsafe"])))
        for i, (name, val) in enumerate(tiles):
            t1 = label(name.upper(), "Muted")
            t2 = label(val, "CardTitle")
            grid.addWidget(t1, 0, i)
            grid.addWidget(t2, 1, i)
        grid.setColumnStretch(len(tiles), 1)
        card.add(grid)
        if d["life"] is not None:
            bar = Bar(8)
            bar.set(d["life"], "bad" if d["life"] <= 10 else "warn" if d["life"] <= 25 else "ok")
            card.add(bar)

        card.add(separator())
        reasons = d.get("reasons") or []
        if not reasons:
            ok = "Sem sinais de avaria: sem setores estragados nem erros registados."
            if d["passed"] is True:
                ok = "O disco passa na autoavaliação S.M.A.R.T. e não há sinais de avaria."
            card.add(label(f"{status_dot('ok')} {ok}", wrap=True))
        for k, text in reasons:
            lb = label(f"{status_dot(k)} {text}", wrap=True)
            card.add(lb)
        if d.get("selftest"):
            card.add(label(f"Último autoteste: {d['selftest']}", "Muted", wrap=True))

        table = QTableWidget(len(d["attrs"]), 3)
        table.setHorizontalHeaderLabels(["Atributo", "Valor", "Normalizado"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        table.setColumnWidth(1, 200)
        table.setColumnWidth(2, 220)
        table.verticalHeader().setVisible(False)
        table.verticalHeader().setDefaultSectionSize(30)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionBehavior(QTableWidget.SelectRows)
        if not any(a[2] for a in d["attrs"]):
            table.hideColumn(2)
        for r, (name, val, norm, k) in enumerate(d["attrs"]):
            for c, txt in enumerate((name, val, norm)):
                it = QTableWidgetItem(txt)
                if k in ("warn", "bad") and c == 1:
                    it.setForeground(theme.qc(k))
                table.setItem(r, c, it)
        table.setFixedHeight(min(420, 34 + 30 * max(1, len(d["attrs"]))))
        table.hide()

        btn_det = QPushButton("Ver todos os atributos")
        btn_det.setObjectName("Ghost")
        btn_det.setCheckable(True)
        btn_det.toggled.connect(lambda on: (table.setVisible(on),
                                            btn_det.setText("Esconder atributos" if on else "Ver todos os atributos")))
        row = hbox(btn_det)
        if d.get("can_selftest") and smart.smartctl_path():
            btn_t = QPushButton("Autoteste rápido (2 min)")
            btn_t.setToolTip("O disco verifica-se a si próprio em segundo plano; pode continuar a usar o PC.")
            btn_t.clicked.connect(lambda _c=False, dev=d["dev"]: self._selftest(dev))
            row.addWidget(btn_t)
        row.addStretch(1)
        if d["serial"]:
            row.addWidget(label(f"N.º de série {d['serial']}", "Muted"))
        if d["attrs"]:
            card.add(row)
            card.add(table)
        return card

    def _selftest(self, dev: str):
        def done(res):
            ok, msg = res
            notify(msg, "ok" if ok else "bad")
        run_async(smart.start_selftest, dev, on_done=done)
