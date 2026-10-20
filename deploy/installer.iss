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
AppName=Folio PDF
AppVersion={#ReleaseVersion}
DefaultDirName={localappdata}\Folio-PDF
DefaultGroupName=Folio PDF
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#OutputDir}
OutputBaseFilename=Folio-Setup-{#ReleaseVersion}-win-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\Folio.exe
SetupLogging=yes

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Files]
Source: "{#PayloadDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Folio PDF - servidor local"; Filename: "{app}\Folio.exe"; Parameters: "--host 127.0.0.1"; WorkingDir: "{app}"
Name: "{group}\Abrir Folio en navegador"; Filename: "http://127.0.0.1:8090/"

[Run]
Filename: "{app}\Folio.exe"; Parameters: "--host 127.0.0.1"; Description: "Iniciar servidor local Folio"; Flags: postinstall nowait skipifsilent unchecked
