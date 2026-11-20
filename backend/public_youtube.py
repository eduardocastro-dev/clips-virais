"""Public YouTube metadata adapter without API keys, OAuth, cookies or downloads.

YouTube may rate-limit/block anonymous requests; an unavailable fact is *unknown*
and must not be invented. This module never grants permission to reuse footage.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit, parse_qs

from backend.integrations import IntegrationError

CHANNEL_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
VIDEO_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
ALLOWED_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com",
                 "youtu.be", "www.youtu.be"}


def video_id_from_url(url: str) -> str:
    """Accept only actual YouTube URLs, never an arbitrary extractor target."""
    try:
        parsed=urlsplit((url or "").strip())
        if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
            raise ValueError("Cole uma URL HTTPS válida do YouTube.")
        parts=parsed.path.strip("/").split("/")
        if parsed.hostname in {"youtu.be", "www.youtu.be"}:
            video_id=parts[0]
        elif parts[0] in {"live", "shorts", "embed"} and len(parts)>1:
            video_id=parts[1]
        elif parts[0]=="watch":
            video_id=parse_qs(parsed.query).get("v", [""])[0]
        else:
            raise ValueError("Utilize um link de vídeo ou live do YouTube.")
        if not VIDEO_RE.fullmatch(video_id):
            raise ValueError("ID do vídeo inválido.")
        return video_id
    except (ValueError, TypeError) as exc:
        raise ValueError(str(exc) or "URL inválida.") from None


def _extract(url: str, *, flat=False, limit=1):
    from yt_dlp import YoutubeDL
    opts={"quiet":True, "no_warnings":True, "skip_download":True,
          "noplaylist":not flat, "extract_flat":flat,
          "playlistend":limit, "socket_timeout":16, "retries":1,
          "ignoreerrors":False, "cachedir":False}
    try:
        with YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=False)
    except Exception:
        raise IntegrationError("Não foi possível consultar metadados públicos do YouTube. "
                               "Configure chave ou login em Configurações > Integrações, "
                               "ou tente novamente.") from None


def public_video_info(video_url: str, *, fresh: bool=False) -> dict:
    vid=video_id_from_url(video_url)
    from backend.youtube_data import configured,video_info,video_details
    data=((video_details([vid],force=True).get(vid) if fresh else video_info(video_url))
          if configured() else _extract("https://www.youtube.com/watch?v="+vid))
    if not isinstance(data,dict) or data.get("id")!=vid:
        raise IntegrationError("Vídeo público não encontrado ou ID divergente.")
    return data


def public_channel_entries(channel_id: str, tab: str="videos", limit: int=12) -> list[dict]:
    if not CHANNEL_RE.fullmatch(channel_id or ""):
        raise ValueError("ID UC inválido.")
    if tab not in ("videos","shorts","streams"):
        raise ValueError("Aba do canal inválida.")
    from backend.youtube_data import configured,channel_uploads
    if configured():
        uploads=channel_uploads(channel_id,limit=max(limit,40))
        if tab=='videos':return uploads[:limit]
        if tab=='streams':
            return [x for x in uploads if x.get('live_status')=='was_live'][:limit]
        # API does not expose an explicit isShort flag; avoid falsely
        # labelling normal videos of 180s or less as Shorts.
        return [x for x in uploads if x.get('duration') is not None and
                x['duration']<=180 and
                ('#shorts' in (str(x.get('title') or '')+' '+str(x.get('description') or '')).lower())
               ][:limit]
    page=_extract(f"https://www.youtube.com/channel/{channel_id}/{tab}",
                  flat=True,limit=max(1,min(30,limit)))
    if not isinstance(page,dict):
        raise IntegrationError("Canal público indisponível.")
    found=[]
    for item in (page.get("entries") or []):
        if not isinstance(item,dict):
            continue
        vid=item.get("id")
        if isinstance(vid,str) and VIDEO_RE.fullmatch(vid):
            found.append(item)
    return found


def public_channel_info(channel_id: str) -> dict:
    if not CHANNEL_RE.fullmatch(channel_id or ""):
        raise ValueError("ID UC inválido.")
    # A flat, single-entry listing is enough to identify a channel by name,
    # but never invent subscriber counts or country if the page omits them.
    from backend.youtube_data import configured,_get_api
    if configured():
        from backend import core as db
        key=db.secret('youtube_api_key')
        from backend.youtube_data import access_token
        raw=_get_api('channels',{'part':'snippet,statistics','id':channel_id},
                     key=key,token=access_token() if not key else None)
        candidates=raw.get('items') or []
        if not candidates:raise IntegrationError('Canal não encontrado.')
        channel=candidates[0]
        fields=channel.get('snippet') or {}
        stats=channel.get('statistics') or {}
        return {'channel_id':channel_id,'name':fields.get('title') or channel_id,
                'subscribers':int(stats['subscriberCount']) if 'subscriberCount' in stats else None,
                'country':fields.get('country'),'language':fields.get('defaultLanguage'),
                'verified_publicly':True}
    data=_extract(f"https://www.youtube.com/channel/{channel_id}/videos",flat=True,limit=1)
    if not isinstance(data,dict):
        raise IntegrationError("Não foi possível verificar o canal público.")
    remote=data.get("channel_id") or data.get("id")
    if remote and CHANNEL_RE.fullmatch(str(remote)) and remote!=channel_id:
        raise ValueError("O link do canal resolveu para um UC diferente.")
    return {"channel_id":channel_id,
            "name":str(data.get("channel") or data.get("uploader") or data.get("title") or channel_id)[:180],
            "subscribers":data.get("channel_follower_count") if isinstance(data.get("channel_follower_count"),int) else None,
            "country":None,"language":None,
            "verified_publicly":bool(remote==channel_id)}


def video_published_at(info: dict) -> datetime | None:
    value=info.get("release_timestamp") or info.get("timestamp")
    if isinstance(value,(int,float)) and value>0:
        try:return datetime.fromtimestamp(value,timezone.utc)
        except (ValueError,OverflowError):pass
    date=str(info.get("upload_date") or info.get("release_date") or "")
    if re.fullmatch(r"\d{8}",date):
        try:return datetime.strptime(date,"%Y%m%d").replace(tzinfo=timezone.utc)
        except ValueError:pass
    return None


def public_recent_video(info: dict, *, days=30, now=None) -> bool:
    now=now or datetime.now(timezone.utc)
    if not isinstance(info,dict) or info.get("availability")!="public":
        return False
    if info.get("age_limit") not in (None,0):
        return False
    if info.get("is_private") or info.get("is_unlisted"):
        return False
    date=video_published_at(info)
    return bool(date and timedelta(0)<=now-date<=timedelta(days=days))


def _stream_time(value) -> datetime | None:
    if isinstance(value,(int,float)) and value>0:
        try:return datetime.fromtimestamp(value,timezone.utc)
        except (ValueError,OverflowError,OSError):return None
    if isinstance(value,str) and value.strip():
        try:
            dt=datetime.fromisoformat(value.replace("Z","+00:00"))
            return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:return None
    return None


def live_ended_at(info: dict) -> datetime | None:
    """Actual end is more meaningful than video upload for archived livestreams.

    Live pages can be scheduled/uploaded weeks before the broadcast. Prefer
    verified liveStreamingDetails.actualEndTime. Missing end metadata is
    approximated using an actual stream start plus the finished VOD duration;
    do not use scheduled start/end to establish a broadcast happened.
    """
    details=info.get('liveStreamingDetails') or {}
    if not isinstance(details,dict):
        details={}
    for value in (details.get('actualEndTime'),info.get('actual_end_time'),
                  info.get('live_end_timestamp')):
        if (parsed:=_stream_time(value)) is not None:
            return parsed
    duration=info.get('duration')
    start=_stream_time(details.get('actualStartTime'))
    if start and info.get('live_status')=='was_live' and isinstance(duration,(int,float)) and duration>0:
        return start+timedelta(seconds=duration)
    # yt-dlp's release time is often closer to broadcast time than upload.
    if info.get('live_status')=='was_live':
        return (_stream_time(info.get('release_timestamp')) or
                video_published_at(info))
    return None


def live_hype_recency_score(info: dict, *, days=30, now=None) -> int:
    """0–100 editorial freshness score, not a forecast of real engagement."""
    end=live_ended_at(info)
    now=now or datetime.now(timezone.utc)
    if not end:return 0
    hours=(now-end).total_seconds()/3600
    if hours<0:return 0
    return max(0,round(100*(1-hours/(days*24))))


def live_rejection_reason(info: dict, *, days=30, now=None) -> str:
    now=now or datetime.now(timezone.utc)
    if info.get('availability')!='public' or info.get('is_unlisted') or info.get('is_private'):
        return 'O VOD precisa estar público (não privado nem não listado).'
    if info.get('age_limit') not in (None,0):
        return 'A gravação tem restrição de idade; este fluxo aceita somente VODs não restritos.'
    status=info.get('live_status')
    if info.get('is_live') or status=='is_live':
        return 'Esta live ainda está em andamento. Aguarde o encerramento.'
    if status=='is_upcoming':
        return 'A live ainda não começou. Aguarde o encerramento e a publicação do replay.'
    if status=='post_live':
        return 'A live terminou, mas o replay ainda está em processamento no YouTube.'
    duration=info.get('duration')
    if not isinstance(duration,(int,float)) or duration<=0:
        return 'O YouTube ainda não disponibilizou um replay com duração verificável.'
    details=info.get('liveStreamingDetails') or {}
    evidence=(status=='was_live' or
              (isinstance(details,dict) and bool(details.get('actualEndTime'))))
    if not evidence:
        return 'O YouTube não confirmou que o vídeo é uma transmissão encerrada.'
    end=live_ended_at(info)
    if end is None:
        return 'Não foi possível confirmar a data de encerramento da live.'
    age=now-end
    if age<timedelta(0):
        return 'A data de encerramento informada pelo YouTube está no futuro.'
    if age>timedelta(days=days):
        return f'A live terminou há {age.days} dias; o limite para cortes automáticos é {days} dias.'
    return ''


def public_ended_live(info: dict, *, days=30, now=None) -> bool:
    if not isinstance(info,dict):
        return False
    return not live_rejection_reason(info,days=days,now=now)
