"""YouTube Data API v3 reads, optional OAuth read-only and quota accounting.

Never include API keys or OAuth tokens in returned payloads or log messages.
Anonymous yt-dlp remains fallback ONLY if both integrations are unconfigured.
"""
from __future__ import annotations
import hashlib
import json
import re
import secrets
import time
from datetime import datetime,timedelta,timezone
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import httpx
from backend import core as db
from backend.integrations import IntegrationError

API="https://www.googleapis.com/youtube/v3"
TOKEN_URL="https://oauth2.googleapis.com/token"
AUTH_URL="https://accounts.google.com/o/oauth2/v2/auth"
REVOKE_URL="https://oauth2.googleapis.com/revoke"
SCOPE="https://www.googleapis.com/auth/youtube.readonly"
VID=re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL=re.compile(r"^UC[A-Za-z0-9_-]{22}$")
BASE_QUOTA=10000
RETRY_DELAYS=(5,15,45)


class YouTubeError(IntegrationError):
    def __init__(self,code,message):
        self.code=code
        super().__init__(message)


def configured():
    return bool(db.secret('youtube_api_key') or
                (db.secret('youtube_client_id') and db.secret('youtube_refresh_token')))


def pt_date():
    return datetime.now(ZoneInfo("America/Los_Angeles")).strftime('%Y-%m-%d')


def quota_state():
    day=pt_date()
    entry=db.get_setting("youtube_quota:"+day,{}) or {}
    used=int(entry.get('estimated',0))
    blocked=bool(entry.get('blocked'))
    return {'day_pacific':day,'estimated_used':used,
            'estimated_remaining':max(0,BASE_QUOTA-used),
            'daily_allocation_assumed':BASE_QUOTA,
            'warning_80pct':used>=int(.8*BASE_QUOTA),
            'blocked':blocked,
            'note':'Estimativa local de chamadas deste Studio, não é saldo oficial do Google Cloud.'}


def _count(cost=1,blocked=False):
    day=pt_date()
    key="youtube_quota:"+day
    data=db.get_setting(key,{}) or {}
    data['estimated']=max(0,int(data.get('estimated',0))+cost)
    data['blocked']=bool(data.get('blocked') or blocked)
    db.put_setting(key,data)


def _get_api(resource,params,*,key=None,token=None,retries=True):
    if resource not in ('videos','channels','playlistItems'):
        raise ValueError('Recurso da API não permitido.')
    if quota_state()['blocked']:
        raise YouTubeError('quotaExceeded',
            'A cota diária da API do YouTube acabou. Usando o cache; renova à meia-noite (horário do Pacífico).')
    if not (key or token):
        raise YouTubeError('missingCredentials','Configure a chave da API do YouTube em Configurações > Integrações.')
    args=dict(params)
    args['maxResults']=args.get('maxResults',50) if resource=='playlistItems' else None
    args={k:v for k,v in args.items() if v is not None}
    if key:args['key']=key
    headers={'Authorization':'Bearer '+token} if token else {}
    for attempt in range(4 if retries else 1):
        try:
            # Never log or interpolate full URL, params, tokens or response text.
            with httpx.Client(timeout=20,follow_redirects=False) as client:
                res=client.get(API+'/'+resource,params=args,headers=headers)
        except httpx.HTTPError:
            if retries and attempt<3:
                time.sleep(RETRY_DELAYS[attempt]);continue
            raise YouTubeError('network','Falha de conexão; use Tentar novamente.') from None
        _count()
        if res.status_code==200:
            try:return res.json()
            except ValueError:raise YouTubeError('invalidResponse','Resposta do YouTube inválida.') from None
        try:
            errors=res.json().get('error',{}).get('errors',[])
            reason=str(errors[0].get('reason') or '') if errors else ''
        except (ValueError,TypeError,AttributeError,IndexError):reason=''
        if reason in ('quotaExceeded','dailyLimitExceeded','dailyLimitExceededUnreg'):
            _count(0,blocked=True)
            raise YouTubeError('quotaExceeded','A cota diária da API do YouTube acabou. Usando o cache; renova à meia-noite (horário do Pacífico).')
        if res.status_code in (401,403) and reason not in ('rateLimitExceeded','userRateLimitExceeded','backendError'):
            raise YouTubeError('invalidKey' if key else 'oauthExpired',
              'A chave da API foi recusada. Verifique a chave e as restrições no Google Cloud.'
              if key else 'Login expirado ou acesso negado. Clique em Reconectar.')
        if res.status_code==404:
            raise YouTubeError('unavailable','Vídeo indisponível ou privado.')
        if (res.status_code in (429,500,502,503,504) or
            reason in ('rateLimitExceeded','userRateLimitExceeded','backendError')) and retries and attempt<3:
            time.sleep(RETRY_DELAYS[attempt]);continue
        raise YouTubeError('upstream','Não foi possível consultar o YouTube. Tente novamente.')
    raise YouTubeError('network','Falha de conexão; use Tentar novamente.')


