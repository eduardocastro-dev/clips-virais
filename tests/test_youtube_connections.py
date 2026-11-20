"""No-network tests for optional YouTube API/OAuth and secure diagnostics."""
import json
import time
import pytest
from backend import core as db
from backend import youtube_data as yt
from backend.public_youtube import public_video_info


VID='jNQXAC9IVRw'
CHANNEL='UC'+'A'*22


def _fixture(private=False):
    return {'items':[{
        'id':VID,
        'snippet':{'title':'Fonte de teste','description':'Notícia pública',
                   'publishedAt':'2026-11-19T16:00:00Z',
                   'channelTitle':'Canal de teste','channelId':CHANNEL},
        'statistics':{'viewCount':'1234','likeCount':'40'},
        'contentDetails':{'duration':'PT2M32S','contentRating':{}},
        'status':{'privacyStatus':'private' if private else 'public'},
        'liveStreamingDetails':{'actualStartTime':'2026-11-19T14:00:00Z',
                                'actualEndTime':'2026-11-19T15:59:00Z'}
    }]}


def test_key_returns_no_secret_in_status_or_settings(monkeypatch):
    key='AIza-UNIT-TEST-NEVER-LOG-CLIENT-SECRET'
    db.set_secret('youtube_api_key',key)
    status=yt.status()
    assert status['key_configured']
    assert status['key_last4']==key[-4:]
    assert key not in json.dumps(status)
    stored=db.rows("SELECT value FROM kv WHERE key='secret:youtube_api_key'")[0]['value']
    assert key not in stored
    assert db.secret('youtube_api_key')==key


def test_api_videos_list_maps_video_with_vod_status_and_caches(monkeypatch):
    db.set_secret('youtube_api_key','AIza-UNIT-TEST')
    calls=[]
    def api(resource,params,**kwargs):
        calls.append((resource,params))
        return _fixture()
    monkeypatch.setattr(yt,'_get_api',api)
    v=public_video_info('https://www.youtube.com/watch?v='+VID)
    assert v['title']=='Fonte de teste'
    assert v['availability']=='public'
    assert v['live_status']=='was_live'
    assert v['duration']==152
    assert v['view_count']==1234
    assert v['channel_id']==CHANNEL
    v2=public_video_info('https://www.youtube.com/watch?v='+VID)
    assert v2==v
    assert len(calls)==1
    assert 'search' not in [x[0] for x in calls]
    assert 'status' in calls[0][1]['part']


def test_private_from_oauth_is_not_marked_public(monkeypatch):
    db.set_secret('youtube_api_key','AIza-UNIT-TEST')
    monkeypatch.setattr(yt,'_get_api',lambda *args,**kwargs:_fixture(private=True))
    v=public_video_info('https://www.youtube.com/watch?v='+VID)
    assert v['availability']=='private'


def test_invalid_key_and_quota_diagnostics_never_reflect_the_key(monkeypatch):
    key='AIza-SECRET-NEVER-EXPOSE-IN-ERROR'
    db.set_secret('youtube_api_key',key)
    monkeypatch.setattr(yt,'_get_api',lambda *args,**kwargs:
                        (_ for _ in ()).throw(yt.YouTubeError('invalidKey','A chave da API foi recusada.')))
    result=yt.test_key()
    assert result['status']=='INVALID'
    assert key not in json.dumps(result)
    monkeypatch.setattr(yt,'_get_api',lambda *args,**kwargs:
                        (_ for _ in ()).throw(yt.YouTubeError('quotaExceeded','Cota excedida.')))
    assert yt.test_key()['status']=='QUOTA_EXCEEDED'


def test_oauth_pkce_one_time_state_and_encrypted_storage(monkeypatch):
    db.set_secret('youtube_client_id','test-client-id.apps.googleusercontent.com')
    db.set_secret('youtube_client_secret','oauth-secret-never-public')
    callback='http://127.0.0.1:3000/api/youtube/oauth/callback'
    url=yt.oauth_state(callback)
    from urllib.parse import urlsplit,parse_qs
    q=parse_qs(urlsplit(url).query)
    assert q['code_challenge_method']==['S256']
    assert q['scope']==[yt.SCOPE]
    assert 'oauth-secret-never-public' not in url
    pending=json.loads(db.secret('youtube_oauth_pending'))
    assert pending['state']==q['state'][0]
    assert pending['verifier'] not in db.rows(
        "SELECT value FROM kv WHERE key='secret:youtube_oauth_pending'")[0]['value']
    with pytest.raises(ValueError):yt.oauth_complete('invalid','code')
    monkeypatch.setattr(yt,'_request_tokens',lambda form:{
        'access_token':'ephemeral_access_test','refresh_token':'refresh_test',
        'scope':yt.SCOPE,'expires_in':3600})
    monkeypatch.setattr(yt,'_get_api',lambda *args,**kwargs:{
        'items':[{'snippet':{'title':'Meu canal privado'}}]})
    out=yt.oauth_complete(pending['state'],'code')
    assert out['connected']
    assert yt.status()['oauth_connected']
    assert yt.status()['account']=='Meu canal privado'
    assert 'ephemeral_access_test' not in json.dumps(yt.status())
    with pytest.raises(ValueError):yt.oauth_complete(pending['state'],'code2')


def test_oauth_redirect_must_match_local_app():
    db.set_secret('youtube_client_id','test-client-id.apps.googleusercontent.com')
    db.set_secret('youtube_client_secret','oauth-secret-never-public')
    with pytest.raises(ValueError):
        yt.oauth_state('https://evil.example.com/api/youtube/oauth/callback')


def test_no_login_no_key_allows_anonymous_fallback(monkeypatch):
    # Credentials are absent by design; fallback must not fake API data.
    assert not yt.configured()
    from backend import public_youtube as adapter
    monkeypatch.setattr(adapter,'_extract',lambda url:{'id':VID,'title':'Anônimo'})
    assert public_video_info('https://www.youtube.com/watch?v='+VID)['title']=='Anônimo'
