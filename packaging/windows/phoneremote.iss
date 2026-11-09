; Inno Setup script for the Windows installer. Built by packaging/build.py,
; which passes /DAppVersion=... and /DSourceDir=... (the PyInstaller output).

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\..\dist\PhoneRemote"
#endif

[Setup]
AppId={{6B0F2C7E-5D1A-4C1E-9E2B-50A7F0E1C0DE}
AppName=Phone Remote
AppVersion={#AppVersion}
AppPublisher=Phone Remote
DefaultDirName={autopf}\Phone Remote
DefaultGroupName=Phone Remote
DisableProgramGroupPage=yes
OutputDir=..\..\dist
OutputBaseFilename=PhoneRemote-{#AppVersion}-windows-setup
SetupIconFile=..\icons\phoneremote.ico
UninstallDisplayIcon={app}\PhoneRemote.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
; Administrator rights are needed to add the firewall rule that lets phones connect.
PrivilegesRequired=admin

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"
Name: "startup"; Description: "Start Phone Remote when I sign in"; GroupDescription: "Other:"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Phone Remote"; Filename: "{app}\PhoneRemote.exe"
Name: "{autodesktop}\Phone Remote"; Filename: "{app}\PhoneRemote.exe"; Tasks: desktopicon
Name: "{userstartup}\Phone Remote"; Filename: "{app}\PhoneRemote.exe"; Tasks: startup

[Run]
; Allow phones on private (home/work) networks to reach the app, so users never
; see a firewall prompt. Public networks (cafes, hotels) stay blocked.
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Phone Remote"""; Flags: runhidden
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall add rule name=""Phone Remote"" dir=in action=allow program=""{app}\PhoneRemote.exe"" enable=yes profile=private"; Flags: runhidden
Filename: "{app}\PhoneRemote.exe"; Description: "Start Phone Remote now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im PhoneRemote.exe"; Flags: runhidden; RunOnceId: "StopApp"
Filename: "{sys}\netsh.exe"; Parameters: "advfirewall firewall delete rule name=""Phone Remote"""; Flags: runhidden; RunOnceId: "RemoveFirewallRule"
