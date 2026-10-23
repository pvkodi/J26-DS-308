"""Start the shared C1/C2/C3/C4 localhost presentation."""
import argparse,json,os,socket,subprocess,sys,time,urllib.error,urllib.request
from pathlib import Path
root=Path(__file__).resolve().parent
pp1=root.parent.parent
component4=pp1/'Component-4'
parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=8051);parser.add_argument('--backend-port',type=int,default=8774);args=parser.parse_args()
backend=component4/'backend/app.py'
if not backend.is_file(): raise SystemExit(f'Component 4 backend is missing: {backend}')
backend_url=f'http://127.0.0.1:{args.backend_port}'
health_url=backend_url+'/api/c4/health'
env=os.environ.copy();env['C4_BACKEND_URL']=backend_url;env['C4_FRONTEND_ROOT']=str((component4/'frontend').resolve())
def ready():
    try:
        with urllib.request.urlopen(health_url,timeout=2) as r:
            value=json.loads(r.read().decode('utf-8'))
            return r.status==200 and value.get('status')=='ready'
    except (urllib.error.URLError,TimeoutError,json.JSONDecodeError): return False
backend_process=None
if not ready():
    with socket.socket() as s:
        if s.connect_ex(('127.0.0.1',args.backend_port))==0:
            raise SystemExit(f'Backend port {args.backend_port} is occupied by a service that did not pass the Component 4 health check.')
    backend_process=subprocess.Popen([sys.executable,str(backend),'--host','127.0.0.1','--port',str(args.backend_port),'--stage-b-root',str(component4/'research/stage_b'),'--stage-a-recorded',str(component4/'data/stage_a_recorded.json')],cwd=component4,env=env)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline and not ready():
        if backend_process.poll() is not None: raise SystemExit('Component 4 backend exited during startup; see its console output.')
        time.sleep(.25)
    if not ready():
        backend_process.terminate();backend_process.wait(timeout=5)
        raise SystemExit(f'Component 4 backend did not become healthy: {health_url}')
print(f'Unified Presentation (C1 Obligations + C2 Conflict Resolver + C3 Belief Tracker + C4 Prompt Optimizer): http://127.0.0.1:{args.port}/',flush=True)
print(f'Component 4 backend: {health_url}',flush=True)
shell_process=None
try:
    shell_process=subprocess.Popen([sys.executable,str(root/'cge_studio/studio_server.py'),'--port',str(args.port)],cwd=root/'cge_studio',env=env)
    while shell_process.poll() is None: time.sleep(.25)
    raise SystemExit(shell_process.returncode)
except KeyboardInterrupt: pass
finally:
    if shell_process is not None and shell_process.poll() is None:
        shell_process.terminate()
        try: shell_process.wait(timeout=5)
        except subprocess.TimeoutExpired: shell_process.kill();shell_process.wait()
    if backend_process is not None and backend_process.poll() is None:
        backend_process.terminate()
        try: backend_process.wait(timeout=5)
        except subprocess.TimeoutExpired: backend_process.kill();backend_process.wait()
