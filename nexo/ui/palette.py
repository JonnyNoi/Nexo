"""Pesquisa rápida (Ctrl+K): encontra páginas, funções, opções e temas e leva diretamente até lá.

O índice junta duas fontes:
- palavras-chave escritas à mão para cada página (funciona mesmo com páginas que ainda não foram abertas);
- os elementos reais das páginas já criadas (títulos de cartões, opções, botões e separadores).
Ao escolher um resultado, a página abre, o elemento fica à vista e pisca com a cor do tema.
"""
from __future__ import annotations

import unicodedata

from PySide6.QtCore import QEasingCurve, QEvent, QPoint, QPropertyAnimation, QSize, Qt, QTimer
from PySide6.QtWidgets import (QAbstractButton, QCheckBox, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                               QLineEdit, QListWidget, QListWidgetItem, QPushButton, QScrollArea, QStackedWidget,
                               QTabWidget, QVBoxLayout, QWidget)

from . import theme
from .icons import icon as make_icon
from .widgets import SettingRow, icon_badge, label

# página → [(função, palavras-chave extra)]; a função é procurada na página para a destacar
FEATURES: dict[str, list[tuple[str, str]]] = {
    "Visão geral": [("Saúde do PC", "pontuação nota estado geral o que fazer recomendações"),
                    ("CPU × GPU", "gráfico temperatura carga consumo watts"),
                    ("Saúde do sistema", "resolver problemas avisos serviços com falha swap tempo ligado"),
                    ("Porque está lento?", "lento lentidão pesado devagar trava diagnóstico encravado"),
                    ("Utilização", "ram vram disco rede anéis")],
    "Informação": [("Exportar relatório", "html json guardar especificações specs hardware"),
                   ("Processador", "cpu caches instruções"), ("Memória", "ram módulos slots"),
                   ("Placa gráfica", "gpu vram pcie vbios opengl vulkan driver"),
                   ("Placa-mãe", "motherboard bios uefi secure boot"), ("Discos", "ssd nvme hdd"),
                   ("Rede", "ip mac wifi ethernet")],
    "Sensores": [("Simples", "resumo temperatura processador placa gráfica quente normal"),
                 ("Todos os sensores", "avançado lista completa mínimo máximo"),
                 ("Histórico", "gráfico ontem semana 24 horas 7 dias passado temperatura máxima"),
                 ("Gravar CSV", "registar log exportar leituras"),
                 ("Temperaturas", "temp graus ventoinhas rpm tensões voltagem clocks consumo hwmon")],
    "Processos": [("Simples", "aplicações abertas fechar app pesada memória gestor de tarefas"),
                  ("Todos os processos", "pid lista completa avançado"),
                  ("Terminar", "matar kill fechar programa gestor de tarefas task manager"),
                  ("Forçar fim", "kill -9 bloqueado não responde"), ("Prioridade", "nice")],
    "Fiabilidade": [("Desligou-se sem aviso", "crash reiniciou sozinho bloqueou congelou ecrã azul bsod kernel panic "
                                              "kernel-power 41 corte de luz"),
                    ("Erros de hardware", "whea mce memória ram instável overclock xmp"),
                    ("Controlador gráfico", "driver gpu ecrã preto reset amdgpu nvidia xid tdr"),
                    ("Programas que fecharam", "crash segfault coredump fechou sozinho"),
                    ("Throttling", "limitação temperatura clock baixou quente desempenho caiu")],
    "Antivírus": [("Análise rápida", "vírus malware procurar infeção trojan ameaças scan defender clamav"),
                  ("Análise completa", "sistema todo disco inteiro rootkit minerador"),
                  ("Quarentena", "isolar restaurar apagar ameaça"),
                  ("Atualizar assinaturas", "freshclam definições base de dados")],
    "Otimização": [("Programas em segundo plano", "ram memória libertar fechar apps pesadas background"),
                   ("Desempenho Máximo", "plano de energia hibernação tweaks ajustes"),
                   ("Menu de contexto clássico", "windows 11 botão direito"), ("Modo escuro", "dark"),
                   ("BBR", "tcp rede linux"), ("NMI watchdog", "linux kernel"), ("Restaurar", "reverter desfazer")],
    "Stress test": [("Configuração", "cpu ram memória carga máxima estabilidade erros temperatura limite"),
                    ("Registo", "log")],
    "Benchmark": [("Resultado", "pontuação nota multi single core path tracer desempenho cpu"),
                  ("Histórico", "comparar resultados anteriores")],
    "Internet": [("Iniciar teste", "teste de velocidade speedtest download upload mbps megas fibra"),
                 ("Latência", "ping jitter variação lag jogos bufferbloat"),
                 ("O que a sua ligação permite", "4k streaming chamadas jogos online qualidade"),
                 ("Ligação à internet", "rede wifi cabo offline sem internet router portal diagnóstico"),
                 ("Histórico", "testes anteriores")],
    "Instalar aplicações": [("Instalar", "programas apps winget flatpak flathub navegador jogos steam discord "
                                         "vlc obs spotify chrome firefox"),
                            ("Atualizar todas", "update upgrade"), ("Desinstalar", "remover")],
    "Utilitários": [("Reparar e manutenção", "sfc dism chkdsk reparar windows ponto de restauro repor rede "
                                             "atualizar o sistema pacman apt dnf órfãos trim firmware fwupd"),
                    ("DNS", "cloudflare google quad9 adguard teste de velocidade internet"),
                    ("Funcionalidades do Windows", "wsl hyper-v sandbox .net"),
                    ("Windows Update", "atualizações segurança drivers"),
                    ("Painéis clássicos", "painel de controlo")],
    "Tarefas agendadas": [("Limpeza automática", "agendar automático semanal mensal limpar caches temporários"),
                          ("Análise antivírus rápida", "agendada automática vírus semanal"),
                          ("Saúde dos discos (S.M.A.R.T.)", "lembrete agendado smart disco")],
    "Arranque": [("Arranque", "startup autostart iniciar com o sistema systemd programas ao ligar")],
    "Windows debloat": [("Apps pré-instaladas", "remover bloatware candy crush tiktok cortana copilot clipchamp"),
                        ("Telemetria", "privacidade publicidade recall bing widgets anúncios sugestões"),
                        ("Restaurar originais", "reverter")],
    "Saúde dos discos": [("Ler discos", "smart s.m.a.r.t. smartctl smartmontools ssd hdd nvme avaria falha "
                                        "estado do disco vida útil desgaste tbw horas setores realocados"),
                         ("Autoteste rápido", "self-test teste do disco verificar"),
                         ("Instalar smartmontools", "smartctl")],
    "Espaço em disco": [("Analisar pasta / disco", "espaço ocupado armazenamento"),
                        ("Pode ser apagado", "seguro apagar jogos caches instaladores isos transferências downloads system32 sistema"),
                        ("Maiores ficheiros", "grandes"), ("Maiores pastas", "node_modules steam"),
                        ("Duplicados", "repetidos iguais hash"), ("Por tipo", "extensões"),
                        ("Limpeza rápida", "lixo caches temporários limpar cleanup journal docker flatpak "
                                           "pacotes antigos navegadores shaders")],
    "Modo jogo": [("Overlay", "fps temperaturas por cima do jogo osd hud mangohud"),
                  ("Deteção de jogos", "steam proton wine lutris heroic epic gog detetar"),
                  ("Perfis por jogo", "perfil jogo energia desempenho fechar programas gamemode feral"),
                  ("Jogos instalados", "biblioteca jogar lançar")],
    "Atualizações": [("Atualizar tudo", "atualizar update upgrade pacman paru yay aur flatpak winget apt dnf pacotes "
                                         "versões novas checkupdates"),
                     ("Verificar automaticamente", "procurar atualizações a cada 6 horas contador")],
    "Fundo de ecrã": [("Fundo atual", "wallpaper papel de parede ambiente de trabalho imagem de fundo desktop"),
                      ("Os meus fundos", "galeria imagens guardadas"),
                      ("Procurar no Wallhaven", "anime wallpaper"), ("Troca automática", "aleatório trocar")],
    "Definições": [("Aparência", "tema escuro claro modo noturno"),
                   ("Alertas", "avisos sobreaquecimento limite temperatura ram memória disco cheio espaço smart"),
                   ("Proteção (pontos de restauro)", "snapshot snapper timeshift restauro voltar atrás backup"),
                   ("Histórico dos sensores", "apagar guardar gráfico"),
                   ("Janela e bandeja", "tray minimizado"),
                   ("Abrir registo de erros", "log nexo.log crash falha bug reportar problema"),
                   ("Copiar diagnóstico", "relatório reportar problema bug suporte github issue"),
                   ("Abrir com o sistema", "arranque automático")],
}


