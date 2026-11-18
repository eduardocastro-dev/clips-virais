"""Deterministic script timing repair. The model never controls production duration/template."""
from __future__ import annotations
import copy
import re


def normalize(payload: dict, duration: int, template: str, video_id: str):
    """Return corrected raw Script payload + auditable field-level fixes.

    Runs *before* Pydantic contiguous validation. Trims narration to fit the
    scheduled slot and redistributes scene timings based on narration density.
    """
    data=copy.deepcopy(payload)
    fixes=[]
    if data.get('duration')!=duration:
        fixes.append({'field':'duration','from':data.get('duration'),'to':duration,'reason':'duração definida pelo pedido/template'})
    if data.get('template')!=template:
        fixes.append({'field':'template','from':data.get('template'),'to':template,'reason':'template da produção'})
    data['duration']=duration
    data['template']=template
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
    total=sum(weights);left=float(duration)
    times=[];t=0.0
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
        # Keep short meaningful narration rather than stretch Piper until it breaks.
        max_words=max(3,int((end-t)*2.15))
        words=str(s.get('narration') or 'Acompanhe os detalhes.').split()
        if len(words)>max_words:
            truncated=' '.join(words[:max_words]).rstrip(',;:.')+'.'
            s['narration']=truncated
            fixes.append({'field':f'scenes[{index}].narration','from':len(words),'to':max_words,'reason':'ajuste de palavras para tempo de voz'})
        if previous!=(s['start'],s['end']):
            fixes.append({'field':f'scenes[{index}].timestamps','from':list(previous),'to':[s['start'],s['end']],'reason':'sincronização contínua'})
        times.append((t,end));t=end
    data['scenes']=scenes
    return data,fixes
