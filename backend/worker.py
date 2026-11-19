import json
import logging
import shutil
import smtplib
import sys
import threading
import time
from email.message import EmailMessage
from backend import core as db
from backend.integrations import IntegrationError, discover, collect_metrics, request
from backend.pipeline import run_pipeline, create_video, daily_report, PipelineInterrupted
from backend.contracts import ImportRequest
from backend.sources import scan_feed, seed_default_sources

logging.basicConfig(level=logging.INFO, format='%(message)s')



def catalog_discovered_shorts():
    """Catalog only: metadata for third-party clips does not grant download rights."""
    from backend.assets import register_short
    for row in db.rows("SELECT metadata FROM opportunities WHERE platform='youtube' ORDER BY created DESC LIMIT 150"):
        try:
            meta=json.loads(row['metadata'])
            if meta.get('format')=='short' or '/shorts/' in meta.get('url',''):
                register_short(meta)
        except (ValueError,KeyError,TypeError):
            continue


def cleanup():
    cutoff = time.time() - db.settings().retention_days * 86400
    # Only media belonging to finished videos is eligible. Pending manual files survive indefinitely.
    for v in db.rows("SELECT * FROM videos WHERE updated<:cutoff AND status IN ('APPROVED','REJECTED','FAILED')", {'cutoff': cutoff}):
        pending = db.rows("SELECT id FROM publications WHERE video_id=:id AND status!='PUBLICADO'", {'id': v['id']})
        recent = db.rows('SELECT id FROM publications WHERE video_id=:id AND updated>:cutoff', dict(id=v['id'],cutoff=cutoff))
        preserve_final = bool(pending or recent)
        for root in ['videos/raw', 'videos/processing']:
            target = (db.ROOT / root / (v['id'] if root.endswith('processing') else v['id'] + '.mp4')).resolve()
            allowed = (db.ROOT / root).resolve()
            if target.is_relative_to(allowed) and not target.is_symlink():
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.is_file():
                    target.unlink()
        if not preserve_final:
            for p in db.rows('SELECT output_path FROM publications WHERE video_id=:id', {'id': v['id']}):
                if p['output_path']:
                    target = (db.ROOT / p['output_path']).resolve()
                    if target.is_relative_to((db.ROOT / 'output').resolve()) and target.is_file():
                        target.unlink()
    from backend import production_media
    production_media.prune_stale(db.settings().temporary_retention_days)
    from backend.uploads import prune_sessions
    prune_sessions(db.settings().temporary_retention_days)
    db.execute('DELETE FROM cache WHERE expires<:now', {'now': time.time()})


def deliver_notifications():
    token, chat = db.secret('telegram_token'), db.secret('telegram_chat_id')
    smtp_host, smtp_to = db.secret('smtp_host'), db.secret('smtp_to')
    if not (token and chat) and not (smtp_host and smtp_to):
        return
    for n in db.rows('SELECT * FROM notifications WHERE delivered=0 ORDER BY created LIMIT 10'):
        # Per-channel durable intent avoids duplicate sends after uncertain responses.
        for channel in ['telegram', 'email']:
            if (channel == 'telegram' and not (token and chat)) or (channel == 'email' and not (smtp_host and smtp_to)):
                continue
            key = f'notification:{channel}:{n["id"]}'
            if db.get_setting(key):
                continue
            db.put_setting(key, 'sending')
            try:
                if channel == 'telegram':
                    request('POST', f'https://api.telegram.org/bot{token}/sendMessage', json={'chat_id': chat, 'text': n['message']})
                else:
                    message = EmailMessage()
                    message['Subject'] = 'GTA Studio — notificação'
                    message['From'] = db.secret('smtp_from')
                    message['To'] = smtp_to
                    message.set_content(n['message'])
                    with smtplib.SMTP(smtp_host, int(db.secret('smtp_port') or 587), timeout=20) as smtp:
                        smtp.starttls()
                        smtp.login(db.secret('smtp_user'), db.secret('smtp_password'))
                        smtp.send_message(message)
                db.put_setting(key, 'sent')
            except Exception:
                db.put_setting(key, 'uncertain')
                db.log_event(None, 'notifications', 'ERROR', f'Entrega {channel} incerta; evento preservado no painel.')
        db.execute('UPDATE notifications SET delivered=1 WHERE id=:id', {'id': n['id']})


