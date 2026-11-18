import json
from pathlib import Path
from backend import core as db,pipeline
from backend.contracts import ImportRequest


def test_quota_tests_and_failures_release_slots(client):
    s=db.settings();s.daily_limit=1;db.put_setting('settings',s.model_dump())
    for _ in range(3):
        assert client.post('/api/test-video',json={}).status_code==200
    assert db.production_usage()==0
    a=pipeline.create_video(ImportRequest(url='https://www.youtube.com/watch?v=abcdefghijk'))
    assert db.production_usage()==1
    assert client.post('/api/import',json={'url':'https://www.youtube.com/watch?v=abcdefghija'}).status_code==409
    db.execute("UPDATE videos SET status='REJECTED' WHERE id=:id",{'id':a})
    assert db.production_usage()==0
    assert client.post('/api/import',json={'url':'https://www.youtube.com/watch?v=abcdefghija'}).status_code==200
    assert db.production_usage()==1


def test_rejection_history_and_manual_decision(client,monkeypatch):
    v=pipeline.create_video(test=True)
    def fake_render(video,script,attempt=1):
        path=db.ROOT/'videos/final'/v/f'attempt-{attempt:02d}.mp4'
        path.parent.mkdir(parents=True,exist_ok=True)
        path.write_bytes(b'synthetic-preview-file')
        return path
    monkeypatch.setattr(pipeline.media,'render',fake_render)
    monkeypatch.setattr(pipeline,'evaluate',lambda *a:{'verdict':'REVISAR','corrections':['Sem prova visual independente de gameplay de GTA 6.'],
        'reason_full':'Sem prova visual independente de gameplay de GTA 6. ' + 'detalhe '*500,
        'score':5.0,'criteria':{'accuracy':{'name':'Exatidão','score':5,'min_score':6,'weight':1,'enabled':True}}})
    monkeypatch.setattr(pipeline,'distribute',lambda *a:None)
    monkeypatch.setattr(pipeline.media,'technical_check',lambda *a:{'valid':True,'failures':[]})
    pipeline.run_pipeline(v)
    result=client.get('/api/videos/'+v+'/attempts').json()['attempts']
    assert len(result)==5 and all(x['render_available'] for x in result)
    assert len(result[0]['details']['reason_full'])>1500
    assert client.get('/api/files/'+v+'?attempt=2').status_code==200
    assert db.rows('SELECT status FROM videos WHERE id=:id',{'id':v})[0]['status']=='AWAITING_MANUAL_DECISION'
    approval=client.post('/api/videos/'+v+'/decision',json={'action':'approve'})
    assert approval.status_code==200
    row=db.rows('SELECT status,manual_by,manual_at,manual_decision FROM videos WHERE id=:id',{'id':v})[0]
    assert row['status']=='APPROVED' and row['manual_decision']=='approved'
    assert row['manual_by']=='local_operator' and row['manual_at']


def test_discard_stops_pipeline_and_respects_running_state(client):
    v=pipeline.create_video(test=True)
    response=client.post('/api/videos/'+v+'/decision',json={'action':'discard'})
    assert response.status_code==200
    assert db.rows('SELECT status FROM videos WHERE id=:id',{'id':v})[0]['status']=='DISCARDED'
    pipeline.run_pipeline(v)
    assert db.rows('SELECT COUNT(*) AS n FROM video_attempts')[0]['n']==0
    assert client.post('/api/videos/'+v+'/decision',json={'action':'approve'}).status_code==409


def test_criterion_settings_can_be_edited(client):
    config=client.get('/api/settings').json()
    criteria=config['evaluation_criteria']
    assert len(criteria)>=10
    criteria['hook']['min_score']=7.5
    criteria['rhythm']['enabled']=False
    config['max_review_attempts']=4
    assert client.put('/api/settings',json=config).status_code==200
    saved=client.get('/api/settings').json()
    assert saved['max_review_attempts']==4
    assert saved['evaluation_criteria']['hook']['min_score']==7.5
    assert saved['evaluation_criteria']['rhythm']['enabled'] is False
