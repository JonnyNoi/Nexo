from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QFont
from PySide6.QtWidgets import (QCheckBox, QFileDialog, QHBoxLayout, QHeaderView, QMenu, QProgressBar, QPushButton,
                               QTableWidget, QTableWidgetItem)

from ...core import antivirus as av
from ...core.util import IS_WIN, get_setting, human_bytes, human_duration, open_path
from .. import theme
from ..theme import qc
from ..netmonitor import require_online
from ..widgets import Card, Page, Task, confirm, label, notify, run_async, status_dot

_MODE_NAMES = {"quick": "rápida", "full": "completa", "folder": "de pasta"}


def _table(headers, stretch: int) -> QTableWidget:
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.horizontalHeader().setSectionResizeMode(stretch, QHeaderView.Stretch)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QTableWidget.NoEditTriggers)
    t.setSelectionBehavior(QTableWidget.SelectRows)
    t.setAlternatingRowColors(True)
    t.setWordWrap(False)
    return t


class AntivirusPage(Page):
    def __init__(self):
        engine = "Microsoft Defender" if IS_WIN else "ClamAV"
        super().__init__("Antivírus", f"Procura vírus em todo o sistema com o {engine} e com verificações próprias "
                                      "do Nexo: processos disfarçados, mineradores, programas de arranque, tarefas "
                                      "agendadas, rootkits e ficheiros suspeitos. Nada é apagado sem perguntar.")
        self.status: av.EngineStatus | None = None
        self.report: av.Report | None = None
        self.task: Task | None = None
        self.cancel = False
        self._loaded = False

        # ------------------------------------------------------------ proteção
        prot = Card("Proteção", f"Motor antivírus: {engine}", icon="virus")
        self.prot_lbl = label("A verificar…", wrap=True)
        self.prot_lbl.setTextFormat(Qt.RichText)
        prot.add(self.prot_lbl)
        row = QHBoxLayout()
        self.btn_update = QPushButton("Atualizar assinaturas")
        self.btn_update.clicked.connect(self._update_sigs)
        self.btn_install = QPushButton("Instalar ClamAV")
        self.btn_install.setObjectName("Primary")
        self.btn_install.clicked.connect(self._install)
        self.btn_install.hide()
        row.addWidget(self.btn_install)
        row.addWidget(self.btn_update)
        row.addStretch(1)
        prot.add(row)
        self.add(prot)

        # ------------------------------------------------------------ análise
        sc = Card("Analisar", "A rápida vê os sítios onde os vírus costumam estar (minutos). A completa analisa "
                              "o disco inteiro com o motor antivírus (pode demorar horas).", icon="search")
        row = QHBoxLayout()
        self.btn_quick = QPushButton("Análise rápida")
        self.btn_quick.setObjectName("Primary")
        self.btn_full = QPushButton("Análise completa")
        self.btn_folder = QPushButton("Analisar pasta…")
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.setObjectName("Danger")
        self.btn_cancel.hide()
        self.btn_quick.clicked.connect(lambda: self.start("quick"))
        self.btn_full.clicked.connect(lambda: self.start("full"))
        self.btn_folder.clicked.connect(self._pick_folder)
        self.btn_cancel.clicked.connect(self._cancel)
        for b in (self.btn_quick, self.btn_full, self.btn_folder, self.btn_cancel):
            row.addWidget(b)
        row.addStretch(1)
        self.chk_engine = QCheckBox(f"Usar o {engine}")
        self.chk_engine.setChecked(True)
        self.chk_engine.setToolTip("Desligado: só as verificações próprias do Nexo (muito mais rápido, "
                                   "mas não reconhece vírus por assinatura).")
        row.addWidget(self.chk_engine)
        sc.add(row)
        self.progress = QProgressBar()
        self.progress.setMaximum(1000)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(8)
        self.progress.hide()
        sc.add(self.progress)
        self.scan_lbl = label("", "Muted")
        sc.add(self.scan_lbl)
        if not IS_WIN:
            sc.add(label("No Linux a análise completa pede a palavra-passe de administrador para conseguir ler "
                         "os ficheiros do sistema.", "Muted", wrap=True))
        self.add(sc)

        # ------------------------------------------------------------ resultados
        res = Card("Resultados", icon="alert")
        self.summary = label("Ainda não fez nenhuma análise nesta sessão.", wrap=True)
        self.summary.setTextFormat(Qt.RichText)
        res.add(self.summary)
        self.table = _table(["Gravidade", "Tipo", "O que foi encontrado", "Local"], 2)
        self.table.setColumnWidth(0, 110)
        self.table.setColumnWidth(1, 100)
        self.table.setColumnWidth(3, 320)
        self.table.setMinimumHeight(260)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._menu)
        self.table.itemSelectionChanged.connect(self._selected)
        res.add(self.table, 1)
        self.detail = label("", "Muted", wrap=True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        res.add(self.detail)
        row = QHBoxLayout()
        self.btn_q = QPushButton("Pôr em quarentena")
        self.btn_q.setObjectName("Danger")
        self.btn_kill = QPushButton("Terminar processo")
        self.btn_open = QPushButton("Abrir localização")
        self.btn_ign = QPushButton("Ignorar")
        self.btn_ign.setToolTip("Não voltar a mostrar este resultado nas próximas análises")
        self.btn_def = QPushButton("Remover com o Defender")
        self.btn_def.setObjectName("Danger")
        self.btn_def.setVisible(False)
        self.btn_q.clicked.connect(self._quarantine)
        self.btn_kill.clicked.connect(self._kill)
        self.btn_open.clicked.connect(self._open)
        self.btn_ign.clicked.connect(self._ignore)
        self.btn_def.clicked.connect(self._defender_remove)
        for b in (self.btn_q, self.btn_kill, self.btn_def, self.btn_open, self.btn_ign):
            row.addWidget(b)
        row.addStretch(1)
        self.btn_unign = QPushButton("Voltar a mostrar ignorados")
        self.btn_unign.setObjectName("Ghost")
        self.btn_unign.clicked.connect(self._unignore)
        row.addWidget(self.btn_unign)
        res.add(row)
        self.add(res, 1)
        self._selected()

        # ------------------------------------------------------------ quarentena
        qc_ = Card("Quarentena", "Ficheiros isolados: ficam codificados e sem permissão de execução (não é cifra). "
                                 "Pode restaurá-los se forem falsos alarmes.", icon="shield")
        self.qtable = _table(["Ficheiro", "Local original", "Tamanho", "Data", "Motivo"], 1)
        self.qtable.setColumnWidth(0, 200)
        self.qtable.setColumnWidth(2, 90)
        self.qtable.setColumnWidth(3, 130)
        self.qtable.setColumnWidth(4, 240)
        self.qtable.setMinimumHeight(140)
        qc_.add(self.qtable)
        row = QHBoxLayout()
        b_res = QPushButton("Restaurar")
        b_del = QPushButton("Apagar definitivamente")
        b_del.setObjectName("Danger")
        b_res.clicked.connect(self._q_restore)
        b_del.clicked.connect(self._q_delete)
        row.addWidget(b_res)
        row.addWidget(b_del)
        row.addStretch(1)
        qc_.add(row)
        self.add(qc_)
        self._load_quarantine()

    # ================================================================== estado
    def on_show(self):
        if not self._loaded:
            self._loaded = True
            self._refresh_status()
        if self.report is None and self.task is None:
            # resultado da análise agendada (Tarefas agendadas), se for mais recente do que esta sessão
            from ...core import schedule
            rep = schedule.load_report()
            if rep is not None and rep.findings:
                self._on_done(rep, quiet=True)

    def refresh(self):
        self._refresh_status()

    def _refresh_status(self):
        self.prot_lbl.setText("A verificar o motor antivírus…")
        run_async(av.engine_status, on_done=self._show_status)

    def _show_status(self, st: av.EngineStatus):
        self.status = st
        lines = []
        if not st.installed:
            lines.append(f"{status_dot('warn')} <b>{st.name} não está instalado.</b> "
                         + ("Sem ele só correm as verificações próprias do Nexo." if not IS_WIN else ""))
        elif st.active:
            lines.append(f"{status_dot('ok')} <b>{st.name} ativo</b>"
                         + (" — proteção em tempo real ligada" if IS_WIN else " — pronto a analisar"))
        else:
            lines.append(f"{status_dot('bad' if IS_WIN else 'warn')} <b>{st.name} sem proteção ativa</b>")
        if st.signatures:
            lines.append(f"Assinaturas: {st.signatures}")
        if st.others:
            lines.append(f"Outros antivírus registados: {', '.join(st.others)}")
        if st.note and st.installed:
            lines.append(st.note)
        last = get_setting("av_last_scan")
        if isinstance(last, dict) and last.get("when"):
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(last["when"]))
            res = ("cancelada" if last.get("cancelled") else
                   f"{last.get('bad', 0)} ameaça(s), {last.get('warn', 0)} suspeito(s)")
            lines.append(f"Última análise: {_MODE_NAMES.get(last.get('mode'), '')} em {when} — {res}")
        self.prot_lbl.setText("<br>".join(lines))
        self.btn_install.setVisible(not IS_WIN and not st.installed and st.can_install)
        self.btn_update.setEnabled(st.installed)
        if not st.installed:
            self.chk_engine.setChecked(False)
            self.chk_engine.setEnabled(False)
        else:
            self.chk_engine.setEnabled(True)

    def _update_sigs(self):
        if not require_online("Atualizar as assinaturas"):
            return
        self.btn_update.setEnabled(False)
        self.btn_update.setText("A atualizar…")
        notify("A atualizar as assinaturas do antivírus…", "info")

        def done(r):
            ok, msg = r
            self.btn_update.setText("Atualizar assinaturas")
            self.btn_update.setEnabled(True)
            notify(msg, "ok" if ok else "bad")
            self._refresh_status()
        run_async(av.update_signatures, on_done=done)

    def _install(self):
        if not require_online("Instalar o ClamAV"):
            return
        if not confirm(self, "Instalar ClamAV", "Instalar o antivírus ClamAV com o gestor de pacotes do sistema e "
                                                "descarregar as assinaturas (~300 MB)?\n\nVai ser pedida a "
                                                "palavra-passe de administrador."):
            return
        self.btn_install.setEnabled(False)
        self.btn_install.setText("A instalar…")

        def done(r):
            ok, msg = r
            self.btn_install.setText("Instalar ClamAV")
            self.btn_install.setEnabled(True)
            notify(msg, "ok" if ok else "bad")
            self._refresh_status()
        run_async(av.install_engine, on_done=done)

    # ================================================================== análise
    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Escolha a pasta a analisar", os.path.expanduser("~"))
        if d:
            self.start("folder", d)

    def start(self, mode: str, target: str = ""):
        if self.task:
            return
        use_engine = self.chk_engine.isChecked() and self.chk_engine.isEnabled()
        if mode == "full" and use_engine and not confirm(
                self, "Análise completa", "A análise completa percorre o disco inteiro e pode demorar bastante "
                                          "(de minutos a algumas horas). Pode continuar a usar o computador e "
                                          "cancelar a qualquer momento.\n\nComeçar?"):
            return
        self.cancel = False
        self._busy(True)
        self.progress.setValue(0)
        self.scan_lbl.setText("A preparar…")
        holder: dict = {}

        def progress(frac, text):
            holder["t"].progress.emit((frac, text))

        t = Task(av.scan, mode, target, use_engine, progress, lambda: self.cancel)
        holder["t"] = t
        t.progress.connect(self._on_progress)
        t.done.connect(self._on_done)
        t.failed.connect(self._on_fail)
        self.task = t
        self._t0 = time.time()
        t.start()

    def _on_progress(self, ev):
        frac, text = ev
        if frac is not None:
            self.progress.setValue(int(frac * 1000))
        el = human_duration(time.time() - self._t0)
        text = text if len(text) < 150 else text[:70] + "…" + text[-70:]
        self.scan_lbl.setText(f"{text}   ·   {el}")

    def _cancel(self):
        self.cancel = True
        self.btn_cancel.setEnabled(False)
        self.scan_lbl.setText("A cancelar…")

    def _busy(self, on: bool):
        for b in (self.btn_quick, self.btn_full, self.btn_folder, self.chk_engine):
            b.setEnabled(not on)
        if not on and self.status and not self.status.installed:
            self.chk_engine.setEnabled(False)
        self.btn_cancel.setVisible(on)
        self.btn_cancel.setEnabled(True)
        self.progress.setVisible(on)

    def _on_fail(self, msg):
        self.task = None
        self._busy(False)
        self.scan_lbl.setText("")
        notify(f"A análise falhou: {msg}", "bad")

    def _on_done(self, rep: av.Report, quiet: bool = False):
        self.task = None
        self._busy(False)
        self.report = rep
        self.scan_lbl.setText("")
        bad, warn = rep.count(av.BAD), rep.count(av.WARN)
        what = f"Análise {_MODE_NAMES.get(rep.mode, '')}" + (" (cancelada — resultados parciais)" if rep.cancelled else "")
        info = f"{human_duration(rep.duration)} · {rep.files_scanned:,} ficheiros vistos".replace(",", ".")
        if rep.engine:
            info += f" · motor: {rep.engine}"
        if rep.ignored:
            info += f" · {rep.ignored} ignorado(s)"
        if bad:
            head = f"{status_dot('bad')} <b>{bad} ameaça(s) encontrada(s)</b>" + \
                   (f" e {warn} item(ns) suspeito(s)" if warn else "") + \
                   " — selecione cada uma para ver o que fazer."
            kind = "bad"
        elif warn:
            head = (f"{status_dot('warn')} <b>Nenhum vírus confirmado</b>, mas há {warn} item(ns) suspeito(s) "
                    "para rever.")
            kind = "warn"
        else:
            head = f"{status_dot('ok')} <b>Nenhuma ameaça encontrada.</b>"
            kind = "ok"
        txt = f"{head}<br><span style='color:{theme.C['muted']}'>{what} · {info}</span>"
        if rep.engine_note:
            txt += f"<br>{status_dot('warn')} {rep.engine_note}"
        self.summary.setText(txt)
        if not quiet:
            notify(f"{what}: " + ("nenhuma ameaça" if kind == "ok" else f"{bad} ameaça(s), {warn} suspeito(s)"), kind)
            from ...core import schedule
            try:
                schedule.save_report(rep)   # volta a aparecer depois de reabrir o Nexo
            except OSError:
                pass
        self._fill(rep.findings)
        self._refresh_status()

    # ================================================================== resultados
    def _fill(self, findings):
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(findings))
        colors = {av.BAD: "bad", av.WARN: "warn", av.INFO: "muted"}
        for i, f in enumerate(findings):
            lv = QTableWidgetItem(av.LEVEL_NAMES[f.level])
            lv.setData(Qt.UserRole, i)
            lv.setForeground(QBrush(qc(colors[f.level])))
            fo = QFont(lv.font())
            fo.setBold(f.level != av.INFO)
            lv.setFont(fo)
            self.table.setItem(i, 0, lv)
            self.table.setItem(i, 1, QTableWidgetItem(f.category))
            t = QTableWidgetItem(f.title)
            t.setToolTip(f.detail)
            self.table.setItem(i, 2, t)
            loc = f.path or (f"PID {f.pid}" if f.pid else "")
            li = QTableWidgetItem(loc)
            li.setToolTip(loc)
            self.table.setItem(i, 3, li)
        self.btn_def.setVisible(any(f.engine == "defender" and f.level == av.BAD for f in findings))
        if findings:
            self.table.selectRow(0)
        self._selected()

    def _current(self) -> av.Finding | None:
        if not self.report:
            return None
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        it = self.table.item(rows[0].row(), 0)
        idx = it.data(Qt.UserRole) if it else None
        return self.report.findings[idx] if idx is not None and idx < len(self.report.findings) else None

    def _selected(self):
        f = self._current()
        can_file = bool(f and f.path and os.path.isfile(f.path) and f.engine != "defender"
                        and f.category in ("Ficheiro", "Processo"))
        self.btn_q.setEnabled(can_file)
        self.btn_kill.setEnabled(bool(f and f.pid))
        self.btn_open.setEnabled(bool(f and f.path and os.path.exists(f.path)))
        self.btn_ign.setEnabled(f is not None)
        self.detail.setText(f"{f.title}\n{f.detail}" if f else "")

    def _menu(self, pos):
        f = self._current()
        if not f:
            return
        m = QMenu(self)
        if self.btn_q.isEnabled():
            m.addAction("Pôr em quarentena", self._quarantine)
        if self.btn_kill.isEnabled():
            m.addAction("Terminar processo", self._kill)
        if self.btn_open.isEnabled():
            m.addAction("Abrir localização", self._open)
        m.addAction("Ignorar nas próximas análises", self._ignore)
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _remove_row(self, f: av.Finding):
        self.report.findings.remove(f)
        self._fill(self.report.findings)

    def _quarantine(self):
        f = self._current()
        if not f or not f.path:
            return
        if not confirm(self, "Quarentena", f"Mover para a quarentena?\n\n{f.path}\n\nO ficheiro deixa de poder ser "
                                           "executado. Pode restaurá-lo mais tarde."):
            return
        if f.pid:
            av.kill_process(f.pid)  # um programa a correr pode impedir que o ficheiro seja movido
        ok, msg = av.quarantine(f.path, f.title)
        notify(msg, "ok" if ok else "bad")
        if ok:
            self._remove_row(f)
            self._load_quarantine()

    def _kill(self):
        f = self._current()
        if not f or not f.pid:
            return
        if not confirm(self, "Terminar processo", f"Terminar o processo PID {f.pid}?\n\n{f.title}"):
            return
        ok, msg = av.kill_process(f.pid)
        notify(msg, "ok" if ok else "bad")
        if ok:
            f.pid = 0
            self._selected()

    def _open(self):
        f = self._current()
        if f and f.path:
            open_path(os.path.dirname(f.path) if os.path.isfile(f.path) else f.path)

    def _ignore(self):
        f = self._current()
        if not f:
            return
        av.ignore(f)
        self._remove_row(f)
        notify("Ignorado — não volta a aparecer nas próximas análises.", "info")

    def _unignore(self):
        n = av.clear_ignored()
        notify(f"{n} resultado(s) ignorado(s) voltam a aparecer na próxima análise." if n
               else "Não há resultados ignorados.", "info")

    def _defender_remove(self):
        if not confirm(self, "Remover ameaças", "Pedir ao Microsoft Defender para remover todas as ameaças ativas?"):
            return
        self.btn_def.setEnabled(False)

        def done(r):
            ok, msg = r
            self.btn_def.setEnabled(True)
            notify(msg, "ok" if ok else "bad")
            if ok and self.report:
                for f in [x for x in self.report.findings if x.engine == "defender" and x.level == av.BAD]:
                    f.level = av.INFO
                    f.detail = "Removida pelo Defender.\n" + f.detail
                self._fill(self.report.findings)
        run_async(av.defender_remove, on_done=done)

    # ================================================================== quarentena
    def _load_quarantine(self):
        items = list(reversed(av.quarantine_list()))
        self.qtable.setRowCount(len(items))
        for i, it in enumerate(items):
            n = QTableWidgetItem(it["name"])
            n.setData(Qt.UserRole, it["id"])
            self.qtable.setItem(i, 0, n)
            o = QTableWidgetItem(it["original"])
            o.setToolTip(it["original"])
            self.qtable.setItem(i, 1, o)
            self.qtable.setItem(i, 2, QTableWidgetItem(human_bytes(it.get("size", 0))))
            self.qtable.setItem(i, 3, QTableWidgetItem(time.strftime("%d/%m/%Y %H:%M", time.localtime(it["when"]))))
            r = QTableWidgetItem(it.get("reason", ""))
            r.setToolTip(it.get("reason", ""))
            self.qtable.setItem(i, 4, r)

    def _q_selected(self) -> str | None:
        rows = self.qtable.selectionModel().selectedRows()
        if not rows:
            notify("Selecione um ficheiro da quarentena.", "warn")
            return None
        return self.qtable.item(rows[0].row(), 0).data(Qt.UserRole)

    def _q_restore(self):
        qid = self._q_selected()
        if not qid or not confirm(self, "Restaurar", "Restaurar este ficheiro para o local original?\n\n"
                                                     "Faça-o só se tiver a certeza de que é um falso alarme."):
            return
        ok, msg = av.quarantine_restore(qid)
        notify(msg, "ok" if ok else "bad")
        self._load_quarantine()

    def _q_delete(self):
        qid = self._q_selected()
        if not qid or not confirm(self, "Apagar", "Apagar definitivamente este ficheiro? Não pode ser desfeito."):
            return
        ok, msg = av.quarantine_delete(qid)
        notify(msg, "ok" if ok else "bad")
        self._load_quarantine()
