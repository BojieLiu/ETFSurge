@echo off
set PROFILE_WARMUP=1
cd /d "%~dp0backend"
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
