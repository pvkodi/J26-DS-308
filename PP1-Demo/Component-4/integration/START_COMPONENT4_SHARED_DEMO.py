#!/usr/bin/env python3
"""Use the existing PP1 demo shell; no duplicate shell build is required."""
import argparse, os, pathlib, shutil, subprocess, sys
component = pathlib.Path(__file__).resolve().parents[1]
p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--shell-port', type=int, default=8051)
p.add_argument('--backend-port', type=int, default=8774)
a = p.parse_args()
launcher = component.parent / 'Component-1/cge_recorded_frontend_20261022/START_RECORDED_DEMO.py'
if not launcher.is_file():
    raise SystemExit(f'Keep Component-4 beside Component-1 in PP1-Demo. Missing: {launcher}')
interpreter = os.environ.get('C4_PYTHON', sys.executable)
if not pathlib.Path(interpreter).is_file():
    interpreter = shutil.which(interpreter) or interpreter
raise SystemExit(subprocess.call([interpreter, str(launcher), '--port', str(a.shell_port), '--backend-port', str(a.backend_port)], cwd=launcher.parent))
