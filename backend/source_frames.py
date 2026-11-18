"""Source frame sampling/curation for editorial illustrations.

This module only reads local licensed media or already acquired temporary copies.
It does NOT treat public access, a video thumbnail, or attribution as permission.
"""
from __future__ import annotations
import hashlib
import json
import math
import shutil
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat
from backend import core as db


def fingerprint(img:Image.Image)->str:
    small=img.convert('L').resize((9,8))
    pixel=list(small.getdata())
    bits=[]
    for y in range(8):
        for x in range(8):bits.append('1' if pixel[y*9+x]>pixel[y*9+x+1] else '0')
    return hex(int(''.join(bits),2))


def image_quality(path:Path, seen:set[str])->bool:
    try:
        with Image.open(path) as im:
            gray=im.convert('L').resize((256,256))
            luma=ImageStat.Stat(gray).mean[0]
            edge=ImageStat.Stat(gray.filter(ImageFilter.FIND_EDGES)).var[0]
            key=fingerprint(gray)
        if luma<23 or luma>241 or edge<35 or key in seen:
            return False
        seen.add(key);return True
    except (OSError,ValueError):return False


def extract(video_id:str, source:Path, interval:float=2.0, max_frames:int=40)->list[dict]:
    """FFmpeg scene-change + distributed sampling; dedup by perceptual hash."""
    from backend import media,production_media
    folder=production_media.workspace(video_id)/'source-frames'
    folder.mkdir(parents=True,exist_ok=True)
    manifest=folder/'frames.json'
    digest=hashlib.sha256((str(source.resolve())+str(source.stat().st_size)+str(source.stat().st_mtime_ns)+str(interval)+str(max_frames)).encode()).hexdigest()
    if manifest.exists():
        try:
            data=json.loads(manifest.read_text('utf-8'))
            if data.get('digest')==digest and all((db.ROOT/f['path']).is_file() for f in data['frames']):return data['frames']
        except (KeyError,TypeError,ValueError):pass
    for old in folder.glob('*.jpg'):old.unlink()
    ff=media.binary('ffmpeg')
    streams=media.probe(source)
    duration=float(streams['format']['duration'])
    if duration<=0:return []
    step=max(float(interval),duration/max_frames)
    # Use separate fast sampler and scene-change detector, then combine.
    try:
        media.run([ff,'-y','-hide_banner','-loglevel','error','-i',str(source),'-vf',
          f'fps=1/{step:.3f},scale=480:-2','-q:v','5','-frames:v',str(max_frames),str(folder/'time-%03d.jpg')],timeout=200)
        # Scene detection frames are additional candidates, not a substitute for temporal coverage.
        media.run([ff,'-y','-hide_banner','-loglevel','error','-i',str(source),'-vf',
          "select='gt(scene,0.30)',scale=480:-2",'-vsync','vfr','-q:v','5',
          '-frames:v',str(max_frames),str(folder/'scene-%03d.jpg')],timeout=200)
    except Exception as exc:
        db.log_event(video_id,'media','SOURCE_FRAME_FAILURE',str(exc)[:500])
        # Some codecs lack scene detection; retain whatever sampling succeeded.
    seen=set();frames=[]
    for path in sorted(folder.glob('time-*.jpg'))+sorted(folder.glob('scene-*.jpg')):
        if not image_quality(path,seen):
            path.unlink(missing_ok=True);continue
        if path.name.startswith('time-'):
            position=max(.0,(int(path.stem.split('-')[1])-1)*step)
        else:position=None  # unknown without showinfo PTS; don't invent it
        frames.append({'path':str(path.relative_to(db.ROOT)),
                       'source_timestamp':position,'origin':'source_video',
                       'frame_hash':hashlib.sha256(path.read_bytes()).hexdigest()})
    # Make the supported PTS explicit: for scene detector output timestamp is unknown.
    db.atomic(manifest,json.dumps({'digest':digest,'frames':frames},ensure_ascii=False,indent=2))
    return frames


def review_with_vision(video:dict, script, frames:list[dict])->dict[int,list[dict]]:
    """One independent visual-semantic review. No fake confidence values.

    If route vision is unavailable, no scores are asserted and caller falls back
    to gameplay/source cards rather than pretending a model reviewed the images.
    """
    from backend.integrations import llm,IntegrationError
    route=db.settings().routes.get('escritor')
    if not route or not route.vision or not frames:return {}
    stride=max(1,math.ceil(len(frames)/16))
    selected=frames[::stride][:16]
    paths=[db.ROOT/x['path'] for x in selected]
    schema={'type':'object','properties':{'selections':{'type':'array','items':{'type':'object',
       'properties':{'scene':{'type':'integer'},'frame':{'type':'integer'},
                     'relevance':{'type':'number'},'reason':{'type':'string'}},
       'required':['scene','frame','relevance','reason']}}},'required':['selections']}
    try:
        result=llm('escritor',video['id'],{'task':'Associe frames à narração APENAS se houver correspondência visual direta. '
              'Não invente elementos que não estejam nas imagens. Se não houver frame apropriado, omita a cena.',
              'source_url':video.get('url'), 'source_name':video.get('title'),
              'frames':[{'index':i,'source_timestamp':f['source_timestamp']} for i,f in enumerate(selected)],
              'scenes':[{'index':i,'narration':s.narration} for i,s in enumerate(script.scenes)]},schema,images=paths)
    except IntegrationError as exc:
        db.log_event(video['id'],'escritor','VISUAL_VISION_UNAVAILABLE',str(exc)[:500]);return {}
    output={}
    for item in result.get('selections',[]):
        try:
            scene=int(item['scene']);idx=int(item['frame']);score=float(item['relevance'])
            if not (0<=scene<len(script.scenes) and 0<=idx<len(selected) and
                    db.settings().source_min_relevance<=score<=10):continue
            candidate={**selected[idx],'relevance':score,'relevance_method':'vision',
                       'reason':str(item.get('reason') or '')[:260]}
            output.setdefault(scene,[])
            if not any(x['path']==candidate['path'] for x in output[scene]):
                output[scene].append(candidate)
                output[scene].sort(key=lambda x:-x['relevance'])
                output[scene]=output[scene][:4]
        except (TypeError,ValueError,KeyError):continue
    return output
