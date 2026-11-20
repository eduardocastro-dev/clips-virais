"""Reusable FFmpeg TV-slot compositor for all nine procedural GTA Studio environments."""
from __future__ import annotations
import json
import hashlib
import re
from pathlib import Path
from urllib.parse import urlsplit
from backend import core as db
from backend.integrations import IntegrationError
from backend.scenarios import build_layers,template_for,TV_SCREEN,FPS


def _source_color(ff,media_path:Path,work:Path):
    """Sample the actual source, never invent a theme based on its title."""
    from PIL import Image
    from backend import media
    sample=media_path
    if _video_file(media_path):
        digest=hashlib.sha256(
            (str(media_path)+str(media_path.stat().st_mtime_ns)).encode()).hexdigest()[:14]
        sample=work/('color-sample-'+digest+'.jpg')
        if not sample.is_file():
            try:
                media.run([ff,'-hide_banner','-loglevel','error','-y',
                           '-ss','0.7','-i',str(media_path),
                           '-frames:v','1','-vf','scale=64:64',
                           str(sample)],timeout=30)
            except IntegrationError:
                return None
    try:
        with Image.open(sample) as image:
            rgb=image.convert('RGB').resize((1,1)).getpixel((0,0))
            return tuple(int(v) for v in rgb)
    except (OSError,ValueError):
        return None



def _video_file(path:Path) -> bool:
    return path.suffix.lower() in {'.mp4','.webm','.mov','.mkv','.avi'}


def _date_for_source(spec,video):
    raw=spec.get('published_at') or spec.get('date')
    if not raw:
        try:
            metadata=json.loads(video.get('metadata') or '{}')
            raw=metadata.get('published_at') or metadata.get('published')
        except (ValueError,TypeError):pass
    raw=str(raw or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}.*',raw):
        return raw[:10]
    return ''


def _source_name(value):
    v=str(value or '').strip()
    try:
        host=urlsplit(v).hostname
        if host:return host.removeprefix('www.')[:24]
    except ValueError:pass
    return v[:24]