def _request_tokens(form):
    try:
        with httpx.Client(timeout=20,follow_redirects=False) as client:
            response=client.post(TOKEN_URL,data=form)
        if response.status_code>=400:
            raise YouTubeError('oauthExpired','Falha ao conectar/renovar login Google; reconecte a conta.')
        data=response.json()
        if not data.get('access_token'):
            raise YouTubeError('oauthExpired','Google não retornou um token de acesso.')
        return data
    except httpx.HTTPError:
        raise YouTubeError('network','Não foi possível contatar o Google.') from None


def access_token():
    token=db.secret('youtube_access_token')
    expiry=float(db.get_setting('youtube_oauth_expires_at',0) or 0)
    if token and expiry>time.time()+60:return token
    refresh=db.secret('youtube_refresh_token')
    client_id=db.secret('youtube_client_id')
    client_secret=db.secret('youtube_client_secret')
    if not (refresh and client_id and client_secret):
        raise YouTubeError('oauthExpired','Faça login com Google em Configurações > Integrações.')
    data=_request_tokens({'client_id':client_id,'client_secret':client_secret,
                          'refresh_token':refresh,'grant_type':'refresh_token'})
    db.set_secret('youtube_access_token',data['access_token'])
    if data.get('refresh_token'):
        db.set_secret('youtube_refresh_token',data['refresh_token'])
    db.put_setting('youtube_oauth_expires_at',time.time()+int(data.get('expires_in',3600)))
    return data['access_token']


def _metadata(raw):
    snippet=raw.get('snippet') or {}
    stats=raw.get('statistics') or {}
    details=raw.get('contentDetails') or {}
    privacy=(raw.get('status') or {}).get('privacyStatus')
    rating=details.get('contentRating') or {}
    live=raw.get('liveStreamingDetails') or {}
    content_status=str(snippet.get('liveBroadcastContent') or '')
    time_string=str(snippet.get('publishedAt') or '')
    ended=bool(live.get('actualEndTime'))
    # YouTube API may not return live details for videos never streamed.
    is_streaming=content_status=='live' and not ended
    video_id=raw.get('id') or ''
    duration_str=str(details.get('duration') or '')
    duration=0
    regex=re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',duration_str)
    if regex:
        d,h,m,s=[int(x or 0) for x in regex.groups()]
        duration=d*86400+h*3600+m*60+s
    try:
        timestamp=datetime.fromisoformat(time_string.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError):timestamp=None
    # Once a broadcast ends, liveBroadcastContent returns 'none'. Occasionally
    # the API omits actualEndTime, but an actualStartTime and finished VOD
    # duration still prove this was an archived stream (not a scheduled event).
    finished_by_replay=(not ended and bool(live.get('actualStartTime')) and
                        content_status=='none' and duration>0)
    return {
        'id':video_id,'title':str(snippet.get('title') or '')[:300],
        'description':str(snippet.get('description') or '')[:4000],
        'uploader':snippet.get('channelTitle'),'channel':snippet.get('channelTitle'),
        'channel_id':snippet.get('channelId'),
        'upload_date':time_string[:10].replace('-','') if time_string else None,
        'timestamp':timestamp,'duration':duration,
        'availability':'public' if privacy=='public' else 'private' if privacy=='private' else 'unlisted' if privacy=='unlisted' else 'unknown',
        'age_limit':18 if rating.get('ytRating')=='ytAgeRestricted' else 0,
        'is_live':is_streaming,
        'live_status':'was_live' if ended or finished_by_replay else 'is_live' if is_streaming else 'not_live',
        'liveStreamingDetails':live,
        'view_count':int(stats['viewCount']) if 'viewCount' in stats else None,
        'like_count':int(stats['likeCount']) if 'likeCount' in stats else None,
        'comment_count':int(stats['commentCount']) if 'commentCount' in stats else None,
        'webpage_url':'https://www.youtube.com/watch?v='+video_id,
        'metadata_source':'youtube_data_api_v3'
    }


