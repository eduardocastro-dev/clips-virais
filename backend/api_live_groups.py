"""Individual live outputs: group listing, explicit decisions, and legacy rerender."""
from __future__ import annotations
import json
import shutil
import time
from fastapi import APIRouter,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,Field
from backend import core as db

router=APIRouter(prefix='/api')


def grouped_lives():
    parents=db.rows('SELECT * FROM live_clips ORDER BY created DESC LIMIT 100')
    if not parents:return {'items':[]}
    children=db.rows("""SELECT * FROM live_clip_outputs
                         WHERE parent_id IN (SELECT id FROM live_clips)
                         ORDER BY parent_id,ordinal""")
    mapping={}
    for child in children:
        mapping.setdefault(child['parent_id'],[]).append(child)
    for parent in parents:
        parent['outputs']=mapping.get(parent['id'],[])
        parent['completed_cuts']=sum(bool(x['file_path']) and x['status'] in
             ('REVIEW_PENDING','APPROVED','DISCARDED') for x in parent['outputs'])
        parent['approved_cuts']=sum(x['status']=='APPROVED' for x in parent['outputs'])
        # Legacy finished lives keep their original count, new jobs always target >=3.
        parent['expected_cuts']=max(3,int(parent.get('cut_target') or 3))
        jobs=db.rows("""SELECT status,attempts,error FROM jobs WHERE kind=:kind
                         ORDER BY due DESC LIMIT 1""",{'kind':'live_cut:'+parent['id']})
        parent['job']=jobs[0] if jobs else None
    return {'items':parents}


def _output(parent_id:str,output_id:str):
    parent=db.rows('SELECT * FROM live_clips WHERE id=:id',{'id':parent_id})
    child=db.rows("""SELECT * FROM live_clip_outputs
         WHERE id=:output AND parent_id=:parent""",
         {'output':output_id,'parent':parent_id})
    if not parent or not child:
        raise HTTPException(404,'Live ou corte não encontrado.')
    return parent[0],child[0]


def _validated_path(raw:str,extension:str='.mp4'):
    if not raw:raise HTTPException(404,'Arquivo indisponível.')
    try:path=db.safe_file(raw)
    except ValueError:raise HTTPException(404,'Caminho inválido.') from None
    folder=(db.ROOT/'videos/final/live_cuts').resolve()
    if not path.is_relative_to(folder) or not path.is_file() or path.suffix.lower()!=extension:
        raise HTTPException(404,'Arquivo de corte indisponível.')
    return path


class OutputDecision(BaseModel):
    decision:str=Field(pattern=r'^(approve|discard)$')


@router.post('/live-clips/{parent_id}/outputs/{output_id}/decision')
def decide_output(parent_id:str,output_id:str,body:OutputDecision):
    from backend.live_cuts import authorized_channel,record_right
    parent,child=_output(parent_id,output_id)
    if child['status']=='APPROVED' and body.decision=='approve':
        return {'status':'APPROVED'}
    if child['status']!='REVIEW_PENDING':
        raise HTTPException(409,'Somente cortes aguardando revisão podem receber decisão.')
    if body.decision=='approve':
        if not authorized_channel(parent['channel_id']):
            raise HTTPException(409,'Autorização do criador revogada.')
        _validated_path(child['file_path'])
    status='APPROVED' if body.decision=='approve' else 'DISCARDED'
    now=time.time()
    db.execute("""UPDATE live_clip_outputs SET status=:status,updated=:now
                  WHERE id=:id""",{'id':output_id,'status':status,'now':now})
    children=db.rows('SELECT status FROM live_clip_outputs WHERE parent_id=:id',{'id':parent_id})
    if children and all(x['status'] in ('APPROVED','DISCARDED') for x in children):
        new_state='APPROVED' if any(x['status']=='APPROVED' for x in children) else 'DISCARDED'
        db.execute("""UPDATE live_clips SET status=:state,updated=:now WHERE id=:id""",
                   {'state':new_state,'now':now,'id':parent_id})
    record_right(parent['video_id'],parent['channel_id'],status,
                 'Revisão manual do corte '+str(child['ordinal'])+' / '+output_id)
    db.log_event(None,'live_cuts','CUT_DECISION',
                 f'{parent["title"]}: corte {child["ordinal"]} {status}')
    return {'status':status,'parent_id':parent_id,'output_id':output_id}


