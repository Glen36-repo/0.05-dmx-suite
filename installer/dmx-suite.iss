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
UninstallDisplayIcon={app}\0.05 DMX Suite.exe
SetupIconFile=icon.ico
CloseApplications=yes
ChangesAssociations=yes
; the show file (or an older show folder) is never removed by uninstall or upgrade

[Tasks]
Name: "claude"; Description: "Add the 0.05 tools to Claude Desktop"; GroupDescription: "Claude:"
Name: "desktopicon"; Description: "Desktop shortcut"; GroupDescription: "Shortcuts:"
Name: "startup"; Description: "Start live at login (resumes the show after a reboot)"; GroupDescription: "Gig laptop:"; Flags: unchecked

[Files]
Source: "..\dist\dmx-suite\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Registry]
; the app, Claude Desktop and the command line all use this show file (or older show folder)
Root: HKCU; Subkey: "Environment"; ValueType: string; ValueName: "DMX_SUITE_SHOWS"; ValueData: "{code:ShowsDir}"; Flags: uninsdeletevalue
; double-click a .dms show file to open it
Root: HKCU; Subkey: "Software\Classes\.dms"; ValueType: string; ValueName: ""; ValueData: "DMXSuite.Show"; Flags: uninsdeletevalue
Root: HKCU; Subkey: "Software\Classes\DMXSuite.Show"; ValueType: string; ValueName: ""; ValueData: "0.05 DMX Suite show"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\DMXSuite.Show\DefaultIcon"; ValueType: string; ValueName: ""; ValueData: "{app}\0.05 DMX Suite.exe,0"
Root: HKCU; Subkey: "Software\Classes\DMXSuite.Show\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\0.05 DMX Suite.exe"" --shows ""%1"""

[Icons]
Name: "{group}\0.05 DMX Suite"; Filename: "{app}\0.05 DMX Suite.exe"; Parameters: "--shows ""{code:ShowsDir}"""; WorkingDir: "{app}"
Name: "{group}\0.05 DMX Suite (simulator)"; Filename: "{app}\0.05 DMX Suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" --sim"; WorkingDir: "{app}"
Name: "{group}\Tools\MIDI monitor"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" midi-monitor"; WorkingDir: "{app}"
Name: "{group}\Tools\Check show files"; Filename: "{cmd}"; Parameters: "/k """"{app}\dmx-suite.exe"" --shows ""{code:ShowsDir}"" check"""; WorkingDir: "{app}"
Name: "{group}\Tools\Simulator console"; Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" run --sim"; WorkingDir: "{app}"
Name: "{group}\Show files folder"; Filename: "{code:ShowsFolder}"
Name: "{group}\Uninstall 0.05 DMX Suite"; Filename: "{uninstallexe}"
Name: "{autodesktop}\0.05 DMX Suite"; Filename: "{app}\0.05 DMX Suite.exe"; Parameters: "--shows ""{code:ShowsDir}"""; WorkingDir: "{app}"; Tasks: desktopicon
Name: "{userstartup}\0.05 DMX Suite"; Filename: "{app}\0.05 DMX Suite.exe"; Parameters: "--shows ""{code:ShowsDir}"""; WorkingDir: "{app}"; Tasks: startup

[Run]
; creates the show file from the starter shows (left alone if it already exists)
Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" check"; Flags: runhidden; StatusMsg: "Setting up show files..."
Filename: "{app}\dmx-suite.exe"; Parameters: "--shows ""{code:ShowsDir}"" claude-setup"; Flags: runhidden; StatusMsg: "Adding the 0.05 tools to Claude Desktop..."; Tasks: claude
Filename: "{app}\0.05 DMX Suite.exe"; Parameters: "--shows ""{code:ShowsDir}"""; Description: "Open 0.05 DMX Suite now"; Flags: postinstall nowait skipifsilent

[Code]
var
  ShowsPage: TInputFileWizardPage;

function DefaultShowsDir(): String;
begin
  { keep the show file (or folder) from a previous install }
  if RegQueryStringValue(HKCU, 'Environment', 'DMX_SUITE_SHOWS', Result) and (Result <> '') then
    exit;
  { SCOPE: show files live in the OneDrive Music folder, next to the Daslight files }
  if GetEnv('OneDrive') <> '' then
    Result := AddBackslash(GetEnv('OneDrive')) + 'Music\0.05 DMX Suite\0.05 shows.dms'
  else
    Result := ExpandConstant('{userdocs}\0.05 DMX Suite\0.05 shows.dms');
end;

procedure InitializeWizard();
begin
  ShowsPage := CreateInputFilePage(wpSelectDir, 'Show file',
    'Which show file should the app open?',
    'The whole show (scenes, shows, setlists, rigs, MIDI map) is kept in one .dms file. An existing file ' +
    '(or show folder from an older version) is used as is; a new one starts from the starter shows. ' +
    'Uninstalling leaves it alone.');
  ShowsPage.Add('Show file:', 'Show files (*.dms)|*.dms|All files|*.*', '.dms');
  ShowsPage.IsSaveButton[0] := True;
  ShowsPage.Values[0] := DefaultShowsDir();
end;

function ShowsDir(Param: String): String;
begin
  Result := ShowsPage.Values[0];
end;

function ShowsFolder(Param: String): String;
begin
  { the folder holding the show file, or the show folder itself }
  if CompareText(ExtractFileExt(ShowsPage.Values[0]), '.dms') = 0 then
    Result := ExtractFileDir(ShowsPage.Values[0])
  else
    Result := ShowsPage.Values[0];
end;
