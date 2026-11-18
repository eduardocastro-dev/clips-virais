"""V5 smoke: upload resume, original retention, precise clipping, provenance and selection."""
import hashlib
import io
import json
import subprocess
from pathlib import Path
from backend import core as db
from backend.clips import time_windows,split_asset
from backend.contracts import Script


def video(path,seconds=51.2,color='purple'):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
        f'color=c={color}:s=240x426:r=12','-t',str(seconds),'-c:v','libx264','-preset','ultrafast',
        '-pix_fmt','yuv420p',str(path)],check=True,timeout=50)


def upload(client,filename,payload,category='gameplay',source='OWNED_GENERATED',evidence='Mídia produzida por mim e autorizada.'):
    fp=hashlib.sha256((filename+str(len(payload))).encode()).hexdigest()
    started=client.post('/api/uploads/sessions',json={'filename':filename,'size':len(payload),'category':category,
        'source_class':source,'evidence':evidence,'tags':['vice city','gameplay'],'fingerprint':fp})
    assert started.status_code==200,started.text
    sid=started.json()['id']
    halfway=len(payload)//2
    response=client.patch(f'/api/uploads/sessions/{sid}',data=payload[:halfway],headers={'Upload-Offset':'0','Content-Type':'application/octet-stream'})
    assert response.status_code==200,response.text
    resumed=client.post('/api/uploads/sessions',json={'filename':filename,'size':len(payload),'category':category,
        'source_class':source,'evidence':evidence,'tags':['vice city','gameplay'],'fingerprint':fp})
    assert resumed.json()['offset']==halfway
    response=client.patch(f'/api/uploads/sessions/{sid}',data=payload[halfway:],headers={'Upload-Offset':str(halfway),'Content-Type':'application/octet-stream'})
    assert response.status_code==200,response.text
    result=client.post(f'/api/uploads/sessions/{sid}/finish')
    assert result.status_code==200,result.text
    return result.json()['asset']


def test_windows_and_merge():
    assert time_windows(51,10,3)==[(0,10),(10,10),(20,10),(30,10),(40,11)]
    assert time_windows(50.5,10,3)[-1]==(40,10.5)
    assert time_windows(46,10,3)[-1]==(40,6)


def test_upload_resume_original_and_clips(client,tmp_path):
    original=tmp_path/'source.mp4';video(original,51.2)
    source_bytes=original.read_bytes()
    asset=upload(client,'gta6-original.mp4',source_bytes)
    assert asset['media_type']=='video' and asset['status']=='SPLIT_QUEUED'
    path=db.ROOT/asset['path']
    assert path.read_bytes()==source_bytes
    result=split_asset(asset['id'])
    assert result['clips']==5
    assert path.read_bytes()==source_bytes
    children=db.rows('SELECT * FROM assets WHERE parent_id=:id ORDER BY clip_index',{'id':asset['id']})
    assert len(children)==5
    assert [round(c['duration']) for c in children]==[10,10,10,10,11]
    assert all(c['source_class']==asset['source_class'] and c['rights_status']==asset['rights_status'] for c in children)
    assert all((db.ROOT/c['path']).is_file() for c in children)
    second=client.post('/api/uploads/sessions',json={'filename':'gta6-original.mp4','size':len(source_bytes),
        'category':'gameplay','source_class':'OWNED_GENERATED','evidence':'Licença própria registrada',
        'tags':[],'fingerprint':hashlib.sha256(('gta6-original.mp4'+str(len(source_bytes))).encode()).hexdigest()})
    assert second.status_code==200
    assert split_asset(asset['id'])['status']=='ALREADY_SPLIT'
    delete_no=client.request('DELETE',f'/api/assets/{asset["id"]}',json={})
    assert delete_no.status_code==409
    assert path.exists()
    delete_yes=client.request('DELETE',f'/api/assets/{asset["id"]}',json={'confirm_children':True})
    assert delete_yes.status_code==200
    assert not path.exists()
    assert not db.rows('SELECT * FROM assets WHERE parent_id=:id',{'id':asset['id']})


def test_short_video_stays_whole(client,tmp_path):
    file=tmp_path/'short.mp4';video(file,3.3)
    asset=upload(client,'clip-curto.mp4',file.read_bytes())
    assert asset['status']=='READY'
    assert not db.rows('SELECT * FROM assets WHERE parent_id=:id',{'id':asset['id']})


def test_media_upload_and_metadata(client):
    from PIL import Image
    buf=io.BytesIO();Image.new('RGB',(25,25),'blue').save(buf,format='PNG')
    asset=upload(client,'fundo.png',buf.getvalue(),category='imagem de fundo')
    assert asset['media_type']=='image'
    updated=client.patch('/api/assets/'+asset['id'],json={'title':'Novo Fundo','active':False,
        'tags':['carros','vice city']})
    assert updated.status_code==200,updated.text
    assert updated.json()['asset']['active']==0
    assert json.loads(updated.json()['asset']['tags'])==['carros','vice city']


def test_visual_selection_avoids_same_clip(client,tmp_path):
    first=tmp_path/'first.mp4';second=tmp_path/'second.mp4'
    video(first,2.7,'purple');video(second,2.7,'red')
    a=upload(client,'one.mp4',first.read_bytes())
    b=upload(client,'two.mp4',second.read_bytes())
    now=__import__('time').time();video_id=db.uid()
    db.execute('''INSERT INTO videos (id,run_id,url,title,rights,evidence,credits,template,duration,status,created,updated)
       VALUES (:id,:run,:url,'GTA 6 teste','REFERENCE_ONLY','','','gta-news',12,'QUEUED',:now,:now)''',
       {'id':video_id,'run':db.uid(),'url':'https://www.youtube.com/watch?v=abcdefghijk','now':now})
    script=Script.model_validate({'title':'GTA 6 teste','hook':'Abertura','description':'','hashtags':[],
       'template':'gta-news','duration':12,'scenes':[{'start':0,'end':6,'text':'GTA 6 carros','narration':'Carros','source_id':'1'},
                                         {'start':6,'end':12,'text':'GTA 6 corrida','narration':'Corrida','source_id':'2'}]})
    from backend.assets import select_visuals
    vis=select_visuals(db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0],script)
    assert len(vis)==2
    parts=[seg for row in vis for seg in row['segments']]
    assert len(parts)==4 and all(2<=p['duration']<=4 for p in parts)
    assert all(p['asset_id'] in (a['id'],b['id']) for p in parts)
    assert all(x['asset_id']!=y['asset_id'] for x,y in zip(parts,parts[1:]))
    assert all((db.ROOT/p['path']).is_file() for p in parts)


def test_srt_and_font_uploads(client):
    sub=b'1\n00:00:00,000 --> 00:00:01,000\nGTA Studio\n'
    captions=upload(client,'texto.srt',sub,category='outro')
    assert captions['media_type']=='subtitle'
    font=Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if font.is_file():
        glyph=upload(client,'fonte.ttf',font.read_bytes(),category='outro')
        assert glyph['media_type']=='font'


def test_audio_upload_and_classification(client,tmp_path):
    path=tmp_path/'music.wav'
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-f','lavfi','-i',
        'sine=frequency=330:sample_rate=44100','-t','2','-c:a','pcm_s16le',str(path)],check=True,timeout=15)
    item=upload(client,'trilha.wav',path.read_bytes(),category='musica')
    assert item['media_type']=='audio'
    assert item['category']=='musica'
    assert not db.rows('SELECT id FROM assets WHERE parent_id=:id',{'id':item['id']})
