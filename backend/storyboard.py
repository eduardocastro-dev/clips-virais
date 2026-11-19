"""Deterministic script timing repair. The model never controls production duration/template."""
from __future__ import annotations
import copy
import re
import math


def normalize(payload: dict, duration: int, template: str, video_id: str, *, source_seconds: float | None = None):
    """Return corrected raw Script payload + auditable field-level fixes.

    Runs *before* Pydantic contiguous validation. Never destroys spoken text:
    only the measured Piper voice, not scene length or an assumed WPS, can
    decide if narration is too long. Source offsets are seconds into licensed
    local footage, never frames or milliseconds.
    """
    data=copy.deepcopy(payload)
    fixes=[]
    if data.get('duration')!=duration:
        fixes.append({'field':'duration','from':data.get('duration'),'to':duration,'reason':'duração definida pelo pedido/template'})
    if data.get('template')!=template:
        fixes.append({'field':'template','from':data.get('template'),'to':template,'reason':'template da produção'})
    data['duration']=duration
    data['template']=template
    # Music for a Script is intentionally 'none'. Licensed music is selected
    # separately from the asset catalogue by audio_mix, never by the LLM.
    if data.get('music','none') != 'none':
        fixes.append({'field':'music','from':data.get('music'),'to':'none',
                      'reason':'sem catálogo licenciado para seleção por nome no Script; mixagem usa biblioteca verificada'})
        data['music']='none'
    scenes=data.get('scenes',[])
    if not isinstance(scenes,list) or not scenes:
        raise ValueError('scenes: roteiro não contém cenas; requer nova geração pelo Escritor')
    if len(scenes)==1:
        one=copy.deepcopy(scenes[0]);two=copy.deepcopy(one)
        words=(one.get('narration') or ' ').split();split=max(1,len(words)//2)
        one['narration']=' '.join(words[:split]) or 'Introdução.'
        two['narration']=' '.join(words[split:]) or 'Acompanhe os próximos detalhes.'
        scenes[:]=[one,two]
        fixes.append({'field':'scenes','from':1,'to':2,'reason':'mínimo duas cenas'})
    if len(scenes)>12:
        scenes[:]=scenes[:12]
        fixes.append({'field':'scenes','from':'mais de 12','to':12,'reason':'limite do roteiro'})
    # Remove overlaps and gaps and allocate more space to longer narration.
    lengths=[max(1,len(str(s.get('narration') or '').split())) for s in scenes]
    weights=[max(1,n) for n in lengths]
    total=sum(weights)
    t=0.0
    for index,s in enumerate(scenes):
        remaining=len(scenes)-index-1
        if index==len(scenes)-1:
            end=float(duration)
        else:
            ideal=duration*weights[index]/total
            # 0.8 second minimum per scene keeps even very short renders valid.
            end=min(duration-remaining*.8,t+max(.8,ideal))
            end=round(end,2)
        if end<=t:raise ValueError('scenes: cenas demais para a duração solicitada')
        previous=(s.get('start'),s.get('end'))
        s['start']=round(t,2);s['end']=round(end,2)
        s['source_id']=video_id
        # 'source_start' is offset in seconds into the actual, authorized video.
        # Schema's 600s ceiling must remain. If there is no local source,
        # no offsets should be guessed: only visuals from the asset library apply.
        old_offset=s.get('source_start',0)
        try:
            proposed=float(old_offset)
            if not math.isfinite(proposed):raise ValueError('non-finite')
        except (TypeError,ValueError):
            proposed=0.
        scene_length=end-t
        if source_seconds is None:
            limit=0.  # reference-only/unknown source never pretends to have footage
            reason='sem vídeo-fonte local autorizado; offset deve ser zero'
        elif source_seconds < scene_length - .01:
            raise ValueError(f'scenes[{index}].source_start: cena de {scene_length:.2f}s não cabe na fonte local de {source_seconds:.2f}s')
        else:
            limit=max(0.,min(600.,source_seconds-scene_length))
            reason=f'offset em segundos; limite min(600, fonte {source_seconds:.2f}s - cena {scene_length:.2f}s)'
        corrected=round(max(0.,min(proposed,limit)),2)
        if old_offset!=corrected:
            fixes.append({'field':f'scenes[{index}].source_start','from':old_offset,
                          'to':corrected,'reason':reason})
        s['source_start']=corrected
        if previous!=(s['start'],s['end']):
            fixes.append({'field':f'scenes[{index}].timestamps','from':list(previous),'to':[s['start'],s['end']],'reason':'sincronização contínua'})
        t=end
    data['scenes']=scenes
    return data,fixes


def local_source_seconds(root, video_id: str, rights: str) -> float | None:
    """Actual measured duration of locally available licensed source footage.

    Metadata from the internet does not establish that a playable file exists.
    If no source exists, the editor must not invent source_start positions.
    """
    from pathlib import Path
    if rights != 'AUTHORIZED':
        return None
    folder=Path(root)/'temp'/video_id
    if not folder.is_dir():
        return None
    path=next((p for p in sorted(folder.glob('source.*'))
               if p.is_file() and p.suffix.lower() in ('.mp4','.webm','.mov','.mkv')),None)
    if not path:
        return None
    from backend import media
    try:
        seconds=float(media.probe(path)['format']['duration'])
        return seconds if 0<seconds<100000 else None
    except (OSError,ValueError,KeyError,TypeError,RuntimeError):
        return None
