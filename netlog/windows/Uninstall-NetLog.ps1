# Remove Net Log for the current user. Settings and saved logs in %APPDATA%\NetLog are kept unless you choose to delete them.
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*NetLog*netlog.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Recurse -Force (Join-Path ([Environment]::GetFolderPath('Programs')) 'Net Log')
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath('Startup')) 'NetLog.lnk')
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath('Desktop')) 'Net Log.lnk')
Set-Location $env:TEMP
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'NetLog')
$r = Read-Host '  Also delete your Net Log settings, letterhead AND ALL SAVED NET LOGS? (y/n) [n]'
if ($r -match '^[Yy]') { Remove-Item -Recurse -Force (Join-Path $env:APPDATA 'NetLog'); Write-Host '  Settings and logs deleted.' }
Write-Host '  Net Log removed.' -ForegroundColor Green
Read-Host '  Press Enter to close'
