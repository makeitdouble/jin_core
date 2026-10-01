@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title JIN CORE ENGINE // LAUNCHER
mode con cols=92 lines=55 >nul 2>nul

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0jl.ps1"
set "JIN_EXIT=%ERRORLEVEL%"

if not "%JIN_EXIT%"=="0" (
  echo.
  echo JIN launcher stopped with error %JIN_EXIT%.
  pause
)

exit /b %JIN_EXIT%
