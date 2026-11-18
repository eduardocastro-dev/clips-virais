"""Network adapters. Every remote result is evidence, never a claimed success."""
import json
import base64
import math
import subprocess
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qs
import httpx
from sqlalchemy import text
from backend import core as db


class IntegrationError(RuntimeError):
    pass


def request(method, url, **kwargs):
    # Do not propagate exception URLs: provider query parameters can contain secrets.
    try:
        with httpx.Client(timeout=40, follow_redirects=False) as client:
            response = client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise IntegrationError(f'Integração respondeu HTTP {response.status_code}.')
        if response.is_redirect:
            raise IntegrationError('Redirecionamento inesperado na integração.')
        return response
    except httpx.HTTPError:
        raise IntegrationError('Falha de rede ou timeout na integração.') from None


def youtube_get(resource, params):
    key = db.secret('youtube_api_key')
    if not key:
        raise IntegrationError('Configure YouTube Data API key para pesquisa e metadados.')
    return request('GET', f'https://www.googleapis.com/youtube/v3/{resource}', params={**params, 'key': key}).json()


def youtube_metadata(url):
    key = 'metadata:' + url
    if cached := db.cache_get(key):
        return cached
    vid = parse_qs(urlsplit(url).query)['v'][0]
    items = youtube_get('videos', {'part': 'snippet,statistics,contentDetails,status', 'id': vid}).get('items', [])
    if not items:
        raise IntegrationError('Vídeo não encontrado ou não acessível pela API.')
    v = items[0]
    sn = v['snippet']
    result = {'title': sn['title'], 'description': sn.get('description', '')[:4000], 'source_profile': sn.get('channelTitle'),
              'published': sn.get('publishedAt'), 'metrics': {k: int(n) for k, n in v.get('statistics', {}).items()},
              'duration_iso': v.get('contentDetails', {}).get('duration'), 'license': v.get('status', {}).get('license'),
              'url': url, 'platform': 'youtube', 'collected_at': time.time()}
    db.cache_set(key, result)
    return result


def metadata(url, platform):
    url=url.split('#studio-variant=')[0]
    if platform == 'youtube':
        return youtube_metadata(url)
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


def discover(profile=None):
    params = {'part': 'snippet', 'type': 'video', 'maxResults': 10, 'order': 'date', 'q': 'GTA 6'}
    if profile:
        if profile['platform'] != 'youtube':
            from backend.sources import connected_profile
            return [x['url'] for x in connected_profile(profile)]
        path = urlsplit(profile['url']).path
        if path.startswith('/channel/'):
            params['channelId'] = path.split('/')[-1]
        else:
            found = youtube_get('channels', {'part': 'id', 'forHandle': path.strip('/')}).get('items', [])
            if not found:
                raise IntegrationError('Canal não encontrado.')
            params['channelId'] = found[0]['id']
        params.pop('q')
    else:
        countries = db.settings().countries
        params['regionCode'] = countries[int(time.time() // 3600) % len(countries)] if countries else 'US'
    cache_key = 'search:' + json.dumps(params, sort_keys=True)
    data = db.cache_get(cache_key)
    if data is None:
        data = youtube_get('search', params)
        db.cache_set(cache_key, data, 1800)
    found = []
    for item in data.get('items', []):
        vid = item.get('id', {}).get('videoId')
        if not vid:
            continue
        url = 'https://www.youtube.com/watch?v=' + vid
        meta = youtube_metadata(url)
        if 'gta' not in (meta['title'] + meta['description']).lower():
            continue
        score = viral_score(meta)
        db.execute('''INSERT INTO opportunities VALUES (:id,:url,'youtube',:title,:metadata,:score,:now,:profile)
            ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata, score=excluded.score''',
            dict(id=db.uid(), url=url, title=meta['title'], metadata=json.dumps(meta), score=score,
                 now=time.time(), profile=profile['id'] if profile else None))
        found.append(url)
    return found


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
    # Reserve the upper bound before the call. Failed requests retain their reservation.
    reservation = len(prompt) + len(system) + route.max_tokens + len(images or []) * 1500
    cost = reservation * config.cost_per_million / 1_000_000
    def reserve():
        with db.transaction() as c:
            usage = c.execute(text('SELECT * FROM usage WHERE day=:day'), {'day': db.today()}).mappings().first()
            if usage and (usage['tokens'] + reservation > config.daily_tokens or usage['cost'] + cost > config.daily_cost_usd):
                raise IntegrationError('Orçamento diário de IA atingido.')
            if reservation > config.daily_tokens or cost > config.daily_cost_usd:
                raise IntegrationError('Requisição excede orçamento diário de IA.')
            c.execute(text('INSERT INTO usage VALUES (:day,:tokens,:cost) ON CONFLICT(day) DO UPDATE SET tokens=tokens+:tokens,cost=cost+:cost'),
                      dict(day=db.today(), tokens=reservation, cost=cost))
    headers = {'Authorization': 'Bearer ' + (db.secret('llm_api_key') or 'ollama')}
    # Stateless request: no shared conversation or filesystem tools.
    last = None
    for model in dict.fromkeys([route.model, route.fallback_model]):
        if not model:
            continue
        reserve()
        content = prompt
        if images:
            if not route.vision:
                raise IntegrationError('Modelo do Avaliador não está habilitado para visão.')
            content = [{'type': 'text', 'text': prompt}] + [{'type': 'image_url', 'image_url': {
                'url': 'data:image/jpeg;base64,' + base64.b64encode(path.read_bytes()).decode(), 'detail': 'low'}} for path in images]
        try:
            r = request('POST', config.provider_url + '/chat/completions', headers=headers, json={
                'model': model, 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
                'max_tokens': route.max_tokens, 'temperature': .3, 'response_format': {'type': 'json_object'}}).json()
            result = json.loads(r['choices'][0]['message']['content'])
            used = r.get('usage', {}).get('total_tokens')
            db.log_event(video_id, agent, 'MODEL', 'Resposta estruturada recebida; reserva conservadora de orçamento.', used or 0)
            return result
        except (IntegrationError, ValueError, KeyError, IndexError) as exc:
            last = exc
    raise IntegrationError(f'Falha do modelo de {agent}; resposta indisponível ou inválida.') from last


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


def collect_metrics():
    for pub in db.rows("SELECT * FROM publications WHERE status='PUBLICADO' AND platform='youtube' AND (provider IS NULL OR provider!='postiz')"):
        if db.cache_get('metrics:' + pub['id']):
            continue
        try:
            items = youtube_get('videos', {'part': 'statistics', 'id': pub['external_id']}).get('items', [])
            if not items:
                continue
            stats = items[0].get('statistics', {})
            data = {key: int(stats[remote]) if remote in stats else None for key, remote in
                    [('views', 'viewCount'), ('likes', 'likeCount'), ('comments', 'commentCount')]}
            data.update(shares=None, retention=None, ctr=None, average_watch_seconds=None, follower_growth=None)
            db.execute('INSERT INTO metrics VALUES (:id,:pub,:now,:data)', dict(id=db.uid(), pub=pub['id'], now=time.time(), data=json.dumps(data)))
            db.cache_set('metrics:' + pub['id'], True, 3600)
        except IntegrationError:
            db.notify('metrics:' + pub['id'] + ':' + db.today(), 'Métricas YouTube indisponíveis; verifique a integração.')
