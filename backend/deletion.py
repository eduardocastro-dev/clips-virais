"""Persistent two-hour discard and explicit clear-all with reference-safe deletion.

A running job is never deleted underneath a writer. It is cancel-requested
and remains visible as DELETING until worker activity has stopped. Audit
logs and shared libraries are not deleted.
"""
from __future__ import annotations
import json
import os
import shutil
import time
from pathlib import Path
from backend import core as db
from sqlalchemy import text

GRACE=7200
CLEANUP_INTERVAL=300
LOG=db.DATA/'deletion_log.json'


def summary():
    videos=db.rows('SELECT id,status,discarded_at,created FROM videos ORDER BY created DESC')
    counts={'approved':0,'pending':0,'rendering':0,'rejected_discarded':0}
    for v in videos:
        status=str(v['status'])
        if status in ('APPROVED','PUBLICADO'):
            counts['approved']+=1
        elif status in ('PROCESSING','RETRY','RENDERING','DELETING'):
            counts['rendering']+=1
        elif status in ('REJECTED','DISCARDED','FAILED','PIPELINE_ERROR'):
            counts['rejected_discarded']+=1
        else:counts['pending']+=1
    return {'total':len(videos),'counts':counts,
            'pending_delete':sum(v['status']=='DELETING' for v in videos)}


def _is_running(video_id):
    now=time.time()
    jobs=db.rows("""SELECT id,lease FROM jobs WHERE video_id=:id AND status='RUNNING'""",
                 {'id':video_id})
    if not jobs:return False
    last_beat=float(db.get_setting('worker_heartbeat',0) or 0)
    if now-last_beat<=300:return True
    return any((row['lease'] or 0)>now-600 for row in jobs)


def _allowed(path:Path,root:Path):
    # Strict symlink rejection: no follow-through to shared asset folders.
    root=root.resolve()
    if path.is_symlink():return False
    target=path.resolve()
    return target.is_relative_to(root) and target!=root


def _remove(path,allowed_root):
    target=Path(path)
    if not _allowed(target,allowed_root) or not target.exists():return 0
    if target.is_symlink():return 0
    def size_of(p):
        if p.is_symlink():return 0
        if p.is_file():return p.stat().st_size
        return sum(f.stat().st_size for f in p.rglob('*') if f.is_file() and not f.is_symlink())
    size=size_of(target)
    if target.is_dir():shutil.rmtree(target)
    else:target.unlink()
    return size


def _log(item):
    try:data=json.loads(LOG.read_text('utf-8')) if LOG.is_file() else {'entries':[]}
    except (ValueError,OSError):data={'entries':[]}
    data['entries'].append(item)
    data['entries']=data['entries'][-10000:]
    db.atomic(LOG,json.dumps(data,ensure_ascii=False,indent=2))


def _purge_one(video,reason):
    ident=video['id']
    if _is_running(ident):
        return {'id':ident,'pending':True,'reason':'Worker executando; cancelamento solicitado.'}
    refs=db.rows('SELECT output_path FROM publications WHERE video_id=:id',
                 {'id':ident})
    media_paths=[]
    for record in refs:
        name=record.get('output_path')
        if not name:continue
        try:output=db.safe_file(name)
        except ValueError:continue
        if output.is_relative_to((db.ROOT/'output').resolve()) and not output.is_symlink():
            others=db.rows("""SELECT id FROM publications WHERE output_path=:path
                               AND video_id!=:id LIMIT 1""",
                           {'path':name,'id':ident})
            if not others:media_paths.append(output)
    bytes_freed=0
    issues=[]
    for path in media_paths:
        try:bytes_freed+=_remove(path,db.ROOT/'output')
        except OSError as exc:issues.append(str(path.name))
    # Individual paths only. Sources in assets/ are shared across productions
    # and intentionally preserved unless separately deleted from the library.
    isolated=[
        (db.ROOT/'videos'/'processing'/ident, db.ROOT/'videos'/'processing'),
        (db.ROOT/'videos'/'final'/ident, db.ROOT/'videos'/'final'),
        (db.ROOT/'videos'/'raw'/(ident+'.mp4'), db.ROOT/'videos'/'raw'),
        (db.ROOT/'temp'/ident,db.ROOT/'temp'),
        (db.ROOT/'handoff'/ident,db.ROOT/'handoff'),
        (db.ROOT/'output'/ident,db.ROOT/'output'),
    ]
    for path,root in isolated:
        try:bytes_freed+=_remove(path,root)
        except OSError:issues.append(str(path.name))
    if issues:
        return {'id':ident,'pending':True,'error':'Arquivos em uso: '+', '.join(issues[:5])}
    # Foreign key order; removing media first avoids references to missing
    # renders only if this DB mutation succeeds.
    with db.transaction() as c:
        c.execute(text('DELETE FROM metrics WHERE publication_id IN (SELECT id FROM publications WHERE video_id=:id)'),{'id':ident})
        c.execute(text('DELETE FROM publications WHERE video_id=:id'),{'id':ident})
        c.execute(text('DELETE FROM video_attempts WHERE video_id=:id'),{'id':ident})
        c.execute(text('DELETE FROM jobs WHERE video_id=:id'),{'id':ident})
        c.execute(text('DELETE FROM events WHERE video_id=:id'),{'id':ident})
        c.execute(text('DELETE FROM videos WHERE id=:id'),{'id':ident})
    _log({'id':ident,'title':video.get('title'),'reason':reason,
          'discarded_at':video.get('discarded_at'),
          'deleted_at':time.time(),'bytes_freed':bytes_freed,
          'preserved':['rights_log.json','shared_asset_library']})
    return {'id':ident,'deleted':True,'bytes_freed':bytes_freed}


