import errno
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from backend import core as db
from backend import uploads
from backend.assets import sync_library,mandatory_assets
from backend.personas import get_cast
from backend.redator import narration_ready


def test_cross_mount_upload_uses_destination_atomic_rename(monkeypatch,tmp_path):
    source=tmp_path/'source.part';data=os.urandom(10*1024*1024+3);source.write_bytes(data)
    dest=tmp_path/'other-mount'/'upload.mp4'
    real=uploads.os.replace
    operations=[]
    def fake_replace(src,dst):
        operations.append((Path(src),Path(dst)))
        if str(src).endswith('.part'):
            raise OSError(errno.EXDEV,'Invalid cross-device link')
        assert Path(src).parent==Path(dst).parent
        return real(src,dst)
    monkeypatch.setattr(uploads.os,'replace',fake_replace)
    uploads.promote_across_volumes(source,dest)
    assert dest.read_bytes()==data
    assert not source.exists()
    assert len(operations)==1 and '.incoming-' in operations[0][0].name


def test_cross_mount_copy_failure_keeps_original(monkeypatch,tmp_path):
    source=tmp_path/'source.part';source.write_bytes(b'important original')
    dest=tmp_path/'dest'/'final.mp4';dest.parent.mkdir()
    dest.write_bytes(b'existing')
    try:uploads.promote_across_volumes(source,dest)
    except FileExistsError:pass
    else:assert False,'Destination collision must block overwrite.'
    assert source.read_bytes()==b'important original' and dest.read_bytes()==b'existing'


def test_recover_previous_failed_upload_session():
    sid=db.uid();name='gta.mp4';fp=hashlib.sha256(b'gta-session').hexdigest()
    part=uploads._session_path(sid);part.write_bytes(b'a'*128)
    now=__import__('time').time()
    db.execute('''INSERT INTO upload_sessions(id,filename,size_bytes,received,state,category,tags,source_class,evidence,media_type,sha256,updated,created,error)
       VALUES (:id,:name,128,128,'FAILED','gameplay','[]','OWNED_GENERATED','Gravado localmente','video',:sha,:now,:now,'EXDEV')''',
       {'id':sid,'name':name,'sha':fp,'now':now})
    item=SimpleNamespace(filename=name,size=128,category='gameplay',source_class='OWNED_GENERATED',fingerprint=fp,tags=[],evidence='Gravado localmente')
    result=uploads.create_session(item)
    assert result['resumed'] and result['offset']==128 and result['id']==sid
    assert db.rows('SELECT state FROM upload_sessions WHERE id=:id',{'id':sid})[0]['state']=='UPLOADING'
    part.unlink()


def test_cast_originals_have_distinct_images():
    cast=get_cast()
    assert {'dante_palma','lia_varela','caio_rivas'}<=set(cast)
    # Fixture with empty STUDIO_FILES intentionally has no bundled avatar until copied by user.
    assert all(cast[name]['role'] in ('apresentador','analista','reporter') for name in cast)


def test_tts_revision_protects_full_sentences():
    sentence=narration_ready('GTA 6 tem 5 eventos. Um rumor não é um fato')
    assert sentence=='GTA seis tem cinco eventos. Um rumor não é um fato.'
    assert not any(ord(c)>0xffff for c in sentence)


def test_rescan_adds_no_unlicensed_asset_to_render_pool():
    directory=db.ROOT/'assets/images';directory.mkdir(parents=True,exist_ok=True)
    from PIL import Image
    path=directory/'noticia.png';Image.new('RGB',(12,12),'blue').save(path)
    a=sync_library();b=sync_library()
    assert a['registered']>=1 and b['registered']==0
    row=db.rows('SELECT rights_status,status FROM assets WHERE path=:path',{'path':'assets/images/noticia.png'})[0]
    assert row['rights_status']=='REVIEW_REQUIRED' and row['status']=='PENDING_RIGHTS'
    path.unlink()


def test_missing_assets_pauses_without_review_attempts():
    from backend.pipeline import create_video,run_pipeline
    vid=create_video(test=True)
    run_pipeline(vid)
    row=db.rows('SELECT status,error FROM videos WHERE id=:id',{'id':vid})[0]
    assert row['status']=='PAUSED_MISSING_ASSETS'
    assert 'assets/gameplay/' in row['error']
    assert 'assets/music/' in row['error']
    assert not db.rows('SELECT attempt FROM video_attempts WHERE video_id=:id',{'id':vid})


def test_two_independent_reviewers(monkeypatch):
    from backend import evaluation
    from backend.contracts import Script
    from types import SimpleNamespace
    import concurrent.futures
    who=db.uid()
    now=__import__('time').time()
    db.execute("INSERT INTO videos(id,run_id,url,status,created,updated,test) VALUES(:id,:run,:url,'PROCESSING',:now,:now,0)",
               {'id':who,'run':db.uid(),'url':'test://'+who,'now':now})
    path=db.ROOT/'videos/final'/f'{who}.mp4';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fake-mock-path')
    script=Script.model_validate({'title':'Rumor sobre GTA seis','hook':'Isso é rumor.',
       'template':'gta-news','duration':10,'description':'','hashtags':[],
       'scenes':[{'start':0,'end':5,'text':'Rumor','narration':'Isso ainda é um rumor.','source_id':who},
                 {'start':5,'end':10,'text':'Fonte','narration':'A fonte não confirmou.','source_id':who}]})
    monkeypatch.setattr(evaluation.media,'technical_check',lambda path,n:{'valid':True,'failures':[],'duration':n,'resolution':[1080,1920]})
    monkeypatch.setattr(evaluation.media,'samples',lambda *args:[])
    monkeypatch.setattr(evaluation.media,'transcript_check',lambda *args:{'valid':True,'language':'pt','word_match':1.0})
    monkeypatch.setattr(evaluation.db,'read_artifact',lambda *args:SimpleNamespace(dados={}))
    from threading import Lock
    called=[];mutex=Lock()
    def fake_llm(agent,*args,**kwargs):
        with mutex:called.append(agent)
        if agent=='avaliador':
            return {'scores':{k:8. for k in db.settings().evaluation_criteria},
                    'evidence':{},'factual_supported':True,'original':True,'summary':'Bom'}
        if agent=='pessoa':
            return {'scores':{k:8. for k in evaluation.PERSON_KEYS},
                    'evidence':{},'summary':'Gostei','boring_second':None}
        raise AssertionError(agent)
    monkeypatch.setattr(evaluation,'llm',fake_llm)
    result=evaluation.evaluate({'id':who,'rights':'REFERENCE_ONLY','test':0},script,path)
    assert set(called)=={'avaliador','pessoa'}
    assert result['verdict']=='APROVADO'
    assert all(v['passed'] for v in result['viewer'].values())
    assert result['review_medium'].startswith('frames+transcript')
