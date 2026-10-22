"""Python 3.10+; standard library only; no installation or model downloads."""
import argparse,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8051);args=parser.parse_args()
print(f'Unified Presentation (Obligation Monitor C1 + Keel Memory C3): http://127.0.0.1:{args.port}/',flush=True)
raise SystemExit(subprocess.call([sys.executable,str(root/'cge_studio/studio_server.py'),'--port',str(args.port)],cwd=root/'cge_studio'))
