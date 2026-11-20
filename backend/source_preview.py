"""Review-only ingest of public source footage for editorial TV screens.

No access bypass, cookies, member-only sources, age-gated content or API keys.
A successful download NEVER changes rights_status to AUTHORIZED, and never
automatically approves or publishes a derived Short.
"""
from __future__ import annotations
import json
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime,timezone
from pathlib import Path
from backend import core as db
from backend.integrations import IntegrationError

PENDING='REVIEW_REQUIRED'


def source_url(video:dict) -> str | None:
    url=str(video.get('url') or '').split('#',1)[0]
    if video.get('platform')=='youtube':
        from backend.public_youtube import video_id_from_url
        try:
            vid=video_id_from_url(url)
            return 'https://www.youtube.com/watch?v='+vid
        except ValueError:
            return None
    # An article may explicitly provide a video URL in its feed metadata.
    if video.get('platform')=='news':
        try:meta=json.loads(video.get('metadata') or '{}')
        except (TypeError,ValueError):return None
        linked=str(meta.get('video_url') or meta.get('source_video_url') or '')
        from backend.public_youtube import video_id_from_url
        try:
            vid=video_id_from_url(linked)
            return 'https://www.youtube.com/watch?v='+vid
        except ValueError:
            return None
    if video.get('platform') in ('instagram','tiktok'):
        from backend.contracts import platform_url
        try:
            name,canonical=platform_url(url)
            return canonical if name==video['platform'] else None
        except ValueError:
            return None
    return None


def record_rights(video_id:str, source_url:str, asset_id:str|None,
                  rights_status:str, detail:str):
    file=db.DATA/'rights_log.json'
    try:
        data=json.loads(file.read_text('utf-8')) if file.is_file() else {'entries':[]}
        if not isinstance(data,dict):data={'entries':[]}
    except (OSError,ValueError):
        data={'entries':[]}
    entries=data.setdefault('entries',[])
    entry={'at':datetime.now(timezone.utc).isoformat(),
           'video_id':video_id,'source_url':source_url,'asset_id':asset_id,
           'status':rights_status,'detail':detail[:400],
           'scope':'gta_studio_tv_slot'}
    # Suppress identical repeat logs when re-rendering the same file.
    if not entries or any(entries[-1].get(key)!=entry[key] for key in
                          ('video_id','asset_id','status','detail')):
        entries.append(entry)
        data['entries']=entries[-5000:]
        db.atomic(file,json.dumps(data,ensure_ascii=False,indent=2)+'\n')


def _check_public(url:str) -> dict:
    if 'youtube.com/' in url or 'youtu.be/' in url:
        from backend.public_youtube import public_video_info
        info=public_video_info(url)
    else:
        from yt_dlp import YoutubeDL
        # Anonymous public-metadata lookup only. No cookies or login bypass.
        options={'quiet':True,'no_warnings':True,'skip_download':True,
                 'noplaylist':True,'socket_timeout':15,'retries':0,
                 'cachedir':False}
        try:
            with YoutubeDL(options) as dl:
                info=dl.extract_info(url,download=False)
        except Exception:
            raise IntegrationError('Fonte pública indisponível sem autenticação.') from None
        if not isinstance(info,dict):
            raise IntegrationError('Metadados públicos ausentes.')
        # Some extractors omit availability for regular public posts.
        if info.get('availability') is None:
            info={**info,'availability':'public'}
    if info.get('availability')!='public' or info.get('age_limit') not in (None,0):
        raise IntegrationError('A fonte não pôde ser confirmada como pública e irrestrita.')
    if info.get('live_status') in ('is_live','is_upcoming') or info.get('is_live'):
        raise IntegrationError('Live em andamento/prevista não pode ser usada como VOD.')
    if info.get('is_private') or info.get('is_unlisted'):
        raise IntegrationError('Fonte privada/não listada não é elegível.')
    return info


