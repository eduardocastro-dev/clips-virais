"""Live clips are eligible by broadcast completion date, not video upload date."""
from __future__ import annotations

import json
from datetime import datetime,timedelta,timezone

import pytest

from backend import core as db,live_cuts,viral_radar20,youtube_data
from backend import public_youtube as py

CHANNEL='UC'+'Q'*22
TODAY=datetime(2026,11,20,18,0,tzinfo=timezone.utc)


def _api_video(*,ident='AAAA1234xyz',end=None,started=None,
               published=None,broadcast='none',duration='PT2H',
               privacy='public',age_restricted=False):
    published=published or TODAY-timedelta(days=40)
    stream={}
    if started:stream['actualStartTime']=started.isoformat()
    if end:stream['actualEndTime']=end.isoformat()
    return {'id':ident,
        'snippet':{'title':'Live GTA VI - evento recente','channelId':CHANNEL,
                   'publishedAt':published.isoformat(),
                   'liveBroadcastContent':broadcast},
        'status':{'privacyStatus':privacy},
        'contentDetails':{'duration':duration,
                          'contentRating':{'ytRating':'ytAgeRestricted'} if age_restricted else {}},
        'liveStreamingDetails':stream}


def test_yesterday_ended_stream_is_recent_even_if_scheduled_forty_days_ago():
    end=TODAY-timedelta(days=1)
    data=youtube_data._metadata(_api_video(end=end,started=end-timedelta(hours=2)))
    assert data['live_status']=='was_live'
    assert not py.public_recent_video(data,days=30,now=TODAY)
    assert py.live_ended_at(data)==end
    assert py.public_ended_live(data,days=30,now=TODAY)
    assert py.live_hype_recency_score(data,days=30,now=TODAY)>=95


def test_completed_replay_without_explicit_end_uses_start_and_archive_duration():
    end=TODAY-timedelta(hours=16)
    data=youtube_data._metadata(_api_video(end=None,started=end-timedelta(hours=2)))
    assert data['live_status']=='was_live'
    assert py.live_ended_at(data)==end
    assert py.public_ended_live(data,now=TODAY)


@pytest.mark.parametrize('raw,detail',[
    (_api_video(end=TODAY-timedelta(hours=5),broadcast='live'),''),
    (_api_video(started=TODAY+timedelta(days=1),broadcast='upcoming',duration='PT0S'),
     'replay'),
    (_api_video(end=TODAY-timedelta(days=31)),'30 dias'),
    (_api_video(end=TODAY+timedelta(hours=1)),'futuro'),
    (_api_video(end=TODAY-timedelta(days=1),privacy='unlisted'),'público'),
    (_api_video(end=TODAY-timedelta(days=1),privacy='private'),'público'),
    (_api_video(end=TODAY-timedelta(days=1),age_restricted=True),'restrição'),
    (_api_video(end=TODAY-timedelta(days=1),duration='PT0S'),'duração'),
    (_api_video(published=TODAY-timedelta(hours=6)),'transmissão encerrada'),
])
def test_reject_ineligible_livestreams(raw,detail):
    data=youtube_data._metadata(raw)
    if detail:
        assert not py.public_ended_live(data,now=TODAY)
        assert detail in py.live_rejection_reason(data,now=TODAY)


def test_actively_streaming_or_processing_vod_is_never_accepted():
    active=youtube_data._metadata(_api_video(
        started=TODAY-timedelta(minutes=30),broadcast='live',duration='PT0S'))
    assert active['live_status']=='is_live'
    assert not py.public_ended_live(active,now=TODAY)
    assert 'andamento' in py.live_rejection_reason(active,now=TODAY)
    processing={'availability':'public','live_status':'post_live',
                'is_live':False,'duration':7200,
                'liveStreamingDetails':{'actualEndTime':TODAY.isoformat()}}
    assert not py.public_ended_live(processing,now=TODAY)


def test_recent_vod_metadata_refreshes_cached_youtube_status(monkeypatch):
    calls=[]
    live= youtube_data._metadata(_api_video(
        started=TODAY-timedelta(hours=25),
        end=TODAY-timedelta(hours=23)))
    stale={**live,'live_status':'is_live','is_live':True,
           'liveStreamingDetails':{}}
    def fetch(url,**kwargs):
        calls.append(kwargs.get('fresh',False))
        return live if kwargs.get('fresh') else stale
    monkeypatch.setattr(live_cuts,'public_video_info',fetch)
    monkeypatch.setattr(youtube_data,'configured',lambda:True)
    assert live_cuts._recent_vod_metadata('AAAA1234xyz')==live
    assert calls==[False,True]