def video_details(video_ids,force=False):
    ids=list(dict.fromkeys(x for x in video_ids if VID.fullmatch(str(x))))
    if not ids:return {}
    found={}
    pending=[]
    for vid in ids:
        cached=None if force else db.cache_get('yt-api-video:'+vid)
        if cached is not None:found[vid]=cached
        else:pending.append(vid)
    if not pending:return found
    key=db.secret('youtube_api_key')
    use_oauth=bool(db.secret('youtube_refresh_token') and db.secret('youtube_client_id'))
    if not key and not use_oauth:
        raise YouTubeError('missingCredentials','Configure a chave da API do YouTube em Configurações > Integrações.')
    for index in range(0,len(pending),50):
        batch=pending[index:index+50]
        kwargs={'key':key} if key else {'token':access_token()}
        try:
            data=_get_api('videos',{'id':','.join(batch),
                    'part':'snippet,statistics,contentDetails,liveStreamingDetails,status',
                    'maxResults':None},**kwargs)
        except YouTubeError as exc:
            if key and use_oauth and exc.code in ('invalidKey','oauthExpired'):
                data=_get_api('videos',{'id':','.join(batch),
                    'part':'snippet,statistics,contentDetails,liveStreamingDetails,status'},
                    token=access_token())
            else:raise
        for item in data.get('items') or []:
            vid=item.get('id')
            if not VID.fullmatch(str(vid)):continue
            result=_metadata(item)
            ttl=600 if result['is_live'] else 21600
            db.cache_set('yt-api-video:'+vid,result,ttl)
            found[vid]=result
    return found


def video_info(url):
    from backend.public_youtube import video_id_from_url
    vid=video_id_from_url(url)
    if configured():
        result=video_details([vid]).get(vid)
        if not result:raise YouTubeError('unavailable','Vídeo indisponível ou privado.')
        return result
    from backend.public_youtube import _extract
    return _extract('https://www.youtube.com/watch?v='+vid)


def channel_uploads(channel_id,limit=50):
    if not CHANNEL.fullmatch(channel_id):
        raise ValueError('ID UC inválido.')
    key=db.secret('youtube_api_key')
    token=access_token() if not key else None
    info=_get_api('channels',{'part':'contentDetails','id':channel_id},key=key,token=token)
    items=info.get('items') or []
    if not items:return []
    uploads=items[0].get('contentDetails',{}).get('relatedPlaylists',{}).get('uploads')
    if not uploads:return []
    ids=[]
    cursor=None
    while len(ids)<min(200,limit):
        args={'part':'contentDetails','playlistId':uploads,
              'maxResults':min(50,limit-len(ids)),'pageToken':cursor}
        data=_get_api('playlistItems',args,key=key,token=token)
        ids.extend(x.get('contentDetails',{}).get('videoId') for x in data.get('items',[]) if x.get('contentDetails',{}).get('videoId'))
        cursor=data.get('nextPageToken')
        if not cursor:break
    details=video_details(ids)
    return [details[vid] for vid in ids if vid in details]


def oauth_state(callback_url):
    client_id=db.secret('youtube_client_id')
    client_secret=db.secret('youtube_client_secret')
    if not (client_id and client_secret):
        raise ValueError('Configure Client ID e Client Secret em Integrações.')
    allowed={'http://127.0.0.1:3000/api/youtube/oauth/callback',
             'http://localhost:3000/api/youtube/oauth/callback'}
    configured_callback=(__import__('os').environ.get('YOUTUBE_OAUTH_REDIRECT_URI') or '').strip()
    if configured_callback:allowed.add(configured_callback)
    if callback_url not in allowed:
        raise ValueError('Redirect URI não permitido; configure-o no Google Cloud.')
    state=secrets.token_urlsafe(30)
    verifier=secrets.token_urlsafe(64)
    challenge=__import__('base64').urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    db.set_secret('youtube_oauth_pending',json.dumps({
        'state':state,'verifier':verifier,'redirect_uri':callback_url,
        'expires':time.time()+600}))
    query={'response_type':'code','client_id':client_id,
           'redirect_uri':callback_url,'scope':SCOPE,
           'access_type':'offline','prompt':'consent',
           'code_challenge':challenge,'code_challenge_method':'S256',
           'state':state}
    return AUTH_URL+'?'+urlencode(query)


