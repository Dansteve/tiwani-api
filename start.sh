#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

if [ ! -f ".env" ]; then
  echo "Error: .env file not found. Copy .env.example to .env and update values before starting."
  exit 1
fi

if [ -d "venv" ]; then
  # shellcheck source=/dev/null
  source "venv/bin/activate"
else
  echo "No virtual environment found. Create one with:"
  echo "  python3 -m venv venv"
  echo "  source venv/bin/activate"
  echo "  pip install -r requirements.txt"
  exit 1
fi

uvicorn main:app --reload --host 0.0.0.0 --port 8000
