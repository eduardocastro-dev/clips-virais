"""Persistent discard, two-hour restoration and safe clear-all regressions."""
import json
import time
from backend import core as db
from backend import deletion


def _video(ident,status='AWAITING_MANUAL_DECISION',approved=0):
    now=time.time()
    db.execute("""INSERT INTO videos(id,run_id,url,title,status,template,rights,
         approved,created,updated)
         VALUES (:id,'run',NULL,:title,:status,'gta-news','REFERENCE_ONLY',
                 :approved,:now,:now)""",
        {'id':ident,'title':'Teste exclusão '+ident,'status':status,
         'approved':approved,'now':now})
    folder=db.ROOT/'videos'/'final'/ident
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'attempt-01.mp4').write_bytes(b'fake mp4 private'+b'x'*2048)
    db.execute('UPDATE videos SET final_path=:file WHERE id=:id',
               {'id':ident,'file':str((folder/'attempt-01.mp4').relative_to(db.ROOT))})
    return folder


def test_discard_keeps_mp4_before_two_hours_and_restore(client):
    ident='a'*32
    folder=_video(ident)
    response=client.post('/api/videos/'+ident+'/decision',json={'action':'discard'})
    assert response.status_code==200
    assert response.json()['status']=='DISCARDED'
    assert folder.exists()
    item=db.rows('SELECT discarded_at FROM videos WHERE id=:id',{'id':ident})[0]
    assert item['discarded_at']>0
    output=client.post('/api/videos/'+ident+'/restore',json={})
    assert output.status_code==200
    assert db.rows('SELECT discarded_at FROM videos WHERE id=:id',{'id':ident})[0]['discarded_at'] is None
    assert folder.exists()


def test_expired_discard_deletes_private_files_and_preserves_audit():
    ident='b'*32
    folder=_video(ident)
    shared=db.ROOT/'assets'/'gameplay'/'licensed-shared.mp4'
    shared.parent.mkdir(parents=True,exist_ok=True)
    shared.write_bytes(b'shared library, must not delete')
    audit=db.DATA/'rights_log.json'
    audit.write_text('{"entries":[]}',encoding='utf-8')
    deletion.mark_discarded(ident)
    db.execute('UPDATE videos SET discarded_at=:old WHERE id=:id',
               {'old':time.time()-7300,'id':ident})
    result=deletion.purge_due()
    assert result['deleted']==1
    assert db.rows('SELECT id FROM videos WHERE id=:id',{'id':ident})==[]
    assert not folder.exists()
    assert shared.exists()
    assert audit.exists()
    records=json.loads((db.DATA/'deletion_log.json').read_text('utf-8'))
    assert records['entries'][-1]['id']==ident


def test_clear_all_counts_by_status_and_honors_exact_confirmation(client):
    first='c'*32;second='d'*32
    _video(first)
    _video(second,status='APPROVED',approved=1)
    preview=client.get('/api/videos/deletion-preview')
    assert preview.status_code==200
    assert preview.json()['total']==2
    assert preview.json()['counts']['approved']==1
    assert client.post('/api/videos/clear',json={
        'expected_total':1,'confirmation':'EXCLUIR_TUDO'
    }).status_code==409
    approved=client.post('/api/videos/clear',json={
        'expected_total':2,'confirmation':'EXCLUIR_TUDO'
    })
    assert approved.status_code==200,approved.text
    assert approved.json()['deleted']==2
    assert db.rows('SELECT id FROM videos')==[]
    assert db.get_setting('operator_cleanup_hold_day')==db.today()
    assert db.get_setting('operator_cleanup_deleted_count')==2


def test_running_job_deletion_is_deferred():
    ident='e'*32
    folder=_video(ident,status='PROCESSING')
    db.enqueue('pipeline',video_id=ident)
    db.execute("""UPDATE jobs SET status='RUNNING',lease=:lease
                  WHERE video_id=:id""",{'id':ident,'lease':time.time()+300})
    db.put_setting('worker_heartbeat',time.time())
    result=deletion.request_clear_all(1)
    assert result['pending']==1
    assert folder.exists()
    assert db.rows('SELECT status FROM videos WHERE id=:id',{'id':ident})[0]['status']=='DELETING'
    # When work stops, the next cleanup can finish.
    db.execute("UPDATE jobs SET status='DONE' WHERE video_id=:id",{'id':ident})
    assert deletion.purge_due()['deleted']==1
    assert not folder.exists()
