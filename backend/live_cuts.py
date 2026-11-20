"""Rights-first live cut planning, with strict public metadata and 7-day deduplication."""
from __future__ import annotations
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from backend import core as db
from backend.integrations import IntegrationError
from backend.public_youtube import video_id_from_url, public_video_info, public_ended_live, video_published_at
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
    """Confirm rights and the public, ended VOD using anonymous metadata only."""
    video_id=str(entry.get('video_id') or entry.get('id') or '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id):
        raise ValueError('ID de live inválido.')
    channel_id=str(entry.get('channel_id') or '')
    if not authorized_channel(channel_id):
        raise ValueError('Canal fora da clipping_allowlist.json (autorização obrigatória).')
    info=public_video_info('https://www.youtube.com/watch?v='+video_id)
    if info.get('channel_id')!=channel_id:
        raise ValueError('O canal da live não corresponde à autorização cadastrada.')
    if not public_ended_live(info,days=RADAR_WINDOW_DAYS):
        raise ValueError('A URL deve ser um VOD público, encerrado, não restrito, publicado nos últimos 30 dias.')
    return info


def submit_live_url(url: str, evidence: str = '', webcam_anchor: str='bottom_left') -> dict:
    """Operator-selected VOD: one queued job producing three distinct cuts."""
    from backend.live_clip_layout import validate_anchor
    webcam_anchor=validate_anchor(webcam_anchor)
    from backend.daily_quota import config, within_deadline
    vid=video_id_from_url(url)
    if not within_deadline(config()):
        raise ValueError('Horário limite da cota atingido. Envie a live no próximo período.')
    # WhisperX runs in the worker image (not the API image). The worker
    # explicitly checks this prerequisite before accepting/rendering a job.
    # No cookies, account, YouTube Data API key or video download for this lookup.
    info=public_video_info('https://www.youtube.com/watch?v='+vid)
    channel_id=str(info.get('channel_id') or '')
    if not CHANNEL_PATTERN.fullmatch(channel_id):
        raise ValueError('O canal original não pôde ser identificado pelo link público.')
    if not authorized_channel(channel_id) and (evidence or '').strip():
        allow_creator(channel_id,evidence)
    if not authorized_channel(channel_id):
        record_right(vid,channel_id,'BLOCKED','Canal sem permissão de corte cadastrada.')
        raise ValueError('Informe uma autorização válida para reutilizar a live do canal UC '+channel_id+'.')
    if not public_ended_live(info,days=RADAR_WINDOW_DAYS):
        record_right(vid,channel_id,'BLOCKED','VOD não confirmado como público, encerrado e recente.')
        raise ValueError('É necessário um VOD público, encerrado e publicado nos últimos 30 dias.')
    title=str(info.get('title') or 'Live pública autorizada')[:250]
    if recently_used(vid,title=title):
        raise ValueError('Essa live ou tema já foi utilizado nos últimos sete dias.')
    exists=db.rows('SELECT id,status FROM live_clips WHERE video_id=:id',{'id':vid})
    if exists:
        raise ValueError('Esta live já possui um corte registrado no histórico.')
    permission=authorized_channel(channel_id)
    ident=db.uid()
    now=time.time()
    db.execute("""INSERT INTO live_clips
       (id,video_id,channel_id,title,source_url,rights_evidence,status,
        webcam_anchor,cut_target,attempts,score,created,updated)
       VALUES (:id,:video,:channel,:title,:url,:rights,'QUEUED',:anchor,3,0,0,:now,:now)""",
        {'id':ident,'video':vid,'channel':channel_id,'title':title,
         'url':'https://www.youtube.com/watch?v='+vid,
         'rights':permission['evidence'],'now':now,'anchor':webcam_anchor})
    record_right(vid,channel_id,'AUTHORIZED',
                 'Seleção manual: URL pública + VOD encerrado + licença declarada verificados.')
    db.enqueue('live_cut:'+ident,unique_key='livecut:'+ident)
    return {'queued':True,'clip_id':ident,'title':title,'channel_id':channel_id,
            'expected_cuts':3,'webcam_anchor':webcam_anchor,
            'message':'Live aceita para gerar três cortes distintos com revisão individual.'}


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
    if quota['approved']['lives_cuts']+quota['pending']['lives_cuts']>=quota['target']['lives_cuts']:
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
                webcam_anchor,cut_target,attempts,score,created,updated)
               VALUES (:id,:video,:channel,:title,:url,:rights,'QUEUED',
                       'bottom_left',3,0,:score,:now,:now)""",
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
    db.execute("""UPDATE live_clips SET status=:status,stage=:stage,
                  attempts=:attempts,error=:error,updated=:now WHERE id=:id""",
               {'id':clip_id,'status':status,'stage':status,'attempts':attempts,
                'error':str(message)[:500],'now':time.time()})
    if status=='FAILED':
        record=db.rows('SELECT video_id,channel_id FROM live_clips WHERE id=:id',{'id':clip_id})
        if record:
            record_right(record[0]['video_id'],record[0]['channel_id'],
                         'FAILED','Falha após 3 tentativas técnicas: '+str(message)[:350])
    return status
