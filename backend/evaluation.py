"""Independent technical and viewer review over an actually rendered file.

OpenAI-compatible chat endpoints in this integration accept sampled JPEG frames,
transcript and technical probe, not MP4 video. The input modality is explicit:
models must not claim direct access to video frames or audio they weren't given.
"""
from __future__ import annotations
import json
import hashlib
from concurrent.futures import ThreadPoolExecutor
from pydantic import BaseModel, Field
from backend import core as db, media
from backend.integrations import IntegrationError, llm

PERSON_KEYS = ('attention','understanding','fun','audiovisual','share','visual_match','energy')
PERSON_NAMES = {
 'attention':'Eu continuaria depois de três segundos?',
 'understanding':'Entendi o assunto?',
 'fun':'Achei interessante/divertido?',
 'audiovisual':'A voz e as imagens são agradáveis?',
 'share':'Eu comentaria ou compartilharia?',
 'visual_match':'O que apareceu na tela combina com o que foi narrado?',
 'energy':'O vídeo me pareceu dinâmico ou ficou morno? Indique o momento exato da queda de energia.',
}

class TechnicalReview(BaseModel):
    scores: dict[str,float]
    evidence: dict[str,str] = Field(default_factory=dict)
    factual_supported: bool
    original: bool
    corrections: list[str] = Field(default_factory=list)
    summary: str = ''

class ViewerReview(BaseModel):
    scores: dict[str,float]
    evidence: dict[str,str] = Field(default_factory=dict)
    summary: str = ''
    boring_second: float | None = None


def _hash(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,default=str).encode()).hexdigest()


def review_context(video, script, technical, manifest):
    """Independent dependency fingerprints for safe score reuse across versions.

    A score is rechecked whenever any input it depends on changed. Render
    integrity is always rechecked by ffprobe regardless of retained AI scores.
    """
    scenes=script.model_dump()['scenes']
    return {
        'script':_hash({'hook':script.hook,'title':script.title,'text':[x['text'] for x in scenes],
                        'facts':[x['source_id'] for x in scenes]}),
        'narration':_hash([{'speaker':x.get('speaker'),'text':x['narration']} for x in scenes]),
        'visual':_hash(manifest),
        'format':_hash({'duration':technical.get('duration'),'resolution':technical.get('resolution'),
                        'planned':script.duration}),
        'rights':_hash({'rights':video['rights'],'evidence':video.get('evidence'),
                        'assets':[(x.get('scene'), [(y.get('asset_id'),y.get('source_class'),y.get('credits'))
                                      for y in x.get('segments',[])]) for x in manifest]}),
    }


def locked_from_previous(previous, context):
    old=previous.get('review_context') or {}
    if not old:
        return {}, {}
    deps={
        'hook':('script','narration'), 'narrative':('script','narration'),
        'briefing':('script','narration'), 'originality':('script','visual'),
        'accuracy':('script',), 'audio':('narration',), 'subtitles':('narration',),
        'cuts':('visual',), 'rhythm':('narration','visual'),
        'visual_relevance':('visual','script'),
        'resolution':('format',), 'duration':('format',), 'rights':('rights',)
    }
    tech={k:v for k,v in (previous.get('criteria') or {}).items()
          if v.get('passed') and v.get('score') is not None
          and all(old.get(field)==context.get(field) for field in deps.get(k, ('script','visual','narration')))}
    # Viewer criteria are holistic: any new narrative, audio or footage can
    # change the experience, so all affected opinions must be rerun.
    viewer={k:v for k,v in (previous.get('viewer') or {}).items()
            if v.get('passed') and v.get('score') is not None
            and all(old.get(field)==context.get(field) for field in ('script','narration','visual'))}
    return tech,viewer


