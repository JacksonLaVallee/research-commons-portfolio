"""Local single-tenant FastAPI shell; one database per project, one tool catalog."""
import asyncio
import base64
import json
import os
import queue
import re
import threading
import uuid
import math
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlparse
from fastapi import FastAPI, Request, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import set_key
from backend import db, components, runtime, provider, ingest, workbench, chat
from backend.tools import TOOLS, Ctx, ToolError

app=FastAPI(title='Vanderbilt Research Commons',version='1.0.0')

@contextmanager
def connection():
    c=db.connect()
    try: yield c
    finally: c.close()

def initialize(pid='default',name='My research project',question='What does the evidence support?'):
    c=db.connect(pid)
    try:
        db.init_schema(c)
        c.execute('INSERT OR IGNORE INTO project VALUES(?,?,?,?)',(pid,name,question,json.dumps({'architecture':'modular monolith','provider':'Amplify'})))
    finally: c.close()

@app.middleware('http')
async def scope(request,call_next):
    host=request.url.hostname
    if host not in ('127.0.0.1','localhost','testserver','::1'): return JSONResponse({'error':'This application accepts local requests only.'},403)
    if request.method not in ('GET','HEAD','OPTIONS'):
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'): return JSONResponse({'error':'Cross-origin writes are not allowed.'},403)
    pid=request.query_params.get('project','default')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}',pid): return JSONResponse({'error':'Invalid project ID'},400)
    if request.url.path.startswith('/api/') and pid!='default' and not (db.project_dir(pid)/'platform.sqlite').exists():
        return JSONResponse({'error':'Project not found'},404)
    token=db.ACTIVE_PROJECT.set(pid)
    try:
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        return response
    finally: db.ACTIVE_PROJECT.reset(token)

@app.exception_handler(ToolError)
async def tool_error(request,exc):
    return JSONResponse({'status':'error','error':{'code':exc.code,'message':exc.message,'retryable':exc.retryable}},400)

class ToolRequest(BaseModel):
    input: dict=Field(default_factory=dict)
    caller: str='ui'
    project_id: str | None=None

@app.get('/api/health')
def health(): return {'ok':True,'version':'1.0.0','provider':provider.status(),'project':db.ACTIVE_PROJECT.get()}

@app.get('/api/projects')
def projects():
    out=[]
    for f in sorted((Path(db.WORKSPACE)/'projects').glob('*/platform.sqlite')):
        c=db.connect(f.parent.name)
        try:
            p=c.execute('SELECT * FROM project').fetchone()
            if p: out.append(dict(p))
        finally: c.close()
    return {'projects':out}

class ProjectInput(BaseModel):
    name: str=Field(min_length=1,max_length=120)
    question: str=Field(min_length=1,max_length=4000)

@app.post('/api/projects')
def new_project(body:ProjectInput):
    pid='project-'+uuid.uuid4().hex[:10]; initialize(pid,body.name,body.question)
    return {'project_id':pid}

@app.post('/api/project')
def edit_project(body:ProjectInput):
    with connection() as c:
        c.execute('UPDATE project SET name=?,question=?',(body.name,body.question))
    return {'ok':True}

@app.get('/api/project')
def project():
    with connection() as c:
        p=dict(c.execute('SELECT * FROM project').fetchone()); p['settings']=json.loads(p['settings'])
        p['counts']={r['type']:r['n'] for r in c.execute('SELECT type,COUNT(*) n FROM node GROUP BY type')}
        p['unreviewed']=c.execute("SELECT COUNT(*) FROM node WHERE review_status='unreviewed'").fetchone()[0]
        p['pending_approvals']=sum(n['props']['approval']['state']!='approved' for n in db.nodes(c,'experiment'))
        p.update(llm_mode='Amplify' if provider.status()['ready'] else 'not configured',similarity='TF-IDF / BM25')
        return p

@app.get('/api/tools')
def tools(): return {'tools':[t.spec() for t in TOOLS.values()],'not_in_catalog':['POST /api/review','POST /api/approvals']}

@app.post('/api/tools/{name}')
def call(name:str,body:ToolRequest):
    if body.project_id and body.project_id!=db.ACTIVE_PROJECT.get(): raise HTTPException(400,'Project context mismatch')
    with connection() as c: return runtime.call_tool(c,name,body.input,'ui' if body.caller=='ui' else 'agent:api')

@app.get('/api/graph')
def graph():
    with connection() as c: return {'nodes':db.nodes(c),'edges':db.edges(c)}

@app.get('/api/jobs')
def jobs(limit:int=60):
    with connection() as c: return {'jobs':[db.job_dict(r) for r in c.execute('SELECT * FROM job ORDER BY rowid DESC LIMIT ?',(max(1,min(200,limit)),))]}