def norm(s: str) -> str:
    """Minúsculas e sem acentos ("Ação" → "acao"), para a pesquisa não depender de acentos."""
    s = unicodedata.normalize("NFKD", s.casefold())
    return "".join(ch for ch in s if not unicodedata.combining(ch))


def score(query_tokens: list[str], title: str, hay: str) -> int:
    """0 = não corresponde. Todas as palavras têm de aparecer; o título vale mais do que as palavras-chave."""
    if not query_tokens:
        return 1
    t = norm(title)
    s = 0
    for q in query_tokens:
        if t.startswith(q):
            s += 40
        elif any(w.startswith(q) for w in t.split()):
            s += 25
        elif q in t:
            s += 12
        elif any(w.startswith(q) for w in hay.split()):
            s += 6
        elif q in hay:
            s += 3
        else:
            return 0
    return s - len(t) // 12  # títulos curtos e diretos primeiro


class Entry:
    __slots__ = ("title", "sub", "icon", "hay", "page", "find", "widget", "action", "rank")

    def __init__(self, title, sub, icon, keys="", page=None, find=None, widget=None, action=None, rank=0):
        self.title, self.sub, self.icon = title, sub, icon
        self.hay = norm(f"{title} {sub} {keys}")
        self.page, self.find, self.widget, self.action, self.rank = page, find, widget, action, rank


