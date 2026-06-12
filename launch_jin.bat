@echo off
setlocal

cd /d "%~dp0"

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0launch_jin.ps1"

echo.
echo JIN launcher finished. Press any key to close this window.
pause >nul
