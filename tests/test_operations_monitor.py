"""Monitoring exposes only real persisted job data; clip jobs outrank radar scans."""
import time
from backend import core as db
from backend.operations_monitor import snapshot


def test_operator_live_cut_is_prioritized_over_older_radar_jobs():
    now=time.time()
    db.enqueue('radar20_scan',unique_key='radar-priority-test',due=now-15)
    db.enqueue('pipeline',unique_key='pipeline-priority-test',due=now-12)
    db.enqueue('live_cut:manual-clip-id',unique_key='manual-priority-test',due=now-10)
    claimed=db.claim('worker')
    assert claimed['kind']=='live_cut:manual-clip-id'
    # Priority changes scheduling, not a job's retry/rights policy.
    assert db.rows("SELECT status FROM jobs WHERE id=:id",{'id':claimed['id']})[0]['status']=='RUNNING'


def test_operations_snapshot_shows_real_running_and_queued_jobs(client):
    now=time.time()
    db.put_setting('worker_heartbeat',now)
    db.put_setting('scheduler_status','Worker operacional')
    db.enqueue('radar20_scan',unique_key='monitor-queued-radar',due=now+2)
    db.enqueue('live_cut:test-monitor',unique_key='monitor-live',due=now-5)
    claimed=db.claim('worker')
    assert claimed['kind']=='live_cut:test-monitor'
    reply=client.get('/api/operations/live')
    assert reply.status_code==200
    report=reply.json()
    assert report['worker']['online'] is True
    assert report['counts']['running']==1
    assert report['counts']['queued']==1
    assert report['running'][0]['kind']=='live_cut:test-monitor'
    assert report['running'][0]['stage_label']=='Iniciando'
    assert report['queued'][0]['kind']=='radar20_scan'
    assert report['manual_publication_only'] is True
    assert report['scheduler_status']=='Worker operacional'


def test_operations_snapshot_does_not_claim_worker_alive_without_heartbeat(client):
    db.put_setting('worker_heartbeat',time.time()-180)
    response=client.get('/api/operations/live')
    assert response.status_code==200
    assert response.json()['worker']['online'] is False


def test_monitor_keeps_video_stage_and_actual_event(client):
    now=time.time()
    db.execute("""INSERT INTO videos
      (id,run_id,url,title,status,stage,created,updated)
      VALUES ('mon-video','mon-run','https://example.com/mon-video',
              'GTA 6 Brasil: análise','PROCESSING','editor',:now,:now)""",
      {'now':now})
    db.enqueue('pipeline',video_id='mon-video',unique_key='monitor-pipeline-video',due=now-2)
    claimed=db.claim('worker')
    assert claimed['kind']=='pipeline'
    db.log_event('mon-video','editor','START','Iniciando renderização.')
    report=client.get('/api/operations/live').json()
    assert report['running'][0]['title']=='GTA 6 Brasil: análise'
    assert report['running'][0]['stage']=='editor'
    assert report['running'][0]['stage_label']=='Edição e render'
    assert report['running'][0]['last_event']['summary']=='Iniciando renderização.'