@app.get('/api/jobs/{jid}')
def job(jid:str):
    with connection() as c:
        r=db.job_dict(c.execute('SELECT * FROM job WHERE id=?',(jid,)).fetchone())
        if not r: raise HTTPException(404,'Job not found')
        return r

@app.post('/api/jobs/{jid}/{action}')
def job_action(jid:str,action:str):
    with connection() as c:
        with db.tx(c):
            j=db.job_dict(c.execute('SELECT * FROM job WHERE id=?',(jid,)).fetchone())
            if not j: raise HTTPException(404,'Job not found')
            if action=='cancel' and j['status'] in ('queued','running'):
                c.execute('UPDATE job SET status=? WHERE id=?',('cancelled' if j['status']=='queued' else 'cancel_requested',jid))
                db.emit(c,'job.cancel_requested','researcher',[jid],handled=True); return {'ok':True}
            if action=='retry' and j['status'] in ('failed','interrupted','cancelled'):
                return {'ok':True,'job_id':runtime.enqueue(c,j['kind'],j['params'],'ui')}
    raise HTTPException(409,'Job state does not allow this action')

@app.get('/api/events/recent')
def recent(limit:int=80):
    with connection() as c:
        rows=c.execute("SELECT * FROM event WHERE type!='job.progress' ORDER BY id DESC LIMIT ?",(max(1,min(200,limit)),)).fetchall()
        return {'events':[dict(r,target_ids=json.loads(r['target_ids']),data=json.loads(r['data'])) for r in rows],
                'last_id':c.execute('SELECT COALESCE(MAX(id),0) FROM event').fetchone()[0]}

@app.get('/api/events')
async def events(request:Request,since:int=0):
    pid=db.ACTIVE_PROJECT.get()
    async def stream():
        c=db.connect(pid); last=since; beat=0
        try:
            yield 'event: hello\ndata: {}\n\n'
            while not await request.is_disconnected():
                for r in c.execute('SELECT * FROM event WHERE id>? ORDER BY id LIMIT 200',(last,)).fetchall():
                    last=r['id']; data=dict(r,target_ids=json.loads(r['target_ids']),data=json.loads(r['data']))
                    yield f'id: {last}\nevent: message\ndata: {json.dumps(data)}\n\n'
                beat+=1
                if beat%30==0: yield ': heartbeat\n\n'
                await asyncio.sleep(.5)
        finally: c.close()
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'Cache-Control':'no-cache'})

class ReviewInput(BaseModel):
    target_ids: list[str]=Field(max_length=200)
    decision: str
    reason: str=''

@app.post('/api/review')
def review(body:ReviewInput):
    states={'accept':'accepted','dismiss':'dismissed','reset':'unreviewed'}
    if body.decision not in states: raise HTTPException(400,'Invalid review decision')
    updated=[]
    with connection() as c:
        with db.tx(c):
            for tid in body.target_ids:
                table='edge' if tid.startswith('e-') else 'node'
                if c.execute(f'UPDATE {table} SET review_status=? WHERE id=?',(states[body.decision],tid)).rowcount: updated.append(tid)
            db.emit(c,'node.reviewed','researcher',updated,{'decision':body.decision,'reason':body.reason},handled=True)
    return {'updated':updated,'status':states[body.decision]}

class ApprovalInput(BaseModel):
    recipe_id:str
    hash:str
    note:str=''

@app.post('/api/approvals')
def approve(body:ApprovalInput):
    with connection() as c:
        with db.tx(c):
            n=db.get_node(c,body.recipe_id)
            if not n or n['type']!='experiment': raise HTTPException(404,'Recipe not found')
            # This check also verifies input file hashes and revalidates recipe columns.
            workbench.approval_check(c,{'recipe_id':body.recipe_id})
            if body.hash!=n['props']['hash']: raise HTTPException(409,'Recipe changed. Refresh and review its current version.')
            approval={'state':'approved','hash':body.hash,'at':db.now(),'by':'researcher','note':body.note}
            db.update_props(c,n['id'],approval=approval)
            db.emit(c,'approval.granted','researcher',[n['id']],approval,handled=True)
    return {'approval':approval,'approval_id':body.hash}

@app.post('/api/uploads')
async def upload(files:list[UploadFile]=File(...)):
    if len(files)>100: raise HTTPException(400,'Upload at most 100 files at a time')
    ids=[]; errors=[]
    with connection() as c:
        for f in files:
            content=await f.read(ingest.MAX_BYTES+1)
            try: ids.append(ingest.stage(c,f.filename or 'upload',content,f.filename or ''))
            except ToolError as exc: errors.append({'file':f.filename,'reason':exc.message})
    return {'upload_ids':ids,'errors':errors}

