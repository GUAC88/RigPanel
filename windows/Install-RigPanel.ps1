# RigPanel installer for Windows 10/11 - browser control panel for CAT-controlled ham radios.
# Installs for the current user only. Run via Install-RigPanel.bat (double-click).
#   -Reconfigure   re-run the setup questions on an existing install
#   -NetLog / -NoNetLog   install (or leave out) the Net log add-on without being asked
param([switch]$Reconfigure, [switch]$NetLog, [switch]$NoNetLog)
$ErrorActionPreference = 'Stop'
$Version = '1.5.0'

$Src     = Join-Path (Split-Path -Parent $PSScriptRoot) 'app'
$AppDir  = Join-Path $env:LOCALAPPDATA 'RigPanel'
$CfgDir  = Join-Path $env:APPDATA 'RigPanel'
$Cfg     = Join-Path $CfgDir 'config.json'
$Menu    = Join-Path ([Environment]::GetFolderPath('Programs')) 'RigPanel'
$Startup = [Environment]::GetFolderPath('Startup')

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [X]  $m" -ForegroundColor Red; Read-Host '  Press Enter to close'; exit 1 }
function Ask($q, $def) {
    $r = if ($def) { Read-Host "  $q [$def]" } else { Read-Host "  $q" }
    if ([string]::IsNullOrWhiteSpace($r)) { $def } else { $r.Trim() }
}
function Write-Utf8NoBom($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }

Write-Host "`nRigPanel $Version installer - ham radio control panel`n" -ForegroundColor Cyan
if (-not (Test-Path $Src)) { Fail "Can't find the app folder next to the windows folder." }

# --- Python ---------------------------------------------------------------------
function Find-Python {
    foreach ($c in @('py -3', 'python')) {
        $exe, $arg = $c -split ' ', 2
        try {
            $p = & $exe $arg -c "import sys; print(sys.executable) if sys.version_info >= (3,8) else None" 2>$null
            if ($p -and (Test-Path $p) -and $p -notmatch 'WindowsApps') { return $p.Trim() }
        } catch {}
    }
    return $null
}
$Py = Find-Python
if (-not $Py) {
    Warn 'Python 3.8+ was not found.'
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        if ((Ask 'Install Python 3.12 now with winget? (y/n)' 'y') -match '^[Yy]') {
            winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
            $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
            $Py = Find-Python
        }
    }
    if (-not $Py) { Fail 'Install Python from https://www.python.org/downloads/ (tick "Add python.exe to PATH"), then run this again.' }
}
$PyW = Join-Path (Split-Path $Py) 'pythonw.exe'
if (-not (Test-Path $PyW)) { $PyW = $Py }
Info "Python: $Py"

& $Py -m pip install --user --quiet --disable-pip-version-check pyserial
if ($LASTEXITCODE -ne 0) { Fail 'Could not install pyserial (pip install --user pyserial).' }
Info 'pyserial installed'

