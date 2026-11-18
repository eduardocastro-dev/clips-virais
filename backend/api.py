import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any
from fastapi import FastAPI, Depends, Header, HTTPException, File, Form, UploadFile, Request, Body
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from backend import core as db
from backend.contracts import Settings, ImportRequest, ProfileRequest, Script, platform_url
from backend.pipeline import create_video, AGENTS, approve_rendered, PipelineInterrupted
from backend.integrations import IntegrationError
from backend.sources import public_url, seed_default_sources


@asynccontextmanager
async def lifespan(app):
    db.init_db()
    yield


app = FastAPI(title='GTA Autonomous Content Studio', lifespan=lifespan)


def auth(authorization: Annotated[str | None, Header()] = None):
    expected = os.getenv('STUDIO_TOKEN', '')
    if not expected or not authorization or not secrets.compare_digest(authorization, 'Bearer ' + expected):
        raise HTTPException(401, 'Informe o token local configurado em STUDIO_TOKEN.')


protected = [Depends(auth)]


@app.get('/health')
def health():
    db.rows('SELECT 1')
    return {'status': 'ok'}


@app.get('/api/state', dependencies=protected)
def state():
    from backend.assets import sync_library
    sync_library()
    videos = db.rows('SELECT * FROM videos ORDER BY created DESC LIMIT 100')
    return {'settings': db.settings().model_dump(), 'videos': videos,
        'publications': db.rows('SELECT p.*,v.title,v.test,v.template FROM publications p JOIN videos v ON p.video_id=v.id ORDER BY p.updated DESC LIMIT 200'),
        'profiles': db.rows('SELECT * FROM profiles ORDER BY priority DESC'),
        'sources': db.rows('SELECT * FROM sources ORDER BY name'),
        'opportunities': db.rows("""SELECT * FROM opportunities ORDER BY
            CASE WHEN platform='youtube' AND url LIKE 'https://www.youtube.com/shorts/%' THEN 0
                 WHEN platform='youtube' THEN 1 WHEN platform='news' THEN 2 ELSE 3 END,
            COALESCE(score, -1) DESC, created DESC LIMIT 150"""),
        'notifications': db.rows('SELECT * FROM notifications ORDER BY created DESC LIMIT 50'),
        'events': db.rows('SELECT * FROM events ORDER BY created DESC LIMIT 100'),
        'jobs': db.rows('SELECT * FROM jobs ORDER BY due DESC LIMIT 100'),
        'metrics': db.rows('SELECT m.*,p.platform,v.template FROM metrics m JOIN publications p ON p.id=m.publication_id JOIN videos v ON v.id=p.video_id ORDER BY observed DESC LIMIT 500'),
        'usage': db.rows('SELECT * FROM usage ORDER BY day DESC LIMIT 30'),
        'assets': db.rows('SELECT * FROM assets ORDER BY created DESC LIMIT 1000'),
        'persona': __import__('backend.personas',fromlist=['get_persona']).get_persona(),
        'cast': __import__('backend.personas',fromlist=['get_cast']).get_cast(),
        'recommendations':db.get_setting('recommendations',{}),
        'worker_online': time.time() - db.get_setting('worker_heartbeat', 0) < 120,
        'agents': AGENTS, 'templates': template_list(), 'daily_production_usage': db.production_usage(),
        'secrets': [x['key'].removeprefix('secret:') for x in db.rows("SELECT key FROM kv WHERE key LIKE 'secret:%'")]}


@app.post('/api/assets/rescan', dependencies=protected)
def rescan_assets():
    from backend.assets import sync_library
    return sync_library()


@app.get('/api/settings', dependencies=protected)
def get_settings():
    return db.settings()


@app.put('/api/settings', dependencies=protected)
def save_settings(settings: Settings):
    settings.configured = True
    settings.postiz_auto = False
    settings.youtube_auto = False
    settings.postiz_url = ''
    settings.postiz_channels = {}
    settings.approval_mode = 'manual'
    db.put_setting('settings', settings.model_dump())
    return settings


class SecretInput(BaseModel):
    name: str
    value: str = Field(max_length=10000)


@app.put('/api/secrets', dependencies=protected)
def save_secret(item: SecretInput):
    allowed = {'llm_api_key','youtube_api_key','youtube_access_token','youtube_refresh_token','youtube_client_id','youtube_client_secret',
               'telegram_token','telegram_chat_id','smtp_host','smtp_port','smtp_to','smtp_from','smtp_user','smtp_password','postiz_api_key',
               'tiktok_access_token','instagram_access_token','instagram_user_id'}
    if item.name not in allowed:
        raise HTTPException(422, 'Credencial não reconhecida.')
    db.set_secret(item.name, item.value)
    return {'saved': item.name}


@app.post('/api/import', dependencies=protected)
def import_url(item: ImportRequest):
    try:
        identifier=create_video(item)
        if item.source_kind=='short':
            from backend.assets import register_short
            register_short({'url':item.url,'title':'Short importado por URL','source_profile':'Canal não identificado',
                            'source_type':'short','rights':'REFERENCE_ONLY'})
        return {'id': identifier}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


class VariantInput(BaseModel):
    instructions: str = Field(min_length=40,max_length=3000)
    duration: int = Field(default=30,ge=10,le=90)
    template: str = 'gta-news'


def variant_request(video, instructions, duration, template):
    if video['test'] or video['platform']=='news':
        raise HTTPException(409,'Variações manuais estão disponíveis para fontes sociais reais.')
    return ImportRequest(url=video['url'].split('#studio-variant=')[0],rights=video['rights'],evidence=video['evidence'],
        credits=video['credits'],instructions=instructions,duration=duration,template=template)


