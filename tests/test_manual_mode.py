import time
from backend import core as db, pipeline
from backend.api import app
from fastapi.testclient import TestClient


def test_settings_cannot_enable_social_publishing(client):
    settings = client.get('/api/settings').json()
    settings.update({'postiz_auto': True, 'youtube_auto': True,
                     'approval_mode': 'automatic', 'postiz_url': 'http://postiz:5000/api/public/v1'})
    r = client.put('/api/settings', json=settings)
    assert r.status_code == 200
    saved = client.get('/api/settings').json()
    assert saved['postiz_auto'] is False and saved['youtube_auto'] is False
    assert saved['postiz_url'] == '' and saved['approval_mode'] == 'manual'


def test_discover_queues_youtube_and_rss(client):
    from backend.sources import seed_default_sources
    seed_default_sources()  # News remains enabled alongside YouTube.
    r = client.post('/api/discover')
    assert r.status_code == 200
    assert r.json()['mode'] == 'all_sources_youtube_first'
    assert r.json()['sources'] >= 2
    kinds = [x['kind'] for x in db.rows('SELECT * FROM jobs')]
    assert 'discover' in kinds and any(x.startswith('source:') for x in kinds)


def test_send_endpoint_is_disabled(client):
    assert client.post('/api/publications/whatever/send', json={'reviewed': True}).status_code == 410


def test_manual_distribution_only_copies_files(monkeypatch):
    from backend.contracts import Script
    id = pipeline.create_video(test=True)
    db.execute("UPDATE videos SET approved=1,status='APPROVED',final_path=:path WHERE id=:id",{'id':id,'path':f'videos/final/{id}.mp4'})
    final = db.ROOT/'videos/final'/f'{id}.mp4'
    final.write_bytes(b'fixture')
    handoff = db.ROOT/'handoff'/id
    handoff.mkdir(parents=True,exist_ok=True)
    script = Script(title='Teste', hook='teste',description='Somente teste',hashtags=['teste'],template='gta-news',duration=10,scenes=[
        {'start':0,'end':5,'text':'Teste 1','narration':'Teste 1','source_id':id},
        {'start':5,'end':10,'text':'Teste 2','narration':'Teste 2','source_id':id}])
    (handoff/'script.json').write_text(script.model_dump_json())
    db.artifact(id,'avaliador',{'verdict':'APROVADO','requires_human_audiovisual_review':True})
    config = db.settings()
    config.postiz_auto=True; config.youtube_auto=True; config.approval_mode='automatic'
    db.put_setting('settings',config.model_dump())
    pipeline.distribute(id)
    statuses = db.rows('SELECT platform,status,output_path FROM publications WHERE video_id=:id',{'id':id})
    assert len(statuses)==3
    assert all(row['status']=='AGUARDANDO_PUBLICACAO_MANUAL' for row in statuses)
    assert all(row['output_path'] for row in statuses)
