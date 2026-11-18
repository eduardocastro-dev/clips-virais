"""FFmpeg scene compositor with provenance and no synthetic background fallback."""
from __future__ import annotations
import json
import hashlib
import shutil
import math
import re
from pathlib import Path
from textwrap import wrap
from backend import core as db
from backend.integrations import IntegrationError


def title_card(text: str, source: str, path: Path):
    """Locally generated card using short original headline, not an article copy."""
    from PIL import Image,ImageDraw,ImageFont
    width,height=850,730
    image=Image.new('RGBA',(width,height),(12,16,40,246))
    d=ImageDraw.Draw(image)
    d.rounded_rectangle((20,20,830,705),radius=32,outline=(255,40,178),width=8)
    d.rectangle((55,88,795,96),fill=(58,229,232))
    try:
        font=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',39)
        small=ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',23)
    except OSError:
        font=ImageFont.load_default();small=font
    d.text((60,45),'GTA 6 BRASIL',font=small,fill='#68e3ff')
    lines=wrap(str(text)[:180],width=23)[:6]
    for i,line in enumerate(lines):
        d.text((59,135+i*75),line,font=font,fill='white',stroke_width=1,stroke_fill='#210a36')
    d.line((60,605,790,605),fill=(255,43,168),width=5)
    d.text((60,637),str(source)[:58],font=small,fill='#ccbbdd')
    image.save(path)
    return path


def _filtered_base(ff, spec, seconds, path, work, index):
    """Output segment 1080x1920 H.264 with no audio, from a copied asset."""
    from backend import media
    base=spec.get('path')
    base_kind=spec.get('type')
    if not base or base_kind=='animated_gradient':
        from backend.assets import MissingAssetsError
        raise MissingAssetsError(['assets/gameplay/'],f'Cena {index}: sem gameplay autorizado')
    base=str(db.safe_file(base))
    args=[ff,'-y']
    if base_kind=='video':
        args+=['-stream_loop','-1','-ss',str(spec.get('source_offset',0)),'-i',base]
        visual='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1'
    else:
        args+=['-loop','1','-framerate','30','-i',base]
        visual="scale=1100:1970:force_original_aspect_ratio=increase,crop=1100:1970,zoompan=z='min(zoom+0.0007,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30"
    overlay=spec.get('overlay_path')
    if not overlay and spec.get('overlay_label')=='headline-card':
        url=spec.get('overlay_source') or 'Fonte declarada no roteiro'
        source=url.split('/')[2] if '://' in url else 'Fonte identificada'
        overlay=str(title_card(spec.get('overlay_text','Notícia em análise'),source,work/f'news-{index}.png'))
    elif overlay:
        overlay=str(db.safe_file(overlay))
    if overlay:
        args+=['-loop','1','-framerate','30','-i',overlay]
        # Show at most four seconds, leaving clean gameplay between excerpts.
        until=max(.6,min(4.0,seconds-.2))
        filt=f'[0:v]{visual}[base];[1:v]scale=760:900:force_original_aspect_ratio=decrease,format=rgba,fade=t=in:st=0:d=0.15:alpha=1[card];[base][card]overlay=x=(W-w)/2:y=145+4*sin(2*PI*t/3):enable=\'between(t,0.15,{until:.2f})\'[video]'
        args+=['-filter_complex',filt,'-map','[video]']
    else:
        args+=['-vf',visual]
    args+=['-t',str(seconds),'-an','-r','30','-c:v','libx264',
           '-preset','veryfast','-crf','25','-pix_fmt','yuv420p','-threads','2',str(path)]
    media.run(args,timeout=300)


def _support_clip(ff,spec,seconds,target):
    from backend import media
    path=db.safe_file(spec['source_clip_path'])
    length=float(media.probe(path)['format']['duration'])
    offset=min(max(0,float(spec.get('source_clip_at') or 0)),max(0,length-seconds))
    media.run([ff,'-y','-ss',str(offset),'-i',str(path),'-t',str(seconds),'-an',
       '-vf','scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
       '-r','30','-c:v','libx264','-preset','veryfast','-crf','25','-pix_fmt','yuv420p',
       '-threads','2',str(target)],timeout=260)


def montage(video,script,attempt,work):
    """Every scene rendered from licensed gameplay; news cards are overlays, not video backgrounds."""
    from backend import assets,media
    ff=media.binary('ffmpeg')
    visuals=assets.select_visuals(video,script)
    db.atomic(db.ROOT/'handoff'/video['id']/f'visual-assets-attempt-{attempt}.json',
              json.dumps(visuals,indent=2,ensure_ascii=False))
    durations=[float(part.get('duration') or 0) for scene in visuals for part in scene.get('segments',[])]
    source_seconds=sum(float(part.get('duration') or 0) for scene in visuals
                       for part in scene.get('segments',[]) if part.get('overlay_path'))
    report={'segments':len(durations),'cuts_per_minute':round(max(0,len(durations)-1)*60/max(.1,script.duration),2),
            'longest_unmodified_seconds':max(durations) if durations else None,
            'source_visual_fraction':round(source_seconds/max(.1,script.duration),3),
            'semantic_curation_verified':any(part.get('visual_relevance_method')=='vision'
               for scene in visuals for part in scene.get('segments',[]))}
    db.atomic(db.ROOT/'handoff'/video['id']/f'visual-rhythm-attempt-{attempt}.json',
              json.dumps(report,ensure_ascii=False,indent=2))
    cuts=[]
    segment_cache=db.ROOT/'videos/processing'/video['id']/'segment-cache';segment_cache.mkdir(parents=True,exist_ok=True)
    for scene_index,(scene,spec) in enumerate(zip(script.scenes,visuals)):
        duration=round(scene.end-scene.start,3)
        if duration<=0:raise IntegrationError(f'Cena {scene_index+1}: duração inválida.')
        segments=spec.get('segments') or [{**spec,'duration':duration}]
        for segment_index,segment in enumerate(segments):
            seconds=float(segment.get('duration') or 0)
            if seconds<.01:continue
            part=work/f'background-{scene_index:02d}-{segment_index:02d}.mp4'
            # Re-use unchanged segment renders between attempts; never alter originals.
            path=db.ROOT/segment['path'] if segment.get('path') else None
            overlay_path=db.ROOT/segment['overlay_path'] if segment.get('overlay_path') else None
            signature={'spec':segment,'seconds':seconds,
                'file_size':path.stat().st_size if path and path.is_file() else None,
                'file_mtime_ns':path.stat().st_mtime_ns if path and path.is_file() else None,
                'overlay_size':overlay_path.stat().st_size if overlay_path and overlay_path.is_file() else None,
                'overlay_mtime_ns':overlay_path.stat().st_mtime_ns if overlay_path and overlay_path.is_file() else None}
            key=hashlib.sha256(json.dumps(signature,sort_keys=True,default=str).encode()).hexdigest()
            cache=segment_cache/(key+'.mp4')
            try:
                if cache.is_file() and cache.stat().st_size>1000:shutil.copy2(cache,part)
                else:
                    if segment.get('source_clip_path'):
                        _support_clip(ff,segment,seconds,part)
                    else:
                        _filtered_base(ff,segment,seconds,part,work,scene_index*100+segment_index)
                    shutil.copy2(part,cache)
            except Exception as exc:
                db.log_event(video['id'],'media','RENDER_ERROR',f'Cena {scene_index+1}: {exc}'[:500])
                raise media.PreflightError(f'Falha real de composição na cena {scene_index+1}, trecho {segment_index+1}: {exc}') from exc
            cuts.append(part)
    if not cuts:raise IntegrationError('Nenhum visual criado na montagem.')
    # Re-encode concatenated clips to avoid timestamp drift between segments.
    listing=work/'visuals.txt'
    listing.write_text('\n'.join(f"file '{p.name}'" for p in cuts),encoding='utf-8')
    result=work/'visual-montage.mp4'
    media.run([ff,'-y','-f','concat','-safe','0','-i',listing.name,
           '-an','-c:v','libx264','-preset','veryfast','-pix_fmt','yuv420p','-r','30',
           '-threads','2',result.name],cwd=work,timeout=600)
    return result,visuals
