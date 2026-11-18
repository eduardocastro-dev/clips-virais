"""Lossless-original media registry and precise 10-second H.264 clip derivatives.

All derivatives live in assets/clips/<parent id>/; never edit the original.
Database job status and an atomic file commit make interruption/retry safe.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import shutil
import time
from pathlib import Path
from backend import core as db

CLIPS_ROOT = db.ROOT / 'assets' / 'clips'
CLIPS_ROOT.mkdir(parents=True, exist_ok=True)


def file_sha256(path: Path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):
            digest.update(block)
    return digest.hexdigest()


def time_windows(duration: float, chunk_seconds: float, minimum_tail: float):
    """Keep last segment >= minimum_tail by merging a short remainder."""
    if not duration or duration<=0:raise ValueError('Duração de vídeo inválida.')
    if chunk_seconds < minimum_tail or minimum_tail<.1:raise ValueError('Parâmetros de corte inválidos.')
    count=int(duration//chunk_seconds)
    remainder=duration-count*chunk_seconds
    windows=[(round(i*chunk_seconds,6),round(chunk_seconds,6)) for i in range(count)]
    if remainder>.02:
        if remainder<minimum_tail and windows:
            start,length=windows.pop()
            windows.append((start,round(length+remainder,6)))
        else:windows.append((round(count*chunk_seconds,6),round(remainder,6)))
    return windows or [(0.0,round(duration,6))]


def mark_for_slicing(asset_id: str):
    row=db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})
    if not row:return False
    asset=row[0]
    if not asset['path'] or asset.get('media_type') not in ('video',None) or asset['kind']=='clip':return False
    try:source=db.safe_file(asset['path'])
    except ValueError:return False
    from backend.media import probe
    info=probe(source)
    if not any(x.get('codec_type')=='video' for x in info.get('streams',[])):return False
    duration=float(info['format']['duration'])
    checksum=asset.get('sha256') or file_sha256(source)
    db.execute('UPDATE assets SET duration=:duration,sha256=:hash,media_type=\'video\' WHERE id=:id',
               {'duration':duration,'hash':checksum,'id':asset_id})
    if duration<=db.settings().clip_threshold_seconds:
        db.execute("UPDATE assets SET status='READY',error=NULL WHERE id=:id",{'id':asset_id})
        return False
    # A stable job key also prevents multiple concurrent workers splitting one asset.
    existing=db.rows('SELECT id FROM assets WHERE parent_id=:id LIMIT 1',{'id':asset_id})
    if existing:
        db.execute("UPDATE assets SET status='READY' WHERE id=:id",{'id':asset_id})
        return False
    db.execute("UPDATE assets SET status='SPLIT_QUEUED',error=NULL WHERE id=:id",{'id':asset_id})
    db.enqueue('split:'+asset_id,unique_key='split:'+asset_id)
    return True


def _safe_parent(asset_id):
    parent=db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})
    if not parent:raise ValueError('Vídeo original não encontrado.')
    item=parent[0]
    if not item['path'] or not item['active'] or item['kind']=='clip':raise ValueError('Asset original inválido ou inativo.')
    origin=db.safe_file(item['path'])
    if not origin.is_relative_to((db.ROOT/'assets').resolve()):raise ValueError('Origem fora da biblioteca.')
    return item,origin


def split_asset(asset_id: str):
    from backend.media import binary,probe,run
    parent,origin=_safe_parent(asset_id)
    if db.rows('SELECT id FROM assets WHERE parent_id=:id LIMIT 1',{'id':asset_id}):
        return {'status':'ALREADY_SPLIT','asset_id':asset_id}
    config=db.settings()
    total=float(probe(origin)['format']['duration'])
    if total<=config.clip_threshold_seconds:
        db.execute("UPDATE assets SET status='READY' WHERE id=:id",{'id':asset_id})
        return {'status':'UNCHANGED','asset_id':asset_id}
    windows=time_windows(total,config.clip_seconds,config.clip_min_tail_seconds)
    dest=CLIPS_ROOT/asset_id
    staging=CLIPS_ROOT/('.pending-'+asset_id)
    if staging.exists():shutil.rmtree(staging)
    staging.mkdir(parents=True,exist_ok=True)
    md=json.loads(parent['metadata'] or '{}')
    md['split']={'total':len(windows),'completed':0,'progress':0,'status':'SPLITTING'}
    db.execute("UPDATE assets SET status='SPLITTING',metadata=:md,error=NULL,updated=:now WHERE id=:id",{'md':json.dumps(md),'now':time.time(),'id':asset_id})
    ff=binary('ffmpeg')
    records=[]
    try:
        for i,(start,length) in enumerate(windows,1):
            path=staging/f'clip_{i:03}.mp4'
            args=[ff,'-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(origin),'-t',str(length),
                '-map','0:v:0','-map','0:a:0?','-c:v','libx264','-preset','veryfast','-crf','23',
                '-pix_fmt','yuv420p','-c:a','aac','-b:a','128k','-avoid_negative_ts','make_zero',
                '-movflags','+faststart',str(path)]
            run(args,timeout=max(180,int(length*12)))
            if not path.is_file() or not path.stat().st_size:raise RuntimeError('FFmpeg não gerou '+path.name)
            actual=float(probe(path)['format']['duration'])
            if abs(actual-length)>.35:raise RuntimeError(f'Clipe {i} divergente: {actual:.3f}s em vez de {length:.3f}s')
            records.append((i,start,actual,path.name))
            md['split'].update({'completed':i,'progress':round(100*i/len(windows),1)})
            db.execute('UPDATE assets SET metadata=:md,updated=:now WHERE id=:id',
                {'md':json.dumps(md,ensure_ascii=False),'now':time.time(),'id':asset_id})
        if dest.exists():
            if any(dest.iterdir()):raise RuntimeError('Destino dos clipes já existe; não sobrescreva os derivados anteriores.')
            dest.rmdir()
        os.replace(staging,dest)
        now=time.time()
        with db.transaction() as conn:
            for i,start,length,filename in records:
                child_id=db.uid()
                rel=str((dest/filename).relative_to(db.ROOT))
                child_md={**json.loads(parent['metadata'] or '{}'),'source_start':start,
                          'position':f'{i}/{len(records)}','parent_sha256':parent.get('sha256'),'derivative':True}
                conn.exec_driver_sql('''INSERT INTO assets
                   (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,path,status,metadata,
                    duration,created,updated,error,category,tags,active,parent_id,clip_index,clip_total,usage_count,
                    sha256,media_type,size_bytes)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                   (child_id,'clip',f'{asset_id}:{i}',parent['url'],f'{parent["title"]} · clipe {i:03}',
                    parent['channel'],parent['source_class'],parent['rights_status'],parent['evidence'],rel,'READY',
                    json.dumps(child_md,ensure_ascii=False),length,now,now,None,parent.get('category'),
                    parent.get('tags') or '[]',parent['active'],asset_id,i,len(records),0,None,'video',
                    (dest/filename).stat().st_size))
            md['split'].update({'status':'READY','progress':100})
            conn.exec_driver_sql("UPDATE assets SET status='READY',metadata=?,error=NULL,updated=? WHERE id=?",
                                (json.dumps(md,ensure_ascii=False),now,asset_id))
        return {'status':'READY','asset_id':asset_id,'clips':len(records)}
    except Exception as exc:
        shutil.rmtree(staging,ignore_errors=True)
        # If filesystem rename was successful but SQLite failed, preserve the output for manual recovery.
        db.execute("UPDATE assets SET status='SPLIT_FAILED',error=:error,updated=:now WHERE id=:id",
                   {'error':str(exc)[-1000:],'now':time.time(),'id':asset_id})
        raise


def register_downloaded(video: dict, path: Path):
    """Cache a licensed remote source as an immutable original; split it asynchronously."""
    if video.get('rights')!='AUTHORIZED' or not video.get('evidence'):return None
    from backend.assets import canonical_id
    original_id=canonical_id(video.get('url') or '')
    if original_id:
        found=db.rows('SELECT id FROM assets WHERE source_id=:id AND kind IN (\'shorts\',\'uploads\') LIMIT 1',{'id':original_id})
        if found and db.rows('SELECT path FROM assets WHERE id=:id AND path IS NOT NULL',{'id':found[0]['id']}):return found[0]['id']
    checksum=file_sha256(path)
    now=time.time();asset_id=db.uid()
    suffix=path.suffix.lower()
    dest=db.ROOT/'assets/uploads/video'/(asset_id+suffix)
    dest.parent.mkdir(parents=True,exist_ok=True)
    shutil.copy2(path,dest)
    duration=float(__import__('backend.media',fromlist=['probe']).probe(path)['format']['duration'])
    db.execute('''INSERT INTO assets
      (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,path,status,metadata,duration,
      created,updated,category,tags,active,sha256,media_type,size_bytes)
      VALUES (:id,'uploads',:source_id,:url,:title,:channel,'THIRD_PARTY','AUTHORIZED',:evidence,:path,'READY',
      :metadata,:duration,:now,:now,'b-roll','[]',1,:hash,'video',:bytes)''',
      {'id':asset_id,'source_id':original_id or checksum,'url':video['url'],'title':video.get('title') or original_id,
       'channel':video.get('credits') or '', 'evidence':video['evidence'],'path':str(dest.relative_to(db.ROOT)),
       'metadata':json.dumps({'origin':'URL'},ensure_ascii=False),'duration':duration,'now':now,
       'hash':checksum,'bytes':dest.stat().st_size})
    mark_for_slicing(asset_id)
    return asset_id
