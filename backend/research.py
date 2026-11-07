"""Discovery, library, field map and funding components over the common graph."""
import hashlib
import json
from . import db, sources, ingest, provider, grounding as G
from .tools import ToolError, node_text

def library_import(ctx, inp):
    result={'paper_ids':[],'dataset_ids':[],'duplicates':[],'skipped':[]}
    ids=inp.get('upload_ids') or []
    if not ids: raise ToolError('invalid_input','Choose uploaded files to import.')
    for i,uid in enumerate(ids[:100]):
        ctx.step(f'Importing file {i+1}/{len(ids)}',(i+1)/len(ids))
        try:
            nid,duplicate=ingest.import_one(ctx,uid)
            if duplicate: result['duplicates'].append({'file':uid,'existing_id':nid})
            else: result['dataset_ids' if nid.startswith('ds-') else 'paper_ids'].append(nid)
        except (ToolError,ValueError,UnicodeError) as exc:
            result['skipped'].append({'file':uid,'reason':str(exc)})
    return result

def search_papers(ctx, inp):
    query=inp['query'].strip()
    if len(query)<3: raise ToolError('invalid_input','Enter at least three characters.')
    srcs=inp.get('sources') or ['openalex','arxiv']
    results=[]; failures=[]; seen=set()
    for i,source in enumerate(srcs[:3]):
        ctx.step('Searching '+source,(i+.2)/len(srcs))
        try:
            for p in sources.search(source,query,inp.get('limit',12)):
                key=p.get('doi') or p.get('arxiv_id') or p['title'].lower()
                if key in seen: continue
                seen.add(key)
                p.update(rank=len(results)+1,screen='maybe',reason='Source search result; relevance needs researcher review.')
                results.append(p)
        except ToolError as exc: failures.append({'source':source,'reason':exc.message})
    if not results and len(failures)==len(srcs): raise ToolError('source_unavailable','; '.join(f['source']+': '+f['reason'] for f in failures),True)
    with db.tx(ctx.c):
        sid=db.add_node(ctx.c,'search',query,{'query':query,'expanded_queries':[query],'sources':srcs,
            'parent_search_id':inp.get('parent_search_id'),'launched_from':inp.get('launched_from'),
            'results':[],'source_failures':failures,'result_count':len(results)},origin='researcher',created_by='search.papers')
        for p in results:
            p['candidate_id']=sid+'-'+hashlib.sha256((p.get('doi') or p['title']).encode()).hexdigest()[:12]
            ctx.c.execute('INSERT INTO candidate VALUES(?,?,?)',(p['candidate_id'],sid,json.dumps(p)))
        db.update_props(ctx.c,sid,results=results)
        parent=inp.get('parent_search_id') or (inp.get('launched_from') or {}).get('node_id')
        if parent and db.get_node(ctx.c,parent): db.add_edge(ctx.c,sid,parent,'derived_from',1,origin='researcher',created_by='search.papers')
    return {'search_id':sid,'expanded_queries':[query],'results':results,'source_failures':failures}

def search_save(ctx, inp):
    ids=[]; old=[]
    with db.tx(ctx.c):
        for cid in inp['candidate_ids'][:50]:
            row=ctx.c.execute('SELECT * FROM candidate WHERE id=?',(cid,)).fetchone()
            if not row: raise ToolError('not_found','Candidate does not belong to this project: '+cid)
            p=json.loads(row['props']); key=p.get('doi') or p.get('arxiv_id') or p['title'].lower()
            existing=next((n for n in db.nodes(ctx.c,'paper') if n['props'].get('key')==key),None)
            if existing:
                old.append(existing['id']); pid=existing['id']
                search=db.get_node(ctx.c,row['search_id'])
                updated=[dict(x,paper_id=pid) if x['candidate_id']==cid else x for x in search['props']['results']]
                db.update_props(ctx.c,row['search_id'],results=updated)
                continue
            pid=db.add_node(ctx.c,'paper',p['title'],dict(p,key=key,full_text=False,extracted=False,via=row['search_id']),origin='published',review_status='unreviewed',created_by='search.save')
            if p.get('abstract'): ctx.c.execute('INSERT INTO passage VALUES(?,?,?,?)',(pid+'-p0',pid,0,p['abstract']))
            db.add_edge(ctx.c,pid,row['search_id'],'derived_from',1,origin='published',created_by='search.save')
            db.emit(ctx.c,'paper.added','search.save',[pid]); ids.append(pid)
            search=db.get_node(ctx.c,row['search_id'])
            updated=[dict(x,paper_id=pid) if x['candidate_id']==cid else x for x in search['props']['results']]
            db.update_props(ctx.c,row['search_id'],results=updated)
    return {'paper_ids':ids,'already_present':old,'warnings':['Saved available metadata and abstracts. Upload the PDF to analyze full text.']}

