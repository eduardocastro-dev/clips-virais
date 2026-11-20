"""Quota/radar/live-cut safety regressions: no credentials or media downloads."""
from datetime import datetime, timedelta, timezone
import json
import pytest

from backend import core as db
from backend.contracts import Settings
from backend import daily_quota, viral_radar20, live_cuts
from backend.live_clip_render import (
    _score_candidates, _selection_valid, _minimum_gap, INTRO_SKIP_SECONDS,
)


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
        {'start':310,'end':322,'text':'Olha só que surpresa incrível! Achei esse detalhe no mapa agora e precisamos discutir.'},
        {'start':322,'end':336,'text':'Essa parte explica exatamente o que aconteceu e por que é relevante para os jogadores.'},
        {'start':336,'end':348,'text':'Você viu isso? O que a comunidade vai achar desse momento?'}
    ]
    volume=[-30.0]*450
    for s in range(320,327):volume[s]=-19
    good=_score_candidates({'segments':segments},volume)
    assert good and good[0]['score']>=70 and good[0]['start']>=300
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


def _interesting_segments(at):
    # Four independent, timestamped speech chunks form a 32-second highlight.
    text='Olha esse momento incrível da partida! A comunidade reagiu e agora temos uma nova jogada especial.'
    return [{'start':at+i*8,'end':at+(i+1)*8,'text':text}
            for i in range(4)]


def test_live_highlights_skip_intro_and_cover_distant_timestamps():
    segments=[]
    # High-scoring moments in the introduction must still be ignored.
    for at in (15,120,305,340,375,1800,3600,6500):
        segments.extend(_interesting_segments(at))
    volumes=[-30.0]*7200
    chosen=_score_candidates({'segments':segments},volumes,min_score=70)
    assert len(chosen)==3
    assert all(c['start']>=INTRO_SKIP_SECONDS for c in chosen)
    assert chosen==sorted(chosen,key=lambda c:c['start'])
    assert chosen[-1]['start']-chosen[0]['start']>5000
    assert all(b['start']-a['end']>=_minimum_gap(len(volumes))
               for a,b in zip(chosen,chosen[1:]))
    assert _selection_valid(chosen,3,70,len(volumes))


def test_live_intro_cutoff_and_short_vods_do_not_fabricate_cuts():
    too_short=_interesting_segments(10)+_interesting_segments(190)
    assert _score_candidates({'segments':too_short},[-30.0]*280)==[]
    old_intro=[{'start':280.,'end':315.,'score':99.},
               {'start':1400.,'end':1435.,'score':95.},
               {'start':2600.,'end':2635.,'score':92.}]
    assert not _selection_valid(old_intro,3,70,3600)
    clustered=[{'start':310.,'end':345.,'score':99.},
               {'start':400.,'end':435.,'score':95.},
               {'start':500.,'end':535.,'score':92.}]
    assert not _selection_valid(clustered,3,70,3600)
