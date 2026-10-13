@echo off
rem Double-click to install RigPanel. Runs the PowerShell installer without changing system policy.
cd /d "%~dp0"
set RECONF=
if exist "%APPDATA%\RigPanel\config.json" (
  choice /m "RigPanel is already set up. Change your station settings"
  if errorlevel 2 (set RECONF=) else (set RECONF=-Reconfigure)
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-RigPanel.ps1" %RECONF%
pause
