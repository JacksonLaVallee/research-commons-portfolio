"""Grounded extraction, guarded cross-paper comparisons and assumption audit.

Exact source validation and comparison safeguards are reused directly from
Jackson LaVallee's Evidence Mapper (evidence_rules.py).
"""
import json
from . import db, provider, evidence_rules as rules, grounding as G, research
from .tools import ToolError, ref_ids, split_sentences

EXTRACTION = '''Extract up to five central research findings from these passages. Return:
{"claims":[{"finding":"...","direction":"positive|negative|null|mixed|unclear",
"evidence":{"passage_id":"supplied ID","quote":"verbatim text"},
"fields":{"population":{"value":"...","evidence":{"passage_id":"...","quote":"..."}},
"intervention":{},"comparator":{},"outcome":{},"timeframe":{},"design":{}},
"tags":{"population":"short tag","intervention":"short tag","outcome":"short tag"},
"limitations":[{"text":"...","evidence":{"passage_id":"...","quote":"..."}}]}],
"assumptions":[{"text":"...","explicit":true,"evidence":{"passage_id":"...","quote":"verbatim text"}}]}
Each field needs its own exact evidence; leave absent fields empty. Extract assumptions only when a
passage actually asserts or relies on them. Quote occurrence does not prove the interpretation correct.
Do not invent full-text results from abstracts. An empty array is valid.'''

def evidence_extract(ctx,inp):
    out={'claim_ids':[],'assumption_ids':[],'method_ids':[],'dataset_ids':[],'rejected':[],
         'grounding':{'exact':0,'fuzzy_candidate':0,'dropped':0}}
    for pid in inp['paper_ids'][:50]:
        paper=db.get_node(ctx.c,pid)
        if not paper or paper['type']!='paper': raise ToolError('not_found','Paper not found: '+pid)
        if paper['props'].get('extracted'): continue
        passages=db.passages(ctx.c,pid)
        if not passages:
            out['rejected'].append({'paper_id':pid,'reason':'No source text available; import full text.'}); continue
        for start in range(0,len(passages),6):
            batch=passages[start:start+6]
            ctx.step(f'Extracting {pid}: passages {start+1}–{start+len(batch)} of {len(passages)}',start/len(passages))
            raw=provider.complete(ctx,'evidence.extract',EXTRACTION,{'title':paper['title'],'full_text':paper['props'].get('full_text'), 'passages':batch},4000)
            try: accepted,rejected=rules.validate_extraction(raw,{'id':pid,'passages':batch})
            except ValueError as exc: raise ToolError('invalid_output',str(exc))
            out['rejected'] += [dict(x,paper_id=pid) for x in rejected]
            out['grounding']['dropped']+=len(rejected)
            with db.tx(ctx.c):
                for item in accepted:
                    if any(n['props'].get('key')==item['id'] for n in db.nodes(ctx.c,'claim')): continue
                    proof=item['evidence']; props=dict(item,key=item['id'],text=item['finding'],paper_id=pid,
                        quote=proof['quote'],passage_id=proof['passage_id'],page=proof['page'],grounding='exact',
                        conditions={k:v['value'] for k,v in item['fields'].items()},provenance=dict(ctx.provenance))
                    cid=db.add_node(ctx.c,'claim',item['finding'],props,created_by='evidence.extract')
                    db.add_edge(ctx.c,cid,pid,'derived_from',1,passage_id=proof['passage_id'],created_by='evidence.extract')
                    out['claim_ids'].append(cid); out['grounding']['exact']+=1
                for item in raw.get('assumptions',[])[:4]:
                    if not isinstance(item,dict) or not isinstance(item.get('text'),str): continue
                    proof=rules.validate_quote(item.get('evidence'),batch)
                    if not proof: out['grounding']['dropped']+=1; continue
                    key=rules.stable_id(pid,item['text'],proof['quote'])
                    if any(n['props'].get('key')==key for n in db.nodes(ctx.c,'assumption')): continue
                    quote=dict(proof,paper_id=pid,grounding='exact')
                    aid=db.add_node(ctx.c,'assumption',item['text'],dict(quote,key=key,text=item['text'],quotes=[quote],explicit=item.get('explicit',True),provenance=dict(ctx.provenance)),created_by='evidence.extract')
                    db.add_edge(ctx.c,pid,aid,'assumes',.5,passage_id=proof['passage_id'],created_by='evidence.extract')
                    out['assumption_ids'].append(aid); out['grounding']['exact']+=1
        with db.tx(ctx.c):
            db.update_props(ctx.c,pid,extracted=True,extraction_provenance=dict(ctx.provenance))
            db.emit(ctx.c,'claims.added','evidence.extract',[n['id'] for n in db.nodes(ctx.c,'claim') if n['props'].get('paper_id')==pid])
    g=out['grounding']; g['rate']=g['exact']/max(1,g['exact']+g['dropped'])
    return out

