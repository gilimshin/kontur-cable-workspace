@echo off
chcp 65001 >nul
echo Starting the local Kontur website...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_kontur.ps1" -OpenBrowser
if errorlevel 1 (
  echo.
  echo Startup failed. Please copy the error text above.
  pause
  exit /b 1
)
echo Website started: http://127.0.0.1:8765/
