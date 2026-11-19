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


def title_card(text: str, source: str, path: Path, badge: str = 'RADAR GTA 6', accent = (58, 229, 232)):
    """Locally generated modern editorial card using short original headline."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = 860, 680
    image = Image.new('RGBA', (width, height), (15, 23, 42, 215))
    d = ImageDraw.Draw(image)
    d.rounded_rectangle((15, 15, width - 15, height - 15), radius=32, outline=accent, width=6)
    badge_text = str(badge).upper()[:22]
    d.rounded_rectangle((50, 45, 290, 95), radius=16, fill=(30, 41, 59, 240), outline=accent, width=2)
    try:
        font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 38)
        small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 24)
        badge_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 22)
    except OSError:
        font = ImageFont.load_default(); small = font; badge_font = font
    d.text((68, 57), badge_text, font=badge_font, fill=accent)
    domain = str(source).split('/')[0].replace('www.', '')[:35]
    d.text((315, 60), f"FONTE: {domain}", font=small, fill='#94a3b8')
    lines = wrap(str(text)[:190], width=25)[:5]
    for i, line in enumerate(lines):
        d.text((55, 140 + i * 80), line, font=font, fill='white', stroke_width=1, stroke_fill='#090d16')
    d.line((50, height - 85, width - 50, height - 85), fill=accent, width=4)
    d.text((55, height - 60), 'GTA 6 BRASIL · DIREÇÃO EDITORIAL', font=small, fill='#94a3b8')
    image.save(path)
    return path


def style_screenshot_card(img_path: Path, out_path: Path, source_label: str = '', badge: str = 'FONTE ORIGINAL', accent = (58, 229, 232)):
    """Styles a raw screenshot or source thumbnail inside a branded broadcast card."""
    from PIL import Image, ImageDraw, ImageFont
    width, height = 860, 660
    card = Image.new('RGBA', (width, height), (15, 23, 42, 245))
    d = ImageDraw.Draw(card)
    d.rounded_rectangle((12, 12, width - 12, height - 12), radius=30, outline=accent, width=5)
    try:
        small = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 23)
        badge_font = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf', 21)
    except OSError:
        small = ImageFont.load_default(); badge_font = small
    d.rounded_rectangle((40, 35, 275, 80), radius=14, fill=(30, 41, 59, 240), outline=accent, width=2)
    d.text((55, 46), str(badge).upper()[:20], font=badge_font, fill=accent)
    clean_src = (source_label.split('/')[2] if '://' in source_label else source_label).replace('www.', '')[:40]
    if clean_src:
        d.text((295, 48), f"REF: {clean_src}", font=small, fill='#94a3b8')
    try:
        with Image.open(img_path) as im:
            im = im.convert('RGBA')
            target_w, target_h = width - 80, height - 150
            im.thumbnail((target_w, target_h), Image.Resampling.LANCZOS)
            mask = Image.new('L', im.size, 0)
            ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0], im.size[1]), radius=20, fill=255)
            paste_x = (width - im.size[0]) // 2
            paste_y = 100 + (target_h - im.size[1]) // 2
            card.paste(im, (paste_x, paste_y), mask)
            d.rounded_rectangle((paste_x - 1, paste_y - 1, paste_x + im.size[0] + 1, paste_y + im.size[1] + 1), radius=20, outline=(51, 65, 85, 220), width=2)
    except Exception:
        pass
    card.save(out_path)
    return out_path


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
        # Gentle alternating virtual camera motion; keep the original footage unaltered.
        from backend.viral_edit import camera_profile
        profile=camera_profile(index)
        horizontal=('30+20*sin(t*0.85)' if profile=='push_in' else
                    '30+23*sin(t*0.65)' if profile=='drift_left' else '30-23*sin(t*0.65)')
        visual=('scale=1140:2025:force_original_aspect_ratio=increase,crop=1140:2025,'
                f'crop=1080:1920:x={horizontal}:y=52+25*cos(t*0.55),setsar=1')
    else:
        args+=['-loop','1','-framerate','30','-i',base]
        visual="scale=1100:1970:force_original_aspect_ratio=increase,crop=1100:1970,zoompan=z='min(zoom+0.0007,1.15)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s=1080x1920:fps=30"
    overlay=spec.get('overlay_path')
    if not overlay and spec.get('overlay_label')=='headline-card':
        url=spec.get('overlay_source') or 'Fonte declarada no roteiro'
        source=url.split('/')[2] if '://' in url else 'Fonte identificada'
        overlay=str(title_card(spec.get('overlay_text','Notícia em análise'),source,work/f'news-{index}.png'))
    elif overlay:
        raw_overlay=db.safe_file(overlay)
        styled_overlay=work/f'styled-card-{index}.png'
        label=spec.get('overlay_label') or 'FONTE ORIGINAL'
        src_url=spec.get('overlay_source') or ''
        overlay=str(style_screenshot_card(raw_overlay,styled_overlay,src_url,badge='FONTE ORIGINAL' if label!='thumbnail' else 'THUMBNAIL FONTE'))
    from backend.viral_edit import overlay_window
    visible=overlay_window(seconds) if overlay else None
    if overlay and visible:
        args+=['-loop','1','-framerate','30','-i',overlay]
        begin,until=visible
        filt=(
            f'[0:v]{visual}[base];'
            f'[1:v]scale=760:740:force_original_aspect_ratio=decrease,format=rgba,'
            f'fade=t=in:st=0:d=0.16:alpha=1,fade=t=out:st={until-.16:.2f}:d=0.16:alpha=1[card];'
            f'[base][card]overlay=x=(W-w)/2:y=360+7*sin(2*PI*t/3.5):'
            f"enable='between(t,{begin:.2f},{until:.2f})'[video]"
        )
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
    credits=(spec.get('credits') or spec.get('source') or '').strip()
    clean_credit=re.sub(r'[^A-Za-z0-9_.\- /@:]+', ' ', credits)[:45].strip()
    vf='scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1'
    if clean_credit:
        vf+=f",drawtext=text='FONTE: {clean_credit}':x=w-tw-50:y=170:fontcolor=white:fontsize=26:box=1:boxcolor=black@0.7:boxborderw=8"
    media.run([ff,'-y','-ss',str(offset),'-i',str(path),'-t',str(seconds),'-an',
       '-vf',vf,
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