@app.post('/api/videos/{id}/variant',dependencies=protected)
def create_variant(id: str, item: VariantInput):
    import hashlib
    found=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})
    if not found:raise HTTPException(404,'Vídeo não encontrado.')
    req=variant_request(found[0],item.instructions,item.duration,item.template)
    key=hashlib.sha256((id+item.model_dump_json()).encode()).hexdigest()[:20]
    try:return {'id':create_video(req,variant_key=key)}
    except ValueError as exc:raise HTTPException(409,str(exc)) from None


@app.post('/api/videos/{id}/briefing',dependencies=protected)
def create_edited_briefing(id: str, script: Script):
    import hashlib
    found=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})
    if not found:raise HTTPException(404,'Vídeo não encontrado.')
    req=variant_request(found[0],'Execute o briefing revisado manualmente, preservando os fatos e as permissões registradas.',script.duration,script.template)
    key=hashlib.sha256((id+script.model_dump_json()).encode()).hexdigest()[:20]
    try:new_id=create_video(req,variant_key=key,manual_script=script)
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    return {'id':new_id}


@app.post('/api/videos/{id}/resume', dependencies=protected)
def resume_missing_assets(id: str):
    from backend.assets import mandatory_assets, sync_library
    from backend.personas import get_persona
    match=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})
    if not match:raise HTTPException(404,'Produção não encontrada.')
    if match[0]['status'] not in ('PAUSED_MISSING_ASSETS','PAUSED_VALIDATION','PIPELINE_ERROR'):
        raise HTTPException(409,'A produção não está pausada por falta de assets.')
    sync_library()
    script_path=db.ROOT/'handoff'/id/'script.json'
    script=Script.model_validate_json(script_path.read_text('utf-8')) if script_path.is_file() else None
    missing=mandatory_assets(get_persona(),script=script)
    if missing:raise HTTPException(409,'Faltam assets: '+', '.join(missing))
    db.execute("UPDATE videos SET status='QUEUED',error=NULL,updated=:now WHERE id=:id",
               {'id':id,'now':time.time()})
    db.enqueue('pipeline',video_id=id,unique_key='pipeline:resume:'+db.uid())
    return {'status':'QUEUED','message':'Produção retomada preservando o histórico de tentativas.'}


@app.post('/api/test-video', dependencies=protected)
def test_video():
    try:
        return {'id': create_video(test=True)}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from None


@app.post('/api/profiles', dependencies=protected)
def add_profile(item: ProfileRequest):
    db.execute('''INSERT INTO profiles VALUES (:id,:url,:platform,:enabled,:interval,:priority,NULL,NULL)
        ON CONFLICT(url) DO UPDATE SET enabled=excluded.enabled, interval_minutes=excluded.interval_minutes, priority=excluded.priority''',
        dict(id=db.uid(), url=item.url, platform=platform_url(item.url, True)[0], enabled=int(item.enabled), interval=item.interval_minutes, priority=item.priority))
    return {'saved': True}


@app.delete('/api/profiles/{id}', dependencies=protected)
def delete_profile(id: str):
    db.execute('DELETE FROM profiles WHERE id=:id', {'id': id})
    return {'deleted': True}


@app.post('/api/profiles/{id}/scan', dependencies=protected)
def scan_profile(id: str):
    if not db.rows('SELECT id FROM profiles WHERE id=:id', {'id': id}):
        raise HTTPException(404, 'Perfil não encontrado.')
    db.enqueue('profile:' + id)
    return {'queued': True}


@app.post('/api/discover', dependencies=protected)
def discover_now():
    seed_default_sources()
    db.enqueue('discover')
    sources=db.rows('SELECT id FROM sources WHERE enabled=1')
    for source in sources:
        db.enqueue('source:'+source['id'])
    return {'queued':True,'sources':len(sources),'mode':'all_sources_youtube_first'}


class SourceInput(BaseModel):
    name: str = Field(min_length=1,max_length=100)
    url: str
    interval_minutes: int = Field(default=120,ge=15,le=10080)
    enabled: bool = True


@app.post('/api/sources',dependencies=protected)
def add_source(item: SourceInput):
    try:public_url(item.url)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    db.execute('''INSERT INTO sources VALUES (:id,:url,:name,:enabled,:interval,NULL,NULL)
        ON CONFLICT(url) DO UPDATE SET name=excluded.name,enabled=excluded.enabled,interval_minutes=excluded.interval_minutes''',
        dict(id=db.uid(),url=item.url,name=item.name,enabled=int(item.enabled),interval=item.interval_minutes))
    return {'saved':True}


@app.post('/api/sources/{id}/scan',dependencies=protected)
def scan_source(id: str):
    if not db.rows('SELECT id FROM sources WHERE id=:id',{'id':id}):raise HTTPException(404,'Fonte não encontrada.')
    db.enqueue('source:'+id)
    return {'queued':True}


@app.post('/api/opportunities/{id}/produce',dependencies=protected)
def produce_opportunity(id: str):
    rows=db.rows('SELECT * FROM opportunities WHERE id=:id',{'id':id})
    if not rows:raise HTTPException(404,'Oportunidade não encontrada.')
    source=rows[0]
    try:
        video=(create_video(reference=json.loads(source['metadata'])) if source['platform']=='news' else
               create_video(ImportRequest(url=source['url'],duration=db.settings().duration)))
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    return {'id':video}


@app.get('/api/postiz/channels', dependencies=protected)
def postiz_channels():
    try:
        raise HTTPException(410,'Postiz foi removido. Publicação é manual.')
    except IntegrationError as exc:
        raise HTTPException(409,str(exc)) from None


class ScheduleInput(BaseModel):
    timestamp: float = Field(gt=0)


