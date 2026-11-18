import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from pydantic import ValidationError
from backend import core as db, pipeline, media, worker, integrations
from backend.contracts import ImportRequest, ProfileRequest, Handoff, Script, platform_url


def test_setup_and_auth(client):
    assert client.get('/health').status_code == 200
    assert client.get('/api/state', headers={'Authorization': 'Bearer invalid'}).status_code == 401
    config = client.get('/api/settings').json()
    config['channel'] = 'Meu canal'
    assert client.put('/api/settings', json=config).status_code == 200
    assert client.get('/api/settings').json()['configured'] is True
    assert client.put('/api/secrets', json={'name':'youtube_api_key','value':'private-key'}).status_code == 200
    assert 'private-key' not in client.get('/api/state').text
    assert db.secret('youtube_api_key') == 'private-key'
    assert 'private-key' not in db.get_setting('secret:youtube_api_key')


@pytest.mark.parametrize('url', ['http://youtube.com/watch?v=abcdefghijk','https://youtube.com.evil.org/watch?v=abcdefghijk','https://127.0.0.1/video','https://youtube.com@evil.org/watch?v=abcdefghijk','https://youtube.com:444/watch?v=abcdefghijk','https://youtu.be/short','file:///etc/passwd'])
def test_bad_urls(url):
    with pytest.raises(ValueError):
        platform_url(url)


def test_canonical_dedup_and_rights(client):
    req = {'url':'https://youtu.be/abcdefghijk?tracking=yes'}
    a = client.post('/api/import',json=req).json()['id']
    b = client.post('/api/import',json={'url':'https://www.youtube.com/watch?v=abcdefghijk'}).json()['id']
    assert a == b
    assert len(db.rows('SELECT * FROM jobs')) == 1
    assert client.post('/api/import',json={**req,'rights':'AUTHORIZED'}).status_code == 422
    with pytest.raises(integrations.IntegrationError):
        integrations.download_authorized({'rights':'REFERENCE_ONLY','evidence':''})


def test_daily_limit_and_stop(client):
    config = db.settings(); config.daily_limit=1; db.put_setting('settings',config.model_dump())
    assert client.post('/api/test-video',json={}).status_code == 200
    assert client.post('/api/test-video',json={}).status_code == 200
    config.emergency_stop=True; db.put_setting('settings',config.model_dump())
    assert client.post('/api/test-video',json={}).status_code == 409


def test_profile_management(client):
    body={'url':'https://www.youtube.com/@RockstarGames','interval_minutes':60,'enabled':True,'priority':3}
    assert client.post('/api/profiles',json=body).status_code == 200
    profile = db.rows('SELECT * FROM profiles')[0]
    assert client.post('/api/profiles/'+profile['id']+'/scan',json={}).status_code == 200
    assert client.post('/api/profiles',json={**body,'enabled':False}).status_code == 200
    assert len(db.rows('SELECT * FROM profiles'))==1
    assert client.delete('/api/profiles/'+profile['id']).status_code==200


def test_cache_expiration_and_notifications():
    db.cache_set('one',{'value':3},10)
    assert db.cache_get('one') == {'value':3}
    db.cache_set('old',{},-1)
    assert db.cache_get('old') is None
    db.notify('event','a'); db.notify('event','a')
    assert len(db.rows('SELECT * FROM notifications')) == 1


def test_handoff_is_atomic_valid_and_isolated():
    id = pipeline.create_video(test=True)
    db.artifact(id,'diretor',summary='Plano pronto.',next_agent='cacador')
    h = db.read_artifact(id,'diretor')
    assert h.id == id and h.proximo_agente=='cacador'
    assert not list((db.ROOT/'handoff'/id).glob('*.tmp'))
    with pytest.raises(ValidationError):
        Handoff(id='bad',run_id=db.uid(),status='CONCLUIDO',proximo_agente='editor',resumo='ok',arquivos=[])


def test_persistent_queue_leases_and_concurrency():
    db.enqueue('maintenance',unique_key='stable')
    db.enqueue('maintenance',unique_key='stable')
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(db.claim,['a','b']))
    assert sum(x is not None for x in results)==1
    db.execute('UPDATE jobs SET lease=0')
    db.engine.dispose()  # reconnect simulates process restart, preserving persistent state
    assert db.claim('after-restart') is not None


