"""Durable daily quotas; shorts target ALWAYS reflects Settings.daily_limit.

Approval means automated validation passed and an item is available in a
human-review queue. An item merely enqueued or rendered does not count.
"""
from __future__ import annotations
import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from backend import core as db

DEFAULT_LIVE_CUTS = 5
TIME_ZONE = 'America/Sao_Paulo'
FINISHED_SHORTS = ("APPROVED",)
ACTIVE_SHORTS = ("QUEUED", "PROCESSING", "RETRY", "PENDING_RIGHTS_REVIEW")
FAILED_SHORTS = ("FAILED", "REJECTED", "DISCARDED", "PIPELINE_ERROR", "AWAITING_MANUAL_DECISION")
CLIP_FINISHED = ("REVIEW_PENDING", "APPROVED")
CLIP_ACTIVE = ("QUEUED", "PROCESSING", "RETRY")
CLIP_FAILED = ("FAILED", "REJECTED", "BLOCKED", "DISCARDED")


def _write(path: Path, data: dict) -> None:
    serialized = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    if path.is_file() and path.read_text('utf-8') == serialized:
        return
    db.atomic(path, serialized)


def config() -> dict:
    """Settings.daily_limit is the operator-defined shorts target; never duplicate X."""
    settings = db.settings()
    extras = db.get_setting('quota_options', {}) or {}
    deadline = str(extras.get('deadline_local') or '23:59')
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', deadline):
        deadline = '23:59'
    target = {
        'date_local': db.today(),
        'lives_cuts': DEFAULT_LIVE_CUTS,
        'shorts': settings.daily_limit,
        'shorts_source': 'settings.daily_limit (Vídeos por dia)',
        'deadline_local': deadline,
        'max_attempts_per_item': 3,
        'min_live_score':max(60,min(100,int(extras.get('min_live_score',70)))),
        'timezone': TIME_ZONE,
    }
    _write(db.DATA / 'daily_quota.json', target)
    return target


def set_deadline(value: str) -> dict:
    if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', value or ''):
        raise ValueError('Informe um horário HH:MM no formato 24h.')
    options=db.get_setting('quota_options',{}) or {}
    db.put_setting('quota_options', {**options,'deadline_local': value})
    return config()


def set_min_live_score(value: int) -> dict:
    if not 60 <= int(value) <= 100:
        raise ValueError('Score mínimo permitido: entre 60 e 100.')
    options=db.get_setting('quota_options',{}) or {}
    db.put_setting('quota_options',{**options,'min_live_score':int(value)})
    return config()


def within_deadline(conf=None, at=None) -> bool:
    conf = conf or config()
    local = at or datetime.now(ZoneInfo(TIME_ZONE))
    return local.strftime('%H:%M') <= conf['deadline_local']


