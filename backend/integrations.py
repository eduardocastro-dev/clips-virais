"""Network adapters. Every remote result is evidence, never a claimed success."""
import json
import base64
import math
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs, urlencode
import httpx
from sqlalchemy import text
from backend import core as db


class IntegrationError(RuntimeError):
    pass


def request(method, url, **kwargs):
    # Do not propagate exception URLs: provider query parameters can contain secrets.
    try:
        with httpx.Client(timeout=60, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise IntegrationError(f'Integração respondeu HTTP {response.status_code}.')
        if response.is_redirect:
            raise IntegrationError('Redirecionamento inesperado na integração.')
        return response
    except httpx.HTTPError:
        raise IntegrationError('Falha de rede ou timeout na integração.') from None


def youtube_get(resource, params):
    from backend.youtube_data import _get_api,access_token
    key=db.secret('youtube_api_key')
    return _get_api(resource,params,key=key,
                    token=access_token() if not key else None)


def youtube_metadata(url):
    return public_youtube_metadata(url)


def metadata(url, platform):
    url=url.split('#studio-variant=')[0]
    if platform == 'youtube':
        return youtube_metadata(url)
    if platform == 'instagram':
        return public_social_metadata(url, platform)
    # Public oEmbed provides reference metadata only, not reuse permission.
    endpoint = 'https://www.tiktok.com/oembed' if platform == 'tiktok' else None
    if not endpoint:
        opportunities=db.rows('SELECT metadata FROM opportunities WHERE url=:url',{'url':url})
        if opportunities:
            return json.loads(opportunities[0]['metadata'])
        raise IntegrationError('Instagram requer consulta prévia do perfil conectado pela API Meta. Importação preservada.')
    result = request('GET', endpoint, params={'url': url}).json()
    return {'title': result.get('title', ''), 'description': '', 'source_profile': result.get('author_name'),
            'metrics': {}, 'url': url, 'platform': platform, 'collected_at': time.time()}



def public_social_metadata(url, platform):
    """Public reference metadata only; does not bypass logins or grant media rights."""
    cache_key = 'metadata:' + url
    if cached := db.cache_get(cache_key):
        return cached
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                        'noplaylist': True, 'socket_timeout': 20, 'retries': 1}) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception:
        raise IntegrationError(f'Metadados públicos do {platform} indisponíveis sem autenticação; use outra fonte.') from None
    if not data:
        raise IntegrationError(f'Metadados públicos do {platform} indisponíveis.')
    result = {'title': str(data.get('title') or f'Vídeo de referência {platform}')[:300],
              'description': str(data.get('description') or '')[:4000],
              'source_profile': data.get('uploader'), 'metrics': {},
              'url': url, 'platform': platform, 'rights': 'REFERENCE_ONLY',
              'collected_at': time.time()}
    db.cache_set(cache_key, result, 3600)
    return result


