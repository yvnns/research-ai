@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  python -m venv .venv
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\pip install -r requirements.txt
)
if not exist ".env" copy .env.example .env
set PYTHONPATH=%CD%
set HOST=127.0.0.1
set PORT=8000
.venv\Scripts\python -m uvicorn app.main:app --host %HOST% --port %PORT%
