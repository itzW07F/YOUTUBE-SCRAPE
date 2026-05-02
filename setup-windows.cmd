@echo off
setlocal EnableExtensions
REM Double-click-safe: always use repository root; avoids ExecutionPolicy prompts when PowerShell is invoked explicitly.
cd /d "%~dp0" || exit /b 1

set "SETUP_PS=%~dp0setup.ps1"

where pwsh >nul 2>&1
if %ERRORLEVEL% equ 0 (
  pwsh -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_PS%" %*
) else (
  where powershell >nul 2>&1
  if errorlevel 1 (
    echo ERROR: Neither pwsh ^(PowerShell 7+^) nor powershell.exe ^(5.1+^) was found on PATH.
    echo Install PowerShell, then open this folder and run setup-windows.cmd again.
    exit /b 1
  )
  powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%SETUP_PS%" %*
)

if errorlevel 1 (
  echo.
  echo Setup stopped with an error. Scroll up for the red ERROR message.
  if not defined SETUP_WINDOWS_NONINTERACTIVE pause
  exit /b 1
)

echo.
echo Setup finished successfully.
if not defined SETUP_WINDOWS_NONINTERACTIVE pause
exit /b 0
