"""Cartão "Perfis por jogo" (página Modo jogo): energia, overlay, programas a fechar e GameMode."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QListWidget, QListWidgetItem, QPushButton

from ..core import gameprofile as gp
from ..core.util import IS_LINUX
from .widgets import Card, SettingRow, Toggle, hbox, label, notify, run_async, separator


class GameProfileCard(Card):
    def __init__(self):
        super().__init__("Perfis por jogo", "O que muda quando um jogo arranca — e volta ao normal quando fecha. "
                         "Cada jogo pode ter o seu.", icon="gamepad")
        self.game_cb = QComboBox()
        self.game_cb.setEditable(True)
        self.game_cb.setMinimumWidth(260)
        self.game_cb.setAccessibleName("Jogo a configurar")
        self.game_cb.lineEdit().setPlaceholderText("Escreva ou escolha um jogo…")
        self.game_cb.currentTextChanged.connect(self._game_selected)
        self.b_now = QPushButton("Jogo atual")
        self.b_now.setToolTip("Escolher o jogo que está a correr agora")
        self.b_now.clicked.connect(self._use_current)
        self.add(hbox(label("<b>Jogo</b>"), self.game_cb, self.b_now, None))
        self.add(separator())

        self.power_cb = QComboBox()
        for k, v in gp.POWER_CHOICES.items():
            self.power_cb.addItem(v, k)
        self.power_cb.currentIndexChanged.connect(lambda _i: self._save("power", self.power_cb.currentData()))
        self.power_cb.setEnabled(gp.power_available())
        self.add(SettingRow("Energia", "Perfil de energia durante o jogo; o anterior volta no fim." + (
            "" if gp.power_available() else " (Indisponível: instale o power-profiles-daemon.)"), self.power_cb))

        self.ov_cb = QComboBox()
        for k, v in gp.OVERLAY_CHOICES.items():
            self.ov_cb.addItem(v, k)
        self.ov_cb.currentIndexChanged.connect(lambda _i: self._save("overlay", self.ov_cb.currentData()))
        self.add(SettingRow("Overlay", "Sobrepõe-se à opção geral só para este jogo.", self.ov_cb))

        if IS_LINUX:
            self.gm = Toggle(False)
            self.gm.clicked.connect(lambda on: self._save("gamemode", bool(on)))
            ok = gp.gamemode_available()
            self.gm.setEnabled(ok)
            self.add(SettingRow("Feral GameMode", "Pede ao gamemoded prioridade de CPU e o governador de desempenho "
                                "para o jogo." + ("" if ok else " Instale o pacote «gamemode» para ativar."), self.gm))
        else:
            self.gm = None

        self.add(separator())
        self.add(label("<b>Fechar ao começar o jogo</b> — marque os programas (pedido normal de fecho; nada é "
                       "fechado à força e o lançador do jogo nunca é tocado):", wrap=True))
        self.close_list = QListWidget()
        self.close_list.setFixedHeight(150)
        self.close_list.setAccessibleName("Programas a fechar quando o jogo arranca")
        self.close_list.itemChanged.connect(lambda _it: self._save_close())
        self.add(self.close_list)
        b_rf = QPushButton("Atualizar lista")
        b_rf.setObjectName("Ghost")
        b_rf.clicked.connect(self._load_running)
        self.b_reset = QPushButton("Apagar perfil deste jogo")
        self.b_reset.setObjectName("Ghost")
        self.b_reset.clicked.connect(self._reset)
        self.add(hbox(b_rf, None, self.b_reset))

        self._running: list[str] = []
        self._loading = False
        self._set_enabled(False)

    # ------------------------------------------------------------------
    def refresh(self, current_game: str | None):
        """Chamado pela página ao abrir."""
        self._current = current_game
        self.b_now.setEnabled(bool(current_game))
        text = self.game_cb.currentText()
        self.game_cb.blockSignals(True)
        self.game_cb.clear()
        names = gp.known_games()
        if current_game and current_game not in names:
            names.insert(0, current_game)
        self.game_cb.addItems(names)
        self.game_cb.setEditText(text or current_game or "")
        self.game_cb.blockSignals(False)
        self._game_selected(self.game_cb.currentText())
        if not self._running:
            self._load_running()

    def _game(self) -> str:
        return self.game_cb.currentText().strip()

    def _set_enabled(self, on: bool):
        for w in (self.ov_cb, self.close_list, self.b_reset):
            w.setEnabled(on)
        self.power_cb.setEnabled(on and gp.power_available())
        if self.gm is not None:
            self.gm.setEnabled(on and gp.gamemode_available())

    def _use_current(self):
        if getattr(self, "_current", None):
            self.game_cb.setEditText(self._current)

    def _game_selected(self, _t=None):
        game = self._game()
        self._set_enabled(bool(game))
        self._loading = True
        prof = gp.get(game)
        self.power_cb.setCurrentIndex(max(0, self.power_cb.findData(prof["power"])))
        self.ov_cb.setCurrentIndex(max(0, self.ov_cb.findData(prof["overlay"])))
        if self.gm is not None:
            self.gm.setChecked(bool(prof["gamemode"]))
        self._fill_close(prof["close"])
        self._loading = False

    def _fill_close(self, chosen: list[str]):
        self.close_list.blockSignals(True)
        self.close_list.clear()
        seen = set()
        for name in list(chosen) + self._running:
            low = name.lower()
            if low in seen or not gp.can_close(name):
                continue
            seen.add(low)
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if name in chosen else Qt.Unchecked)
            self.close_list.addItem(it)
        if not seen:
            it = QListWidgetItem("A carregar os programas abertos…" if not self._running else "Nenhum programa.")
            it.setFlags(Qt.NoItemFlags)
            self.close_list.addItem(it)
        self.close_list.blockSignals(False)

    def _load_running(self):
        from ..core import memory

        def done(rows):
            self._running = [r["name"] for r in rows]
            self._fill_close(gp.get(self._game())["close"] if self._game() else [])
        run_async(memory.background_processes, 60, on_done=done, on_fail=lambda _m: None)

    # ------------------------------------------------------------------ gravar
    def _save(self, key, value):
        game = self._game()
        if self._loading or not game:
            return
        gp.set_value(game, key, value)
        self._applied_now(game)

    def _save_close(self):
        if self._loading:
            return
        names = [self.close_list.item(i).text() for i in range(self.close_list.count())
                 if self.close_list.item(i).checkState() == Qt.Checked]
        self._save("close", names)

    def _reset(self):
        game = self._game()
        if not game:
            return
        for k, v in gp.DEFAULT.items():
            gp.set_value(game, k, v)
        self._game_selected()
        notify(f"Perfil de «{game}» apagado — usa as definições gerais.", "ok")

    def _applied_now(self, game: str):
        if game == getattr(self, "_current", None):
            notify("Guardado. Aplica-se na próxima vez que o jogo arrancar.", "info")