def test_submit_recent_stream_with_old_upload_and_scoped_rights(monkeypatch):
    end=datetime.now(timezone.utc)-timedelta(hours=19)
    info=youtube_data._metadata(_api_video(
        started=end-timedelta(hours=2),end=end))
    monkeypatch.setattr(live_cuts,'public_video_info',lambda url:info)
    from backend import daily_quota
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    link='https://www.youtube.com/live/AAAA1234xyz'
    result=live_cuts.submit_live_url(
        link,'Autorização registrada para cortar e republicar esta live.')
    assert result['queued'] and result['expected_cuts']==3
    assert db.rows('SELECT status FROM live_clips')[0]['status']=='QUEUED'
    assert db.rows("SELECT kind FROM jobs WHERE kind LIKE 'live_cut:%'")


def test_recent_lives_auto_queue_prefers_fresh_broadcast_end(monkeypatch):
    channel=CHANNEL
    live_cuts.allow_creator(channel,'Autorização para cortes de todas as lives do canal.')
    start=datetime.now(timezone.utc)
    fresh=(start-timedelta(hours=12)).isoformat()
    older=(start-timedelta(days=9)).isoformat()
    old_upload=(start-timedelta(days=55)).isoformat()
    live_cuts._write('recent_lives.json',{'items':[
        {'id':'ABCD1234old','url':'https://www.youtube.com/watch?v=ABCD1234old',
         'title':'GTA VI review longo antigo','channel_id':channel,
         'published_at':(start-timedelta(days=10)).isoformat(),
         'ended_at':older,'score':99,'ended':True},
        {'id':'ABCD1234new','url':'https://www.youtube.com/watch?v=ABCD1234new',
         'title':'GTA VI detalhes da live atual','channel_id':channel,
         'published_at':old_upload,'ended_at':fresh,'score':55,'ended':True}
    ]})
    from backend import daily_quota
    import importlib.util
    monkeypatch.setattr(importlib.util,'find_spec',lambda x:object())
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    monkeypatch.setattr(live_cuts,'verified_live',lambda entry:{'id':entry['id']})
    settings=db.settings()
    settings.automatic=True
    db.put_setting('settings',settings.model_dump())
    queued=live_cuts.enqueue_next()
    assert queued['queued']
    assert db.rows('SELECT video_id FROM live_clips')[0]['video_id']=='ABCD1234new'
    # Never enqueue the same VOD twice, even after seven-day dedup expiry.
    queued_again=live_cuts.enqueue_next()
    assert queued_again['queued'] is False


def test_radar_retains_stream_that_was_uploaded_before_thirty_day_window(monkeypatch):
    end=datetime.now(timezone.utc)-timedelta(hours=9)
    raw=_api_video(started=end-timedelta(hours=2),end=end)
    info=youtube_data._metadata(raw)
    monkeypatch.setattr(viral_radar20,'stored_top_creators',lambda:{
        'channels':[{'channel_id':CHANNEL,'name':'Criador autorizado'}]})
    monkeypatch.setattr(viral_radar20,'public_channel_entries',
        lambda channel,tab,limit=5:[{'id':'AAAA1234xyz','title':'Live GTA VI - evento recente'}] if tab=='streams' else [])
    monkeypatch.setattr(viral_radar20,'public_video_info',lambda url:info)
    result=viral_radar20.scan_recent()
    assert len(result['recent_lives'])==1
    vod=result['recent_lives'][0]
    assert vod['ended_at']==end.isoformat()
    assert vod['hype_recency_score']>90
    assert vod['hype_basis']=='freshness_heuristic'


def _fallback_metadata(*,end_hours_ago=20,**changes):
    start=datetime.now(timezone.utc)-timedelta(hours=end_hours_ago+2)
    result={
        'id':'AAAA1234xyz','channel_id':CHANNEL,'title':'Live GTA VI encerrada ontem',
        'availability':'public','live_status':'was_live','is_live':False,
        'age_limit':0,'duration':7200,'release_timestamp':start.timestamp(),
        'timestamp':start.timestamp(),'upload_date':start.strftime('%Y%m%d'),
    }
    result.update(changes)
    return result