def review_models(video,script,render,technical,frames,audio_check,previous):
    config=db.settings()
    source=db.read_artifact(video['id'],'cacador').dados
    manifest_file=db.ROOT/'handoff'/video['id']/'visual-assets.json'
    manifest=json.loads(manifest_file.read_text('utf-8')) if manifest_file.exists() else []
    editor=db.read_artifact(video['id'],'editor').dados
    common={'date_sao_paulo':db.today(),'source':source,'script':script.model_dump(),
       'technical_probe':technical,'transcript_check':audio_check,'visual_manifest':manifest,
       'editor':editor,'render_relative_path':str(render.relative_to(db.ROOT)),
       'media_presented_to_model':{'mp4_attached':False,'audio_attached':False,
          'frames_attached':config.routes['avaliador'].vision,'transcript_available':bool(audio_check)},
       'rules':'Only score what can be verified from the supplied frames, transcript and source. '
         'No evidence = no negative criterion. Do not equate test_audio false with absent audio. '
         'Use the Sao Paulo current date. Do not call a dated source future without comparing correctly. '
         'Do not claim to have directly watched the full mp4. Every below-minimum score needs '
         'evidence with a time, frame or field. Não exija selo de fato/rumor. Exatidão não significa exibir etiqueta.'}
    criteria=config.evaluation_criteria
    context=review_context(video,script,technical,manifest)
    locked,locked_viewer=locked_from_previous(previous,context)
    tech_data={**common,'reviewer':'technical','evaluation_rubric':{
        k:c.model_dump() for k,c in criteria.items() if c.enabled and k not in locked},
        'locked_scores':{k:v.get('score') for k,v in locked.items()},
        'rules':common['rules']+' Return score for every requested rubric criterion.'}
    person_data={**common,'reviewer':'viewer','viewer_questions':{k:v for k,v in PERSON_NAMES.items() if k not in locked_viewer},
       'locked_scores':{k:v.get('score') for k,v in locked_viewer.items()},
       'media_presented_to_model':{**common['media_presented_to_model'],
                                   'frames_attached':config.routes['pessoa'].vision}}
    with ThreadPoolExecutor(max_workers=2) as ex:
        f1=ex.submit(llm,'avaliador',video['id'],tech_data,TechnicalReview.model_json_schema(),
                     frames[:6] if config.routes['avaliador'].vision else None)
        f2=ex.submit(llm,'pessoa',video['id'],person_data,ViewerReview.model_json_schema(),
                     frames[:6] if config.routes['pessoa'].vision else None)
        tech=TechnicalReview.model_validate(f1.result())
        person=ViewerReview.model_validate(f2.result())
    return tech,person,locked,locked_viewer,context


