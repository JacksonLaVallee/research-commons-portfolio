"""Source adapters: LitReview arXiv, Precedent OpenAlex/S2, GrantScout Grants.gov.

Normalized metadata only. An abstract is never labelled full text. Partial source
outages remain visible. No fabricated or fixture fallback is used.
"""
import hashlib
import json
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
import httpx
from . import db, provider
from .tools import ToolError

ARXIV_LOCK=threading.Lock()
ARXIV_LAST=0.0

def fetch(url, params=None, payload=None):
    try:
        cfg=provider.config()
        headers={'User-Agent':'VanderbiltResearchCommons/1.0 (academic research)'}
        if 'api.openalex.org' in url and cfg.get('OPENALEX_API_KEY'): headers['Authorization']='Bearer '+cfg['OPENALEX_API_KEY']
        if 'api.semanticscholar.org' in url and cfg.get('S2_API_KEY'): headers['x-api-key']=cfg['S2_API_KEY']
        with httpx.Client(timeout=25, follow_redirects=True) as client:
            r=client.request('POST' if payload is not None else 'GET',url,params=params,json=payload,headers=headers)
            r.raise_for_status()
            if len(r.content)>8_000_000: raise ValueError('Response too large')
            return r.text if 'export.arxiv.org' in url else r.json()
    except (httpx.HTTPError,ValueError) as exc:
        code=exc.response.status_code if isinstance(exc,httpx.HTTPStatusError) else 'network/format'
        raise ToolError('source_unavailable',f'Source request failed ({code}). Try another source or retry later.',True) from None

def paper(title, authors, year, abstract, source, url, **extra):
    return dict(title=title,authors=authors,year=year,abstract=abstract or '',source=source,url=url,**extra)

def search(source, query, limit=12):
    global ARXIV_LAST
    limit=max(1,min(50,limit))
    if source=='openalex':
        data=fetch('https://api.openalex.org/works',{'search':query,'per-page':limit})
        out=[]
        for w in data.get('results',[]):
            inv=w.get('abstract_inverted_index') or {}
            positions={p:word for word,ps in inv.items() for p in ps}
            abstract=' '.join(positions[k] for k in sorted(positions))
            loc=w.get('primary_location') or {}
            out.append(paper(w.get('title','Untitled'),[a['author']['display_name'] for a in w.get('authorships',[])],w.get('publication_year'),
                abstract,source,w.get('doi') or w['id'],doi=(w.get('doi') or '').replace('https://doi.org/',''),openalex_id=w['id'],
                pdf_url=loc.get('pdf_url'),venue=(loc.get('source') or {}).get('display_name',''),references=w.get('referenced_works',[])))
        return out
    if source=='semantic_scholar':
        data=fetch('https://api.semanticscholar.org/graph/v1/paper/search',{'query':query,'limit':limit,
            'fields':'title,authors,year,abstract,url,externalIds,openAccessPdf,venue'})
        return [paper(w['title'],[a['name'] for a in w.get('authors',[])],w.get('year'),w.get('abstract'),source,w.get('url'),
                doi=(w.get('externalIds') or {}).get('DOI'),pdf_url=(w.get('openAccessPdf') or {}).get('url'),venue=w.get('venue','')) for w in data.get('data',[])]
    if source=='arxiv':
        with ARXIV_LOCK:
            time.sleep(max(0,3-(time.monotonic()-ARXIV_LAST)))
            try: xml=fetch('https://export.arxiv.org/api/query',{'search_query':query if ':' in query else 'all:'+query,'max_results':limit})
            finally: ARXIV_LAST=time.monotonic()
        ns={'a':'http://www.w3.org/2005/Atom'}
        out=[]
        for e in ET.fromstring(xml).findall('a:entry',ns):
            txt=lambda tag: ' '.join((e.findtext('a:'+tag,'',ns) or '').split())
            out.append(paper(txt('title'),[a.findtext('a:name','',ns) for a in e.findall('a:author',ns)],txt('published')[:4],txt('summary'),source,txt('id'),
                             arxiv_id=txt('id').split('/abs/')[-1],venue='arXiv',pdf_url=txt('id').replace('/abs/','/pdf/')))
        return out
    raise ToolError('invalid_input','Unknown literature source: '+source)

def grants(query, limit=10):
    raw=fetch('https://api.grants.gov/v1/api/search2',payload={'rows':max(1,min(25,limit)), 'keyword':query,'oppStatuses':'forecasted|posted'})
    if raw.get('errorcode') not in (0,None): raise ToolError('source_unavailable','Grants.gov rejected the search.',True)
    out=[]
    for h in raw.get('data',{}).get('oppHits',[]):
        out.append({'opportunity_id':str(h['id']),'title':h.get('title','Untitled'),'sponsor':h.get('agencyName') or h.get('agency',''),
                    'deadline':h.get('closeDate') or 'Not specified','status':h.get('oppStatus'),'eligibility':'Verify in the official announcement',
                    'source_url':'https://www.grants.gov/search-results-detail/'+str(h['id']), 'checked_at':db.now()})
    return out
