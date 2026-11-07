"""Bounded recipes, immutable input manifests, researcher approvals, run exports."""
import base64
import hashlib
import io
import json
import os
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from . import db, recipe as R, provider, ingest
from .tools import ToolError, Cancelled

def digest(steps,base,datasets):
    return hashlib.sha256(json.dumps({'steps':steps,'base':base,'inputs':sorted((n['id'],n['props']['sha256']) for n in datasets)},sort_keys=True).encode()).hexdigest()

def datasets_for(c,ids):
    data=[db.get_node(c,x) for x in ids]
    if not data or any(not n or n['type']!='dataset' for n in data): raise ToolError('invalid_input','Select valid datasets in this project.')
    return data

def validation(steps,base,datasets):
    if not isinstance(steps,list) or not 1<=len(steps)<=20 or any(not isinstance(s,dict) or not isinstance(s.get('params'),dict) for s in steps):
        return {'errors':['Use 1–20 catalog steps with parameter objects.'],'warnings':[],'output_columns':[]}
    try: errors,warnings,cols=R.validate(steps,{n['props']['name']:n['props']['columns'] for n in datasets},base)
    except (TypeError,KeyError,AttributeError): errors,warnings,cols=['Malformed step parameters.'],[],[]
    return {'errors':errors,'warnings':warnings,'output_columns':cols}

def experiment_register_dataset(ctx,inp):
    nid,_=ingest.import_one(ctx,inp['upload_id']); n=db.get_node(ctx.c,nid)
    if n['type']!='dataset': raise ToolError('invalid_input','Upload is not a CSV dataset.')
    return {'dataset_id':nid,'columns':n['props']['profile'],'rows':n['props']['rows']}

def experiment_propose(ctx,inp):
    datasets=datasets_for(ctx.c,inp.get('dataset_ids') or [n['id'] for n in db.nodes(ctx.c,'dataset')])
    schema=[{'id':n['id'],'name':n['props']['name'],'columns':n['props']['columns'],'rows':n['props']['rows'],
             'sample':R.load_csv(n['props']['path'])[:3]} for n in datasets]
    raw=provider.complete(ctx,'experiment.propose','Draft a bounded data-analysis recipe. Return {base:"one dataset name",steps:[{tool:"catalog name",params:{}}],review:[{level:"warning|info",text:"..."}]}. Use only catalog tools and actual columns. Do not claim causal effects or novelty. Summarize missing data and limitations. Every recipe requires human approval.',
                          {'objective':inp['objective'],'datasets':schema,'catalog':R.CATALOG},2500)
    return create_recipe(ctx,inp,raw,datasets)

def create_recipe(ctx,inp,raw,datasets=None):
    datasets=datasets or datasets_for(ctx.c,inp['dataset_ids'])
    base=raw.get('base') or datasets[0]['props']['name']; steps=raw.get('steps',[])
    val=validation(steps,base,datasets); h=digest(steps,base,datasets)
    props={'objective':inp['objective'],'base':base,'dataset_ids':[n['id'] for n in datasets],'steps':steps,
           'validation':val,'hash':h,'approval':{'state':'pending'},'review':raw.get('review',[]),'novelty':[],
           'gap_id':inp.get('gap_id'),'hypothesis_node_id':inp.get('hypothesis_node_id'),
           'provenance':dict(ctx.provenance),'input_hashes':{n['id']:n['props']['sha256'] for n in datasets}}
    with db.tx(ctx.c):
        eid=db.add_node(ctx.c,'experiment',inp['objective'][:120],props,origin='ai' if ctx.provenance.get('model') else 'researcher',created_by='experiment.propose')
        for n in datasets: db.add_edge(ctx.c,eid,n['id'],'uses_dataset',1,created_by='experiment.propose')
        gap=inp.get('gap_id')
        if gap and db.get_node(ctx.c,gap): db.add_edge(ctx.c,eid,gap,'tests',1,created_by='experiment.propose')
    return dict(props,recipe_id=eid,approval='pending')

def experiment_update_recipe(ctx,inp):
    n=db.get_node(ctx.c,inp['recipe_id'])
    if not n or n['type']!='experiment': raise ToolError('not_found','Recipe not found.')
    p=n['props']; datasets=datasets_for(ctx.c,p['dataset_ids']); steps=inp['steps']
    val=validation(steps,p['base'],datasets); h=digest(steps,p['base'],datasets)
    approval=p['approval'] if h==p['hash'] else {'state':'pending'}
    with db.tx(ctx.c):
        db.update_props(ctx.c,n['id'],steps=steps,validation=val,hash=h,approval=approval)
        db.emit(ctx.c,'approval.reset',ctx.actor,[n['id']],{'reason':'Recipe edited'},handled=True)
    return {'recipe_id':n['id'],'validation':val,'hash':h,'approval':approval['state']}