def search_resolve(ctx,inp):
    q=inp.get('doi') or inp.get('title')
    if not q: raise ToolError('invalid_input','Supply a DOI or title.')
    results=sources.search('openalex',q,3)
    ranked=sorted(results,key=lambda p:G.jaccard(q,p['title']),reverse=True)
    score=G.jaccard(q,ranked[0]['title']) if ranked else 0
    exact=bool(ranked and inp.get('doi') and inp['doi'].lower().replace('https://doi.org/','')==(ranked[0].get('doi') or '').lower())
    return {'match':ranked[0] if ranked and (exact or score>.55) else None,'title_similarity':score}

def search_summarize(ctx,inp):
    out=[]
    for pid in inp['paper_ids'][:20]:
        n=db.get_node(ctx.c,pid)
        if not n or n['type']!='paper': raise ToolError('not_found','Paper not found.')
        ps=db.passages(ctx.c,pid)
        if not ps: raise ToolError('invalid_input','No source text is available for this paper.')
        r=provider.complete(ctx,'summary','Return {problem,method,results,limitations}, each a string. Summarize supplied text only; say not reported when absent.',{'paper':n,'passages':ps[:10]})
        fields={k:str(r.get(k,'Not reported')) for k in ('problem','method','results','limitations')}
        with db.tx(ctx.c): db.update_props(ctx.c,pid,summary=fields,summary_provenance=ctx.provenance)
        out.append({'paper_id':pid,'fields':fields,'cached':ctx.provenance.get('cache_hit',False)})
    return {'summaries':out}

def graph_rebuild_links(ctx,inp):
    papers=db.nodes(ctx.c,'paper',False); added=0; cites=0
    with db.tx(ctx.c):
        for i,a in enumerate(papers):
            for b in papers[i+1:]:
                score=G.jaccard(node_text(a),node_text(b))
                if score>=.14:
                    before=len(db.edges(ctx.c,a['id'],'similar'))
                    db.add_edge(ctx.c,a['id'],b['id'],'similar',score,props={'note':'Keyword Jaccard similarity; not evidence of support.'},created_by='graph.rebuild_links')
                    added+=len(db.edges(ctx.c,a['id'],'similar'))>before
            for b in papers:
                if b['id']!=a['id'] and b['props'].get('openalex_id') in a['props'].get('references',[]):
                    db.add_edge(ctx.c,a['id'],b['id'],'cites',1,origin='published',created_by='graph.rebuild_links'); cites+=1
    return {'similar_added':added,'cites_added':cites,'unresolved_refs':[]}

def fieldmap_build(ctx,inp):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    import numpy as np
    papers=db.nodes(ctx.c,'paper',False)
    if not papers: raise ToolError('invalid_input','Import papers before building the field map.')
    if inp.get('algorithm','kmeans')!='kmeans': raise ToolError('invalid_input','This implementation supports kmeans.')
    ctx.step('Clustering actual document text with TF-IDF and silhouette selection',.3)
    vec=TfidfVectorizer(stop_words='english',max_features=5000)
    try: matrix=vec.fit_transform([node_text(n) for n in papers])
    except ValueError: raise ToolError('invalid_input','Not enough meaningful text to cluster.')
    labels=np.zeros(len(papers),dtype=int); best=None
    for k in range(2,min(7,len(papers))):
        trial=KMeans(n_clusters=k,random_state=42,n_init=10).fit_predict(matrix)
        if 1<len(set(trial))<len(papers):
            score=float(silhouette_score(matrix,trial))
            if best is None or score>best: best=score; labels=trial
    terms=vec.get_feature_names_out(); groups=[]
    with db.tx(ctx.c):
        # Replace computed memberships while retaining snapshot history.
        ctx.c.execute("DELETE FROM edge WHERE type='in_topic' AND created_by='fieldmap.build'")
        for label in sorted(set(labels)):
            indexes=np.where(labels==label)[0]; mean=np.asarray(matrix[indexes].mean(axis=0)).ravel()
            keywords=[str(terms[j]) for j in mean.argsort()[-4:][::-1]]
            title=' · '.join(keywords); key='|'.join(sorted(keywords))
            old=next((n for n in db.nodes(ctx.c,'topic') if n['props'].get('key')==key),None)
            tid=old['id'] if old else db.add_node(ctx.c,'topic',title,{'key':key},created_by='fieldmap.build')
            pids=[papers[int(i)]['id'] for i in indexes]
            db.update_props(ctx.c,tid,size=len(pids))
            for pid in pids: db.add_edge(ctx.c,pid,tid,'in_topic',1,props={'method':'TF-IDF/KMeans'},created_by='fieldmap.build')
            groups.append({'topic_id':tid,'key':key,'label':title,'size':len(pids),'paper_ids':pids})
        props={'k':len(groups),'silhouette':round(best,3) if best is not None else None,'topics':groups,'algorithm':'kmeans','backend':'TF-IDF'}
        sid=db.next_id(ctx.c,'snap'); ctx.c.execute('INSERT INTO snapshot VALUES(?,?,?)',(sid,db.now(),json.dumps(props)))
        db.emit(ctx.c,'fieldmap.updated','fieldmap.build',[sid],handled=True)
    return dict(props,snapshot_id=sid)