def evidence_compare(ctx,inp):
    all_claims=db.nodes(ctx.c,'claim',False)
    if inp.get('topic_id'):
        paper_ids={e['src_id'] for e in db.edges(ctx.c,inp['topic_id'],'in_topic') if e['review_status']!='dismissed'}
        all_claims=[n for n in all_claims if n['props'].get('paper_id') in paper_ids]
    claims={n['id']:dict(n['props'],id=n['id'],document_id=n['props'].get('paper_id'),finding=n['title']) for n in all_claims}
    scope=set(inp.get('claim_ids') or claims)
    pairs=[p for p in rules.candidate_pairs(list(claims.values()),100) if p[1] in scope or p[2] in scope]
    out={'edge_ids':[],'labels':{},'not_comparable':[]}
    label_map={'consistent':'equivalent','mixed':'measured_gap','potential_conflict':'conflict','not_comparable':'scope_difference','uncertain':'unresolved'}
    for _,aid,bid in pairs[:min(12,max(0,inp.get('max_pairs',8)))]:
        existing=next((e for e in db.edges(ctx.c,aid) if e['dst_id']==bid and e['props'].get('comparison_version')=='1'),None)
        if existing: continue
        a,b=claims[aid],claims[bid]
        raw=provider.complete(ctx,'evidence.compare','Compare studies. Return {relation:"consistent|mixed|potential_conflict|not_comparable|uncertain", axes:{population:"matched|different|unknown",intervention:"...",comparator:"...",outcome:"...",timeframe:"...",design:"..."}, explanation:"...",hypotheses:[]}. Judge comparability only from cited fields.',{'a':a,'b':b})
        result=rules.guard_comparison(a,b,raw); label=label_map[result['relation']]
        with db.tx(ctx.c):
            eid=db.add_edge(ctx.c,aid,bid,label,.5,props=dict(result,note=result['explanation'],conditions=result['axes'],comparison_version='1',provenance=dict(ctx.provenance)),created_by='evidence.compare')
        out['edge_ids'].append(eid); out['labels'][label]=out['labels'].get(label,0)+1
        if label in ('scope_difference','unresolved'): out['not_comparable'].append({'a':aid,'b':bid,'reason':'; '.join(result['guard_notes'])})
    return out

def citation_checks(c,text):
    checks=[]
    for sentence in split_sentences(text):
        if not sentence.strip() or sentence.lstrip().startswith('#'): continue
        ids=ref_ids(sentence)
        if not ids:
            checks.append({'sentence':sentence,'cited_id':None,'verdict':'UNVERIFIABLE','reason':'no_citation'}); continue
        for nid in ids:
            n=db.get_node(c,nid)
            reason='missing_source' if not n else 'dismissed_source' if n['review_status']=='dismissed' else None
            checks.append({'sentence':sentence,'cited_id':nid,'verdict':'UNVERIFIABLE' if reason else 'NEEDS_REVIEW',
                           'reason':reason,'basis':'source existence only; not semantic verification'})
    return checks

def evidence_check_citations(ctx,inp):
    if not inp.get('draft_id'):
        raise ToolError('invalid_input','Choose a draft. Uploaded documents do not contain canonical graph citation IDs until linked.')
    draft=db.get_node(ctx.c,inp['draft_id'])
    if not draft: raise ToolError('not_found','Draft not found.')
    checks=citation_checks(ctx.c,draft['props']['text']); pending=[]
    for i,x in enumerate(checks):
        if x['verdict']=='NEEDS_REVIEW':
            n=db.get_node(ctx.c,x['cited_id']); ps=db.passages(ctx.c,n['id']) if n['type']=='paper' else []
            pending.append({'index':i,'sentence':x['sentence'],'source':n,'passages':ps[:4]})
    if pending:
        raw=provider.complete(ctx,'citation.judge','Return {checks:[{index:0,verdict:"SUPPORTED|PARTIAL|NOT|UNVERIFIABLE",why:"..."}]}. Does each provided source actually support the sentence? Abstract-only and absent evidence require caution. Do not infer support from a citation ID.',pending[:25])
        for item in raw.get('checks',[]):
            if not isinstance(item,dict): continue
            i=item.get('index'); verdict=item.get('verdict')
            if i not in [p['index'] for p in pending[:25]] or verdict not in ('SUPPORTED','PARTIAL','NOT','UNVERIFIABLE'): continue
            checks[i].update(verdict=verdict,why=str(item.get('why','')),reason=None if verdict=='SUPPORTED' else 'citation_unsupported',basis='model judgment; researcher review required')
    with db.tx(ctx.c): db.update_props(ctx.c,draft['id'],citation_checks=checks)
    return {'checks':checks,'kappa':None,'kappa_note':'One model judgment; inter-rater agreement was not measured.'}