def _api_without_live_fields():
    raw=_api_video(published=datetime.now(timezone.utc)-timedelta(days=40))
    return youtube_data._metadata(raw)


def test_yt_dlp_fallback_accepts_yesterday_replay_without_api_live_fields(monkeypatch):
    from backend import public_youtube
    primary=_api_without_live_fields()
    assert primary['live_status']=='not_live'
    assert not py.public_ended_live(primary)
    calls=[]
    monkeypatch.setattr(live_cuts,'public_video_info',
                        lambda url,**kwargs:primary)
    monkeypatch.setattr(youtube_data,'configured',lambda:True)
    def extract(url):
        calls.append(url)
        return _fallback_metadata()
    monkeypatch.setattr(public_youtube,'_extract',extract)
    info=live_cuts._recent_vod_metadata('AAAA1234xyz')
    assert calls==['https://www.youtube.com/watch?v=AAAA1234xyz']
    assert info['live_status']=='was_live'
    assert info['metadata_source']=='youtube_data_api_v3+yt_dlp_public_replay'
    assert py.public_ended_live(info)
    assert 0<(datetime.now(timezone.utc)-py.live_ended_at(info)).total_seconds()<86400
    assert 'actualEndTime' not in info['liveStreamingDetails']


@pytest.mark.parametrize('changes', [
    {'channel_id':'UC'+'B'*22},
    {'id':'BBBB1234xyz'},
    {'availability':'unlisted'},
    {'live_status':'is_live'},
    {'is_live':True},
    {'age_limit':18},
    {'duration':0},
    {'release_timestamp':(datetime.now(timezone.utc)-timedelta(days=40)).timestamp()},
])
def test_ytdlp_fallback_rejects_mismatched_private_active_old_or_incomplete_vod(
        changes):
    primary=_api_without_live_fields()
    alternative=_fallback_metadata(**changes)
    from backend import public_youtube
    from unittest.mock import patch
    with patch.object(public_youtube,'_extract',return_value=alternative):
        assert live_cuts._yt_dlp_finished_fallback('AAAA1234xyz',primary) is None


def test_fallback_cannot_override_api_active_live_or_private_vod():
    from backend import public_youtube
    from unittest.mock import patch
    primary=_api_without_live_fields()
    calls=[]
    def extract(url):
        calls.append(url)
        return _fallback_metadata()
    with patch.object(public_youtube,'_extract',side_effect=extract):
        assert live_cuts._yt_dlp_finished_fallback('AAAA1234xyz',
                   {**primary,'live_status':'is_live','is_live':True}) is None
        assert live_cuts._yt_dlp_finished_fallback('AAAA1234xyz',
                   {**primary,'availability':'private'}) is None
    assert calls==[]


def test_fallback_network_error_does_not_fake_live_end():
    from backend import public_youtube
    from backend.integrations import IntegrationError
    from unittest.mock import patch
    primary=_api_without_live_fields()
    with patch.object(public_youtube,'_extract',
                      side_effect=IntegrationError('YouTube indisponível')):
        assert live_cuts._yt_dlp_finished_fallback('AAAA1234xyz',primary) is None


def test_submit_yesterday_live_using_independent_vod_confirmation(
        monkeypatch):
    from backend import daily_quota,public_youtube
    primary=_api_without_live_fields()
    monkeypatch.setattr(live_cuts,'public_video_info',
                        lambda url,**kwargs:primary)
    monkeypatch.setattr(youtube_data,'configured',lambda:True)
    monkeypatch.setattr(public_youtube,'_extract',
                        lambda url:_fallback_metadata())
    monkeypatch.setattr(daily_quota,'within_deadline',
                        lambda *args,**kwargs:True)
    outcome=live_cuts.submit_live_url(
        'https://www.youtube.com/live/AAAA1234xyz',
        'Permissão do proprietário para reutilizar e publicar os cortes desta live.')
    assert outcome['queued'] and outcome['expected_cuts']==3
    assert db.rows('SELECT status FROM live_clips')[0]['status']=='QUEUED'
    assert db.rows('SELECT kind FROM jobs WHERE kind LIKE :prefix',
                   {'prefix':'live_cut:%'})


def test_release_timestamp_plus_vod_duration_approximates_end_not_start():
    start=TODAY-timedelta(days=3)
    info={'live_status':'was_live','duration':10800,
          'release_timestamp':start.timestamp()}
    assert py.live_ended_at(info)==start+timedelta(hours=3)