def _shown_in(w: QWidget, stop: QWidget) -> bool:
    """O elemento está à vista dentro da página (ignora separadores não selecionados, que contam como visíveis)."""
    while w is not None and w is not stop:
        par = w.parentWidget()
        if w.isHidden() and not isinstance(par, QStackedWidget):
            return False
        w = par
    return True


def _page_entries(win, idx: int) -> list[Entry]:
    """Elementos reais de uma página já criada."""
    page = win.pages[idx]
    if page is None:
        return []
    name, ic = win.names[idx], win.icons[idx]
    out, seen = [], set()

    def add(text, w, kind, rank):
        text = " ".join(text.replace("&", "").split())
        key = norm(text)
        if len(key) < 3 or key in seen or not _shown_in(w, page):
            return
        seen.add(key)
        out.append(Entry(text, f"{name} · {kind}", ic, "", idx, None, w, None, rank))

    for lb in page.findChildren(QLabel):
        if lb.objectName() == "CardTitle":
            add(lb.text(), lb.parentWidget(), "secção", 3)
    for tw in page.findChildren(QTabWidget):
        for i in range(tw.count()):
            add(tw.tabText(i), tw.widget(i), "separador", 3)
    for row in page.findChildren(SettingRow):
        lbs = row.findChildren(QLabel)
        if lbs:
            add(lbs[0].text(), row, "opção", 2)
    for b in page.findChildren(QAbstractButton):
        if isinstance(b, (QPushButton, QCheckBox)) and b.text().strip() and len(b.text()) <= 48:
            add(b.text(), b, "botão" if isinstance(b, QPushButton) else "opção", 1)
    return out


def find_widget(page: QWidget, text: str) -> QWidget | None:
    """Procura numa página o elemento cujo texto corresponde a uma função (títulos primeiro, depois botões)."""
    want = norm(text)
    best, best_s = None, 0
    for w in page.findChildren(QWidget):
        if isinstance(w, QLabel):
            t, tgt = w.text(), (w.parentWidget() if w.objectName() == "CardTitle" else w)
            bonus = 3 if w.objectName() == "CardTitle" else 1
        elif isinstance(w, QAbstractButton):
            t, tgt, bonus = w.text(), w, 2
        elif isinstance(w, QTabWidget):
            for i in range(w.count()):
                if norm(w.tabText(i)) == want:
                    return w.widget(i)
            continue
        else:
            continue
        n = norm(t.replace("&", ""))
        if not n or not _shown_in(tgt, page):
            continue
        s = (10 if n == want else 6 if n.startswith(want) else 3 if want in n else 0)
        if s and s + bonus > best_s:
            best, best_s = tgt, s + bonus
    return best


