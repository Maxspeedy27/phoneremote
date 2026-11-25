; Inno Setup script for the Windows installer. Built by packaging/build.py,
; which passes /DAppVersion=... and /DSourceDir=... (the PyInstaller output).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\Kumpas"
#endif

[Setup]
AppId={{6B0F2C7E-5D1A-4C1E-9E2B-50A7F0E1C0DE}
AppName=Kumpas
AppVersion={#AppVersion}
AppPublisher=Kumpas
DefaultDirName={autopf}\Kumpas
DefaultGroupName=Kumpas
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=Kumpas-{#AppVersion}-windows-setup
SetupIconFile=..\icons\kumpas.ico
UninstallDisplayIcon={app}\Kumpas.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Administrator rights are needed to add the firewall rule that lets phones connect.
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Kumpas when I sign in"; GroupDescription: "Other:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\..\LICENSE"; DestDir: "{app}"; DestName: "LICENSE.txt"; Flags: ignoreversion

[Icons]
Name: "{group}\Kumpas"; Filename: "{app}\Kumpas.exe"
Name: "{autodesktop}\Kumpas"; Filename: "{app}\Kumpas.exe"; Tasks: desktopicon
Name: "{userstartup}\Kumpas"; Filename: "{app}\Kumpas.exe"; Tasks: startup

[Run]
; Allow phones on private (home/work) networks to reach the app, so users never
; see a firewall prompt. Public networks (cafes, hotels) stay blocked.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Kumpas"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Kumpas"" dir=in action=allow program=""{app}\Kumpas.exe"" enable=yes profile=private"; Flags: runhidden
Filename: "{app}\Kumpas.exe"; Description: "Start Kumpas now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im Kumpas.exe"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Kumpas"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
