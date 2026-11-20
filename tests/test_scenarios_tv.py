"""Nine GTA scenario TV layouts and publication-rights safety regression tests."""
import json
from pathlib import Path
from PIL import Image
import pytest

from backend import core as db
from backend.scenarios import SCENARIOS,TV_OUTER,TV_SCREEN,PRESENTER_ZONE,CAPTIONS_ZONE,build_layers,geometry
from backend.rights_gate import pending_sources,require_clearance,confirm
from backend.integrations import IntegrationError


def test_nine_scenarios_are_distinct_and_reserve_separate_regions(tmp_path):
    assert len(SCENARIOS)==9
    x0,y0,x1,y1=TV_OUTER
    ax0,ay0,ax1,ay1=PRESENTER_ZONE
    cx0,cy0,cx1,cy1=CAPTIONS_ZONE
    assert 230>=y0-10 and y1<=790
    assert TV_SCREEN[1]>=y0 and TV_SCREEN[3]<=y1
    assert y1 < ay0 < ay1 < cy0 < cy1 <=1580
    assert geometry()['frame_rate']==30
    for name,meta in SCENARIOS.items():
        assert meta['kind'] and meta['sfx']
        layers=build_layers(name,tmp_path/name,source_label='news.example',
                            date_label='2026-11-20')
        assert layers is not None
        for path in (layers['plate'],layers['bezel']):
            with Image.open(path) as im:
                assert im.size==(1080,1920)
        with Image.open(layers['bezel']) as im:
            # Transparent presenter and subtitles; only spill light may cross.
            assert im.getpixel((540,950))[3]==0
            assert im.getpixel((540,1490))[3]==0
            assert im.getpixel((x0,y0))[3]!=0 or im.getpixel((x0+10,y0+10))[3]!=0


def test_bezel_has_source_credit_inside_tv_and_reusable_plate(tmp_path):
    folder=tmp_path/'set'
    a=build_layers('gta-news',folder,source_label='IGN',date_label='2026-11-20')
    b=build_layers('gta-news',folder,source_label='GameSpot',date_label='2026-11-19')
    assert a['plate']==b['plate']
    assert a['bezel']!=b['bezel']
    with Image.open(a['bezel']) as im:
        # Source label is in the screen; no text enters presenter/caption area.
        assert any(im.getpixel((x,690))[3] for x in range(160,900,10))


def _video_with_pending_slot(video_id):
    db.execute("""INSERT INTO videos(id,run_id,url,title,rights,evidence,template,status,
        stage,created,updated,final_path)
        VALUES (:id,'run','https://www.youtube.com/watch?v=4UwvtMF9FXg',
        'Teste com TV','REFERENCE_ONLY','','gta-news','PENDING_RIGHTS_REVIEW',
        'diretor',1,1,:final)""",{'id':video_id,'final':'videos/final/'+video_id+'/attempt-01.mp4'})
    output=db.ROOT/'videos/final'/video_id/'attempt-01.mp4'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_bytes(b'preview-fixture-only')
    handoff=db.ROOT/'handoff'/video_id
    handoff.mkdir(parents=True,exist_ok=True)
    source='https://www.youtube.com/watch?v=4UwvtMF9FXg'
    manifest=[{'scene':0,'segments':[{'duration':3,'tv_slot':{
        'tv_source_url':source,'rights_status':'REVIEW_REQUIRED',
        'preview_only':True,'tv_source':'temp/source.mp4'}}]}]
    db.atomic(handoff/'visual-assets.json',json.dumps(manifest))
    return source


def test_rendered_preview_is_not_automatically_licensed(client):
    video_id='e'*32
    _video_with_pending_slot(video_id)
    pending=pending_sources(video_id)
    assert len(pending)==1
    with pytest.raises(IntegrationError,match='TV contém material'):
        require_clearance(db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0])
    response=client.post('/api/videos/'+video_id+'/decision',json={'action':'approve'})
    assert response.status_code==409
    assert not db.rows('SELECT approved FROM videos WHERE id=:id',{'id':video_id})[0]['approved']


def test_operator_can_record_license_after_render_but_still_must_approve(client):
    video_id='f'*32
    source=_video_with_pending_slot(video_id)
    response=client.post('/api/videos/'+video_id+'/source-rights',json={
        'evidence':'Licença documentada do criador cobre este excerto e sua publicação.'})
    assert response.status_code==200
    assert response.json()['status']=='RIGHTS_CONFIRMED'
    updated=db.rows('SELECT rights,evidence,approved FROM videos WHERE id=:id',{'id':video_id})[0]
    assert updated['rights']=='AUTHORIZED'
    assert updated['approved']==0
    assert db.rows('SELECT status FROM videos WHERE id=:id',{'id':video_id})[0]['status']=='AWAITING_MANUAL_DECISION'
    assert pending_sources(video_id)==[]
    assert (db.DATA/'rights_log.json').is_file()


def test_license_evidence_cannot_be_blank_or_grant_before_mp4(client):
    video_id='d'*32
    _video_with_pending_slot(video_id)
    bad=client.post('/api/videos/'+video_id+'/source-rights',json={'evidence':'sim'})
    assert bad.status_code==422
    output=db.ROOT/'videos/final'/video_id/'attempt-01.mp4'
    output.unlink()
    bad=client.post('/api/videos/'+video_id+'/source-rights',
                    json={'evidence':'Temos autorização formal registrada para o conteúdo.'})
    assert bad.status_code==409
