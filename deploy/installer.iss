#ifndef ReleaseVersion
  #error ReleaseVersion es obligatorio
#endif
#ifndef PayloadDir
  #error PayloadDir es obligatorio
#endif
#ifndef OutputDir
  #error OutputDir es obligatorio
#endif

[Setup]
AppId={{0CDAF997-9472-45F7-B8F7-2D655B6921A2}
AppName=EVA PDF Enterprise
AppVersion={#ReleaseVersion}
DefaultDirName={localappdata}\EVA-PDF-Enterprise
DefaultGroupName=EVA PDF Enterprise
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=EVA-PDF-Enterprise-Setup-{#ReleaseVersion}-win-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\EVA-PDF.exe
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EVA PDF Enterprise - servidor local"; Filename: "{app}\EVA-PDF.exe"; Parameters: "--host 127.0.0.1"; WorkingDir: "{app}"
Name: "{group}\Abrir EVA PDF Enterprise en navegador"; Filename: "http://127.0.0.1:8090/"

[Run]
Filename: "{app}\EVA-PDF.exe"; Parameters: "--host 127.0.0.1"; Description: "Iniciar servidor local EVA PDF Enterprise"; Flags: postinstall nowait skipifsilent unchecked
