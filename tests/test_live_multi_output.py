"""Live VOD -> three individual MP4s, safe migration, original layout and rights tests."""
from __future__ import annotations
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend import core as db,daily_quota,live_clip_render,live_cuts
from backend.live_clip_layout import ANCHORS,camera_rect,graph
from backend.integrations import IntegrationError


CHANNEL='UC'+'A'*22
VIDEO_ID='ABCD1234xyz'


def _parent(*,id='a'*32,status='QUEUED',file_path=None):
    now=time.time()
    db.execute("""INSERT INTO live_clips
        (id,video_id,channel_id,title,source_url,rights_evidence,
         webcam_anchor,cut_target,status,created,updated,file_path)
        VALUES (:id,:video,:channel,'Live do streamer',
                :url,'Licença comprovada pela emissora e criador',
                'bottom_left',3,:status,:now,:now,:file)""",
        {'id':id,'video':VIDEO_ID,'channel':CHANNEL,
         'url':'https://www.youtube.com/watch?v='+VIDEO_ID,
         'status':status,'now':now,'file':file_path})
    return id


def _output(parent,ordinal,*,status='REVIEW_PENDING'):
    ident=parent+'-'+str(ordinal)
    path='videos/final/live_cuts/'+parent+f'/cut-{ordinal:02d}.mp4'
    target=db.ROOT/path
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes(b'mp4 fixture '+bytes([ordinal])*2048)
    db.execute("""INSERT INTO live_clip_outputs
        (id,parent_id,ordinal,title,status,score,segment_start,
         segment_end,file_path,created,updated)
        VALUES (:id,:parent,:ordinal,:title,:status,:score,:start,
                :end,:file,:now,:now)""",
        {'id':ident,'parent':parent,'ordinal':ordinal,
         'title':'Corte '+str(ordinal),'status':status,'score':85,
         'start':float(ordinal*80),'end':float(ordinal*80+30),
         'file':path,'now':time.time()})
    return ident


def test_layout_has_streamer_above_game_and_safe_caption_band():
    assert camera_rect('bottom_left')==(0.0,0.39,0.19,0.36)
    assert set(ANCHORS)=={'bottom_left','top_left','bottom_right','top_right'}
    content=graph('/tmp/captions.ass','bottom_left')
    assert 'overlay=x=40:y=130' in content
    assert 'overlay=x=40:y=830' in content
    assert 'drawbox=x=0:y=1620' in content
    assert 'loudnorm=I=-14:TP=-1.5' in content
    with pytest.raises(ValueError):
        graph('/tmp/captions.ass','random')


def test_live_list_groups_three_independent_outputs(client):
    parent=_parent()
    for i in (1,2,3):_output(parent,i)
    response=client.get('/api/live-clips')
    assert response.status_code==200
    group=next(x for x in response.json()['items'] if x['id']==parent)
    assert group['completed_cuts']==3
    assert group['expected_cuts']==3
    assert [x['ordinal'] for x in group['outputs']]==[1,2,3]


def test_individual_review_does_not_approve_siblings(client,monkeypatch):
    parent=_parent(status='REVIEW_PENDING')
    children=[_output(parent,i) for i in (1,2,3)]
    monkeypatch.setattr(live_cuts,'authorized_channel',
                        lambda _channel:{'evidence':'Licença documentada'})
    response=client.post(f'/api/live-clips/{parent}/outputs/{children[0]}/decision',
                         json={'decision':'approve'})
    assert response.status_code==200
    status=db.rows('SELECT ordinal,status FROM live_clip_outputs ORDER BY ordinal')
    assert [x['status'] for x in status]==['APPROVED','REVIEW_PENDING','REVIEW_PENDING']
    assert db.rows('SELECT status FROM live_clips WHERE id=:id',
                   {'id':parent})[0]['status']=='REVIEW_PENDING'
    old=client.post(f'/api/live-clips/{parent}/decision',
                    json={'decision':'approve'})
    assert old.status_code==409


def test_quota_counts_children_not_parent(monkeypatch):
    parent=_parent(status='PROCESSING')
    _output(parent,1)
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    quota=daily_quota.state()
    assert quota['approved']['lives_cuts']==1
    assert quota['pending']['lives_cuts']==2


def test_rerender_legacy_live_preserves_old_file(client,monkeypatch):
    parent=_parent(status='REVIEW_PENDING')
    old=db.ROOT/'videos'/'final'/'live_cuts'/parent/'cut.mp4'
    old.parent.mkdir(parents=True,exist_ok=True)
    old.write_bytes(b'old render preserved')
    db.execute("UPDATE live_clips SET file_path=:file WHERE id=:id",
               {'id':parent,'file':str(old.relative_to(db.ROOT))})
    db.init_db()  # additive migration imports the legacy output
    monkeypatch.setattr(live_cuts,'authorized_channel',
                        lambda _channel:{'evidence':'Licença documentada'})
    monkeypatch.setattr(daily_quota,'within_deadline',
                        lambda *args,**kwargs:True)
    response=client.post(f'/api/live-clips/{parent}/reprocess',
                         json={'webcam_anchor':'bottom_left'})
    assert response.status_code==200
    assert old.exists()
    assert not db.rows('SELECT id FROM live_clip_outputs WHERE parent_id=:id',
                       {'id':parent})
    assert db.rows('SELECT webcam_anchor,cut_target,status FROM live_clips WHERE id=:id',
                   {'id':parent})[0]=={'webcam_anchor':'bottom_left','cut_target':3,'status':'QUEUED'}