def public_youtube_metadata(url):
    """Reference metadata; cache, Data API first, OAuth second, anonymous only if unconfigured."""
    from backend.youtube_data import configured,video_info
    from backend.public_youtube import video_id_from_url
    video_id_from_url(url)
    cached=db.cache_get('metadata:'+url)
    if cached:return cached
    if configured():
        data=video_info(url)
        date=str(data.get('upload_date') or '')
        published=(date[:4]+'-'+date[4:6]+'-'+date[6:8]+'T00:00:00Z'
                   if len(date)==8 else None)
        result={
            'title':data['title'][:300],
            'description':(data.get('description') or '')[:4000],
            'source_profile':data.get('uploader'),
            'published':published,
            'metrics':{'viewCount':data['view_count']} if data.get('view_count') is not None else {},
            'url':url,'platform':'youtube','collected_at':time.time(),
            'rights':'REFERENCE_ONLY','metadata_source':'youtube_data_api_v3'
        }
        for a,b in (('likeCount','like_count'),('commentCount','comment_count')):
            if data.get(b) is not None:result['metrics'][a]=data[b]
        db.cache_set('metadata:'+url,result,600 if data.get('is_live') else 21600)
        return result
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                        'noplaylist': True, 'socket_timeout': 20, 'retries': 1}) as ydl:
            data = ydl.extract_info(url, download=False)
    except Exception:
        raise IntegrationError('Metadados públicos do YouTube indisponíveis; tente novamente ou use RSS.') from None
    if not data or not data.get('title'):
        raise IntegrationError('Metadados públicos indisponíveis para este vídeo.')
    published = str(data.get('upload_date') or '')
    if len(published) == 8 and published.isdigit():
        published = f'{published[:4]}-{published[4:6]}-{published[6:]}T00:00:00Z'
    result = {'title': data['title'][:300], 'description': (data.get('description') or '')[:4000],
              'source_profile': data.get('uploader'), 'published': published or None,
              'metrics': {k: data[v] for k, v in [('viewCount','view_count'),('likeCount','like_count'),
                          ('commentCount','comment_count')] if isinstance(data.get(v), int)},
              'url': url, 'platform': 'youtube', 'collected_at': time.time(), 'rights': 'REFERENCE_ONLY'}
    db.cache_set('metadata:' + url, result, 3600)
    return result


# YouTube introduced a dedicated Shorts search type in 2026. This is NOT
# the old duration filter (which also includes ordinary short videos).
SHORTS_SEARCH_FILTER = 'EgIQCQ=='
SHORTS_MAX_SECONDS = 180  # Reject known overlong results; not the sole Shorts test.


def shorts_search_target(profile=None):
    if profile:
        if profile['platform'] != 'youtube':
            raise IntegrationError('A descoberta automática aceita apenas perfis YouTube Shorts.')
        return profile['url'].rstrip('/') + '/shorts'
    return 'https://www.youtube.com/results?' + urlencode({
        'search_query': 'GTA 6 Grand Theft Auto VI', 'sp': SHORTS_SEARCH_FILTER})


