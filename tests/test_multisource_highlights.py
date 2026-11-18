import json
import sys
import types

from backend import core as db, highlights, integrations, pipeline, worker
from backend.contracts import ImportRequest, Script


def test_search_radar_prioritizes_youtube_over_news(client):
    examples=[('https://example.com/news','news','new'),
              ('https://www.youtube.com/watch?v=abcdefghijk','youtube','video'),
              ('https://www.youtube.com/shorts/abcdefghijk','youtube','shorts')]
    for url, platform, label in examples:
        db.execute('INSERT INTO opportunities VALUES (:id,:url,:platform,:title,:meta,NULL,0,NULL)',
                   {'id':label,'url':url,'platform':platform,'title':label,'meta':json.dumps({'format':label})})
    result=client.get('/api/state').json()['opportunities']
    assert [v['id'] for v in result]==['shorts','video','new']


def test_long_form_highlights_choose_non_overlapping_ranges():
    script=Script(title='GTA',hook='Cortes',description='Original',hashtags=['gta6'],template='gta-news', duration=30,
         scenes=[{'start':0,'end':10,'text':'a','narration':'aaa','source_id':'x'},
                 {'start':10,'end':20,'text':'b','narration':'bbb','source_id':'x'},
                 {'start':20,'end':30,'text':'c','narration':'ccc','source_id':'x'}])
    edl=highlights.fit_cuts(script,{'source_seconds':180,'scene_cuts_seconds':[15,20,60,70,120,130]})
    assert len(edl)==3
    assert len(set(item['source_start'] for item in edl))==3
    for scene in script.scenes:
        assert scene.source_start+scene.end-scene.start<=180


def test_short_source_never_analyzed(monkeypatch,tmp_path):
    assert highlights.analyze(tmp_path/'unused.mp4',44,30,video_id='unused')=={}


def test_authorized_long_video_clamps_duration(monkeypatch,client,tmp_path):
    id=pipeline.create_video(ImportRequest(url='https://www.youtube.com/watch?v=abcdefghijk',
          rights='AUTHORIZED',evidence='Permissão explícita do titular comprovada',duration=90))
    raw=db.ROOT/'videos/raw'/f'{id}.mp4'; raw.write_bytes(b'fixture')
    monkeypatch.setattr(pipeline,'metadata',lambda *args:{'title':'GTA 6 gameplay','metrics':{},'url':'fixture'})
    monkeypatch.setattr(pipeline,'download_authorized',lambda video:raw)
    monkeypatch.setattr(pipeline.media,'probe',lambda path:{'format':{'duration':'125.0'}})
    monkeypatch.setattr(pipeline.highlights,'analyze',lambda *args,**kwargs:{'target_seconds':45})
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})[0]
    pipeline.hunt(video)
    assert video['duration']==45
    assert db.rows('SELECT duration FROM videos WHERE id=:id',{'id':id})[0]['duration']==45
    assert json.loads(db.rows('SELECT metadata FROM videos WHERE id=:id',{'id':id})[0]['metadata'])['highlight_mode']=='automatic_authorized_clips'


def test_unlicensed_long_youtube_is_reference_only(client,monkeypatch):
    video_id=pipeline.create_video(ImportRequest(url='https://www.youtube.com/watch?v=abcdefghijk',duration=90))
    monkeypatch.setattr(pipeline,'metadata',lambda *args:{'title':'GTA 6 video','metrics':{}})
    monkeypatch.setattr(pipeline.highlights,'analyze',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No media analysis')))
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0]
    pipeline.hunt(video)
    assert not (db.ROOT/'handoff'/video_id/'highlights.json').exists()
    assert video['rights']=='REFERENCE_ONLY'