@router.get('/live-clips/{parent_id}/outputs/{output_id}/file')
def get_output_file(parent_id:str,output_id:str):
    _,child=_output(parent_id,output_id)
    if child['status'] not in ('REVIEW_PENDING','APPROVED','DISCARDED'):
        raise HTTPException(404,'Corte ainda não validado.')
    path=_validated_path(child['file_path'])
    return FileResponse(path,media_type='video/mp4',
                        filename=f'corte-{output_id}.mp4')


@router.get('/live-clips/{parent_id}/outputs/{output_id}/metadata')
def get_output_metadata(parent_id:str,output_id:str):
    _,child=_output(parent_id,output_id)
    if child['metadata_path']:
        path=_validated_path(child['metadata_path'],'.json')
        return json.loads(path.read_text('utf-8'))
    # Older single-cut productions stored metadata as metadata.json.
    if child['file_path']:
        output=_validated_path(child['file_path'])
        old=output.with_name('metadata.json')
        if old.is_file():return json.loads(old.read_text('utf-8'))
    raise HTTPException(404,'SEO deste corte não encontrado.')


class Rerender(BaseModel):
    webcam_anchor:str=Field(default='bottom_left',
        pattern=r'^(bottom_left|top_left|bottom_right|top_right)$')


@router.post('/live-clips/{parent_id}/reprocess')
def rerender_live(parent_id:str,body:Rerender):
    from backend.live_cuts import authorized_channel
    from backend.daily_quota import config,within_deadline
    parents=db.rows('SELECT * FROM live_clips WHERE id=:id',{'id':parent_id})
    if not parents:raise HTTPException(404,'Live não encontrada.')
    live=parents[0]
    if not authorized_channel(live['channel_id']):
        raise HTTPException(409,'Permissão do canal revogada.')
    if not within_deadline(config()):
        raise HTTPException(409,'Horário limite atingido. Tente no próximo dia.')
    if live['status'] in ('QUEUED','PROCESSING','RETRY'):
        raise HTTPException(409,'A produção ainda está em execução.')
    outputs=db.rows("SELECT status FROM live_clip_outputs WHERE parent_id=:id",{'id':parent_id})
    if any(x['status']=='APPROVED' for x in outputs):
        raise HTTPException(409,'Um corte já foi aprovado; não substitua um arquivo publicado.')
    # Reprocessing can overwrite cut-01.mp4 etc. Archive unapproved versions
    # first: never silently destroy a completed, previously reviewed render.
    old_records=db.rows("""SELECT file_path,metadata_path,cover_path
                           FROM live_clip_outputs WHERE parent_id=:id""",
                        {'id':parent_id})
    archive=db.ROOT/'videos'/'final'/'live_cuts'/parent_id/'history'/db.uid()
    for item in old_records:
        for key in ('file_path','metadata_path','cover_path'):
            if not item.get(key):continue
            try:source=db.safe_file(item[key])
            except ValueError:continue
            if source.is_file():
                archive.mkdir(parents=True,exist_ok=True)
                shutil.copy2(source,archive/source.name)
    db.execute('DELETE FROM live_clip_outputs WHERE parent_id=:id',{'id':parent_id})
    db.execute("""UPDATE live_clips SET status='QUEUED',stage=NULL,
         webcam_anchor=:anchor,cut_target=3,file_path=NULL,score=NULL,
         segment_start=NULL,segment_end=NULL,attempts=0,error=NULL,
         updated=:now WHERE id=:id""",
         {'id':parent_id,'anchor':body.webcam_anchor,'now':time.time()})
    db.enqueue('live_cut:'+parent_id,
               unique_key='livecut:reprocess:'+db.uid())
    db.log_event(None,'live_cuts','REPROCESS_QUEUED',
                 'Nova produção 3 cortes '+parent_id+' com webcam '+body.webcam_anchor)
    return {'queued':True,'parent_id':parent_id,'expected_cuts':3}
