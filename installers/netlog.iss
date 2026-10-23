; Net Log setup .exe (Inno Setup 6). Built by installers/build-windows.sh, which passes:
;   /DAppVer=1.1.0  /DStage=<folder with python\ and app\>  /DRoot=<project folder>
; Per-user install with its own embedded Python; settings and logs stay in %APPDATA%\NetLog.

#define App "Net Log"

[Setup]
AppId={{C3D9A1F4-58E2-4B6D-A0F7-91E2B7C4D650}
AppName={#App}
AppVersion={#AppVer}
AppVerName={#App} {#AppVer}
AppPublisher=KJ5JDO
AppPublisherURL=https://github.com/GUAC88/RigPanel
AppSupportURL=https://github.com/GUAC88/RigPanel/issues
DefaultDirName={localappdata}\Programs\NetLog
DefaultGroupName={#App}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputBaseFilename=NetLog-{#AppVer}-Setup
SetupIconFile={#Root}\app\netlog.ico
UninstallDisplayIcon={app}\app\netlog.ico
UninstallDisplayName={#App}
LicenseFile={#Root}\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
CloseApplications=no

[Tasks]
Name: "desktopicon"; Description: "Create a &Desktop shortcut"
Name: "startup"; Description: "Start Net Log in the background when I log in"; Flags: unchecked

[Files]
Source: "{#Stage}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion
Source: "{#Stage}\app\*"; DestDir: "{app}\app"; Flags: ignoreversion
; needed by setup itself before the files are copied (see PrepareToInstall)
Source: "{#Stage}\app\stop.py"; Flags: dontcopy

[InstallDelete]
; a Net Log 1.0 zip/PowerShell install: its program files and shortcuts (settings and logs in %APPDATA% are kept)
Type: filesandordirs; Name: "{localappdata}\NetLog"
Type: filesandordirs; Name: "{userprograms}\Net Log"
Type: files; Name: "{userstartup}\NetLog.lnk"

[Icons]
Name: "{autoprograms}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" netlog"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\netlog.ico"; Comment: "Log check-ins for ham radio nets"
Name: "{autodesktop}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" netlog"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\netlog.ico"; Comment: "Log check-ins for ham radio nets"; Tasks: desktopicon
Name: "{userstartup}\{#App}"; Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" netlog --no-browser"; WorkingDir: "{app}\app"; IconFilename: "{app}\app\netlog.ico"; Tasks: startup

[Run]
Filename: "{app}\python\pythonw.exe"; Parameters: """{app}\app\launch.py"" netlog"; WorkingDir: "{app}\app"; Description: "Open Net Log now"; Flags: postinstall nowait skipifsilent

[UninstallRun]
Filename: "{app}\python\python.exe"; Parameters: """{app}\app\stop.py"" netlog"; Flags: runhidden; RunOnceId: "StopNetLog"

[UninstallDelete]
; anything Python left in the program folder (settings and logs live in %APPDATA% and are kept)
Type: filesandordirs; Name: "{app}"

[Code]
var
  StationPage: TInputQueryWizardPage;

function ConfigFile: String;
begin
  Result := ExpandConstant('{userappdata}\NetLog\config.json');
end;

procedure InitializeWizard;
begin
  StationPage := CreateInputQueryPage(wpSelectTasks, 'Your station',
    'Your callsign is the default net control.',
    'The grid square is optional: it is used for check-in distances. You can leave both blank and fill them in when Net Log first opens.');
  StationPage.Add('Callsign:', False);
  StationPage.Add('Grid square (e.g. EM26av):', False);
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
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
  ExtractTemporaryFile('stop.py');
  Exec('cmd.exe', '/c where py >nul 2>nul && py -3 "' + ExpandConstant('{tmp}\stop.py') + '" netlog', '', SW_HIDE, ewWaitUntilTerminated, Code);
  if FileExists(ExpandConstant('{app}\python\python.exe')) then
    Exec(ExpandConstant('{app}\python\python.exe'), '"' + ExpandConstant('{tmp}\stop.py') + '" netlog', '', SW_HIDE, ewWaitUntilTerminated, Code);
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
      '  "http_port": 8075' + #13#10 + '}' + #13#10, False);
  end;
end;
