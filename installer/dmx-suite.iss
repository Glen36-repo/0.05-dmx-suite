; Inno Setup script for the 0.05 DMX Suite Windows installer.
; Build after PyInstaller (see installer/build.ps1):
;   iscc /DAppVersion=0.1.0 installer\dmx-suite.iss

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6E3C1B52-0D5A-4F7B-9C61-005D4A1E0505}
AppName=0.05 DMX Suite
AppVersion={#AppVersion}
AppPublisher=0.05
DefaultDirName={autopf}\0.05 DMX Suite
DefaultGroupName=0.05 DMX Suite
DisableProgramGroupPage=yes
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
ChangesEnvironment=yes
OutputDir=..\dist
OutputBaseFilename=0.05-DMX-Suite-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\dmx-suite.exe
; the show folder is never removed by uninstall or upgrade

[Tasks]
Name: "claude"; Description: "Add the 0.05 tools to Claude Desktop"; GroupDescription: "Claude:"
Name: "desktopicon"; Description: "Desktop shortcut (live)"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start live at login (resumes the show after a reboot)"; GroupDescription: "Gig laptop:"; Flags: unchecked

[Files]
Source: "..\dist\dmx-suite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; the app, Claude Desktop and the command line all use this show folder
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "DMX_SUITE_SHOWS"; ValueData: "{code:ShowsDir}"; Flags: uninsdeletevalue

[Icons]
Name: "{group}\0.05 DMX Suite (live)"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --rig full"; WorkingDir: "{app}"
Name: "{group}\0.05 DMX Suite (simulator)"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --sim"; WorkingDir: "{app}"
Name: "{group}\MIDI monitor"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" midi-monitor"; WorkingDir: "{app}"
Name: "{group}\Check show files"; Filename: "{cmd}"; Parameters: "/k """"{app}\dmx-suite.exe"" --shows ""{code:ShowsDir}"" check"""; WorkingDir: "{app}"
Name: "{group}\Open lighting UI"; Filename: "http://localhost:8505/"
Name: "{group}\Show files folder"; Filename: "{code:ShowsDir}"
Name: "{group}\Uninstall 0.05 DMX Suite"; Filename: "{uninstallexe}"
Name: "{autodesktop}\0.05 DMX Suite"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --rig full"; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\0.05 DMX Suite"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --rig full"; WorkingDir: "{app}"; Tasks: startup

[Run]
; creates the show folder from the starter shows (left alone if it already exists)
Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" check"; Flags: runhidden; StatusMsg: "Setting up show files..."
Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" claude-setup"; Flags: runhidden; StatusMsg: "Adding the 0.05 tools to Claude Desktop..."; Tasks: claude
Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --sim"; Description: "Open the simulator now"; Flags: postinstall nowait skipifsilent unchecked

[Code]
var
  ShowsPage: TInputDirWizardPage;

function DefaultShowsDir(): String;
begin
  { keep the folder from a previous install }
  if RegQueryStringValue(HKCU, 'Environment', 'DMX_SUITE_SHOWS', Result) and (Result <> '') then
    exit;
  { SCOPE: show files live in the OneDrive Music folder, next to the Daslight files }
  if GetEnv('OneDrive') <> '' then
    Result := AddBackslash(GetEnv('OneDrive')) + 'Music\0.05 DMX Suite\shows'
  else
    Result := ExpandConstant('{userdocs}\0.05 DMX Suite\shows');
end;

procedure InitializeWizard();
begin
  ShowsPage := CreateInputDirPage(wpSelectDir, 'Show files',
    'Where should the show files live?',
    'Scenes, shows, setlists, rigs and the MIDI map are kept here. An existing folder is used as is; ' +
    'a new one is filled with the starter shows. Uninstalling leaves this folder alone.',
    False, '');
  ShowsPage.Add('');
  ShowsPage.Values[0] := DefaultShowsDir();
end;

function ShowsDir(Param: String): String;
begin
  Result := ShowsPage.Values[0];
end;
