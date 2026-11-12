"""Modo jogo: deteção do jogo a correr, overlay por cima do jogo e biblioteca de jogos instalados."""
from __future__ import annotations

import os
import shutil
import time

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QGridLayout, QHBoxLayout, QHeaderView, QLineEdit,
                               QListWidget, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QWidget)

from ...core import fps as fpsmod
from ...core import games
from ...core import processes as pr
from ...core.util import IS_WIN, get_setting, human_bytes, open_path, set_setting
from ..overlay import ITEMS, POSITIONS
from ..widgets import Card, Page, SettingRow, Tip, Toggle, hbox, label, notify, run_async, separator


class GameModePage(Page):
    def __init__(self):
        super().__init__("Modo jogo", "Deteta quando está a jogar e mostra temperaturas e uso por cima do jogo")

        # ---------------------------------------------------------------- agora
        now = Card("Agora", icon="gamepad")
        self.now_big = label("", "Big", wrap=True)
        self.now_sub = label("", "Muted", wrap=True)
        self.btn_ov = QPushButton("Mostrar overlay agora")
        self.btn_ov.setObjectName("Primary")
        self.btn_ov.setCheckable(True)
        self.btn_ov.clicked.connect(self._toggle_overlay)
        now.add(self.now_big)
        now.add(hbox(self.now_sub, None, self.btn_ov))
        self.add(now)

        # ---------------------------------------------------------------- overlay
        ov = Card("Overlay", "Pequena caixa por cima do jogo — não apanha cliques nem rouba o foco.", icon="gauge")
        ov.add(SettingRow("Mostrar automaticamente ao jogar", "Aparece quando um jogo arranca e some quando fecha.",
                          self._toggle("overlay_auto")))
        ov.add(separator())
        self.pos = QComboBox()
        for k, v in POSITIONS.items():
            self.pos.addItem(v, k)
        self.pos.setCurrentIndex(max(0, self.pos.findData(get_setting("overlay_pos"))))
        self.pos.currentIndexChanged.connect(lambda _i: self._set("overlay_pos", self.pos.currentData()))
        self.size = QComboBox()
        self.size.addItem("Detalhado (uma linha por valor)", "detalhado")
        self.size.addItem("Compacto (tudo numa linha)", "compacto")
        self.size.setCurrentIndex(max(0, self.size.findData(get_setting("overlay_size"))))
        self.size.currentIndexChanged.connect(lambda _i: self._set("overlay_size", self.size.currentData()))
        box = QWidget()
        box.setObjectName("Transparent")
        box.setLayout(hbox(self.pos, self.size))
        ov.add(SettingRow("Posição e formato", "Canto do ecrã onde aparece.", box))
        ov.add(separator())
        op = QSlider(Qt.Horizontal)
        op.setRange(20, 100)
        op.setFixedWidth(220)
        op.setValue(int(get_setting("overlay_opacity")))
        op.valueChanged.connect(lambda v: self._set("overlay_opacity", int(v)))
        ov.add(SettingRow("Opacidade do fundo", "Mais transparente = vê-se mais o jogo por trás.", op))
        ov.add(separator())
        ov.add(label("<b>O que mostrar</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        chosen = set(get_setting("overlay_items") or [])
        self.item_cbs: dict[str, QCheckBox] = {}
        for i, (k, v) in enumerate(ITEMS.items()):
            cb = QCheckBox(v)
            cb.setChecked(k in chosen)
            cb.toggled.connect(lambda _c: self._items_changed())
            self.item_cbs[k] = cb
            grid.addWidget(cb, i // 4, i % 4)
        ov.add(grid)
        tip = ("Se o overlay não aparecer, ponha o jogo em <b>ecrã inteiro sem bordas</b> (borderless/janela). "
               "O ecrã inteiro exclusivo desenha por cima de todas as janelas.")
        ov.add(Tip(tip, "info"))
        self.add(ov)

        # ---------------------------------------------------------------- FPS
        fc = Card("Contador de FPS", "Quantos fotogramas por segundo o jogo está a desenhar — aparece no overlay.",
                  icon="zap")
        self.fps_state = label("", wrap=True)
        fc.add(self.fps_state)
        self.fps_help = label("", "Muted", wrap=True)
        self.fps_help.setTextFormat(Qt.RichText)
        fc.add(self.fps_help)
        self.fps_btns = QHBoxLayout()
        self.fps_btns.setSpacing(10)
        fc.add(self.fps_btns)
        self.b_copy = QPushButton("Copiar opção de arranque")
        self.b_copy.setObjectName("Primary")
        self.b_copy.clicked.connect(self._copy_launch)
        self.b_pm = QPushButton("Transferir PresentMon (1 MB)")
        self.b_pm.setObjectName("Primary")
        self.b_pm.clicked.connect(self._get_presentmon)
        self.b_perm = QPushButton("Dar permissão (pede administrador)")
        self.b_perm.clicked.connect(self._grant_perm)
        for b in (self.b_copy, self.b_pm, self.b_perm):
            self.fps_btns.addWidget(b)
        self.fps_btns.addStretch(1)
        self.add(fc)
        self._fps_help_fill()

        # ---------------------------------------------------------------- deteção
        det = Card("Deteção de jogos", "Steam/Proton, Wine, Lutris, Heroic, Epic, GOG, Xbox e pastas de jogos.",
                   icon="search")
        det.add(SettingRow("Detetar jogos automaticamente", "Verifica a cada 4 segundos (gasta quase nada).",
                           self._toggle("game_detect")))
        det.add(separator())
        det.add(SettingRow("Avisar ao começar e acabar", "No fim mostra a duração e as temperaturas máximas.",
                           self._toggle("game_notify")))
        det.add(separator())
        det.add(label("<b>Jogos que não são detetados</b> — marque o programa enquanto ele está aberto:"))
        self.run_cb = QComboBox()
        self.run_cb.setMinimumWidth(260)
        b_rf = QPushButton("Atualizar lista")
        b_rf.clicked.connect(self._fill_running)
        b_add = QPushButton("Marcar como jogo")
        b_add.clicked.connect(self._add_extra)
        det.add(hbox(self.run_cb, b_rf, b_add, None))
        self.extra = QListWidget()
        self.extra.setFixedHeight(90)
        b_rm = QPushButton("Remover")
        b_rm.setObjectName("Ghost")
        b_rm.clicked.connect(self._rm_extra)
        det.add(self.extra)
        det.add(hbox(None, b_rm))
        self.add(det)

        # ---------------------------------------------------------------- perfis por jogo
        from ..gameprofile_card import GameProfileCard
        self.gp_card = GameProfileCard()
        self.add(self.gp_card)

        # ---------------------------------------------------------------- sessões
        ses = Card("Sessões de jogo", "Tempo jogado, FPS e temperaturas de cada sessão — guardado automaticamente "
                   "quando o jogo fecha.", icon="chart")
        self.ses_period = QComboBox()
        for txt, days in (("Últimos 7 dias", 7), ("Últimos 30 dias", 30), ("Desde sempre", 0)):
            self.ses_period.addItem(txt, days)
        self.ses_period.setCurrentIndex(1)
        self.ses_period.currentIndexChanged.connect(lambda _i: self._load_sessions())
        b_clear = QPushButton("Apagar histórico")
        b_clear.clicked.connect(self._clear_sessions)
        ses.head.addWidget(self.ses_period)
        ses.head.addWidget(b_clear)
        self.ses_info = label("", "Muted", wrap=True)
        ses.add(self.ses_info)
        self.ses_sum = self._mk_table(["Jogo", "Sessões", "Tempo", "FPS médio", "CPU máx.", "GPU máx."], 180)
        ses.add(self.ses_sum)
        ses.add(label("Últimas sessões", "Section"))
        self.ses_list = self._mk_table(["Jogo", "Quando", "Duração", "FPS médio", "1 % low", "Mín.", "CPU máx.",
                                        "GPU máx."], 220)
        self.ses_list.setToolTip("«1 % low»: o FPS abaixo do qual o jogo esteve 1 % do tempo — mostra as quebras "
                                 "(engasgos) melhor do que a média. Calculado com uma amostra por segundo.")
        ses.add(self.ses_list)
        self.add(ses)

        # ---------------------------------------------------------------- biblioteca
        lib = Card("Jogos instalados", icon="package")
        self.lib_search = QLineEdit()
        self.lib_search.setPlaceholderText("Procurar jogo…")
        self.lib_search.setFixedWidth(220)
        self.lib_search.textChanged.connect(self._filter_lib)
        b_lib = QPushButton("Atualizar")
        b_lib.clicked.connect(self._load_lib)
        lib.head.addWidget(self.lib_search)
        lib.head.addWidget(b_lib)
        self.lib_info = label("A procurar…", "Muted")
        lib.add(self.lib_info)
        t = QTableWidget(0, 4)
        t.setHorizontalHeaderLabels(["Jogo", "Loja", "Tamanho", ""])
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c, w in ((1, 150), (2, 100), (3, 200)):
            hh.setSectionResizeMode(c, QHeaderView.Fixed)
            t.setColumnWidth(c, w)
        t.verticalHeader().setVisible(False)
        t.verticalHeader().setDefaultSectionSize(44)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.setMinimumHeight(260)
        self.lib = t
        lib.add(t, 1)
        self.add(lib, 1)

        self._games: list = []
        self._lib_loaded = False
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._refresh_now)
        self._load_extra()

    # ------------------------------------------------------------------ sessões
    @staticmethod
    def _mk_table(headers, min_h):
        t = QTableWidget(0, len(headers))
        t.setHorizontalHeaderLabels(headers)
        hh = t.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(headers)):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        t.verticalHeader().setVisible(False)
        t.setEditTriggers(QTableWidget.NoEditTriggers)
        t.setSelectionMode(QTableWidget.NoSelection)
        t.setFocusPolicy(Qt.NoFocus)
        t.setAlternatingRowColors(True)
        t.setShowGrid(False)
        t.setMinimumHeight(min_h)
        return t

    def _load_sessions(self):
        days = self.ses_period.currentData() or None

        def work():
            from ...core import sessions
            since = time.time() - days * 86400 if days else 0
            return sessions.summary(days), [x for x in sessions.recent(200) if x.start >= since]
        run_async(work, on_done=self._got_sessions, on_fail=lambda _m: None)

    @staticmethod
    def _dur(minutes: float) -> str:
        h, m = divmod(int(round(minutes)), 60)
        return f"{h} h {m:02d} min" if h else f"{m} min"

    def _got_sessions(self, res):
        summ, recent = res
        total = sum(g.minutes for g in summ)
        self.ses_info.setText(
            f"{len(summ)} jogos · {sum(g.sessions for g in summ)} sessões · {self._dur(total)} a jogar"
            if summ else "Ainda não há sessões neste período. Jogue um pouco — cada sessão com mais de 1 minuto "
            "fica registada aqui (o FPS precisa do contador de FPS ativo).")

        def cell(t, r, c, txt, right=True):
            it = QTableWidgetItem(txt)
            if right:
                it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(r, c, it)
        fmt = lambda v, u="": "—" if v is None else f"{v:.0f}{u}"  # noqa: E731
        self.ses_sum.setRowCount(len(summ))
        for i, g in enumerate(summ):
            cell(self.ses_sum, i, 0, g.game, False)
            cell(self.ses_sum, i, 1, str(g.sessions))
            cell(self.ses_sum, i, 2, self._dur(g.minutes))
            cell(self.ses_sum, i, 3, fmt(g.fps_avg))
            cell(self.ses_sum, i, 4, fmt(g.cpu_max, " °C"))
            cell(self.ses_sum, i, 5, fmt(g.gpu_max, " °C"))
        self.ses_list.setRowCount(len(recent))
        for i, x in enumerate(recent):
            cell(self.ses_list, i, 0, x.game, False)
            cell(self.ses_list, i, 1, time.strftime("%d/%m %H:%M", time.localtime(x.start)))
            cell(self.ses_list, i, 2, self._dur(x.minutes))
            cell(self.ses_list, i, 3, fmt(x.fps_avg))
            cell(self.ses_list, i, 4, fmt(x.fps_low1))
            cell(self.ses_list, i, 5, fmt(x.fps_min))
            cell(self.ses_list, i, 6, fmt(x.cpu_max, " °C"))
            cell(self.ses_list, i, 7, fmt(x.gpu_max, " °C"))

    def _clear_sessions(self):
        from ..widgets import confirm
        if not confirm(self, "Apagar histórico", "Apagar o histórico de todas as sessões de jogo?"):
            return
        from ...core import sessions
        sessions.clear()
        self._load_sessions()
        notify("Histórico das sessões apagado.", "ok")

    # ------------------------------------------------------------------
    def _win(self):
        return self.window() if hasattr(self.window(), "overlay") else None

    def on_show(self):
        self._refresh_now()
        self._load_sessions()
        w = self._win()
        self.gp_card.refresh(w.game.name if w is not None and w.game is not None else None)
        self.timer.start(1000)
        if not self._lib_loaded:
            self._lib_loaded = True
            self._load_lib()
            self._fill_running()

    def on_hide(self):
        self.timer.stop()

    def _refresh_now(self):
        w = self._win()
        if w is None:
            return
        g = w.game
        self.btn_ov.blockSignals(True)
        self.btn_ov.setChecked(w.overlay_manual)
        self.btn_ov.setText("Esconder overlay" if w.overlay_manual else "Mostrar overlay agora")
        self.btn_ov.blockSignals(False)
        self._fps_state(w, g)
        if g is None:
            self.now_big.setText("Nenhum jogo a correr")
            self.now_sub.setText("Abra um jogo e o Nexo deteta-o sozinho"
                                 + (" e mostra o overlay." if get_setting("overlay_auto") else "."))
            return
        mins = int((time.time() - (g.started or time.time())) / 60)
        st = w.game_stats
        extra = []
        if st.get("cpu_max") is not None:
            extra.append(f"CPU máx. {st['cpu_max']:.0f} °C")
        if st.get("gpu_max") is not None:
            extra.append(f"GPU máx. {st['gpu_max']:.0f} °C")
        self.now_big.setText(f"🎮 {g.name}")
        dur = "acabou de começar" if mins < 1 else f"a jogar há {mins} min" if mins < 60 else \
            f"a jogar há {mins // 60}h{mins % 60:02d}"
        self.now_sub.setText(f"{dur[0].upper()}{dur[1:]} · via {g.source}"
                             + (" · " + " · ".join(extra) if extra else ""))

    # ---- FPS
    def _fps_help_fill(self):
        self.b_copy.setVisible(not IS_WIN)
        self.b_pm.setVisible(IS_WIN and not fpsmod.presentmon_installed())
        self.b_perm.setVisible(False)
        if IS_WIN:
            self.fps_help.setText(
                "Se o <b>RivaTuner/MSI Afterburner</b> estiver aberto, o Nexo lê os FPS dele. Senão usa o "
                "<b>PresentMon</b> (Intel, gratuito): lê os eventos de imagem do próprio Windows, não toca no jogo "
                "e é seguro com anti-batota."
                + ("" if fpsmod.presentmon_installed() else " Transfira-o uma vez com o botão abaixo."))
            return
        if not shutil.which("mangohud"):
            cmd = next((f"sudo {c} {t} mangohud" for c, t in (("pacman", "-S"), ("apt", "install"),
                                                               ("dnf", "install"), ("zypper", "install"))
                        if shutil.which(c)), "")
            self.fps_help.setText("No Linux os FPS vêm do <b>MangoHud</b>, que não está instalado. "
                                  + (f"Instale-o (<code>{cmd}</code>) e volte aqui." if cmd else
                                     "Instale o pacote <code>mangohud</code> e volte aqui."))
            self.b_copy.setVisible(False)
            return
        self.fps_help.setText(
            "Os FPS vêm do <b>MangoHud</b> (já instalado). Na <b>Steam</b>: botão direito no jogo → Propriedades → "
            "<b>Opções de arranque</b> → cole a opção copiada pelo botão abaixo. No <b>Lutris/Heroic</b>: ative o "
            "MangoHud no jogo e acrescente a variável de ambiente <code>MANGOHUD_CONFIG</code> com o valor "
            f"<code>{fpsmod.mangohud_env()}</code>.<br>A caixa do próprio MangoHud fica escondida — os FPS "
            "aparecem no overlay do Nexo. Funciona em jogos nativos e Proton.")

    def _fps_state(self, w, g):
        f = getattr(w.overlay, "last_fps", None)
        if f:
            self.fps_state.setText(f"<b>{f['fps']:.0f} FPS</b> · {f['ft']:.1f} ms por fotograma · via {f['src']}")
            return
        err = w.overlay.fps.error() if hasattr(w.overlay, "fps") else ""
        self.b_perm.setVisible(IS_WIN and err == "sem-permissao")
        if err == "sem-permissao":
            self.fps_state.setText("⚠️ O PresentMon precisa de permissão para ler os eventos do Windows: abra o Nexo "
                                   "como administrador ou use o botão abaixo (depois termine sessão e volte a entrar).")
        elif err:
            self.fps_state.setText(f"⚠️ PresentMon: {err}")
        elif g is None:
            self.fps_state.setText("Sem jogo a correr.")
        elif IS_WIN and not fpsmod.presentmon_installed():
            self.fps_state.setText("Ainda não há FPS: abra o RivaTuner ou transfira o PresentMon.")
        elif not IS_WIN:
            self.fps_state.setText("Ainda não há FPS deste jogo — foi lançado com a opção do MangoHud?")
        else:
            self.fps_state.setText("À espera dos primeiros fotogramas…")

    def _copy_launch(self):
        QApplication.clipboard().setText(fpsmod.steam_launch_option())
        notify("Opção copiada — cole-a nas Opções de arranque do jogo na Steam.", "ok")

    def _get_presentmon(self):
        from ..netmonitor import require_online
        if not require_online("Transferir o PresentMon"):
            return
        self.b_pm.setEnabled(False)
        self.b_pm.setText("A transferir…")

        def done(_p):
            self.b_pm.setEnabled(True)
            self.b_pm.setText("Transferir PresentMon (1 MB)")
            self._fps_help_fill()
            w = self._win()
            if w is not None and w.game is not None:
                w.overlay.fps.pm.start()
            notify("PresentMon instalado — os FPS aparecem no próximo jogo (ou já, se houver um aberto).", "ok")

        def fail(m):
            self.b_pm.setEnabled(True)
            self.b_pm.setText("Transferir PresentMon (1 MB)")
            from ...core.network import friendly_error
            notify(f"Não consegui transferir o PresentMon: {friendly_error(m)}", "bad")
        run_async(fpsmod.install_presentmon, on_done=done, on_fail=fail)

    def _grant_perm(self):
        if fpsmod.grant_perf_log_permission():
            notify("Permissão pedida. Termine sessão no Windows e volte a entrar para ter efeito.", "info")

    def _toggle_overlay(self, on):
        w = self._win()
        if w is not None:
            w.set_overlay_manual(bool(on))
        self._refresh_now()

    def _toggle(self, key) -> Toggle:
        tg = Toggle(bool(get_setting(key)))
        tg.clicked.connect(lambda checked, k=key: self._set(k, bool(checked)))
        return tg

    def _set(self, key, value):
        set_setting(key, value)
        w = self._win()
        if w is None:
            return
        if key.startswith("overlay_"):
            w.overlay.send_cfg()
        if key == "overlay_auto" and w.game is not None:
            (w.overlay.show(w.game.name, w.game.started) if value else
             (None if w.overlay_manual else w.overlay.hide()))
        if key == "game_detect" and not value and w.game is not None:
            w._game_misses = 5   # termina já a sessão em curso
            w._game_changed(None)

    def _items_changed(self):
        self._set("overlay_items", [k for k, cb in self.item_cbs.items() if cb.isChecked()])

    # ---- processos extra
    def _load_extra(self):
        self.extra.clear()
        names = get_setting("game_processes") or []
        self.extra.addItems(names)
        self.extra.setVisible(bool(names))

    def _fill_running(self):
        def done(rows):
            apps, _h = pr.group_apps(rows)
            self.run_cb.clear()
            for a in sorted(apps, key=lambda a: -a["rss"]):
                exe = os.path.basename(a["exe"]) if a["exe"] else a["key"]
                self.run_cb.addItem(f"{a['name']}  ({exe})", exe)
        run_async(pr.snapshot, True, on_done=done)

    def _add_extra(self):
        exe = self.run_cb.currentData()
        if not exe:
            return
        names = list(get_setting("game_processes") or [])
        if exe.lower() not in [n.lower() for n in names]:
            names.append(exe)
            set_setting("game_processes", names)
        self._load_extra()
        notify(f"{exe} passa a contar como jogo.", "ok")

    def _rm_extra(self):
        it = self.extra.currentItem()
        if not it:
            return
        names = [n for n in (get_setting("game_processes") or []) if n != it.text()]
        set_setting("game_processes", names)
        self._load_extra()

    # ---- biblioteca
    def _load_lib(self):
        self.lib_info.setText("A procurar jogos instalados…")
        run_async(games.installed_games, on_done=self._got_lib)

    def _got_lib(self, gl):
        self._games = gl
        total = sum(g.size for g in gl)
        stores = sorted({g.store for g in gl})
        self.lib_info.setText(f"{len(gl)} jogos · {human_bytes(total)}" + (f" · {', '.join(stores)}" if stores else "")
                              if gl else "Não encontrei jogos instalados (Steam, Epic, GOG, Heroic, Lutris).")
        t = self.lib
        t.setRowCount(len(gl))
        for i, g in enumerate(gl):
            it = QTableWidgetItem(g.name)
            f = it.font()
            f.setBold(True)
            it.setFont(f)
            it.setToolTip(g.path)
            t.setItem(i, 0, it)
            t.setItem(i, 1, QTableWidgetItem(g.store))
            s = QTableWidgetItem(human_bytes(g.size) if g.size else "—")
            s.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            t.setItem(i, 2, s)
            holder = QWidget()
            holder.setObjectName("Transparent")
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(8, 5, 8, 5)
            hl.setSpacing(6)
            bp = QPushButton("Jogar")
            bp.setObjectName("Primary")
            bp.setEnabled(bool(g.launch))
            bp.clicked.connect(lambda _c=False, gg=g: self._play(gg))
            bf = QPushButton("Pasta")
            bf.setEnabled(bool(g.path) and os.path.isdir(g.path))
            bf.clicked.connect(lambda _c=False, gg=g: open_path(gg.path))
            hl.addWidget(bp)
            hl.addWidget(bf)
            t.setCellWidget(i, 3, holder)
        self._filter_lib(self.lib_search.text())

    def _filter_lib(self, q):
        q = (q or "").strip().lower()
        for i, g in enumerate(self._games):
            self.lib.setRowHidden(i, bool(q) and q not in g.name.lower() and q not in g.store.lower())

    def _play(self, g):
        if g.launch.startswith("lutris:") and shutil.which("lutris"):
            import subprocess
            subprocess.Popen(["lutris", g.launch], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            QDesktopServices.openUrl(QUrl(g.launch))
        notify(f"A abrir {g.name}…", "info")

