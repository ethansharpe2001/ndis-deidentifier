; Inno Setup script for the NDIS Behaviour Support Plan De-identifier.
;
; Built from CI (windows-latest ships Inno Setup preinstalled) right after
; the PyInstaller onedir build, via:
;
;   iscc packaging\installer.iss
;
; This exists to remove the manual "download a zip, extract it somewhere,
; hope you picked a short enough path" step entirely - a real installer
; controls the install location, defaulting to somewhere already known to
; leave plenty of headroom under Windows' 260-character path limit (see the
; contents_directory comment in presidio_deid.spec for why that limit
; matters here). Installing under the user's own profile (rather than
; Program Files) also means no admin rights are required.
#define AppName "NDIS Behaviour Support Plan De-identifier"
#define AppVersion "1.0.0"
#define AppExeName "NDIS-Deidentifier.exe"
#define SourceDir "..\dist\NDIS-Deidentifier"

[Setup]
AppId={{B7B6E3B0-6E3E-4C8B-9B0A-2B7B6E3B0A1D}
AppName={#AppName}
AppVersion={#AppVersion}
DefaultDirName={localappdata}\NDIS-Deidentifier
DefaultGroupName=NDIS De-identifier
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\dist\installer
OutputBaseFilename=NDIS-Deidentifier-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
