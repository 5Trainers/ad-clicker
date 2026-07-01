; ============================================================================
;  installer.iss  —  Inno Setup script that turns the PyInstaller-built
;  GoogleResultClicker.exe into a proper Windows installer (Setup.exe).
;
;  The finished "GoogleResultClicker-Setup.exe" is ONE file you can share.
;  The end user double-clicks it, clicks Next a few times, and gets a Start
;  Menu / Desktop shortcut. No Python, no dependencies, nothing to configure.
;  (The target PC only needs Google Chrome installed.)
;
;  You normally do NOT run this by hand — build_installer.sh compiles it for
;  you (via Wine on Linux, or run ISCC.exe on it directly on a Windows PC after
;  producing dist\GoogleResultClicker.exe with PyInstaller).
; ============================================================================

#define MyAppName "Google Result Clicker"
#define MyAppPublisher "5Trainers"
#define MyAppExeName "GoogleResultClicker.exe"
; Version is overridden by the CI build via /DMyAppVersion=...; this is the fallback.
#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif

[Setup]
; A stable GUID so upgrades replace the previous install instead of duplicating it.
AppId={{8F3A1C7E-4B2D-4E9A-9C1F-7A2B5D6E8F01}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
; Install per-user so no admin rights are required.
PrivilegesRequired=lowest
OutputDir=installer-output
OutputBaseFilename=GoogleResultClicker-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "README.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Uninstall {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(MyAppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent
