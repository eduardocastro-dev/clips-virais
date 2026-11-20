"""Single canonical 9-template visual engine using installed operator ZIP.

Coordinates are read from templates.json.  TV aperture in plate is transparent.
Presenters and the foreground are composited by media.render on separate layers.
"""
from __future__ import annotations
import json
import re
import hashlib
from pathlib import Path
from urllib.parse import urlsplit
from backend import core as db
from backend.integrations import IntegrationError
from backend.template_pack import selected
from backend.scenarios import template_for

FPS=30


def _video_file(path):
    return Path(path).suffix.lower() in ('.mp4','.mov','.webm','.mkv','.avi')


def _source_path(segment,preview_source):
    if preview_source and preview_source.get('path'):
        return preview_source
    if segment.get('source_clip_path'):
        return {'path':segment['source_clip_path'],
                'url':segment.get('overlay_source') or segment.get('source'),
                'rights_status':segment.get('overlay_rights') or 'AUTHORIZED'}
    if segment.get('overlay_path'):
        return {'path':segment['overlay_path'],
                'url':segment.get('overlay_source') or segment.get('source'),
                'rights_status':segment.get('overlay_rights') or 'REVIEW_REQUIRED'}
    if segment.get('path'):
        return {'path':segment['path'],'url':segment.get('source'),
                'rights_status':segment.get('rights_status') or 'AUTHORIZED'}
    raise IntegrationError('Não há conteúdo de origem nem fallback autorizado para o cenário.')


def _source_label(src):
    value=str(src.get('channel') or src.get('url') or src.get('title') or '').strip()
    host=urlsplit(value).hostname
    return (host.removeprefix('www.') if host else value)[:80]


def _esc(s):
    return str(s).replace('\\',r'\\').replace(':',r'\:').replace("'",r"\'")


def render_segment(ff,video,segment,seconds,target,work,index,preview_source=None):
    from backend import media
    scene=selected(video['template'])
    if not scene:
        raise IntegrationError('Pacote gta_studio_templates não instalado. '
                               'Envie o ZIP em Configurações > Templates.')
    layout=scene['layout']
    template=scene['template']
    src=_source_path(segment,preview_source)
    media_path=db.safe_file(str(src['path']))
    if not media_path.is_file():
        raise IntegrationError('Mídia da fonte não encontrada no volume do Studio.')
    top=layout['top_panel']
    tv=layout['tv_screen']
    offset=layout['plate_offset_y']
    w,h=layout['canvas']
    if (tv['y']<offset or tv['y']+tv['h']>h):
        raise IntegrationError('Coordenadas de TV incompatíveis com o plate enviado.')
    is_video=_video_file(media_path)
    pending=src.get('rights_status') not in ('AUTHORIZED','OWNED_GENERATED')
    # Crediting the video in the description and audit manifest is mandatory.
    # On-screen credit is only drawn when the source license requires it.
    onsite=bool(src.get('requires_onscreen_credit') or
                segment.get('requires_onscreen_credit'))
    source_name=_source_label(src)
    date=str(src.get('date') or segment.get('tv_source_date') or '')[:10]
    # The source itself can be video, image or an approved library fallback.
    cmd=[ff,'-hide_banner','-y']
    if is_video:
        clip_start=float(segment.get('source_clip_at') or segment.get('source_offset') or 0)
        cmd+=['-stream_loop','-1','-ss',str(max(0.,clip_start)),'-i',str(media_path)]
    else:
        cmd+=['-loop','1','-framerate',str(FPS),'-i',str(media_path)]
    cmd+=['-loop','1','-framerate',str(FPS),'-i',str(scene['plate'])]
    top_filter=(f'scale={top["w"]}:{top["h"]}:force_original_aspect_ratio=increase,'
                f'crop={top["w"]}:{top["h"]},setsar=1')
    mode=template.get('top_panel',{}).get('mode','single')
    if mode=='letterbox':
        top_filter=(f'scale={top["w"]}:{round(top["h"]*.72)//2*2}:'
                    'force_original_aspect_ratio=decrease,'
                    'pad=1080:960:(ow-iw)/2:(oh-ih)/2:black,setsar=1')
    vfilter=(f'scale={tv["w"]}:{tv["h"]}:force_original_aspect_ratio=increase,'
             f'crop={tv["w"]}:{tv["h"]},setsar=1')
    graph=[
        '[0:v]split=2[topinput][tvinput]',
        f'[topinput]{top_filter}[top]',
        f'[tvinput]{vfilter}[tv]',
        f'color=c=0x0c1020:s={w}x{h}:r={FPS}[canvas]',
        f'[canvas][top]overlay=x={top["x"]}:y={top["y"]}:shortest=1[toplayer]',
        f'[toplayer][tv]overlay=x={tv["x"]}:y={tv["y"]}:shortest=1[tvcomposed]',
        '[1:v]format=rgba[plate]',
        f'[tvcomposed][plate]overlay=x=0:y={offset}:shortest=1[scene]',
    ]
    final='scene'
    if onsite:
        # An explicit exception to the source_label.enabled=false default.
        # Show credit only inside the TV screen aperture, never over persona.
        label=('FONTE: '+source_name+' · '+date).replace("'","").replace(':',r'\:')
        font='/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
        # Fit a modest credit box within the TV even when the source is long.
        y=tv['y']+tv['h']-36
        graph.append(f"[scene]drawbox=x={tv['x']+6}:y={y-2}:w={tv['w']-12}:"
                     f"h=30:color=black@0.75:t=fill,"
                     f"drawtext=fontfile={font}:text='{_esc(label[:44])}':"
                     f"x={tv['x']+10}:y={y+1}:fontsize=15:fontcolor=white[credited]")
        final='credited'
    graph.append(f'[{final}]format=yuv420p[out]')
    cmd+=['-filter_complex',';'.join(graph),'-map','[out]',
          '-t',str(seconds),'-an','-r',str(FPS),'-c:v','libx264',
          '-preset','veryfast','-crf','24','-pix_fmt','yuv420p',
          '-threads','2',str(target)]
    media.run(cmd,timeout=300)
    return {
        'tv_source':str(media_path.relative_to(db.ROOT)),
        'tv_source_url':src.get('url') or segment.get('source'),
        'rights_status':src.get('rights_status'),
        'rights_evidence':src.get('evidence',''),
        'requires_onscreen_credit':onsite,'onscreen_credit_drawn':onsite,
        'preview_only':pending,
        'source_label':source_name,'date':date,
        'template':video['template'],'template_pack':scene['id'],
        'tv_bounds':[tv['x'],tv['y'],tv['x']+tv['w'],tv['y']+tv['h']],
        'presenter_zone':layout['presenter_zone'],
        'caption_band':layout['subtitle_band'],
        'duration':seconds,'channel_glitch_frames':0,
        'foreground_path':str(scene['foreground'].relative_to(db.ROOT)),
        'layers':{
            'plate':str(scene['plate'].relative_to(db.ROOT)),
            'foreground':str(scene['foreground'].relative_to(db.ROOT)),
        },
    }
