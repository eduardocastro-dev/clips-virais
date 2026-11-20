"""No YouTube Data API key needed to discover, verify and enqueue approved VODs."""
from datetime import datetime, timezone, timedelta

import pytest

from backend import public_youtube, viral_radar20, live_cuts, api_radar


def test_extract_video_id_only_from_official_https_youtube_urls():
    vid='4UwvtMF9FXg'
    assert public_youtube.video_id_from_url('https://www.youtube.com/watch?v='+vid)==vid
    assert public_youtube.video_id_from_url('https://youtu.be/'+vid+'?t=15')==vid
    assert public_youtube.video_id_from_url('https://www.youtube.com/live/'+vid)==vid
    assert public_youtube.video_id_from_url('https://youtube.com/shorts/'+vid)==vid
    with pytest.raises(ValueError):
        public_youtube.video_id_from_url('https://youtube.com.evil.test/watch?v='+vid)
    with pytest.raises(ValueError):
        public_youtube.video_id_from_url('http://youtube.com/watch?v='+vid)
    with pytest.raises(ValueError):
        public_youtube.video_id_from_url('https://www.youtube.com/channel/UC'+'a'*22)


def test_only_public_recent_ended_lives_pass():
    now=datetime(2026,11,19,tzinfo=timezone.utc)
    video={'id':'4UwvtMF9FXg','channel_id':'UC'+'a'*22,
           'availability':'public','age_limit':0,'is_live':False,
           'live_status':'was_live','timestamp':(now-timedelta(days=3)).timestamp(),
           'duration':3600}
    assert public_youtube.public_ended_live(video,now=now)
    for patch in ({'availability':'unlisted'},{'availability':'subscriber_only'},
                  {'availability':'needs_auth'},{'age_limit':18},
                  {'live_status':'is_live'},{'live_status':'not_live'},
                  {'timestamp':(now-timedelta(days=31)).timestamp()},
                  {'duration':0},{'timestamp':None,'upload_date':None}):
        assert not public_youtube.public_ended_live({**video,**patch},now=now)


def test_manual_live_url_queues_without_accessing_api_key(monkeypatch):
    from backend import daily_quota
    channel='UC'+'a'*22
    video={'id':'4UwvtMF9FXg','channel_id':channel,'title':'GTA 6 live highlights',
           'availability':'public','age_limit':0,'is_live':False,'live_status':'was_live',
           'timestamp':datetime.now(timezone.utc).timestamp()-86400,'duration':4000}
    monkeypatch.setattr(live_cuts,'public_video_info',lambda url:video)
    monkeypatch.setattr(live_cuts,'authorized_channel',lambda cid: {'evidence':'Licença comercial documentada'} if cid==channel else None)
    monkeypatch.setattr(live_cuts,'recently_used',lambda *args,**kwargs:False)
    monkeypatch.setattr(daily_quota,'config',lambda:{'deadline_local':'23:59'})
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    monkeypatch.setattr(live_cuts.db,'rows',lambda *args,**kwargs:[])
    monkeypatch.setattr(live_cuts.db,'uid',lambda:'new_clip_id')
    inserted=[]
    queued=[]
    monkeypatch.setattr(live_cuts.db,'execute',lambda sql,p:inserted.append((sql,p)))
    monkeypatch.setattr(live_cuts.db,'enqueue',lambda kind,**kw:queued.append(kind))
    monkeypatch.setattr(live_cuts,'record_right',lambda *args,**kw:None)
    def no_key(name):
        raise AssertionError('no key or API should be consulted')
    monkeypatch.setattr(live_cuts.db,'secret',no_key)
    result=live_cuts.submit_live_url('https://www.youtube.com/live/4UwvtMF9FXg')
    assert result['queued']
    assert inserted and queued==['live_cut:new_clip_id']


def test_public_radar_api_endpoints_dont_check_any_secrets(monkeypatch):
    enqueued=[]
    monkeypatch.setattr(api_radar.db,'enqueue',lambda *args,**kwargs:enqueued.append(args[0]))
    monkeypatch.setattr(api_radar.db,'uid',lambda:'one')
    monkeypatch.setattr(api_radar.db,'secret',
                        lambda name: (_ for _ in ()).throw(AssertionError('key not allowed')))
    assert api_radar.trigger_ranking_refresh()['queued']
    assert api_radar.trigger_radar_scan()['queued']
    assert enqueued==['top20_refresh','radar20_scan']


def test_public_video_query_uses_canonical_url_and_never_downloads(monkeypatch):
    called=[]
    def fake_extract(url,**kwargs):
        called.append((url,kwargs))
        return {'id':'4UwvtMF9FXg','availability':'public'}
    monkeypatch.setattr(public_youtube,'_extract',fake_extract)
    result=public_youtube.public_video_info('https://www.youtube.com/live/4UwvtMF9FXg')
    assert result['id']=='4UwvtMF9FXg'
    assert called==[('https://www.youtube.com/watch?v=4UwvtMF9FXg',{})]


def test_manual_channel_can_be_saved_without_api_credentials(monkeypatch,tmp_path):
    channel='UC'+'a'*22
    monkeypatch.setattr(viral_radar20.db,'DATA',tmp_path)
    monkeypatch.setattr(viral_radar20.db,'get_setting',lambda *a,**kw:[])
    recorded=[]
    monkeypatch.setattr(viral_radar20.db,'put_setting',lambda name,value:recorded.append((name,value)))
    monkeypatch.setattr(viral_radar20,'public_channel_info',
                        lambda cid:{'channel_id':cid,'name':'Canal GTA',
                                    'verified_publicly':True,'subscribers':None})
    added=viral_radar20.add_creator(channel)
    assert added[0]['channel_id']==channel
    assert (tmp_path/'top_creators.json').is_file()
    assert recorded[0][0]=='creator_includes'