@app.post('/api/publications/{id}/schedule', dependencies=protected)
def schedule_publication(id: str, item: ScheduleInput):
    if item.timestamp < time.time() or item.timestamp > time.time()+365*86400:
        raise HTTPException(422,'Escolha um horário futuro em até um ano.')
    if not db.execute("UPDATE publications SET scheduled_for=:date WHERE id=:id AND status IN ('PENDENTE','AGUARDANDO_PUBLICACAO_MANUAL')",dict(id=id,date=item.timestamp)):
        raise HTTPException(409,'Publicação já enviada ou não encontrada. Altere agendamentos externos no Postiz.')
    return {'scheduled_for':item.timestamp,'mode':'editorial_plan'}


class HumanReview(BaseModel):
    reviewed: bool


@app.post('/api/publications/{id}/send', dependencies=protected)
def send_reviewed(id: str, item: HumanReview):
    raise HTTPException(410, 'Envio automático desativado. Baixe o MP4 no Video Studio e publique manualmente.')


class Confirm(BaseModel):
    url: str


@app.post('/api/publications/{id}/confirm', dependencies=protected)
def confirm(id: str, item: Confirm):
    pubs = db.rows('SELECT * FROM publications WHERE id=:id', {'id': id})
    if not pubs:
        raise HTTPException(404, 'Publicação não encontrada.')
    pub = pubs[0]
    try:
        platform, url = platform_url(item.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    if platform != pub['platform']:
        raise HTTPException(422, 'URL não corresponde à plataforma.')
    if db.rows('SELECT test FROM videos WHERE id=:id', {'id': pub['video_id']})[0]['test']:
        raise HTTPException(409, 'Vídeo de homologação não pode ser marcado como publicação real.')
    if pub['status'] == 'PUBLICADO':
        if pub['url'] != url:
            raise HTTPException(409, 'Publicação já confirmada com outra URL.')
        return {'status': 'PUBLICADO'}
    external = url.split('v=')[-1] if platform == 'youtube' else url.rstrip('/').split('/')[-1]
    db.execute("UPDATE publications SET status='PUBLICADO',url=:url,external_id=:external,updated=:now WHERE id=:id",
               dict(id=id, url=url, external=external, now=time.time()))
    db.notify('published:' + id, 'Publicação confirmada manualmente: ' + url)
    return {'status': 'PUBLICADO'}


@app.post('/api/jobs/{id}/{action}', dependencies=protected)
def job_action(id: str, action: str):
    if action not in ('pause', 'retry'):
        raise HTTPException(422, 'Ação desconhecida.')
    job = db.rows('SELECT * FROM jobs WHERE id=:id', {'id': id})
    if not job:
        raise HTTPException(404, 'Job não encontrado.')
    if job[0]['status'] == 'RUNNING':
        raise HTTPException(409, 'Job em execução; parada de emergência impede a próxima etapa.')
    db.execute('UPDATE jobs SET status=:status,attempts=0,due=:now,error=NULL WHERE id=:id', dict(id=id, status='PAUSED' if action == 'pause' else 'QUEUED', now=time.time()))
    return {'updated': True}




@app.get('/api/videos/{id}/attempts', dependencies=protected)
def video_attempts(id: str):
    found=db.rows('SELECT id,render_error,final_path,revision FROM videos WHERE id=:id',{'id':id})
    if not found:
        raise HTTPException(404,'Produção não encontrada.')
    items=db.rows('SELECT * FROM video_attempts WHERE video_id=:id ORDER BY attempt',{'id':id})
    for entry in items:
        entry['details']=json.loads(entry['details'])
        entry['render_available']=bool(entry['render_path'] and (db.ROOT/entry['render_path']).is_file())
    # Legacy versions only stored final_path after approval. Return it when present.
    if not items and found[0]['final_path']:
        items=[{'attempt':1,'verdict':'LEGADO','score':None,'details':{},
                'render_path':found[0]['final_path'],'render_error':found[0]['render_error'],
                'render_available':(db.ROOT/found[0]['final_path']).is_file()}]
    return {'video_id':id,'attempts':items,'render_error':found[0]['render_error']}


class ManualDecision(BaseModel):
    action: str = Field(pattern='^(approve|discard)$')


@app.post('/api/videos/{id}/decision', dependencies=protected)
def manual_decision(id: str, item: ManualDecision):
    found=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})
    if not found:
        raise HTTPException(404,'Produção não encontrada.')
    video=found[0]
    now=time.time()
    if video['manual_decision']=='discard':
        if item.action=='discard':return {'status':'DISCARDED'}
        raise HTTPException(409,'Produção já descartada; é necessário criar uma nova produção.')
    if video['manual_decision']=='approved' or video['approved']:
        if item.action=='approve':return {'status':'APPROVED'}
        raise HTTPException(409,'Produção já aprovada; não é possível descartar um item já entregue à fila de publicação.')
    if item.action=='discard':
        db.execute("UPDATE videos SET manual_decision='discard',manual_by='local_operator',manual_at=:now,"
                   "status='DISCARDED',approved=0,updated=:now WHERE id=:id",
                   {'id':id,'now':now})
        db.execute("UPDATE jobs SET status='PAUSED',lease=NULL WHERE video_id=:id AND status='QUEUED'",{'id':id})
        db.execute("UPDATE publications SET status='DISCARDED',updated=:now WHERE video_id=:id AND status!='PUBLICADO'",{'id':id,'now':now})
        db.log_event(id,'diretor','MANUAL_DISCARDED','Descartado pelo operador local.')
        from backend.production_media import remove_workspace
        remove_workspace(id)
        return {'status':'DISCARDED','manual_by':'local_operator','manual_at':now}
    if video['rights'] in ('BLOCKED','REVIEW_REQUIRED') or (video['rights']=='AUTHORIZED' and not video['evidence']):
        raise HTTPException(409,'Direitos de utilização não comprovados. A decisão manual não autoriza uso indevido de mídia.')
    if video['final_path'] and (db.ROOT/video['final_path']).is_file():
        try:
            approve_rendered(id,manual=True)
        except (IntegrationError,PipelineInterrupted) as exc:
            raise HTTPException(409,str(exc)) from None
        return {'status':'APPROVED','manual_by':'local_operator','manual_at':now,'manual_approval':True}
    if video['status'] in ('FAILED','AWAITING_MANUAL_DECISION','REJECTED'):
        raise HTTPException(409,'Não há render disponível para aprovar. Consulte o erro do Editor e execute uma nova produção.')
    db.execute("UPDATE videos SET manual_decision='approve_pending',manual_by='local_operator',manual_at=:now WHERE id=:id",
               {'now':now,'id':id})
    db.log_event(id,'diretor','MANUAL_PENDING','Aprovação será aplicada quando o primeiro render ficar pronto.')
    return {'status':'APPROVAL_PENDING','manual_by':'local_operator','manual_at':now}

