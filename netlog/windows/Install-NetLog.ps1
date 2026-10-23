# Net Log installer for Windows 10/11 - net control logger for ham radio nets (check-ins, FCC lookups,
# PDF / Word / CSV export with your letterhead). Installs for the current user only.
# Run via Install-NetLog.bat (double-click).
#   -Reconfigure   re-run the setup questions on an existing install
param([switch]$Reconfigure)
$ErrorActionPreference = 'Stop'
$Version = '1.0.0'

$Src = Join-Path (Split-Path -Parent $PSScriptRoot) 'app'
if (-not (Test-Path $Src)) { $Src = Join-Path (Split-Path -Parent (Split-Path -Parent $PSScriptRoot)) 'app' }   # inside the RigPanel source tree
$AppDir  = Join-Path $env:LOCALAPPDATA 'NetLog'
$CfgDir  = Join-Path $env:APPDATA 'NetLog'
$Cfg     = Join-Path $CfgDir 'config.json'
$Menu    = Join-Path ([Environment]::GetFolderPath('Programs')) 'Net Log'
$Startup = [Environment]::GetFolderPath('Startup')
$Files   = @('netlog.py', 'netlogcore.py', 'netexport.py', 'index-net.html', 'netlog.svg', 'netlog.ico')

function Info($m) { Write-Host "  [OK] $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [!]  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "  [X]  $m" -ForegroundColor Red; Read-Host '  Press Enter to close'; exit 1 }
function Ask($q, $def) {
    $r = if ($def) { Read-Host "  $q [$def]" } else { Read-Host "  $q" }
    if ([string]::IsNullOrWhiteSpace($r)) { $def } else { $r.Trim() }
}
function Write-Utf8NoBom($path, $text) { [IO.File]::WriteAllText($path, $text, (New-Object Text.UTF8Encoding $false)) }

Write-Host "`nNet Log $Version installer - net control logging for ham radio nets`n" -ForegroundColor Cyan
foreach ($f in $Files) { if (-not (Test-Path (Join-Path $Src $f))) { Fail "Can't find $f in the app folder ($Src)." } }

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

# --- Setup questions -----------------------------------------------------------------
if ((Test-Path $Cfg) -and -not $Reconfigure) {
    Info "Keeping existing settings in $Cfg (run with -Reconfigure to change them)"
} else {
    Write-Host "`nStation setup" -ForegroundColor Cyan
    do {
        $Call = (Ask 'Your callsign (the default net control)' '').ToUpper()
        $ok = $Call -match '^[A-Z0-9]{1,3}[0-9][A-Z0-9]{0,3}[A-Z]$'
        if (-not $ok) { Warn "`"$Call`" doesn't look like a callsign, try again" }
    } until ($ok)
    $GridGuess = ''
    try {
        $r = Invoke-RestMethod "https://callook.info/$Call/json" -TimeoutSec 8 -UserAgent 'NetLog-installer'
        if ($r.status -eq 'VALID') { $GridGuess = $r.location.gridsquare; Info "Found $Call in the FCC database (grid $GridGuess)" }
    } catch {}
    do {
        $Grid = Ask 'Grid square, used for check-in distances (blank = none)' $GridGuess
        $ok = (-not $Grid) -or ($Grid -match '^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$')
        if (-not $ok) { Warn 'Invalid grid square, try again' }
    } until ($ok)
    do { $HttpPort = Ask 'Web port for Net Log' '8074' } until ($HttpPort -match '^\d{4,5}$')
    New-Item -ItemType Directory -Force -Path $CfgDir | Out-Null
    Write-Utf8NoBom $Cfg ([ordered]@{ callsign = $Call; grid = $Grid; http_port = [int]$HttpPort } | ConvertTo-Json)
    Info "Saved settings to $Cfg"
}
$conf = Get-Content $Cfg -Raw | ConvertFrom-Json
$HttpPort = if ($conf.http_port) { $conf.http_port } else { 8074 }

# --- Install files --------------------------------------------------------------------
Write-Host "`nInstalling" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name like 'python%'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*NetLog*netlog.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
foreach ($f in $Files) { Copy-Item -Force (Join-Path $Src $f) $AppDir }
Copy-Item -Force (Join-Path $PSScriptRoot 'Uninstall-NetLog.ps1') $AppDir
Write-Utf8NoBom (Join-Path $AppDir 'VERSION') $Version
Info "App files -> $AppDir"

# Launcher: start Net Log hidden if it isn't running, then open the browser
$launcher = @"
`$port = $HttpPort
try { Invoke-WebRequest "http://localhost:`$port/api/config" -UseBasicParsing -TimeoutSec 1 | Out-Null }
catch {
    Start-Process -FilePath '$PyW' -ArgumentList '"$AppDir\netlog.py"' -WindowStyle Hidden
    for (`$i = 0; `$i -lt 30; `$i++) {
        Start-Sleep -Milliseconds 300
        try { Invoke-WebRequest "http://localhost:`$port/api/config" -UseBasicParsing -TimeoutSec 1 | Out-Null; break } catch {}
    }
}
Start-Process "http://localhost:`$port"
"@
Write-Utf8NoBom (Join-Path $AppDir 'Launch-NetLog.ps1') $launcher

$ws = New-Object -ComObject WScript.Shell
function New-Shortcut($path, $target, $arguments, $desc) {
    $s = $ws.CreateShortcut($path)
    $s.TargetPath = $target; $s.Arguments = $arguments; $s.Description = $desc
    $s.WorkingDirectory = $AppDir; $s.IconLocation = (Join-Path $AppDir 'netlog.ico'); $s.WindowStyle = 7
    $s.Save()
}
New-Item -ItemType Directory -Force -Path $Menu | Out-Null
$ps = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$launchArgs = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$AppDir\Launch-NetLog.ps1`""
New-Shortcut (Join-Path $Menu 'Net Log.lnk') $ps $launchArgs 'Log check-ins for ham radio nets'
New-Shortcut (Join-Path $Menu 'Uninstall Net Log.lnk') $ps "-NoProfile -ExecutionPolicy Bypass -File `"$AppDir\Uninstall-NetLog.ps1`"" 'Remove Net Log'
New-Shortcut ([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'Net Log.lnk')) $ps $launchArgs 'Log check-ins for ham radio nets'
Info 'Start Menu + Desktop shortcut: "Net Log"'

if ((Ask 'Start Net Log automatically when you log in? (y/n)' 'n') -match '^[Yy]') {
    New-Shortcut (Join-Path $Startup 'NetLog.lnk') $PyW "`"$AppDir\netlog.py`"" 'Net Log background service'
    Info 'Will start at login'
}

# --- Start and check ---------------------------------------------------------------
Start-Process -FilePath $PyW -ArgumentList "`"$AppDir\netlog.py`"" -WindowStyle Hidden
$up = $false
for ($i = 0; $i -lt 30 -and -not $up; $i++) {
    Start-Sleep -Milliseconds 300
    try { Invoke-RestMethod "http://localhost:$HttpPort/api/config" -TimeoutSec 5 | Out-Null; $up = $true } catch {}
}
Write-Host ''
if ($up) { Info "Running on http://localhost:$HttpPort" } else { Warn "Net Log didn't start. Try running: `"$Py`" `"$AppDir\netlog.py`" to see the error." }
Write-Host "`nDone! Open `"Net Log`" from the Start Menu or Desktop, or visit http://localhost:$HttpPort" -ForegroundColor Cyan
Write-Host "  Your logs are kept in $CfgDir\netlogs."
if ((Ask 'Open it now? (y/n)' 'y') -match '^[Yy]') { Start-Process "http://localhost:$HttpPort" }
