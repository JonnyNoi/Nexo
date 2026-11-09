"""Windows debloat: remover apps pré-instaladas (Appx) desnecessárias.

As apps removidas podem ser reinstaladas a partir da Microsoft Store.
Nada aqui toca em componentes de segurança (Defender, SmartScreen, Update, UAC).
"""
from __future__ import annotations

from dataclasses import dataclass

from .util import IS_WIN, as_list, ps_json, run_ps


@dataclass
class BloatApp:
    package: str      # nome do pacote Appx (padrão)
    label: str
    desc: str
    recommended: bool = True


CATALOG: list[BloatApp] = [
    BloatApp("Microsoft.BingNews", "Notícias (Microsoft News)", "Feed de notícias do MSN."),
    BloatApp("Microsoft.BingWeather", "Meteorologia (MSN)", "App de meteorologia do MSN.", False),
    BloatApp("Microsoft.BingSearch", "Pesquisa Bing", "Integração da pesquisa Bing."),
    BloatApp("Microsoft.GetHelp", "Obter Ajuda", "Assistente de ajuda online."),
    BloatApp("Microsoft.Getstarted", "Dicas", "App de dicas do Windows."),
    BloatApp("Microsoft.MicrosoftSolitaireCollection", "Solitaire Collection", "Jogos de cartas com anúncios."),
    BloatApp("Microsoft.MicrosoftOfficeHub", "Microsoft 365 (Office Hub)", "Atalho/publicidade do Office."),
    BloatApp("Microsoft.People", "Pessoas", "Contactos (descontinuada)."),
    BloatApp("Microsoft.WindowsFeedbackHub", "Hub de Comentários", "Enviar feedback à Microsoft."),
    BloatApp("Microsoft.WindowsMaps", "Mapas", "Mapas offline do Windows."),
    BloatApp("Microsoft.ZuneVideo", "Filmes e TV", "Leitor/loja de vídeo."),
    BloatApp("Microsoft.ZuneMusic", "Groove / Leitor Multimédia", "Leitor de música da Microsoft.", False),
    BloatApp("Microsoft.YourPhone", "Ligação ao Telemóvel", "Liga o telemóvel ao PC.", False),
    BloatApp("Microsoft.WindowsAlarms", "Alarmes e Relógio", "Alarmes, temporizador, cronómetro.", False),
    BloatApp("Microsoft.WindowsSoundRecorder", "Gravador de Voz", "Gravador de áudio simples.", False),
    BloatApp("Microsoft.Todos", "Microsoft To Do", "Lista de tarefas."),
    BloatApp("Microsoft.PowerAutomateDesktop", "Power Automate", "Automatização de tarefas."),
    BloatApp("Microsoft.549981C3F5F10", "Cortana", "Assistente de voz (descontinuada)."),
    BloatApp("Microsoft.Windows.DevHome", "Dev Home", "Painel para programadores."),
    BloatApp("Microsoft.OutlookForWindows", "Outlook (novo)", "Novo cliente de e-mail.", False),
    BloatApp("MicrosoftCorporationII.QuickAssist", "Assistência Rápida", "Suporte remoto.", False),
    BloatApp("MicrosoftCorporationII.MicrosoftFamily", "Microsoft Family", "Controlo parental online."),
    BloatApp("Microsoft.MixedReality.Portal", "Portal de Realidade Mista", "Para óculos VR Windows MR."),
    BloatApp("Microsoft.3DBuilder", "3D Builder", "Editor 3D."),
    BloatApp("Microsoft.Microsoft3DViewer", "Visualizador 3D", "Visualizador de modelos 3D."),
    BloatApp("Microsoft.Print3D", "Print 3D", "Impressão 3D."),
    BloatApp("Microsoft.SkypeApp", "Skype", "Descontinuado em 2025."),
    BloatApp("Microsoft.MicrosoftStickyNotes", "Notas Autoadesivas", "Post-its no ambiente de trabalho.", False),
    BloatApp("Microsoft.Office.OneNote", "OneNote (Store)", "Versão Store do OneNote.", False),
    BloatApp("Microsoft.Copilot", "Copilot (app)", "Assistente de IA da Microsoft."),
    BloatApp("Microsoft.Windows.Ai.Copilot.Provider", "Copilot (fornecedor)", "Componente do Copilot."),
    BloatApp("Clipchamp.Clipchamp", "Clipchamp", "Editor de vídeo online."),
    BloatApp("MSTeams", "Microsoft Teams (pessoal)", "Chat do Teams."),
    BloatApp("Microsoft.XboxApp", "Xbox Console Companion", "App antiga da Xbox.", False),
    BloatApp("Microsoft.GamingApp", "Xbox (app)", "Loja Xbox / Game Pass — mantenha se usa Game Pass.", False),
    BloatApp("Microsoft.XboxGamingOverlay", "Xbox Game Bar", "Sobreposição Win+G — mantenha se grava jogos.", False),
    BloatApp("SpotifyAB.SpotifyMusic", "Spotify (pré-instalado)", "Instalado automaticamente."),
    BloatApp("Disney.37853FC22B2CE", "Disney+", "Instalado automaticamente."),
    BloatApp("BytedancePte.Ltd.TikTok", "TikTok", "Instalado automaticamente."),
    BloatApp("Facebook.Facebook", "Facebook", "Instalado automaticamente."),
    BloatApp("FACEBOOK.317180B0BB486", "Messenger", "Instalado automaticamente."),
    BloatApp("Facebook.InstagramBeta", "Instagram", "Instalado automaticamente."),
    BloatApp("AmazonVideo.PrimeVideo", "Prime Video", "Instalado automaticamente."),
    BloatApp("king.com.CandyCrushSaga", "Candy Crush Saga", "Jogo instalado automaticamente."),
    BloatApp("king.com.CandyCrushSodaSaga", "Candy Crush Soda", "Jogo instalado automaticamente."),
    BloatApp("king.com.BubbleWitch3Saga", "Bubble Witch 3", "Jogo instalado automaticamente."),
    BloatApp("5A894077.McAfeeSecurity", "McAfee (versão de teste)", "Antivírus de teste — o Defender já protege."),
    BloatApp("Microsoft.LinkedIn", "LinkedIn", "Instalado automaticamente."),
]


def installed() -> dict[str, dict]:
    """{nome_pacote: {Name, PackageFullName, Version}} das apps do catálogo instaladas."""
    if not IS_WIN:
        return {}
    names = ",".join(f"'{a.package}'" for a in CATALOG)
    data = ps_json(f"$n=@({names}); Get-AppxPackage | Where-Object {{ $n -contains $_.Name }} | "
                   "Select Name,PackageFullName,Version", timeout=60)
    return {d["Name"]: d for d in as_list(data)}


def remove(package: str, all_users: bool = False) -> tuple[bool, str]:
    """Remove a app do utilizador atual e o pacote provisionado (para não voltar em novas contas)."""
    if not IS_WIN:
        return False, "Só no Windows"
    script = (f"$p = Get-AppxPackage {'-AllUsers ' if all_users else ''}-Name '{package}'; "
              f"if ($p) {{ $p | Remove-AppxPackage {'-AllUsers ' if all_users else ''}-ErrorAction Stop }}; "
              f"Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue | "
              f"Where-Object DisplayName -eq '{package}' | Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue | Out-Null; "
              "'ok'")
    code, out = run_ps(script, timeout=180)
    return code == 0 and out.strip().endswith("ok"), out.strip()[-300:]
