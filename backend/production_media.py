"""Per-production ephemeral media: never modify source assets; retain work for retries.

No unauthorized download: research-only videos remain metadata-only. External article
screenshots are small, attributed editorial excerpts that require manual rights review.
"""
from __future__ import annotations
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
from datetime import datetime
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo
from backend import core as db
from backend.integrations import IntegrationError

BASE = db.ROOT/'temp'
BASE.mkdir(parents=True,exist_ok=True)


def workspace(video_id: str) -> Path:
    if not re.fullmatch(r'[a-f0-9]{32}',video_id):
        raise ValueError('ID da produção inválido.')
    folder = BASE/video_id
    folder.mkdir(parents=True,exist_ok=True)
    return folder


def copy_original(source: Path, video_id: str, name='source') -> Path:
    source=source.resolve(strict=True)
    if not source.is_file() or source.is_symlink():
        raise ValueError('Origem não é um arquivo regular.')
    dest=workspace(video_id)/f'{name}{source.suffix.lower()}'
    if dest.exists() and dest.stat().st_size == source.stat().st_size:
        import hashlib
        digest=lambda file:hashlib.sha256(file.read_bytes()).digest()
        if digest(dest)==digest(source):
            return dest
    temporary=dest.with_suffix(dest.suffix+'.partial')
    shutil.copy2(source,temporary)
    os.replace(temporary,dest)
    return dest


def _log(video_id, event, detail):
    db.log_event(video_id,'media',event,str(detail)[:600])


def cached_video(video):
    """Only licensed source assets are considered for editing."""
    from backend.assets import canonical_id
    if video['rights']!='AUTHORIZED':
        return None
    url=video.get('url','').split('#',1)[0]
    vid=canonical_id(url)
    found=db.rows("""SELECT * FROM assets WHERE kind IN ('shorts','gameplay','uploads') AND
        rights_status='AUTHORIZED' AND status='READY' AND (url=:url OR source_id=:source_id)
        ORDER BY created DESC LIMIT 1""",{'url':url,'source_id':vid or ''})
    if not found or not found[0]['path']:
        return None
    source=db.safe_file(found[0]['path'])
    return copy_original(source,video['id'],'source')


def acquire_source_video(video):
    """Reuse cached media or download *authorized* source to workspace with two retries."""
    if video['rights']!='AUTHORIZED' or not video.get('evidence'):
        return None
    folder=workspace(video['id'])
    ready=list(folder.glob('source.mp4'))
    if ready and ready[0].stat().st_size:
        return ready[0]
    reused=cached_video(video)
    if reused:
        _log(video['id'],'REUSED','Fonte copiada da biblioteca sem alterar original.')
        return reused
    url=video['url'].split('#',1)[0]
    from backend.contracts import platform_url
    platform_url(url) # do not accept arbitrary URLs from the video row
    target=folder/'source.mp4'
    errors=[]
    for number in range(1,4):
        part=folder/f'download-{number}.%(ext)s'
        cmd=[sys.executable,'-m','yt_dlp','--no-playlist','--no-warnings','--no-progress',
             '--max-filesize','250M','--socket-timeout','15','--retries','0',
             '-f','best[ext=mp4]/best','--merge-output-format','mp4',
             '-o',str(part),'--',url]
        try:
            process=subprocess.run(cmd,capture_output=True,timeout=200)
            downloaded=list(folder.glob(f'download-{number}.*'))
            if process.returncode or not downloaded:
                raise RuntimeError(process.stderr.decode('utf-8','replace')[-500:] or 'mídia não foi baixada')
            candidate=next((p for p in downloaded if p.suffix.lower()=='.mp4'),None)
            if not candidate:
                raise RuntimeError('Formato de vídeo não suportado para o render MP4.')
            os.replace(candidate,target)
            for extra in downloaded:
                if extra.exists(): extra.unlink()
            _log(video['id'],'DOWNLOADED',f'Vídeo autorizado disponível na área temporária, tentativa {number}.')
            try:
                from backend.clips import register_downloaded
                register_downloaded(video,target)
            except (OSError,ValueError,RuntimeError) as exc:
                _log(video['id'],'LIBRARY_CACHE_FAILED',str(exc)[:400])
            return target
        except (RuntimeError,subprocess.TimeoutExpired,OSError) as exc:
            errors.append(f'{number}/3: {exc}')
            for extra in folder.glob(f'download-{number}.*'):
                extra.unlink(missing_ok=True)
            _log(video['id'],'DOWNLOAD_RETRY',errors[-1])
    # Downloader failure is visible; background fallback is still possible.
    db.atomic(folder/'download-error.json',json.dumps({'url':url,'errors':errors},ensure_ascii=False))
    _log(video['id'],'DOWNLOAD_FAILED',errors[-1])
    return None


