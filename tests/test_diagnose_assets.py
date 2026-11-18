"""Read-only diagnostics must not change existing production records."""
import hashlib
import json
import sqlite3
from pathlib import Path
from backend.diagnose_assets import report


def test_diagnose_no_database(tmp_path):
    result=report(tmp_path,tmp_path/'missing.sqlite')
    assert result['database_exists'] is False
    assert result['scenes']==[]


def test_diagnose_existing_video_readonly(tmp_path):
    data=tmp_path/'data'
    data.mkdir()
    database=data/'studio.sqlite'
    with sqlite3.connect(database) as c:
        c.executescript('''
            CREATE TABLE videos(id TEXT, title TEXT, status TEXT, final_path TEXT, created REAL);
            CREATE TABLE video_attempts(video_id TEXT, attempt INTEGER, verdict TEXT,render_path TEXT,render_error TEXT);
            CREATE TABLE events(video_id TEXT,status TEXT,summary TEXT,created REAL);
            CREATE TABLE kv(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE assets(id TEXT,category TEXT,status TEXT,rights_status TEXT,active INTEGER,path TEXT);
        ''')
        c.execute('INSERT INTO videos VALUES (?,?,?,?,?)',('v1','Teste','REJECTED','videos/final/v1/attempt-01.mp4',123))
        c.execute('INSERT INTO video_attempts VALUES (?,?,?,?,?)',('v1',1,'REVISAR','videos/final/v1/attempt-01.mp4',None))
        c.execute('INSERT INTO events VALUES (?,?,?,?)',('v1','VISUAL_FALLBACK','Cena 1: arquivo ausente',124))
        c.execute('INSERT INTO kv VALUES (?,?)',('persona',json.dumps({'selected':'dante_palma','image_path':'assets/persona/dante.png'})))
        c.execute('INSERT INTO assets VALUES (?,?,?,?,?,?)',('m1','musica','READY','AUTHORIZED',1,'assets/uploads/audio/music.mp3'))
    handoff=tmp_path/'handoff/v1';handoff.mkdir(parents=True)
    (handoff/'visual-assets-attempt-1.json').write_text(json.dumps([{'scene':0,'start':0,'end':3,'segments':[{'type':'animated_gradient','asset_id':None,'path':None,'source':'generated_by_studio','source_class':'OWNED_GENERATED'}]}]))
    before=hashlib.sha256(database.read_bytes()).hexdigest()
    result=report(tmp_path,database,'v1')
    assert result['persona']['selected']=='dante_palma'
    assert not result['persona']['image']['exists_now']
    assert result['authorized_music_rows']==1
    assert result['scenes'][0]['segments'][0]['reason']=='fallback de gradiente selecionado'
    assert result['scenes'][0]['segments'][0]['used_in_render']=='UNVERIFIED'
    assert result['render_fallback_events'][0]['status']=='VISUAL_FALLBACK'
    assert hashlib.sha256(database.read_bytes()).hexdigest()==before
