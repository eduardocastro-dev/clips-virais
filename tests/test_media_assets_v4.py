"""Asset provenance, temporary lifecycle, repairs, and manual selection tests."""
import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from PIL import Image
import pytest
from backend import core as db,assets,storyboard,production_media
from backend.contracts import Script,ImportRequest


def make_video(status='PROCESSING',rights='AUTHORIZED'):
    id=db.uid()
    db.execute('''INSERT INTO videos (id,run_id,url,platform,title,rights,evidence,status,test,created,updated)
        VALUES (:id,:run,:url,'youtube','Demo',:rights,'Autorização explícita do titular',:status,0,:now,:now)''',
        {'id':id,'run':db.uid(),'url':'https://www.youtube.com/watch?v='+id[:11],
         'rights':rights,'status':status,'now':time.time()})
    return id


def test_timing_normalizer_repairs_all_fields():
    payload={'title':'Demo','hook':'O que se sabe','description':'Fatos','hashtags':[],
        'duration':50,'template':'wrong','music':'none','scenes':[
         {'start':3,'end':4,'text':'Cena um','narration':'Narrativa curta','source_id':'bad'},
         {'start':7,'end':11,'text':'Cena dois','narration':'Mais informações','source_id':'bad'}]}
    data,fixes=storyboard.normalize(payload,30,'gta-news','a'*32)
    script=Script.model_validate(data)
    assert script.duration==30 and script.template=='gta-news'
    assert script.scenes[-1].end==30
    assert all(x.source_id=='a'*32 for x in script.scenes)
    assert {'duration','template'} <= {x['field'] for x in fixes}


def test_temp_copy_preserves_original_and_persistent_metadata():
    id=make_video()
    src=db.ROOT/'assets/gameplay/own.mp4';src.write_bytes(b'fake-video-not-rendered')
    original_hash=hashlib.sha256(src.read_bytes()).hexdigest()
    copy=production_media.copy_original(src,id,'background')
    assert copy.is_relative_to(db.ROOT/'temp'/id)
    assert copy.read_bytes()==src.read_bytes()
    copy.write_bytes(b'edited-working-copy')
    assert hashlib.sha256(src.read_bytes()).hexdigest()==original_hash
    production_media.remove_workspace(id)
    assert src.exists() and not copy.exists()


def test_libray_requires_license_and_copies_selected_visual():
    id=make_video(rights='REFERENCE_ONLY')
    path=db.ROOT/'assets/images/frame.png';Image.new('RGB',(40,60),'red').save(path)
    assets.sync_library()
    stored=db.rows("SELECT * FROM assets WHERE kind='images'")[0]
    assert stored['rights_status']=='REVIEW_REQUIRED'
    assets.set_license(stored['id'],'OWNED_GENERATED','Esta imagem foi desenhada por mim em 2026.')
    script=SimpleNamespace(scenes=[SimpleNamespace(start=0,end=2,source_start=0),
                                   SimpleNamespace(start=2,end=4,source_start=0)])
    # v6 requires real, licensed gameplay: a standalone illustration cannot
    # silently become a background or hide a missing source video.
    with pytest.raises(assets.MissingAssetsError, match='assets/gameplay/'):
        assets.select_visuals({'id':id,'platform':'youtube','rights':'REFERENCE_ONLY',
                               'url':'https://www.youtube.com/watch?v=abcdefghijk'},script)
    assert path.exists()  # Library source is not touched by the failed attempt.


def test_unauthorized_video_is_not_downloaded():
    id=make_video(rights='REFERENCE_ONLY')
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':id})[0]
    assert production_media.acquire_source_video(video) is None
    assert not list((db.ROOT/'temp'/id).glob('source.*')) if (db.ROOT/'temp'/id).exists() else True


def test_retention_keeps_pending_manual_and_expires_finished():
    pending=make_video(status='AWAITING_MANUAL_DECISION')
    old=make_video(status='DISCARDED')
    for id in (pending,old):
        folder=production_media.workspace(id)
        (folder/'working.mp4').write_bytes(b'temp')
        os.utime(folder,(time.time()-864000,time.time()-864000))
    production_media.prune_stale(7)
    assert (db.ROOT/'temp'/pending).exists()
    assert not (db.ROOT/'temp'/old).exists()


def test_assets_api_workflow_and_persona(client):
    image=Image.new('RGB',(20,20),'cyan')
    import io
    stream=io.BytesIO();image.save(stream,format='PNG')
    uploaded=client.post('/api/assets/upload',data={'kind':'persona'},
          files={'file':('reference.png',stream.getvalue(),'image/png')})
    assert uploaded.status_code==200,uploaded.text
    asset=uploaded.json()['asset'];assert asset['rights_status']=='REVIEW_REQUIRED'
    res=client.put('/api/assets/'+asset['id']+'/rights',json={
        'source_class':'OWNED_GENERATED','evidence':'Arte original produzida pelo próprio canal.'})
    assert res.status_code==200,res.text
    saved=client.put('/api/persona',json={'selected':'nico_neon','image_path':asset['path'],
        'voice_model':'','overrides':{'name':'Nico Neon'}})
    assert saved.status_code==200,saved.text
    assert saved.json()['current']['image_path']==asset['path']
    assert client.get('/api/assets').json()['items']


def test_short_import_canonical_and_catalogued(client):
    req=ImportRequest.model_validate({'url':'https://www.youtube.com/shorts/abcdefghijk'})
    assert req.source_kind=='short'
    response=client.post('/api/import',json={'url':'https://www.youtube.com/shorts/abcdefghijk'})
    assert response.status_code==200,response.text
    row=db.rows("SELECT * FROM assets WHERE kind='shorts' AND source_id='abcdefghijk'")
    assert len(row)==1 and row[0]['status']=='METADATA_ONLY'
