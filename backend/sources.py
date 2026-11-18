import ipaddress
import socket
import re
import json
import time
from urllib.parse import urlsplit
import feedparser
from backend import core as db
from backend.integrations import request, IntegrationError, viral_score


def public_url(value):
    u=urlsplit(value)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError('Use URL HTTPS pública, sem credenciais.')
    return value


def ensure_public_host(url):
    host=urlsplit(public_url(url)).hostname
    try:
        addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
    except OSError:
        raise IntegrationError('Não foi possível resolver o domínio da fonte.') from None
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise IntegrationError('Fontes de pesquisa não podem acessar endereços privados.')


def store_opportunity(meta, profile_id=None):
    db.execute('''INSERT INTO opportunities VALUES (:id,:url,:platform,:title,:meta,:score,:now,:profile)
        ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata,score=excluded.score''',dict(id=db.uid(),url=meta['url'],platform=meta['platform'],
        title=meta['title'],meta=json.dumps(meta,ensure_ascii=False),score=viral_score(meta),now=time.time(),profile=profile_id))


def scan_feed(source):
    ensure_public_host(source['url'])
    content=request('GET',source['url'],headers={'User-Agent':'GTAContentStudio/0.1 (+personal RSS reader)'}).content
    if len(content)>2_000_000:
        raise IntegrationError('Feed excede o limite de 2 MB.')
    feed=feedparser.parse(content)
    if not feed.entries:
        raise IntegrationError('Feed sem entradas RSS/Atom legíveis.')
    found=[]
    for entry in feed.entries[:30]:
        title=entry.get('title','')[:300]
        description=re.sub('<[^>]+>',' ',entry.get('summary',''))[:4000]
        if not re.search(r'gta\s*(vi|6)|grand theft auto',title+' '+description,re.I):
            continue
        url=entry.get('link','')
        try:public_url(url)
        except ValueError:continue
        meta={'url':url,'platform':'news','title':title,'description':description,'metrics':{},'source_profile':source['name'],
              'source_feed':source['url'],'published':entry.get('published'),'collected_at':time.time(),'rights':'REFERENCE_ONLY'}
        store_opportunity(meta);found.append(url)
    return found


def connected_profile(profile):
    """Official APIs only expose the account authorized by the configured tokens."""
    platform=profile['platform']
    expected=urlsplit(profile['url']).path.strip('/').lstrip('@').lower()
    if platform=='tiktok':
        token=db.secret('tiktok_access_token')
        if not token:raise IntegrationError('TikTok requer token oficial com user.info.profile e video.list.')
        headers={'Authorization':'Bearer '+token}
        info=request('GET','https://open.tiktokapis.com/v2/user/info/',headers=headers,params={'fields':'username,display_name'}).json()
        user=info.get('data',{}).get('user',{})
        if user.get('username','').lower()!=expected:
            raise IntegrationError('O token TikTok não autoriza o perfil solicitado ou falta escopo de identidade.')
        response=request('POST','https://open.tiktokapis.com/v2/video/list/',headers=headers,
            params={'fields':'id,title,video_description,duration,share_url,view_count,like_count,comment_count,share_count,create_time'},json={'max_count':20}).json()
        items=response.get('data',{}).get('videos')
        if items is None:raise IntegrationError('TikTok não disponibilizou vídeos para este token.')
        from datetime import datetime,timezone
        result=[{'url':v.get('share_url',''),'platform':'tiktok','title':v.get('title',''), 'description':v.get('video_description',''),
            'duration':v.get('duration'),'source_profile':expected,'published':datetime.fromtimestamp(v['create_time'],timezone.utc).isoformat() if v.get('create_time') else None,
            'metrics':{k:v.get(remote) for k,remote in [('viewCount','view_count'),('likeCount','like_count'),('commentCount','comment_count'),('shareCount','share_count')]},
            'collected_at':time.time()} for v in items]
    elif platform=='instagram':
        token=db.secret('instagram_access_token');user_id=db.secret('instagram_user_id')
        if not token or not user_id or not re.fullmatch(r'\d+',user_id):
            raise IntegrationError('Instagram requer token Meta autorizado e ID da conta profissional.')
        headers={'Authorization':'Bearer '+token}
        base='https://graph.facebook.com/v23.0/'+user_id
        user=request('GET',base,headers=headers,params={'fields':'username'}).json()
        if user.get('username','').lower()!=expected:
            raise IntegrationError('A conta Instagram autorizada não corresponde ao perfil solicitado.')
        response=request('GET',base+'/media',headers=headers,params={'fields':'id,caption,media_type,permalink,timestamp,like_count,comments_count','limit':25}).json()
        if 'data' not in response:raise IntegrationError('Instagram não disponibilizou mídia para este token.')
        result=[{'url':v.get('permalink',''),'platform':'instagram','title':v.get('caption','')[:120] or 'Vídeo Instagram',
            'description':v.get('caption','')[:4000],'source_profile':expected,'published':v.get('timestamp'),
            'metrics':{'likeCount':v.get('like_count'),'commentCount':v.get('comments_count')},'collected_at':time.time()}
            for v in response['data'] if v.get('media_type')=='VIDEO']
    else:
        raise IntegrationError('Perfil não suportado neste adaptador.')
    from backend.contracts import platform_url
    valid=[]
    for item in result:
        if not re.search(r'gta\s*(vi|6)|grand theft auto',item['title']+' '+item['description'],re.I):continue
        try:item['url']=platform_url(item['url'])[1]
        except ValueError:continue
        item['metrics']={k:v for k,v in item['metrics'].items() if v is not None}
        store_opportunity(item,profile['id']);valid.append(item)
    return valid


def seed_default_sources():
    """Idempotent public-news RSS defaults; stored under existing schema."""
    from urllib.parse import urlencode
    presets = (
        ('Google News · GTA VI (EN)', 'GTA 6 OR "Grand Theft Auto VI"', 'en-US', 'US', 'US:en'),
        ('Google News · GTA 6 (BR)', 'GTA 6 OR "Grand Theft Auto VI"', 'pt-BR', 'BR', 'BR:pt-419'),
        ('Google News · GTA 6 Gameplay', 'GTA 6 gameplay OR GTA VI trailer', 'en-US', 'US', 'US:en'),
        ('Google News · Rockstar Oficial', 'site:rockstargames.com GTA VI', 'en-US', 'US', 'US:en'),
    )
    for name, query, hl, gl, ceid in presets:
        url = 'https://news.google.com/rss/search?' + urlencode({'q': query, 'hl': hl, 'gl': gl, 'ceid': ceid})
        db.execute("""INSERT OR IGNORE INTO sources (id,url,name,enabled,interval_minutes,last_checked,error)
            VALUES (:id,:url,:name,1,180,NULL,NULL)""",
            {'id': db.uid(), 'url': url, 'name': name})
