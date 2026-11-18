"""Resumable, authenticated, server-side streamed multi-file uploads.

No original is modified: session files are atomically promoted into assets/uploads.
Unsafe paths are never derived from user filenames. Uploads require authorization
and do not confer third-party reuse rights automatically.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import time
from pathlib import Path
from backend import core as db

TEMP = db.ROOT/'temp'/'uploads'
DEST = db.ROOT/'assets'/'uploads'
TEMP.mkdir(parents=True,exist_ok=True)
for sub in ('video','audio','image','font','subtitle','logo'):(DEST/sub).mkdir(parents=True,exist_ok=True)

FILE_TYPES={
    'video':{'.mp4','.mov','.webm','.mkv'},
    'audio':{'.mp3','.wav','.m4a'},
    'image':{'.png','.jpg','.jpeg','.webp','.gif'},
    'font':{'.ttf','.otf'},
    'subtitle':{'.srt'},
    'logo':{'.png','.jpg','.jpeg','.webp','.gif'},
}
CATEGORIES={'gameplay','b-roll','musica','efeito sonoro','imagem de fundo','logo','outro'}


def validate_type(filename,category):
    suffix=Path(filename).suffix.lower()
    kinds=[kind for kind,allowed in FILE_TYPES.items() if suffix in allowed]
    if not kinds:raise ValueError('Formato não aceito: '+suffix)
    if category not in CATEGORIES:raise ValueError('Categoria inválida.')
    if category=='musica' or category=='efeito sonoro':
        if 'audio' not in kinds:raise ValueError('Categoria de áudio exige MP3, WAV ou M4A.')
        return 'audio'
    if category=='logo':
        if 'logo' not in kinds:raise ValueError('Logo precisa ser uma imagem suportada.')
        return 'logo'
    if category=='imagem de fundo':
        if 'image' not in kinds:raise ValueError('Imagem de fundo exige PNG, JPG, WEBP ou GIF.')
        return 'image'
    # Gameplay / B-roll only video. 'other' supports remaining file types.
    if category in ('gameplay','b-roll'):
        if 'video' not in kinds:raise ValueError('Gameplay/B-roll exige arquivo de vídeo.')
        return 'video'
    return 'image' if 'image' in kinds else kinds[0]


def _session_path(sid):
    if not re.fullmatch(r'[a-f0-9]{32}',sid):raise ValueError('ID de upload inválido.')
    return TEMP/(sid+'.part')


def create_session(item):
    """Caller supplies a file fingerprint; full SHA-256 is verified after receiving."""
    kind=validate_type(item.filename,item.category)
    limit=db.settings().upload_max_mb*1024*1024
    if item.size<=0 or item.size>limit:raise ValueError(f'Tamanho inválido; máximo configurado: {db.settings().upload_max_mb} MB.')
    if item.source_class not in ('OWNED_GENERATED','OFFICIAL','THIRD_PARTY'):
        raise ValueError('Origem inválida.')
    if not re.fullmatch('[a-fA-F0-9]{64}',item.fingerprint):raise ValueError('Identificador de upload inválido.')
    found=db.rows("""SELECT * FROM upload_sessions WHERE sha256=:fp AND filename=:filename
        AND size_bytes=:size AND state='UPLOADING' ORDER BY created DESC LIMIT 1""",
        {'fp':item.fingerprint,'filename':item.filename,'size':item.size})
    if found:
        session=found[0]
        part=_session_path(session['id'])
        bytes_now=part.stat().st_size if part.exists() else 0
        if bytes_now>item.size:raise ValueError('Upload parcial maior que o arquivo.')
        db.execute("UPDATE upload_sessions SET received=:n,state='UPLOADING' WHERE id=:id",
            {'n':bytes_now,'id':session['id']})
        return {'id':session['id'],'offset':bytes_now,'size':item.size,'resumed':True}
    writing=db.rows("SELECT id,updated FROM upload_sessions WHERE sha256=:fp AND filename=:filename AND size_bytes=:size AND state='WRITING' LIMIT 1",{'fp':item.fingerprint,'filename':item.filename,'size':item.size})
    if writing and time.time()-writing[0]['updated']<180:
        raise ValueError('Outro bloco deste arquivo está em andamento. Aguarde e retome o envio.')
    if writing:
        db.execute("UPDATE upload_sessions SET state='UPLOADING' WHERE id=:id",{'id':writing[0]['id']})
        return create_session(item)
    sid=db.uid();now=time.time()
    _session_path(sid).touch(exist_ok=False)
    db.execute('''INSERT INTO upload_sessions
      (id,filename,size_bytes,received,state,category,tags,source_class,evidence,media_type,sha256,updated,created)
      VALUES (:id,:filename,:size,0,'UPLOADING',:category,:tags,:class,:evidence,:media,:sha,:now,:now)''',
      {'id':sid,'filename':item.filename[:255],'size':item.size,'category':item.category,
       'tags':json.dumps(item.tags[:25],ensure_ascii=False),'class':item.source_class,
       'evidence':item.evidence[:2000],'media':kind,'sha':item.fingerprint,'now':now})
    return {'id':sid,'offset':0,'size':item.size,'resumed':False}


def status(sid):
    rows=db.rows('SELECT * FROM upload_sessions WHERE id=:id',{'id':sid})
    if not rows:raise ValueError('Sessão de upload não encontrada.')
    item=rows[0];p=_session_path(sid)
    return {'id':sid,'offset':p.stat().st_size if p.is_file() else item['received'],
            'size':item['size_bytes'],'state':item['state'],'error':item['error']}


async def append_chunk(sid,offset,stream):
    rows=db.rows('SELECT * FROM upload_sessions WHERE id=:id',{'id':sid})
    if not rows:raise ValueError('Sessão inválida.')
    session=rows[0]
    path=_session_path(sid)
    # Atomic claim; reject two concurrent chunks rather than corrupting the file.
    if db.execute("UPDATE upload_sessions SET state='WRITING' WHERE id=:id AND state='UPLOADING'",{'id':sid})!=1:
        raise ValueError('Sessão ocupada ou já finalizada.')
    try:
        actual=path.stat().st_size
        db.execute('UPDATE upload_sessions SET updated=:now WHERE id=:id',{'now':time.time(),'id':sid})
        if offset!=actual:raise ValueError(f'Offset diferente do recebido: esperado {actual}, veio {offset}.')
        with path.open('ab') as dest:
            async for chunk in stream:
                if not chunk:continue
                if dest.tell()+len(chunk)>session['size_bytes']:
                    raise ValueError('Bloco excede o tamanho declarado do arquivo.')
                dest.write(chunk)
            dest.flush();os.fsync(dest.fileno())
        size=path.stat().st_size
        db.execute("UPDATE upload_sessions SET state='UPLOADING',received=:n,updated=:now WHERE id=:id",
                   {'n':size,'now':time.time(),'id':sid})
        return {'offset':size,'size':session['size_bytes']}
    except Exception:
        db.execute("UPDATE upload_sessions SET state='UPLOADING',received=:n,updated=:now WHERE id=:id",
                   {'n':path.stat().st_size,'now':time.time(),'id':sid})
        raise


def check_format(path,media_type):
    if media_type in ('video','audio'):
        from backend.media import probe
        result=probe(path)
        streams=result.get('streams',[])
        if not any(s.get('codec_type')==media_type for s in streams):
            raise ValueError('Arquivo não contém '+('vídeo' if media_type=='video' else 'áudio')+' válido.')
        return float(result['format']['duration'])
    if media_type in ('image','logo'):
        from PIL import Image
        with Image.open(path) as image:image.verify()
    elif media_type=='subtitle':
        with path.open('rb') as data:
            snippet=data.read(1024*1024).decode('utf-8-sig')
            if '-->' not in snippet:raise ValueError('Legenda SRT inválida.')
    elif media_type=='font':
        with path.open('rb') as src:
            if src.read(4) not in (b'OTTO',b'\x00\x01\x00\x00',b'true',b'typ1'):
                raise ValueError('Formato de fonte inválido.')
    return None


def finish(sid):
    session=db.rows('SELECT * FROM upload_sessions WHERE id=:id',{'id':sid})
    if not session:raise ValueError('Sessão inexistente.')
    item=session[0]
    if item['state']!='UPLOADING':raise ValueError('Upload ainda em processamento.')
    path=_session_path(sid)
    if not path.is_file() or path.stat().st_size!=item['size_bytes']:
        raise ValueError('Upload incompleto; envie os blocos restantes antes de finalizar.')
    if db.execute("UPDATE upload_sessions SET state='FINALIZING' WHERE id=:id AND state='UPLOADING'",{'id':sid})!=1:
        raise ValueError('Upload já está sendo finalizado.')
    try:
        duration=check_format(path,item['media_type'])
        from backend.clips import file_sha256
        sha=file_sha256(path)
        # Same bytes already in library: reuse the asset without changing provenance/rights.
        duplicate=db.rows("SELECT * FROM assets WHERE sha256=:sha AND parent_id IS NULL AND path IS NOT NULL LIMIT 1",{'sha':sha})
        if duplicate and (db.ROOT/duplicate[0]['path']).is_file():
            path.unlink(missing_ok=True)
            db.execute("UPDATE upload_sessions SET state='DONE',received=:n,updated=:now WHERE id=:id",
                       {'n':item['size_bytes'],'now':time.time(),'id':sid})
            return {'asset':duplicate[0],'duplicate':True}
        asset_id=db.uid();suffix=Path(item['filename']).suffix.lower()
        target=DEST/item['media_type']/(asset_id+suffix)
        # Never overwrite any prior original.
        os.replace(path,target)
        tags=json.loads(item['tags'] or '[]')
        evidence=(item['evidence'] or '').strip()
        rights='AUTHORIZED' if len(evidence)>=10 else 'REVIEW_REQUIRED'
        status='READY' if rights=='AUTHORIZED' else 'PENDING_RIGHTS'
        now=time.time()
        metadata={'uploaded_filename':item['filename'],'uploaded_at':now,'source_url':'',
                  'channel':'upload local','category':item['category'],'tags':tags}
        db.execute('''INSERT INTO assets
          (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,path,status,metadata,
           duration,created,updated,category,tags,active,sha256,media_type,size_bytes)
          VALUES (:id,'uploads',:source_id,'',:title,'upload local',:class,:rights,:evidence,:path,:status,
           :metadata,:duration,:now,:now,:category,:tags,1,:sha,:media,:size)''',
          {'id':asset_id,'source_id':'upload:'+sha,'title':Path(item['filename']).stem[:300],
           'class':item['source_class'],'rights':rights,'evidence':evidence,
           'path':str(target.relative_to(db.ROOT)),'status':status,'metadata':json.dumps(metadata,ensure_ascii=False),
           'duration':duration,'now':now,'category':item['category'],'tags':item['tags'],'sha':sha,
           'media':item['media_type'],'size':item['size_bytes']})
        if item['media_type']=='video':
            from backend.clips import mark_for_slicing
            mark_for_slicing(asset_id)
        db.execute("UPDATE upload_sessions SET state='DONE',received=:n,updated=:now WHERE id=:id",
                   {'n':item['size_bytes'],'now':time.time(),'id':sid})
        return {'asset':db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})[0], 'duplicate':False}
    except Exception as exc:
        db.execute("UPDATE upload_sessions SET state='FAILED',error=:error,updated=:now WHERE id=:id",
                   {'error':str(exc)[-700:],'now':time.time(),'id':sid})
        raise


def prune_sessions(days: int):
    """Only stale partial uploads are purged; promoted library originals are untouched."""
    cutoff=time.time()-days*86400
    stale=db.rows('SELECT id,state FROM upload_sessions WHERE updated<:cutoff',{'cutoff':cutoff})
    for item in stale:
        if item['state']=='WRITING':continue
        _session_path(item['id']).unlink(missing_ok=True)
        db.execute('DELETE FROM upload_sessions WHERE id=:id',{'id':item['id']})
    return len(stale)
