"""Tarefas agendadas: o que o Nexo faz sozinho, de quanto em quanto tempo e quando volta a fazer."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QPushButton

from ...core import schedule
from ...core.i18n import tr
from ...core.util import get_setting, human_bytes
from ..widgets import Card, Page, SettingRow, Tip, hbox, label, notify, run_async, separator, status_dot


def _fmt(ts: float, now: float) -> str:
    from datetime import date
    days = (date.fromtimestamp(ts) - date.fromtimestamp(now)).days
    hm = time.strftime("%H:%M", time.localtime(ts))
    if days in (-1, 0, 1):
        return tr(f"{ {-1: 'ontem', 0: 'hoje', 1: 'amanhã'}[days]} às {hm}")
    return time.strftime("%d/%m/%Y %H:%M", time.localtime(ts))


class TasksPage(Page):
    def __init__(self):
        super().__init__("Tarefas agendadas", "O que o Nexo faz sozinho em segundo plano — só enquanto está aberto "
                         "(ou na bandeja) e nunca durante um jogo.")
        self.rows: dict[str, tuple] = {}
        for t in schedule.tasks():
            c = Card(t.name, t.desc, icon=t.icon)
            cb = QComboBox()
            for days, txt in schedule.INTERVALS.items():
                cb.addItem(txt, days)
            cb.setCurrentIndex(max(0, cb.findData(schedule.interval(t))))
            cb.setAccessibleName(f"Frequência: {t.name}")
            cb.currentIndexChanged.connect(lambda _i, t=t, cb=cb: self._changed(t, cb))
            run_now = QPushButton("Lembrar agora" if t.reminder else "Executar agora")
            run_now.clicked.connect(lambda _c=False, t=t: self._run_now(t))
            go = QPushButton(f"Abrir {t.page}")
            go.setObjectName("Ghost")
            go.clicked.connect(lambda _c=False, p=t.page: self.window().go_name(p))
            c.add(SettingRow("Frequência", "Desligada = nunca corre sozinha.", cb))
            c.add(separator())
            info = label("", "Muted", wrap=True)
            info.setTextFormat(Qt.RichText)
            row = hbox(go, run_now)
            row.insertWidget(0, info, 1)
            c.add(row)
            self.rows[t.id] = (cb, info, run_now)
            self.add(c)
        self.add(Tip("As atualizações do sistema são procuradas a cada 6 horas e as do Nexo uma vez por dia "
                     "(Definições). Os avisos de temperatura, memória e espaço em disco são contínuos "
                     "(Definições → Alertas)."))
        self.body.addStretch(1)
        self._busy: set[str] = set()

    def on_show(self):
        now = time.time()
        schedule.start_counting(now)
        for t in schedule.tasks():
            cb, info, btn = self.rows[t.id]
            cb.blockSignals(True)
            cb.setCurrentIndex(max(0, cb.findData(schedule.interval(t))))
            cb.blockSignals(False)
            lines = []
            nxt = schedule.next_run(t, now)
            if t.id in self._busy:
                lines.append(f"{status_dot('info')} <b>{tr('A correr…')}</b>")
            elif nxt is None:
                lines.append(f"{status_dot('muted')} {tr('Desligada.')}")
            else:
                when = tr("em breve") if nxt <= now else _fmt(nxt, now)
                lines.append(f"{status_dot('ok')} {tr(f'Próxima: <b>{when}</b>')}")
            r = schedule.result(t)
            if r.get("when"):
                lines.append(tr(f"Última: {_fmt(r['when'], now)} — {r.get('msg', '')}"))
            elif schedule.last_run(t) and t.id == "clean" and get_setting("auto_clean_freed"):
                lines.append(tr(f"Total libertado: {human_bytes(int(get_setting('auto_clean_freed')))}"))
            info.setText("<br>".join(lines))
            btn.setEnabled(t.id not in self._busy)

    def _changed(self, t, cb):
        schedule.set_interval(t, int(cb.currentData() or 0))
        self.on_show()

    def _run_now(self, t):
        if t.id in self._busy:
            return
        self._busy.add(t.id)
        self.on_show()

        def done(res):
            self._busy.discard(t.id)
            msg, kind = res
            win = self.window()
            if msg and hasattr(win, "_alert"):
                win._alert(msg, kind or "info", t.page)
            elif not msg:
                notify(schedule.result(t).get("msg") or "Concluído.", "ok")
            self.on_show()

        def fail(m):
            self._busy.discard(t.id)
            schedule.record(t, False, f"Falhou: {m}")
            notify(f"{t.name}: {m}", "bad")
            self.on_show()
        run_async(schedule.run_task, t, on_done=done, on_fail=fail)