def mark_discarded(video_id,reason='manual'):
    rows=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})
    if not rows:raise ValueError('Vídeo inexistente.')
    row=rows[0]
    if row.get('approved') or row.get('manual_decision')=='approved':
        raise ValueError('Vídeo já aprovado ou publicado não pode ser descartado por esse fluxo.')
    if row.get('discarded_at'):
        return {'id':video_id,'status':row['status'],'discarded_at':row['discarded_at']}
    now=time.time()
    db.execute("""UPDATE videos SET status='DISCARDED',discarded_at=:at,
        pre_discard_status=:before,delete_reason=:reason,
        manual_decision='discard',manual_at=:at,approved=0,updated=:at
        WHERE id=:id""",{
          'id':video_id,'at':now,'before':row['status'],'reason':reason})
    db.execute("""UPDATE jobs SET status='PAUSED',lease=NULL
                   WHERE video_id=:id AND status='QUEUED'""",{'id':video_id})
    db.execute("""UPDATE publications SET status='DISCARDED',updated=:now
                   WHERE video_id=:id AND status!='PUBLICADO'""",{'id':video_id,'now':now})
    db.put_setting('video_cancel_requested:'+video_id,True)
    return {'id':video_id,'status':'DISCARDED','discarded_at':now,
            'delete_after':now+GRACE}


def restore(video_id):
    records=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})
    if not records:raise ValueError('Vídeo já excluído ou inexistente.')
    row=records[0]
    stamp=row.get('discarded_at')
    if not stamp or time.time()-float(stamp)>=GRACE:
        raise ValueError('Prazo para restaurar já terminou.')
    if row['status'] not in ('DISCARDED','DELETING'):
        raise ValueError('Item não está descartado.')
    if _is_running(video_id):
        raise ValueError('Vídeo ainda em processamento; não é seguro restaurar agora.')
    before=row.get('pre_discard_status') or 'PAUSED_VALIDATION'
    if before in ('PROCESSING','RETRY','QUEUED','DELETING'):
        before='PAUSED_VALIDATION'
    db.execute("""UPDATE videos SET status=:status,discarded_at=NULL,
      pre_discard_status=NULL,delete_reason=NULL,manual_decision=NULL,
      manual_at=NULL,manual_by=NULL,updated=:now WHERE id=:id""",
      {'id':video_id,'status':before,'now':time.time()})
    db.put_setting('video_cancel_requested:'+video_id,False)
    return {'restored':True,'status':before}


def request_clear_all(expected_total:int):
    snapshot=summary()
    if int(expected_total)!=snapshot['total']:
        raise ValueError('A lista mudou. Atualize a confirmação antes de excluir.')
    now=time.time()
    for row in db.rows('SELECT id,status,discarded_at FROM videos'):
        if row['status']!='DELETING':
            db.execute("""UPDATE videos SET status='DELETING',
                discarded_at=COALESCE(discarded_at,:now),
                delete_reason='limpeza manual',updated=:now WHERE id=:id""",
                {'id':row['id'],'now':now})
        db.put_setting('video_cancel_requested:'+row['id'],True)
        db.execute("""UPDATE jobs SET status='PAUSED',lease=NULL
                       WHERE video_id=:id AND status='QUEUED'""",
                   {'id':row['id']})
    db.put_setting('operator_cleanup_hold_day',db.today())
    db.put_setting('operator_cleanup_deleted_count',expected_total)
    result=purge_due(force=True)
    result['requested']=expected_total
    result['counts']=snapshot['counts']
    return result


def purge_due(force=False):
    now=time.time()
    # All status changes survive restarts and all deletions are idempotent.
    rows=db.rows("""SELECT * FROM videos WHERE
      (status='DISCARDED' AND discarded_at IS NOT NULL AND discarded_at<=:cutoff)
      OR status='DELETING'
      ORDER BY created""",{'cutoff':now-GRACE})
    outcomes=[]
    for row in rows:
        if row['status']=='DELETING' and not force:
            # DELETING always represents explicit operator clear; it does not
            # depend on the two-hour grace period.
            pass
        outcomes.append(_purge_one(row,row.get('delete_reason') or 'descarte expirado'))
    return {
        'deleted':sum(bool(x.get('deleted')) for x in outcomes),
        'pending':sum(bool(x.get('pending')) for x in outcomes),
        'freed_bytes':sum(int(x.get('bytes_freed',0)) for x in outcomes),
        'errors':[x for x in outcomes if x.get('error')]
    }


def tick_cleanup():
    now=time.time()
    if now-float(db.get_setting('discard_cleanup_last',0) or 0)<CLEANUP_INTERVAL:
        return None
    db.put_setting('discard_cleanup_last',now)
    return purge_due()
