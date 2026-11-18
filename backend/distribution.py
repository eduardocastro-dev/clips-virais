"""Postiz public API adapter; receipt IDs are scheduling acknowledgments, never publication proof."""
import json
import time
from datetime import datetime, timezone, timedelta
from sqlalchemy import text
from backend import core as db
from backend.contracts import platform_url
from backend.integrations import request, IntegrationError


def postiz(method, path, **kwargs):
    config = db.settings()
    key = db.secret('postiz_api_key')
    if not config.postiz_url or not key:
        raise IntegrationError('Configure a URL pública da API Postiz e postiz_api_key.')
    # Conservative public API budget; counts failed calls as requests too.
    with db.transaction() as c:
        window='postiz-rate:'+str(int(time.time()//3600))
        current=c.execute(text('SELECT value FROM kv WHERE key=:key'),{'key':window}).scalar()
        count=int(current) if current else 0
        if count>=30:raise IntegrationError('Limite local Postiz de 30 requisições/hora atingido.')
        c.execute(text('INSERT INTO kv VALUES (:key,:value) ON CONFLICT(key) DO UPDATE SET value=excluded.value'),dict(key=window,value=str(count+1)))
    return request(method, config.postiz_url + path, headers={'Authorization': key}, **kwargs).json()


def channels():
    result = postiz('GET', '/integrations')
    if not isinstance(result, list):
        raise IntegrationError('Resposta de integrações Postiz inválida.')
    return [{k: item.get(k) for k in ['id','name','identifier','disabled','profile']} for item in result
            if item.get('identifier') in ('youtube','tiktok','instagram','instagram-standalone')]


def schedule_postiz(publication, path, script):
    config = db.settings()
    if config.emergency_stop:raise IntegrationError('Parada de emergência ativa.')
    platform = publication['platform']
    channel = config.postiz_channels.get(platform)
    provider_settings = config.postiz_settings.get(platform, {})
    allowed_types = {'youtube':['youtube'],'tiktok':['tiktok'],'instagram':['instagram','instagram-standalone']}
    if not channel or provider_settings.get('__type') not in allowed_types[platform]:
        raise IntegrationError('Selecione o canal e as configurações oficiais do provedor no Postiz.')
    available = channels()
    if not any(c['id']==channel and not c['disabled'] and c['identifier'] in allowed_types[platform] for c in available):
        raise IntegrationError('Canal Postiz não encontrado, desativado ou de outra plataforma.')
    with path.open('rb') as file:
        media = postiz('POST', '/upload', files={'file':(path.name,file,'video/mp4')})
    if not media.get('id') or not media.get('path'):
        raise IntegrationError('Upload Postiz não confirmou mídia.')
    if media.get('status')=='processing':raise IntegrationError('Mídia Postiz ainda em processamento; envio não iniciado.')
    when = max(publication.get('scheduled_for') or 0, time.time()+60)
    date = datetime.fromtimestamp(when, timezone.utc).isoformat().replace('+00:00','Z')
    if platform == 'youtube':
        provider_settings = {**provider_settings, 'title':script['title']}
    body = {'type':'schedule','date':date,'shortLink':False,'tags':[],
        'posts':[{'integration':{'id':channel},'value':[{'content':script['description']+'\n'+' '.join('#'+h.lstrip('#') for h in script['hashtags']),
            'image':[{'id':media['id'],'path':media['path']}]}], 'settings':provider_settings}]}
    # Guard durable intent before non-idempotent POST. Never retry an ambiguous acknowledgment.
    if db.settings().emergency_stop:raise IntegrationError('Parada de emergência ativa antes do envio.')
    if not db.execute("UPDATE publications SET status='PUBLICANDO',provider='postiz',updated=:now WHERE id=:id AND status IN ('PENDENTE','AGUARDANDO_PUBLICACAO_MANUAL')",
                      dict(now=time.time(),id=publication['id'])):
        return
    result = postiz('POST','/posts',json=body)
    if not isinstance(result,list) or not result or not result[0].get('postId'):
        raise IntegrationError('Resposta de agendamento incerta; reconcilie no Postiz antes de repetir.')
    db.execute("UPDATE publications SET status='AGENDADO',remote_id=:remote,scheduled_for=:date,updated=:now WHERE id=:id",
        dict(id=publication['id'],remote=result[0]['postId'],date=when,now=time.time()))
    db.notify('scheduled:'+publication['id'],f'{platform}: agendamento recebido pelo Postiz; aguardando confirmação efetiva.')


def reconcile_postiz():
    pending = db.rows("SELECT * FROM publications WHERE provider='postiz' AND status IN ('AGENDADO','PUBLICANDO') AND remote_id IS NOT NULL")
    if not pending:
        return
    start = datetime.fromtimestamp(min(p['scheduled_for'] or p['updated'] for p in pending),timezone.utc)-timedelta(days=2)
    end = datetime.fromtimestamp(max(p['scheduled_for'] or p['updated'] for p in pending),timezone.utc)+timedelta(days=2)
    result = postiz('GET','/posts',params={'startDate':start.isoformat(),'endDate':end.isoformat()})
    remote = {p['id']:p for p in result.get('posts',[]) if p.get('id')}
    for publication in pending:
        item = remote.get(publication['remote_id'])
        if not item:
            continue
        if item.get('state') == 'PUBLISHED' and item.get('releaseURL'):
            try:
                platform,url = platform_url(item['releaseURL'])
            except ValueError:
                db.notify('postiz-url:'+publication['id'],'Postiz informou URL não reconhecida; confirme manualmente.')
                continue
            if platform != publication['platform']:
                continue
            external = url.split('v=')[-1] if platform=='youtube' else url.rstrip('/').split('/')[-1]
            db.execute("UPDATE publications SET status='PUBLICADO',url=:url,external_id=:external,updated=:now WHERE id=:id",
                dict(id=publication['id'],url=url,external=external,now=time.time()))
            db.notify('published:'+publication['id'],'Publicação confirmada pela integração: '+url)
        elif item.get('state') == 'ERROR':
            db.execute("UPDATE publications SET status='AGUARDANDO_PUBLICACAO_MANUAL',error='Falha reportada pelo Postiz; consulte o canal e reconcilie antes de reenviar.',updated=:now WHERE id=:id",
                       dict(id=publication['id'],now=time.time()))
            db.notify('postiz-failed:'+publication['id'],'Falha Postiz: arquivo preservado para publicação manual.')


def collect_postiz_metrics():
    for publication in db.rows("SELECT * FROM publications WHERE provider='postiz' AND status='PUBLICADO' AND remote_id IS NOT NULL"):
        key='postiz-metrics:'+publication['id']
        if db.cache_get(key):continue
        try:
            series=postiz('GET','/analytics/post/'+publication['remote_id'],params={'date':'7'})
            if not isinstance(series,list):raise IntegrationError('Métricas Postiz fora do schema esperado.')
            data={k:None for k in ['views','likes','comments','shares','retention','ctr','average_watch_seconds','follower_growth']}
            labels={'views':'views','video views':'views','likes':'likes','comments':'comments','shares':'shares'}
            for metric in series:
                name=labels.get(str(metric.get('label','')).lower())
                observations=sorted(metric.get('data',[]),key=lambda p:p.get('date',''))
                if name and observations:
                    try:data[name]=float(observations[-1]['total'])
                    except (ValueError,TypeError,KeyError):pass
            data['provider_series']=series
            data['measurement']='Último total por data fornecido pelo Postiz; séries originais preservadas.'
            db.execute('INSERT INTO metrics VALUES (:id,:pub,:now,:data)',dict(id=db.uid(),pub=publication['id'],now=time.time(),data=json.dumps(data)))
            db.cache_set(key,True,21600)
        except IntegrationError:
            db.notify('postiz-metrics:'+publication['id']+':'+db.today(),'Métricas Postiz indisponíveis para '+publication['id'])