@app.get('/api/files/{video_id}', dependencies=protected)
def video_file(video_id: str, attempt: int | None = None):
    video = db.rows('SELECT final_path,render_error FROM videos WHERE id=:id', {'id': video_id})
    if not video:
        raise HTTPException(404, 'Produção não encontrada.')
    path=video[0]['final_path']
    if attempt is not None:
        matches=db.rows('SELECT render_path,render_error FROM video_attempts WHERE video_id=:id AND attempt=:attempt',
                        {'id':video_id,'attempt':attempt})
        if not matches:
            raise HTTPException(404,'Tentativa não encontrada.')
        path=matches[0]['render_path']
        if not path:
            raise HTTPException(409, matches[0]['render_error'] or 'Tentativa sem render: falha técnica.')
    if not path:
        raise HTTPException(409,video[0]['render_error'] or 'Render ainda em processamento.')
    try:
        file = db.safe_file(path)
    except ValueError:
        raise HTTPException(404, 'Vídeo removido pela política de retenção.') from None
    return FileResponse(file, media_type='video/mp4', filename=video_id + (f'-attempt-{attempt}' if attempt else '') + '.mp4')


@app.get('/api/exports/{video_id}/{platform}', dependencies=protected)
def export_metadata(video_id: str, platform: str):
    if platform not in ('youtube', 'tiktok', 'instagram'):
        raise HTTPException(404, 'Plataforma desconhecida.')
    rows = db.rows('SELECT output_path FROM publications WHERE video_id=:video AND platform=:platform',
                   {'video': video_id, 'platform': platform})
    if not rows or not rows[0]['output_path']:
        raise HTTPException(404, 'Metadados ainda não disponíveis.')
    from pathlib import Path
    rel = Path(rows[0]['output_path']).parent / f'metadata_{video_id}.json'
    try:
        file = db.safe_file(str(rel))
    except ValueError:
        raise HTTPException(404, 'Metadados não encontrados.') from None
    return FileResponse(file, media_type='application/json', filename=f'{platform}_{video_id}.json')


@app.get('/api/handoffs/{video_id}', dependencies=protected)
def handoffs(video_id: str):
    if not db.rows('SELECT id FROM videos WHERE id=:id', {'id': video_id}):
        raise HTTPException(404, 'Vídeo não encontrado.')
    return {p.name: json.loads(p.read_text('utf-8')) for p in (db.ROOT / 'handoff' / video_id).glob('*.json')}


@app.get('/api/report', dependencies=protected, response_class=PlainTextResponse)
def report():
    path = db.ROOT / 'reports' / f'{db.today()}.md'
    return path.read_text('utf-8') if path.exists() else 'Nenhum relatório gerado hoje.'


def template_list():
    base = json.loads((Path(__file__).resolve().parent.parent / 'templates/catalog.json').read_text('utf-8'))
    overrides = db.get_setting('templates', {})
    return {key: {**value, **overrides.get(key, {})} for key, value in base.items()}



@app.get('/api/videos/{id}/visuals', dependencies=protected)
def video_visuals(id: str, attempt: int | None = None):
    if not db.rows('SELECT id FROM videos WHERE id=:id',{'id':id}):
        raise HTTPException(404,'Produção não encontrada.')
    if attempt is not None and not 1<=attempt<=100:raise HTTPException(422,'Tentativa inválida.')
    filename=f'visual-assets-attempt-{attempt}.json' if attempt else 'visual-assets.json'
    manifest=db.ROOT/'handoff'/id/filename
    return {'scenes':json.loads(manifest.read_text('utf-8')) if manifest.is_file() else []}


@app.get('/api/assets/{id}/preview', dependencies=protected)
def asset_preview(id:str):
    from backend import media
    from backend.assets import safe_asset
    items=db.rows('SELECT path,media_type FROM assets WHERE id=:id',{'id':id})
    if not items or not items[0]['path']:raise HTTPException(404,'Arquivo não disponível.')
    try:source=safe_asset(items[0]['path'])
    except ValueError:raise HTTPException(404,'Arquivo não encontrado.') from None
    if items[0]['media_type']!='video' and source.suffix.lower() not in ('.mp4','.webm','.mkv','.mov'):
        raise HTTPException(422,'Prévia compacta disponível somente para vídeos.')
    folder=db.ROOT/'cache'/'previews';folder.mkdir(parents=True,exist_ok=True)
    output=folder/(id+'.mp4')
    if not output.is_file() or output.stat().st_mtime_ns<source.stat().st_mtime_ns:
        tmp=folder/(id+'.tmp.mp4')
        try:
            media.run([media.binary('ffmpeg'),'-y','-hide_banner','-loglevel','error',
              '-i',str(source),'-t','3','-an','-vf','scale=270:-2','-c:v','libx264',
              '-preset','ultrafast','-crf','30','-movflags','+faststart',str(tmp)],timeout=45)
            tmp.replace(output)
        except Exception as exc:
            tmp.unlink(missing_ok=True)
            raise HTTPException(422,'Prévia de vídeo indisponível: '+str(exc)[:230]) from None
    return FileResponse(output,media_type='video/mp4')


