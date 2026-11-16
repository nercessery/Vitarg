[Setup]
AppName=Vitarg
AppVersion=1.0.3.2
DefaultDirName={autopf}\Vitarg
DefaultGroupName=Vitarg
OutputDir=..\dist
OutputBaseFilename=Vitarg-Setup
Compression=lzma2/max
SolidCompression=yes
SetupIconFile=..\assets\vitarg.ico
UninstallDisplayIcon={app}\Vitarg.exe
UninstallDisplayName=Vitarg
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=yes
CloseApplicationsFilter=Vitarg.exe

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Vitarg\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion
Source: "..\assets\vitarg.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "..\assets\vitarg.png"; DestDir: "{app}\assets"; Flags: ignoreversion

[Icons]
Name: "{group}\Vitarg"; Filename: "{app}\Vitarg.exe"; IconFilename: "{app}\assets\vitarg.ico"
Name: "{group}\Uninstall Vitarg"; Filename: "{uninstallexe}"
Name: "{autostartmenu}\Vitarg"; Filename: "{app}\Vitarg.exe"; IconFilename: "{app}\assets\vitarg.ico"
Name: "{autodesktop}\Vitarg"; Filename: "{app}\Vitarg.exe"; IconFilename: "{app}\assets\vitarg.ico"; Tasks: desktopicon

[Run]
Filename: "{app}\Vitarg.exe"; Description: "Start Vitarg"; Flags: nowait postinstall skipifsilent
