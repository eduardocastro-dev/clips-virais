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
        'recommendations':db.get_setting('recommendations',{}),
        'worker_online': time.time() - db.get_setting('worker_heartbeat', 0) < 120,
        'agents': AGENTS, 'templates': template_list(), 'daily_production_usage': db.production_usage(),
        'secrets': [x['key'].removeprefix('secret:') for x in db.rows("SELECT key FROM kv WHERE key LIKE 'secret:%'")]}


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
    if kind not in KINDS:raise HTTPException(422,'Categoria inválida.')
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
        return {'asset':found[0] if found else None,'permission_required':True}
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
        if not picture.is_relative_to((db.ROOT/'assets/persona').resolve()):
            raise HTTPException(422,'Coloque a imagem em assets/persona.')
    if item.voice_model:
        from pathlib import Path
        path=Path(item.voice_model).resolve()
        if not path.is_file() or path.suffix!='.onnx' or not path.is_relative_to(Path('/models').resolve()):
            raise HTTPException(422,'Voz deve ser um arquivo .onnx existente na pasta /models.')
    db.put_setting('persona',item.model_dump())
    return {'saved':True,'current':get_persona()}

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
