; RigPanel setup .exe (Inno Setup 6). Built by installers/build-windows.sh, which passes:
;   /DAppVer=1.5.0  /DStage=<folder with python\ and app\>  /DRoot=<project folder>
; Per-user install with its own embedded Python; settings stay in %APPDATA%\RigPanel.

#define App "RigPanel"

[Setup]
AppId={{6B0C2E52-6F7B-4E7C-9C1E-2B5A4F9A7D31}
AppName={#App}
AppVersion={#AppVer}
AppVerName={#App} {#AppVer}
AppPublisher=KJ5JDO
AppPublisherURL=https://github.com/GUAC88/RigPanel
AppSupportURL=https://github.com/GUAC88/RigPanel/issues
DefaultDirName={localappdata}\Programs\{#App}
DefaultGroupName={#App}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename={#App}-{#AppVer}-Setup
SetupIconFile={#Root}\app\rigpanel.ico
UninstallDisplayIcon={app}\app\rigpanel.ico
UninstallDisplayName={#App}
LicenseFile={#Root}\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Types]
Name: "full"; Description: "RigPanel with the Net log add-on"
Name: "compact"; Description: "RigPanel only"
Name: "custom"; Description: "Choose"; Flags: iscustom

[Components]
Name: "main"; Description: "RigPanel"; Types: full compact custom; Flags: fixed
Name: "netlog"; Description: "Net log add-on (log net check-ins; export to PDF / Word with your letterhead)"; Types: full

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"
Name: "startup"; Description: "Start RigPanel in the background when I log in"

[Files]
Source: "{#Stage}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion; Components: main
Source: "{#Stage}\app\*"; DestDir: "{app}\app"; Excludes: "index-net.html,netlogcore.py,netexport.py"; Flags: ignoreversion; Components: main
Source: "{#Stage}\app\index-net.html"; DestDir: "{app}\app"; Flags: ignoreversion; Components: netlog
Source: "{#Stage}\app\netlogcore.py"; DestDir: "{app}\app"; Flags: ignoreversion; Components: netlog
Source: "{#Stage}\app\netexport.py"; DestDir: "{app}\app"; Flags: ignoreversion; Components: netlog

[InstallDelete]
; an older zip/PowerShell install (1.4 and earlier): its program files and shortcuts (settings in %APPDATA% are kept)
Type: filesandordirs; Name: "{localappdata}\RigPanel"
Type: filesandordirs; Name: "{userprograms}\RigPanel"
Type: files; Name: "{userdesktop}\* Rig Panel.lnk"
Type: files; Name: "{userstartup}\RigPanel.lnk"
; the add-on was unticked on an upgrade: take its files away (saved logs are in %APPDATA% and are kept)
Type: files; Name: "{app}\app\index-net.html"; Check: not WizardIsComponentSelected('netlog')
Type: files; Name: "{app}\app\netlogcore.py"; Check: not WizardIsComponentSelected('netlog')
Type: files; Name: "{app}\app\netexport.py"; Check: not WizardIsComponentSelected('netlog')

[Icons]
Name: "{autoprograms}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" rigpanel"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\rigpanel.ico"; Comment: "Control your ham radio"
Name: "{autodesktop}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" rigpanel"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\rigpanel.ico"; Comment: "Control your ham radio"; Tasks: desktopicon
Name: "{userstartup}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" rigpanel --no-browser"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\rigpanel.ico"; Tasks: startup

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" rigpanel"; WorkingDir: "{app}\app"; Description: "Open RigPanel now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: """{app}\app\stop.py"" rigpanel"; Flags: runhidden; RunOnceId: "StopRigPanel"

[UninstallDelete]
; anything Python left in the program folder (settings and logs live in %APPDATA% and are kept)
Type: filesandordirs; Name: "{app}"

[Code]
var
  StationPage: TInputQueryWizardPage;

function ConfigFile: String;
begin
  Result := ExpandConstant('{userappdata}\RigPanel\config.json');
end;

procedure InitializeWizard;
begin
  StationPage := CreateInputQueryPage(wpSelectComponents, 'Your station',
    'Your callsign goes on the display and is the default net control.',
    'The grid square is optional: it is used for distances and to find your local NOAA weather radio station. ' +
    'You can leave both blank and fill them in when RigPanel first opens.');
  StationPage.Add('Callsign:', False);
  StationPage.Add('Grid square (e.g. EM26av):', False);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { already set up on this computer: keep those settings }
  Result := (PageID = StationPage.ID) and FileExists(ConfigFile);
end;

function LooksLikeCall(S: String): Boolean;
var
  I, Digits: Integer;
begin
  Result := (Length(S) >= 3) and (Length(S) <= 7);
  Digits := 0;
  for I := 1 to Length(S) do
  begin
    if (S[I] >= '0') and (S[I] <= '9') then Digits := Digits + 1
    else if not ((S[I] >= 'A') and (S[I] <= 'Z')) then Result := False;
  end;
  Result := Result and (Digits >= 1);
end;

function LooksLikeGrid(S: String): Boolean;
var
  U: String;
begin
  U := Uppercase(S);
  Result := ((Length(U) = 4) or (Length(U) = 6)) and (U[1] >= 'A') and (U[1] <= 'R') and (U[2] >= 'A') and (U[2] <= 'R') and
            (U[3] >= '0') and (U[3] <= '9') and (U[4] >= '0') and (U[4] <= '9');
  if Result and (Length(U) = 6) then
    Result := (U[5] >= 'A') and (U[5] <= 'X') and (U[6] >= 'A') and (U[6] <= 'X');
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  Call, Grid: String;
begin
  Result := True;
  if CurPageID = StationPage.ID then
  begin
    Call := Uppercase(Trim(StationPage.Values[0]));
    Grid := Trim(StationPage.Values[1]);
    StationPage.Values[0] := Call;
    if (Call <> '') and not LooksLikeCall(Call) then
    begin
      MsgBox('"' + Call + '" doesn''t look like a callsign. Fix it, or leave it blank to set it later.', mbError, MB_OK);
      Result := False;
    end
    else if (Grid <> '') and not LooksLikeGrid(Grid) then
    begin
      MsgBox('"' + Grid + '" isn''t a grid square (like EM26 or EM26av). Fix it, or leave it blank.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Code: Integer;
begin
  { an upgrade (this installer or an older zip/PowerShell install): stop the running copy, which holds its files open }
  ExtractTemporaryFile('stop.py');
  Exec('cmd.exe', '/c where py >nul 2>nul && py -3 "' + ExpandConstant('{tmp}\stop.py') + '" rigpanel', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if FileExists(ExpandConstant('{app}\python\python.exe')) then
    Exec(ExpandConstant('{app}\python\python.exe'), '"' + ExpandConstant('{tmp}\stop.py') + '" rigpanel', '', SW_HIDE, ewWaitUntilTerminated, Code);
  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Call, Grid: String;
begin
  if (CurStep = ssPostInstall) and not FileExists(ConfigFile) then
  begin
    Call := Uppercase(Trim(StationPage.Values[0]));
    Grid := Trim(StationPage.Values[1]);
    if Call = '' then Call := 'N0CALL';
    ForceDirectories(ExtractFileDir(ConfigFile));
    SaveStringToFile(ConfigFile, '{' + #13#10 +
      '  "callsign": "' + Call + '",' + #13#10 +
      '  "grid": "' + Grid + '",' + #13#10 +
      '  "serial_port": "",' + #13#10 +
      '  "baud": 38400,' + #13#10 +
      '  "http_port": 8073,' + #13#10 +
      '  "winlink_freq": 145030000' + #13#10 + '}' + #13#10, False);
  end;
end;

[Files]
; stop.py is also needed by setup itself before the files are copied (see PrepareToInstall)
Source: "{#Stage}\app\stop.py"; Flags: dontcopy
