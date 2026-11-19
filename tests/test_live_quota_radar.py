"""Quota/radar/live-cut safety regressions: no credentials or media downloads."""
from datetime import datetime, timedelta, timezone
import json
import pytest

from backend import core as db
from backend.contracts import Settings
from backend import daily_quota, viral_radar20, live_cuts
from backend.live_clip_render import _score_candidates


def test_shorts_quota_is_the_existing_operator_daily_limit(monkeypatch,tmp_path):
    monkeypatch.setattr(daily_quota.db,'DATA',tmp_path)
    monkeypatch.setattr(daily_quota.db,'settings',lambda:Settings(daily_limit=8))
    cfg=daily_quota.config()
    assert cfg['shorts']==8
    assert cfg['lives_cuts']==5
    assert cfg['max_attempts_per_item']==3
    assert cfg['shorts_source'].startswith('settings.daily_limit')
    assert json.loads((tmp_path/'daily_quota.json').read_text())['shorts']==8


def test_deadline_is_checked_in_sao_paulo(monkeypatch,tmp_path):
    monkeypatch.setattr(daily_quota.db,'DATA',tmp_path)
    monkeypatch.setattr(daily_quota.db,'settings',lambda:Settings(daily_limit=4))
    cfg=daily_quota.config()
    assert cfg['shorts']==4
    assert daily_quota.within_deadline({**cfg,'deadline_local':'18:00'},
        datetime.fromisoformat('2026-11-19T18:01:00-03:00')) is False
    assert daily_quota.within_deadline({**cfg,'deadline_local':'18:00'},
        datetime.fromisoformat('2026-11-19T17:59:00-03:00')) is True


def test_public_recent_ended_eligibility_is_conservative():
    now=datetime(2026,11,19,tzinfo=timezone.utc)
    good={'snippet':{'publishedAt':(now-timedelta(days=2)).isoformat()},
          'status':{'privacyStatus':'public'},'contentDetails':{}}
    assert viral_radar20.allowed_public_video(good,now)
    assert not viral_radar20.allowed_public_video(
        {**good,'snippet':{'publishedAt':(now-timedelta(days=31)).isoformat()}},now)
    assert not viral_radar20.allowed_public_video(
        {**good,'status':{'privacyStatus':'unlisted'}},now)
    assert not viral_radar20.allowed_public_video(
        {**good,'status':{'privacyStatus':'private'}},now)
    assert not viral_radar20.allowed_public_video(
        {**good,'contentDetails':{'contentRating':{'ytRating':'ytAgeRestricted'}}},now)
    assert not viral_radar20.allowed_public_video(
        {**good,'status':{}},now)


def test_public_ranking_parser_does_not_invent_channels():
    html='<table class="wikitable"><tr><th>Rank</th><th>Channel</th><th>Subscribers</th></tr>'
    for i in range(1,21):
        html+=f'<tr><td>{i}</td><td>Creator {i}</td><td>{100-i} million</td></tr>'
    html+='</table>'
    results=viral_radar20.parse_ranking(html)
    assert len(results)==20
    assert results[0]['name']=='Creator 1'
    with pytest.raises(Exception):
        viral_radar20.parse_ranking('<p>no verified creator list</p>')


def test_clipping_allowlist_requires_explicit_permission(monkeypatch,tmp_path):
    monkeypatch.setattr(live_cuts.db,'DATA',tmp_path)
    channel='UC'+'A'*22
    with pytest.raises(ValueError):
        live_cuts.allow_creator(channel,'público')
    assert not live_cuts.authorized_channel(channel)
    live_cuts.allow_creator(channel,'Autorização documentada e aceita pelo titular')
    assert live_cuts.authorized_channel(channel)['channel_id']==channel
    live_cuts.remove_creator(channel)
    assert live_cuts.authorized_channel(channel) is None


def test_highlight_scoring_rejects_short_contextless_audio():
    segments=[
        {'start':0,'end':12,'text':'Olha só que surpresa incrível! Achei esse detalhe no mapa agora e precisamos discutir.'},
        {'start':12,'end':26,'text':'Essa parte explica exatamente o que aconteceu e por que é relevante para os jogadores.'},
        {'start':26,'end':38,'text':'Você viu isso? O que a comunidade vai achar desse momento?'}
    ]
    volume=[-30.0]*45
    for s in range(10,17):volume[s]=-19
    good=_score_candidates({'segments':segments},volume)
    assert good and good[0]['score']>=70
    bad=_score_candidates({'segments':[{'start':0,'end':2,'text':'oi'}]},volume)
    assert bad==[]


def test_quota_empty_does_not_fabricate_approved_work(monkeypatch,tmp_path):
    monkeypatch.setattr(db,'DATA',tmp_path)
    monkeypatch.setattr(db,'ROOT',tmp_path)
    monkeypatch.setattr(db,'settings',lambda:Settings(daily_limit=6))
    db.init_db()
    snapshot=daily_quota.state()
    assert snapshot['approved']=={'shorts':0,'lives_cuts':0}
    assert snapshot['target']=={'shorts':6,'lives_cuts':5}
    assert (tmp_path/'quota_state.json').is_file()
