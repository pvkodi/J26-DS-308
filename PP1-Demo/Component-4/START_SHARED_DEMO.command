#!/bin/zsh
set -e
cd "$(dirname "$0")"
if [[ -n "${C4_PYTHON:-}" ]]; then
  PYTHON="$C4_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  PYTHON="$PWD/.venv/bin/python"
elif [[ -x ../../.venv/bin/python ]]; then
  PYTHON="$(cd ../../.venv/bin && pwd)/python"
else
  PYTHON=python3
fi
exec "$PYTHON" integration/START_COMPONENT4_SHARED_DEMO.py "$@"
