import json
import time
import pytest
from backend import core as db, pipeline
from backend import distribution, sources
from backend.integrations import IntegrationError


def fixture_publication():
    video=pipeline.create_video(test=True)
    db.execute("INSERT INTO publications(id,video_id,platform,status,updated) VALUES ('p',:id,'youtube','PENDENTE',:now)",dict(id=video,now=time.time()))
    path=db.ROOT/'videos/final'/f'{video}.mp4';path.write_bytes(b'fixture')
    config=db.settings();config.postiz_channels={'youtube':'channel'};config.postiz_settings={'youtube':{'__type':'youtube','type':'private'}}
    db.put_setting('settings',config.model_dump())
    return db.rows('SELECT * FROM publications')[0],path,{'title':'Title','description':'Description','hashtags':['gta6']}


def test_postiz_ack_is_scheduled_not_published(monkeypatch):
    pub,path,script=fixture_publication();calls=[]
    def fake(method,endpoint,**kwargs):
        calls.append((method,endpoint))
        if endpoint=='/integrations':return [{'id':'channel','identifier':'youtube','disabled':False}]
        if endpoint=='/upload':return {'id':'media','path':'https://postiz.example/video.mp4'}
        if method=='POST' and endpoint=='/posts':
            assert kwargs['json']['posts'][0]['settings']['title']=='Title'
            return [{'postId':'remote','integration':'channel'}]
        return {'posts':[{'id':'remote','state':'PUBLISHED','releaseURL':'https://www.youtube.com/watch?v=abcdefghijk'}]}
    monkeypatch.setattr(distribution,'postiz',fake)
    distribution.schedule_postiz(pub,path,script)
    assert db.rows('SELECT * FROM publications')[0]['status']=='AGENDADO'
    distribution.reconcile_postiz()
    result=db.rows('SELECT * FROM publications')[0]
    assert result['status']=='PUBLICADO' and result['external_id']=='abcdefghijk'


def test_postiz_timeout_preserves_intent(monkeypatch):
    pub,path,script=fixture_publication()
    def fake(method,endpoint,**kwargs):
        if endpoint=='/integrations':return [{'id':'channel','identifier':'youtube','disabled':False}]
        if endpoint=='/upload':return {'id':'media','path':'https://postiz.example/video.mp4'}
        raise IntegrationError('Timeout')
    monkeypatch.setattr(distribution,'postiz',fake)
    with pytest.raises(IntegrationError):distribution.schedule_postiz(pub,path,script)
    assert db.rows('SELECT * FROM publications')[0]['status']=='PUBLICANDO'


def test_test_video_never_sent_via_ui(client):
    pub,_,_=fixture_publication()
    assert client.post('/api/publications/p/send',json={'reviewed':True}).status_code==409


def test_schedule_preserves_manual_status(client):
    fixture_publication()
    assert client.post('/api/publications/p/schedule',json={'timestamp':time.time()+3600}).status_code==200
    assert db.rows('SELECT * FROM publications')[0]['status']=='PENDENTE'
    assert client.post('/api/publications/p/schedule',json={'timestamp':time.time()-1}).status_code==422


def test_feed_reference_only_and_production(client,monkeypatch):
    body={'name':'Official fixture','url':'https://example.com/feed.xml'}
    assert client.post('/api/sources',json=body).status_code==200
    monkeypatch.setattr(sources,'ensure_public_host',lambda url:None)
    class Response:
        content=b'<rss version="2.0"><channel><title>News</title><item><title>GTA 6 update</title><link>https://example.com/gta6</link><description>Confirmed test fixture only.</description></item></channel></rss>'
    monkeypatch.setattr(sources,'request',lambda *a,**kw:Response())
    source=db.rows('SELECT * FROM sources')[0]
    assert len(sources.scan_feed(source))==1
    opportunity=db.rows('SELECT * FROM opportunities')[0]
    r=client.post('/api/opportunities/'+opportunity['id']+'/produce',json={})
    assert r.status_code==200
    video=db.rows('SELECT * FROM videos')[0]
    assert video['rights']=='REFERENCE_ONLY' and video['platform']=='news'
    pipeline.hunt(video)
    assert db.read_artifact(video['id'],'cacador').dados['source_feed']==body['url']


