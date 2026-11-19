"""Sixth agent: narration text revision with auditable before/after handoff."""
import json
import re
import math
from backend import core as db
from backend.contracts import Script
from backend.integrations import llm, IntegrationError
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


def auto_reduce_narration(script: Script, measured_seconds: float, target_seconds: float) -> Script:
    """Conservative, measured fallback: remove exact duplicate sentences only.

    Blindly deleting articles, source facts or merging scenes creates invalid or
    misleading narration. If this cannot help, a worker retry is safer.
    """
    if measured_seconds <= target_seconds:
        return script
    content = script.model_dump()
    changed = False
    for scene in content['scenes']:
        phrases = re.split(r'(?<=[.!?])\s+', scene['narration'].strip())
        unique = []
        seen = set()
        for phrase in phrases:
            normalized = re.sub(r'\W+', '', phrase, flags=re.UNICODE).casefold()
            if normalized and normalized in seen:
                changed = True
                continue
            seen.add(normalized)
            unique.append(phrase)
        if unique:
            scene['narration'] = ' '.join(unique)
    return Script.model_validate(content) if changed else script


def polish(video, script:Script, attempt:int=1):
    before=script.model_dump()
    cast=get_cast()
    # Speaker references cannot resolve to unknown voices.
    script_data=script.model_dump()
    for scene in script_data['scenes']:
        if scene.get('speaker') not in cast:scene['speaker']='dante_palma'
    structural_errors=[]
    from backend.narration_budget import script_budget
    budget=script_budget(script.duration,db.settings().narration_margin_seconds,cast,script.scenes)
    original_words=sum(_word_count(row['narration']) for row in script_data['scenes'])
    words_delta=max(0,budget['total_words_target']-original_words)
    if not video.get('test') and db.settings().redator_ai:
        # Only wording/voice may change. Script metadata, factual scope, scene timings stay fixed.
        schema={'type':'object','properties':{'scenes':{'type':'array','items':{'type':'object',
          'properties':{'narration':{'type':'string'},'text':{'type':'string'},'speaker':{'type':'string'}},
          'required':['narration','text','speaker']}}},'required':['scenes']}
        for rewrite in range(2):
            try:
                result=llm('redator',video['id'],{'role':'redator','today_sao_paulo':db.today(),
                 'source_facts':db.read_artifact(video['id'],'cacador').dados,
                 'script':script_data,'cast':cast,'structural_feedback':structural_errors,
                 'narration_word_budget':budget,
                 'current_word_count':original_words,
                 'word_delta_to_target':words_delta,
                 'instructions':'Revise somente redação para fala natural PT-BR. Não altere duração, '
                 'cenas, fatos, fonte, template nem eventos. Uma entrada por cena na mesma ordem. '
                 'Corrija frases cortadas e repetições. Escreva números por extenso, sem emojis. '
                 'Ajuste a contagem total para narration_word_budget.total_words_target; '
                 'observe words_by_scene_target e o delta de palavras. A fonte não permite inventar fatos. '
                 'Cada personagem mantém seu próprio jeito de falar; frases curtas até 14 palavras e energia com naturalidade. '
                 'Não apresente alegações incertas como certezas. Não inclua selos ou falas "fato/rumor/fake/confirmado".'},schema)
            except IntegrationError as exc:
                structural_errors.append('Modelo indisponível; preservando roteiro do Escritor: ' + str(exc)[:180])
                db.log_event(video['id'],'redator','MODEL_FALLBACK',str(exc)[:300])
                break
            candidate=result.get('scenes',[]) if isinstance(result, dict) else []
            if len(candidate)==len(script_data['scenes']):
                before_words=sum(_word_count(row['narration']) for row in script_data['scenes'])
                after_words=sum(_word_count(row.get('narration') or '') for row in candidate)
                if after_words < max(5,int(before_words*.85)):
                    structural_errors.append(
                        f'Redação abreviada demais: {before_words}→{after_words} palavras. '
                        f'Meta de {budget["total_words_target"]} palavras; faltam '
                        f'{max(0,budget["total_words_target"]-after_words)}. '
                        'Mantenha contexto e informações relevantes para o TTS; não resuma o vídeo todo.')
                    continue
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
            'narration_word_budget':budget,'words_after':sum(_word_count(sc.narration) for sc in reviewed.scenes),
            'structural_return_count':len(structural_errors)}
    db.atomic(folder/f'redator-attempt-{attempt}.json',json.dumps(output,ensure_ascii=False,indent=2))
    db.atomic(folder/'script.json',reviewed.model_dump_json(indent=2))
    db.artifact(video['id'],'redator',data={'changes':changes,'today_sao_paulo':db.today()},
                files=[f'handoff/{video["id"]}/redator-attempt-{attempt}.json'],next_agent='editor')
    return reviewed


