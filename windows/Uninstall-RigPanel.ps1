# Remove RigPanel for the current user. Settings in %APPDATA%\RigPanel are kept unless you choose to delete them.
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
    Where-Object { $_.CommandLine -like '*RigPanel*rigpanel.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item -Recurse -Force (Join-Path ([Environment]::GetFolderPath('Programs')) 'RigPanel')
Remove-Item -Force (Join-Path ([Environment]::GetFolderPath('Startup')) 'RigPanel.lnk')
Get-ChildItem ([Environment]::GetFolderPath('Desktop')) -Filter '* Rig Panel.lnk' | Remove-Item -Force
Set-Location $env:TEMP
Remove-Item -Recurse -Force (Join-Path $env:LOCALAPPDATA 'RigPanel')
$r = Read-Host '  Also delete your RigPanel settings, presets and lookup history? (y/n) [n]'
if ($r -match '^[Yy]') { Remove-Item -Recurse -Force (Join-Path $env:APPDATA 'RigPanel'); Write-Host '  Settings deleted.' }
Write-Host '  RigPanel removed.' -ForegroundColor Green
Read-Host '  Press Enter to close'
