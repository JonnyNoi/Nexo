"""Ajustes do sistema com interruptor ligado/desligado e "restaurar originais".

Cada ajuste guarda o valor original antes de mudar (em tweaks_backup.json), por isso
desligar um ajuste repõe exatamente o que estava antes.
"""
from __future__ import annotations

import glob
import os
import re

from . import snapshot
from .util import IS_LINUX, IS_WIN, _save_lock, is_admin, load_json, read_text, run, run_root, save_json, which

BACKUP_FILE = "tweaks_backup.json"


class Tweak:
    id = ""
    name = ""
    desc = ""
    category = "Desempenho"
    needs_admin = False
    reboot = False

    def available(self) -> bool:
        return True

    def is_on(self) -> bool | None:
        raise NotImplementedError

    def set(self, on: bool) -> tuple[bool, str]:
        raise NotImplementedError

    # backup partilhado
    def _backup_get(self, key, default=None):
        return load_json(BACKUP_FILE, {}).get(f"{self.id}:{key}", default)

    # ler-alterar-gravar sob o mesmo trinco: dois ajustes ligados ao mesmo tempo não podem
    # perder o valor original um do outro
    def _backup_set(self, key, value) -> None:
        with _save_lock:
            data = load_json(BACKUP_FILE, {})
            data.setdefault(f"{self.id}:{key}", value)  # só guarda o primeiro (o original)
            save_json(BACKUP_FILE, data)

    def _backup_clear(self, key) -> None:
        with _save_lock:
            data = load_json(BACKUP_FILE, {})
            data.pop(f"{self.id}:{key}", None)
            save_json(BACKUP_FILE, data)