def scheduler():
    config = db.settings()
    now = time.time()
    if config.emergency_stop:
        return
    # Lightweight polling watcher works for bind-mounted /assets on Windows,
    # where inotify events are not reliable across Docker Desktop volumes.
    if now - db.get_setting('last_asset_scan',0) > 30:
        from backend.assets import sync_library
        try:
            result=sync_library()
            db.put_setting('last_asset_scan',now)
            if result.get('registered'):
                logging.info(json.dumps({'assets_registered':result['registered']},ensure_ascii=False))
        except Exception as exc:
            db.log_event(None,'assets','SCAN_ERROR',str(exc)[:350])
    last = db.get_setting('maintenance', 0)
    if now - last > 3600:
        db.enqueue('maintenance', unique_key=f'maintenance:{int(now // 3600)}')
        db.put_setting('maintenance', now)
    if not config.automatic:
        return
    if shutil.disk_usage(db.ROOT).free < 2 * 1024**3:
        db.notify('disk:' + db.today(), 'Produção interrompida: menos de 2 GB livres.')
        return
    last = db.get_setting('last_search', 0)
    if now - last >= config.search_minutes * 60:
        db.enqueue('discover', unique_key=f'discover:{int(now // (config.search_minutes * 60))}')
        db.put_setting('last_search', now)
    for profile in db.rows("SELECT * FROM profiles WHERE enabled=1"):
        if now - (profile['last_checked'] or 0) > profile['interval_minutes'] * 60:
            db.enqueue('profile:' + profile['id'], unique_key=f'profile:{profile["id"]}:{int(now // (profile["interval_minutes"]*60))}')
    for source in db.rows("SELECT * FROM sources WHERE enabled=1"):
        if now - (source['last_checked'] or 0) >= source['interval_minutes'] * 60:
            db.enqueue('source:' + source['id'],
                       unique_key=f'source:{source["id"]}:{int(now // (source["interval_minutes"]*60))}')


def prioritized_opportunities(limit=150):
    # Strong preference for Shorts; never hide longer YouTube videos or RSS.
    return db.rows("""SELECT * FROM opportunities
        ORDER BY CASE
          WHEN platform='youtube' AND url LIKE 'https://www.youtube.com/shorts/%' THEN 0
          WHEN platform='youtube' THEN 1
          WHEN platform='news' THEN 2
          ELSE 3 END,
          COALESCE(score, -1) DESC, created DESC LIMIT :limit""", {'limit':limit})


def queue_opportunities():
    config = db.settings()
    if not config.automatic:
        return
    for opportunity in prioritized_opportunities(limit=30):
        if db.rows('SELECT id FROM videos WHERE url=:url', {'url':opportunity['url']}):
            continue
        try:
            if db.production_usage() >= config.daily_limit:
                break
            if opportunity['platform']=='news':
                create_video(reference=json.loads(opportunity['metadata']))
            else:
                recommended=db.get_setting('recommendations', {}).get('template') or 'gta-news'
                create_video(ImportRequest(url=opportunity['url'],duration=db.settings().duration,template=recommended))
            db.log_event(None, 'worker', 'AUTO_QUEUE', f'Oportunidade enfileirada automaticamente: {opportunity["url"]}')
            break
        except Exception as exc:
            logging.error(json.dumps({'error': 'auto_queue_failed', 'message': str(exc)}, ensure_ascii=False))
            continue


