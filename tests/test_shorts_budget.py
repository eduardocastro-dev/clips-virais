import sys
import types
from urllib.parse import parse_qs, urlsplit

from backend import core as db, integrations, worker


def test_only_shorts_search_targets():
    query = integrations.shorts_search_target()
    parsed = parse_qs(urlsplit(query).query)
    assert parsed['sp'] == ['EgIQCQ==']
    assert 'GTA 6' in parsed['search_query'][0]
    assert integrations.shorts_search_target({'platform':'youtube','url':'https://www.youtube.com/@canal'}) == 'https://www.youtube.com/@canal/shorts'


def test_discover_keeps_shorts_first_and_long_videos(monkeypatch):
    captured=[]
    class FakeYDL:
        def __init__(self, opts):pass
        def __enter__(self):return self
        def __exit__(self, *args):return None
        def extract_info(self, target, download=False):
            captured.append(target)
            return {'entries':[
                {'id':'abcdefghijk','url':'https://www.youtube.com/shorts/abcdefghijk','title':'GTA 6 detalhe', 'duration':32},
                {'id':'longvideo01','url':'https://www.youtube.com/watch?v=longvideo01','title':'GTA 6 trailer', 'duration':600},
                {'id':'short000001','url':'https://www.youtube.com/shorts/short000001','title':'Other game', 'duration':30},
            ]}
    monkeypatch.setitem(sys.modules,'yt_dlp',types.SimpleNamespace(YoutubeDL=FakeYDL))
    urls = integrations.discover()
    assert urls[0] == 'https://www.youtube.com/shorts/abcdefghijk'
    assert 'https://www.youtube.com/watch?v=longvideo01' in urls
    assert '/results?' in captured[0]
    rows = db.rows('SELECT * FROM opportunities')
    assert len(rows) == 2
    assert 'shorts' in rows[0]['metadata']


def test_radar_shows_all_sources_shorts_first(client):
    for idx, (url, platform) in enumerate([
        ('https://www.youtube.com/watch?v=abcdefghijk','youtube'),
        ('https://example.com/gta6','news'),
        ('https://www.youtube.com/shorts/abcdefghijk','youtube')]):
        db.execute('INSERT INTO opportunities VALUES (:id,:url,:platform,:title,:metadata,NULL,0,NULL)',
                   dict(id=str(idx), url=url, platform=platform, title='GTA 6', metadata='{}'))
    result = client.get('/api/state').json()['opportunities']
    assert len(result)==3 and result[0]['url'].endswith('/shorts/abcdefghijk')
    assert result[1]['platform']=='youtube' and result[2]['platform']=='news'


def test_success_reconciles_to_actual_tokens(monkeypatch):
    conf=db.settings();conf.routes['escritor'].model='studio-free';conf.daily_tokens=40000
    db.put_setting('settings',conf.model_dump())
    class Response:
        def json(self):
            return {'choices':[{'message':{'content':'{"ok":true}'}}],'usage':{'total_tokens':120}}
    monkeypatch.setattr(integrations,'request',lambda *a,**kw:Response())
    assert integrations.llm('escritor',None,{'test':1},{})=={'ok':True}
    assert db.rows('SELECT tokens FROM usage')[0]['tokens']==120


def test_rss_jobs_scan_enabled_source(monkeypatch):
    db.execute("INSERT INTO sources VALUES ('rss1','https://example.com/rss','Example',1,120,NULL,NULL)")
    called=[]
    monkeypatch.setattr(worker,'scan_feed',lambda source:called.append(source['url']))
    worker.perform({'kind':'source:rss1'})
    assert called==['https://example.com/rss']