def evaluate(video,script,render):
    cfg=db.settings()
    probe=media.technical_check(render,script.duration)
    rights_ok=video['rights']=='REFERENCE_ONLY' or (video['rights']=='AUTHORIZED' and bool(video['evidence']))
    hard=list(probe['failures'])
    if not rights_ok:hard.append('Direitos de utilização não documentados.')
    previous_rows=db.rows('SELECT attempt,details FROM video_attempts WHERE video_id=:id ORDER BY attempt DESC LIMIT 1',{'id':video['id']})
    previous=json.loads(previous_rows[0]['details']) if previous_rows else {}
    if previous_rows:previous['attempt']=previous_rows[0]['attempt']
    tech_review=None;person_review=None;locked={};locked_viewer={};context={}
    if not hard and not video.get('test'):
        frames=media.samples(render,video['id'])
        audio_check=media.transcript_check(render,script)
        if not audio_check['valid']:
            # Input failure, not an AI judgment. The video stays available.
            raise media.PreflightError('Verificação determinística: áudio real diverge do roteiro; '+str(audio_check))
        tech_review,person_review,locked,locked_viewer,context=review_models(video,script,render,probe,frames,audio_check,previous)
    scores={k:10. for k,c in cfg.evaluation_criteria.items() if c.enabled} if video.get('test') else (tech_review.scores if tech_review else {})
    person_scores={k:10. for k in PERSON_KEYS} if video.get('test') else (person_review.scores if person_review else {})
    breakdown={}; problems=[]; optional=[];provided={}
    for key,c in cfg.evaluation_criteria.items():
        val=locked.get(key,{}).get('score',scores.get(key))
        ev=(tech_review.evidence or {}).get(key,'') if tech_review else ''
        if val is not None and not 0<=val<=10:
            raise IntegrationError('Avaliador devolveu nota fora de 0 a 10: '+key)
        passed=val is not None and val>=c.min_score
        if c.enabled and val is None:
            problems.append({'criterion':key,'problem':'Nota técnica ausente','evidence':'campo '+key,
                             'correction':'Reavaliar este critério'})
        elif c.enabled and not passed and ev.strip():
            problems.append({'criterion':key,'problem':f'{c.name}: {val:.1f} abaixo de {c.min_score}',
                             'evidence':ev,'correction':'Revisar somente trecho evidenciado'})
        elif c.enabled and not passed:
            optional.append(f'Critério {c.name}: nota {val} sem evidência objetiva; não reprovar automaticamente.')
            passed=True
        breakdown[key]={**c.model_dump(),'score':val,'passed':passed,'evidence':ev,
                        'locked':key in locked}
    viewer={}
    for key,title in PERSON_NAMES.items():
        val=locked_viewer.get(key,{}).get('score',person_scores.get(key))
        ev=(person_review.evidence or {}).get(key,'') if person_review else ''
        passed=val is not None and val>=cfg.spectator_min_score
        if val is None:
            problems.append({'criterion':'pessoa.'+key,'problem':title+': nota ausente',
                             'evidence':'pessoa.'+key,'correction':'Reavaliar pelo espectador'})
        elif not 0<=val<=10:raise IntegrationError('Pessoa devolveu nota fora de 0 a 10.')
        elif not passed and ev.strip():
            problems.append({'criterion':'pessoa.'+key,'problem':title+f': {val:.1f}',
                             'evidence':ev,'correction':'Ajustar o trecho referido pela Pessoa'})
        elif not passed:
            optional.append('Pessoa: '+title+' — sem evidência concreta, não reprovar automaticamente.')
            passed=True
        viewer[key]={'name':title,'score':val,'min_score':cfg.spectator_min_score,'passed':passed,'evidence':ev,'locked':key in locked_viewer}
    if tech_review and not tech_review.factual_supported:
        # Do not invent a failing fact if the source/model did not provide evidence.
        optional.append('Verificar afirmações sem suporte específico; encaminhar à revisão humana.')
    if tech_review and not tech_review.original:
        optional.append('Verificar originalidade; exigir evidência antes de bloquear.')
    problems=[{'criterion':'technical','problem':msg,'evidence':'ffprobe/ffmpeg ou campo de direitos',
               'correction':'Corrigir o arquivo/render ou a licença'} for msg in hard]+problems
    deviations=[k for k in viewer if breakdown.get(k) and viewer[k]['score'] is not None and
                breakdown[k]['score'] is not None and abs(viewer[k]['score']-breakdown[k]['score'])>=3]
    score=round(sum(x['score']*x['weight'] for x in breakdown.values() if x['enabled'] and x['score'] is not None)/
          max(.001,sum(x['weight'] for x in breakdown.values() if x['enabled'] and x['score'] is not None)),2)
    verdict='APROVADO' if not problems else ('REPROVADO' if hard else 'REVISAR')
    result={'verdict':verdict,'score':score,'criteria':breakdown,'scores':scores,'viewer':viewer,
      'viewer_summary':person_review.summary if person_review else '',
      'viewer_boring_second':person_review.boring_second if person_review else None,
      'disagreements':deviations,'issues':problems,'optional_suggestions':optional,
      'corrections':[f"{p['criterion']}: {p['correction']} ({p['evidence']})" for p in problems],
      'reason_full':'\n'.join(p['problem']+' | '+p['evidence'] for p in problems) or 'Critérios atendidos.',
      'summary':tech_review.summary if tech_review else ('Teste sintético.' if video.get('test') else 'Falha técnica'),
      'hard_blocks':bool(hard),'technical':probe,'date_sao_paulo':db.today(),
      'review_medium':'frames+transcript+ffprobe; MP4 não enviado diretamente ao modelo',
      'review_context':context}
    db.artifact(video['id'],'avaliador',data=result,
                status='CONCLUIDO' if verdict=='APROVADO' else verdict,
                next_agent='diretor' if verdict=='APROVADO' else 'escritor')
    return result
