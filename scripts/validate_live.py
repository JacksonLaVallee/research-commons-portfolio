"""Exercise live AI audit, reviewer, revision and citation workflows on an existing demo.

Uses the configured provider budget; no automatic approval or experiment execution.
"""
import argparse,json,time
from pathlib import Path
import httpx

p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8000');p.add_argument('--project',required=True);a=p.parse_args()
c=httpx.Client(base_url=a.url,timeout=160,params={'project':a.project})
def tool(name,inp):
    r=c.post('/api/tools/'+name,json={'input':inp});r.raise_for_status();r=r.json()
    if r['status']=='queued':
        end=time.monotonic()+300
        while time.monotonic()<end:
            j=c.get('/api/jobs/'+r['job_id']).json()
            if j['status']=='succeeded': return j['result']
            if j['status'] in ('failed','interrupted','cancelled'): raise RuntimeError(j['error'])
            time.sleep(.5)
        raise TimeoutError(name)
    if r['status']!='ok': raise RuntimeError(r)
    return r['data']

report={}
for name,inp in [('gaps.find',{'scope_ids':[],'budget':{'llm_calls':3,'searches':1},'check_literature':True}),
                 ('writing.review',{'draft_id':'drf-1','personas':['evidence','methods']}),
                 ('evidence.check_citations',{'draft_id':'drf-1'})]:
    try:
        data=tool(name,inp);report[name]=data;print(name,'OK',flush=True)
    except Exception as exc: report[name]={'error':str(exc)};print(name,'ERROR',str(exc),flush=True)
review=report.get('writing.review',{})
if review.get('comments'):
    report['writing.revise']=tool('writing.revise',{'draft_id':'drf-1','review_id':review['review_id'],'accept_comment_ids':[review['comments'][0]['id']]})
    print('writing.revise OK',flush=True)
report['word_export']=tool('writing.export',{'draft_id':'drf-1','format':'docx'})
report['ai_recipe']=tool('experiment.propose',{'objective':'Measure the correlation between bmi and progression without any causal claim','dataset_ids':['ds-1']})
path=Path(__file__).resolve().parents[1]/'.workspace/live-validation.json';path.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(path,flush=True)
