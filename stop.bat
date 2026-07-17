@echo off
chcp 65001 >nul
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo.
echo Press any key to close...
pause >nul
