import json
import os
import secrets
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, event, text
from backend.contracts import Settings, Handoff

ROOT = Path(os.getenv('STUDIO_FILES', '.')).resolve()
DATA = Path(os.getenv('STUDIO_DATA', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
for folder in ['handoff', 'videos/raw', 'videos/processing', 'videos/final', 'output', 'reports', 'cache', 'logs', 'assets/shorts', 'assets/gameplay', 'assets/images', 'assets/persona', 'assets/personas', 'assets/music', 'assets/sfx', 'assets/clips', 'assets/uploads/video', 'assets/uploads/audio', 'assets/uploads/image', 'assets/uploads/font', 'assets/uploads/subtitle', 'assets/uploads/logo', 'temp']:
    (ROOT / folder).mkdir(parents=True, exist_ok=True)
engine = create_engine('sqlite:///' + str(DATA / 'studio.sqlite'), connect_args={'timeout': 30})


@event.listens_for(engine, 'connect')
def pragmas(conn, _):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')


@contextmanager
def transaction():
    with engine.connect() as c:
        c.exec_driver_sql('BEGIN IMMEDIATE')
        try:
            yield c
            c.commit()
        except Exception:
            c.rollback()
            raise


def init_db():
    statements = [
        'CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT NOT NULL)',
        '''CREATE TABLE IF NOT EXISTS videos (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, url TEXT UNIQUE,
        platform TEXT, title TEXT, rights TEXT, evidence TEXT, credits TEXT, instructions TEXT,
        template TEXT, duration INTEGER, status TEXT, stage TEXT, revision INTEGER DEFAULT 0,
        test INTEGER DEFAULT 0, metadata TEXT DEFAULT '{}', created REAL, updated REAL, error TEXT,
        approved INTEGER DEFAULT 0, script_hash TEXT, final_path TEXT)''',
        '''CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, video_id TEXT, kind TEXT, status TEXT,
        attempts INTEGER DEFAULT 0, due REAL, lease REAL, owner TEXT, error TEXT, unique_key TEXT UNIQUE,
        FOREIGN KEY(video_id) REFERENCES videos(id))''',
        '''CREATE TABLE IF NOT EXISTS publications (id TEXT PRIMARY KEY, video_id TEXT NOT NULL,
        platform TEXT, status TEXT, external_id TEXT, url TEXT, output_path TEXT, error TEXT, updated REAL,
        UNIQUE(video_id,platform), FOREIGN KEY(video_id) REFERENCES videos(id))''',
        '''CREATE TABLE IF NOT EXISTS notifications (id TEXT PRIMARY KEY, event_key TEXT UNIQUE,
        message TEXT, created REAL, delivered INTEGER DEFAULT 0, read INTEGER DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS profiles (id TEXT PRIMARY KEY, url TEXT UNIQUE, platform TEXT,
        enabled INTEGER, interval_minutes INTEGER, priority INTEGER, last_checked REAL, error TEXT)''',
        '''CREATE TABLE IF NOT EXISTS opportunities (id TEXT PRIMARY KEY, url TEXT UNIQUE, platform TEXT,
        title TEXT, metadata TEXT, score REAL, created REAL, profile_id TEXT)''',
        '''CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, url TEXT UNIQUE, name TEXT, enabled INTEGER,
        interval_minutes INTEGER, last_checked REAL, error TEXT)''',
        '''CREATE TABLE IF NOT EXISTS metrics (id TEXT PRIMARY KEY, publication_id TEXT, observed REAL,
        data TEXT, FOREIGN KEY(publication_id) REFERENCES publications(id))''',
        '''CREATE TABLE IF NOT EXISTS live_clips (
            id TEXT PRIMARY KEY, video_id TEXT NOT NULL UNIQUE, channel_id TEXT NOT NULL,
            title TEXT NOT NULL, source_url TEXT NOT NULL, rights_evidence TEXT NOT NULL,
            status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, score REAL,
            segment_start REAL, segment_end REAL, file_path TEXT, error TEXT,
            created REAL NOT NULL, updated REAL NOT NULL)''',
        'CREATE INDEX IF NOT EXISTS idx_live_clips_status_created ON live_clips(status,created)',
        """CREATE TABLE IF NOT EXISTS live_clip_outputs (
            id TEXT PRIMARY KEY, parent_id TEXT NOT NULL,
            ordinal INTEGER NOT NULL, title TEXT,
            status TEXT NOT NULL, score REAL, segment_start REAL,
            segment_end REAL, file_path TEXT, metadata_path TEXT,
            cover_path TEXT, reason TEXT, error TEXT,
            created REAL NOT NULL, updated REAL NOT NULL,
            UNIQUE(parent_id,ordinal),
            FOREIGN KEY(parent_id) REFERENCES live_clips(id))""",
        'CREATE INDEX IF NOT EXISTS idx_live_clip_outputs_parent ON live_clip_outputs(parent_id,ordinal)',
        '''CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, video_id TEXT, agent TEXT,
        status TEXT, summary TEXT, tokens INTEGER DEFAULT 0, created REAL)''',
        'CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, expires REAL)',
        'CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, tokens INTEGER, cost REAL)',
        """CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY, kind TEXT NOT NULL, source_id TEXT, url TEXT,
            title TEXT, channel TEXT, source_class TEXT NOT NULL, rights_status TEXT NOT NULL,
            evidence TEXT, path TEXT, status TEXT NOT NULL, metadata TEXT,
            duration REAL, created REAL, updated REAL, error TEXT,
            UNIQUE(kind,source_id))""",
        """CREATE TABLE IF NOT EXISTS upload_sessions (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            received INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL, category TEXT,
            tags TEXT, source_class TEXT, evidence TEXT, media_type TEXT,
            sha256 TEXT, updated REAL, created REAL, error TEXT)""",
        '''CREATE TABLE IF NOT EXISTS video_attempts (video_id TEXT NOT NULL, attempt INTEGER NOT NULL,
        verdict TEXT NOT NULL, score REAL, details TEXT NOT NULL, render_path TEXT, render_error TEXT,
        created REAL NOT NULL, PRIMARY KEY(video_id,attempt),
        FOREIGN KEY(video_id) REFERENCES videos(id))''',
    ]
    with engine.begin() as c:
        old_version=int(c.exec_driver_sql('PRAGMA user_version').scalar() or 0)
        for sql in statements:
            c.execute(text(sql))
        columns = {r[1] for r in c.exec_driver_sql('PRAGMA table_info(publications)')}
        for name, typ in [('provider','TEXT'),('remote_id','TEXT'),('scheduled_for','REAL')]:
            if name not in columns:
                c.exec_driver_sql(f'ALTER TABLE publications ADD COLUMN {name} {typ}')
        video_cols={r[1] for r in c.exec_driver_sql('PRAGMA table_info(videos)')}
        for name, typ in [('approved_at','REAL'),('manual_decision','TEXT'),('manual_by','TEXT'),
                          ('manual_at','REAL'),('render_error','TEXT')]:
            if name not in video_cols:
                c.exec_driver_sql(f'ALTER TABLE videos ADD COLUMN {name} {typ}')
        clip_cols={r[1] for r in c.exec_driver_sql('PRAGMA table_info(live_clips)')}
        if 'stage' not in clip_cols:
            c.exec_driver_sql('ALTER TABLE live_clips ADD COLUMN stage TEXT')
        if 'webcam_anchor' not in clip_cols:
            c.exec_driver_sql("ALTER TABLE live_clips ADD COLUMN webcam_anchor TEXT DEFAULT 'bottom_left'")
        if 'cut_target' not in clip_cols:
            c.exec_driver_sql("ALTER TABLE live_clips ADD COLUMN cut_target INTEGER DEFAULT 3")
        # Preserve old one-cut deliveries as a visible legacy child; never
        # rewrite, delete or count existing clips more than once.
        c.exec_driver_sql("""INSERT OR IGNORE INTO live_clip_outputs
          (id,parent_id,ordinal,title,status,score,segment_start,segment_end,
           file_path,created,updated)
          SELECT 'legacy-' || id,id,1,title,status,score,segment_start,
                 segment_end,file_path,created,updated
          FROM live_clips WHERE file_path IS NOT NULL AND file_path!=''""")
        asset_cols={r[1] for r in c.exec_driver_sql('PRAGMA table_info(assets)')}
        for name,typ in [('category','TEXT'),('tags',"TEXT DEFAULT '[]'"),('active','INTEGER DEFAULT 1'),
                         ('parent_id','TEXT'),('clip_index','INTEGER'),('clip_total','INTEGER'),
                         ('usage_count','INTEGER DEFAULT 0'),('sha256','TEXT'),('media_type','TEXT'),
                         ('size_bytes','INTEGER')]:
            if name not in asset_cols:c.exec_driver_sql(f'ALTER TABLE assets ADD COLUMN {name} {typ}')
        c.exec_driver_sql('CREATE INDEX IF NOT EXISTS idx_assets_parent ON assets(parent_id)')
        c.exec_driver_sql('CREATE INDEX IF NOT EXISTS idx_assets_tags ON assets(category,active,usage_count)')
        if old_version < 3:
            # Repair previews for legacy rejected videos, whose MP4 existed but
            # whose final_path was written only on evaluator approval.
            for v in c.execute(text('SELECT id,final_path FROM videos')).mappings():
                legacy=ROOT/'videos/final'/(v['id']+'.mp4')
                if not v['final_path'] and legacy.is_file():
                    c.execute(text('UPDATE videos SET final_path=:path WHERE id=:id'),
                              {'path':str(legacy.relative_to(ROOT)),'id':v['id']})
                handoffs=ROOT/'handoff'/v['id']
                for old in sorted(handoffs.glob('review-*.json')):
                    try:
                        n=int(old.stem.rsplit('-',1)[-1])+1  # old index was zero based
                        details=json.loads(old.read_text('utf-8'))
                        details.setdefault('reason_full','\n'.join(details.get('corrections',[])) or details.get('summary','Sem motivo registrado.'))
                    except (ValueError,TypeError,json.JSONDecodeError):
                        continue
                    path=str(legacy.relative_to(ROOT)) if legacy.is_file() and n==max(1,len(list(handoffs.glob('review-*.json')))) else None
                    c.execute(text('''INSERT OR IGNORE INTO video_attempts
                       (video_id,attempt,verdict,score,details,render_path,render_error,created)
                       VALUES (:id,:n,:verdict,:score,:details,:path,NULL,:created)'''),
                       {'id':v['id'],'n':n,'verdict':details.get('verdict','LEGADO'),'score':details.get('score'),
                        'details':json.dumps(details,ensure_ascii=False),'path':path,'created':legacy.stat().st_mtime if legacy.exists() else time.time()})
        c.execute(text('PRAGMA user_version=3'))


def rows(sql, params=None):
    with engine.connect() as c:
        return [dict(x) for x in c.execute(text(sql), params or {}).mappings()]


def execute(sql, params=None):
    with engine.begin() as c:
        return c.execute(text(sql), params or {}).rowcount


def uid():
    return uuid.uuid4().hex


def today():
    return datetime.now(ZoneInfo(os.getenv('STUDIO_TIMEZONE', 'America/Sao_Paulo'))).date().isoformat()


def get_setting(key, default=None):
    result = rows('SELECT value FROM kv WHERE key=:key', {'key': key})
    return json.loads(result[0]['value']) if result else default


def put_setting(key, value):
    execute('INSERT INTO kv VALUES (:key,:value) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
            {'key': key, 'value': json.dumps(value, ensure_ascii=False)})


def settings():
    return Settings.model_validate(get_setting('settings', {}))


def cipher():
    path = DATA / 'secrets.key'
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(Fernet.generate_key())
    except FileExistsError:
        pass
    return Fernet(path.read_bytes())


def set_secret(name, value):
    put_setting('secret:' + name, cipher().encrypt(value.encode()).decode())


def secret(name):
    value = get_setting('secret:' + name)
    return cipher().decrypt(value.encode()).decode() if value else ''


def atomic(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uid() + '.tmp')
    tmp.write_text(content, encoding='utf-8')
    os.replace(tmp, path)


def artifact(video_id, agent, data=None, files=None, summary='Etapa concluída.', status='CONCLUIDO', next_agent='diretor'):
    video = rows('SELECT run_id FROM videos WHERE id=:id', {'id': video_id})[0]
    item = Handoff(id=video_id, run_id=video['run_id'], status=status, proximo_agente=next_agent,
                   resumo=summary, arquivos=files or [], dados=data or {})
    target = ROOT / 'handoff' / video_id / f'{agent}.json'
    # Compact JSON; large payloads stay in files referenced in arquivos.
    atomic(target, item.model_dump_json(indent=2) if not data else item.model_dump_json())
    return item


def read_artifact(video_id, agent):
    return Handoff.model_validate_json((ROOT / 'handoff' / video_id / f'{agent}.json').read_text('utf-8'))


def log_event(video_id, agent, status, summary, tokens=0):
    execute('INSERT INTO events VALUES (:id,:video,:agent,:status,:summary,:tokens,:created)',
            dict(id=uid(), video=video_id, agent=agent, status=status, summary=summary[:600], tokens=tokens, created=time.time()))


def notify(key, message):
    execute('INSERT OR IGNORE INTO notifications(id,event_key,message,created) VALUES (:id,:key,:message,:now)',
            dict(id=uid(), key=key, message=message[:1000], now=time.time()))


def cache_get(key):
    found = rows('SELECT value FROM cache WHERE key=:key AND expires>:now', dict(key=key, now=time.time()))
    return json.loads(found[0]['value']) if found else None


def cache_set(key, value, ttl=3600):
    execute('INSERT INTO cache VALUES (:key,:value,:expires) ON CONFLICT(key) DO UPDATE SET value=excluded.value, expires=excluded.expires',
            dict(key=key, value=json.dumps(value), expires=time.time() + ttl))


def enqueue(kind, video_id=None, unique_key=None, due=None):
    execute('INSERT OR IGNORE INTO jobs(id,video_id,kind,status,due,unique_key) VALUES (:id,:video,:kind,\'QUEUED\',:due,:key)',
            dict(id=uid(), video=video_id, kind=kind, due=due or time.time(), key=unique_key or uid()))


def claim(owner):
    now = time.time()
    with transaction() as c:
        c.execute(text("UPDATE jobs SET status='QUEUED', owner=NULL WHERE status='RUNNING' AND lease<:now"), {'now': now})
        # Operator-submitted live cuts must not wait behind long discovery scans.
        # Lower-priority radar jobs remain queued; no in-flight job is killed.
        priority = ("CASE "
                    "WHEN kind LIKE 'live_cut:%' THEN 0 "
                    "WHEN kind='pipeline' THEN 1 "
                    "WHEN kind IN ('radar20_scan','top20_refresh') THEN 9 "
                    "ELSE 3 END")
        job = c.execute(text(
            "SELECT * FROM jobs WHERE status='QUEUED' AND due<=:now "
            "ORDER BY " + priority + ", due, id LIMIT 1"
        ), {'now': now}).mappings().first()
        if not job:
            return None
        c.execute(text("UPDATE jobs SET status='RUNNING', attempts=attempts+1, owner=:owner, lease=:lease WHERE id=:id"),
                  dict(owner=owner, lease=now+180, id=job['id']))
        return dict(job)


def safe_file(relative):
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        raise ValueError('Arquivo inexistente ou fora do diretório permitido.')
    return path


def local_day_bounds():
    from datetime import datetime, time as dtime, timedelta
    zone=ZoneInfo('America/Sao_Paulo')
    start=datetime.combine(datetime.now(zone).date(),dtime.min,tzinfo=zone)
    return start.timestamp(), (start+timedelta(days=1)).timestamp()


def production_usage(connection=None):
    """One row per real production. Revisions and tests never count twice.

    Active real jobs hold a slot; approvals count on approval day. Rejected,
    failed and discarded work releases the slot. No legacy kv daily counter.
    """
    begin,end=local_day_bounds()
    statement=text("""SELECT COUNT(*) FROM videos WHERE test=0 AND (
        (status IN ('QUEUED','PROCESSING','RETRY','PENDING_RIGHTS_REVIEW') AND created>=:start AND created<:end)
        OR (status='APPROVED' AND COALESCE(approved_at,created)>=:start AND COALESCE(approved_at,created)<:end)
    )""")
    if connection is not None:
        return int(connection.execute(statement,{'start':begin,'end':end}).scalar() or 0)
    with engine.connect() as c:
        return int(c.execute(statement,{'start':begin,'end':end}).scalar() or 0)
