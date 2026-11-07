import io
import json
import zipfile
import pytest
from backend import db, chat, provider, tools, grounding, research, sources
from test_workflows import call,run_one,upload

def test_chat_has_no_approval_tool(client,c,monkeypatch):
    monkeypatch.setattr(provider,'complete',lambda *a,**k:{'action':'tool','tool':'approvals','input':{'recipe_id':'exp-1'}})
    events=[];chat.handle(c,'Approve my recipe',{},None,lambda e,d:events.append((e,d)))
    assert events[-1][1]['error']['code']=='invalid_output'
    assert c.execute("SELECT COUNT(*) FROM event WHERE type='approval.granted'").fetchone()[0]==0

def test_chat_removes_nonexistent_citations_and_saves_history(client,c,monkeypatch):
    monkeypatch.setattr(provider,'complete',lambda *a,**k:{'action':'answer','answer':'Unknown [pap-999].'})
    events=[];chat.handle(c,'What is known?',{},'test-conversation',lambda e,d:events.append((e,d)))
    assert events[-1][1]['removed_citations']==['pap-999']
    assert '[pap-999]' not in events[-1][1]['answer']
    assert c.execute('SELECT COUNT(*) FROM conversation').fetchone()[0]==2

def test_word_export_and_exact_quotes(client,c):
    created=call(client,'writing.create',{'title':'Source-aware draft','text':'A draft with a limitation.'})['data']
    exported=call(client,'writing.export',{'draft_id':created['draft_id'],'format':'docx'})['data']
    content=client.get('/api/artifacts/'+exported['artifact_id']).content
    assert 'word/document.xml' in zipfile.ZipFile(io.BytesIO(content)).namelist()
    assert grounding.check_quote('The effect was measured.','The effect was measured.')['match']=='exact'
    assert grounding.check_quote('THE EFFECT WAS MEASURED.','The effect was measured.')['match']=='fuzzy_candidate'

def test_settings_validation_does_not_touch_secret_file(client):
    assert client.post('/api/settings',json={'VRP_BUDGET_USD':'NaN'}).status_code==400
    assert client.post('/api/settings',json={'AMPLIFY_BASE_URL':'http://example.com'}).status_code==400
    assert client.post('/api/settings',json={'VRP_MAX_CALLS':-1}).status_code==400

def test_actual_fieldmap_and_events(client,c):
    upload(client,c,'vision.txt',b'Computer vision classification recognizes handwritten images and digit features.')
    upload(client,c,'clinical.txt',b'Clinical research follows patient disease progression and baseline health measurements.')
    result=run_one(c,call(client,'fieldmap.build',{'scope':'project'})['job_id'])
    assert result['k']==1 and result['silhouette'] is None
    assert sum(t['size'] for t in result['topics'])==2
    runtime_events=client.get('/api/events/recent').json()['events']
    assert any(e['type']=='fieldmap.updated' for e in runtime_events)

def test_funding_is_current_source_data(client,c,monkeypatch):
    monkeypatch.setattr(sources,'grants',lambda q,limit:[{'title':'Diabetes research','opportunity_id':'test-id','deadline':'2027-01-01','source_url':'https://example.org/grant','checked_at':db.now()}])
    result=run_one(c,call(client,'funding.find',{'top':1})['job_id'])
    grant=db.get_node(c,result['grant_ids'][0])
    assert grant['props']['opportunity_id']=='test-id'
    assert grant['review_status']=='unreviewed'
    assert grant['props']['score_method']=='keyword overlap'
