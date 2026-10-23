@echo off
rem Double-click to install Net Log. Runs the PowerShell installer without changing system policy.
cd /d "%~dp0"
set RECONF=
if exist "%APPDATA%\NetLog\config.json" (
  choice /m "Net Log is already set up. Change your callsign or grid square"
  if errorlevel 2 (set RECONF=) else (set RECONF=-Reconfigure)
)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-NetLog.ps1" %RECONF%
pause
