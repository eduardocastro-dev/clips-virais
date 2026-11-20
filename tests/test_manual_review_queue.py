"""Manual approval is a parked state, not a blocker or a failed Short."""
import time

import pytest

from backend import core as db, daily_quota, pipeline, worker


def _opportunity(index: int):
    url = f"https://www.youtube.com/shorts/{index:011d}"
    db.execute(
        """INSERT INTO opportunities(id,url,platform,title,metadata,score,created)
           VALUES (:id,:url,'youtube',:title,'{}',:score,:created)""",
        {'id':f'candidate-{index}', 'url':url, 'title':f'GTA {index}',
         'score':100-index, 'created':time.time()+index},
    )
    return url


@pytest.mark.parametrize('status', ['AWAITING_MANUAL_DECISION', 'PENDING_RIGHTS_REVIEW'])
def test_manual_review_keeps_daily_slot_without_auto_restarting(client, status):
    settings=db.settings()
    settings.daily_limit=2
    db.put_setting('settings',settings.model_dump())
    video_id=pipeline.create_video(test=False)
    db.execute(
        "UPDATE videos SET status=:status,stage='diretor',error='Revisão solicitada' WHERE id=:id",
        {'status':status,'id':video_id},
    )
    assert db.production_usage()==1
    pipeline.run_pipeline(video_id)
    saved=db.rows('SELECT status,stage,error FROM videos WHERE id=:id',{'id':video_id})[0]
    assert saved['status']==status
    assert saved['stage']=='diretor'
    assert saved['error']=='Revisão solicitada'

    snapshot=daily_quota.state()
    assert snapshot['manual_review']=={'shorts':1}
    assert snapshot['rejected']['shorts']==0
    assert snapshot['pending']['shorts']==1
    assert snapshot['capacity_remaining']['shorts']==1
    assert snapshot['failures']==[]


def test_auto_queue_continues_past_manual_review_until_daily_limit(client, monkeypatch):
    settings=db.settings()
    settings.automatic=True
    settings.daily_limit=2
    db.put_setting('settings',settings.model_dump())
    for index in range(1,4):
        _opportunity(index)

    worker.queue_opportunities()
    first=db.rows('SELECT id FROM videos')[0]['id']
    db.execute("UPDATE videos SET status='AWAITING_MANUAL_DECISION' WHERE id=:id",{'id':first})
    db.execute("UPDATE jobs SET status='DONE' WHERE video_id=:id",{'id':first})
    assert db.production_usage()==1

    worker.queue_opportunities()
    videos=db.rows('SELECT id,status FROM videos ORDER BY created')
    assert len(videos)==2
    assert db.production_usage()==2
    assert db.rows('SELECT status FROM videos WHERE id=:id',{'id':first})[0]['status']=='AWAITING_MANUAL_DECISION'

    # A queued worker can still complete a different Short; the parked one is
    # neither approved, discarded nor put back into the processing queue.
    monkeypatch.setattr(worker,'scheduler',lambda:None)
    processed=[]
    monkeypatch.setattr(worker,'perform',lambda job:processed.append(job['video_id']))
    assert worker.tick() is True
    assert len(processed)==1 and processed[0]!=first
    assert db.rows('SELECT status FROM jobs WHERE video_id=:id',{'id':first})[0]['status']=='DONE'

    worker.queue_opportunities()
    assert len(db.rows('SELECT id FROM videos'))==2
    assert db.production_usage()==2
    snapshot=daily_quota.state()
    assert snapshot['capacity_used']['shorts']==2
    assert snapshot['capacity_remaining']['shorts']==0
    assert snapshot['manual_review']['shorts']==1
