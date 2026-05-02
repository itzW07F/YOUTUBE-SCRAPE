@echo off
setlocal EnableExtensions
cd /d "%~dp0" || exit /b 1
set "START_PS=%~dp0start-gui.ps1"

where pwsh >nul 2>&1
if %ERRORLEVEL% equ 0 (
  pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%START_PS%" %*
  exit /b %ERRORLEVEL%
)

where powershell >nul 2>&1
if errorlevel 1 (
  echo ERROR: PowerShell was not found on PATH.
  exit /b 1
)
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%START_PS%" %*
exit /b %ERRORLEVEL%
