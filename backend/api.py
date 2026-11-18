import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from fastapi import FastAPI, Depends, Header, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field
from backend import core as db
from backend.contracts import Settings, ImportRequest, ProfileRequest, Script, platform_url
from backend.pipeline import create_video, AGENTS
from backend.distribution import channels, schedule_postiz
from backend.integrations import IntegrationError
from backend.sources import public_url


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
    videos = db.rows('SELECT * FROM videos ORDER BY created DESC LIMIT 100')
    return {'settings': db.settings().model_dump(), 'videos': videos,
        'publications': db.rows('SELECT p.*,v.title,v.test,v.template FROM publications p JOIN videos v ON p.video_id=v.id ORDER BY p.updated DESC LIMIT 200'),
        'profiles': db.rows('SELECT * FROM profiles ORDER BY priority DESC'),
        'sources': db.rows('SELECT * FROM sources ORDER BY name'),
        'opportunities': db.rows('SELECT * FROM opportunities ORDER BY score DESC LIMIT 100'),
        'notifications': db.rows('SELECT * FROM notifications ORDER BY created DESC LIMIT 50'),
        'events': db.rows('SELECT * FROM events ORDER BY created DESC LIMIT 100'),
        'jobs': db.rows('SELECT * FROM jobs ORDER BY due DESC LIMIT 100'),
        'metrics': db.rows('SELECT m.*,p.platform,v.template FROM metrics m JOIN publications p ON p.id=m.publication_id JOIN videos v ON v.id=p.video_id ORDER BY observed DESC LIMIT 500'),
        'usage': db.rows('SELECT * FROM usage ORDER BY day DESC LIMIT 30'),
        'recommendations':db.get_setting('recommendations',{}),
        'worker_online': time.time() - db.get_setting('worker_heartbeat', 0) < 120,
        'agents': AGENTS, 'templates': template_list(),
        'secrets': [x['key'].removeprefix('secret:') for x in db.rows("SELECT key FROM kv WHERE key LIKE 'secret:%'")]}


@app.get('/api/settings', dependencies=protected)
def get_settings():
    return db.settings()


@app.put('/api/settings', dependencies=protected)
def save_settings(settings: Settings):
    settings.configured = True
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
        return {'id': create_video(item)}
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
    db.enqueue('discover')
    return {'queued': True}


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
        return channels()
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
    pub = db.rows('SELECT * FROM publications WHERE id=:id',{'id':id})
    if not pub:
        raise HTTPException(404,'Publicação não encontrada.')
    pub=pub[0]
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':pub['video_id']})[0]
    if not item.reviewed or video['test'] or not video['approved'] or video['rights'] in ('BLOCKED','REVIEW_REQUIRED'):
        raise HTTPException(409,'Envio exige vídeo real aprovado e revisão humana confirmada.')
    if db.settings().emergency_stop or pub['platform'] in db.settings().paused_integrations:
        raise HTTPException(409,'Publicação pausada.')
    if pub['status'] not in ('PENDENTE','AGUARDANDO_PUBLICACAO_MANUAL') or pub['remote_id']:
        raise HTTPException(409,'Envio já iniciado; reconcilie no Postiz antes de qualquer repetição.')
    script=json.loads((db.ROOT/'handoff'/video['id']/'script.json').read_text('utf-8'))
    script['description']+='\n\nCréditos: '+video['credits'] if video['credits'] else ''
    try:
        schedule_postiz(pub,db.safe_file(video['final_path']),script)
    except (IntegrationError,ValueError) as exc:
        raise HTTPException(409,str(exc)) from None
    db.log_event(video['id'],'publication','REVIEWED','Revisão humana confirmada no painel antes de enviar ao Postiz.')
    return {'status':'AGENDADO'}


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


@app.get('/api/files/{video_id}', dependencies=protected)
def video_file(video_id: str):
    video = db.rows('SELECT final_path FROM videos WHERE id=:id', {'id': video_id})
    if not video or not video[0]['final_path']:
        raise HTTPException(404, 'Vídeo ainda não disponível.')
    try:
        file = db.safe_file(video[0]['final_path'])
    except ValueError:
        raise HTTPException(404, 'Vídeo removido pela política de retenção.') from None
    return FileResponse(file, media_type='video/mp4', filename=video_id + '.mp4')


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