# =========================================================================== Windows
if IS_WIN:
    import winreg

    _HIVES = {"HKCU": winreg.HKEY_CURRENT_USER, "HKLM": winreg.HKEY_LOCAL_MACHINE}
    _TYPES = {"dword": winreg.REG_DWORD, "sz": winreg.REG_SZ}

    def reg_get(hive: str, path: str, name: str):
        try:
            with winreg.OpenKey(_HIVES[hive], path, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as k:
                return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return None

    def reg_set(hive: str, path: str, name: str, typ: str, value) -> None:
        with winreg.CreateKeyEx(_HIVES[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
            winreg.SetValueEx(k, name, 0, _TYPES[typ], value)

    def reg_del(hive: str, path: str, name: str) -> None:
        try:
            with winreg.OpenKey(_HIVES[hive], path, 0, winreg.KEY_SET_VALUE | winreg.KEY_WOW64_64KEY) as k:
                winreg.DeleteValue(k, name)
        except OSError:
            pass


class RegTweak(Tweak):
    """values = [(hive, caminho, nome, tipo, valor_quando_ligado), ...]"""

    def __init__(self, id, name, desc, values, category="Desempenho", reboot=False):
        self.id, self.name, self.desc, self.values = id, name, desc, values
        self.category, self.reboot = category, reboot
        self.needs_admin = any(v[0] == "HKLM" for v in values)

    def available(self) -> bool:
        return IS_WIN

    def is_on(self) -> bool | None:
        return all(reg_get(h, p, n) == v for h, p, n, _t, v in self.values)

    def set(self, on: bool) -> tuple[bool, str]:
        if self.needs_admin and not is_admin():
            return False, "Precisa de executar como administrador."
        try:
            for h, p, n, t, v in self.values:
                key = f"{h}\\{p}\\{n}"
                if on:
                    self._backup_set(key, reg_get(h, p, n))
                    reg_set(h, p, n, t, v)
                else:
                    orig = self._backup_get(key)
                    if orig is None:
                        reg_del(h, p, n)
                    else:
                        reg_set(h, p, n, t, orig)
                    self._backup_clear(key)
            return True, "Feito" + (" (reinicie o PC para aplicar)" if self.reboot else "")
        except OSError as e:
            return False, str(e)


class ServiceTweak(Tweak):
    """Desativa serviços do Windows (ligado = desativado)."""

    def __init__(self, id, name, desc, services, category="Privacidade"):
        self.id, self.name, self.desc, self.services, self.category = id, name, desc, services, category
        self.needs_admin = True

    def available(self) -> bool:
        return IS_WIN

    def _start_type(self, svc):
        v = reg_get("HKLM", rf"SYSTEM\CurrentControlSet\Services\{svc}", "Start")
        return v

    def is_on(self) -> bool | None:
        states = [self._start_type(s) for s in self.services]
        states = [s for s in states if s is not None]
        return bool(states) and all(s == 4 for s in states)

    def set(self, on: bool) -> tuple[bool, str]:
        if not is_admin():
            return False, "Precisa de executar como administrador."
        names = {2: "auto", 3: "demand", 4: "disabled"}
        for s in self.services:
            cur = self._start_type(s)
            if cur is None:
                continue
            if on:
                self._backup_set(s, cur)
                run(["sc", "stop", s], timeout=20)
                code, out = run(["sc", "config", s, "start=", "disabled"], timeout=20)
            else:
                orig = self._backup_get(s, 3)
                code, out = run(["sc", "config", s, "start=", names.get(orig, "demand")], timeout=20)
                if orig == 2:
                    run(["sc", "start", s], timeout=20)
                self._backup_clear(s)
            if code != 0:
                return False, out
        return True, "Feito"


class WinPowerPlan(Tweak):
    id = "win_power"
    name = "Plano de energia Alto desempenho"
    desc = "Mantém a CPU nos clocks altos (mais consumo). Desligar volta ao plano anterior."
    HIGH = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    ULTIMATE = "e9a42b02-d5df-448d-aa00-03f14749eb61"

    def available(self) -> bool:
        return IS_WIN

    def _active(self) -> str:
        _, out = run(["powercfg", "/getactivescheme"], timeout=10)
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", out, re.I)
        return m.group(1).lower() if m else ""

    def is_on(self) -> bool | None:
        return self._active() in (self.HIGH, self.ULTIMATE)

    def set(self, on: bool) -> tuple[bool, str]:
        if on:
            self._backup_set("scheme", self._active())
            code, out = run(["powercfg", "/setactive", self.HIGH], timeout=10)
            if code != 0:  # alguns portáteis escondem o plano: duplica-o
                run(["powercfg", "-duplicatescheme", self.HIGH], timeout=10)
                code, out = run(["powercfg", "/setactive", self.HIGH], timeout=10)
        else:
            orig = self._backup_get("scheme") or "381b4222-f694-41f0-9685-ff5bb260df2e"  # Equilibrado
            code, out = run(["powercfg", "/setactive", orig], timeout=10)
            self._backup_clear("scheme")
        return code == 0, out or "Feito"


# =========================================================================== Linux
_CPUFREQ = "/sys/devices/system/cpu/cpu*/cpufreq/scaling_governor"


class LinuxGovernor(Tweak):
    id = "linux_governor"
    name = "Governor da CPU em \"performance\""
    desc = "Mantém os clocks no máximo (mais consumo e calor). Desligar repõe o governor anterior."
    needs_admin = True

    def available(self) -> bool:
        return IS_LINUX and bool(glob.glob(_CPUFREQ))

    def is_on(self) -> bool | None:
        return read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor") == "performance"

    def set(self, on: bool) -> tuple[bool, str]:
        if on:
            self._backup_set("gov", read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor"))
            target = "performance"
        else:
            target = self._backup_get("gov") or "powersave"
            avail = read_text("/sys/devices/system/cpu/cpu0/cpufreq/scaling_available_governors").split()
            if avail and target not in avail:
                target = "schedutil" if "schedutil" in avail else avail[0]
        cmd = f"for f in {_CPUFREQ}; do echo {target} > $f; done"
        code, out = run_root(snapshot.with_snapshot(cmd, f"ajuste: {self.name}") if on else cmd)
        if code == 0 and not on:
            self._backup_clear("gov")
        return code == 0, out or f"Governor: {target}"


class LinuxPowerProfile(Tweak):
    id = "linux_ppd"
    name = "Perfil de energia \"performance\""
    desc = "Usa o power-profiles-daemon / tuned-ppd (o mesmo do menu do ambiente gráfico)."

    def available(self) -> bool:
        return IS_LINUX and bool(which("powerprofilesctl"))

    def is_on(self) -> bool | None:
        _, out = run(["powerprofilesctl", "get"], timeout=5)
        return out.strip() == "performance"

    def set(self, on: bool) -> tuple[bool, str]:
        if on:
            _, cur = run(["powerprofilesctl", "get"], timeout=5)
            self._backup_set("profile", cur.strip())
            code, out = run(["powerprofilesctl", "set", "performance"], timeout=10)
        else:
            code, out = run(["powerprofilesctl", "set", self._backup_get("profile") or "balanced"], timeout=10)
            self._backup_clear("profile")
        return code == 0, out or "Feito"


class LinuxSysctl(Tweak):
    """Grava /etc/sysctl.d/99-nexo-<id>.conf (persistente) e aplica já."""
    needs_admin = True

    def __init__(self, id, name, desc, key, value):
        self.id, self.name, self.desc, self.key, self.value = id, name, desc, key, str(value)

    def available(self) -> bool:
        return IS_LINUX and os.path.exists("/proc/sys/" + self.key.replace(".", "/"))

    def _conf(self) -> str:
        return f"/etc/sysctl.d/99-nexo-{self.id}.conf"

    def is_on(self) -> bool | None:
        return read_text("/proc/sys/" + self.key.replace(".", "/")) == self.value

    def set(self, on: bool) -> tuple[bool, str]:
        path = "/proc/sys/" + self.key.replace(".", "/")
        if on:
            self._backup_set("v", read_text(path))
            cmd = f"echo '{self.key} = {self.value}' > {self._conf()} && sysctl -w {self.key}={self.value}"
        else:
            orig = self._backup_get("v") or self.value
            legacy = f"/etc/sysctl.d/99-pcforge-{self.id}.conf"  # nome antigo (PCForge)
            cmd = f"rm -f {self._conf()} {legacy} && sysctl -w {self.key}={orig}"
        code, out = run_root(snapshot.with_snapshot(cmd, f"ajuste: {self.name}") if on else cmd)
        if code == 0 and not on:
            self._backup_clear("v")
        return code == 0, out or "Feito"


# =========================================================================== catálogos
def performance_tweaks() -> list[Tweak]:
    if IS_WIN:
        return [
            WinPowerPlan(),
            RegTweak("win_gamemode", "Modo de Jogo do Windows",
                     "Dá prioridade ao jogo e evita atualizações/notificações durante o jogo.",
                     [("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled", "dword", 1),
                      ("HKCU", r"Software\Microsoft\GameBar", "AllowAutoGameMode", "dword", 1)]),
            RegTweak("win_gamedvr", "Desativar Game DVR / gravação em segundo plano",
                     "A gravação contínua da Xbox Game Bar custa FPS.",
                     [("HKCU", r"System\GameConfigStore", "GameDVR_Enabled", "dword", 0),
                      ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\GameDVR", "AppCaptureEnabled", "dword", 0)]),
            RegTweak("win_hags", "Agendamento de GPU acelerado por hardware (HAGS)",
                     "Reduz latência em GPUs recentes (NVIDIA 10xx+, AMD RX 5000+).",
                     [("HKLM", r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", "dword", 2)],
                     reboot=True),
            RegTweak("win_windowed", "Otimizações para jogos em janela",
                     "Usa o modelo flip moderno em jogos DX10/11 em janela sem borda.",
                     [("HKCU", r"Software\Microsoft\DirectX\UserGpuPreferences", "DirectXUserGlobalSettings",
                       "sz", "SwapEffectUpgradeEnable=1;")]),
            RegTweak("win_mouseaccel", "Desativar aceleração do rato",
                     "Movimento 1:1 (\"Melhorar precisão do ponteiro\" desligado). Aplica após terminar sessão.",
                     [("HKCU", r"Control Panel\Mouse", "MouseSpeed", "sz", "0"),
                      ("HKCU", r"Control Panel\Mouse", "MouseThreshold1", "sz", "0"),
                      ("HKCU", r"Control Panel\Mouse", "MouseThreshold2", "sz", "0")]),
            RegTweak("win_visualfx", "Menos animações do Windows",
                     "Desliga animações de janelas/menus (o Windows parece mais rápido).",
                     [("HKCU", r"Control Panel\Desktop\WindowMetrics", "MinAnimate", "sz", "0"),
                      ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarAnimations", "dword", 0)]),
        ]
    if IS_LINUX:
        tw: list[Tweak] = [
            LinuxPowerProfile(),
            LinuxGovernor(),
            LinuxSysctl("swappiness", "Swappiness baixo (10)",
                        "Usa menos swap enquanto há RAM livre — sistema mais responsivo com muita RAM.",
                        "vm.swappiness", 10),
            LinuxSysctl("vfs_cache", "Manter cache de pastas (vfs_cache_pressure 50)",
                        "Abre pastas e procura ficheiros mais depressa.", "vm.vfs_cache_pressure", 50),
            LinuxSysctl("max_map", "vm.max_map_count alto (jogos Steam/Proton)",
                        "Valor recomendado pela Valve; evita crashes em alguns jogos.", "vm.max_map_count", 2147483642),
        ]
        return [t for t in tw if t.available()]
    return []


_CDM = r"Software\Microsoft\Windows\CurrentVersion\ContentDeliveryManager"


def privacy_tweaks() -> list[Tweak]:
    """Debloat / privacidade — só Windows. Nada que reduza a segurança (Defender, UAC, Update)."""
    if not IS_WIN:
        return []
    P = "Privacidade"
    U = "Interface"
    return [
        RegTweak("w_telemetry", "Telemetria no mínimo",
                 "Envia à Microsoft só os dados obrigatórios.",
                 [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", "dword", 0)], P),
        ServiceTweak("w_diagtrack", "Desativar serviços de telemetria",
                     "Connected User Experiences (DiagTrack) e WAP Push (dmwappushservice).",
                     ["DiagTrack", "dmwappushservice"], P),
        RegTweak("w_adid", "Desativar ID de publicidade",
                 "As apps deixam de usar um identificador para anúncios personalizados.",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", "dword", 0)], P),
        RegTweak("w_tailored", "Desativar experiências personalizadas",
                 "Sem dicas e anúncios baseados nos dados de diagnóstico.",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled", "dword", 0)], P),
        RegTweak("w_activity", "Desativar histórico de atividades",
                 "O Windows deixa de guardar a linha do tempo das apps e ficheiros abertos.",
                 [("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", "dword", 0),
                  ("HKLM", r"SOFTWARE\Policies\Microsoft\Windows\System", "UploadUserActivities", "dword", 0)], P),
        RegTweak("w_recall", "Desativar Recall (capturas de ecrã por IA)",
                 "Impede o Windows de guardar instantâneos do ecrã (PCs Copilot+).",
                 [("HKCU", r"Software\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", "dword", 1)], P),
        RegTweak("w_feedback", "Não pedir feedback",
                 "Desliga as janelas \"Como avalia o Windows?\".",
                 [("HKCU", r"Software\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", "dword", 0)], P),
        RegTweak("w_suggest", "Sem anúncios e sugestões no Iniciar",
                 "Remove apps sugeridas, dicas e instalações silenciosas de apps promovidas.",
                 [("HKCU", _CDM, "SystemPaneSuggestionsEnabled", "dword", 0),
                  ("HKCU", _CDM, "SilentInstalledAppsEnabled", "dword", 0),
                  ("HKCU", _CDM, "SubscribedContent-338388Enabled", "dword", 0),
                  ("HKCU", _CDM, "SubscribedContent-338389Enabled", "dword", 0),
                  ("HKCU", _CDM, "SubscribedContent-353694Enabled", "dword", 0),
                  ("HKCU", _CDM, "SubscribedContent-353696Enabled", "dword", 0),
                  ("HKCU", _CDM, "SoftLandingEnabled", "dword", 0)], U),
        RegTweak("w_lockscreen", "Sem dicas no ecrã de bloqueio",
                 "Desliga \"factos divertidos e dicas\" do Windows Spotlight no bloqueio.",
                 [("HKCU", _CDM, "RotatingLockScreenOverlayEnabled", "dword", 0),
                  ("HKCU", _CDM, "SubscribedContent-338387Enabled", "dword", 0)], U),
        RegTweak("w_bing", "Pesquisa do Iniciar sem Bing",
                 "A pesquisa procura só no PC (sem resultados da web).",
                 [("HKCU", r"Software\Policies\Microsoft\Windows\Explorer", "DisableSearchBoxSuggestions", "dword", 1)], U),
        RegTweak("w_copilot", "Desativar Copilot",
                 "Remove o Copilot da barra de tarefas (Windows 11).",
                 [("HKCU", r"Software\Policies\Microsoft\Windows\WindowsCopilot", "TurnOffWindowsCopilot", "dword", 1),
                  ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowCopilotButton", "dword", 0)], U),
        RegTweak("w_widgets", "Desativar Widgets / Notícias",
                 "Remove o painel de widgets e notícias da barra de tarefas.",
                 [("HKLM", r"SOFTWARE\Policies\Microsoft\Dsh", "AllowNewsAndInterests", "dword", 0)], U),
        RegTweak("w_chat", "Esconder botão Chat/Teams",
                 "Remove o ícone do Teams (pessoal) da barra de tarefas.",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarMn", "dword", 0)], U),
        RegTweak("w_ext", "Mostrar extensões dos ficheiros",
                 "Ajuda a identificar ficheiros perigosos (ex.: fatura.pdf.exe).",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "HideFileExt", "dword", 0)], U),
    ]


class KeyTweak(Tweak):
    """Cria uma chave do registo com um valor (ligado) e apaga a chave inteira (desligado).
    Usado para o menu de contexto clássico do Windows 11."""

    def __init__(self, id, name, desc, hive, path, category="Interface"):
        self.id, self.name, self.desc, self.hive, self.path, self.category = id, name, desc, hive, path, category
        self.needs_admin = hive == "HKLM"

    def available(self) -> bool:
        return IS_WIN

    def is_on(self) -> bool | None:
        code, _ = run(["reg", "query", f"{self.hive}\\{self.path}"], timeout=10)
        return code == 0

    def set(self, on: bool) -> tuple[bool, str]:
        if on:
            code, out = run(["reg", "add", f"{self.hive}\\{self.path}", "/ve", "/d", "", "/f"], timeout=10)
        else:
            parent = self.path.rsplit("\\", 1)[0]
            code, out = run(["reg", "delete", f"{self.hive}\\{parent}", "/f"], timeout=10)
        if code == 0:
            run(["taskkill", "/f", "/im", "explorer.exe"], timeout=10)
            import subprocess
            subprocess.Popen(["explorer.exe"])
        return code == 0, "Feito (o Explorador foi reiniciado)" if code == 0 else out


class WinHibernation(Tweak):
    id = "w_hiber"
    name = "Desativar hibernação"
    desc = ("Apaga o hiberfil.sys (liberta tantos GB como a RAM) e desliga o \"arranque rápido\". "
            "Desligar este ajuste volta a ativar.")
    category = "Sistema"
    needs_admin = True

    def available(self) -> bool:
        return IS_WIN

    def is_on(self) -> bool | None:
        return reg_get("HKLM", r"SYSTEM\CurrentControlSet\Control\Power", "HibernateEnabled") == 0

    def set(self, on: bool) -> tuple[bool, str]:
        if not is_admin():
            return False, "Precisa de executar como administrador."
        code, out = run(["powercfg", "/hibernate", "off" if on else "on"], timeout=20)
        return code == 0, out or "Feito"


class WinUltimatePlan(Tweak):
    id = "w_ultimate"
    name = "Plano de energia Desempenho Máximo"
    desc = ("O plano \"Ultimate Performance\" escondido do Windows: sem poupança de energia nenhuma. "
            "Ideal para desktops; evite em portáteis a bateria.")
    category = "Sistema"
    GUID = "e9a42b02-d5df-448d-aa00-03f14749eb61"

    def available(self) -> bool:
        return IS_WIN

    def _active(self) -> tuple[str, str]:
        _, out = run(["powercfg", "/getactivescheme"], timeout=10)
        m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", out, re.I)
        return (m.group(1).lower() if m else ""), out.lower()

    def is_on(self) -> bool | None:
        guid, txt = self._active()
        return guid == self.GUID or "ultimate" in txt or "desempenho máximo" in txt

    def set(self, on: bool) -> tuple[bool, str]:
        if on:
            self._backup_set("scheme", self._active()[0])
            code, out = run(["powercfg", "-duplicatescheme", self.GUID], timeout=10)
            m = re.search(r"([0-9a-f]{8}-[0-9a-f-]{27})", out, re.I)
            target = m.group(1) if m else self.GUID
            code, out = run(["powercfg", "/setactive", target], timeout=10)
        else:
            orig = self._backup_get("scheme") or "381b4222-f694-41f0-9685-ff5bb260df2e"
            code, out = run(["powercfg", "/setactive", orig], timeout=10)
            self._backup_clear("scheme")
        return code == 0, out or "Feito"


_ADV = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"


def windows_extra_tweaks() -> list[Tweak]:
    """Ajustes "essenciais" e "avançados" ao estilo do WinUtil — todos reversíveis."""
    if not IS_WIN:
        return []
    S, U, R = "Sistema", "Interface", "Rede"
    return [
        WinUltimatePlan(),
        WinHibernation(),
        RegTweak("w_endtask", "\"Terminar tarefa\" no clique direito da barra de tarefas",
                 "Fecha um programa bloqueado sem abrir o Gestor de Tarefas (Windows 11).",
                 [("HKCU", _ADV + r"\TaskbarDeveloperSettings", "TaskbarEndTask", "dword", 1)], U),
        KeyTweak("w_classicmenu", "Menu de contexto clássico (Windows 11)",
                 "Volta ao menu do botão direito completo, sem o \"Mostrar mais opções\".", "HKCU",
                 r"Software\Classes\CLSID\{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}\InprocServer32"),
        RegTweak("w_hidden", "Mostrar ficheiros ocultos", "Mostra pastas como AppData no Explorador.",
                 [("HKCU", _ADV, "Hidden", "dword", 1)], U),
        RegTweak("w_dark", "Modo escuro", "Tema escuro nas apps e no sistema.",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "AppsUseLightTheme", "dword", 0),
                  ("HKCU", r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize", "SystemUsesLightTheme", "dword", 0)], U),
        RegTweak("w_taskleft", "Barra de tarefas alinhada à esquerda", "Botão Iniciar no canto, como no Windows 10.",
                 [("HKCU", _ADV, "TaskbarAl", "dword", 0)], U),
        RegTweak("w_sticky", "Desativar atalho das Teclas Presas",
                 "Carregar 5× no Shift (a jogar) deixa de abrir a janela das Teclas Presas.",
                 [("HKCU", r"Control Panel\Accessibility\StickyKeys", "Flags", "sz", "506")], U),
        RegTweak("w_numlock", "NumLock ligado ao iniciar", "O teclado numérico já vem ativo.",
                 [("HKCU", r"Control Panel\Keyboard", "InitialKeyboardIndicators", "sz", "2")], U),
        RegTweak("w_bgapps", "Desativar apps em segundo plano",
                 "As apps da Store deixam de correr escondidas (menos RAM e bateria).",
                 [("HKCU", r"Software\Microsoft\Windows\CurrentVersion\BackgroundAccessApplications",
                   "GlobalUserDisabled", "dword", 1)], S),
        RegTweak("w_fso", "Desativar otimizações de ecrã inteiro",
                 "Ecrã inteiro exclusivo a sério em jogos antigos (pode reduzir latência).",
                 [("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehaviorMode", "dword", 2),
                  ("HKCU", r"System\GameConfigStore", "GameDVR_HonorUserFSEBehaviorMode", "dword", 1),
                  ("HKCU", r"System\GameConfigStore", "GameDVR_FSEBehavior", "dword", 2),
                  ("HKCU", r"System\GameConfigStore", "GameDVR_DXGIHonorFSEWindowsCompatible", "dword", 1)], S),
        RegTweak("w_bsod", "Ecrã azul detalhado", "Mostra o código de erro e o driver culpado num crash.",
                 [("HKLM", r"SYSTEM\CurrentControlSet\Control\CrashControl", "DisplayParameters", "dword", 1)], S),
        RegTweak("w_verbose", "Mensagens detalhadas ao arrancar/desligar",
                 "Mostra o que o Windows está a fazer quando parece preso.",
                 [("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System", "VerboseStatus", "dword", 1)], S),
        RegTweak("w_location", "Desativar localização", "As apps deixam de poder pedir a sua localização.",
                 [("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\location",
                   "Value", "sz", "Deny")], S),
        RegTweak("w_pstelemetry", "Desativar telemetria do PowerShell 7",
                 "Variável POWERSHELL_TELEMETRY_OPTOUT=1.",
                 [("HKCU", r"Environment", "POWERSHELL_TELEMETRY_OPTOUT", "sz", "1")], S),
        RegTweak("w_ipv4", "Preferir IPv4 em vez de IPv6",
                 "Resolve lentidão em redes com IPv6 mal configurado (não desliga o IPv6).",
                 [("HKLM", r"SYSTEM\CurrentControlSet\Services\Tcpip6\Parameters", "DisabledComponents", "dword", 32)],
                 R, reboot=True),
    ]


class LinuxBBR(LinuxSysctl):
    def available(self) -> bool:
        return IS_LINUX and (os.path.exists("/lib/modules") and bool(
            glob.glob(f"/lib/modules/{os.uname().release}/kernel/net/ipv4/tcp_bbr*")) or
            "bbr" in read_text("/proc/sys/net/ipv4/tcp_available_congestion_control"))


def linux_extra_tweaks() -> list[Tweak]:
    if not IS_LINUX:
        return []
    tw: list[Tweak] = [
        LinuxBBR("bbr", "Controlo de congestão TCP BBR",
                 "Algoritmo da Google: downloads mais rápidos e menos latência em redes congestionadas.",
                 "net.ipv4.tcp_congestion_control", "bbr"),
        LinuxSysctl("nmi_watchdog", "Desativar o NMI watchdog",
                    "Liberta um contador de hardware por núcleo e reduz interrupções (ligeiro ganho em jogos).",
                    "kernel.nmi_watchdog", 0),
        LinuxSysctl("split_lock", "Desativar mitigação de split-lock",
                    "Evita quebras de FPS em alguns jogos (o mesmo que o Steam Deck faz).",
                    "kernel.split_lock_mitigate", 0),
        LinuxSysctl("inotify", "Mais inotify watches (524288)",
                    "Evita erros \"too many open files\" no VS Code, Syncthing, Dropbox…",
                    "fs.inotify.max_user_watches", 524288),
    ]
    return [t for t in tw if t.available()]


def restore_all(tweaks: list[Tweak]) -> list[str]:
    msgs = []
    for t in tweaks:
        try:
            if t.is_on():
                ok, m = t.set(False)
                msgs.append(f"{t.name}: {'restaurado' if ok else m}")
        except Exception as e:  # noqa: BLE001
            msgs.append(f"{t.name}: {e}")
    return msgs