@app.get('/api/assets/{id}/thumbnail', dependencies=protected)
def asset_thumbnail(id:str):
    from backend import media
    from backend.assets import safe_asset
    from PIL import Image
    items=db.rows('SELECT path,media_type FROM assets WHERE id=:id',{'id':id})
    if not items or not items[0]['path']:raise HTTPException(404,'Asset não disponível.')
    try:source=safe_asset(items[0]['path'])
    except ValueError:raise HTTPException(404,'Arquivo não encontrado.') from None
    folder=db.ROOT/'cache'/'thumbnails';folder.mkdir(parents=True,exist_ok=True)
    output=folder/(id+'.jpg')
    if not output.is_file() or output.stat().st_mtime_ns<source.stat().st_mtime_ns:
        temporary=folder/(id+'.tmp.jpg')
        kind=items[0]['media_type'] or ''
        try:
            if kind=='image' or source.suffix.lower() in ('.jpg','.jpeg','.png','.webp','.gif'):
                with Image.open(source) as im:
                    im.convert('RGB').resize((240,240)).save(temporary,quality=77)
            elif kind=='audio' or source.suffix.lower() in ('.mp3','.wav','.m4a'):
                media.run([media.binary('ffmpeg'),'-y','-i',str(source),'-filter_complex',
                   'showwavespic=s=240x120:colors=0x38cdd1','-frames:v','1',str(temporary)],timeout=25)
            else:
                media.run([media.binary('ffmpeg'),'-y','-ss','1','-i',str(source),
                  '-frames:v','1','-vf','scale=240:-2','-q:v','6',str(temporary)],timeout=40)
            temporary.replace(output)
        except Exception as exc:
            temporary.unlink(missing_ok=True)
            raise HTTPException(422,'Não foi possível gerar miniatura: '+str(exc)[:220]) from None
    return FileResponse(output,media_type='image/jpeg')


class AssetsBulk(BaseModel):
    ids: list[str] = Field(min_length=1,max_length=100)
    operation: str
    category: str | None = None
    confirm_delete: bool = False

@app.post('/api/assets/bulk', dependencies=protected)
def assets_bulk(item:AssetsBulk):
    from backend.assets import update_metadata,delete
    if item.operation not in ('activate','deactivate','recategorize','delete'):
        raise HTTPException(422,'Operação inválida.')
    if item.operation=='delete' and not item.confirm_delete:
        raise HTTPException(409,'Confirmação explícita necessária para excluir assets.')
    result={'updated':[],'errors':{}}
    for id in dict.fromkeys(item.ids):
        try:
            if item.operation=='delete':delete(id,confirm_children=True)
            elif item.operation=='activate':update_metadata(id,active=True)
            elif item.operation=='deactivate':update_metadata(id,active=False)
            else:update_metadata(id,category=item.category)
            result['updated'].append(id)
        except (ValueError,OSError) as exc:result['errors'][id]=str(exc)
    return result


@app.get('/api/assets', dependencies=protected)
def list_assets():
    from backend.assets import sync_library
    sync_library()
    return {'items':db.rows('SELECT * FROM assets ORDER BY created DESC LIMIT 500')}


class AssetPermission(BaseModel):
    source_class: str
    evidence: str = Field(min_length=10,max_length=2000)


@app.put('/api/assets/{id}/rights', dependencies=protected)
def update_asset_rights(id: str, item: AssetPermission):
    from backend.assets import set_license
    if not db.rows('SELECT id FROM assets WHERE id=:id',{'id':id}):raise HTTPException(404,'Asset não encontrado.')
    try:set_license(id,item.source_class,item.evidence)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None
    return {'updated':True}


@app.post('/api/assets/{id}/download', dependencies=protected)
def download_library_short(id: str):
    from backend.assets import download_short
    try:
        return {'path':download_short(id)}
    except (ValueError,IntegrationError) as exc:
        raise HTTPException(409,str(exc)) from None


