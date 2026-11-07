"""Create two real-data research projects through the public API.

python scripts/demo.py                 # imports datasets + protocols, pending recipes
python scripts/demo.py --run           # approves the predefined demonstration recipes and runs them
python scripts/demo.py --run --live    # also searches real literature and synthesizes with Amplify

Each invocation creates new projects; it never resets an existing project.
"""
import argparse
import csv
import io
import json
import time
from pathlib import Path
import httpx
from sklearn.datasets import load_diabetes,load_digits

def csv_bytes(headers,rows):
    f=io.StringIO(); w=csv.writer(f); w.writerow(headers); w.writerows(rows); return f.getvalue().encode()

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--url',default='http://127.0.0.1:8000'); p.add_argument('--run',action='store_true');p.add_argument('--live',action='store_true'); a=p.parse_args()
    client=httpx.Client(base_url=a.url,timeout=160)
    configs=[
      {'name':'Vision lab · handwritten digits','question':'How do mean pixel intensities and class representation differ across handwritten digits?',
       'data':load_digits(),'file':'digits.csv','headers':[f'pixel_{i}' for i in range(64)]+['digit'],
       'source':'https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_digits.html',
       'protocol':'This computer-vision analysis uses 1,797 handwritten digit images, each represented by 64 pixel intensities from an 8 by 8 grid. Each image has a digit label from 0 to 9. We compare class counts and mean center-pixel intensity. This subset alone cannot establish performance on new writers or new imaging devices. A descriptive class profile is not a classifier accuracy estimate.',
       'query':'handwritten digit recognition generalization',
       'steps':[{'tool':'aggregate','params':{'group_by':['digit'],'metrics':[{'column':'pixel_27','fn':'mean'},{'column':'pixel_28','fn':'mean'},{'fn':'count'}]}}]},
      {'name':'Clinical methods · diabetes','question':'How is baseline body mass index associated with disease progression in the diabetes dataset?',
       'data':load_diabetes(),'file':'diabetes.csv','headers':list(load_diabetes().feature_names)+['progression'],
       'source':'https://scikit-learn.org/stable/modules/generated/sklearn.datasets.load_diabetes.html',
       'protocol':'This observational research uses the scikit-learn diabetes dataset: 442 samples, ten baseline variables and a disease-progression target. The features use the loader default centering and scaling. We measure the Pearson correlation between baseline body mass index (bmi) and progression. Association does not establish that changing body mass index changes the outcome. We must examine confounding and validation in a separate population before generalizing. Some serum feature interpretations are uncertain in the source documentation.',
       'query':'body mass index diabetes disease progression',
       'steps':[{'tool':'correlate','params':{'x':'bmi','y':'progression'}},{'tool':'aggregate','params':{'group_by':[],'metrics':[{'column':'progression','fn':'mean'},{'fn':'count'}]}}]}
    ]
    report=[]
    for case in configs:
        result=client.post('/api/projects',json={'name':case['name'],'question':case['question']}); result.raise_for_status(); pid=result.json()['project_id']
        def get(path): r=client.get(path,params={'project':pid});r.raise_for_status();return r.json()
        def post(path,data): r=client.post(path,params={'project':pid},json=data);r.raise_for_status();return r.json()
        def tool(name,inp):
            r=post('/api/tools/'+name,{'input':inp})
            if r['status']=='queued':
                deadline=time.monotonic()+360
                while time.monotonic()<deadline:
                    j=get('/api/jobs/'+r['job_id'])
                    if j['status']=='succeeded': return j['result']
                    if j['status'] in ('failed','cancelled','interrupted'): raise RuntimeError(j['error'] or j['message'])
                    time.sleep(.3)
                raise TimeoutError(name)
            if r['status']!='ok': raise RuntimeError(r)
            return r['data']
        data=case['data']; rows=[[*list(x),float(y)] for x,y in zip(data.data,data.target)]
        content=csv_bytes(case['headers'],rows)
        doc=('# Research protocol (researcher-authored demo document)\n\n'+case['protocol']+'\n\nDataset documentation: '+case['source']+'\n').encode()
        r=client.post('/api/uploads',params={'project':pid},files=[('files',(case['file'],content)),('files',('protocol.md',doc))]);r.raise_for_status()
        imported=tool('library.import',{'upload_ids':r.json()['upload_ids']})
        graph=get('/api/graph'); dataset=next(n for n in graph['nodes'] if n['type']=='dataset')
        recipe=tool('experiment.create',{'objective':case['question'],'dataset_ids':[dataset['id']],'base':dataset['props']['name'],'steps':case['steps']})
        item={'project_id':pid,'name':case['name'],'dataset_rows':len(rows),'source':case['source'],'recipe_id':recipe['recipe_id'],
              'url':a.url+'/?project='+pid+'#/home'}
        if a.run:
            post('/api/approvals',{'recipe_id':recipe['recipe_id'],'hash':recipe['hash'],'note':'Approved execution of the fixed demonstration recipe via scripts/demo.py --run.'})
            run=tool('experiment.run',{'recipe_id':recipe['recipe_id']}); item['run_id']=run['run_id']; item['stats']=run['stats']
            print(case['name'],'computed:',json.dumps(run['stats']),flush=True)
        if a.live:
            try:
                found=tool('search.papers',{'query':case['query'],'sources':['openalex'],'limit':3})
                candidates=[r for r in found['results'] if r.get('abstract')][:2]
                if candidates: tool('search.save',{'candidate_ids':[r['candidate_id'] for r in candidates]})
                # Let the durable worker finish import-triggered evidence before synthesis.
                deadline=time.monotonic()+300
                while time.monotonic()<deadline and any(j['status'] in ('queued','running') for j in get('/api/jobs')['jobs']): time.sleep(1)
                graph=get('/api/graph'); papers=[n['id'] for n in graph['nodes'] if n['type']=='paper']
                draft=tool('chat.synthesize',{'paper_ids':papers,'question':case['question']}); item['draft_id']=draft['draft_id']
                item['claims']=sum(n['type']=='claim' for n in graph['nodes'])
            except Exception as exc: item['live_error']=str(exc); print('Live analysis issue:',str(exc),flush=True)
        report.append(item); print(item['url'],flush=True)
    path=Path(__file__).resolve().parents[1]/'.workspace/demo-report.json'; path.parent.mkdir(exist_ok=True);path.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Demo report:',path,flush=True)

if __name__=='__main__':main()