def test_manual_permission_and_anchor_are_recorded(monkeypatch):
    monkeypatch.setattr(live_cuts,'public_video_info',lambda _url:{
        'title':'Patife joga GTA 6','channel_id':CHANNEL})
    monkeypatch.setattr(live_cuts,'public_ended_live',lambda *args,**kwargs:True)
    monkeypatch.setattr(live_cuts,'recently_used',lambda *args,**kwargs:False)
    from backend import daily_quota
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    outcome=live_cuts.submit_live_url(
        'https://www.youtube.com/watch?v='+VIDEO_ID,
        'Permissão escrita do titular para reproduzir três cortes.',
        'bottom_left')
    assert outcome['expected_cuts']==3
    row=db.rows('SELECT webcam_anchor,cut_target,rights_evidence FROM live_clips')[0]
    assert row['cut_target']==3
    assert row['webcam_anchor']=='bottom_left'
    assert 'Permissão escrita' in row['rights_evidence']


def test_render_three_outputs_after_single_transcription(monkeypatch):
    parent=_parent()
    import backend.live_clip_render as render
    transcribed=[]
    monkeypatch.setattr(live_cuts,'authorized_channel',
                        lambda _channel:{'evidence':'Licença documentada'})
    monkeypatch.setattr(render,'verified_live',lambda *args,**kwargs:{})
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *args,**kwargs:True)
    def fake_audio(url,folder):
        file=folder/'dummy.wav';file.write_bytes(b'audio');return file
    monkeypatch.setattr(render,'_audio_first',fake_audio)
    monkeypatch.setattr(render,'_volume_levels',lambda a,f:([-27.0]*120,f/'dummy.wav'))
    def transcription(a,f):
        transcribed.append(True)
        return {'words':[{'text':'momento','start':2,'end':3}],
                'segments':[{'start':2,'end':3,'text':'momento'}]}
    monkeypatch.setattr(render,'_whisperx_words',transcription)
    candidates=[{'start':i*65+1,'end':i*65+31,'score':83+i,
                 'reason':'Pico de áudio e reação'} for i in range(3)]
    monkeypatch.setattr(render,'_score_candidates',lambda *args,**kwargs:candidates)
    def fake_get(url,start,end,folder):
        path=folder/'source.mp4';path.write_bytes(b'source');return path
    monkeypatch.setattr(render,'_get_range',fake_get)
    monkeypatch.setattr(render,'_subtitles',lambda *args:4)
    def fake_run(args,timeout):
        if args[-1].endswith('render.mp4'):
            Path(args[-1]).write_bytes(b'render test'+b'x'*2500)
    monkeypatch.setattr(render,'_run',fake_run)
    monkeypatch.setattr(render.media,'probe',lambda p:{
        'streams':[{'codec_type':'video','codec_name':'h264','width':1080,'height':1920}],
        'format':{'duration':30}})
    def fake_media_run(args,**kwargs):
        if args[-1].endswith('.jpg'):
            Path(args[-1]).write_bytes(b'cover')
    monkeypatch.setattr(render.media,'run',fake_media_run)
    monkeypatch.setattr(render.subprocess,'run',lambda *args,**kwargs:
        SimpleNamespace(returncode=0,stderr=b'Integrated loudness: I: -14.0 LUFS'))
    result=render.render_clip(parent)
    assert result['total_cuts']==3
    assert len(transcribed)==1
    rows=db.rows('SELECT * FROM live_clip_outputs WHERE parent_id=:id ORDER BY ordinal',
                 {'id':parent})
    assert len(rows)==3
    assert len({row['file_path'] for row in rows})==3
    assert all(row['status']=='REVIEW_PENDING' for row in rows)
    assert db.rows('SELECT status FROM live_clips WHERE id=:id',{'id':parent})[0]['status']=='REVIEW_PENDING'


def test_2_eligible_segments_do_not_become_3_fake_cuts(monkeypatch):
    parent=_parent()
    import backend.live_clip_render as render
    monkeypatch.setattr(live_cuts,'authorized_channel',lambda _channel:{'evidence':'valid'})
    monkeypatch.setattr(render,'verified_live',lambda *a,**kw:{})
    monkeypatch.setattr(daily_quota,'within_deadline',lambda *a,**kw:True)
    monkeypatch.setattr(render,'_audio_first',lambda url,folder:folder/'cached.mp3')
    monkeypatch.setattr(render,'_volume_levels',lambda audio,folder:([-20.0]*120,folder/'audio.wav'))
    monkeypatch.setattr(render,'_whisperx_words',lambda audio,folder:{'words':[],'segments':[]})
    monkeypatch.setattr(render,'_score_candidates',
                        lambda *args,**kwargs:[{'start':1,'end':31,'score':90},
                                                {'start':75,'end':105,'score':90}])
    with pytest.raises(IntegrationError,match='São necessários 3'):
        render.render_clip(parent)
    assert db.rows('SELECT * FROM live_clip_outputs WHERE parent_id=:id',{'id':parent})==[]
