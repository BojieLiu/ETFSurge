@echo off
chcp 65001 >nul
cd /d "%~dp0"

if "%1"=="local" (
    powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0start.ps1" -Local
    goto :eof
)
if "%1"=="docker" (
    powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0start.ps1" -Docker
    goto :eof
)

echo ?? ETF Surge
echo 1) ????(??, ????, Redis ? Docker ??)
echo 2) Docker ??(??????)
set /p choice="??? (1/2, ??1): "
if "%choice%"=="2" (
    powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0start.ps1" -Docker
) else (
    powershell -ExecutionPolicy Bypass -NoExit -File "%~dp0start.ps1" -Local
)