def validated_public_url(url: str) -> str:
    """Block localhost / private network targets and URL credentials before browser access."""
    u=urlsplit(url)
    if u.scheme!='https' or not u.hostname or u.username or u.password or u.port not in (None,443):
        raise ValueError('Captura aceita somente páginas públicas HTTPS.')
    try:
        results=socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)
        if not results or any(not ip_address(record[4][0]).is_global for record in results):
            raise ValueError('Destino não público.')
    except socket.gaierror as exc:
        raise ValueError('Endereço da matéria não pôde ser resolvido.') from exc
    return url


def capture_article(video) -> dict:
    """Mobile screenshot of headline/lead only, not full page. Optional Playwright."""
    folder=workspace(video['id'])
    cache=folder/'article.json'
    if cache.exists():
        return json.loads(cache.read_text('utf-8'))
    result={'status':'FALLBACK','source':video.get('url',''),'assets':[],
            'error':None,'rights_status':'REVIEW_REQUIRED'}
    try:
        url=validated_public_url(video['url'])
        from playwright.sync_api import sync_playwright
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(headless=True,args=['--disable-dev-shm-usage','--no-sandbox'])
            context=browser.new_context(viewport={'width':390,'height':844},device_scale_factor=1,
                  java_script_enabled=True,service_workers='block',accept_downloads=False)
            page=context.new_page()
            # External links, iframes, private hosts, and non-http navigation are blocked.
            def route(req):
                try:
                    target=urlsplit(req.request.url)
                    if target.scheme not in ('http','https') or target.hostname!=urlsplit(url).hostname:
                        return req.abort()
                    return req.continue_()
                except Exception:return req.abort()
            page.route('**/*',route)
            page.goto(url,wait_until='domcontentloaded',timeout=20000)
            # Snapshot stays in temporary workspace; never copied to permanent assets.
            (folder/'article.html').write_text(page.content()[:250_000],encoding='utf-8')
            page.add_style_tag(content='''[id*="cookie"],[class*="cookie"],[class*="advert"],
                [class*="popup"],[role="dialog"],iframe,header,footer,nav{display:none!important;}''')
            for kind,loc in [('headline','h1'),('excerpt','article p')]:
                matches=page.locator(loc)
                if matches.count():
                    node=matches.first
                    if node.is_visible():
                        text=node.inner_text(timeout=4000).strip()[:220]
                        if text:
                            path=folder/f'article-{kind}.png'
                            node.screenshot(path=str(path),timeout=7000,animations='disabled')
                            result['assets'].append({'path':str(path.relative_to(db.ROOT)),
                                'kind':kind,'excerpt':text,'source':url,
                                'source_class':'THIRD_PARTY','rights_status':'REVIEW_REQUIRED'})
            images=page.locator('article img')
            if images.count():
                picture=images.first
                if picture.is_visible():
                    try:
                        path=folder/'article-image.png'
                        picture.screenshot(path=str(path),timeout=7000,animations='disabled')
                        result['assets'].append({'path':str(path.relative_to(db.ROOT)),
                            'kind':'article-image','excerpt':str(picture.get_attribute('alt') or '')[:120],
                            'source':url,'source_class':'THIRD_PARTY','rights_status':'REVIEW_REQUIRED'})
                    except Exception as exc:
                        _log(video['id'],'ARTICLE_IMAGE_FAILED',str(exc)[:200])
            browser.close()
            result['status']='CAPTURED' if result['assets'] else 'FALLBACK'
    except Exception as exc:
        result['error']=str(exc)[:500]
        _log(video['id'],'ARTICLE_CAPTURE_FAILED',result['error'])
    db.atomic(cache,json.dumps(result,ensure_ascii=False,indent=2))
    return result


def remove_workspace(video_id: str):
    folder=BASE/video_id
    if folder.is_symlink():raise ValueError('Pasta temporária não pode ser link simbólico.')
    if folder.is_dir() and folder.resolve().parent==BASE.resolve():
        shutil.rmtree(folder)


def prune_stale(days: int):
    cutoff=time.time()-days*86400
    for folder in BASE.iterdir():
        if not folder.is_dir() or folder.is_symlink() or not re.fullmatch('[0-9a-f]{32}',folder.name):
            continue
        found=db.rows('SELECT status,manual_decision FROM videos WHERE id=:id',{'id':folder.name})
        if found and (found[0]['status'] in ('PROCESSING','QUEUED','RETRY','AWAITING_MANUAL_DECISION') or
                      found[0]['manual_decision']=='approve_pending'):
            continue
        if folder.stat().st_mtime<cutoff:
            remove_workspace(folder.name)
