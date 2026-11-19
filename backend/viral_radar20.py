"""Monthly public top-channel ranking and strictly public 30-day YouTube radar.

No scraping of authenticated pages, cookies, private videos, or member content.
The ranking is an *index*; YouTube Data API verifies channel IDs and metrics.
Neither public accessibility nor a Creative Commons tag grants clip permission.
"""
from __future__ import annotations
import json
import math
import re
import statistics
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlsplit
from backend import core as db
from backend.integrations import youtube_get, request, IntegrationError

RADAR_WINDOW_DAYS = 30
RANKING_SOURCE = 'https://en.wikipedia.org/wiki/List_of_most-subscribed_YouTube_channels'
CHANNEL_PATTERN = re.compile(r'^UC[A-Za-z0-9_-]{22}$')


class RankingTables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.depth = 0
        self.tables = []
        self.table = None
        self.row = None
        self.cell = None
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'table':
            if self.depth == 0:
                self.table = [] if 'wikitable' in attributes.get('class','') else None
            self.depth += 1
        elif self.depth and self.table is not None:
            if tag == 'tr':
                self.row = []
            elif tag in ('td','th') and self.row is not None:
                self.cell = {'text': '', 'links': []}
            elif tag == 'a' and self.cell is not None:
                self.cell['links'].append(attributes.get('href',''))
            elif tag in ('sup','script','style'):
                self.skip += 1

    def handle_endtag(self, tag):
        if tag == 'table' and self.depth:
            self.depth -= 1
            if self.depth == 0:
                if self.table:
                    self.tables.append(self.table)
                self.table = None
                self.row = None
                self.cell = None
        elif self.depth and self.table is not None:
            if tag in ('td','th') and self.cell is not None and self.row is not None:
                self.cell['text'] = re.sub(r'\s+', ' ', unescape(self.cell['text'])).strip()
                self.row.append(self.cell)
                self.cell = None
            elif tag == 'tr' and self.row is not None:
                if self.row:
                    self.table.append(self.row)
                self.row = None
            elif tag in ('sup','script','style') and self.skip:
                self.skip -= 1

    def handle_data(self, data):
        if self.cell is not None and not self.skip:
            self.cell['text'] += data


def parse_ranking(page_html, limit=32):
    """Extract candidates from a public ranking table, not a hard-coded list."""
    parser = RankingTables()
    parser.feed(page_html)
    for table in parser.tables:
        headings = ' '.join(cell['text'].lower() for cell in table[0]) if table else ''
        if not any(key in headings for key in ('subscribers','subscribed')):
            continue
        if not any(key in headings for key in ('channel','name')):
            continue
        results = []
        seen = set()
        for row in table[1:]:
            if len(row) < 3:
                continue
            first = re.search(r'\d+', row[0]['text'])
            if not first:
                continue
            name = re.sub(r'\s+', ' ', row[1]['text']).strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            source_id = next((m.group(0) for cell in row[1:2] for link in cell['links']
                              if (m := re.search(r'UC[A-Za-z0-9_-]{22}',link))), '')
            results.append({'rank':int(first.group()), 'name':name,'channel_id':source_id})
            if len(results) >= limit:
                break
        if len(results) >= 10:
            return results
    raise IntegrationError('Ranking público indisponível ou formato não reconhecido; não inventar top 20.')