def test_metadata_cache_and_score(monkeypatch):
    db.set_secret('youtube_api_key', 'fixture-key')
    calls=[]
    def yt(resource,params):
        calls.append(resource)
        return {'items':[{'snippet':{'title':'GTA 6','publishedAt':'2026-11-17T00:00:00Z'},'statistics':{'viewCount':'100','likeCount':'5'},'contentDetails':{},'status':{}}]}
    monkeypatch.setattr(integrations,'youtube_get',yt)
    url='https://www.youtube.com/watch?v=abcdefghijk'
    assert integrations.youtube_metadata(url)['metrics']['viewCount']==100
    integrations.youtube_metadata(url)
    assert len(calls)==1
    assert integrations.viral_score({'metrics':{}}) is None


def test_revisions_capped(monkeypatch):
    id=pipeline.create_video(test=True)
    monkeypatch.setattr(media,'render',lambda v,s,attempt=1:db.ROOT/'fake.mp4')
    calls=[]
    def evaluate(*args):
        calls.append(1)
        return {'verdict':'REVISAR','corrections':['Ajustar roteiro.']}
    monkeypatch.setattr(pipeline,'evaluate',evaluate)
    pipeline.run_pipeline(id)
    assert len(calls)==5
    video=db.rows('SELECT * FROM videos')[0]
    assert video['revision']==5 and video['status']=='AWAITING_MANUAL_DECISION'


def test_editor_ambiguity_returns_to_writer_with_limit(monkeypatch):
    id=pipeline.create_video(test=True)
    calls=[]
    def fail(video,script,attempt=1):
        calls.append(1)
        raise media.BriefingError('Corte excede a duração.')
    monkeypatch.setattr(media,'render',fail)
    pipeline.run_pipeline(id)
    assert len(calls)==5
    assert db.read_artifact(id,'editor').proximo_agente=='escritor'
    assert db.rows('SELECT status FROM videos')[0]['status']=='AWAITING_MANUAL_DECISION'


def test_technical_invalid_blocks(monkeypatch,tmp_path):
    id=pipeline.create_video(test=True); v=db.rows('SELECT * FROM videos')[0]
    pipeline.hunt(v); script=pipeline.write_script(v)
    monkeypatch.setattr(media,'technical_check',lambda *args:{'valid':False,'failures':['Inválido']})
    assert pipeline.evaluate(v,script,tmp_path/'bad.mp4')['verdict']=='REPROVADO'
    with pytest.raises(integrations.IntegrationError):
        pipeline.distribute(id)


def test_manual_fallback_idempotency_retention(client):
    id=pipeline.create_video(test=True); v=db.rows('SELECT * FROM videos')[0]
    pipeline.hunt(v); pipeline.write_script(v)
    final=db.ROOT/'videos/final'/f'{id}.mp4'; final.write_bytes(b'test-fixture-not-real-video')
    db.artifact(id,'avaliador',data={'verdict':'APROVADO','test_only':True})
    db.execute("UPDATE videos SET approved=1,status='APPROVED',final_path=:path,updated=0 WHERE id=:id",dict(id=id,path=str(final.relative_to(db.ROOT))))
    pipeline.distribute(id);pipeline.distribute(id)
    pubs=db.rows('SELECT * FROM publications')
    assert len(pubs)==3 and all(p['status']=='AGUARDANDO_PUBLICACAO_MANUAL' for p in pubs)
    assert len(db.rows('SELECT * FROM notifications'))==3
    worker.cleanup()
    assert final.exists() and all((db.ROOT/p['output_path']).exists() for p in pubs)
    assert client.post('/api/publications/'+pubs[0]['id']+'/confirm',json={'url':'https://www.youtube.com/watch?v=abcdefghijk'}).status_code==409
    assert db.rows('SELECT * FROM videos')


def test_failure_backoff(monkeypatch):
    db.enqueue('maintenance')
    monkeypatch.setattr(worker,'scheduler',lambda:None)
    monkeypatch.setattr(worker,'perform',lambda job:(_ for _ in ()).throw(integrations.IntegrationError('Falha controlada')))
    for i in range(3):
        worker.tick()
        db.execute('UPDATE jobs SET due=0')
    job=db.rows('SELECT * FROM jobs')[0]
    assert job['status']=='FAILED' and job['attempts']==3
    assert len(db.rows('SELECT * FROM notifications'))==1


def test_script_timestamps():
    with pytest.raises(ValidationError):
        Script(title='a',hook='b',description='c',hashtags=[],template='gta-news',duration=10,scenes=[
            {'start':0,'end':4,'text':'a','narration':'a','source_id':'x'},
            {'start':5,'end':10,'text':'b','narration':'b','source_id':'x'}])