def test_feed_rejects_private_addresses(monkeypatch):
    monkeypatch.setattr(sources.socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('127.0.0.1',443))])
    with pytest.raises(IntegrationError):sources.ensure_public_host('https://private.example/feed')


def test_tiktok_scope_identity_boundary(monkeypatch):
    db.set_secret('tiktok_access_token','mock-token')
    class Response:
        def json(self):return {'data':{'user':{'username':'different'}}}
    monkeypatch.setattr(sources,'request',lambda *a,**kw:Response())
    with pytest.raises(IntegrationError,match='perfil solicitado'):
        sources.connected_profile({'id':'profile','url':'https://www.tiktok.com/@expected','platform':'tiktok'})


def test_instagram_connected_account_only(monkeypatch):
    db.set_secret('instagram_access_token','mock');db.set_secret('instagram_user_id','1234')
    class Response:
        def __init__(self,data):self.data=data
        def json(self):return self.data
    def fake(method,url,**kw):
        if url.endswith('/media'):return Response({'data':[{'media_type':'VIDEO','permalink':'https://www.instagram.com/reel/AbCd123/','caption':'GTA 6 fixture','timestamp':'2026-11-17T00:00:00+0000'}]})
        return Response({'username':'authorized'})
    monkeypatch.setattr(sources,'request',fake)
    items=sources.connected_profile({'id':'profile','platform':'instagram','url':'https://www.instagram.com/authorized'})
    assert len(items)==1 and items[0]['metrics']=={}


def test_variant_idempotency_and_daily_limit(client):
    original=client.post('/api/import',json={'url':'https://www.youtube.com/watch?v=abcdefghijk'}).json()['id']
    variant={'instructions':'Reorganize a narrativa para comparar personagens e destacar uma hipótese original claramente identificada.','template':'gta-theory','duration':20}
    first=client.post('/api/videos/'+original+'/variant',json=variant)
    second=client.post('/api/videos/'+original+'/variant',json=variant)
    assert first.status_code==200 and first.json()['id']==second.json()['id']
    assert first.json()['id']!=original and len(db.rows('SELECT * FROM videos'))==2


def test_manual_briefing_is_atomic_before_job_claim(client):
    from backend.contracts import Script
    original=client.post('/api/import',json={'url':'https://www.youtube.com/watch?v=abcdefghijk'}).json()['id']
    script={'title':'Comentário original','hook':'Qual hipótese faz sentido?','description':'Teoria, não notícia confirmada.','hashtags':['gta6'],
        'rumor':True,'template':'gta-theory','duration':10,'scenes':[
        {'start':0,'end':5,'text':'Uma teoria','narration':'Primeiro ponto de análise original.','source_id':original},
        {'start':5,'end':10,'text':'Outra perspectiva','narration':'Outro ponto, sem alegar confirmação.','source_id':original}]}
    result=client.post('/api/videos/'+original+'/briefing',json=script)
    assert result.status_code==200
    new_id=result.json()['id']
    saved=Script.model_validate_json((db.ROOT/'handoff'/new_id/'manual-script.json').read_text('utf-8'))
    assert all(s.source_id==new_id for s in saved.scenes)
    assert db.rows('SELECT * FROM jobs WHERE video_id=:id',{'id':new_id})


def test_postiz_metrics_preserve_provider_series(monkeypatch):
    pub,_,_=fixture_publication()
    db.execute("UPDATE publications SET provider='postiz',remote_id='remote',status='PUBLICADO'")
    series=[{'label':'Likes','data':[{'total':'5','date':'2026-11-16'},{'total':'7','date':'2026-11-17'}]}]
    monkeypatch.setattr(distribution,'postiz',lambda *a,**kw:series)
    distribution.collect_postiz_metrics();distribution.collect_postiz_metrics()
    rows=db.rows('SELECT * FROM metrics');assert len(rows)==1
    data=json.loads(rows[0]['data'])
    assert data['likes']==7 and data['views'] is None and data['provider_series']==series


def test_postiz_emergency_blocks_network(monkeypatch):
    pub,path,script=fixture_publication()
    config=db.settings();config.emergency_stop=True;db.put_setting('settings',config.model_dump())
    monkeypatch.setattr(distribution,'postiz',lambda *a,**kw:pytest.fail('No network call permitted'))
    with pytest.raises(IntegrationError,match='emergência'):distribution.schedule_postiz(pub,path,script)