def approval_check(c,inp):
    n=db.get_node(c,inp.get('recipe_id',''))
    if not n or n['type']!='experiment': raise ToolError('not_found','Recipe not found.')
    p=n['props']; datasets=datasets_for(c,p['dataset_ids'])
    val=validation(p['steps'],p['base'],datasets)
    if val['errors']: raise ToolError('invalid_input','; '.join(val['errors']))
    for d in datasets:
        actual=hashlib.sha256(Path(d['props']['path']).read_bytes()).hexdigest()
        if actual!=d['props']['sha256']: raise ToolError('invalid_input','Input data changed on disk. Import a new version before approval.')
    h=digest(p['steps'],p['base'],datasets)
    if p['approval'].get('state')!='approved' or p['approval'].get('hash')!=h or p['hash']!=h:
        return {'recipe_id':n['id'],'approval':'pending','approve_in':'#/experiments/'+n['id'],
                'message':'Review and approve this exact recipe and its input hashes in Experiments.'}
    return None

def experiment_run(ctx,inp):
    # Recheck in the worker, not merely when the job was enqueued.
    if approval_check(ctx.c,inp): raise ToolError('needs_approval','Recipe approval changed before execution.')
    e=db.get_node(ctx.c,inp['recipe_id']); p=e['props']; datasets=datasets_for(ctx.c,p['dataset_ids'])
    paths={n['props']['name']:n['props']['path'] for n in datasets}
    payload={'base':p['base'],'steps':p['steps'],'datasets':paths}
    ctx.step('Running approved catalog recipe in a bounded child process',.25)
    proc=subprocess.Popen([sys.executable,R.__file__,'--stdin'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    started=time.monotonic(); first=True
    try:
        while True:
            try:
                stdout,stderr=proc.communicate(json.dumps(payload) if first else None,timeout=.25); break
            except subprocess.TimeoutExpired:
                first=False
                if ctx.cancelled(): raise Cancelled()
                if time.monotonic()-started>60: raise ToolError('timeout','Recipe exceeded the 60-second execution limit.')
    finally:
        if proc.poll() is None: proc.kill(); proc.communicate()
    if proc.returncode: raise ToolError('invalid_input','Recipe failed: '+stderr[-400:])
    out=json.loads(stdout)
    if not out.get('ok'): raise ToolError('invalid_input','; '.join(out.get('errors',[])))
    if ctx.cancelled(): raise Cancelled()
    manifest={'recipe_hash':p['hash'],'recipe':p['steps'],'base':p['base'],'inputs':{n['props']['name']:n['props']['sha256'] for n in datasets},
              'python':sys.version,'created_at':db.now(),'elapsed_seconds':round(time.monotonic()-started,3)}
    repro=Path(R.__file__).read_text(encoding='utf-8').replace('EMBEDDED_RECIPE = None','EMBEDDED_RECIPE = '+repr({'steps':p['steps'],'base':p['base'],'datasets':list(paths)}),1)
    csv=R.to_csv(out['columns'],out['rows']); archive=io.BytesIO()
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('reproduce.py',repro); z.writestr('manifest.json',json.dumps(manifest,indent=2)); z.writestr('results.csv',csv)
        for name,path in paths.items(): z.write(path,name+'.csv')
    with db.tx(ctx.c):
        rid=db.next_id(ctx.c,'run')
        arts={'results':db.add_artifact(ctx.c,'run_output',rid+'_results.csv','text/csv',csv,rid),
              'repro':db.add_artifact(ctx.c,'repro_script',rid+'_reproduce.py','text/x-python',repro,rid),
              'bundle':db.add_artifact(ctx.c,'repro_bundle',rid+'_reproduce.zip','application/zip',base64.b64encode(archive.getvalue()).decode(),rid),
              'log':db.add_artifact(ctx.c,'run_log',rid+'_audit.json','application/json',json.dumps(dict(manifest,diagnostics=out['diagnostics']),indent=2),rid)}
        props={'experiment_id':e['id'],'status':'succeeded','recipe_hash':p['hash'],'row_count':out['row_count'],
               'rows':out['rows'][:40],'columns':out['columns'],'stats':out['stats'],'diagnostics':out['diagnostics'],
               'artifact_ids':arts,'manifest':manifest}
        db.add_node(ctx.c,'run','Run of '+e['title'],props,origin='researcher',created_by='experiment.run',id_=rid)
        db.add_edge(ctx.c,e['id'],rid,'produced',1,origin='researcher',created_by='experiment.run')
        db.emit(ctx.c,'run.finished','experiment.run',[rid,e['id']])
    return {'run_id':rid,'status':'succeeded','diagnostics':out['diagnostics'],'stats':out['stats'],
            'output_artifact_ids':[arts['results'],arts['log'],arts['bundle']],'repro_artifact_id':arts['repro']}
