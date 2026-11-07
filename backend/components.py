"""Explicit component installation into the one shared tool registry."""
from . import tools, research, evidence, workbench, writing

def install():
    for module in (research,evidence,workbench,writing):
        for name,tool in tools.TOOLS.items():
            handler=getattr(module,name.replace('.','_'),None)
            if handler: tool.handler=handler
    tools.approval_check=workbench.approval_check
    tools.TOOLS['search.papers'].inputs['limit']['default']=10
    tools.TOOLS['search.papers'].inputs['sources']['default']=['openalex','arxiv']
    # Honest contract for a metadata/abstract import; PDF ingestion uses actual uploads.
    tools.TOOLS['search.save'].description='Save current source metadata and abstracts into the research graph. Upload full text separately.'
    tools.TOOLS['search.save'].inputs.pop('fetch_pdf',None)
    tools.TOOLS['funding.find'].inputs.pop('sweep',None)
    tools.TOOLS['funding.find'].inputs.pop('agent_loop',None)
    tools.TOOLS['funding.find'].description='Search current Grants.gov opportunities and screen title overlap with the project or researcher topics.'
    tools.TOOLS['fieldmap.assign'].description='Refresh actual TF-IDF topic memberships after an import.'
    tools.TOOLS['writing.flag_unsupported'].description='Flag missing citations and citations needing semantic review; IDs alone do not prove support.'
    tools.TOOLS['evidence.check_citations'].description='Judge draft citations against supplied evidence; no fabricated inter-rater statistics.'
    tools.TOOLS['experiment.propose'].inputs['dataset_ids']['default']=[]
    tools.TOOLS['evidence.compare'].inputs['max_pairs']['default']=8
    @tools.tool('experiment.create','C9 Experiments & Data',side_effect='write',desc='Create a researcher-authored bounded recipe; approval is still required.',
                inputs={'objective':tools.I('str',True),'dataset_ids':tools.I('list',True),'base':tools.I('str',True),'steps':tools.I('list',True)})
    def create(ctx,inp): return workbench.create_recipe(ctx,inp,inp)
    @tools.tool('writing.create','C10 Writing, Review & Reports',side_effect='write',desc='Create a researcher draft.',
                inputs={'title':tools.I('str',True),'text':tools.I('str',True)})
    def create_draft(ctx,inp):
        from . import db
        with db.tx(ctx.c):
            did=db.add_node(ctx.c,'draft',inp['title'],{'text':inp['text'],'version':1,'cited_node_ids':tools.ref_ids(inp['text'])},origin='researcher' if ctx.caller=='ui' else 'ai',created_by='writing.create')
        return {'draft_id':did}

install()