def reveal(page: QWidget, target: QWidget, flash_parent: QWidget) -> None:
    """Abre o separador certo, faz scroll até ao elemento e destaca-o por instantes."""
    w = target
    while w is not None and w is not page:  # separadores (QTabWidget) que contêm o elemento
        par = w.parentWidget()
        if isinstance(par, QStackedWidget) and isinstance(par.parentWidget(), QTabWidget):
            par.parentWidget().setCurrentWidget(w)
        w = par
    w = target.parentWidget()
    while w is not None:  # scroll em todas as áreas que o contêm
        if isinstance(w, QScrollArea) and w.widget() is not None and w.widget().isAncestorOf(target):
            w.ensureWidgetVisible(target, 40, 80)
        if w is page:
            break
        w = w.parentWidget()
    QTimer.singleShot(60, lambda: _flash(target, flash_parent))


def _flash(target: QWidget, parent: QWidget) -> None:
    try:
        if not target.isVisible():
            return
    except RuntimeError:  # o elemento foi destruído entretanto
        return
    pos = target.mapTo(parent, QPoint(0, 0))
    f = QFrame(parent)
    f.setAttribute(Qt.WA_TransparentForMouseEvents)
    f.setStyleSheet(f"QFrame {{ border: 2px solid {theme.C['accent']}; border-radius: 12px; "
                    f"background: {theme.C['accent_soft']}; }}")
    pad = 4
    f.setGeometry(pos.x() - pad, pos.y() - pad, target.width() + 2 * pad, target.height() + 2 * pad)
    fx = QGraphicsOpacityEffect(f)
    f.setGraphicsEffect(fx)
    an = QPropertyAnimation(fx, b"opacity", f)
    an.setDuration(1600)
    an.setKeyValueAt(0, 0.0)
    an.setKeyValueAt(0.12, 1.0)
    an.setKeyValueAt(0.55, 0.85)
    an.setKeyValueAt(1, 0.0)
    an.setEasingCurve(QEasingCurve.InOutSine)
    an.finished.connect(f.deleteLater)
    f.show()
    f.raise_()
    an.start()


class _Row(QWidget):
    def __init__(self, e: Entry):
        super().__init__()
        self.setObjectName("Transparent")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        h = QHBoxLayout(self)
        h.setContentsMargins(6, 4, 10, 4)
        h.setSpacing(12)
        h.addWidget(icon_badge(e.icon, 30, 16))
        col = QVBoxLayout()
        col.setSpacing(0)
        t = label(e.title)
        f = t.font()
        f.setBold(True)
        t.setFont(f)
        col.addWidget(t)
        col.addWidget(label(e.sub, "Muted"))
        h.addLayout(col, 1)