def perform(job):
    kind = job['kind']
    if kind == 'pipeline':
        run_pipeline(job['video_id'])
    elif kind.startswith('split:'):
        from backend.clips import split_asset
        split_asset(kind.split(':',1)[1])
    elif kind == 'discover' or kind.startswith('profile:'):
        profile = None
        if kind.startswith('profile:'):
            results = db.rows('SELECT * FROM profiles WHERE id=:id', {'id': kind.split(':')[1]})
            if not results or not results[0]['enabled']:
                return
            profile = results[0]
        try:
            discover(profile)
            catalog_discovered_shorts()
            if profile:db.execute('UPDATE profiles SET error=NULL WHERE id=:id',{'id':profile['id']})
        finally:
            if profile:
                db.execute('UPDATE profiles SET last_checked=:now WHERE id=:id', dict(now=time.time(), id=profile['id']))
        if db.settings().automatic:
            queue_opportunities()
    elif kind == 'maintenance':
        cleanup()
        # Publicação manual não requer API YouTube; métricas só quando a chave
        # opcional de leitura estiver presente (sem OAuth de postagem).
        if db.secret('youtube_api_key'):
            collect_metrics()
        daily_report()
        db.notify('daily:' + db.today(), 'Resumo atualizado em reports/' + db.today() + '.md')
    elif kind == 'reconcile':
        # Job herdado da versão Postiz: desativado de forma segura.
        return
    elif kind.startswith('source:'):
        source_id=kind.split(':', 1)[1]
        found=db.rows('SELECT * FROM sources WHERE id=:id', {'id':source_id})
        if not found or not found[0]['enabled']:
            return
        try:
            scan_feed(found[0])
            db.execute('UPDATE sources SET error=NULL WHERE id=:id', {'id':source_id})
        finally:
            db.execute('UPDATE sources SET last_checked=:now WHERE id=:id',
                       {'id':source_id,'now':time.time()})
        if db.settings().automatic:
            queue_opportunities()
    else:
        raise ValueError('Tipo de job desconhecido.')


def tick():
    db.put_setting('worker_heartbeat', time.time())
    scheduler()
    if db.settings().emergency_stop:
        return False
    job = db.claim('worker')
    if not job:
        deliver_notifications()
        return False
    stop = threading.Event()
    def heartbeat():
        while not stop.wait(30):
            db.execute("UPDATE jobs SET lease=:lease WHERE id=:id AND status='RUNNING'", dict(id=job['id'], lease=time.time()+180))
            db.put_setting('worker_heartbeat', time.time())
    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        perform(job)
        db.execute("UPDATE jobs SET status='DONE',lease=NULL,error=NULL WHERE id=:id", {'id': job['id']})
    except PipelineInterrupted:
        db.execute("UPDATE jobs SET status='DONE',lease=NULL,error=NULL WHERE id=:id",{'id':job['id']})
    except Exception as exc:
        message = str(exc)[:500] if isinstance(exc, (IntegrationError, ValueError)) else 'Erro interno no pipeline; reencaminhado para nova tentativa.'
        attempts = job['attempts'] + 1
        failed = attempts >= 5
        db.execute('UPDATE jobs SET status=:status,due=:due,lease=NULL,error=:error WHERE id=:id',
                   dict(id=job['id'], status='FAILED' if failed else 'QUEUED', due=time.time()+min(1800, 15*2**attempts), error=message))
        if job['video_id']:
            if failed:
                db.execute("UPDATE videos SET status=:status,error=:error,updated=:now WHERE id=:id AND manual_decision IS NULL",
                           dict(id=job['video_id'], status='REJECTED', error=message, now=time.time()))
                db.log_event(job['video_id'], 'worker', 'REJECTED', f'Vídeo descartado após {attempts} tentativas falhadas: {message}')
            else:
                db.execute("UPDATE videos SET status=:status,error=:error,updated=:now WHERE id=:id AND manual_decision IS NULL",
                           dict(id=job['video_id'], status='RETRY', error=message, now=time.time()))
                db.log_event(job['video_id'], 'worker', 'RETRY', f'Tentativa {attempts} falhou; nova tentativa agendada: {message}')
        if job['kind'].startswith('profile:'):
            db.execute('UPDATE profiles SET error=:error WHERE id=:id', dict(id=job['kind'].split(':')[1], error=message))
        if job['kind'].startswith('source:'):
            db.execute('UPDATE sources SET error=:error WHERE id=:id',dict(id=job['kind'].split(':')[1],error=message))
        db.notify('job-error:' + job['id'], f'Job {job["id"]}: {message}')
        logging.error(json.dumps({'job': job['id'], 'error_type': type(exc).__name__, 'message': message}, ensure_ascii=False))
    finally:
        stop.set()
        thread.join(timeout=2)
    return True


def main():
    db.init_db()
    seed_default_sources()
    if '--health' in sys.argv:
        sys.exit(0 if time.time() - db.get_setting('worker_heartbeat', 0) < 120 else 1)
    while True:
        tick()
        time.sleep(2)


if __name__ == '__main__':
    main()
