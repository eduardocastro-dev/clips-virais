"""Editorial archive and real-metric collection regressions."""
import json
import time

from backend import core as db, integrations, worker
from backend.integrations import IntegrationError


def _published(ident='v1', pub='p1', *, status='PUBLICADO'):
    now=time.time()
    db.execute("""INSERT INTO videos
        (id,run_id,url,platform,title,template,status,approved,
         approved_at,created,updated,test)
        VALUES (:id,:run,:source,'youtube',:title,'gta-news','APPROVED',1,
                :approved,:created,:updated,0)""",
        {'id':ident,'run':ident,'source':'https://example.org/'+ident,
         'title':'GTA VI — vídeo '+ident,'approved':now-86400,
         'created':now-90000,'updated':now-86400})
    db.execute("""INSERT INTO publications
        (id,video_id,platform,status,url,external_id,updated)
        VALUES (:id,:video,'youtube',:status,
                'https://www.youtube.com/watch?v=abcdefghijk','abcdefghijk',:updated)""",
        {'id':pub,'video':ident,'status':status,'updated':now})
    return ident,pub


def test_state_exposes_published_archive_without_recreating_destinations(client):
    ident,pub=_published()
    response=client.get('/api/state')
    assert response.status_code==200
    payload=response.json()
    assert any(v['id']==ident and v['approved_at'] for v in payload['approved_videos'])
    assert any(p['id']==pub and p['status']=='PUBLICADO' for p in payload['publications'])
    assert db.rows('SELECT COUNT(*) AS n FROM publications')[0]['n']==1


def test_confirm_publication_triggers_real_metrics_job(client):
    ident,pub=_published(status='AGUARDANDO_PUBLICACAO_MANUAL')
    response=client.post('/api/publications/'+pub+'/confirm',
                         json={'url':'https://youtu.be/abcdefghijk'})
    assert response.status_code==200,response.text
    record=db.rows('SELECT * FROM publications WHERE id=:id',{'id':pub})[0]
    assert record['url']=='https://www.youtube.com/watch?v=abcdefghijk'
    assert record['status']=='PUBLICADO'
    assert db.rows("SELECT kind FROM jobs WHERE kind='metrics_collect'")==[
        {'kind':'metrics_collect'}]


def test_metric_collection_records_real_statistics_and_diagnostics(client,monkeypatch):
    _published()
    seen=[]
    def public_data(url):
        seen.append(url)
        return {'metrics':{'viewCount':42,'likeCount':7},'metadata_source':'youtube_data_api_v3'}
    monkeypatch.setattr(integrations,'public_youtube_metadata',public_data)
    result=integrations.collect_metrics()
    assert result['observed']==1 and result['unavailable']==0
    assert seen==['https://www.youtube.com/watch?v=abcdefghijk']
    row=db.rows('SELECT * FROM metrics')[0]
    stats=json.loads(row['data'])
    assert stats['views']==42 and stats['likes']==7
    assert stats['comments'] is None and stats['retention'] is None
    response=client.get('/api/state').json()
    assert response['metric_checks']['p1']['status']=='observed'
    assert integrations.collect_metrics()['cached']==1
    assert len(db.rows('SELECT id FROM metrics'))==1


def test_unavailable_metrics_are_explained_not_fabricated(client,monkeypatch):
    _published()
    def unavailable(url):
        raise IntegrationError('Provider unavailable')
    monkeypatch.setattr(integrations,'public_youtube_metadata',unavailable)
    result=integrations.collect_metrics()
    assert result['unavailable']==1
    assert db.rows('SELECT * FROM metrics')==[]
    state=client.get('/api/state').json()
    assert state['metric_checks']['p1']['status']=='unavailable'
    assert 'YouTube' in state['metric_checks']['p1']['reason']


def test_manual_metrics_refresh_enqueues_worker_job(client,monkeypatch):
    _published()
    calls=[]
    monkeypatch.setattr(worker,'collect_metrics',lambda:calls.append('called') or
                        {'observed':1,'unavailable':0,'cached':0,'invalid':0})
    response=client.post('/api/analytics/refresh',json={})
    assert response.status_code==200
    assert response.json()['queued']
    job=db.rows("SELECT * FROM jobs WHERE kind='metrics_collect'")[0]
    worker.perform(job)
    assert calls==['called']
