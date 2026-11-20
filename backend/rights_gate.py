"""Operator rights confirmation for fully rendered, PRIVATE video previews.

Neither downloading nor AI evaluation grants publication rights. Every TV slot
is checked against its persisted authorization; an operator must supply
evidence covering all displayed third-party sources before approval.
"""
from __future__ import annotations
import json
import time
from backend import core as db
from backend.integrations import IntegrationError
from backend.source_preview import record_rights


def _manifest(video_id: str) -> list[dict]:
    file=db.ROOT/'handoff'/video_id/'visual-assets.json'
    try:
        value=json.loads(file.read_text('utf-8'))
        return value if isinstance(value,list) else []
    except (OSError,ValueError):
        return []


def _write_manifest(video_id: str, scenes:list[dict]):
    db.atomic(db.ROOT/'handoff'/video_id/'visual-assets.json',
              json.dumps(scenes,ensure_ascii=False,indent=2))


def pending_sources(video_id: str) -> list[dict]:
    """Return every non-authorized TV source, unique by ID or URL."""
    unresolved={}
    for scene in _manifest(video_id):
        for segment in scene.get('segments',[]):
            slot=segment.get('tv_slot') or {}
            if not slot:
                continue
            source=slot.get('tv_source_url') or segment.get('tv_source_url') or ''
            aid=segment.get('tv_source_asset_id') or slot.get('asset_id')
            status=slot.get('rights_status')
            if aid:
                rows=db.rows('SELECT rights_status FROM assets WHERE id=:id',{'id':aid})
                if rows:status=rows[0]['rights_status']
            if status not in ('AUTHORIZED','OWNED_GENERATED'):
                key=aid or source or slot.get('tv_source','')
                unresolved[str(key)]={'source_url':source,'asset_id':aid,
                                      'rights_status':status or 'REVIEW_REQUIRED',
                                      'scene':scene.get('scene')}
    return list(unresolved.values())


def requires_review(video:dict) -> bool:
    return bool(pending_sources(video['id']) or video.get('rights') in ('BLOCKED','REVIEW_REQUIRED'))


def require_clearance(video:dict):
    if video.get('rights') in ('BLOCKED','REVIEW_REQUIRED'):
        raise IntegrationError('Direitos da produção bloqueados ou pendentes.')
    # An on-screen credit explicitly required by a source license cannot
    # be replaced with description-only attribution.
    for scene in _manifest(video['id']):
        for segment in scene.get('segments',[]):
            slot=segment.get('tv_slot') or {}
            if slot.get('requires_onscreen_credit') and not slot.get('onscreen_credit_drawn'):
                raise IntegrationError(
                    'A licença desta fonte exige crédito na tela. '
                    'Revise e re-renderize com a indicação visível.')
    pending=pending_sources(video['id'])
    if pending:
        raise IntegrationError('A TV contém material aguardando licença; confirme os direitos em Video Studio antes da publicação.')


def confirm(video_id:str,evidence:str):
    rows=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})
    if not rows:raise ValueError('Produção não encontrada.')
    video=rows[0]
    if video.get('manual_decision')=='discard':
        raise ValueError('Produção descartada não pode receber liberação.')
    if video.get('approved'):
        raise ValueError('Produção já aprovada.')
    if not video.get('final_path') or not (db.ROOT/video['final_path']).is_file():
        raise ValueError('O MP4 precisa estar pronto antes da confirmação de direitos.')
    evidence=(evidence or '').strip()
    if len(evidence)<15:
        raise ValueError('Informe a autorização/licença válida para TODOS os materiais da TV.')
    pending=pending_sources(video_id)
    if not pending and video['rights'] not in ('REVIEW_REQUIRED','REFERENCE_ONLY'):
        raise ValueError('Nenhum material pendente de autorização.')
    if video['rights']=='BLOCKED':
        raise ValueError('Material bloqueado não pode ser liberado por esse formulário.')
    # Check the entire list before updating anything. Blocked or revoked
    # assets cannot be made publishable through a generic preview approval.
    for item in pending:
        aid=item.get('asset_id')
        if aid:
            rows=db.rows('SELECT rights_status FROM assets WHERE id=:id',{'id':aid})
            if rows and rows[0]['rights_status'] not in ('REVIEW_REQUIRED','AUTHORIZED'):
                raise ValueError('Asset bloqueado ou revogado: '+str(aid))
    # Operator attests that evidence covers every named TV source.
    for item in pending:
        aid=item.get('asset_id')
        if aid:
            db.execute("""UPDATE assets SET rights_status='AUTHORIZED',evidence=:evidence,
                updated=:now WHERE id=:id AND rights_status='REVIEW_REQUIRED'""",
                {'evidence':evidence,'now':time.time(),'id':aid})
        record_rights(video_id,item.get('source_url') or '',aid,'AUTHORIZED',
                      'Licença/autorização declarada pelo operador: '+evidence[:240])
    if video['rights'] in ('REVIEW_REQUIRED','REFERENCE_ONLY'):
        db.execute("UPDATE videos SET rights='AUTHORIZED',evidence=:evidence,updated=:now WHERE id=:id",
                   {'evidence':evidence,'now':time.time(),'id':video_id})
    scenes=_manifest(video_id)
    for scene in scenes:
        for segment in scene.get('segments',[]):
            slot=segment.get('tv_slot')
            if slot and slot.get('rights_status') not in ('AUTHORIZED','OWNED_GENERATED'):
                slot['rights_status']='AUTHORIZED'
                slot['rights_evidence']='Confirmado pelo operador após a prévia: '+evidence[:200]
                slot['preview_only']=False
                segment['tv_slot']=slot
    if scenes:
        _write_manifest(video_id,scenes)
        # Keep attempt-specific visual inspection in sync with the current
        # license decision. rights_log.json preserves the original pending event.
        handoffs=db.ROOT/'handoff'/video_id
        for file in handoffs.glob('visual-assets-attempt-*.json'):
            try:
                previous=json.loads(file.read_text('utf-8'))
            except (OSError,ValueError):
                continue
            if not isinstance(previous,list):
                continue
            for scene in previous:
                for segment in scene.get('segments',[]):
                    slot=segment.get('tv_slot')
                    if slot and slot.get('rights_status') not in ('AUTHORIZED','OWNED_GENERATED'):
                        slot['rights_status']='AUTHORIZED'
                        slot['rights_evidence']='Declaração de licença do operador'
                        slot['preview_only']=False
            db.atomic(file,json.dumps(previous,ensure_ascii=False,indent=2))
    db.execute("""UPDATE videos SET status='AWAITING_MANUAL_DECISION',
                  error=NULL,updated=:now WHERE id=:id AND
                  status='PENDING_RIGHTS_REVIEW'""",
               {'id':video_id,'now':time.time()})
    db.log_event(video_id,'rights','OPERATOR_CONFIRMED',
                 'Direitos declarados para os materiais de TV; revisão humana ainda necessária.')
    return {'status':'RIGHTS_CONFIRMED','pending':pending_sources(video_id),
            'review_required':True}