def oauth_complete(state,code):
    raw=db.secret('youtube_oauth_pending')
    try:pending=json.loads(raw) if raw else {}
    except ValueError:pending={}
    if (not pending or not secrets.compare_digest(str(state),str(pending.get('state'))) or
        pending.get('expires',0)<time.time()):
        raise ValueError('Sessão OAuth expirada ou inválida. Recomece em Integrações.')
    # Invalidate callback state before exchanging code, preventing replay.
    db.set_secret('youtube_oauth_pending','')
    data=_request_tokens({'code':code,'client_id':db.secret('youtube_client_id'),
                          'client_secret':db.secret('youtube_client_secret'),
                          'redirect_uri':pending['redirect_uri'],
                          'code_verifier':pending['verifier'],
                          'grant_type':'authorization_code'})
    scopes=str(data.get('scope') or '')
    if SCOPE not in scopes.split():
        raise ValueError('O Google não concedeu o escopo mínimo youtube.readonly.')
    db.set_secret('youtube_access_token',data['access_token'])
    if data.get('refresh_token'):
        db.set_secret('youtube_refresh_token',data['refresh_token'])
    db.put_setting('youtube_oauth_expires_at',time.time()+int(data.get('expires_in',3600)))
    try:
        info=_get_api('channels',{'part':'snippet','mine':'true'},
                     token=data['access_token'],retries=False)
        person=(info.get('items') or [{}])[0].get('snippet') or {}
        db.put_setting('youtube_account_label',str(person.get('title') or 'Conta Google conectada')[:150])
    except (YouTubeError,ValueError):
        db.put_setting('youtube_account_label','Conta Google conectada')
    return {'connected':True}


def oauth_disconnect():
    token=db.secret('youtube_refresh_token') or db.secret('youtube_access_token')
    if token:
        try:
            with httpx.Client(timeout=12,follow_redirects=False) as client:
                client.post(REVOKE_URL,data={'token':token})
        except httpx.HTTPError:pass
    for name in ('youtube_refresh_token','youtube_access_token','youtube_oauth_pending'):
        db.set_secret(name,'')
    db.put_setting('youtube_oauth_expires_at',0)
    db.put_setting('youtube_account_label','')
    return {'disconnected':True}


def test_key():
    if not db.secret('youtube_api_key'):
        return {'status':'NOT_CONFIGURED','message':'Configure a chave da API do YouTube.'}
    try:
        data=_get_api('videos',{'part':'snippet','id':'jNQXAC9IVRw'},
                      key=db.secret('youtube_api_key'),retries=False)
        valid=bool(data.get('items'))
        return {'status':'VALID' if valid else 'INVALID',
                'message':'Chave válida.' if valid else 'Vídeo de teste não retornado.',
                'quota':quota_state()}
    except YouTubeError as exc:
        return {'status':'QUOTA_EXCEEDED' if exc.code=='quotaExceeded' else 'INVALID',
                'message':str(exc),'quota':quota_state()}


def status():
    key=db.secret('youtube_api_key')
    refresh=db.secret('youtube_refresh_token')
    return {'key_configured':bool(key),'key_last4':key[-4:] if key else '',
            'client_configured':bool(db.secret('youtube_client_id') and db.secret('youtube_client_secret')),
            'oauth_connected':bool(refresh),
            'oauth_expires_at':db.get_setting('youtube_oauth_expires_at',0),
            'account':db.get_setting('youtube_account_label',''),
            'quota':quota_state(),
            'scope':'youtube.readonly',
            'oauth_test_warning':'Tokens de aplicativos Google em modo de teste podem expirar em 7 dias.'}