def gaps_find(ctx,inp):
    budget=inp.get('budget') or {'llm_calls':3,'searches':1}
    limit=max(0,min(6,int(budget.get('llm_calls',3)))); searches=max(0,min(3,int(budget.get('searches',1))))
    if limit<2: raise ToolError('invalid_input','The audit requires at least two calls: proposal and verification.')
    nodes=[n for n in db.nodes(ctx.c,include_dismissed=False) if n['type'] in ('claim','assumption')]
    scope=set(inp.get('scope_ids') or [])
    if scope: nodes=[n for n in nodes if n['id'] in scope or n['props'].get('paper_id') in scope]
    if not nodes: raise ToolError('invalid_input','Extract claims before auditing assumptions.')
    raw=provider.complete(ctx,'gaps.propose','Return {gaps:[{title,rationale,gap_type:"missing_link|untested_condition|method_not_carried_over|contradiction",evidence_ids:[IDs],search_query}]}. Propose at most 3 testable gaps in this supplied corpus. Missing evidence here is not proof of absence in all literature.',nodes[:35])
    proposed=raw.get('gaps',[])[:3]; out={'gap_ids':[],'abstained':[],'searches_run':[],'budget':{'llm_calls':limit,'searches':searches},'budget_used':{'llm_calls':1,'searches':0}}
    allowed={n['id']:n for n in nodes}
    for gap in proposed:
        if not isinstance(gap,dict): continue
        refs=[x for x in gap.get('evidence_ids',[]) if x in allowed]
        if not refs or out['budget_used']['llm_calls']>=limit: out['abstained'].append({'title':gap.get('title','Gap'),'reason':'Missing evidence IDs or call budget exhausted.'}); continue
        if inp.get('gap_types') and gap.get('gap_type') not in inp['gap_types']: continue
        retrieved=[]
        query=str(gap.get('search_query') or gap.get('title',''))
        ps=[dict(r) for r in ctx.c.execute('SELECT * FROM passage')]
        hits=G.bm25(query,[(p['id'],p['text']) for p in ps])[:5]
        retrieved=[p for pid,_ in hits for p in ps if p['id']==pid]
        literature=None
        if inp.get('check_literature') and out['budget_used']['searches']<searches:
            try:
                result=research.search_papers(ctx,{'query':query,'sources':['openalex'],'limit':5})
                out['searches_run'].append(result['search_id']); literature={'search_id':result['search_id'],'possible_matches':result['results']}
            except ToolError as exc: gap['search_warning']=exc.message
            out['budget_used']['searches']+=1
        verified=provider.complete(ctx,'gaps.verify','Return {keep:true|false,rationale:"...",status:"open|partly_addressed|addressed"}. Reconsider the proposed gap against the retrieved context and search abstracts. Reject unsupported interpretation. Scope absence claims to the checked corpus.',{'proposal':gap,'sources':[allowed[r] for r in refs],'retrieved':retrieved,'literature':literature})
        out['budget_used']['llm_calls']+=1
        if verified.get('keep') is not True:
            out['abstained'].append({'title':gap.get('title','Gap'),'reason':str(verified.get('rationale','Insufficient support'))}); continue
        items=[{'node_id':r,'quote':allowed[r]['props'].get('quote'),'passage_id':allowed[r]['props'].get('passage_id')} for r in refs]
        props=dict(gap,rationale=str(verified.get('rationale','')),status=verified.get('status','open'),evidence=items,evidence_ids=refs,
                   literature=literature,budget_used=dict(out['budget_used']),provenance=dict(ctx.provenance))
        if props['status'] not in ('open','partly_addressed','addressed'): props['status']='open'
        with db.tx(ctx.c):
            gid=db.add_node(ctx.c,'gap',str(gap.get('title','Research gap')),props,created_by='gaps.find')
            for rid in refs: db.add_edge(ctx.c,gid,rid,'about',.5,created_by='gaps.find')
        out['gap_ids'].append(gid)
    return out

def gaps_explain(ctx,inp):
    n=db.get_node(ctx.c,inp['gap_id'])
    if not n or n['type']!='gap': raise ToolError('not_found','Gap not found.')
    items=n['props'].get('evidence',[])
    exact=sum(bool(i.get('quote') and i.get('passage_id')) for i in items)
    return {'gap':n,'evidence':items,'searches':[],'grounding':{'exact':exact,'fuzzy_candidate':0,'none':len(items)-exact}}