def _word_count(text: str) -> int:
    return len(str(text).split())


def _timing_targets(script: Script, measured_seconds: float, target_seconds: float) -> list[int]:
    """Assign realistic *minimum* word targets from measured Piper speech.

    A blanket 2.5 words/second is unreliable across Portuguese voices. Use
    measured duration and the exact text that generated that audio instead.
    These are instructions to the LLM, never fabricated TTS timestamps.
    """
    current=[_word_count(scene.narration) for scene in script.scenes]
    if not current or measured_seconds <= 0:
        return current
    # Aim slightly into the compliant window, not precisely at its boundary.
    desired=max(1.0,target_seconds - .7)
    ratio=desired/measured_seconds
    # First try to converge in one edit, but don't ask for an unrealistic 3x
    # expansion in a single scene, which often causes an LLM to ignore us.
    ratio=max(.55,min(2.4,ratio))
    return [max(5,math.ceil(words*ratio)) for words in current]


def _source_context(video_id: str) -> dict:
    """Read the existing evidence ledger; never fabricate missing source facts."""
    evidence=db.ROOT/'handoff'/video_id/'facts.json'
    if not evidence.is_file():
        return {}
    try:
        original=json.loads(evidence.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return {}
    return {
        'title':str(original.get('source_title') or '')[:250],
        'url':str(original.get('source_url') or '')[:400],
        'claims':original.get('claims',[])[:14],
        'note':'As alegações da fonte não estão automaticamente verificadas. Não invente dados ou eventos.',
    }


def _timing_improvement(before: list[str], after: list[str], issue) -> tuple[bool,int,int]:
    """Accept a rewrite only when word count moves toward real measured speech target."""
    previous=sum(_word_count(x) for x in before)
    proposed=sum(_word_count(x) for x in after)
    target=float(issue.target)
    actual=float(issue.actual)
    if previous == proposed or actual <= 0:
        return False,previous,proposed
    # A meaningful fraction of the needed correction, not an arbitrary 15s grace.
    needed=max(1,math.ceil(abs(previous * (target/actual-1))))
    minimum=max(1,math.ceil(needed*.20))
    progress=previous-proposed if actual>target else proposed-previous
    return progress>=minimum,previous,proposed


def _remove_function_words(words: list[str], remove_count: int) -> list[str]:
    """Remove function words (articles, prepositions, etc.) from a list."""
    function_words={
        'articles': {'o','a','os','as','um','uma','uns','umas'},
        'prepositions': {'de','do','da','dos','das','em','no','na','nos','nas','por','para','com','sem','sobre','trás','até','perante','conforme','segundo','mediante','frente','diante'},
        'conjunctions': {'e','ou','mas','porque','pois','que','se','nem','tão','como','já','ora','ainda','sem','senão','só','seja'},
        'relative_pronouns': {'que','quem','cujo','cujos','cuja','cujas'},
    }
    removed=0
    result=[]
    for word in words:
        lower=word.lower().rstrip(',.;:!?\n')
        if removed < remove_count and any(lower in group for group in function_words.values()):
            removed+=1
            continue
        result.append(word)
    return result


def merge_small_scenes(scenes: list, max_duration: float = 5.0) -> list:
    """Merge small consecutive scenes to reduce total duration."""
    if not scenes:
        return []
    merged=[]
    current=None
    for scene in scenes:
        duration=scene.end-scene.start
        if current is None:
            current={'scene':scene,'durations':[duration],'texts':[scene.narration]}
        elif duration < max_duration and current['durations'][-1] < max_duration:
            current['scene'].end=scene.end
            current['durations'].append(duration)
            current['texts'].append(scene.narration)
        else:
            merged.append(current)
            current={'scene':scene,'durations':[duration],'texts':[scene.narration]}
    if current:
        merged.append(current)
    return merged


def adjust_timing(video,script:Script,issue,attempt:int,correction:int):
    """Measured, evidence-grounded TTS rewrite (not a video review attempt).

    If the Redator ignores a word-budget request, retry with stricter targets,
    then try the Escritor route, rather than immediately failing every video.
    Do not pad with silence or duplicate sentences to fake narration duration.
    """
    from backend.media import PreflightError
    target=float(issue.target)
    # A TimingBudgetError means the real audio is outside the allowed window.
    # Never silently ignore 40.1-55s TTS because of a 15s editing tolerance.
    short=issue.actual<target-2
    scene_targets=_timing_targets(script,float(issue.actual),target)
    original=[scene.narration for scene in script.scenes]
    current_words=sum(map(_word_count,original))
    target_words=sum(scene_targets)
    delta_words=target_words-current_words
    measured_wps=current_words/max(float(issue.actual),.01)
    delta_seconds=target-float(issue.actual)
    source_context=_source_context(video['id'])
    schema={'type':'object','properties':{'narrations':{'type':'array','items':{'type':'string'}}},
            'required':['narrations']}
    details=[]
    max_scene_chars=590  # Pydantic Scene.narration <= 600 chars
    for idx,agent in enumerate(('redator','redator','escritor')):
        stronger=idx>0
        task=('Amplie o roteiro com contexto útil e ancorado na fonte, explicando o assunto para um público gamer.'
              if short else 'Reduza o roteiro eliminando repetições e palavras dispensáveis, preservando fatos.')
        prompt={
            'role':'tts_timing_rewrite',
            'today_sao_paulo':db.today(),
            'task':task,
            'script':script.model_dump(),
            'source_evidence':source_context,
            'measured_tts_seconds':round(float(issue.actual),3),
            'speech_target_seconds':target,
            'allowed_speech_window_seconds':[round(target-2,2),target],
            'current_total_words':current_words,
            'measured_words_per_second':round(measured_wps,4),
            'delta_seconds':round(delta_seconds,3),
            'delta_words_exact_target':delta_words,
            'target_total_words':target_words,
            'words_per_scene_current':[ _word_count(x) for x in original ],
            'words_per_scene_target':scene_targets,
            'constraints':(
                'Retorne EXATAMENTE um texto em narrations por cena, em mesma ordem, '
                'com narrativas COMPLETAS, em PT-BR e frases naturais. '
                'A contagem de palavras por cena é uma META concreta. '
                'Use delta_words_exact_target para saber EXATAMENTE quantas palavras adicionar/remover '
                'e delta_seconds para saber quantos segundos faltam; não responda com o mesmo tamanho. '
                'Quando estiver curto, adicione contexto realmente sustentado pelos trechos da fonte, '
                'explicação original, consequência potencial formulada como hipótese e pergunta relevante. '
                'Não repita bordões, texto ou a mesma ideia, não fabrique novas notícias. '
                'Quando não houver fatos suficientes, explicite incertezas naturalmente ("segundo a fonte"). '
                'Não insira selos "fato/rumor/fake". '
                f'Cada narração precisa ter até {max_scene_chars} caracteres. '
                'Preserve o tema, speaker, ordem e quantidade de cenas. '
                'Não inclua timestamps, marcadores nem o texto da tela.'
            ),
            'retry_reason': ('A resposta anterior não aumentou/diminuiu suficientemente o número de palavras. '
                             'Escreva textos materialmente diferentes e cumpra a meta por cena.' if stronger else ''),
        }
        try:
            result=llm(agent,video['id'],prompt,schema)
        except IntegrationError as exc:
            details.append(f'{agent}: {str(exc)[:160]}')
            continue
        candidates=result.get('narrations') if isinstance(result,dict) else None
        if not isinstance(candidates,list) or len(candidates)!=len(original):
            details.append(f'{agent}: quantidade de narrações divergente')
            continue
        revised=[narration_ready(str(text)) for text in candidates]
        if any(len(text)>max_scene_chars for text in revised):
            details.append(f'{agent}: cena maior que {max_scene_chars} caracteres')
            continue
        if any(not text for text in revised):
            details.append(f'{agent}: cena vazia')
            continue
        if revised==original:
            details.append(f'{agent}: devolveu a narração original sem alterações')
            continue
        improved,old_words,new_words=_timing_improvement(original,revised,issue)
        if not improved:
            details.append(f'{agent}: contagem de palavras {old_words}→{new_words}, progresso insuficiente')
            continue
        data=script.model_dump()
        changes=[]
        for i,(before,text) in enumerate(zip(original,revised)):
            if text!=before:
                changes.append({'scene':i+1,'before':before,'after':text,
                                'word_count_before':_word_count(before),'word_count_after':_word_count(text),
                                'reason':'Calibragem com base na duração de áudio real'})
                data['scenes'][i]['narration']=text
        try:
            updated=Script.model_validate(data)
        except (ValueError,TypeError) as exc:
            details.append(f'{agent}: validação de roteiro: {str(exc)[:180]}')
            continue
        folder=db.ROOT/'handoff'/video['id'];folder.mkdir(exist_ok=True,parents=True)
        db.atomic(folder/f'narration-timing-adjust-{attempt}-{correction}.json',json.dumps({
            'measured_s':issue.actual,'target_s':target,'words_per_scene_target':scene_targets,
            'measured_words_per_second':round(measured_wps,4),
            'delta_seconds':round(delta_seconds,3),'delta_words_exact_target':delta_words,
            'word_count_before':old_words,'word_count_after':new_words,
            'model_role_used':agent,'changes':changes,'failed_rewrites':details,
        },indent=2,ensure_ascii=False))
        db.atomic(folder/'script.json',updated.model_dump_json(indent=2))
        db.log_event(video['id'],'redator','TTS_TIMING_CORRECTION',
                     f'Ajuste {correction}/2; {len(changes)} cenas; palavras {old_words}→{new_words}; '
                     f'TTS anterior={issue.actual:.2f}s; rota={agent}')
        return updated

    # Safe fallback never removes facts, changes scenes or fakes audio duration.
    try:
        reduced=auto_reduce_narration(script, float(issue.actual), target)
        if reduced!=script:
            folder=db.ROOT/'handoff'/video['id'];folder.mkdir(parents=True,exist_ok=True)
            db.atomic(folder/'script.json',reduced.model_dump_json(indent=2))
            db.log_event(video['id'],'redator','AUTO_REDUCE_FALLBACK',
                         f'Remoção apenas de frases duplicadas; TTS anterior={issue.actual:.2f}s')
            return reduced
    except (ValueError, TypeError) as exc:
        details.append('fallback de duplicatas: '+str(exc)[:120])
    raise PreflightError(
        f'Áudio real {issue.actual:.2f}s fora de {target-2:.2f}s–{target:.2f}s; '
        f'palavras atuais={current_words}, alvo={target_words}; '
        'o Redator/Escritor não conseguiu alterar a duração com o combo OmniRoute. '
        'Nova tentativa agendada pelo worker. Detalhes: '+'; '.join(details[-3:])[:420])
