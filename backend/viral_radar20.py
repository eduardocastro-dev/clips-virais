"""Monthly public top-channel ranking and strictly public 30-day YouTube radar.

No scraping of authenticated pages, cookies, private videos, or member content.
The ranking is a public index; channel IDs and videos are read anonymously.
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
from backend.integrations import request, IntegrationError
from backend.public_youtube import public_channel_info, public_channel_entries, public_video_info, public_recent_video, public_ended_live, video_published_at

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
    """Allow operator-selected UC IDs without YouTube Data API credentials."""
    if not CHANNEL_PATTERN.fullmatch(channel_id or ''):
        raise ValueError('Informe um channel_id UC válido.')
    try:
        item=public_channel_info(channel_id)
    except IntegrationError:
        item={'channel_id':channel_id,'name':channel_id,'subscribers':None,
              'country':None,'language':None,'verified_publicly':False}
    current=db.get_setting('creator_includes',[]) or []
    current=[x for x in current if x['channel_id']!=channel_id]
    current.append({**item,'manual':True,'updated_at':datetime.now(timezone.utc).isoformat()})
    db.put_setting('creator_includes',current)
    catalog=stored_top_creators()
    catalog['channels']=[c for c in catalog.get('channels',[])
                         if c.get('channel_id')!=channel_id]
    catalog['channels'].append({**current[-1],'rank':None})
    catalog['manual_includes']=sum(bool(c.get('manual')) for c in catalog['channels'])
    catalog['status']='PARTIAL' if catalog.get('status')!='READY' else 'READY'
    _write('top_creators.json',catalog)
    return current


def exclude_creator(channel_id):
    if not CHANNEL_PATTERN.fullmatch(channel_id or ''):
        raise ValueError('Channel ID inválido.')
    excluded=set(db.get_setting('creator_excludes',[]) or [])
    excluded.add(channel_id)
    db.put_setting('creator_excludes',sorted(excluded))
    db.put_setting('creator_includes',[x for x in db.get_setting('creator_includes',[]) or []
                                      if x['channel_id']!=channel_id])
    catalog=stored_top_creators()
    catalog['channels']=[c for c in catalog.get('channels',[])
                         if c.get('channel_id')!=channel_id]
    _write('top_creators.json',catalog)
    return sorted(excluded)


def refresh_creators(force=False):
    """Best-effort public ranking; never synthesize IDs or subscriber counts."""
    now=datetime.now(timezone.utc)
    old=stored_top_creators()
    updated=_utc_time(old.get('updated_at'))
    manual=db.get_setting('creator_includes',[]) or []
    if not force and updated and now-updated < timedelta(days=30) and old.get('status')=='READY':
        return old
    warnings=[]
    try:
        html=request('GET',RANKING_SOURCE,
                     headers={'User-Agent':'Mozilla/5.0 GTAStudioPublicRadar/1.0'},
                     timeout=25).text
        candidates=parse_ranking(html,40)
    except (IntegrationError, ValueError) as exc:
        candidates=[]
        warnings.append('Ranking público indisponível: '+str(exc))
    excluded=set(db.get_setting('creator_excludes',[]) or [])
    channels=[]
    for candidate in candidates:
        if len(channels)>=20:
            break
        cid=candidate.get('channel_id')
        if not CHANNEL_PATTERN.fullmatch(cid or '') or cid in excluded:
            # A ranking name without its real channel ID cannot be guessed.
            continue
        try:
            verified=public_channel_info(cid)
        except (IntegrationError,ValueError):
            continue
        if not verified['verified_publicly']:
            continue
        channels.append({**verified,'rank':candidate['rank'],'manual':False,
                         'updated_at':now.isoformat(),'source':RANKING_SOURCE})
    for extra in manual:
        if extra['channel_id'] not in {c['channel_id'] for c in channels} and extra['channel_id'] not in excluded:
            channels.append({**extra,'rank':None,'manual':True,'updated_at':now.isoformat()})
    verified_count=sum(not c.get('manual') for c in channels)
    if verified_count<20:
        warnings.append('A fonte pública não disponibilizou 20 IDs UC verificáveis; lista parcial.')
    data={'updated_at':now.isoformat(),'ranking_source':RANKING_SOURCE,
          'status':'READY' if verified_count>=20 else 'PARTIAL',
          'channels':channels,'verified_count':verified_count,
          'manual_includes':sum(c.get('manual',False) for c in channels),
          'warning':' '.join(warnings) or None,
          'discovery_mode':'public_web_no_key'}
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
    """No-key channel tab scanning. Missing public metrics remain explicitly unknown."""
    creators=stored_top_creators().get('channels',[])
    now=datetime.now(timezone.utc)
    all_videos=[]
    lives=[]
    errors=[]
    seen=set()
    for channel in creators[:35]:
        cid=str(channel.get('channel_id') or '')
        if not CHANNEL_PATTERN.fullmatch(cid):
            continue
        sampled=[]
        for tab in ('shorts','videos','streams'):
            try:
                sampled.extend(public_channel_entries(cid,tab,limit=8))
            except (IntegrationError,ValueError) as exc:
                errors.append(f"{channel.get('name',cid)} ({tab}): {str(exc)[:120]}")
        eligible=[]
        for entry in sampled:
            vid=entry.get('id')
            if not isinstance(vid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid):
                continue
            if vid in seen:
                continue
            seen.add(vid)
            # A gaming-news radar should not inject unrelated global-channel topics.
            if not re.search(r'(?i)\b(?:gta\s*(?:6|vi|5|v)|grand theft auto|rockstar)\b',
                             str(entry.get('title') or '')):
                continue
            try:
                item=public_video_info('https://www.youtube.com/watch?v='+vid)
            except (IntegrationError,ValueError) as exc:
                errors.append(f"{vid}: {str(exc)[:120]}")
                continue
            if not public_recent_video(item,days=RADAR_WINDOW_DAYS,now=now):
                continue
            if item.get('channel_id')!=cid:
                continue
            eligible.append(item)
        counts=[v.get('view_count') for v in eligible
                if isinstance(v.get('view_count'),int) and v['view_count']>=0]
        median=statistics.median(counts) if counts else None
        for item in eligible:
            vid=item['id']
            date=video_published_at(item)
            if not date:
                continue
            views=item.get('view_count')
            likes=item.get('like_count')
            comments=item.get('comment_count')
            has_views=isinstance(views,int) and views>=0
            complete_metrics=(has_views and isinstance(likes,int) and
                              isinstance(comments,int))
            if complete_metrics:
                api_shaped={'snippet':{'publishedAt':date.isoformat()},
                            'statistics':{'viewCount':views}}
                if isinstance(likes,int):api_shaped['statistics']['likeCount']=likes
                if isinstance(comments,int):api_shaped['statistics']['commentCount']=comments
                evaluated=virality(api_shaped,median or 1,now=now)
            else:
                evaluated={'score':None,'views_per_hour':None,'likes_per_view':None,
                           'comments_per_view':None,'versus_channel_median':None,
                           'reason':'Visualizações ou interações públicas incompletas; pontuação não atribuída.'}
            url='https://www.youtube.com/watch?v='+vid
            info={'id':vid,'url':url,'channel_id':cid,
                  'creator':channel.get('name',cid),'title':item.get('title') or vid,
                  'published_at':date.isoformat(),
                  'duration_seconds':item.get('duration'),
                  'metrics':{'viewCount':views if has_views else None,
                             'likeCount':likes if isinstance(likes,int) else None,
                             'commentCount':comments if isinstance(comments,int) else None},
                  **evaluated,'rights':'REFERENCE_ONLY',
                  'discovery':'public_web_no_key'}
            all_videos.append(info)
            if public_ended_live(item,days=RADAR_WINDOW_DAYS,now=now):
                lives.append({**info,'ended_at':date.isoformat(),'ended':True})
            if info['score'] is not None:
                meta={'url':url,'platform':'youtube','title':info['title'],
                      'published':date.isoformat(),'metrics':info['metrics'],
                      'source_profile':info['creator'],'channel_id':cid,
                      'rights':'REFERENCE_ONLY','discovery':'public_web_no_key',
                      'collected_at':now.timestamp()}
                db.execute("""INSERT INTO opportunities(id,url,platform,title,metadata,score,created,profile_id)
                    VALUES (:id,:url,'youtube',:title,:metadata,:score,:created,NULL)
                    ON CONFLICT(url) DO UPDATE SET metadata=excluded.metadata,score=excluded.score,
                    title=excluded.title""",
                    {'id':db.uid(),'url':url,'title':info['title'],
                     'metadata':json.dumps(meta,ensure_ascii=False),
                     'score':round(float(info['score'])/10,2),'created':now.timestamp()})
    all_videos.sort(key=lambda x:(x['score'] is not None,x['score'] or 0),reverse=True)
    lives.sort(key=lambda x:(x['published_at'],x['score'] or 0),reverse=True)
    radar={'day':db.today(),'window_days':RADAR_WINDOW_DAYS,
           'scanned_at':now.isoformat(),'top':all_videos[:max(1,min(100,int(limit)))],
           'examined':len(all_videos),'public_only':True,'clipping_rights_granted':False,
           'discovery_mode':'public_web_no_key',
           'status':'READY' if all_videos else 'PARTIAL',
           'warnings':errors[:30] if errors else ([] if creators else ['Nenhum canal configurado.'])}
    _write('viral_radar_'+db.today()+'.json',radar)
    _write('recent_lives.json',{'scanned_at':now.isoformat(),
                                'window_days':RADAR_WINDOW_DAYS,'items':lives})
    md=['# Viral Radar — '+db.today(),'','Fonte: metadados públicos sem YouTube Data API. '
        'Acessibilidade pública não concede licença de reutilização.','']
    md.extend(f"- **{x['creator']}** — {x['title']} — score "
              f"{x['score'] if x['score'] is not None else 'indisponível'}"
              f" — {x['url']} — {x['reason']}" for x in radar['top'])
    if errors:
        md.extend(['','## Fontes temporariamente indisponíveis',*('- '+x for x in errors[:20])])
    db.atomic(db.ROOT/'reports'/('viral_radar_'+db.today()+'.md'),'\n'.join(md)+'\n')
    return {'radar':radar,'recent_lives':lives}
