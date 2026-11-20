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
        raise IntegrationError("Não foi possível consultar metadados públicos do YouTube "
                               "sem login. Tente novamente mais tarde; nenhuma API key é necessária.") from None


def public_video_info(video_url: str) -> dict:
    vid=video_id_from_url(video_url)
    data=_extract("https://www.youtube.com/watch?v="+vid)
    if not isinstance(data,dict) or data.get("id")!=vid:
        raise IntegrationError("Vídeo público não encontrado ou ID divergente.")
    return data


def public_channel_entries(channel_id: str, tab: str="videos", limit: int=12) -> list[dict]:
    if not CHANNEL_RE.fullmatch(channel_id or ""):
        raise ValueError("ID UC inválido.")
    if tab not in ("videos","shorts","streams"):
        raise ValueError("Aba do canal inválida.")
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


def public_ended_live(info: dict, *, days=30, now=None) -> bool:
    if not public_recent_video(info,days=days,now=now):
        return False
    status=info.get("live_status")
    return status=="was_live" and not info.get("is_live") and bool(info.get("duration"))
