"""Launch with python commons.py. API and durable worker use separate processes."""
import argparse
import os
import subprocess
import sys
import time
from pathlib import Path
from backend import db, components, runtime

def worker():
    from server import initialize
    initialize()
    recovered=set()
    print('Research Commons worker ready',flush=True)
    while True:
        worked=False
        for path in sorted((Path(db.WORKSPACE)/'projects').glob('*/platform.sqlite')):
            pid=path.parent.name; db.ACTIVE_PROJECT.set(pid); c=db.connect()
            try:
                if pid not in recovered:
                    c.execute("UPDATE job SET status='interrupted',message='Worker restarted; retry from Activity.' WHERE status IN ('running','cancel_requested')")
                    recovered.add(pid)
                runtime.dispatch_once(c)
                jid=runtime.claim(c)
                if jid:
                    worked=True; print(pid,jid,flush=True); runtime.run_job(c,jid)
            finally: c.close()
        if not worked: time.sleep(.25)

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('command',nargs='?',default='dev',choices=['dev','serve','worker'])
    p.add_argument('--port',type=int,default=int(os.getenv('VRP_PORT','8000'))); args=p.parse_args()
    if args.command=='worker': return worker()
    import uvicorn
    child=None
    if args.command=='dev': child=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'worker'])
    try: uvicorn.run('server:app',host='127.0.0.1',port=args.port,log_level='warning')
    finally:
        if child:
            child.terminate()
            try: child.wait(5)
            except subprocess.TimeoutExpired: child.kill()

if __name__=='__main__': main()
