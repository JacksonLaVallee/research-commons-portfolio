import base64
import io
import json
import subprocess
import sys
import zipfile
from pathlib import Path
import pytest
from backend import db, runtime, sources, provider, tools, workbench, evidence, recipe, evidence_rules

def call(client,name,inp):
    r=client.post('/api/tools/'+name,json={'input':inp}).json()
    assert r['status']!='error',r
    return r

def run_one(c,jid):
    c.execute("UPDATE job SET status='running' WHERE id=?",(jid,)); runtime.run_job(c,jid)
    j=db.job_dict(c.execute('SELECT * FROM job WHERE id=?',(jid,)).fetchone())
    assert j['status']=='succeeded',j
    return j['result']

def upload(client,c,name,data):
    r=client.post('/api/uploads',files={'files':(name,data)}); assert r.status_code==200,r.text
    j=call(client,'library.import',{'upload_ids':r.json()['upload_ids']})
    return run_one(c,j['job_id'])

def test_real_csv_approval_execution_reproduction_and_brief(client,c,tmp_path):
    imp=upload(client,c,'observations.csv',b'group,x,y\na,1,2\na,2,4\nb,3,6\nb,4,8\n')
    did=imp['dataset_ids'][0]; d=db.get_node(c,did)
    created=call(client,'experiment.create',{'objective':'Association of x and y','dataset_ids':[did],'base':d['props']['name'],
            'steps':[{'tool':'correlate','params':{'x':'x','y':'y'}},{'tool':'aggregate','params':{'group_by':['group'],'metrics':[{'column':'y','fn':'mean'},{'fn':'count'}]}}]})['data']
    eid=created['recipe_id']
    assert call(client,'experiment.run',{'recipe_id':eid})['status']=='needs_approval'
    assert client.post('/api/approvals',json={'recipe_id':eid,'hash':'stale'}).status_code==409
    assert client.post('/api/approvals',json={'recipe_id':eid,'hash':created['hash']}).status_code==200
    job=call(client,'experiment.run',{'recipe_id':eid})
    result=run_one(c,job['job_id']); run=db.get_node(c,result['run_id'])
    assert run['props']['stats'][0]['value']==1
    assert run['props']['rows'][0]['mean_y']==3
    bundle=client.get('/api/artifacts/'+run['props']['artifact_ids']['bundle'])
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as z:z.extractall(tmp_path/'repro')
    proc=subprocess.run([sys.executable,str(tmp_path/'repro/reproduce.py')],capture_output=True,text=True)
    assert proc.returncode==0,proc.stderr
    assert 'a,3.0,2' in proc.stdout or 'a,3,2' in proc.stdout
    runtime.dispatch_once(c)
    brief_job=c.execute("SELECT id FROM job WHERE kind='writing.brief'").fetchone()[0]
    brief=run_one(c,brief_job)
    assert 'pearson_r' in client.get('/api/artifacts/'+brief['artifact_id']).text
    edited=call(client,'experiment.update_recipe',{'recipe_id':eid,'steps':[{'tool':'select_columns','params':{'columns':['x']}}]})['data']
    assert edited['approval']=='pending'
    # A job queued under the old approval is checked again by the worker.
    c.execute("UPDATE job SET status='running' WHERE id=?",(job['job_id'],)); runtime.run_job(c,job['job_id'])
    assert db.job_dict(c.execute('SELECT * FROM job WHERE id=?',(job['job_id'],)).fetchone())['error']['code']=='needs_approval'

def test_project_isolation_and_path_traversal(client,c):
    imp=upload(client,c,'note.md',b'A sufficiently long research observation for the document corpus.')
    pid=client.post('/api/projects',json={'name':'Second','question':'Another research question'}).json()['project_id']
    assert client.get('/api/graph?project='+pid).json()['nodes']==[]
    r=client.post('/api/tools/graph.get?project='+pid,json={'input':{'node_id':imp['paper_ids'][0]}}).json()
    assert r['error']['code']=='not_found'
    assert client.get('/api/graph?project=../../escape').status_code==400
    assert client.post('/api/review',headers={'Origin':'https://evil.example'},json={'target_ids':[],'decision':'accept'}).status_code==403

def test_reject_connection_removes_line_but_keeps_history(client,c):
    with db.tx(c):
        a=db.add_node(c,'claim','First'); b=db.add_node(c,'claim','Second'); e=db.add_edge(c,a,b,'supports')
    assert len(call(client,'graph.neighbors',{'node_id':a})['data']['edges'])==1
    client.post('/api/review',json={'target_ids':[e],'decision':'dismiss','reason':'Unsupported relation'})
    assert call(client,'graph.neighbors',{'node_id':a})['data']['edges']==[]
    assert db.edges(c)[0]['review_status']=='dismissed'
    assert c.execute("SELECT COUNT(*) FROM event WHERE type='node.reviewed'").fetchone()[0]==1
    client.post('/api/review',json={'target_ids':[e],'decision':'reset'})
    assert len(call(client,'graph.neighbors',{'node_id':a})['data']['edges'])==1