def ensure(video:dict) -> dict|None:
    """Ingest into the persistent library for a PRIVATE review-only video.

    Missing network access is non-fatal for editing: fall back to licensed
    library clips or an original TV graphic. Explicit unauthorized access is
    never attempted. Caller must block publishing pending rights confirmation.
    """
    url=source_url(video)
    if not url or video.get('test'):return None
    # Prevent unreviewed external footage entering a previously approved job.
    if video.get('approved'):return None
    if 'youtube.com/' in url or 'youtu.be/' in url:
        from backend.public_youtube import video_id_from_url
        vid=video_id_from_url(url)
    else:
        vid=hashlib.sha256(url.encode('utf-8')).hexdigest()[:24]
    source_id='source-'+vid
    current=db.rows(
        "SELECT * FROM assets WHERE kind='uploads' AND source_id=:sid",
        {'sid':source_id})
    if current and current[0].get('path'):
        path=db.ROOT/current[0]['path']
        if path.is_file() and current[0]['status']=='READY':
            return current[0]
    try:
        info=_check_public(url)
    except (ValueError,IntegrationError) as exc:
        db.log_event(video['id'],'source_preview','SOURCE_UNAVAILABLE',str(exc)[:400])
        return None
    dst_folder=db.ROOT/'assets'/'source_previews'
    dst_folder.mkdir(parents=True,exist_ok=True)
    target=dst_folder/(vid+'.mp4')
    if not target.is_file() or target.stat().st_size<4096:
        work=db.ROOT/'temp'/'source-previews'/video['id']
        work.mkdir(parents=True,exist_ok=True)
        name=work/'source.%(ext)s'
        cmd=[sys.executable,'-m','yt_dlp','--no-playlist','--no-warnings',
             '--no-progress','--max-filesize','250M','--socket-timeout','15',
             '--retries','0','-f','best[ext=mp4]/best',
             '--merge-output-format','mp4',
             '-o',str(name),'--',url]
        try:
            output=subprocess.run(cmd,capture_output=True,timeout=220)
            downloaded=next((p for p in work.glob('source.*') if p.suffix.lower()=='.mp4'),None)
            if output.returncode or downloaded is None:
                raise IntegrationError(output.stderr.decode('utf-8','replace')[-400:] or 'Arquivo indisponível.')
            from backend.media import probe
            details=probe(downloaded)
            if float(details.get('format',{}).get('duration') or 0)<=0:
                raise IntegrationError('Fonte baixada sem duração de vídeo válida.')
            shutil.copy2(downloaded,target)
        except (OSError,subprocess.TimeoutExpired,IntegrationError) as exc:
            db.log_event(video['id'],'source_preview','DOWNLOAD_FAILED',str(exc)[-400:])
            record_rights(video['id'],url,None,'UNAVAILABLE',
                          'Download público falhou; render deve usar outros materiais autorizados.')
            return None
        finally:
            for file in work.glob('source.*'):
                file.unlink(missing_ok=True)
    aid=current[0]['id'] if current else db.uid()
    source_status=('AUTHORIZED' if video.get('rights')=='AUTHORIZED' and
                   len(str(video.get('evidence') or '').strip())>=10 else PENDING)
    evidence=str(video.get('evidence') or '') if source_status=='AUTHORIZED' else ''
    upload_date=str(info.get('upload_date') or info.get('release_date') or '')
    published=(upload_date[:4]+'-'+upload_date[4:6]+'-'+upload_date[6:8]
               if len(upload_date)==8 and upload_date.isdigit() else '')
    meta={'reference_video_id':video['id'],'source_url':url,'source_title':info.get('title'),
          'source_channel':info.get('channel'),'source_date':published,
          'availability':'public',
          'preview_only':source_status!= 'AUTHORIZED','ingested_at':time.time()}
    from backend.media import probe
    secs=float(probe(target)['format']['duration'])
    entry={'id':aid,'kind':'uploads','source_id':source_id,'url':url,
           'title':str(info.get('title') or video.get('title') or 'Vídeo da fonte')[:300],
           'channel':str(info.get('channel') or '')[:200],
           'source_class':'THIRD_PARTY','rights_status':source_status,
           'evidence':evidence,'path':str(target.relative_to(db.ROOT)),
           'status':'READY','media_type':'video','category':'fonte','active':1,
           'metadata':json.dumps(meta,ensure_ascii=False),'duration':secs}
    if current:
        # An operator-approved asset must never be silently demoted by a retry.
        if current[0]['rights_status']=='AUTHORIZED':
            entry['rights_status']='AUTHORIZED'
            entry['evidence']=current[0]['evidence']
        db.execute("""UPDATE assets SET path=:path,status='READY',duration=:duration,
            metadata=:metadata,updated=:updated WHERE id=:id""",
            {**entry,'updated':time.time()})
    else:
        db.execute("""INSERT INTO assets
            (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,
             path,status,metadata,duration,created,updated,media_type,category,active)
            VALUES (:id,:kind,:source_id,:url,:title,:channel,:source_class,:rights_status,:evidence,
             :path,:status,:metadata,:duration,:created,:updated,:media_type,:category,:active)""",
            {**entry,'created':time.time(),'updated':time.time()})
    record_rights(video['id'],url,aid,entry['rights_status'],
                  'Fonte incorporada somente à prévia privada; liberação exige direitos comprovados.')
    db.log_event(video['id'],'source_preview','IMPORTED',
                 'Vídeo da fonte salvo na biblioteca com status '+entry['rights_status'])
    return entry


def pending_assets(video_id:str) -> list[dict]:
    return db.rows("""SELECT a.id,a.url,a.title,a.rights_status,a.evidence
      FROM assets a WHERE a.kind='uploads' AND a.source_id LIKE 'source-%'
        AND json_extract(a.metadata,'$.reference_video_id')=:video
        AND a.rights_status!='AUTHORIZED'""", {'video':video_id})
