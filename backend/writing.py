"""Evidence-linked drafts, reviewer personas, diffs, reports and exports."""
import base64
import io
import json
from . import db, provider, evidence
from .tools import ToolError, ref_ids, split_sentences

def writing_flag_unsupported(ctx,inp):
    d=db.get_node(ctx.c,inp['draft_id'])
    if not d: raise ToolError('not_found','Draft not found.')
    checks=evidence.citation_checks(ctx.c,d['props'].get('text',''))
    return {'sentences':[dict(index=i,text=x['sentence'],reason=x.get('reason') or 'semantic_review_needed',cited_id=x['cited_id']) for i,x in enumerate(checks)],
            'total_sentences':len(split_sentences(d['props'].get('text','')))}

def chat_synthesize(ctx,inp):
    ids=inp.get('paper_ids') or [n['id'] for n in db.nodes(ctx.c,'paper',False)]
    if not ids: raise ToolError('invalid_input','Import source papers first.')
    selected=[n for n in db.nodes(ctx.c,include_dismissed=False) if n['id'] in ids or n['props'].get('paper_id') in ids or n['type']=='run']
    raw=provider.complete(ctx,'writing.synthesize','Return {title,text}. Write an evidence-linked research brief answering the question. Cite supplied graph IDs as [pap-1], [clm-1], [run-1]. Distinguish observations, hypotheses, uncertainty and proposed work. Include limitations. Never invent numbers, authors or findings. Write only from supplied records.',{'question':inp.get('question','Synthesize the project evidence'),'records':selected[:40]},3500)
    title=str(raw.get('title','Research brief')); text=str(raw.get('text',''))
    if not text.strip(): raise ToolError('invalid_output','The model did not return draft text.')
    allowed={n['id'] for n in selected}; unknown=set(ref_ids(text))-allowed
    if unknown: raise ToolError('invalid_output','Draft cited records outside the supplied evidence: '+', '.join(sorted(unknown)))
    with db.tx(ctx.c):
        did=db.add_node(ctx.c,'draft',title,{'text':text,'version':1,'kind':'synthesis','cited_node_ids':sorted(set(ref_ids(text))),
                         'provenance':dict(ctx.provenance),'source_ids':ids},created_by='chat.synthesize')
        for nid in set(ref_ids(text)): db.add_edge(ctx.c,did,nid,'cites',.5,created_by='chat.synthesize')
    flags=writing_flag_unsupported(ctx,{'draft_id':did})['sentences']
    return {'draft_id':did,'cited_node_ids':sorted(set(ref_ids(text))),'unsupported_sentences':flags,'revisions':0}

def writing_review(ctx,inp):
    draft=db.get_node(ctx.c,inp['draft_id'])
    if not draft or draft['type']!='draft': raise ToolError('not_found','Draft not found.')
    comments=[]; text=draft['props']['text']
    refs=[db.get_node(ctx.c,x) for x in set(ref_ids(text))]; refs=[r for r in refs if r]
    for persona in inp.get('personas',['methods','evidence','clarity','novelty'])[:4]:
        if persona not in ('methods','evidence','clarity','novelty'): raise ToolError('invalid_input','Unknown reviewer persona.')
        ctx.step('Reviewing '+persona)
        raw=provider.complete(ctx,'review.'+persona,'Act as the '+persona+' reviewer. Return {comments:[{text:"review comment",target:"exact substring of draft",fix:"suggested replacement",section:"..."}]}. Up to three comments. Ground objections in supplied records. Fixes cannot add new claims or citations.',{'draft':text,'records':refs},1800)
        for item in raw.get('comments',[])[:3]:
            if not isinstance(item,dict) or not item.get('target') or item['target'] not in text: continue
            fix=str(item.get('fix',''))
            if set(ref_ids(fix))-set(ref_ids(text)): continue
            comments.append(dict(item,id='c'+str(len(comments)+1),persona=persona,quote=item['target'],grounding='exact',paper_id=None,fix=fix))
    with db.tx(ctx.c):
        rid=db.add_node(ctx.c,'report','Review of '+draft['title'],{'kind':'review','draft_id':draft['id'],'comments':comments,'personas':inp.get('personas',[]),'provenance':dict(ctx.provenance)},created_by='writing.review')
        db.add_edge(ctx.c,rid,draft['id'],'about',1,created_by='writing.review')
    return {'review_id':rid,'comments':comments}

def writing_brief(ctx,inp):
    runs=[db.get_node(ctx.c,x) for x in inp.get('run_ids',[])] if inp.get('run_ids') else db.nodes(ctx.c,'run')[-1:]
    runs=[r for r in runs if r and r['type']=='run']
    if not runs: raise ToolError('not_found','No completed runs to brief.')
    lines=['# Experiment brief','', 'Computed results from approved recipes. These descriptive results do not establish causality.','']
    for r in runs:
        p=r['props']; lines += ['## '+r['title']+' ['+r['id']+']','',f"Output rows: {p['row_count']}. Recipe fingerprint: `{p['recipe_hash']}`.",'']
        for s in p['stats']: lines.append(f"- {s['name']}: {s['value']} (n={s['n']}).")
        lines+=['','```json',json.dumps(p['rows'][:10],indent=2),'```','']
        for d in p['diagnostics']:
            if d['level']!='trace': lines.append('- '+d['level']+': '+d['text'])
    text='\n'.join(lines)
    with db.tx(ctx.c):
        rid=db.add_node(ctx.c,'report','Run brief: '+', '.join(r['id'] for r in runs),{'kind':'brief','brief_kind':inp.get('kind','thread'),'text':text,'run_ids':[r['id'] for r in runs]},origin='researcher',created_by='writing.brief')
        aid=db.add_artifact(ctx.c,'brief',rid+'.md','text/markdown',text,rid); db.update_props(ctx.c,rid,artifact_id=aid)
        for r in runs: db.add_edge(ctx.c,rid,r['id'],'derived_from',1,origin='researcher',created_by='writing.brief')
    return {'report_id':rid,'artifact_id':aid}

def writing_export(ctx,inp):
    d=db.get_node(ctx.c,inp['draft_id'])
    if not d: raise ToolError('not_found','Draft not found.')
    refs=[]
    for nid in sorted(set(ref_ids(d['props'].get('text','')))):
        n=db.get_node(ctx.c,nid)
        if n: refs.append(f"[{nid}] {n['title']}. {n['props'].get('url') or n['props'].get('doi') or ''}")
    text='# '+d['title']+'\n\n'+d['props'].get('text','')+'\n\n## References\n\n'+'\n\n'.join(refs)
    fmt=inp.get('format','md')
    if fmt=='docx':
        from docx import Document
        document=Document()
        for line in text.splitlines():
            if line.startswith('# '): document.add_heading(line[2:],0)
            elif line.startswith('## '): document.add_heading(line[3:],1)
            else: document.add_paragraph(line)
        b=io.BytesIO(); document.save(b); content=base64.b64encode(b.getvalue()).decode(); mime='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    elif fmt=='md': content=text; mime='text/markdown'
    else: raise ToolError('invalid_input','Choose md or docx.')
    with db.tx(ctx.c): aid=db.add_artifact(ctx.c,'draft_export',d['id']+'.'+fmt,mime,content,d['id'])
    return {'artifact_id':aid}
