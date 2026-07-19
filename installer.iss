; Voxxwire Installer Script

[Setup]
AppName=Voxxwire
AppVersion=1.4.0
AppPublisher=Jay Parmar and Raj Prajapati
AppPublisherURL=https://github.com/raj20023/voxxwire
DefaultDirName={autopf}\Voxxwire
DefaultGroupName=Voxxwire
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=Voxxwire-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create desktop shortcut"

[Files]
Source: "dist\Voxxwire\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Voxxwire"; Filename: "{app}\Voxxwire.exe"
Name: "{autodesktop}\Voxxwire"; Filename: "{app}\Voxxwire.exe"; Tasks: desktopicon
Name: "{group}\Uninstall Voxxwire"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\Voxxwire.exe"; Description: "Launch Voxxwire"; Flags: nowait postinstall skipifsilent
