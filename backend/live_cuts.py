"""Rights-first live cut planning, with strict public metadata and 7-day deduplication."""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend import core as db
from backend.integrations import youtube_get, IntegrationError
from backend.viral_radar20 import RADAR_WINDOW_DAYS, _utc_time, CHANNEL_PATTERN, allowed_public_video

MIN_SCORE = 70
MIN_DURATION = 20
MAX_DURATION = 60
ALLOWLIST = 'clipping_allowlist.json'
RIGHTS_LOG = 'rights_log.json'


def _read(name: str, default):
    file=db.DATA/name
    try:
        return json.loads(file.read_text('utf-8')) if file.is_file() else default
    except (OSError,ValueError):
        return default


def _write(name: str, value):
    db.atomic(db.DATA/name, json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def allowlist():
    return _read(ALLOWLIST, {'channels':[], 'policy':'Explicit permission required before any download.'})


def allow_creator(channel_id: str, evidence: str, owner: str='operator'):
    if not CHANNEL_PATTERN.fullmatch(channel_id or ''):
        raise ValueError('Channel ID deve começar com UC e conter 24 caracteres.')
    evidence=(evidence or '').strip()
    if len(evidence)<15:
        raise ValueError('Forneça comprovação verificável de autorização para criar e publicar cortes.')
    channels=allowlist()['channels']
    channels=[c for c in channels if c['channel_id'] != channel_id]
    channels.append({'channel_id':channel_id, 'evidence':evidence[:2000],
                     'approved_by':owner[:100], 'updated_at':datetime.now(timezone.utc).isoformat(),
                     'status':'OPERATOR_DECLARED'})
    _write(ALLOWLIST, {'channels':channels,'policy':'Only operator-declared clip permissions.'})
    return channels[-1]


def remove_creator(channel_id: str):
    channels=[c for c in allowlist()['channels'] if c['channel_id']!=channel_id]
    _write(ALLOWLIST,{'channels':channels,'policy':'Only operator-declared clip permissions.'})
    return {'removed':channel_id}


def authorized_channel(channel_id: str):
    return next((x for x in allowlist()['channels']
                 if x['channel_id']==channel_id and
                 len(str(x.get('evidence') or '').strip())>=15),None)


def record_right(video_id: str, channel_id: str, outcome: str, message: str):
    data=_read(RIGHTS_LOG, {'entries':[]})
    data['entries'].append({'at':datetime.now(timezone.utc).isoformat(),'video_id':video_id,
                            'channel_id':channel_id,'status':outcome,'detail':message[:400]})
    data['entries']=data['entries'][-5000:]
    _write(RIGHTS_LOG,data)


def verified_live(entry: dict):
    """Recheck via official API immediately before any download or processing."""
    ids=str(entry.get('video_id') or entry.get('id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',ids):
        raise ValueError('ID de live inválido.')
    videos=youtube_get('videos',{'part':'snippet,status,contentDetails,liveStreamingDetails',
                                 'id':ids}).get('items',[])
    if not videos:
        raise ValueError('VOD público removido ou não encontrado.')
    video=videos[0]
    if not allowed_public_video(video):
        raise ValueError('A live não está pública nos últimos 30 dias ou tem restrições.')
    ended=_utc_time(video.get('liveStreamingDetails',{}).get('actualEndTime'))
    if ended is None or ended>datetime.now(timezone.utc):
        raise ValueError('A live precisa estar encerrada e o VOD público.')
    if video.get('snippet',{}).get('channelId') != entry['channel_id']:
        raise ValueError('Canal da live não coincide com a origem.')
    if not authorized_channel(entry['channel_id']):
        raise ValueError('Canal fora da clipping_allowlist.json.')
    return video


def _topic_fingerprint(title: str) -> str:
    words=re.findall(r'[a-z0-9]+',str(title or '').lower())
    ignore={'gta','vi','6','live','ao','vivo','replay','do','de','da','para','com','the',
            'stream','brasil','video','jogando','games'}
    return '|'.join(sorted(set(w for w in words if len(w)>3 and w not in ignore)))


def recently_used(video_id: str, at=None, title: str='') -> bool:
    cutoff=(at if at is not None else time.time())-7*86400
    rows=db.rows(
        """SELECT video_id,title FROM live_clips WHERE created >= :cutoff
           AND status IN ('QUEUED','PROCESSING','RETRY','REVIEW_PENDING','APPROVED')""",
        {'cutoff':cutoff})
    topic=_topic_fingerprint(title)
    return any(item['video_id']==video_id or
               (topic and topic==_topic_fingerprint(item['title']))
               for item in rows)


def enqueue_next():
    """One job at a time. No authorized VOD => a partial quota, never a fabricated cut."""
    from backend.daily_quota import state, within_deadline
    settings=db.settings()
    quota=state()
    if not settings.automatic or settings.emergency_stop or not within_deadline(quota['config']):
        return {'queued':False,'reason':'Automação desativada, emergência ou deadline.'}
    if quota['approved']['lives_cuts']+quota['pending']['lives_cuts']>=5:
        return {'queued':False,'reason':'Cinco cortes aprovados/em andamento.'}
    if quota['pending']['lives_cuts']:
        return {'queued':False,'reason':'Já existe um corte em processamento.'}
    # Avoid downloading a multi-hour VOD when forced alignment is not installed.
    from importlib.util import find_spec
    if find_spec('whisperx') is None:
        return {'queued':False,
                'reason':'WhisperX não instalado no worker; alinhamento obrigatório ausente.'}
    sources=_read('recent_lives.json', {'items':[]}).get('items',[])
    ordered=sorted(sources,key=lambda x:(x.get('published_at',''), x.get('score',0)),reverse=True)
    cutoff=datetime.now(timezone.utc)-timedelta(days=RADAR_WINDOW_DAYS)
    for entry in ordered:
        vid=entry.get('id')
        if not vid or not authorized_channel(entry.get('channel_id','')):
            continue
        published=_utc_time(entry.get('published_at'))
        if not published or published<cutoff or not entry.get('ended'):
            continue
        if recently_used(vid,title=entry.get('title','')):
            continue
        # Failures max 3 attempts per VOD; replace with another VOD thereafter.
        past=db.rows("SELECT status,attempts FROM live_clips WHERE video_id=:id",{'id':vid})
        if past and (past[0]['status'] in ('FAILED','REJECTED','BLOCKED','DISCARDED') or
                     past[0]['attempts']>=3):
            continue
        try:
            checked=verified_live({'id':vid,'channel_id':entry['channel_id']})
        except (ValueError,IntegrationError) as exc:
            record_right(vid,entry['channel_id'],'BLOCKED',str(exc))
            continue
        permission=authorized_channel(entry['channel_id'])
        if not past:
            ident=db.uid()
            db.execute("""INSERT INTO live_clips
               (id,video_id,channel_id,title,source_url,rights_evidence,status,
                attempts,score,created,updated)
               VALUES (:id,:video,:channel,:title,:url,:rights,'QUEUED',0,:score,:now,:now)""",
                {'id':ident,'video':vid,'channel':entry['channel_id'],
                 'title':entry.get('title','Live pública')[:250],
                 'url':entry['url'],'rights':permission['evidence'],
                 'score':0,'now':time.time()})
        else:
            ident=db.rows("SELECT id FROM live_clips WHERE video_id=:id",{'id':vid})[0]['id']
            db.execute("UPDATE live_clips SET status='QUEUED',updated=:now WHERE id=:id",
                       {'id':ident,'now':time.time()})
        record_right(vid,entry['channel_id'],'AUTHORIZED','Permissão do operador e VOD encerrado verificados antes de enfileirar.')
        db.enqueue('live_cut:'+ident,unique_key='livecut:'+ident)
        return {'queued':True,'clip_id':ident,'source_url':entry['url']}
    return {'queued':False,'reason':'Sem lives públicas recentes e autorizadas disponíveis.'}


def mark_failed(clip_id: str, message: str, attempts: int):
    status='FAILED' if attempts>=3 else 'RETRY'
    db.execute("""UPDATE live_clips SET status=:status, attempts=:attempts,error=:error,updated=:now
                  WHERE id=:id""",
               {'id':clip_id,'status':status,'attempts':attempts,
                'error':str(message)[:500],'now':time.time()})
    if status=='FAILED':
        record=db.rows('SELECT video_id,channel_id FROM live_clips WHERE id=:id',{'id':clip_id})
        if record:
            record_right(record[0]['video_id'],record[0]['channel_id'],
                         'FAILED','Falha após 3 tentativas técnicas: '+str(message)[:350])
    return status