def fieldmap_assign(ctx,inp):
    data=fieldmap_build(ctx,{'algorithm':'kmeans'})
    return {'assignments':[{'paper_id':pid,'topic_id':t['topic_id'],'confidence':None} for t in data['topics'] for pid in t['paper_ids'] if pid in inp['paper_ids']],
            'rebuild_suggested':False,'method':'Recomputed deterministic TF-IDF clusters'}

def funding_identify(ctx,inp):
    name=inp.get('name','').strip()
    raw=sources.fetch('https://api.openalex.org/authors',{'search':name,'per-page':5})
    out=[]
    with db.tx(ctx.c):
        for a in raw.get('results',[]):
            props={'name':a['display_name'],'orcid':a.get('orcid'),'works_count':a.get('works_count'),
                   'topics':[t['display_name'] for t in a.get('topics',[])[:5]],'openalex_id':a['id'],
                   'affiliation':', '.join(x['display_name'] for x in a.get('last_known_institutions',[]))}
            rid=db.add_node(ctx.c,'researcher',a['display_name'],props,origin='published',review_status='unreviewed',created_by='funding.identify')
            out.append(dict(props,researcher_id=rid))
    return {'candidates':out}

def funding_find(ctx,inp):
    project=ctx.c.execute('SELECT question FROM project').fetchone()
    topic_nodes=[db.get_node(ctx.c,x) for x in inp.get('topic_ids',[])]
    terms=' '.join(n['title'] for n in topic_nodes if n) or (project['question'] if project else 'research')
    researcher=db.get_node(ctx.c,inp.get('researcher_id',''))
    if researcher and researcher['props'].get('topics'): terms=' '.join(researcher['props']['topics'][:2])
    query=' '.join(G.tokens(terms)[:5]); ctx.step('Querying current Grants.gov announcements',.3)
    grants=sources.grants(query,inp.get('top',10)); ranked=[]
    with db.tx(ctx.c):
        for g in grants:
            overlap=G.overlap(terms,g['title']); score=min(100,overlap*15)
            reason=f'{overlap} shared topic terms in announcement title. Eligibility and fit require review.'
            existing=next((n for n in db.nodes(ctx.c,'grant') if n['props'].get('opportunity_id')==g['opportunity_id']),None)
            props=dict(g,fit_score=score,reason=reason,score_method='keyword overlap',topics=terms)
            gid=existing['id'] if existing else db.add_node(ctx.c,'grant',g['title'],props,origin='published',review_status='unreviewed',created_by='funding.find')
            if existing: db.update_props(ctx.c,gid,**props)
            for n in topic_nodes:
                if n: db.add_edge(ctx.c,gid,n['id'],'funds',score/100,created_by='funding.find')
            ranked.append({'grant_id':gid,'fit_score':score,'reason':reason,'deadline':g['deadline']})
    return {'grant_ids':[r['grant_id'] for r in ranked],'ranked':sorted(ranked,key=lambda x:-x['fit_score']),
            'source_checked_at':db.now(),'usage':{'llm_calls':0,'cost_usd':0},'query':query}