def _utc_time(value):
    try:
        value = str(value).replace('Z','+00:00')
        t = datetime.fromisoformat(value)
        return t.astimezone(timezone.utc) if t.tzinfo else t.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _write(file_name, data):
    db.atomic(db.DATA/file_name,json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def _load(file_name,default):
    p=db.DATA/file_name
    try:
        return json.loads(p.read_text('utf-8')) if p.is_file() else default
    except (OSError,ValueError):
        return default


def stored_top_creators():
    return _load('top_creators.json',{'status':'NOT_UPDATED','channels':[]})


def add_creator(channel_id):
    if not CHANNEL_PATTERN.fullmatch(channel_id or ''):
        raise ValueError('Informe o channel_id do YouTube, começando com UC.')
    items=youtube_get('channels',{'part':'snippet,statistics','id':channel_id}).get('items',[])
    if not items:
        raise ValueError('Channel ID público não encontrado pela API oficial.')
    creator = items[0]
    current=db.get_setting('creator_includes',[]) or []
    current=[item for item in current if item['channel_id']!=channel_id]
    current.append({'channel_id':channel_id,'name':creator['snippet']['title'],
                    'subscribers':int(creator.get('statistics',{}).get('subscriberCount') or 0),
                    'country':creator['snippet'].get('country'),
                    'language':creator['snippet'].get('defaultLanguage')})
    db.put_setting('creator_includes',current)
    return current


def exclude_creator(channel_id):
    if not CHANNEL_PATTERN.fullmatch(channel_id or ''):
        raise ValueError('Channel ID inválido.')
    excluded=set(db.get_setting('creator_excludes',[]) or [])
    excluded.add(channel_id)
    db.put_setting('creator_excludes',sorted(excluded))
    db.put_setting('creator_includes',[x for x in db.get_setting('creator_includes',[]) or []
                                      if x['channel_id']!=channel_id])
    return sorted(excluded)


def refresh_creators(force=False):
    now=datetime.now(timezone.utc)
    old=stored_top_creators()
    updated=_utc_time(old.get('updated_at'))
    if not force and updated and now-updated < timedelta(days=30) and len(old.get('channels',[])) >= 20:
        return old
    if not db.secret('youtube_api_key'):
        raise IntegrationError('Configure YouTube Data API key antes da atualização do top 20.')
    html=request('GET',RANKING_SOURCE,headers={'User-Agent':'GTAStudioRadar/1.0 (public research)'},timeout=25).text
    candidates=parse_ranking(html,35)
    excluded=set(db.get_setting('creator_excludes',[]) or [])
    channels=[]
    for candidate in candidates:
        if len(channels)>=20:
            break
        channel_id=candidate.get('channel_id')
        if not channel_id:
            results=youtube_get('search',{'part':'snippet','type':'channel','maxResults':3,
                                          'q':candidate['name']}).get('items',[])
            match=next((item for item in results
                        if item.get('snippet',{}).get('channelTitle','').casefold()==candidate['name'].casefold()),None)
            if not match:
                continue
            channel_id=match.get('id',{}).get('channelId','')
        if not CHANNEL_PATTERN.fullmatch(channel_id) or channel_id in excluded:
            continue
        profiles=youtube_get('channels',{'part':'snippet,statistics','id':channel_id}).get('items',[])
        if not profiles:
            continue
        item=profiles[0]
        info=item['snippet'];counts=item.get('statistics',{})
        if not counts.get('subscriberCount'):
            continue
        channels.append({'rank':candidate['rank'],'name':info['title'],
                         'channel_id':item['id'],'subscribers':int(counts['subscriberCount']),
                         'country':info.get('country'),'language':info.get('defaultLanguage'),
                         'updated_at':now.isoformat(),'source':RANKING_SOURCE})
    for extra in db.get_setting('creator_includes',[]) or []:
        if extra['channel_id'] not in {c['channel_id'] for c in channels} and extra['channel_id'] not in excluded:
            channels.append({**extra,'rank':None,'manual':True,'updated_at':now.isoformat()})
    data={'updated_at':now.isoformat(),'ranking_source':RANKING_SOURCE,
          'status':'READY' if len([x for x in channels if not x.get('manual')])==20 else 'PARTIAL',
          'channels':channels,'verified_count':len([x for x in channels if not x.get('manual')]),
          'manual_includes':len([x for x in channels if x.get('manual')]),
          'warning':None if len(channels)>=20 else 'Menos de 20 canais verificados; verificar API/ranking.'}
    _write('top_creators.json',data)
    return data


def _seconds(iso):
    match=re.fullmatch(r'P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?',iso or '')
    return (int(match.group(1) or 0)*86400 + int(match.group(2) or 0)*3600
            +int(match.group(3) or 0)*60+int(match.group(4) or 0)) if match else None


def allowed_public_video(item,now=None):
    now=now or datetime.now(timezone.utc)
    published=_utc_time(item.get('snippet',{}).get('publishedAt'))
    if not published or not timedelta(0) <= now-published <= timedelta(days=RADAR_WINDOW_DAYS):
        return False
    status=item.get('status',{})
    if status.get('privacyStatus') != 'public':
        return False
    content=item.get('contentDetails',{})
    if content.get('contentRating',{}).get('ytRating')=='ytAgeRestricted':
        return False
    restrictions=content.get('regionRestriction',{})
    if 'BR' in restrictions.get('blocked',[]):
        return False
    if restrictions.get('allowed') and 'BR' not in restrictions['allowed']:
        return False
    return True


def virality(item, channel_median, now=None):
    now=now or datetime.now(timezone.utc)
    published=_utc_time(item['snippet']['publishedAt'])
    hours=max(1,(now-published).total_seconds()/3600)
    stats=item.get('statistics',{})
    views=int(stats.get('viewCount') or 0)
    likes=int(stats.get('likeCount') or 0)
    comments=int(stats.get('commentCount') or 0)
    velocity=views/hours
    lift=views/max(1,channel_median)
    # Weighted and bounded 0-100; unlike raw views this considers channel norms.
    score=min(100,round(min(40,10*math.log10(1+velocity))+
                        min(18,150*likes/max(1,views))+
                        min(17,500*comments/max(1,views))+
                        min(25,10*math.log2(1+lift)),2))
    reason=f'{velocity:,.0f} visualizações/h; curtidas/views {likes/max(1,views):.2%}; ' \
           f'comentários/views {comments/max(1,views):.2%}; {lift:.2f}× mediana do canal'
    return {'score':score,'views_per_hour':round(velocity,2),
            'likes_per_view':round(likes/max(1,views),5),
            'comments_per_view':round(comments/max(1,views),5),
            'versus_channel_median':round(lift,3),'reason':reason}


def scan_recent(limit=30):
    if not db.secret('youtube_api_key'):
        raise IntegrationError('YouTube Data API key necessária para o radar de 30 dias.')
    creators=stored_top_creators()['channels']
    if not creators:
        raise IntegrationError('Top de canais vazio: execute atualizar top 20 antes do radar.')
    now=datetime.now(timezone.utc)
    all_videos=[]
    lives=[]
    for channel in creators[:35]:
        cid=channel['channel_id']
        details=youtube_get('channels',{'part':'contentDetails','id':cid}).get('items',[])
        if not details:
            continue
        upload=details[0].get('contentDetails',{}).get('relatedPlaylists',{}).get('uploads')
        if not upload:
            continue
        recent=youtube_get('playlistItems',{'part':'contentDetails','playlistId':upload,
                                           'maxResults':40}).get('items',[])
        ids=[item.get('contentDetails',{}).get('videoId') for item in recent]
        ids=[v for v in ids if isinstance(v,str) and re.fullmatch(r'[A-Za-z0-9_-]{11}',v)]
        if not ids:
            continue
        found=youtube_get('videos',{'part':'snippet,status,contentDetails,statistics,liveStreamingDetails',
                                   'id':','.join(ids)}).get('items',[])
        eligible=[x for x in found if allowed_public_video(x,now) and
                  x.get('snippet',{}).get('channelId')==cid]
        all_counts=[int(x.get('statistics',{}).get('viewCount') or 0) for x in eligible]
        median=statistics.median(all_counts) if all_counts else 1
        for item in eligible:
            stats=item.get('statistics',{})
            measured=virality(item,median,now)
            info={'id':item['id'],'url':'https://www.youtube.com/watch?v='+item['id'],
                  'channel_id':cid,'creator':channel['name'],
                  'title':item['snippet']['title'],
                  'published_at':item['snippet']['publishedAt'],
                  'duration_seconds':_seconds(item.get('contentDetails',{}).get('duration','')),
                  'metrics':{k:int(v) for k,v in stats.items() if k in ('viewCount','likeCount','commentCount')},
                  **measured,'rights':'REFERENCE_ONLY'}
            all_videos.append(info)
            ended=item.get('liveStreamingDetails',{}).get('actualEndTime')
            if ended and _utc_time(ended) and _utc_time(ended)<=now and info['duration_seconds']:
                lives.append({**info,'ended_at':ended,'ended':True})
    # Only GTA-related public sources feed the existing Shorts pipeline as
    # reference metadata. Discovery NEVER authorizes footage reuse.
    for candidate in all_videos:
        if not re.search(r'(?i)\b(?:gta\s*(?:6|vi)|grand theft auto|rockstar games)\b',
                         candidate['title']):
            continue
        meta={'url':candidate['url'],'platform':'youtube','title':candidate['title'],
              'published':candidate['published_at'],'metrics':candidate['metrics'],
              'source_profile':candidate['creator'],'channel_id':candidate['channel_id'],
              'rights':'REFERENCE_ONLY','discovery':'top20_official_api',
              'collected_at':now.timestamp()}
        db.execute("""INSERT INTO opportunities(id,url,platform,title,metadata,score,created,profile_id)
            VALUES (:id,:url,'youtube',:title,:metadata,:score,:created,NULL)
            ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata,score=excluded.score,
             title=excluded.title""",
            {'id':db.uid(),'url':candidate['url'],'title':candidate['title'],
             'metadata':json.dumps(meta,ensure_ascii=False),
             'score':round(candidate['score']/10,2),'created':now.timestamp()})
    all_videos.sort(key=lambda v:v['score'],reverse=True)
    lives.sort(key=lambda v:(v['published_at'],v['score']),reverse=True)
    radar={'day':db.today(),'window_days':RADAR_WINDOW_DAYS,'scanned_at':now.isoformat(),
           'top':all_videos[:max(1,min(100,int(limit)))],
           'examined':len(all_videos),'public_only':True,
           'clipping_rights_granted':False}
    _write('viral_radar_'+db.today()+'.json',radar)
    _write('recent_lives.json',{'scanned_at':now.isoformat(),'window_days':RADAR_WINDOW_DAYS,'items':lives})
    md=['# Viral Radar — '+db.today(),'','Janela: últimos 30 dias; API YouTube pública. '
        'Metadados não autorizam reaproveitamento de vídeo.','']
    md.extend(f"- **{i['creator']}** — {i['title']} — score {i['score']} — {i['url']} — {i['reason']}"
              for i in radar['top'])
    db.atomic(db.ROOT/'reports'/('viral_radar_'+db.today()+'.md'),'\n'.join(md)+'\n')
    return {'radar':radar,'recent_lives':lives}
