"""List/requeue only productions blocked by Redator/TTS timing failures.

Default is read-only. Use --apply after deploying the corrected audio engine.
This does not delete jobs, video renders, attempts, scripts or API usage.
"""
from __future__ import annotations
import argparse
import json
import time
from backend import core as db


QUERY = """SELECT id,title,status,error,render_error FROM videos
WHERE status='PIPELINE_ERROR' AND (manual_decision IS NULL OR manual_decision='')
AND (lower(coalesce(error,'')) LIKE '%redator%'
 OR lower(coalesce(error,'')) LIKE '%tts%'
 OR lower(coalesce(error,'')) LIKE '%narra%'
 OR lower(coalesce(render_error,'')) LIKE '%redator%'
 OR lower(coalesce(render_error,'')) LIKE '%tts%')
ORDER BY updated ASC LIMIT :limit"""


def run(limit: int = 5, apply: bool = False):
    db.init_db()
    rows=db.rows(QUERY, {'limit':max(1,min(100,limit))})
    ids=[]
    for row in rows:
        ids.append({'id':row['id'],'title':row['title'],'reason':(row['error'] or row['render_error'] or '')[:200]})
        if not apply:
            continue
        queued=db.rows("SELECT id FROM jobs WHERE video_id=:id AND status IN ('QUEUED','RUNNING','PENDING') AND kind='pipeline' LIMIT 1", {'id':row['id']})
        if queued:
            continue
        db.execute("UPDATE videos SET status='QUEUED',error=NULL,render_error=NULL,updated=:now WHERE id=:id AND status='PIPELINE_ERROR'",
                   {'id':row['id'],'now':time.time()})
        db.enqueue('pipeline',video_id=row['id'],unique_key='tts-budget-retry:'+row['id']+':'+db.uid())
    print(json.dumps({'mode':'apply' if apply else 'preview','matched':len(rows),'productions':ids},ensure_ascii=False,indent=2))
    return rows


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='Requeue matching paused productions; no deletion')
    parser.add_argument('--limit',type=int,default=5,help='Maximum productions in this batch (default 5)')
    args=parser.parse_args()
    run(args.limit,args.apply)
