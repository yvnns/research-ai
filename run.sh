#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="${VENV_DIR:-}"

if [ -z "$VENV" ]; then
  if [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    VENV="$PROJECT_DIR/.venv"
  elif [ -x "/home/vns/research-ai-venv/bin/python" ]; then
    VENV="/home/vns/research-ai-venv"
  else
    VENV="/home/vns/research-ai-venv"
  fi
fi

if [ ! -x "$VENV/bin/python" ]; then
  echo "Criando ambiente virtual em $VENV"
  python3 -m venv --copies "$VENV"
  "$VENV/bin/pip" install --upgrade pip
  "$VENV/bin/pip" install -r "$PROJECT_DIR/requirements.txt"
fi

cd "$PROJECT_DIR"
export PYTHONPATH="$PROJECT_DIR"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
exec "$VENV/bin/uvicorn" app.main:app --host "$HOST" --port "$PORT"