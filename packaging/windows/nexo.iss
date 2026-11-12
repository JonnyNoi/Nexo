; Instalador do Nexo para Windows (Inno Setup 6/7).
; Gerado por: ./build_windows_wine.sh --instalador   →   Aplicacao/Windows/Nexo-Instalador-<versão>.exe
#ifndef AppVersion
  #define AppVersion "2.2"
#endif

[Setup]
AppId={{6F0B7E43-2C1A-4E6B-9F3D-6E5C0A1B9D27}
AppName=Nexo
AppVersion={#AppVersion}
AppVerName=Nexo {#AppVersion}
AppPublisher=Nexo
DefaultDirName={autopf}\Nexo
DefaultGroupName=Nexo
DisableProgramGroupPage=yes
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\Aplicacao\Windows
OutputBaseFilename=Nexo-Instalador-{#AppVersion}
SetupIconFile=..\..\assets\nexo.ico
UninstallDisplayIcon={app}\Nexo.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes

[Languages]
Name: "pt"; MessagesFile: "compiler:Languages\Portuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho no ambiente de trabalho"; GroupDescription: "Atalhos:"

[Files]
Source: "..\..\Aplicacao\Windows\Nexo.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Nexo"; Filename: "{app}\Nexo.exe"
Name: "{group}\Desinstalar o Nexo"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Nexo"; Filename: "{app}\Nexo.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Nexo.exe"; Description: "Abrir o Nexo"; Flags: nowait postinstall skipifsilent shellexec

[UninstallDelete]
; as definições ficam em %APPDATA%\Nexo (o utilizador pode querer reinstalar); só se apaga o que o Nexo criou ao lado do .exe
Type: files; Name: "{app}\Nexo.old.exe"
Type: files; Name: "{app}\Nexo.exe.novo"