def test_budget_enforced_before_model(monkeypatch):
    config=db.settings();config.routes['escritor'].model='local';config.daily_tokens=1000
    db.put_setting('settings',config.model_dump())
    with pytest.raises(integrations.IntegrationError,match='Orçamento'):
        integrations.llm('escritor',None,{'data':'x'*2000},{})


def test_file_path_boundary(tmp_path):
    with pytest.raises(ValueError):
        db.safe_file('../../outside')


def test_retry_model_refunds_rejected_call_and_uses_reported_tokens(monkeypatch):
    config=db.settings();config.routes['escritor'].model='primary';config.routes['escritor'].fallback_model='fallback'
    config.daily_tokens=100000;db.put_setting('settings',config.model_dump())
    calls=[]
    class Response:
        def json(self):
            return {'choices':[{'message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':10}}
    def request(*args,**kwargs):
        calls.append(kwargs['json']['model'])
        if len(calls)==1:
            raise integrations.IntegrationError('Integração respondeu HTTP 429.')
        return Response()
    monkeypatch.setattr(integrations,'request',request)
    result=integrations.llm('escritor',None,{'data':'hello'},{})
    assert result['ok'] and calls==['primary','fallback']
    assert db.rows('SELECT * FROM usage')[0]['tokens'] == 10


def test_missing_metrics_stay_null(monkeypatch):
    id=pipeline.create_video(test=True)
    db.execute("INSERT INTO publications(id,video_id,platform,status,external_id) VALUES ('pub',:video,'youtube','PUBLICADO','abcdefghijk')",{'video':id})
    monkeypatch.setattr(integrations,'youtube_get',lambda *a:{'items':[{'statistics':{'viewCount':'12'}}]})
    integrations.collect_metrics();integrations.collect_metrics()
    metrics=db.rows('SELECT * FROM metrics')
    assert len(metrics)==1
    data=json.loads(metrics[0]['data'])
    assert data['views']==12 and data['likes'] is None and data['retention'] is None


def test_upload_ambiguous_response_does_not_confirm(monkeypatch,tmp_path):
    monkeypatch.setattr(integrations,'youtube_token',lambda:'test-oauth')
    class Response:
        headers={'location':'https://www.googleapis.com/upload/session'}
        def json(self):return {}
    monkeypatch.setattr(integrations,'request',lambda *a,**kw:Response())
    path=tmp_path/'video.mp4';path.write_bytes(b'fixture')
    with pytest.raises(integrations.IntegrationError,match='confirmou'):
        integrations.youtube_upload(path,{'title':'test','description':'test','hashtags':[]})


def test_retention_starts_after_confirmation(client):
    id=pipeline.create_video(test=True);v=db.rows('SELECT * FROM videos')[0]
    pipeline.hunt(v);pipeline.write_script(v)
    final=db.ROOT/'videos/final'/f'{id}.mp4';final.write_bytes(b'fixture')
    db.artifact(id,'avaliador',data={'verdict':'APROVADO','test_only':True})
    db.execute("UPDATE videos SET approved=1,status='APPROVED',final_path=:path,updated=0 WHERE id=:id",dict(id=id,path=str(final.relative_to(db.ROOT))))
    pipeline.distribute(id)
    db.execute("UPDATE publications SET status='PUBLICADO',updated=:now",{'now':time.time()})
    worker.cleanup()
    assert final.exists()
    db.execute('UPDATE publications SET updated=0')
    worker.cleanup()
    assert final.exists()  # history previews retained until explicit reset
    assert db.rows('SELECT * FROM videos') and db.rows('SELECT * FROM publications')


@pytest.mark.skipif(not __import__('shutil').which('ffmpeg') or not __import__('shutil').which('ffprobe'), reason='Requires FFmpeg and ffprobe; run in Docker')
def test_real_render_and_pipeline():
    id=pipeline.create_video(test=True)
    pipeline.run_pipeline(id)
    video=db.rows('SELECT * FROM videos')[0]
    assert video['approved']==1
    assert media.technical_check(db.ROOT/video['final_path'],10)['valid']
    assert len(db.rows('SELECT * FROM publications'))==3
    assert set(p.name for p in (db.ROOT/'handoff'/id).glob('*.json')) >= {'diretor.json','cacador.json','escritor.json','editor.json','avaliador.json'}
    corrupt=db.ROOT/'cache/corrupt.mp4';corrupt.write_bytes(b'not-an-mp4')
    script=Script.model_validate_json((db.ROOT/'handoff'/id/'script.json').read_text('utf-8'))
    assert pipeline.evaluate(video,script,corrupt)['verdict']=='REPROVADO'