class CommandPalette(QWidget):
    """Camada por cima da janela com a caixa de pesquisa; clicar fora ou Esc fecha."""
    MAX = 40

    def __init__(self, win, parent: QWidget):
        super().__init__(parent)
        self.win = win
        self.setAttribute(Qt.WA_StyledBackground)
        self.setObjectName("PaletteDim")
        self.panel = QFrame(self)
        self.panel.setObjectName("Palette")
        v = QVBoxLayout(self.panel)
        v.setContentsMargins(14, 14, 14, 10)
        v.setSpacing(10)
        top = QHBoxLayout()
        top.setSpacing(10)
        self.ic = QLabel()
        top.addWidget(self.ic)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText("Procurar páginas, funções, opções ou temas…")
        self.edit.setClearButtonEnabled(True)
        self.edit.textChanged.connect(self._filter)
        self.edit.installEventFilter(self)
        top.addWidget(self.edit, 1)
        v.addLayout(top)
        self.list = QListWidget()
        self.list.setUniformItemSizes(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._choose)
        self.list.itemClicked.connect(self._choose)
        v.addWidget(self.list, 1)
        self.hint = label("↑ ↓ escolher · Enter abrir · Esc fechar", "Muted")
        v.addWidget(self.hint)
        self.entries: list[Entry] = []
        self.hide()

    # ------------------------------------------------------------------ índice
    def _build(self):
        win = self.win
        out: list[Entry] = []
        for i, name in enumerate(win.names):
            keys = " ".join(f"{t} {k}" for t, k in FEATURES.get(name, []))
            group = win.btn_of[i].name if hasattr(win, "btn_of") else name
            if group != name:
                keys += f" {group}"
            out.append(Entry(name, "Página", win.icons[i], keys, i, None, None, None, 5))
            known = set()
            for e in _page_entries(win, i):
                known.add(norm(e.title))
                out.append(e)
            for title, kw in FEATURES.get(name, []):
                if norm(title) not in known:
                    out.append(Entry(title, name, win.icons[i], kw, i, title, None, None, 2))
        for key, t in theme.THEMES.items():
            out.append(Entry(f"Tema {t['name']}", "Aparência · aplicar tema", "sun" if t.get("light") else "moon",
                             f"tema {key} cores visual {'claro' if t.get('light') else 'escuro'}", None, None, None,
                             (lambda k=key: win.set_theme(k)), 0))
        out.append(Entry("Sair do Nexo", "Ação · Ctrl+Q", "power", "fechar terminar", action=win.quit, rank=0))
        self.entries = out

    def _filter(self, text: str):
        toks = norm(text).split()
        self.list.clear()
        if toks:
            hits = [(s + e.rank, e) for e in self.entries if (s := score(toks, e.title, e.hay)) > 0]
            hits.sort(key=lambda h: -h[0])
        else:  # sem texto: as páginas, pela ordem do menu
            hits = [(0, e) for e in self.entries if e.sub == "Página"]
        for _s, e in hits[:self.MAX]:
            it = QListWidgetItem()
            it.setSizeHint(QSize(0, 50))
            it.setData(Qt.UserRole, e)
            self.list.addItem(it)
            self.list.setItemWidget(it, _Row(e))
        if not hits:
            it = QListWidgetItem("Nada encontrado — experimente outra palavra.")
            it.setFlags(Qt.NoItemFlags)
            self.list.addItem(it)
        self.list.setCurrentRow(0)

    # ------------------------------------------------------------------ abrir / fechar
    def open(self):
        c = theme.C
        self.setStyleSheet(
            f"QWidget#PaletteDim {{ background: rgba(0,0,0,{110 if theme.mode() == 'dark' else 60}); }}"
            f"QFrame#Palette {{ background: {c['surface']}; border: 1px solid {c['border2']}; border-radius: 16px; }}"
            f"QFrame#Palette QLineEdit {{ font-size: 16px; padding: 8px 10px; }}"
            f"QFrame#Palette QListWidget {{ background: transparent; border: none; }}"
            f"QFrame#Palette QLabel, QFrame#Palette QWidget#Transparent {{ background: transparent; }}")
        self.ic.setPixmap(make_icon("search", c["muted"]).pixmap(20, 20))
        self._build()
        self.setGeometry(self.parentWidget().rect())
        self._place()
        self.edit.blockSignals(True)
        self.edit.clear()
        self.edit.blockSignals(False)
        self._filter("")
        self.show()
        self.raise_()
        self.edit.setFocus()

    def _place(self):
        w = min(640, self.width() - 80)
        h = min(480, self.height() - 120)
        self.panel.setGeometry((self.width() - w) // 2, 70, w, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place()

    def close_palette(self):
        self.hide()
        self.win.setFocus()

    def mousePressEvent(self, e):
        if not self.panel.geometry().contains(e.position().toPoint()):
            self.close_palette()

    def eventFilter(self, obj, e):
        if obj is self.edit and e.type() == QEvent.KeyPress:
            k = e.key()
            if k == Qt.Key_Escape:
                self.close_palette()
                return True
            if k in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                n = self.list.count()
                if n:
                    step = {Qt.Key_Down: 1, Qt.Key_Up: -1, Qt.Key_PageDown: 6, Qt.Key_PageUp: -6}[k]
                    self.list.setCurrentRow(max(0, min(n - 1, self.list.currentRow() + step)))
                return True
            if k in (Qt.Key_Return, Qt.Key_Enter):
                it = self.list.currentItem()
                if it is not None:
                    self._choose(it)
                return True
        return super().eventFilter(obj, e)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.close_palette()
        else:
            super().keyPressEvent(e)

    def _choose(self, it: QListWidgetItem):
        e: Entry | None = it.data(Qt.UserRole)
        if e is None:
            return
        self.close_palette()
        if e.action is not None:
            e.action()
            return
        self.win.go(e.page)
        page = self.win.pages[e.page]
        target = e.widget
        if target is None and e.find:
            target = find_widget(page, e.find)
        if target is not None:
            try:
                reveal(page, target, self.win.right)
            except RuntimeError:  # elemento destruído (a página recriou-o)
                pass