def render_segment(ff,video,segment,seconds,target,work,index,preview_source=None):
    """Build a segment: original plate + 1 replaceable TV + bezel/foreground.

    Source video from the current article/topic always wins over library B-roll.
    The whole screen remains framed. No downloaded file is given publication rights
    by this function. Actual durations come from measured Piper scene boundaries.
    """
    from backend import media
    scenario=template_for(video.get('template'))
    if scenario is None:
        raise ValueError('Cenário não identificado.')
    source=preview_source
    if not source and segment.get('source_clip_path'):
        source={'path':segment['source_clip_path'],
                'url':segment.get('overlay_source') or segment.get('source'),
                'rights_status':segment.get('overlay_rights') or 'AUTHORIZED'}
    # Images from a news source may be displayed as photos within TV.
    if not source and segment.get('overlay_path'):
        source={'path':segment['overlay_path'],
                'url':segment.get('overlay_source') or segment.get('source'),
                'rights_status':segment.get('overlay_rights') or 'REVIEW_REQUIRED'}
    if not source and segment.get('path'):
        source={'path':segment['path'],'url':segment.get('source'),
                'rights_status':segment.get('rights_status') or 'AUTHORIZED'}
    if not source:
        raise IntegrationError('Cenário sem mídia de TV; a prévia não pode ser concluída.')
    media_path=db.safe_file(str(source['path']))
    if not media_path.is_file():
        raise IntegrationError('Fonte da TV não está disponível.')
    is_video=_video_file(media_path)
    pending=source.get('rights_status') not in ('AUTHORIZED','OWNED_GENERATED')
    label=_source_name(source.get('channel') or source.get('url') or source.get('title'))
    if source.get('rights_status')=='OWNED_GENERATED':
        label='GTA Studio'
    if source.get('date'):
        date_label=str(source['date'])[:10]
    else:
        date_label=_date_for_source(segment,video)
    glow=_source_color(ff,media_path,work)
    layers=build_layers(video['template'],work/'scenario-layers',
                        source_label=label,date_label=date_label,
                        preview=False,glow_color=glow)
    # Rights remain gated in the DB and API, not embedded as a persistent
    # watermark that would require recompressing after operator clearance.
    if not layers:raise IntegrationError('Camadas do cenário indisponíveis.')
    x0,y0,x1,y1=TV_SCREEN
    vw,vh=x1-x0,y1-y0
    cmd=[ff,'-hide_banner','-y',
         '-loop','1','-framerate',str(FPS),'-i',str(layers['plate'])]
    if is_video:
        offset=float(segment.get('source_clip_at') or segment.get('source_offset') or 0)
        cmd+=['-stream_loop','-1','-ss',str(max(0,offset)),'-i',str(media_path)]
    else:
        cmd+=['-loop','1','-framerate',str(FPS),'-i',str(media_path)]
    cmd+=['-loop','1','-framerate',str(FPS),'-i',str(layers['bezel'])]
    # Dynamic content in a single pin-mapped display. No transforms touch
    # the presenter region or the fixed outer geometry.
    base=(f'scale={vw+24}:{vh+16}:force_original_aspect_ratio=increase,'
          f'crop={vw+24}:{vh+16},setsar=1,')
    # A mild perspective corner pin fits within the physical bezel.
    perspective=(f'perspective=x0=8:y0=5:x1={vw-9}:y1=0:'
                 f'x2=0:y2={vh-8}:x3={vw-2}:y3={vh-3}:sense=destination,')
    if is_video:
        tv_filter=(base+f'crop={vw}:{vh}:12:8,'
                   'setpts=PTS-STARTPTS,format=rgba,'+perspective+
                   'format=rgba[tv]')
    else:
        tv_filter=(base+f'crop={vw}:{vh}:12:8,'
                   f"zoompan=z='min(zoom+0.00035,1.03)':"
                   "x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':"
                   f'd=1:s={vw}x{vh}:fps={FPS},'
                   'format=rgba,'+perspective+'format=rgba[tv]')
    # Glitch on the first seven frames only. Short public/licensed SFX
    # are mixed later by the existing licensed-audio pipeline.
    graph=['[0:v]format=rgba[plate]',
           '[1:v]'+tv_filter,
           '[tv]split[tvclean][tvglitchsrc]',
           '[tvglitchsrc]noise=alls=35:allf=t,format=rgba[tvnoise]',
           '[tvclean][tvnoise]overlay=x=0:y=0:enable='+f"'lt(t,{7/FPS:.5f})'"+'[tvready]',
           f'[plate][tvready]overlay=x={x0}:y={y0}:format=auto[screen]',
           '[2:v]format=rgba[frame]',
           '[screen][frame]overlay=0:0:format=auto,format=yuv420p[out]']
    cmd+=['-filter_complex',';'.join(graph),'-map','[out]','-t',str(seconds),
          '-an','-r',str(FPS),'-c:v','libx264','-preset','veryfast',
          '-crf','24','-pix_fmt','yuv420p','-threads','2',str(target)]
    media.run(cmd,timeout=300)
    return {'tv_source':str(media_path.relative_to(db.ROOT)),
            'tv_source_url':source.get('url') or segment.get('source'),
            'rights_status':source.get('rights_status'),
            'rights_evidence':source.get('evidence',''),
            'preview_only':pending,
            'source_label':label,'date':date_label,
            'layers':{key:str(value.relative_to(db.ROOT)) if isinstance(value,Path) and
                      value.is_relative_to(db.ROOT) else str(value)
                      for key,value in layers.items() if key in ('plate','bezel')},
            'tv_bounds':list(TV_SCREEN),'duration':seconds,
            'screen_tint_rgb':list(glow) if glow else None,
            'template':video['template'],'channel_glitch_frames':7}