@app.post('/api/assets/upload', dependencies=protected)
async def upload_asset(kind: str = Form(...),file: UploadFile = File(...)):
    """Local import. Uploaded files are untrusted until the owner records rights."""
    from backend.assets import ROOT,KINDS,sync_library
    import re
    if kind not in ('shorts','gameplay','images','persona'):raise HTTPException(422,'Use Upload de mídia para este tipo de arquivo.')
    extension=Path(file.filename or '').suffix.lower()
    allowed={ 'shorts':{'.mp4'},'gameplay':{'.mp4','.mov','.webm'},
              'images':{'.png','.jpeg','.jpg','.webp'},
              'persona':{'.png','.jpeg','.jpg','.webp'}}
    if extension not in allowed[kind]:raise HTTPException(422,'Extensão não suportada.')
    stem=re.sub(r'[^a-zA-Z0-9_-]','_',Path(file.filename).stem)[:60] or db.uid()
    destination=ROOT/kind/(stem+'-'+db.uid()[:8]+extension)
    partial=destination.with_suffix(destination.suffix+'.partial')
    size=0
    try:
        with partial.open('xb') as stream:
            while chunk:=await file.read(1024*1024):
                size+=len(chunk)
                if size>250*1024*1024:raise HTTPException(413,'Arquivo maior que 250 MB.')
                stream.write(chunk)
        if size==0:raise HTTPException(422,'Arquivo vazio.')
        if kind in ('persona','images'):
            from PIL import Image
            with Image.open(partial) as img:img.verify()
        else:
            from backend.media import probe
            info=probe(partial)
            if not any(x.get('codec_type')=='video' for x in info.get('streams',[])):
                raise HTTPException(422,'Arquivo não contém vídeo legível.')
        os.replace(partial,destination)
        sync_library()
        found=db.rows('SELECT * FROM assets WHERE path=:path',{'path':str(destination.relative_to(db.ROOT))})
        if not found:
            from backend.clips import file_sha256
            found=db.rows('SELECT * FROM assets WHERE sha256=:sha AND parent_id IS NULL',{'sha':file_sha256(destination)})
        return {'asset':found[0] if found else None,'permission_required':True,'duplicate':bool(found and found[0]['path']!=str(destination.relative_to(db.ROOT)))}
    finally:
        partial.unlink(missing_ok=True)



class UploadStart(BaseModel):
    filename: str = Field(min_length=1,max_length=255)
    size: int = Field(gt=0)
    category: str = 'outro'
    tags: list[str] = Field(default_factory=list,max_length=25)
    source_class: str = 'THIRD_PARTY'
    evidence: str = Field(default='',max_length=2000)
    fingerprint: str


@app.post('/api/uploads/sessions', dependencies=protected)
def upload_start(item: UploadStart):
    from backend.uploads import create_session
    try:return create_session(item)
    except ValueError as exc:raise HTTPException(422,str(exc)) from None


@app.get('/api/uploads/sessions/{sid}', dependencies=protected)
def upload_status(sid: str):
    from backend.uploads import status
    try:return status(sid)
    except ValueError as exc:raise HTTPException(404,str(exc)) from None


@app.patch('/api/uploads/sessions/{sid}', dependencies=protected)
async def upload_append(sid: str, request: Request, upload_offset: int = Header(...,alias='Upload-Offset')):
    from backend.uploads import append_chunk
    try:return await append_chunk(sid,upload_offset,request.stream())
    except ValueError as exc:raise HTTPException(409,str(exc)) from None


@app.post('/api/uploads/sessions/{sid}/finish', dependencies=protected)
def upload_finish(sid: str):
    from backend.uploads import finish
    try:return finish(sid)
    except (ValueError, RuntimeError, OSError) as exc:raise HTTPException(422,str(exc)) from None


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None,max_length=300)
    category: str | None = None
    tags: list[str] | None = None
    active: bool | None = None


@app.patch('/api/assets/{id}', dependencies=protected)
def patch_asset(id: str, item: AssetUpdate):
    from backend.assets import update_metadata
    try:return {'asset':update_metadata(id,item.title,item.category,item.tags,item.active)}
    except ValueError as exc:raise HTTPException(422,str(exc)) from None

@app.get('/api/assets/{id}/file', dependencies=protected)
def asset_file(id: str):
    import mimetypes
    found=db.rows('SELECT path FROM assets WHERE id=:id',{'id':id})
    if not found or not found[0]['path']:raise HTTPException(404,'Asset não baixado ou sem arquivo local.')
    try:file=db.safe_file(found[0]['path'])
    except ValueError:raise HTTPException(404,'Arquivo não encontrado.') from None
    mime=mimetypes.guess_type(file.name)[0] or 'application/octet-stream'
    return FileResponse(file,media_type=mime)


class DeleteAsset(BaseModel):
    confirm_children: bool = False


@app.delete('/api/assets/{id}', dependencies=protected)
def delete_asset(id: str, payload: DeleteAsset = Body(default=DeleteAsset())):
    from backend.assets import delete
    try:
        if not delete(id,confirm_children=payload.confirm_children):
            raise HTTPException(404,'Asset não encontrado.')
    except ValueError as exc:raise HTTPException(409,str(exc)) from None
    return {'deleted':True}


@app.get('/api/persona', dependencies=protected)
def persona_details():
    from backend.personas import PRESETS,get_persona
    return {'presets':PRESETS,'current':get_persona()}


class PersonaUpdate(BaseModel):
    selected: str
    overrides: dict[str,Any] = Field(default_factory=dict)
    image_path: str = ''
    voice_model: str = ''


@app.put('/api/persona', dependencies=protected)
def save_persona(item: PersonaUpdate):
    from backend.personas import PRESETS,get_persona
    from backend.assets import safe_asset
    if item.selected not in PRESETS:raise HTTPException(422,'Escolha uma das três personas originais.')
    if len(str(item.overrides))>4000:raise HTTPException(422,'Dossiê muito extenso.')
    if any(k not in ('name','look','personality','voice','opening','closing','catchphrases','never') for k in item.overrides):
        raise HTTPException(422,'Campo de persona não permitido.')
    if any(not isinstance(value,str) for key,value in item.overrides.items() if key not in ('catchphrases','never')):
        raise HTTPException(422,'Campos textuais inválidos.')
    for field in ('catchphrases','never'):
        if field in item.overrides and (not isinstance(item.overrides[field],list) or
            len(item.overrides[field])>12 or any(not isinstance(x,str) or len(x)>160 for x in item.overrides[field])):
            raise HTTPException(422,f'Lista {field} inválida.')
    if item.image_path:
        try:picture=safe_asset(item.image_path)
        except ValueError:raise HTTPException(422,'Imagem não cadastrada na biblioteca.') from None
        if not (picture.is_relative_to((db.ROOT/'assets/persona').resolve()) or picture.is_relative_to((db.ROOT/'assets/personas').resolve())):
            raise HTTPException(422,'Coloque a imagem em assets/persona ou assets/personas/<nome>.')
    if item.voice_model:
        from pathlib import Path
        path=Path(item.voice_model).resolve()
        if not path.is_file() or path.suffix!='.onnx' or not path.is_relative_to(Path('/models').resolve()):
            raise HTTPException(422,'Voz deve ser um arquivo .onnx existente na pasta /models.')
    db.put_setting('persona',item.model_dump())
    return {'saved':True,'current':get_persona()}



