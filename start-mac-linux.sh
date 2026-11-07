#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -f .venv/bin/python ]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
echo 'Research Commons: http://127.0.0.1:8000 (Ctrl+C to stop)'
exec .venv/bin/python commons.py