def test_ingestion_dedup_and_exact_evidence(client,c,monkeypatch):
    imp=upload(client,c,'protocol.md',b'The study measured four participants. The observations were collected in one hospital.')
    pid=imp['paper_ids'][0]
    dup=upload(client,c,'renamed.md',b'The study measured four participants. The observations were collected in one hospital.')
    assert dup['duplicates'][0]['existing_id']==pid
    def model(ctx,task,instruction,data,max_tokens=2400):
        p=data['passages'][0]
        return {'claims':[{'finding':'Four participants were measured.','direction':'unclear','evidence':{'passage_id':p['id'],'quote':'The study measured four participants.'}},
                          {'finding':'Made up result','direction':'positive','evidence':{'passage_id':p['id'],'quote':'The intervention cured every participant.'}}],
                'assumptions':[]}
    monkeypatch.setattr(provider,'complete',model)
    j=call(client,'evidence.extract',{'paper_ids':[pid]}); r=run_one(c,j['job_id'])
    assert len(r['claim_ids'])==1 and r['grounding']['dropped']==1
    assert db.get_node(c,r['claim_ids'][0])['review_status']=='unreviewed'
    r2=run_one(c,call(client,'evidence.extract',{'paper_ids':[pid]})['job_id']); assert r2['claim_ids']==[]

def test_guard_never_upgrades_unsubstantiated_comparability():
    a={'fields':{},'direction':'positive'}; b={'fields':{},'direction':'negative'}
    assert evidence_rules.guard_comparison(a,b,{'relation':'potential_conflict','axes':{x:'matched' for x in evidence_rules.AXES}})['relation']=='uncertain'
    assert evidence_rules.validate_quote({'quote':'invented','passage_id':'p'},[{'id':'p','text':'Real source text.'}]) is None

def test_search_partial_failure_save_and_history(client,c,monkeypatch):
    def search(source,query,limit):
        if source=='arxiv': raise tools.ToolError('source_unavailable','offline')
        return [sources.paper('A real-shaped test source',['Test Author'],2024,'An abstract about methods.','openalex','https://example.org',doi='10.test/source')]
    monkeypatch.setattr(sources,'search',search)
    result=run_one(c,call(client,'search.papers',{'query':'methods','sources':['openalex','arxiv']})['job_id'])
    assert len(result['source_failures'])==1
    inp={'candidate_ids':[result['results'][0]['candidate_id']]}
    saved=run_one(c,call(client,'search.save',inp)['job_id'])
    assert db.get_node(c,saved['paper_ids'][0])['props']['full_text'] is False
    again=run_one(c,call(client,'search.save',inp)['job_id']); assert again['already_present']==saved['paper_ids']
    assert db.get_node(c,result['search_id'])['props']['results'][0]['paper_id']==saved['paper_ids'][0]

def test_input_integrity_and_unknown_tools(client,c):
    imp=upload(client,c,'x.csv',b'x\n1\n2\n'); d=db.get_node(c,imp['dataset_ids'][0])
    result=call(client,'experiment.create',{'objective':'bad','dataset_ids':[d['id']],'base':d['props']['name'],
                                         'steps':[{'tool':'shell','params':{'command':'whoami'}}]})['data']
    assert result['validation']['errors']
    assert client.post('/api/approvals',json={'recipe_id':result['recipe_id'],'hash':result['hash']}).status_code==400
    with pytest.raises(ValueError): recipe.run([{'tool':'join','params':{'dataset':'b','on':'id'}}],{'a':[{'id':1}],'b':[{'id':1},{'id':1}]},'a')

def test_budget_reservation_cache_and_failure(client,c,monkeypatch):
    cfg={'AMPLIFY_API_KEY':'test-only','AMPLIFY_MODEL':'test','AMPLIFY_INPUT_USD_PER_MILLION':'1','AMPLIFY_OUTPUT_USD_PER_MILLION':'1','VRP_BUDGET_USD':'5','VRP_MAX_CALLS':'1'}
    monkeypatch.setattr(provider,'config',lambda:cfg)
    calls=[]
    def request(path,payload): calls.append(payload); return {'data':{'content':'{"answer":"ok"}'}}
    monkeypatch.setattr(provider,'request',request)
    ctx=tools.Ctx(c)
    assert provider.complete(ctx,'test','Return answer',{})=={'answer':'ok'}
    assert provider.complete(ctx,'test','Return answer',{})=={'answer':'ok'}
    assert len(calls)==1 and ctx.provenance['cache_hit']
    assert calls[0]['data']['options']['prompt']==calls[0]['data']['messages'][-1]['content']
    with pytest.raises(tools.ToolError,match='limit'): provider.complete(ctx,'different','Return answer',{})

def test_missing_key_does_not_fabricate_output(client,c,monkeypatch):
    monkeypatch.setattr(provider,'config',lambda:{})
    with pytest.raises(tools.ToolError,match='Configure'): provider.complete(tools.Ctx(c),'test','test',{})
