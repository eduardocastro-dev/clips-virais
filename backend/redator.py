"""Sixth agent: narration text revision with auditable before/after handoff."""
import json
import re
from backend import core as db
from backend.contracts import Script
from backend.integrations import llm
from backend.personas import get_cast

NUMBER_NAMES = dict(enumerate('zero um dois três quatro cinco seis sete oito nove dez onze doze treze quatorze quinze'.split()))

def narration_ready(text):
    text = re.sub(r'(?i)GTA\s*6\b', 'GTA seis', text)
    text = re.sub(r'(?i)GTA\s*5\b', 'GTA cinco', text)
    text = re.sub(r'\b\d+\b', lambda m: NUMBER_NAMES.get(int(m.group()),m.group()),text)
    text = re.sub(r'[\U0001F000-\U0010FFFF#@]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    sentences=[]
    for sentence in re.split(r'(?<=[.!?])\s+', text):
        words=sentence.split()
        while len(words)>20:
            sentences.append(' '.join(words[:20]).rstrip(',;:.')+'.')
            words=words[20:]
        if words:
            sentences.append(' '.join(words).rstrip(',;:.!?') + (sentence[-1] if sentence.endswith(('?','!')) else '.'))
    return ' '.join(sentences)


def polish(video, script:Script, attempt:int=1):
    before=script.model_dump()
    cast=get_cast()
    # Speaker references cannot resolve to unknown voices.
    script_data=script.model_dump()
    for scene in script_data['scenes']:
        if scene.get('speaker') not in cast:scene['speaker']='dante_palma'
    structural_errors=[]
    if not video.get('test') and db.settings().redator_ai:
        # Only wording/voice may change. Script metadata, factual scope, scene timings stay fixed.
        schema={'type':'object','properties':{'scenes':{'type':'array','items':{'type':'object',
          'properties':{'narration':{'type':'string'},'text':{'type':'string'},'speaker':{'type':'string'}},
          'required':['narration','text','speaker']}}},'required':['scenes']}
        for rewrite in range(2):
            result=llm('redator',video['id'],{'role':'redator','today_sao_paulo':db.today(),
                 'source_facts':db.read_artifact(video['id'],'cacador').dados,
                 'script':script_data,'cast':cast,'structural_feedback':structural_errors,
                 'instructions':'Revise somente redação para fala natural PT-BR. Não altere duração, '
                 'cenas, fatos, fonte, template nem eventos. Uma entrada por cena na mesma ordem. '
                 'Corrija frases cortadas e repetições. Escreva números por extenso, sem emojis. '
                 'Cada personagem mantém seu próprio jeito de falar; frases curtas até 14 palavras e energia com naturalidade. '
                 'Não apresente alegações incertas como certezas. Não inclua selos ou falas "fato/rumor/fake/confirmado".'},schema)
            candidate=result.get('scenes',[])
            if len(candidate)==len(script_data['scenes']):
                for row,change in zip(script_data['scenes'],candidate):
                    row['narration']=str(change.get('narration') or row['narration'])
                    row['text']=str(change.get('text') or row['text'])
                    row['speaker']=change.get('speaker') if change.get('speaker') in cast else row['speaker']
                break
            structural_errors.append('Redator retornou número divergente de cenas; preserve a estrutura.')
    for row in script_data['scenes']:
        row['narration']=narration_ready(row['narration'])
    from backend.editorial_style import screen_copy
    script_data['hook']=screen_copy(script_data['hook'])
    script_data['cta']=screen_copy(script_data.get('cta',''))
    for row in script_data['scenes']:
        row['text']=screen_copy(row.get('text',''))
        row['narration']=screen_copy(row.get('narration',''))
    reviewed=Script.model_validate(script_data)
    folder=db.ROOT/'handoff'/video['id'];folder.mkdir(parents=True,exist_ok=True)
    changes=[]
    for idx,(old,new) in enumerate(zip(before['scenes'],reviewed.model_dump()['scenes']),1):
        for name in ('narration','text','speaker'):
            if old.get(name)!=new.get(name):
                changes.append({'scene':idx,'field':name,'before':old.get(name),'after':new.get(name)})
    output={'before':before,'after':reviewed.model_dump(),'changes':changes,'today_sao_paulo':db.today(),
            'structural_return_count':len(structural_errors)}
    db.atomic(folder/f'redator-attempt-{attempt}.json',json.dumps(output,ensure_ascii=False,indent=2))
    db.atomic(folder/'script.json',reviewed.model_dump_json(indent=2))
    db.artifact(video['id'],'redator',data={'changes':changes,'today_sao_paulo':db.today()},
                files=[f'handoff/{video["id"]}/redator-attempt-{attempt}.json'],next_agent='editor')
    return reviewed


def adjust_timing(video,script:Script,issue,attempt:int,correction:int):
    """Fix TTS duration without spending a video evaluation attempt.

    Only narration may change; source metadata, speakers, scene boundaries,
    factual claims and visual assets remain untouched.
    """
    from backend.media import PreflightError
    target=issue.target
    too_long=issue.actual>target
    ratio=target/max(.1,issue.actual)
    budget=[max(3,int(len(scene.narration.split())*ratio*(.92 if too_long else 1.05)))
            for scene in script.scenes]
    # Ask the Redator to make the most localized factual rewrite possible.
    schema={'type':'object','properties':{'narrations':{'type':'array','items':{'type':'string'}}},
            'required':['narrations']}
    try:
        result=llm('redator',video['id'],{'role':'tts_timing_redator', 'today_sao_paulo':db.today(),
          'task':'Encurte somente narrações com repetição' if too_long else 'Amplie somente cenas com contexto factual verificável',
          'script':script.model_dump(), 'seconds_target':target, 'seconds_measured':issue.actual,
          'seconds_by_scene':issue.scenes, 'word_budget_per_scene':budget,
          'constraints':'Preserve todos os fatos e indicadores de rumor. Não altere cenas, ordem, speaker, '
           'emoções, duração do template, fontes ou CTA. Evite cortes abruptos e enchimento artificial. '
           'Retorne exatamente uma narração por cena, terminando em pontuação.'},schema)
    except IntegrationError as exc:
        raise PreflightError('Redator não conseguiu corrigir o orçamento temporal: '+str(exc)) from exc
    narrations=result.get('narrations')
    if not isinstance(narrations,list) or len(narrations)!=len(script.scenes):
        raise PreflightError('Redator retornou quantidade de cenas incorreta para ajuste de TTS.')
    data=script.model_dump();changes=[]
    for index,text in enumerate(narrations):
        revised=narration_ready(str(text))
        if not revised:raise PreflightError('Redator retornou cena sem narração.')
        if revised!=data['scenes'][index]['narration']:
            changes.append({'scene':index+1,'before':data['scenes'][index]['narration'],
                            'after':revised,'reason':'Ajuste temporal sem mudar o template'})
            data['scenes'][index]['narration']=revised
    if not changes:
        raise PreflightError('Redator não conseguiu melhorar o orçamento temporal do TTS.')
    revised=Script.model_validate(data)
    folder=db.ROOT/'handoff'/video['id'];folder.mkdir(exist_ok=True,parents=True)
    db.atomic(folder/f'narration-timing-adjust-{attempt}-{correction}.json',
              json.dumps({'measured_s':issue.actual,'target_s':target,'changes':changes},indent=2,ensure_ascii=False))
    db.atomic(folder/'script.json',revised.model_dump_json(indent=2))
    db.log_event(video['id'],'redator','TTS_TIMING_CORRECTION',
                f'Ajuste {correction}/2; {len(changes)} cenas alteradas; medida anterior={issue.actual:.2f}s')
    return revised