@app.get('/api/uploads')
def uploads():
    with connection() as c: return {'uploads':[{'upload_id':r['id'],'file':r['relative_path'],'imported':bool(r['imported_id']),
                                               'dataset':r['name'] if r['name'].lower().endswith('.csv') else None} for r in c.execute('SELECT * FROM upload')]}

@app.get('/api/datasets/{did}/rows')
def dataset(did:str,limit:int=25):
    from backend.recipe import load_csv
    with connection() as c:
        n=db.get_node(c,did)
        if not n or n['type']!='dataset': raise HTTPException(404,'Dataset not found')
        rows=load_csv(n['props']['path']); return {'rows':rows[:max(1,min(100,limit))],'columns':n['props']['columns'],'total':len(rows)}

@app.get('/api/artifacts')
def artifacts():
    with connection() as c: return {'artifacts':[dict(r) for r in c.execute('SELECT id,kind,name,mime,source_id,created_at,LENGTH(content) size FROM artifact ORDER BY rowid DESC')]}

@app.get('/api/artifacts/{aid}')
def artifact(aid:str,download:bool=False):
    with connection() as c: r=c.execute('SELECT * FROM artifact WHERE id=?',(aid,)).fetchone()
    if not r: raise HTTPException(404,'Artifact not found')
    binary=r['mime'] in ('application/zip','application/vnd.openxmlformats-officedocument.wordprocessingml.document')
    content=base64.b64decode(r['content']) if binary else r['content'].encode('utf-8')
    headers={'Content-Disposition':f'attachment; filename="{r["name"]}"'} if download or binary else {}
    return Response(content,media_type=r['mime'],headers=headers)

class ChatInput(BaseModel):
    message:str=Field(max_length=8000)
    context:dict=Field(default_factory=dict)
    conversation_id:str | None=None

@app.post('/api/chat')
def chat_route(body:ChatInput):
    pid=db.ACTIVE_PROJECT.get(); q=queue.Queue()
    def run():
        db.ACTIVE_PROJECT.set(pid); c=db.connect()
        try: chat.handle(c,body.message,body.context,body.conversation_id,lambda event,data:q.put((event,data)))
        except Exception: q.put(('answer',{'answer':'Chat encountered an error. Check Activity and retry.','citations':[],'actions':[]}))
        finally: c.close(); q.put(None)
    threading.Thread(target=run,daemon=True).start()
    def stream():
        while True:
            try: item=q.get(timeout=10)
            except queue.Empty: yield ': heartbeat\n\n'; continue
            if item is None: break
            yield 'event: '+item[0]+'\ndata: '+json.dumps(item[1])+'\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')

@app.get('/api/settings')
def settings(): return provider.status()

@app.get('/api/models')
def models(): return provider.request('/available_models')

@app.post('/api/settings')
def save_settings(body:dict):
    allowed={'AMPLIFY_API_KEY','AMPLIFY_MODEL','AMPLIFY_BASE_URL','AMPLIFY_INPUT_USD_PER_MILLION','AMPLIFY_OUTPUT_USD_PER_MILLION','VRP_BUDGET_USD','VRP_MAX_CALLS','OPENALEX_API_KEY','S2_API_KEY'}
    combined={**provider.config(),**body}
    for name in ('AMPLIFY_INPUT_USD_PER_MILLION','AMPLIFY_OUTPUT_USD_PER_MILLION','VRP_BUDGET_USD'):
        value=combined.get(name)
        if value not in ('',None):
            try:
                number=float(value)
                if not math.isfinite(number) or number<=0 or (name=='VRP_BUDGET_USD' and number>5): raise ValueError()
            except (ValueError,TypeError): raise HTTPException(400,'Enter positive model prices and a budget up to $5.')
    if 'VRP_MAX_CALLS' in combined:
        try: valid=1<=int(combined['VRP_MAX_CALLS'])<=500
        except (TypeError,ValueError): valid=False
        if not valid: raise HTTPException(400,'Call limit must be between 1 and 500.')
    url=urlparse(str(combined.get('AMPLIFY_BASE_URL') or 'https://prod-api.vanderbilt.ai'))
    if url.scheme!='https' or not url.netloc or url.username or url.password or url.query or url.fragment:
        raise HTTPException(400,'Use an HTTPS base URL without credentials, query parameters or fragments.')
    for k,v in body.items():
        if k not in allowed or not isinstance(v,(str,int,float)): raise HTTPException(400,'Invalid configuration field')
        if '\n' in str(v) or '\r' in str(v): raise HTTPException(400,'Configuration values cannot contain newlines')
    path=Path(db.ROOT)/'.env'; path.touch(exist_ok=True)
    for k,v in body.items():
        if k.endswith('API_KEY') and not str(v).strip(): continue
        set_key(str(path),k,str(v))
    return provider.status()

initialize()
app.mount('/',StaticFiles(directory=Path(__file__).parent/'web',html=True),name='web')
