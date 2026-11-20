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
ACTIVE_SHORTS = ("QUEUED", "PROCESSING", "RETRY")
MANUAL_REVIEW_SHORTS = ("PENDING_RIGHTS_REVIEW", "AWAITING_MANUAL_DECISION")
FAILED_SHORTS = ("FAILED", "REJECTED", "DISCARDED", "PIPELINE_ERROR")
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
    manual_review_shorts = []
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
        elif video['status'] in MANUAL_REVIEW_SHORTS:
            manual_review_shorts.append(video['id'])
        elif video['status'] in FAILED_SHORTS:
            rejected_shorts.append(video['id'])
            failures.append({'kind':'short','id':video['id'],'reason':video['error'] or video['status']})
    approved_clips, active_clips, rejected_clips = [], [], []
    # A single live has 3 independent deliverables, not a single quota slot.
    # Each completed output is counted exactly once; unfinished expected
    # outputs reserve quota while that live is processing.
    for clip in clips:
        attempts['live_cut:'+clip['id']] = int(clip['attempts'] or 0)
        children=db.rows(
            "SELECT id,status,file_path,ordinal FROM live_clip_outputs WHERE parent_id=:parent",
            {'parent':clip['id']})
        for child in children:
            if (child['status'] in CLIP_FINISHED and child['file_path'] and
                (db.ROOT/child['file_path']).is_file()):
                approved_clips.append(child['id'])
            elif child['status'] in CLIP_FAILED:
                rejected_clips.append(child['id'])
        # Old one-cut rows migrated to a child keep their single valid output.
        expected=max(3,int(clip.get('cut_target') or 3))
        ready_count=sum(x['status'] in CLIP_FINISHED or x['status']=='DISCARDED'
                        for x in children)
        if clip['status'] in CLIP_ACTIVE:
            active_clips.extend(clip['id']+':'+str(i) for i in range(
                max(0,expected-ready_count)))
        elif clip['status'] in CLIP_FAILED:
            rejected_clips.append(clip['id'])
            failures.append({'kind':'live_cut','id':clip['id'],
                             'reason':clip['error'] or clip['status']})
    # This is a production cap, not a requirement to force every item through
    # human approval before allowing the next one to start.
    used_shorts = db.production_usage()
    missing = {'shorts':max(0,conf['shorts']-len(approved_shorts)),
               'lives_cuts':max(0,conf['lives_cuts']-len(approved_clips))}
    complete = not any(missing.values())
    remaining_time = within_deadline(conf)
    result = {
        'day':db.today(), 'config':conf,
        'target':{'shorts':conf['shorts'],'lives_cuts':conf['lives_cuts']},
        'approved':{'shorts':len(approved_shorts),'lives_cuts':len(approved_clips)},
        'approved_ids':{'shorts':approved_shorts,'lives_cuts':approved_clips},
        'pending':{'shorts':len(active_shorts)+len(manual_review_shorts),'lives_cuts':len(active_clips)},
        'manual_review':{'shorts':len(manual_review_shorts)},
        'manual_review_ids':{'shorts':manual_review_shorts},
        'capacity_used':{'shorts':used_shorts},
        'capacity_remaining':{'shorts':max(0,conf['shorts']-used_shorts)},
        'rejected':{'shorts':len(rejected_shorts),'lives_cuts':len(rejected_clips)},
        'missing':missing, 'attempts_per_item':attempts, 'failures':failures,
        'deadline_reached':not remaining_time,
        'status':'COMPLETA' if complete else 'EM_ANDAMENTO' if remaining_time else 'PARCIAL',
        'live_clip_scheduler_status':db.get_setting('live_clip_scheduler_status','Aguardando busca de VODs elegíveis.'),
        'manual_review_only':True,
        'excluido_pelo_operador': (
            int(db.get_setting('operator_cleanup_deleted_count',0) or 0)
            if db.get_setting('operator_cleanup_hold_day')==db.today() else 0),
        'automatic_replacement_paused_by_operator':(
            db.get_setting('operator_cleanup_hold_day')==db.today())
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
        '- Vagas de produção ocupadas hoje: '+str(snapshot['capacity_used']['shorts'])+'/'+str(cfg['shorts'])+' (incluindo revisão manual)',
        '- Aguardando decisão humana: '+str(snapshot['manual_review']['shorts'])+' Shorts',
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
        lookup=db.rows("SELECT parent_id FROM live_clip_outputs WHERE id=:id",{'id':clip_id})
        if lookup:
            lines.append('- Corte '+clip_id+': /api/live-clips/'+lookup[0]['parent_id']+
                         '/outputs/'+clip_id+'/file')
    for short_id in snapshot['approved_ids']['shorts']:
        lines.append('- Short '+short_id+': /api/files/'+short_id)
    lines += ['','## Pendências e ações para o operador']
    if snapshot['manual_review_ids']['shorts']:
        lines.append('- Aguardando aprovação/direitos: '+', '.join(snapshot['manual_review_ids']['shorts'])+'. A fila segue sem depender da decisão humana.')
    if missing['shorts'] and snapshot['capacity_remaining']['shorts']>0:
        lines.append('- Faltam '+str(missing['shorts'])+' Shorts aprovados. Verificar radar público recente, direitos, fontes válidas e jobs técnicos.')
    elif missing['shorts']:
        lines.append('- Limite diário ocupado; '+str(missing['shorts'])+' Shorts ainda não foram aprovados. Não abrir novas produções até liberar uma vaga ou iniciar novo dia.')
    if missing['lives_cuts']:
        lines.append('- Faltam '+str(missing['lives_cuts'])+' cortes de lives. '+snapshot.get('live_clip_scheduler_status','')+' Verificar autorização, disponibilidade pública, WhisperX e VODs encerrados dos últimos 30 dias.')
    if not any(missing.values()):
        lines.append('- Cota alcançada; revisar e publicar manualmente.')
    text='\n'.join(lines)+'\n'
    db.atomic(db.ROOT/'reports'/'quota_report.md',text)
    db.atomic(db.ROOT/'reports'/'daily_report.md',text)
    return text
