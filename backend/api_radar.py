"""Authenticated optional radar, quota and live-cut routes, independent of API core."""
from __future__ import annotations
import json
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from backend import core as db
from backend.integrations import IntegrationError

router=APIRouter(prefix='/api')


@router.get('/operations/live')
def operations_live():
    """Read-only snapshot for the main dashboard, refreshed by the browser."""
    from backend.operations_monitor import snapshot
    return snapshot()


@router.get('/daily-quota')
def quota_state():
    from backend.daily_quota import state
    return state()


class DeadlineInput(BaseModel):
    deadline_local: str = Field(pattern=r'^(?:[01]\d|2[0-3]):[0-5]\d$')


@router.put('/daily-quota/deadline')
def update_deadline(body: DeadlineInput):
    from backend.daily_quota import set_deadline
    try:
        return set_deadline(body.deadline_local)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


class LiveScoreInput(BaseModel):
    min_live_score: int = Field(ge=60,le=100)


@router.put('/daily-quota/live-score')
def set_live_score(body: LiveScoreInput):
    from backend.daily_quota import set_min_live_score
    return set_min_live_score(body.min_live_score)


@router.get('/viral-radar/top-creators')
def get_top_creators():
    from backend.viral_radar20 import stored_top_creators
    return stored_top_creators()


@router.post('/viral-radar/top-creators/refresh')
def trigger_ranking_refresh():
    db.enqueue('top20_refresh',unique_key='top20:manual:'+db.uid())
    return {'queued':True,'message':'Atualização mensal de ranking enviada ao worker.'}


@router.post('/viral-radar/scan')
def trigger_radar_scan():
    db.enqueue('radar20_scan',unique_key='radar20:manual:'+db.uid())
    return {'queued':True,'message':'Pesquisa de conteúdos públicos recentes enviada ao worker.'}


@router.get('/viral-radar/latest')
def get_latest_radar():
    from backend.viral_radar20 import _load
    return {'radar':_load('viral_radar_'+db.today()+'.json',{'top':[],'status':'NOT_SCANNED'}),
            'recent_lives':_load('recent_lives.json',{'items':[]})}


class ChannelInput(BaseModel):
    channel_id: str = Field(pattern=r'^UC[A-Za-z0-9_-]{22}$')


@router.post('/viral-radar/channels')
def include_creator(body: ChannelInput):
    from backend.viral_radar20 import add_creator
    try:
        return {'included':add_creator(body.channel_id)}
    except (ValueError,IntegrationError) as exc:
        raise HTTPException(422,str(exc)) from None


@router.delete('/viral-radar/channels/{channel_id}')
def remove_creator(channel_id: str):
    from backend.viral_radar20 import exclude_creator
    try:
        return {'excluded':exclude_creator(channel_id)}
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


@router.get('/clipping-allowlist')
def get_allowlist():
    from backend.live_cuts import allowlist
    return allowlist()


class PermissionInput(BaseModel):
    channel_id: str = Field(pattern=r'^UC[A-Za-z0-9_-]{22}$')
    evidence: str = Field(min_length=15,max_length=2000)


@router.post('/clipping-allowlist')
def grant_permission(body: PermissionInput):
    from backend.live_cuts import allow_creator
    try:
        return allow_creator(body.channel_id,body.evidence)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from None


@router.delete('/clipping-allowlist/{channel_id}')
def revoke_permission(channel_id: str):
    from backend.live_cuts import remove_creator
    return remove_creator(channel_id)


class ManualLiveInput(BaseModel):
    url: str = Field(min_length=20,max_length=350)
    evidence: str = Field(default='',max_length=2000)


@router.post('/live-clips/from-url')
def queue_live_from_url(body: ManualLiveInput):
    from backend.live_cuts import submit_live_url
    try:
        return submit_live_url(body.url,body.evidence)
    except (ValueError,IntegrationError) as exc:
        raise HTTPException(422,str(exc)) from None


@router.get('/live-clips')
def list_live_clips():
    return {'items':db.rows('SELECT * FROM live_clips ORDER BY created DESC LIMIT 100')}


class ClipDecision(BaseModel):
    decision: str = Field(pattern=r'^(approve|discard)$')


@router.post('/live-clips/{id}/decision')
def live_clip_decision(id: str, body: ClipDecision):
    current=db.rows('SELECT * FROM live_clips WHERE id=:id',{'id':id})
    if not current:
        raise HTTPException(404,'Corte não encontrado.')
    clip=current[0]
    if clip['status']=='APPROVED' and body.decision=='approve':
        return {'status':'APPROVED'}
    if clip['status'] not in ('REVIEW_PENDING','APPROVED'):
        raise HTTPException(409,'Somente cortes validados podem receber decisão.')
    if body.decision=='approve':
        from backend.live_cuts import authorized_channel
        if not authorized_channel(clip['channel_id']):
            raise HTTPException(409,'Autorização para cortar a live foi revogada.')
        try:
            file=db.safe_file(clip['file_path'])
        except ValueError:
            raise HTTPException(409,'Render final ausente.') from None
        if not file.is_relative_to((db.ROOT/'videos/final/live_cuts').resolve()):
            raise HTTPException(409,'Arquivo fora da biblioteca validada.')
    status='APPROVED' if body.decision=='approve' else 'DISCARDED'
    db.execute("UPDATE live_clips SET status=:status,updated=:now WHERE id=:id",
               {'id':id,'status':status,'now':__import__('time').time()})
    db.log_event(None,'live_cuts','MANUAL_DECISION',
                 'Operador escolheu '+status+' para '+id)
    return {'status':status}


@router.get('/live-clips/{id}/file')
def fetch_live_clip_file(id: str):
    items=db.rows('SELECT file_path,status FROM live_clips WHERE id=:id',{'id':id})
    if not items or items[0]['status'] not in ('REVIEW_PENDING','APPROVED') or not items[0]['file_path']:
        raise HTTPException(404,'Corte não renderizado ou aguardando validação.')
    try:
        file=db.safe_file(items[0]['file_path'])
    except ValueError:
        raise HTTPException(404,'Arquivo do corte não encontrado.') from None
    if not file.is_relative_to((db.ROOT/'videos/final/live_cuts').resolve()):
        raise HTTPException(403,'Arquivo fora da pasta de cortes.')
    return FileResponse(file,media_type='video/mp4',filename='corte-live-'+id+'.mp4')


@router.get('/live-clips/{id}/metadata')
def fetch_live_clip_metadata(id: str):
    items=db.rows('SELECT file_path FROM live_clips WHERE id=:id',{'id':id})
    if not items or not items[0]['file_path']:
        raise HTTPException(404,'Corte ainda não finalizado.')
    try:
        video_file=db.safe_file(items[0]['file_path'])
    except ValueError:
        raise HTTPException(404,'Arquivo do corte não encontrado.') from None
    target=video_file.with_name('metadata.json')
    if not target.is_relative_to((db.ROOT/'videos/final/live_cuts').resolve()) or not target.is_file():
        raise HTTPException(404,'Metadados do corte não encontrados.')
    return json.loads(target.read_text('utf-8'))
