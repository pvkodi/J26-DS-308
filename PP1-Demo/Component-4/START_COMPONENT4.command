#!/bin/zsh
set -e
cd "$(dirname "$0")"
PROJECT_ROOT="$(cd ../.. && pwd)"
if [[ -x "$PROJECT_ROOT/.venv/bin/python" ]]; then
  PYTHON="$PROJECT_ROOT/.venv/bin/python"
elif [[ -x "$PWD/.venv/bin/python" ]]; then
  PYTHON="$PWD/.venv/bin/python"
else
  PYTHON=python3
fi
exec "$PYTHON" backend/app.py --host 127.0.0.1 --port 8774 --stage-b-root research/stage_b --stage-a-recorded data/stage_a_recorded.json