class CastUpdate(BaseModel):
    look: str | None = Field(default=None, max_length=500)
    personality: str | None = Field(default=None, max_length=600)
    voice: str | None = Field(default=None, max_length=300)
    voice_model: str | None = Field(default=None, max_length=300)
    image_path: str | None = Field(default=None, max_length=300)
    speed: float | None = Field(default=None, ge=0.7, le=1.3)
    opening: str | None = Field(default=None, max_length=250)
    closing: str | None = Field(default=None, max_length=250)


@app.get('/api/personas', dependencies=protected)
def list_cast():
    from backend.personas import get_cast
    return {'cast':get_cast()}


@app.put('/api/personas/{slug}', dependencies=protected)
def update_cast(slug: str, changes: CastUpdate):
    from backend.personas import get_cast
    from backend.assets import safe_asset
    if slug not in ('dante_palma','lia_varela','caio_rivas'):
        raise HTTPException(404,'Personagem não encontrado.')
    data={k:v for k,v in changes.model_dump().items() if v is not None}
    if 'image_path' in data and data['image_path']:
        try:
            img=safe_asset(data['image_path'])
            if img.suffix.lower() not in ('.png','.jpg','.jpeg','.webp'):
                raise ValueError('Formato inválido')
        except ValueError:raise HTTPException(422,'Imagem não encontrada em /assets/') from None
    if 'voice_model' in data and data['voice_model']:
        model=Path(data['voice_model']).resolve()
        if not model.is_file() or model.suffix!='.onnx' or not model.is_relative_to(Path('/models').resolve()):
            raise HTTPException(422,'Voz Piper precisa existir em /models/*.onnx')
    existing=db.get_setting('cast',{})
    existing[slug]={**existing.get(slug,{}),**data}
    db.put_setting('cast',existing)
    return {'saved':True,'persona':get_cast()[slug]}


@app.get('/api/personas/{slug}/avatar', dependencies=protected)
def cast_avatar(slug: str):
    from backend.personas import get_cast
    from backend.assets import safe_asset
    info=get_cast().get(slug)
    if not info or not info.get('image_path'):
        raise HTTPException(404,'Nenhuma imagem definida para este personagem.')
    try:img=safe_asset(info['image_path'])
    except ValueError:raise HTTPException(404,'Imagem da persona não encontrada.') from None
    return FileResponse(img,media_type='image/png')


@app.get('/api/personas/{slug}/sample', dependencies=protected)
def cast_sample(slug: str):
    from backend.personas import get_cast
    from backend.media import binary
    import subprocess
    person=get_cast().get(slug)
    if person is None:raise HTTPException(404,'Personagem não encontrado.')
    model=Path(person.get('voice_model','')).resolve() if person.get('voice_model') else None
    if not model or not model.is_file() or not model.is_relative_to(Path('/models').resolve()):
        raise HTTPException(409,'Configure uma voz Piper existente na pasta /models para ouvir a amostra.')
    target=db.ROOT/'cache'/('voice-sample-'+slug+'.wav')
    phrase='GTA seis: vamos separar o que sabemos do que ainda é rumor.'
    result=subprocess.run([binary('piper'),'--model',str(model),'--length_scale',str(round(1/float(person.get('speed') or 1),3)),'--output_file',str(target)],
             input=phrase.encode('utf-8'),capture_output=True,timeout=120)
    if result.returncode or not target.is_file():
        raise HTTPException(503,'Falha no Piper: '+result.stderr.decode('utf-8',errors='replace')[-300:])
    return FileResponse(target,media_type='audio/wav')


# Persona poses: auth-required, with idempotent validation and no arbitrary paths.
def _pose_folder(slug:str):
    if slug not in ('dante_palma','lia_varela','caio_rivas'):
        raise HTTPException(404,'Personagem inexistente.')
    from backend.personas import get_cast
    get_cast()
    return db.ROOT/'assets'/'personas'/slug/'expressions'

def _pose_manifest(slug:str):
    folder=_pose_folder(slug)
    file=folder/'manifest.json'
    if not file.is_file():raise HTTPException(404,'Galeria não instalada.')
    return folder,json.loads(file.read_text('utf-8'))

@app.post('/api/personas/{slug}/pose-sheet',dependencies=protected)
async def upload_pose_reference(slug:str,file:UploadFile=File(...)):
    from backend.pose_import import save_sheet
    try:return save_sheet(slug,await file.read())
    except (ValueError,OSError) as exc:raise HTTPException(422,str(exc)) from None


@app.post('/api/personas/{slug}/expressions/import',dependencies=protected)
async def import_pose_package(slug:str,file:UploadFile=File(...)):
    from backend.pose_import import import_poses
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'poses.zip'
            size=0
            with target.open('wb') as output:
                while chunk:=await file.read(1024*1024):
                    size+=len(chunk)
                    if size>300*1024*1024:raise HTTPException(413,'Pacote de poses excede 300 MB.')
                    output.write(chunk)
            return import_poses(slug,target)
    except (ValueError,OSError, __import__('zipfile').BadZipFile) as exc:
        raise HTTPException(422,str(exc)) from None


