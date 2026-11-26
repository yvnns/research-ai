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
start "Research AI" .venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
timeout /t 5 /nobreak >nul
echo Iniciando tunnel publico...
"C:\Program Files (x86)\cloudflared\cloudflared.exe" tunnel --url http://127.0.0.1:8000