# --- Setup questions -----------------------------------------------------------------
if ((Test-Path $Cfg) -and -not $Reconfigure) {
    Info "Keeping existing settings in $Cfg (run with -Reconfigure to change them)"
} else {
    Write-Host "`nStation setup" -ForegroundColor Cyan
    do {
        $Call = (Ask 'Your callsign' '').ToUpper()
        $ok = $Call -match '^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$'
        if (-not $ok) { Warn "`"$Call`" doesn't look like a callsign, try again" }
    } until ($ok)

    $GridGuess = ''
    try {
        $r = Invoke-RestMethod "https://callook.info/$Call/json" -TimeoutSec 8 -UserAgent 'RigPanel-installer'
        if ($r.status -eq 'VALID') { $GridGuess = $r.location.gridsquare; Info "Found $Call in the FCC database (grid $GridGuess)" }
    } catch {}
    do {
        $Grid = Ask 'Grid square (Maidenhead, e.g. EM25fs)' $GridGuess
        $ok = (-not $Grid) -or ($Grid -match '^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$')
        if (-not $ok) { Warn 'Invalid grid square, try again' }
    } until ($ok)

    # Yaesu radios with a CP210x bridge show two COM ports (CAT is the "Enhanced" one); Icom radios show one
    $ports = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
             Where-Object { $_.Name -match '\((COM\d+)\)' } | ForEach-Object { $_.Name }
    $enh = $ports | Where-Object { $_ -match 'Enhanced|Icom|IC-\d' } | Select-Object -First 1
    if ($ports) { Write-Host '  Serial ports found:'; $ports | ForEach-Object { Write-Host "    $_" } }
    $def = if ($enh -match '\((COM\d+)\)') { $Matches[1] } else { '' }
    if (-not $ports) {
        Warn 'No COM ports found. Plug in the radio, turn it on, and install its USB driver if needed (Yaesu / IC-7300: Silicon Labs CP210x):'
        Warn '  https://www.silabs.com/developers/usb-to-uart-bridge-vcp-drivers'
    } elseif ($def) { Info "Radio CAT port looks like $def" }
    $Port = (Ask 'Radio CAT COM port (blank = auto-detect at startup)' $def).ToUpper()

    $baudDef = if ($enh -match 'Icom|IC-\d') { '115200' } else { '38400' }
    do { $Baud = Ask 'Radio CAT baud rate (Yaesu FT-991A: MENU 031, Icom: CI-V USB Baud Rate)' $baudDef } until ($Baud -in @('4800', '9600', '19200', '38400', '57600', '115200'))
    do {
        $Wl = Ask 'Your local Winlink VARA FM frequency in MHz' '145.030'
        $WlHz = 0; $ok = [double]::TryParse($Wl, [Globalization.NumberStyles]::Float, [Globalization.CultureInfo]::InvariantCulture, [ref]$WlHz)
    } until ($ok)
    do { $HttpPort = Ask 'Web port for the panel' '8073' } until ($HttpPort -match '^\d{4,5}$')

    New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null
    $json = [ordered]@{
        callsign = $Call; grid = $Grid; serial_port = $Port; baud = [int]$Baud
        http_port = [int]$HttpPort; winlink_freq = [long][math]::Round($WlHz * 1e6)
    } | ConvertTo-Json
    Write-Utf8NoBom $Cfg $json
    Info "Saved settings to $Cfg"
}
$conf = Get-Content $Cfg -Raw | ConvertFrom-Json
$HttpPort = if ($conf.http_port) { $conf.http_port } else { 8073 }

# --- Winlink / VARA FM -------------------------------------------------------------
# Windows lets only one program open a COM port: VARA keying the radio by CAT on RigPanel's port breaks one of them
$ports = Get-CimInstance Win32_PnPEntity -ErrorAction SilentlyContinue |
         Where-Object { $_.Name -match '\((COM\d+)\)' } | ForEach-Object { $_.Name }
$catPort = "$($conf.serial_port)".ToUpper()
if (-not $catPort -and ($ports | Where-Object { $_ -match 'Enhanced|Icom|IC-\d' } | Select-Object -First 1) -match '\((COM\d+)\)') { $catPort = $Matches[1] }
$stdPort = if (($ports | Where-Object { $_ -match 'Standard' } | Select-Object -First 1) -match '\((COM\d+)\)') { $Matches[1] } else { '' }
$varaIni = @('C:\VARA FM', "$env:ProgramFiles\VARA FM", "${env:ProgramFiles(x86)}\VARA FM") |
           ForEach-Object { Join-Path $_ 'VARAFM.ini' } | Where-Object { Test-Path $_ } | Select-Object -First 1
Write-Host "`nWinlink / VARA FM" -ForegroundColor Cyan
if ($varaIni) {
    $vara = @{}
    Get-Content $varaIni -ErrorAction SilentlyContinue | Where-Object { $_ -match '^\s*(CATPort|PTTPort)\s*=\s*(\S*)' } |
        ForEach-Object { if (-not $vara[$Matches[1]]) { $vara[$Matches[1]] = $Matches[2].ToUpper() } }
    if ($catPort -and $vara.CATPort -eq $catPort) {
        Warn "VARA FM is set to use $catPort for CAT, the same port as RigPanel. Windows lets only one program open it,"
        Warn '  so either VARA can''t transmit or RigPanel loses the radio. In VARA FM: Settings > PTT, choose'
        Warn "  $(if ($stdPort) { $stdPort } else { 'the radio''s Standard COM port' }) and RTS (or VOX)."
    } else { Info "VARA FM found ($varaIni)" }
}
$pttTip = if ($stdPort) { "$stdPort (the radio's Standard port)" } else { "the radio's Standard COM port (not $(if ($catPort) { $catPort } else { 'the CAT port' }))" }
Write-Host "  For Winlink, set VARA FM's sound card to the radio's USB Audio CODEC (input and output),"
Write-Host "  and its PTT to $pttTip with RTS. On the FT-991A also set MENU 076 FM PKT PTT SELECT = RTS."

# --- Optional add-on: Net log --------------------------------------------------------
$NetLogFiles = @('index-net.html', 'netlogcore.py', 'netexport.py')
if ($NetLog) { $WantNetLog = $true }
elseif ($NoNetLog) { $WantNetLog = $false }
else {
    Write-Host "`nAdd-ons" -ForegroundColor Cyan
    Write-Host '  Net log: log check-ins when you run a net (FCC name/location lookup, traffic and short-time flags),'
    Write-Host '  then export to PDF or Word with your club''s letterhead, or CSV. Opens from a button in the panel.'
    $def = if ((Test-Path $AppDir) -and -not (Test-Path (Join-Path $AppDir 'netlogcore.py'))) { 'n' } else { 'y' }   # keep an earlier choice
    $WantNetLog = (Ask 'Install the Net log add-on? (y/n)' $def) -match '^[Yy]'
}

# --- Install files --------------------------------------------------------------------
Write-Host "`nInstalling" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*RigPanel*rigpanel.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
foreach ($f in @('rigpanel.py', 'radios.py', 'index.html', 'menus.json', 'nwr.json', 'rigpanel.svg', 'rigpanel.ico')) {
    Copy-Item -Force (Join-Path $Src $f) $AppDir
}
foreach ($f in $NetLogFiles) {
    if ($WantNetLog) { Copy-Item -Force (Join-Path $Src $f) $AppDir }
    else { Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $AppDir $f) }
}
if ($WantNetLog) { Info "Net log add-on installed (Net log button in the panel; logs kept in $CfgDir\netlogs)" }
else { Info 'Net log add-on not installed (your saved net logs, if any, are kept)' }
Copy-Item -Force (Join-Path $PSScriptRoot 'Uninstall-RigPanel.ps1') $AppDir
Write-Utf8NoBom (Join-Path $AppDir 'VERSION') $Version
Info "App files -> $AppDir"

# Launcher: start the panel hidden if it isn't running, then open the browser
$launcher = @"
`$port = $HttpPort
try { Invoke-WebRequest "http://localhost:`$port/api/config" -UseBasicParsing -TimeoutSec 1 | Out-Null }
catch {
    Start-Process -FilePath '$PyW' -ArgumentList '"$AppDir\rigpanel.py"' -WindowStyle Hidden
    for (`$i = 0; `$i -lt 30; `$i++) {
        Start-Sleep -Milliseconds 300
        try { Invoke-WebRequest "http://localhost:`$port/api/config" -UseBasicParsing -TimeoutSec 1 | Out-Null; break } catch {}
    }
}
Start-Process "http://localhost:`$port"
"@
Write-Utf8NoBom (Join-Path $AppDir 'Launch-RigPanel.ps1') $launcher

$ws = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $target, $arguments, $desc) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $target; $s.Arguments = $arguments; $s.Description = $desc
    $s.WorkingDirectory = $AppDir; $s.IconLocation = (Join-Path $AppDir 'rigpanel.ico'); $s.WindowStyle = 7
    $s.Save()
}
New-Item -ItemType Directory -Force -Path $Menu | Out-Null
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$launchArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$AppDir\Launch-RigPanel.ps1`""
New-Shortcut (Join-Path $Menu "$($conf.callsign) Rig Panel.lnk") $ps $launchArgs 'Control your ham radio'
New-Shortcut (Join-Path $Menu 'Uninstall RigPanel.lnk') $ps "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\Uninstall-RigPanel.ps1`"" 'Remove RigPanel'
New-Shortcut ([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), "$($conf.callsign) Rig Panel.lnk")) $ps $launchArgs 'Control your ham radio'
Info "Start Menu + Desktop shortcut: `"$($conf.callsign) Rig Panel`""

if ((Ask 'Start the panel automatically when you log in? (y/n)' 'y') -match '^[Yy]') {
    New-Shortcut (Join-Path $Startup 'RigPanel.lnk') $PyW "`"$AppDir\rigpanel.py`"" 'RigPanel background service'
    Info 'Will start at login'
}

# --- Start and check ---------------------------------------------------------------
Start-Process -FilePath $PyW -ArgumentList "`"$AppDir\rigpanel.py`"" -WindowStyle Hidden
$up = $false
for ($i = 0; $i -lt 30 -and -not $up; $i++) {
    Start-Sleep -Milliseconds 300
    try { $st = Invoke-RestMethod "http://localhost:$HttpPort/api/status" -TimeoutSec 5; $up = $true } catch {}
}
Write-Host ''
if (-not $up) { Warn "The panel didn't start. Try running: `"$Py`" `"$AppDir\rigpanel.py`" to see the error." }
elseif ($st.ok) { Info 'Connected to the radio' }
else { Warn "Panel is running but the radio isn't answering (check USB cable, power, COM port and baud rate $($conf.baud); or open Radio setup in the panel)" }

Write-Host "`nDone! Open `"$($conf.callsign) Rig Panel`" from the Start Menu or Desktop, or visit http://localhost:$HttpPort" -ForegroundColor Cyan
Write-Host '  Change settings later: run Install-RigPanel.bat again and choose to reconfigure, or use -Reconfigure.'
if ((Ask 'Open it now? (y/n)' 'y') -match '^[Yy]') { Start-Process "http://localhost:$HttpPort" }
