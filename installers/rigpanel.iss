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
; Winlink programs: not bundled (winlink.org serves them only to a web browser). Setup opens the download page, then runs their setup.
Name: "winlink"; Description: "Winlink Express - Winlink email client (downloaded from winlink.org)"; Check: not WinlinkInstalled
Name: "vara"; Description: "VARA FM - the sound modem Winlink uses on 2m/70cm (downloaded from winlink.org)"; Check: not VaraInstalled

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

{ --- Winlink Express and VARA FM: found in Downloads (or downloaded now in the browser), then their own setup runs --- }

function FindInstalled(Rel: String): Boolean;
begin
  Result := FileExists('C:\' + Rel) or FileExists(ExpandConstant('{commonpf32}\') + Rel) or
            FileExists(ExpandConstant('{commonpf64}\') + Rel);
end;

function WinlinkInstalled: Boolean;
begin
  Result := FindInstalled('RMS Express\RMS Express.exe');
end;

function VaraInstalled: Boolean;
begin
  Result := FindInstalled('VARA FM\VARAFM.exe');
end;

function DownloadsDir: String;
begin
  Result := ExpandConstant('{%USERPROFILE}\Downloads');
end;

{ Best becomes the newest file in Dir matching Pattern if it is newer than Best (BestHi/BestLo = Best's write time) }
procedure Newest(Dir, Pattern: String; var Best: String; var BestHi, BestLo: Cardinal);
var
  F: TFindRec;
begin
  if FindFirst(Dir + '\' + Pattern, F) then
  try
    repeat
      if (F.Attributes and FILE_ATTRIBUTE_DIRECTORY = 0) and ((Best = '') or (F.LastWriteTime.dwHighDateTime > BestHi) or
         ((F.LastWriteTime.dwHighDateTime = BestHi) and (F.LastWriteTime.dwLowDateTime > BestLo))) then
      begin
        Best := Dir + '\' + F.Name;
        BestHi := F.LastWriteTime.dwHighDateTime;
        BestLo := F.LastWriteTime.dwLowDateTime;
      end;
    until not FindNext(F);
  finally
    FindClose(F);
  end;
end;

function FindDownload(P1, P2: String): String;
var
  Hi, Lo: Cardinal;
begin
  Result := '';
  Hi := 0;
  Lo := 0;
  Newest(DownloadsDir, P1, Result, Hi, Lo);
  Newest(DownloadsDir, P2, Result, Hi, Lo);
end;

{ the setup program inside an unpacked download: prefer *setup* / *install*, and look one folder down too }
function FindSetupExe(Dir: String; Depth: Integer): String;
var
  F: TFindRec;
  Any: String;
begin
  Result := '';
  Any := '';
  if FindFirst(Dir + '\*', F) then
  try
    repeat
      if (F.Name <> '.') and (F.Name <> '..') then
      begin
        if F.Attributes and FILE_ATTRIBUTE_DIRECTORY <> 0 then
        begin
          if Depth > 0 then
          begin
            Result := FindSetupExe(Dir + '\' + F.Name, Depth - 1);
            if (Result <> '') and (Pos('SETUP', Uppercase(ExtractFileName(Result))) = 0) and
               (Pos('INSTALL', Uppercase(ExtractFileName(Result))) = 0) then
            begin
              if Any = '' then Any := Result;
              Result := '';
            end;
          end;
        end
        else if CompareText(ExtractFileExt(F.Name), '.exe') = 0 then
        begin
          if (Pos('SETUP', Uppercase(F.Name)) > 0) or (Pos('INSTALL', Uppercase(F.Name)) > 0) then Result := Dir + '\' + F.Name
          else if Any = '' then Any := Dir + '\' + F.Name;
        end;
      end;
    until (Result <> '') or not FindNext(F);
  finally
    FindClose(F);
  end;
  if Result = '' then Result := Any;
end;

{ a path inside a PowerShell '...' string: single quotes are doubled }
function PsQuote(S: String): String;
begin
  Result := S;
  StringChangeEx(Result, '''', '''''', True);
  Result := '''' + Result + '''';
end;

procedure InstallExtra(Name, Url, Hint, P1, P2: String);
var
  Download, Dir, Exe: String;
  Code: Integer;
begin
  Download := FindDownload(P1, P2);
  Log(Name + ': download in ' + DownloadsDir + ': ' + Download);
  if Download = '' then
  begin
    if MsgBox(Name + ' comes from winlink.org. Setup will open its download page in your browser.' + #13#10#13#10 +
              'Download ' + Hint + ', then come back here.', mbInformation, MB_OKCANCEL) = IDCANCEL then Exit;
    ShellExec('open', Url, '', '', SW_SHOWNORMAL, ewNoWait, Code);
    repeat
      if MsgBox('Click OK when the ' + Name + ' download has finished.' + #13#10#13#10 +
                '(Cancel skips ' + Name + '. You can install it yourself later.)', mbInformation, MB_OKCANCEL) = IDCANCEL then Exit;
      Download := FindDownload(P1, P2);
      if (Download = '') and (MsgBox('Setup can''t find the ' + Name + ' download in ' + DownloadsDir + '.' + #13#10 +
          'Do you want to find it yourself?', mbConfirmation, MB_YESNO) = IDYES) then
        if not GetOpenFileName('Find the ' + Name + ' download', Download, DownloadsDir,
                               'Zip or setup files (*.zip;*.exe)|*.zip;*.exe', 'zip') then Download := '';
    until Download <> '';
  end;

  if CompareText(ExtractFileExt(Download), '.zip') = 0 then
  begin
    Dir := ExpandConstant('{tmp}\') + Name;
    ForceDirectories(Dir);
    Exec(ExpandConstant('{sys}\WindowsPowerShell\v1.0\powershell.exe'),
         '-NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath ' + PsQuote(Download) +
         ' -DestinationPath ' + PsQuote(Dir) + ' -Force"', '', SW_HIDE, ewWaitUntilTerminated, Code);
    Exe := FindSetupExe(Dir, 1);
  end
  else
    Exe := Download;
  if Exe = '' then
  begin
    MsgBox('No setup program was found in ' + Download + '. Is the download complete? You can install ' + Name +
           ' yourself later.', mbError, MB_OK);
    Exit;
  end;
  { the vendor's own installer: it asks for administrator rights itself if it needs them }
  Log(Name + ': running ' + Exe);
  if not ShellExec('', Exe, '', ExtractFileDir(Exe), SW_SHOWNORMAL, ewWaitUntilTerminated, Code) then
    MsgBox('The ' + Name + ' setup didn''t start: ' + SysErrorMessage(Code), mbError, MB_OK);
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
  if (CurStep = ssPostInstall) and not WizardSilent then
  begin
    if WizardIsComponentSelected('vara') then
      InstallExtra('VARA FM', 'https://downloads.winlink.org/VARA%20Products/',
                   'the newest "VARA FM v... setup.zip" (not VARA HF)', 'VARA FM*.zip', 'VARA*FM*setup*.exe');
    if WizardIsComponentSelected('winlink') then
      InstallExtra('Winlink Express', 'https://downloads.winlink.org/User%20Programs/',
                   'the newest "Winlink_Express_install_....zip"', 'Winlink_Express_install*.zip', 'Winlink*Express*.zip');
  end;
end;

[Files]
; stop.py is also needed by setup itself before the files are copied (see PrepareToInstall)
Source: "{#Stage}\app\stop.py"; Flags: dontcopy
