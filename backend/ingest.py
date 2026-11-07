"""Immutable content-addressed uploads, page extraction, and CSV profiling."""
import csv
import hashlib
import io
import json
from pathlib import Path
from . import db, recipe
from .tools import ToolError

EXTENSIONS={'.pdf','.txt','.md','.docx','.csv'}
MAX_BYTES=25_000_000

def stage(c, name, content, relative_path=''):
    name=Path(name.replace('\\','/')).name
    if Path(name).suffix.lower() not in EXTENSIONS:
        raise ToolError('invalid_input','Supported files: PDF, DOCX, TXT, Markdown and CSV.')
    if not content or len(content)>MAX_BYTES:
        raise ToolError('invalid_input','Each file must be nonempty and at most 25 MB.')
    sha=hashlib.sha256(content).hexdigest()
    uid='upl-'+sha[:24]
    path=Path(db.data_dir())/(sha+Path(name).suffix.lower())
    if not path.exists(): path.write_bytes(content)
    with db.tx(c):
        c.execute('INSERT OR IGNORE INTO upload VALUES(?,?,?,?,?,?,?)',(uid,name,str(path),sha,len(content),None,relative_path or name))
    return uid

def extract(path):
    path=Path(path)
    if path.suffix.lower()=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(path)
        if len(reader.pages)>500: raise ToolError('invalid_input','PDF limit is 500 pages per file.')
        return [(i+1,p.extract_text() or '') for i,p in enumerate(reader.pages)]
    if path.suffix.lower()=='.docx':
        from docx import Document
        return [(1,'\n'.join(p.text for p in Document(path).paragraphs))]
    return [(1,path.read_text(encoding='utf-8-sig'))]

def import_one(ctx, uid):
    c=ctx.c
    u=c.execute('SELECT * FROM upload WHERE id=?',(uid,)).fetchone()
    if not u: raise ToolError('not_found','Upload not found in this project.')
    if u['imported_id']: return u['imported_id'],True
    if Path(u['path']).suffix.lower()=='.csv':
        rows=recipe.load_csv(u['path'])
        if not rows or len(rows)>100_000: raise ToolError('invalid_input','CSV must contain 1–100,000 data rows.')
        columns=list(rows[0])
        if None in columns or len(columns)>200: raise ToolError('invalid_input','CSV must have a header and at most 200 columns.')
        name=Path(u['name']).stem+'_'+u['sha256'][:6]
        props={'name':name,'path':u['path'],'columns':columns,'rows':len(rows),'sha256':u['sha256'],
               'relative_path':u['relative_path'],'profile':[{'name':k,'missing':sum(r.get(k) in ('',None) for r in rows),
               'numeric':sum(isinstance(r.get(k),(int,float)) for r in rows)} for k in columns]}
        with db.tx(c):
            nid=db.add_node(c,'dataset',u['name'],props,origin='researcher',created_by='library.import')
            c.execute('UPDATE upload SET imported_id=? WHERE id=?',(nid,uid))
        return nid,False
    pages=extract(u['path'])
    if not any(text.strip() for _,text in pages):
        raise ToolError('invalid_input','No selectable text was found. This scanned document needs OCR before import.')
    if sum(len(t) for _,t in pages)>2_000_000: raise ToolError('invalid_input','Document text exceeds 2 million characters.')
    with db.tx(c):
        # Recheck after extraction to make concurrent imports idempotent.
        old=c.execute('SELECT imported_id FROM upload WHERE id=?',(uid,)).fetchone()[0]
        if old:return old,True
        nid=db.add_node(c,'paper',Path(u['name']).stem,{'key':u['sha256'],'authors':[],'year':'','abstract':pages[0][1][:1500],
            'full_text':True,'path':u['path'],'sha256':u['sha256'],'relative_path':u['relative_path'],
            'pages':len(pages),'extracted':False,'source':'upload','page_label':'page' if Path(u['path']).suffix.lower()=='.pdf' else 'text section'},
            origin='researcher',created_by='library.import')
        for page,text in pages:
            # Overlapping chunks preserve nearby evidence; stored quote offsets refer to these exact strings.
            for i,start in enumerate(range(0,len(text),5000)):
                c.execute('INSERT INTO passage VALUES(?,?,?,?)',(f'{nid}-p{page}-{i}',nid,page,text[start:start+6000]))
        c.execute('UPDATE upload SET imported_id=? WHERE id=?',(nid,uid))
        db.emit(c,'paper.added','library.import',[nid])
    return nid,False
