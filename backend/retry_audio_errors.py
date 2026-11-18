"""Recover only productions blocked by the legacy metadata_errors PyAV exception."""
import json, time
from backend import core as db

def main():
    db.init_db()
    affected=db.rows("""SELECT id,title,status,error FROM videos WHERE status IN
       ('PAUSED_VALIDATION','PIPELINE_ERROR','FAILED','RETRY') AND
       (error LIKE '%metadata_errors%' OR render_error LIKE '%metadata_errors%')""")
    ids=[]
    for video in affected:
        db.execute("UPDATE videos SET status='QUEUED',stage='editor',error=NULL,render_error=NULL,updated=:now WHERE id=:id",
                   {'id':video['id'],'now':time.time()})
        db.enqueue('pipeline',video_id=video['id'],unique_key='audio-migration:'+video['id']+':'+db.uid())
        ids.append(video['id'])
    print(json.dumps({'requeued':len(ids),'ids':ids},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
