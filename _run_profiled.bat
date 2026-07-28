@echo off
set PROFILE_WARMUP=1
echo Starting with PROFILE_WARMUP=1
cd /d E:\ETF_Surge\backend
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