def public_youtube_discover(profile=None):
    """Discover from YouTube's dedicated Shorts search/channel tabs.

    Reference-only metadata. Never download or claim redistribution rights.
    YouTube can alter its search UI or throttle access; empty results are valid.
    """
    target = shorts_search_target(profile)
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                        'extract_flat': True, 'ignoreerrors': True, 'socket_timeout': 20,
                        'playlistend': 30, 'retries': 1}) as ydl:
            results = ydl.extract_info(target, download=False)
    except IntegrationError:
        raise
    except Exception:
        raise IntegrationError('A pesquisa de Shorts está indisponível no YouTube; tente mais tarde.') from None
    found = []
    for item in (results or {}).get('entries') or []:
        if not isinstance(item, dict):
            continue
        vid = item.get('id')
        if not isinstance(vid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            continue
        # These results come from the dedicated /shorts tab or Shorts search
        # type, not the ordinary video search. Guard against anomalous entries.
        duration = item.get('duration')
        if isinstance(duration, (int, float)) and (duration <= 0 or duration > SHORTS_MAX_SECONDS):
            continue
        paths = [str(item.get(key) or '') for key in ('url', 'webpage_url', 'original_url')]
        if any('/watch?' in path or '/live/' in path for path in paths):
            # A watch URL alone is not a proof of Shorts, so never accept it.
            if not any('/shorts/' in path for path in paths):
                continue
        title = str(item.get('title') or '')[:300]
        description = str(item.get('description') or '')[:4000]
        if not re.search(r'gta\s*(6|vi)|grand theft auto', title + ' ' + description, re.I):
            continue
        url = f'https://www.youtube.com/shorts/{vid}'
        meta = {'url': url, 'platform': 'youtube', 'format': 'shorts',
                'title': title, 'description': description,
                'source_profile': item.get('uploader'), 'published': None,
                'duration': duration, 'metrics': {}, 'rights': 'REFERENCE_ONLY',
                'shorts_discovery': 'channel_shorts_tab' if profile else 'youtube_shorts_search_filter',
                'collected_at': time.time()}
        db.execute("""INSERT INTO opportunities VALUES (:id,:url,'youtube',:title,:metadata,:score,:now,:profile)
            ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata,score=excluded.score""",
            {'id': db.uid(), 'url': url, 'title': title, 'metadata': json.dumps(meta,ensure_ascii=False),
             'score': None, 'now': time.time(), 'profile': profile['id'] if profile else None})
        found.append(url)
    return found


def viral_score(meta):
    metrics = meta.get('metrics', {})
    views = metrics.get('viewCount')
    if views is None:
        return None
    try:
        age = max(1, (datetime.now(timezone.utc) - datetime.fromisoformat(meta['published'].replace('Z', '+00:00'))).total_seconds() / 3600)
    except (KeyError, ValueError, TypeError):
        return None
    velocity = views / age
    engagement = (metrics.get('likeCount', 0) + metrics.get('commentCount', 0) * 2) / max(1, views)
    return round(min(10, math.log10(1 + velocity) * 1.5 + min(2, engagement * 30) + max(0, 2 - age / 168)), 2)


def public_youtube_videos(profile=None):
    """Public YouTube *video* search as supplemental source (Shorts have priority).

    Search metadata only. Neither a successful search nor a license tag grants
    download/reuse permissions for gameplay.
    """
    if profile and profile['platform'] != 'youtube':
        raise IntegrationError('Consulta pública de vídeos disponível para perfis YouTube.')
    target = (profile['url'].rstrip('/') + '/videos') if profile else 'ytsearch:GTA 6 gameplay trailer curiosidades Rockstar sort=upload_date'
    try:
        from yt_dlp import YoutubeDL
        with YoutubeDL({'quiet': True, 'no_warnings': True, 'skip_download': True,
                        'extract_flat': True, 'ignoreerrors': True, 'socket_timeout': 20,
                        'playlistend': 35, 'retries': 1}) as ydl:
            results = ydl.extract_info(target, download=False)
    except Exception:
        raise IntegrationError('Busca pública de vídeos do YouTube indisponível.') from None
    found=[]
    for item in (results or {}).get('entries') or []:
        if not isinstance(item, dict):
            continue
        vid=item.get('id')
        if not isinstance(vid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', vid):
            continue
        if any('/shorts/' in str(item.get(k) or '') for k in ('url','webpage_url','original_url')):
            continue  # Managed by the high-priority Shorts scanner.
        title=str(item.get('title') or '')[:300]
        description=str(item.get('description') or '')[:4000]
        if not re.search(r'gta\s*(6|vi)|grand theft auto',title+' '+description,re.I):
            continue
        url='https://www.youtube.com/watch?v='+vid
        meta={'url':url,'platform':'youtube','format':'video','title':title,'description':description,
              'source_profile':item.get('uploader'), 'duration':item.get('duration'),
              'published':None,'metrics':{},'rights':'REFERENCE_ONLY',
              'discovery':'public_youtube_videos','collected_at':time.time()}
        db.execute("""INSERT INTO opportunities VALUES (:id,:url,'youtube',:title,:meta,NULL,:now,:profile)
            ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata, title=excluded.title""",
            {'id':db.uid(),'url':url,'title':title,'meta':json.dumps(meta,ensure_ascii=False),
             'now':time.time(),'profile':profile['id'] if profile else None})
        found.append(url)
    return found


def discover(profile=None):
    """All available source families; prefer YouTube Shorts, then full videos.

    Connected Instagram/TikTok monitoring requires official access to the user's
    own account. News feeds run independently via source jobs, not this function.
    """
    if profile and profile['platform'] in ('instagram','tiktok'):
        from backend.sources import connected_profile
        return [v['url'] for v in connected_profile(profile)]
    found=[]
    errors=[]
    for adapter in (public_youtube_discover,public_youtube_videos):
        try:
            found.extend(adapter(profile))
        except IntegrationError as exc:
            errors.append(str(exc))
    if errors:
        db.log_event(None,'cacador','WARN', ' | '.join(errors)[:580])
    if not found and errors:
        raise IntegrationError('Consultas YouTube indisponíveis. Fontes RSS continuam independentes.')
    return list(dict.fromkeys(found))


def download_authorized(video):
    if video['rights'] != 'AUTHORIZED' or not video['evidence']:
        raise IntegrationError('Download bloqueado: autorização ausente.')
    destination = db.ROOT / 'videos/raw' / f"{video['id']}.mp4"
    if destination.exists():
        return destination
    args = [sys.executable, '-m', 'yt_dlp', '--no-playlist', '--no-warnings', '--no-progress',
            '--max-filesize', '250M', '--socket-timeout', '20', '--retries', '2',
            '--match-filter', 'duration <= 600', '-f', 'best[ext=mp4]/best',
            '-o', str(destination), '--', video['url'].split('#studio-variant=')[0]]
    result = subprocess.run(args, capture_output=True, timeout=180)
    if result.returncode or not destination.exists():
        raise IntegrationError('Download autorizado indisponível; verifique acesso e requisitos da plataforma.')
    return destination


def llm(agent, video_id, payload, output_schema, images=None):
    config = db.settings()
    route = config.routes.get(agent)
    if not route or not route.model:
        raise IntegrationError(f'Configure o modelo do agente {agent}.')
    system = (db.Path(__file__).resolve().parent.parent / 'agents' / agent / 'system.md').read_text('utf-8')
    prompt = json.dumps({'input': payload, 'output_json_schema': output_schema}, ensure_ascii=False)
    # Estimate input tokens from characters rather than treating every character
    # as a token. Reserve atomically to keep concurrent workers under the cap.
    # Reconcile against provider-reported usage whenever available.
    estimated_input = math.ceil((len(prompt) + len(system)) / 4) + len(images or []) * 1500
    reservation = estimated_input + route.max_tokens
    cost = reservation * config.cost_per_million / 1_000_000
    day = db.today()

    def reserve():
        with db.transaction() as c:
            usage = c.execute(text('SELECT * FROM usage WHERE day=:day'), {'day': day}).mappings().first()
            used_tokens = usage['tokens'] if usage else 0
            used_cost = usage['cost'] if usage else 0
            if used_tokens + reservation > config.daily_tokens or used_cost + cost > config.daily_cost_usd:
                raise IntegrationError(
                    f'Orçamento diário interno do Studio atingido: {used_tokens} tokens contabilizados '
                    f'de {config.daily_tokens} permitidos. Ajuste em Configurações > Tokens por dia; '
                    'isso não altera as quotas reais do OmniRoute.')
            c.execute(text('INSERT INTO usage VALUES (:day,:tokens,:cost) ON CONFLICT(day) '
                           'DO UPDATE SET tokens=tokens+:tokens,cost=cost+:cost'),
                      dict(day=day, tokens=reservation, cost=cost))

    def reconcile(actual_tokens):
        # Keep reservation when provider omits usage; only refund when certain.
        if actual_tokens is None:
            return
        actual_tokens = max(0, int(actual_tokens))
        actual_cost = actual_tokens * config.cost_per_million / 1_000_000
        with db.transaction() as c:
            c.execute(text('UPDATE usage SET tokens=MAX(0,tokens+:delta), '
                           'cost=MAX(0,cost+:cost_delta) WHERE day=:day'),
                      {'delta': actual_tokens-reservation, 'cost_delta': actual_cost-cost, 'day': day})
    headers = {'Authorization': 'Bearer ' + (db.secret('llm_api_key') or 'ollama')}
    # Stateless request: no shared conversation or filesystem tools.
    errors=[]
    models=list(dict.fromkeys([m for m in (route.model,route.fallback_model) if m]))
    for model in models:
        for retry in range(2):
            content = prompt
            if images:
                if not route.vision:
                    raise IntegrationError('Modelo do agente não está habilitado para visão.')
                content = [{'type': 'text', 'text': prompt}] + [{'type': 'image_url', 'image_url': {
                    'url': 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode(), 'detail': 'low'}} for path in images]
            reserve()
            try:
                response = request('POST', config.provider_url + '/chat/completions', headers=headers, json={
                    'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                    'max_tokens': route.max_tokens, 'temperature': .3, 'response_format': {'type': 'json_object'}}).json()
                raw = response['choices'][0]['message']['content']
                if isinstance(raw,str):
                    cleaned=raw.strip()
                    if cleaned.startswith('```'):
                        cleaned=re.sub(r'^```(?:json)?\s*|\s*```$', '', cleaned, flags=re.IGNORECASE).strip()
                    try:
                        result=json.loads(cleaned)
                    except json.JSONDecodeError:
                        # Extract just the first JSON object when the provider wraps it in prose.
                        start=cleaned.find('{')
                        if start<0:
                            raise ValueError('Resposta sem objeto JSON') from None
                        result,_=json.JSONDecoder().raw_decode(cleaned[start:])
                else:
                    result=raw
                if not isinstance(result,dict) or not result:
                    raise ValueError('Resposta do modelo não contém um objeto JSON válido')
                missing=[key for key in output_schema.get('required',[]) if key not in result]
                if missing:
                    raise ValueError('JSON sem campos obrigatórios: '+', '.join(missing[:5]))
                used=response.get('usage',{}).get('total_tokens')
                reconcile(used if isinstance(used,int) and used>=0 else None)
                db.log_event(video_id,agent,'MODEL',
                             'Resposta estruturada recebida; consumo conciliado quando informado.',used or 0)
                return result
            except IntegrationError as exc:
                message=str(exc)
                # Upstream HTTP rejection means no generation; refund this reservation.
                if any(message.startswith(f'Integração respondeu HTTP {status}')
                       for status in (400,401,403,404,408,409,422,425,429,500,502,503,504)) or 'timeout' in message.lower():
                    reconcile(0)
                errors.append(f'{model}: {message[:145]}')
                transient=('timeout' in message.lower() or 'Falha de rede' in message or
                           any(message.startswith(f'Integração respondeu HTTP {status}')
                               for status in (408,425,429,500,502,503,504)))
                # Prefer the configured fallback immediately on a throttled main model.
                if not transient or retry or (model==route.model and route.fallback_model and route.fallback_model!=model):
                    break
            except (ValueError, KeyError, IndexError, TypeError, AttributeError) as exc:
                # Provider may report HTTP 200 with empty or malformed JSON.
                # Unknown token usage is deliberately not refunded.
                errors.append(f'{model}: {type(exc).__name__} - {str(exc)[:120]}')
                if retry:
                    break
            if retry==0:
                time.sleep(1)
    reason='; '.join(errors[-4:])[:540]
    db.log_event(video_id,agent,'MODEL_ERROR',reason)
    raise IntegrationError(
        f'Falha do modelo de {agent}; resposta indisponível ou inválida. '
        f'Últimas causas: {reason or "nenhuma resposta válida"}')


def youtube_token():
    refresh = db.secret('youtube_refresh_token')
    if refresh:
        return request('POST', 'https://oauth2.googleapis.com/token', data={
            'client_id': db.secret('youtube_client_id'), 'client_secret': db.secret('youtube_client_secret'),
            'refresh_token': refresh, 'grant_type': 'refresh_token'}).json()['access_token']
    token = db.secret('youtube_access_token')
    if not token:
        raise IntegrationError('YouTube requer autenticação OAuth com escopo youtube.upload.')
    return token


def youtube_upload(path, script):
    token = youtube_token()
    response = request('POST', 'https://www.googleapis.com/upload/youtube/v3/videos',
        params={'uploadType': 'resumable', 'part': 'snippet,status'},
        headers={'Authorization': 'Bearer ' + token, 'X-Upload-Content-Type': 'video/mp4',
                 'X-Upload-Content-Length': str(path.stat().st_size)},
        json={'snippet': {'title': script['title'], 'description': script['description'], 'tags': script['hashtags'], 'categoryId': '20'},
              'status': {'privacyStatus': 'private', 'selfDeclaredMadeForKids': False}})
    location = response.headers.get('location', '')
    u = urlsplit(location)
    if u.scheme != 'https' or u.hostname not in ('www.googleapis.com', 'youtube.googleapis.com'):
        raise IntegrationError('URL de upload retornada não reconhecida.')
    with path.open('rb') as stream:
        result = request('PUT', location, headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'video/mp4'}, content=stream).json()
    if not result.get('id'):
        raise IntegrationError('Plataforma não confirmou ID do vídeo. Reconciliar manualmente.')
    return result['id'], 'https://www.youtube.com/watch?v=' + result['id']


def collect_metrics(force: bool=False):
    """Observe real YouTube statistics; report why each link lacks metrics.

    No invented values, and no automatic statistics for platforms without
    a supported authenticated collector. The hourly cache limits API usage.
    """
    from backend.contracts import platform_url
    from backend.youtube_data import configured
    summary={'observed':0,'unavailable':0,'cached':0,'invalid':0}
    publications=db.rows("""SELECT * FROM publications
                        WHERE status='PUBLICADO' AND platform='youtube'""")
    for pub in publications:
        if not force and db.cache_get('metrics:'+pub['id']):
            summary['cached']+=1
            continue
        url=(pub.get('url') or '').strip()
        if not url and re.fullmatch(r'[A-Za-z0-9_-]{11}',str(pub.get('external_id') or '')):
            url='https://www.youtube.com/watch?v='+pub['external_id']
        try:
            platform,url=platform_url(url)
            if platform!='youtube':
                raise ValueError('link não pertence ao YouTube')
        except ValueError:
            summary['invalid']+=1
            db.put_setting('metrics_check:'+pub['id'],{
                'status':'invalid_url','reason':'URL publicada ausente ou inválida.',
                'checked_at':time.time()})
            continue
        try:
            # Discovery metadata can be cached for six hours. Published
            # engagement needs an independent fresh observation.
            db.execute('DELETE FROM cache WHERE key=:key',{'key':'metadata:'+url})
            result=public_youtube_metadata(url)
            counts=result.get('metrics') or {}
            if counts.get('viewCount') is None:
                raise IntegrationError('O YouTube não retornou contagens públicas para este vídeo.')
            data={'views':int(counts['viewCount']),
                  'likes':int(counts['likeCount']) if counts.get('likeCount') is not None else None,
                  'comments':int(counts['commentCount']) if counts.get('commentCount') is not None else None,
                  'shares':None,'retention':None,'ctr':None,
                  'average_watch_seconds':None,'follower_growth':None}
            db.execute('INSERT INTO metrics VALUES (:id,:pub,:now,:data)',
                       dict(id=db.uid(),pub=pub['id'],now=time.time(),data=json.dumps(data)))
            db.cache_set('metrics:'+pub['id'],True,3600)
            db.put_setting('metrics_check:'+pub['id'],{
                'status':'observed','reason':'Métricas públicas consultadas com sucesso.',
                'checked_at':time.time(),'source':result.get('metadata_source','public')})
            summary['observed']+=1
        except (IntegrationError,ValueError,TypeError) as exc:
            summary['unavailable']+=1
            # Never expose API keys or HTTP URLs in a persisted error message.
            reason=('API configurada: verifique a chave, cota ou visibilidade do vídeo.'
                    if configured() else
                    'Estatísticas públicas indisponíveis; conecte a API YouTube Data v3.')
            db.put_setting('metrics_check:'+pub['id'],{
                'status':'unavailable','reason':reason,
                'checked_at':time.time()})
    db.put_setting('last_metrics_collection',{'at':time.time(),**summary})
    return summary