def state() -> dict:
    conf = config()
    from_timestamp, to_timestamp = db.local_day_bounds()
    shorts = db.rows(
        """SELECT v.id, v.status, v.title, v.error, v.url, v.approved_at,
                  (SELECT COALESCE(MAX(j.attempts),0) FROM jobs j
                   WHERE j.video_id=v.id AND j.kind='pipeline') AS attempts
           FROM videos v WHERE v.test=0 AND
             ((v.created>=:begin AND v.created<:end) OR
              (v.approved_at>=:begin AND v.approved_at<:end))
           ORDER BY v.created""", {'begin':from_timestamp,'end':to_timestamp})
    try:
        clips = db.rows(
            """SELECT id, channel_id, video_id, title, status, error, attempts,
                      file_path, segment_start, segment_end, score, created
               FROM live_clips WHERE created>=:begin AND created<:end ORDER BY created""",
            {'begin':from_timestamp,'end':to_timestamp})
    except Exception:
        clips = []
    approved_shorts = []
    active_shorts = []
    rejected_shorts = []
    attempts = {}
    failures = []
    for video in shorts:
        attempts['short:'+video['id']] = int(video['attempts'] or 0)
        # Keep a single count per approved video, regardless of destinations.
        if (video['status'] in FINISHED_SHORTS and video['approved_at'] is not None
                and from_timestamp <= video['approved_at'] < to_timestamp
                and db.rows('SELECT id FROM publications WHERE video_id=:id LIMIT 1', {'id':video['id']})):
            approved_shorts.append(video['id'])
        elif video['status'] in ACTIVE_SHORTS:
            active_shorts.append(video['id'])
        elif video['status'] in FAILED_SHORTS:
            rejected_shorts.append(video['id'])
            failures.append({'kind':'short','id':video['id'],'reason':video['error'] or video['status']})
    approved_clips, active_clips, rejected_clips = [], [], []
    for clip in clips:
        attempts['live_cut:'+clip['id']] = int(clip['attempts'] or 0)
        if clip['status'] in CLIP_FINISHED and clip['file_path'] and (db.ROOT/clip['file_path']).is_file():
            approved_clips.append(clip['id'])
        elif clip['status'] in CLIP_ACTIVE:
            active_clips.append(clip['id'])
        elif clip['status'] in CLIP_FAILED:
            rejected_clips.append(clip['id'])
            failures.append({'kind':'live_cut','id':clip['id'],'reason':clip['error'] or clip['status']})
    missing = {'shorts':max(0,conf['shorts']-len(approved_shorts)),
               'lives_cuts':max(0,conf['lives_cuts']-len(approved_clips))}
    complete = not any(missing.values())
    remaining_time = within_deadline(conf)
    result = {
        'day':db.today(), 'config':conf,
        'target':{'shorts':conf['shorts'],'lives_cuts':conf['lives_cuts']},
        'approved':{'shorts':len(approved_shorts),'lives_cuts':len(approved_clips)},
        'approved_ids':{'shorts':approved_shorts,'lives_cuts':approved_clips},
        'pending':{'shorts':len(active_shorts),'lives_cuts':len(active_clips)},
        'rejected':{'shorts':len(rejected_shorts),'lives_cuts':len(rejected_clips)},
        'missing':missing, 'attempts_per_item':attempts, 'failures':failures,
        'deadline_reached':not remaining_time,
        'status':'COMPLETA' if complete else 'EM_ANDAMENTO' if remaining_time else 'PARCIAL',
        'live_clip_scheduler_status':db.get_setting('live_clip_scheduler_status','Aguardando busca de VODs elegíveis.'),
        'manual_review_only':True
    }
    _write(db.DATA / 'quota_state.json', result)
    if result['status'] in ('PARCIAL','COMPLETA'):
        report(result)
    return result


def report(snapshot=None) -> str:
    snapshot = snapshot or state()
    cfg=snapshot['config']
    missing=snapshot['missing']
    lines=[
        '# Relatório da cota — '+snapshot['day'],
        '',
        '- Status: **'+snapshot['status']+'**',
        '- Shorts: '+str(snapshot['approved']['shorts'])+'/'+str(cfg['shorts'])+' aprovados e enviados para revisão humana',
        '- Cortes de lives: '+str(snapshot['approved']['lives_cuts'])+'/5 aprovados e enviados para revisão humana',
        '- Horário limite: '+cfg['deadline_local']+' ('+TIME_ZONE+')',
        '- Publicação: manual; nenhuma postagem automática',
        '',
        '## Itens aprovados (IDs)',
        '- Shorts: '+(', '.join(snapshot['approved_ids']['shorts']) or 'nenhum'),
        '- Cortes: '+(', '.join(snapshot['approved_ids']['lives_cuts']) or 'nenhum'),
        '',
        '## Falhas registradas'
    ]
    lines.extend('- '+failure['kind']+' '+failure['id']+': '+failure['reason'].replace('\n',' ')[:220]
                 for failure in snapshot['failures'])
    if not snapshot['failures']:
        lines.append('- Nenhuma reprovação registrada no dia.')
    lines += ['','## Links locais dos cortes e Shorts']
    for clip_id in snapshot['approved_ids']['lives_cuts']:
        lines.append('- Corte '+clip_id+': /api/live-clips/'+clip_id+'/file')
    for short_id in snapshot['approved_ids']['shorts']:
        lines.append('- Short '+short_id+': /api/files/'+short_id)
    lines += ['','## Pendências e ações para o operador']
    if missing['shorts']:
        lines.append('- Faltam '+str(missing['shorts'])+' Shorts. Verificar radar público recente, direitos, fontes válidas e jobs técnicos.')
    if missing['lives_cuts']:
        lines.append('- Faltam '+str(missing['lives_cuts'])+' cortes de lives. '+snapshot.get('live_clip_scheduler_status','')+' Verificar autorização, YouTube API, WhisperX e VODs encerrados dos últimos 30 dias.')
    if not any(missing.values()):
        lines.append('- Cota alcançada; revisar e publicar manualmente.')
    text='\n'.join(lines)+'\n'
    db.atomic(db.ROOT/'reports'/'quota_report.md',text)
    db.atomic(db.ROOT/'reports'/'daily_report.md',text)
    return text
