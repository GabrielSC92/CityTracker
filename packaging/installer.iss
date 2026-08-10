; City Tracker — Windows installer.
;
; Compiled by build.ps1, which stages everything this script ships into
; ..\build\payload. Don't run ISCC on this file directly; PayloadDir and
; AppVersion arrive as /D defines.
;
; Deliberate choices:
;   * PrivilegesRequired=lowest — installs under the user's own AppData, so
;     nobody has to find an administrator password or approve a UAC prompt.
;   * The database lives outside {app} (see db.py), so reinstalling or
;     uninstalling never destroys someone's travel history.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef PayloadDir
  #define PayloadDir "..\build\payload"
#endif

#define AppName "City Tracker"
#define AppExeName "python\python.exe"
; The launcher path is quoted for the command line, so every occurrence below
; writes it literally with Inno's doubled quotes rather than via a #define --
; a define would expand one level too far and unbalance the parameter.

[Setup]
AppId={{4C7B9E2A-7F13-4D5E-9C86-1A2B3C4D5E6F}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
VersionInfoVersion={#AppVersion}
AppPublisher=City Tracker
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=CityTracker-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\icon.ico
UninstallDisplayName={#AppName}
Compression=lzma2/max
SolidCompression=yes
LZMANumBlockThreads=4
WizardStyle=modern
WizardSizePercent=110
ShowLanguageDialog=no
CloseApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "portuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Messages]
english.WelcomeLabel2=This will install [name/ver] on your computer.%n%nCity Tracker is a personal map of everywhere you have been. It runs entirely on this computer and needs no account. Everything it needs — including Python — is included, so there is nothing else to install.
portuguese.WelcomeLabel2=Isto vai instalar o [name/ver] no seu computador.%n%nO City Tracker é um mapa pessoal de todos os lugares onde você já esteve. Funciona somente neste computador e não precisa de conta. Tudo o que ele precisa — inclusive o Python — já está incluído, então não há mais nada para instalar.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "icon.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
; runminimized sends the launcher window straight to the taskbar. It still
; exists, because it is the only way to quit and the only place a failed start
; is reported - pythonw.exe would remove it entirely, but input() raises
; RuntimeError with no console and hold_open() catches only EOFError, so every
; error path would die silently.
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: """{app}\app\launcher.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; Comment: "Your personal map of everywhere you have been"; Flags: runminimized
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Parameters: """{app}\app\launcher.py"""; WorkingDir: "{app}\app"; IconFilename: "{app}\icon.ico"; Comment: "Your personal map of everywhere you have been"; Tasks: desktopicon; Flags: runminimized

[Run]
Filename: "{app}\{#AppExeName}"; Parameters: """{app}\app\launcher.py"""; WorkingDir: "{app}\app"; Description: "Open City Tracker now"; Flags: nowait postinstall skipifsilent runminimized

[UninstallDelete]
; Byte-code the bundled interpreter writes after installation, which is not
; part of the file list and would otherwise leave empty folders behind.
Type: filesandordirs; Name: "{app}\app\__pycache__"
Type: filesandordirs; Name: "{app}\lib"
Type: filesandordirs; Name: "{app}\python"