@app.get('/api/personas/{slug}/expressions',dependencies=protected)
def expressions(slug:str):
    folder,manifest=_pose_manifest(slug)
    return {'personagem':slug,'images':[{
        **image,'exists':(folder/image['file']).is_file(),
        'url':f'/api/personas/{slug}/expressions/{image["index"]}/file'
        } for image in manifest['images']]}

@app.get('/api/personas/{slug}/expressions/{index}/file',dependencies=protected)
def expression_image(slug:str,index:int):
    folder,manifest=_pose_manifest(slug)
    record=next((e for e in manifest['images'] if e['index']==index),None)
    if not record:raise HTTPException(404,'Pose inexistente.')
    file=folder/record['file']
    if not file.is_file():raise HTTPException(404,'Arquivo PNG não encontrado.')
    return FileResponse(file,media_type='image/png')

class ExpressionUpdate(BaseModel):
    active: bool

@app.patch('/api/personas/{slug}/expressions/{index}',dependencies=protected)
def expression_active(slug:str,index:int,item:ExpressionUpdate):
    folder,manifest=_pose_manifest(slug)
    record=next((e for e in manifest['images'] if e['index']==index),None)
    if not record:raise HTTPException(404,'Pose inexistente.')
    if index==1 and not item.active:raise HTTPException(409,'A pose neutra é obrigatória como fallback.')
    record['active']=item.active
    db.atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'updated':True}

@app.post('/api/personas/{slug}/expressions/{index}/restore',dependencies=protected)
def restore_expression(slug:str,index:int):
    import shutil,hashlib
    folder,manifest=_pose_manifest(slug)
    record=next((e for e in manifest['images'] if e['index']==index),None)
    if not record:raise HTTPException(404,'Pose inexistente.')
    # Creator-supplied high-resolution master takes precedence; never restore SVG placeholders.
    template=db.ROOT/'assets'/'personas'/'_quality_master'/slug/record['file']
    if not template.is_file():
        raise HTTPException(409,'A pose não possui um master de qualidade. Importe os 24 PNGs antes de restaurar.')
    dest=folder/record['file'];tmp=folder/(record['file']+'.restoring')
    shutil.copy2(template,tmp);tmp.replace(dest)
    record['sha256']=hashlib.sha256(dest.read_bytes()).hexdigest();record['active']=True
    db.atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'restored':True,'mode':'restored_from_reference_not_ai_generated'}

@app.put('/api/personas/{slug}/expressions/{index}/image',dependencies=protected)
async def replace_expression(slug:str,index:int,file:UploadFile=File(...)):
    from PIL import Image
    from io import BytesIO
    import hashlib
    folder,manifest=_pose_manifest(slug)
    record=next((e for e in manifest['images'] if e['index']==index),None)
    if not record:raise HTTPException(404,'Pose inexistente.')
    content=await file.read(12*1024*1024+1)
    if len(content)>12*1024*1024:raise HTTPException(413,'PNG excede 12 MB.')
    try:
        im=Image.open(BytesIO(content))
        if im.format!='PNG' or im.mode!='RGBA' or im.size!=(1024,1536):
            raise ValueError('Exigido PNG RGBA 1024x1536.')
        if any(im.getpixel(c)[3]!=0 for c in [(0,0),(1023,0),(0,1535),(1023,1535)]):
            raise ValueError('Os quatro cantos devem ser transparentes.')
        if im.getchannel('A').getbbox() is None:raise ValueError('A imagem não contém personagem.')
    except (OSError,ValueError) as exc:raise HTTPException(422,str(exc)) from None
    destination=folder/record['file'];temporary=folder/(record['file']+'.uploading')
    temporary.write_bytes(content);temporary.replace(destination)
    record['sha256']=hashlib.sha256(content).hexdigest();record['active']=True
    db.atomic(folder/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return {'saved':True}

@app.get('/api/videos/{id}/audio-timeline',dependencies=protected)
def audio_timeline(id:str,attempt:int|None=None):
    found=db.rows('SELECT revision FROM videos WHERE id=:id',{'id':id})
    if not found:raise HTTPException(404,'Produção não encontrada.')
    a=attempt or found[0]['revision'] or 1
    path=db.ROOT/'videos'/'processing'/id/f'attempt-{a:02d}'/'audio-timeline.json'
    if not path.is_file():raise HTTPException(404,'Áudio ainda não renderizado ou medido.')
    return json.loads(path.read_text('utf-8'))

@app.get('/api/videos/{id}/pose-timeline',dependencies=protected)
def pose_timeline(id:str,attempt:int|None=None):
    found=db.rows('SELECT revision FROM videos WHERE id=:id',{'id':id})
    if not found:raise HTTPException(404,'Produção não encontrada.')
    a=attempt or found[0]['revision'] or 1
    path=db.ROOT/'videos'/'processing'/id/f'attempt-{a:02d}'/'pose-timeline.json'
    if not path.is_file():raise HTTPException(404,'Poses ainda não definidas.')
    return json.loads(path.read_text('utf-8'))


class TemplateEdit(BaseModel):
    background: str = Field(pattern=r'^0x[0-9a-fA-F]{6}$')
    accent: str = Field(pattern=r'^0x[0-9a-fA-F]{6}$')
    font_size: int = Field(ge=36, le=72)


@app.put('/api/templates/{name}', dependencies=protected)
def edit_template(name: str, item: TemplateEdit):
    if name not in template_list():
        raise HTTPException(404, 'Template inexistente.')
    overrides = db.get_setting('templates', {})
    overrides[name] = item.model_dump()
    db.put_setting('templates', overrides)
    return {'saved': True}
