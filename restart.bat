@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === Restarting ETF Surge ===
powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo Waiting for ports to free...
powershell -Command "try{ $ports=8000,5173; foreach($p in $ports){ $r=0; while($r -lt 20){ $c=netstat -ano|findstr \":$p \"; if(-not $c){ echo Port $p freed!; break }; $pid=($c -split '\s+')[-1]; taskkill /F /PID $pid 2>nul; sleep 1; $r++ } } }catch{}"
echo Starting...
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Local
