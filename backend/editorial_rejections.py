"""Editorial veto memory: manually discarded subjects are not future auto jobs.

A manual rejection is feedback about an unwanted source or topic, not a
transient rendering failure. Keep it independently of the video/MP4 lifecycle.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from backend import core as db

COOLDOWN_DAYS = 30
COOLDOWN_SECONDS = COOLDOWN_DAYS * 86400
# Generic GTA VI vocabulary does not identify an editorial subject.
_NOISE = set("""
gta gta6 6 vi v grand theft auto rockstar videogame game video videos gaming
short shorts youtube youtuber official oficial novo nova novos novas new
hoje agora today ontem yesterday atualizado update atualizacao novidades
sobre falando veja vejaa vejao tudo todos todas muito mais para pelo pela
do dos da das de em no na nos nas um uma uns umas o os a as e ou com sem
por que qual quais como sera será foi pode voce voces eu minha meu sua seu
parte episodio live stream streaming reacts reaction react ao vivo
the and in at of for from on this that with is are was were about
breaking news noticia noticias urgente real verdade rumor rumores
circula circulam atribuido atribuida atribuidos atribuidas internet web
assistir assista confira inacreditavel incrivel sensacional impressionante
""".split())
_GENERIC = {'aguardando', 'pesquisa', 'teste', 'tecnico', 'studio'}


def normalize_source(value: str | None) -> str:
    """Stable identity for the same public reference (watch and Shorts links)."""
    url=str(value or '').split('#studio-variant=',1)[0].strip()
    if not url or url.startswith('test:'):
        return ''
    try:
        from backend.public_youtube import video_id_from_url
        ident=video_id_from_url(url)
        return 'https://www.youtube.com/watch?v='+ident
    except ValueError:
        pass
    try:
        from backend.contracts import platform_url
        return platform_url(url)[1]
    except ValueError:
        pass
    parsed=urlsplit(url)
    if parsed.scheme not in ('http','https') or not parsed.hostname:
        return ''
    # Strip tracking parameters, never collapse distinct articles.
    query=urlencode(sorted((k,v) for k,v in parse_qsl(parsed.query,keep_blank_values=True)
                           if not k.lower().startswith('utm_') and
                           k.lower() not in ('fbclid','gclid')))
    return urlunsplit((parsed.scheme.lower(),parsed.hostname.lower(),
                       parsed.path.rstrip('/') or '/',query,''))


def topic_tokens(title: str | None) -> frozenset[str]:
    text=unicodedata.normalize('NFKD',str(title or '').lower())
    text=''.join(c for c in text if not unicodedata.combining(c))
    text=re.sub(r'grand\s+theft\s+auto\s*(?:vi|6)?|gta\s*(?:vi|6)', ' gta6 ',text)
    parts=re.findall(r'[a-z0-9]+',text)
    return frozenset(p[:-1] if len(p)>5 and p.endswith('s') else p
                     for p in parts if len(p)>=4 and p not in _NOISE and
                     p not in _GENERIC)


def same_topic(first: str | None, second: str | None) -> bool:
    left,right=topic_tokens(first),topic_tokens(second)
    if min(len(left),len(right))<2:
        return False
    shared=len(left & right)
    if shared<2:
        return False
    # High containment plus reasonable overlap: avoids blocking all GTA news
    # and catches paraphrases / reordered headlines about the same event.
    return shared/min(len(left),len(right))>=.8 and shared/len(left|right)>=.48


def _valid_title(title: str | None) -> bool:
    return bool(title and str(title).strip() and
                not set(topic_tokens(title)).issubset(_GENERIC) and
                len(topic_tokens(title))>=2)


def _legacy_import() -> None:
    """Import manual rejects previously purged from deletion_log.json once."""
    if db.get_setting('editorial_discard_legacy_import_v1',False):
        return
    path=db.DATA/'deletion_log.json'
    try:
        entries=json.loads(path.read_text('utf-8')).get('entries',[]) if path.is_file() else []
    except (OSError,ValueError,AttributeError,TypeError):
        entries=[]
    now=time.time()
    for item in entries[-10000:]:
        if not isinstance(item,dict) or item.get('reason')!='manual':
            continue
        title=str(item.get('title') or '').strip()
        if not _valid_title(title):
            continue
        ident=str(item.get('id') or '')
        if not re.fullmatch(r'[a-f0-9]{32}',ident):
            continue
        if db.get_setting('editorial_unblocked:'+ident,False):
            continue
        try:
            created=float(item.get('discarded_at') or item.get('deleted_at') or now)
        except (ValueError,TypeError):
            continue
        if created+COOLDOWN_SECONDS<=now:
            continue
        db.execute("""INSERT OR IGNORE INTO editorial_rejections
                   (id,video_id,title,titles_json,source_url,created,expires_at)
                   VALUES (:id,:video,:title,:titles,'',:created,:expires)""",
                   {'id':'legacy:'+ident,'video':ident,'title':title,
                    'titles':json.dumps([title],ensure_ascii=False),
                    'created':created,'expires':created+COOLDOWN_SECONDS})
    db.put_setting('editorial_discard_legacy_import_v1',True)


def active() -> list[dict]:
    _legacy_import()
    now=time.time()
    db.execute('DELETE FROM editorial_rejections WHERE expires_at<=:now',{'now':now})
    return db.rows('SELECT * FROM editorial_rejections ORDER BY created DESC')


def blocked(url: str | None, title: str | None,
            entries: list[dict] | None=None) -> dict | None:
    """Return grounded veto; no AI model or approximate category blocking."""
    current=entries if entries is not None else active()
    source=normalize_source(url)
    for row in current:
        if source and row['source_url'] and source==row['source_url']:
            return {**row,'reason':'same_source'}
        titles=json.loads(row['titles_json'] or '[]')
        if title and any(same_topic(title,t) for t in titles):
            return {**row,'reason':'same_topic'}
    return None


def _titles_for_video(video: dict) -> list[str]:
    titles=[]
    for title in (video.get('title'),):
        if _valid_title(title) and title not in titles:
            titles.append(str(title).strip())
    try:
        info=json.loads(video.get('metadata') or '{}')
        title=info.get('title')
        if _valid_title(title) and title not in titles:
            titles.append(str(title).strip())
    except (ValueError,TypeError,AttributeError):
        pass
    source=normalize_source(video.get('url'))
    if source:
        candidates=db.rows(
            """SELECT title,url FROM opportunities
               WHERE url=:original OR url=:normalized
               ORDER BY created DESC LIMIT 5""",
            {'original':video.get('url'),'normalized':source})
        # Some catalog items retain /shorts/ URL; compare canonical identities.
        if not candidates:
            from backend.public_youtube import video_id_from_url
            try:
                ident=video_id_from_url(source)
                candidates=db.rows(
                    """SELECT title,url FROM opportunities
                       WHERE platform='youtube' AND url LIKE :pattern
                       ORDER BY created DESC LIMIT 10""",
                    {'pattern':'%'+ident+'%'})
            except ValueError:
                pass
        for candidate in candidates:
            title=candidate.get('title')
            if _valid_title(title) and title not in titles:
                titles.append(str(title).strip())
    return titles[:8]


def remember_manual(video: dict, *, when: float | None=None) -> dict | None:
    if video.get('test'):
        return None
    when=time.time() if when is None else when
    titles=_titles_for_video(video)
    source=normalize_source(video.get('url'))
    if not titles and not source:
        return None
    label=titles[0] if titles else str(video.get('title') or 'Fonte descartada')
    entry={'id':'manual:'+str(video['id']),
           'video':str(video['id']),'title':label,
           'titles':json.dumps(titles,ensure_ascii=False),
           'source':source,'created':when,'expires':when+COOLDOWN_SECONDS}
    db.execute("""INSERT INTO editorial_rejections
               (id,video_id,title,titles_json,source_url,created,expires_at)
               VALUES (:id,:video,:title,:titles,:source,:created,:expires)
               ON CONFLICT(id) DO UPDATE SET
               title=excluded.title,titles_json=excluded.titles_json,
               source_url=excluded.source_url,expires_at=excluded.expires_at""",
               entry)
    return {'title':label,'expires_at':entry['expires']}


def forget_video(video_id: str) -> None:
    db.execute('DELETE FROM editorial_rejections WHERE video_id=:id',{'id':video_id})


def forget_entry(entry_id: str) -> bool:
    selected=db.rows('SELECT video_id FROM editorial_rejections WHERE id=:id',
                     {'id':entry_id})
    if not selected:
        return False
    # The discard's two-hour media purge must never silently re-add a veto
    # that the operator has already explicitly removed.
    db.put_setting('editorial_unblocked:'+selected[0]['video_id'],True)
    return bool(db.execute('DELETE FROM editorial_rejections WHERE id=:id',
                           {'id':entry_id}))
