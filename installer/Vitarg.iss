[Setup]
AppName=Vitarg
AppVersion=1.0.4
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
Name: "contextmenu"; Description: "Add 'Convert with Vitarg' to context menu (files and desktop background)"; GroupDescription: "{cm:AdditionalIcons}"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Classes\*\shell\Vitarg"; ValueType: string; ValueName: ""; ValueData: "Convert with Vitarg"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Vitarg"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Vitarg.exe"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\Vitarg\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Vitarg.exe"" ""%1"""; Tasks: contextmenu; Flags: uninsdeletekey

Root: HKCU; Subkey: "Software\Classes\Directory\shell\Vitarg"; ValueType: string; ValueName: ""; ValueData: "Convert with Vitarg"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Vitarg"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Vitarg.exe"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\Vitarg\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Vitarg.exe"" ""%1"""; Tasks: contextmenu; Flags: uninsdeletekey

Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Vitarg"; ValueType: string; ValueName: ""; ValueData: "Convert with Vitarg"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Vitarg"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Vitarg.exe"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\Background\shell\Vitarg\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Vitarg.exe"" --select ""%V"""; Tasks: contextmenu; Flags: uninsdeletekey

Root: HKCU; Subkey: "Software\Classes\DesktopBackground\shell\Vitarg"; ValueType: string; ValueName: ""; ValueData: "Convert with Vitarg"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\DesktopBackground\shell\Vitarg"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\Vitarg.exe"; Tasks: contextmenu; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\DesktopBackground\shell\Vitarg\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Vitarg.exe"" --select ""%V"""; Tasks: contextmenu; Flags: uninsdeletekey

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
