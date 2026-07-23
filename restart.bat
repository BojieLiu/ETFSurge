@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo === 重启 ETF Surge ===
powershell -ExecutionPolicy Bypass -File "%~dp0stop.ps1"
echo Waiting for ports to free...
powershell -Command "try{ $ports=8000,5173; foreach($p in $ports){ $r=0; while($r -lt 30){ $c=netstat -ano|findstr /R ('^.*:'+$p+'\s.*LISTENING'); if(-not $c){ echo Port $p freed!; break }; $c|ForEach-Object{ $t=$_-split '\s+'; $pid=[int]$t[-1]; taskkill /F /PID $pid 2>nul }; sleep 1; $r++ } } }catch{}"
echo Starting...
powershell -ExecutionPolicy Bypass -File "%~dp0start.ps1" -Local -Silent
