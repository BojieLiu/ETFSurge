@echo off
cd /d E:\ETF_Surge\backend
set PROFILE_WARMUP=1
start "ETF_Surge_Backend" /MIN python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
echo Backend started (new window)
