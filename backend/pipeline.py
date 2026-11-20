import hashlib
import json
import re
import shutil
import time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from pydantic import BaseModel, Field
from sqlalchemy import text
from backend import core as db, media, highlights, production_media, storyboard
from backend.contracts import ImportRequest, Script, platform_url
from backend.integrations import IntegrationError, metadata, viral_score, llm


AGENTS = ['diretor', 'cacador', 'escritor', 'redator', 'editor', 'avaliador']


def director_choose_template(title: str, text: str = '', current_template: str = 'gta-news') -> str:
    """Intelligent template selection by the Director based on radar content."""
    content = f"{title} {text}".lower()
    
    # 1. Comparison
    comparison_keywords = ['comparação', 'comparado', 'versus', ' vs ', ' vs.', 'diferença', 'gta 5', 'gta v', 'rdr2', 'red dead', 'vida real', 'miami real']
    if any(k in content for k in comparison_keywords):
        return 'gta-comparison'
    
    # 2. Theory, leaks, investigative journalism
    theory_keywords = ['vazamento', 'vazou', 'leak', 'rumor', 'suposto', 'teoria', 'especulaç', 'código', 'investiga', 'apuração', 'bastidor', 'documento secreto', 'insider']
    if any(k in content for k in theory_keywords):
        return 'gta-theory'
    
    # 3. Facts / Curiosities / Secrets / Easter Eggs
    facts_keywords = ['fatos', 'curiosidades', 'detalhes', 'segredo', 'easter egg', 'escondido', 'coisas que você não sabia', 'top ', 'motivos', 'mecânicas', 'física', 'descoberta']
    if any(k in content for k in facts_keywords):
        return 'gta-facts'
        
    # 4. Cinematic / Visual showcase
    cinematic_keywords = ['gráfico', 'visual', 'cinemat', 'ray tracing', 'iluminação', 'showcase', 'motor gráfico', 'rage engine', 'textura']
    if any(k in content for k in cinematic_keywords):
        return 'gta-cinematic'
        
    # 5. Reaction / Community debate / Hype
    reaction_keywords = ['reação', 'reagindo', 'opinião', 'polêmica', 'comunidade', 'fãs', 'hype', 'vale a pena', 'decepcionou', 'adiamento', 'debate', 'revolta']
    if any(k in content for k in reaction_keywords):
        return 'gta-reaction'
        
    # 6. Official News
    news_keywords = ['anúncio', 'oficial', 'rockstar games', 'take-two', 'take two', 'data de lançamento', 'lançamento', 'confirmado', 'trailer', 'preço', 'ps5', 'xbox', 'urgente']
    if any(k in content for k in news_keywords):
        return 'gta-news'
        
    return current_template or 'gta-news'


def download_authorized(video):
    """Compatibility wrapper: authorized source goes to /temp, never /videos/raw."""
    return production_media.acquire_source_video(video)


class Review(BaseModel):
    scores: dict[str, float]
    factual_supported: bool
    original: bool
    corrections: list[str] = Field(max_length=30)
    summary: str = Field(max_length=8000)


def create_video(req: ImportRequest | None = None, test=False, reference=None, variant_key=None, manual_script=None):
    config = db.settings()
    if config.emergency_stop:
        raise ValueError('Parada de emergência ativa.')
    id = db.uid()
    params = dict(id=id, run=db.uid(), url=req.url if req else 'test:' + id,
        platform=platform_url(req.url)[0] if req else 'synthetic', title='Aguardando pesquisa' if req else 'Teste técnico · GTA Studio',
        rights=req.rights.value if req else 'AUTHORIZED', evidence=req.evidence if req else 'Mídia sintética criada pelo próprio sistema para homologação.',
        credits=req.credits if req else '', instructions=req.instructions if req else '', template=req.template if req else 'gta-news',
        duration=req.duration if req else 10, test=int(test), now=time.time())
    if reference:
        chosen_template = director_choose_template(reference.get('title', ''), reference.get('description', ''))
        params.update(url=reference['url'],platform='news',title=reference['title'],rights='REFERENCE_ONLY',evidence='',
                      duration=config.duration,template=chosen_template,test=0)
    if variant_key:
        params['url'] += '#studio-variant=' + variant_key
    media.template(params['template'])
    with db.transaction() as c:
        existing = c.execute(text('SELECT id FROM videos WHERE url=:url'), params).scalar()
        if existing:
            return existing
        # One slot per active or approved real production, never one slot per
        # retry, failed/rejected job or test. São Paulo civil-day boundaries.
        if not test and db.production_usage(c) >= config.daily_limit:
            raise ValueError('Limite diário de produção atingido (produções ativas + aprovadas hoje).')
        c.execute(text('''INSERT INTO videos(id,run_id,url,platform,title,rights,evidence,credits,instructions,template,duration,status,stage,test,created,updated)
            VALUES (:id,:run,:url,:platform,:title,:rights,:evidence,:credits,:instructions,:template,:duration,'QUEUED','diretor',:test,:now,:now)'''), params)
        if manual_script:
            for scene in manual_script.scenes:scene.source_id=id
            db.atomic(db.ROOT/'handoff'/id/'manual-script.json',manual_script.model_dump_json(indent=2))
        c.execute(text("INSERT INTO jobs(id,video_id,kind,status,due,unique_key) VALUES (:job,:id,'pipeline','QUEUED',:now,:key)"),
                  dict(job=db.uid(), id=id, now=time.time(), key='pipeline:' + id))
        if reference:
            c.execute(text('UPDATE videos SET metadata=:meta WHERE id=:id'),dict(id=id,meta=json.dumps(reference,ensure_ascii=False)))
    return id


class PipelineInterrupted(Exception):
    """Manual decision superseded the running pipeline."""


def decision(video_id):
    found=db.rows('SELECT manual_decision FROM videos WHERE id=:id', {'id':video_id})
    return found[0]['manual_decision'] if found else 'discard'


def stage(video_id, agent):
    if db.settings().emergency_stop:
        raise IntegrationError('Parada de emergência ativa.')
    changed=db.execute("UPDATE videos SET stage=:agent,status='PROCESSING',updated=:now,error=NULL "
               "WHERE id=:id AND (manual_decision IS NULL OR manual_decision='approve_pending')",
               dict(id=video_id, agent=agent, now=time.time()))
    if not changed:
        raise PipelineInterrupted('Produção interrompida por decisão manual.')
    db.log_event(video_id, agent, 'START', 'Etapa iniciada.')


def hunt(video):
    if video['rights'] in ('BLOCKED', 'REVIEW_REQUIRED'):
        raise IntegrationError('Direitos bloqueados ou pendentes de verificação.')
    if video['test']:
        meta = {'title': 'Teste técnico · GTA Studio', 'description': 'Esta é uma demonstração técnica. Não contém notícias ou gameplay de GTA 6.',
                'metrics': {}, 'synthetic': True, 'url': video['url']}
    elif video['platform']=='news':
        meta=json.loads(video['metadata'])
    else:
        meta = metadata(video['url'], video['platform'])
        if video['rights'] == 'AUTHORIZED':
            path=download_authorized(video)
            if path is not None:
                source_seconds=float(media.probe(path)['format']['duration'])
                meta['duration']=source_seconds
            else:
                source_seconds=0
                meta['media_download']='FAILED_BACKGROUND_FALLBACK'
            if source_seconds > highlights.MAX_CLIP_SECONDS:
                new_duration=min(video['duration'],highlights.MAX_CLIP_SECONDS)
                context=highlights.analyze(path,source_seconds,new_duration,video_id=video['id'])
                video['duration']=new_duration
                meta['highlight_mode']='automatic_authorized_clips'
                meta['highlight_analysis_file']='handoff/'+video['id']+'/highlights.json'
                db.execute('UPDATE videos SET duration=:duration WHERE id=:id',
                           {'duration':new_duration,'id':video['id']})
    db.execute('UPDATE videos SET metadata=:meta,title=:title WHERE id=:id', dict(meta=json.dumps(meta), title=meta['title'], id=video['id']))
    db.artifact(video['id'], 'cacador', data={**meta, 'rights': video['rights'], 'evidence': video['evidence'],
        'credits': video['credits'], 'viral_score': viral_score(meta), 'today_sao_paulo':db.today(), 'score_method': 'views/hour + engagement + recency; no source baseline available'}, next_agent='escritor')


def write_script(video, corrections=None):
    source = db.read_artifact(video['id'], 'cacador').dados
    override=db.ROOT/'handoff'/video['id']/'manual-script.json'
    if override.exists() and not corrections:
        script=Script.model_validate_json(override.read_text('utf-8'))
    elif video['test']:
        script = Script(title='GTA Studio — teste técnico', hook='Seu estúdio está funcionando', description='Vídeo sintético de homologação, sem notícias de GTA 6.',
            hashtags=['teste'], template=video['template'], duration=10, scenes=[
                {'start': 0, 'end': 5, 'text': 'GTA STUDIO · TESTE', 'narration': 'Teste técnico de vídeo vertical. Material sintético autorizado.', 'source_id': video['id']},
                {'start': 5, 'end': 10, 'text': 'PIPELINE EM OPERAÇÃO', 'narration': 'Handoffs, renderização e avaliação. Nenhuma notícia é apresentada.', 'source_id': video['id']}])
    else:
        from backend.personas import get_persona
        from backend.facts import extract
        fact_ledger=extract(video,source)
        db.atomic(db.ROOT/'handoff'/video['id']/'facts.json',
                  json.dumps(fact_ledger,ensure_ascii=False,indent=2))
        persona=get_persona()
        clip_file=db.ROOT/'handoff'/video['id']/'highlights.json'
        clip_analysis=json.loads(clip_file.read_text('utf-8')) if clip_file.exists() else None
        vision_frames = ([db.safe_file(f['path']) for f in clip_analysis.get('frames',[])[:3]]
                         if clip_analysis and db.settings().routes['escritor'].vision else None)
        requested_duration=media.template(video['template']).get('duration') or video['duration']
        if requested_duration!=video['duration']:
            requested_duration=int(requested_duration)
            db.execute('UPDATE videos SET duration=:duration WHERE id=:id',
                       {'duration':requested_duration,'id':video['id']})
            video['duration']=requested_duration
        from backend.personas import get_cast
        from backend.narration_budget import script_budget
        cast=get_cast()
        narration_plan=script_budget(requested_duration,db.settings().narration_margin_seconds,cast)
        local_source_seconds=storyboard.local_source_seconds(db.ROOT,video['id'],video['rights'])
        failures=[]
        script=None
        for repair in range(3):
            try:
                result=llm('escritor',video['id'],{'source':source,'facts':fact_ledger,'id':video['id'],
                    'persona':persona,'cast':__import__('backend.personas',fromlist=['get_cast']).get_cast(),
                    'available_speakers':[k for k,v in __import__('backend.personas',fromlist=['get_cast']).get_cast().items() if v.get('production_ready')],
                    'two_hosts_requested':(int(hashlib.sha256(video['id'].encode()).hexdigest()[:8],16)%3==0 and
                     sum(bool(v.get('production_ready')) for v in __import__('backend.personas',fromlist=['get_cast']).get_cast().values())>=2),
                    'today_sao_paulo':db.today(),'highlight_analysis':clip_analysis,
                    'narration_word_budget':narration_plan,
                    'source_video_available':local_source_seconds is not None,
                    'source_duration_seconds':local_source_seconds,
                    'source_start_unit':'seconds, not milliseconds or frames',
                    'source_start_max_seconds':min(600,local_source_seconds) if local_source_seconds is not None else 0,
                    'allowed_script_music':'none',
                    'instructions':video['instructions'],'duration':requested_duration,
                    'template':video['template'],
                    'editorial_guideline':media.template(video['template']).get('editorial_guideline',''),
                    'template_badge':media.template(video['template']).get('badge',''),
                    'corrections':(corrections or [])+failures,
                    'repair_attempt':repair,
                    'constraints':'A pessoa narradora é ficcional, não copie personagens conhecidos. '
                    'Evidências e atribuição verificadas internamente, nunca selos de fato/rumor na tela. Notícias em comentário original. '
                    'Cada cena precisa ter narração e texto, com tempo coerente e sem contradições. '
                    'Conteúdo de terceiros é apenas referência salvo licença documentada. '
                    'Gancho nos primeiros dois segundos; frases de até 14 palavras, 2 a 4 ideias, análise ágil e pergunta final. '
                    'Cada cena precisa marcar speaker dentre available_speakers SOMENTE (não selecione personagens sem arte aprovada). '
                    'Marque emotion nas cenas dentre as 24 poses conhecidas. '
                    'Narração: cumpra narration_word_budget.total_words_target usando a calibração da voz Piper '
                    'e reserve 5 segundos (ou a margem configurada) para o encerramento; nunca corte frases no meio. '
                    'music deve ser exatamente "none": a trilha licenciada é selecionada em etapa separada. '
                    'source_start é sempre SEGUNDOS dentro do vídeo-fonte local, nunca frames ou ms; '
                    'exija 0 <= source_start <= min(600, source_duration_seconds - duração da cena). '
                    'Sem mídia-fonte local, source_start deve ser 0. '+
                    __import__('backend.editorial_style',fromlist=['WRITER_STYLE']).WRITER_STYLE},
                    Script.model_json_schema(),images=vision_frames)
                normalized,fixes=storyboard.normalize(result,requested_duration,video['template'],video['id'],source_seconds=local_source_seconds)
                script=Script.model_validate(normalized)
                if fixes:
                    db.atomic(db.ROOT/'handoff'/video['id']/f'briefing-fixes-{repair+1}.json',
                              json.dumps(fixes,ensure_ascii=False,indent=2))
                    db.log_event(video['id'],'escritor','BRIEFING_REPAIRED',
                                 ', '.join(f['field'] for f in fixes)[:500])
                break
            except (ValueError,TypeError) as exc:
                failures.append(f'Correção {repair+1}/3: campo duração/template/cenas inválido: {exc}')
                if repair==2:
                    raise media.BriefingError('; '.join(failures)) from None
        if script is None:raise media.BriefingError('Roteiro não pôde ser normalizado.')

        if clip_analysis:
            edl=highlights.fit_cuts(script,clip_analysis)
            db.atomic(db.ROOT/'handoff'/video['id']/'highlight-edl.json',
                      json.dumps(edl,ensure_ascii=False,indent=2))
    content = ' '.join(s.narration.lower() for s in script.scenes)
    fingerprint = hashlib.sha256(content.encode()).hexdigest()
    duplicates = db.rows('SELECT id FROM videos WHERE script_hash=:hash AND id!=:id', dict(hash=fingerprint, id=video['id']))
    if duplicates and not video['test']:
        raise IntegrationError('Roteiro duplicado detectado.')
    # Near duplicate check uses normalized word shingles, no model calls.
    words = content.split()
    shingles = set(' '.join(words[i:i+3]) for i in range(max(0, len(words)-2)))
    for previous in db.rows('SELECT id FROM videos WHERE approved=1 AND id!=:id AND test=0', {'id': video['id']}):
        path = db.ROOT / 'handoff' / previous['id'] / 'script.json'
        if path.exists() and not video['test']:
            old = Script.model_validate_json(path.read_text('utf-8'))
            w = ' '.join(s.narration.lower() for s in old.scenes).split()
            other = set(' '.join(w[i:i+3]) for i in range(max(0, len(w)-2)))
            if shingles and len(shingles & other) / max(1, len(shingles | other)) > .75:
                raise IntegrationError('Roteiro semelhante demais a conteúdo anterior.')
    folder = db.ROOT / 'handoff' / video['id']
    db.atomic(folder / 'script.json', script.model_dump_json(indent=2))
    briefing = [f'# {script.title}', f'Identificação: {video["id"]}', 'Objetivo: comentário original PT-BR baseado nas fontes registradas.',
                f'Duração: {script.duration}s', f'Gancho: {script.hook}', f'Template: {script.template}',
                'Narração: Piper PT-BR (sinal de teste na homologação).', 'Música: biblioteca autorizada com ducking obrigatório.', 'Legendas: alinhamento pelo áudio real.',
                'Enquadramento: centro, corte vertical 1080×1920. Transições: fade de texto 150ms.',
                f'Materiais: {video["rights"]}; fonte {video["url"]}; créditos {video["credits"]}', '## Alterações e roteiro']
    for i, s in enumerate(script.scenes, 1):
        briefing += [f'{i}. {s.start}–{s.end}s | texto + narração | {s.text} | conduzir a narrativa', s.narration]
    briefing += [f'CTA: {script.cta}', f'Descrição: {script.description}', 'Hashtags: ' + ' '.join(script.hashtags)]
    db.atomic(folder / f'escritor_{video["id"]}.md', '\n'.join(briefing))
    db.execute('UPDATE videos SET script_hash=:hash,title=:title WHERE id=:id', dict(hash=fingerprint, title=script.title, id=video['id']))
    db.artifact(video['id'], 'escritor', files=[str((folder / 'script.json').relative_to(db.ROOT)), str((folder / f'escritor_{video["id"]}.md').relative_to(db.ROOT))], next_agent='redator')
    return script


def evaluate(video, script, final):
    from backend.evaluation import evaluate as evaluate_pair
    return evaluate_pair(video,script,final)


def store_attempt(video_id, attempt, result, final=None, error=None):
    path=str(final.relative_to(db.ROOT)) if final else None
    stamp=time.time()
    db.execute('''INSERT INTO video_attempts(video_id,attempt,verdict,score,details,render_path,render_error,created)
        VALUES (:id,:attempt,:verdict,:score,:details,:path,:error,:now)
        ON CONFLICT(video_id,attempt) DO UPDATE SET verdict=excluded.verdict,score=excluded.score,
          details=excluded.details,render_path=excluded.render_path,render_error=excluded.render_error,
          created=excluded.created''',dict(id=video_id,attempt=attempt,verdict=result['verdict'],
           score=result.get('score'),details=json.dumps(result,ensure_ascii=False),path=path,error=error,now=stamp))
    db.atomic(db.ROOT/'handoff'/video_id/f'review-{attempt}.json',json.dumps(result,ensure_ascii=False,indent=2))
    folder=db.ROOT/'handoff'/video_id
    for name in ('script.json','escritor.json','redator.json','editor.json','avaliador.json'):
        source=folder/name
        if source.is_file():
            shutil.copy2(source,folder/f'{source.stem}-attempt-{attempt}{source.suffix}')


def approve_rendered(video_id, manual=False, by='local_operator'):
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0]
    if video['manual_decision']=='discard':
        raise PipelineInterrupted('Produção descartada.')
    if video['rights'] in ('BLOCKED','REVIEW_REQUIRED') or (video['rights']=='AUTHORIZED' and not video['evidence']):
        raise IntegrationError('Aprovação bloqueada: direitos de uso não verificados.')
    from backend.rights_gate import require_clearance
    require_clearance(video)
    if not video['final_path'] or not (db.ROOT/video['final_path']).is_file():
        raise IntegrationError('Não existe render para aprovar.')
    if manual:
        check=media.technical_check(db.safe_file(video['final_path']),video['duration'])
        if not check['valid']:
            raise IntegrationError('Render tecnicamente inválido; reprovação manual não contorna integridade de mídia: '
                                   + '; '.join(check['failures']))
    now=time.time()
    changed=db.execute("UPDATE videos SET approved=1,approved_at=:now,status='APPROVED',stage='diretor',error=NULL,updated=:now,"
               "manual_decision=:decision,manual_by=:by,manual_at=:manual_at WHERE id=:id "
               "AND (manual_decision IS NULL OR manual_decision='approve_pending')",
               dict(id=video_id,now=now,decision='approved' if manual else None,by=by if manual else None,
                    manual_at=now if manual else None))
    if not changed:
        raise PipelineInterrupted('A produção já recebeu decisão manual.')
    db.log_event(video_id,'diretor','MANUAL_APPROVED' if manual else 'DONE',
                 'Aprovação manual registrada.' if manual else 'Aprovado pelo Avaliador.')
    distribute(video_id)
    production_media.remove_workspace(video_id)



def preserve_unaffected_scenes(video_id, new_script, previous_details, previous_attempt):
    """Keep approved, unaffected scenes byte-for-byte when failures are localized.

    We only do partial regeneration if every blocking issue has a time/scene
    reference. If an issue is structural or has no location, full-script repair
    remains available; silently guessing a scene would be unsafe.
    """
    if not previous_attempt or not previous_details:
        return new_script
    old_path=db.ROOT/'handoff'/video_id/f'script-attempt-{previous_attempt}.json'
    if not old_path.is_file():
        return new_script
    previous=Script.model_validate_json(old_path.read_text('utf-8'))
    if len(previous.scenes)!=len(new_script.scenes):
        return new_script
    issues=previous_details.get('issues') or []
    if not issues:
        return new_script
    targets=set()
    for item in issues:
        ev=str(item.get('evidence') or '')
        matched=False
        for number in re.findall(r'(?i)cena\s*(\d+)',ev):
            idx=int(number)-1
            if 0<=idx<len(previous.scenes):
                targets.add(idx);matched=True
        for second in re.findall(r'(?<![\w.])(\d+(?:[.,]\d+)?)\s*s\b',ev):
            position=float(second.replace(',','.'))
            for idx,scene in enumerate(previous.scenes):
                if scene.start<=position<scene.end:
                    targets.add(idx);matched=True
        if not matched:
            # Without concrete evidence, do not edit arbitrary scenes.
            return new_script
    if not targets or len(targets)>=len(previous.scenes):
        return new_script
    result=new_script.model_dump()
    old=previous.model_dump()
    for idx in range(len(result['scenes'])):
        if idx not in targets:
            result['scenes'][idx]=old['scenes'][idx]
        else:
            # Keep scene boundaries fixed; partial TTS changes must not move
            # other scenes or invalidate previously approved cut timestamps.
            result['scenes'][idx]['start']=old['scenes'][idx]['start']
            result['scenes'][idx]['end']=old['scenes'][idx]['end']
    result['duration']=old['duration'];result['template']=old['template']
    revised=Script.model_validate(result)
    folder=db.ROOT/'handoff'/video_id
    db.atomic(folder/'script.json',revised.model_dump_json(indent=2))
    db.atomic(folder/f'surgical-attempt-{previous_attempt+1}.json',json.dumps({
        'from_attempt':previous_attempt,'edited_scenes':[n+1 for n in sorted(targets)],
        'preserved_scenes':[n+1 for n in range(len(previous.scenes)) if n not in targets],
        'reason':'Somente cenas com evidência temporal foram reescritas.'},ensure_ascii=False,indent=2))
    db.log_event(video_id,'redator','SURGICAL_REVISION',
                 'Refação apenas nas cenas '+', '.join(str(n+1) for n in sorted(targets)))
    return revised


def run_pipeline(video_id):
    video = db.rows('SELECT * FROM videos WHERE id=:id', {'id': video_id})[0]
    if video['manual_decision'] in ('discard','approved'):
        return
    # A stale/reclaimed job must never restart an item parked for operator review.
    # Its decision is independent of the remaining production queue.
    if video['status'] in ('AWAITING_MANUAL_DECISION','PENDING_RIGHTS_REVIEW'):
        return
    if video['approved']:
        distribute(video_id)
        return
    stage(video_id, 'diretor')
    config=db.settings()
    video_meta = {}
    if video.get('metadata'):
        try: video_meta = json.loads(video['metadata'])
        except Exception: pass
    if not video.get('test'):
        decided_template = director_choose_template(
            (video.get('title') or '') + ' ' + (video_meta.get('title') or ''),
            (video_meta.get('description') or '') + ' ' + (video.get('instructions') or ''),
            video.get('template') or 'gta-news'
        )
        if decided_template != video.get('template'):
            db.execute('UPDATE videos SET template=:tpl WHERE id=:id', {'tpl': decided_template, 'id': video_id})
            video['template'] = decided_template
    # Same-day scenario variety applies only to subsequent automated, real Shorts.
    if not video.get('test') and config.automatic:
        from backend.scenarios import SCENARIOS
        start,end=db.local_day_bounds()
        last=db.rows("""SELECT template FROM videos WHERE id!=:id AND test=0
            AND created>=:start AND created<:end AND status IN
            ('APPROVED','AWAITING_MANUAL_DECISION','PENDING_RIGHTS_REVIEW')
            ORDER BY created DESC LIMIT 1""",
            {'id':video_id,'start':start,'end':end})
        if last and video['template']==last[0]['template'] and video['template'] in SCENARIOS:
            options=list(SCENARIOS)
            selected=options[(options.index(video['template'])+1)%len(options)]
            db.execute('UPDATE videos SET template=:tpl WHERE id=:id',
                       {'tpl':selected,'id':video_id})
            video['template']=selected
            db.log_event(video_id,'diretor','TEMPLATE_VARIATION',
                         'Cenário consecutivo evitado: '+selected)
    template_info = media.template(video['template'])
    db.artifact(video_id,'diretor',data={
        'daily_limit':config.daily_limit,
        'max_review_attempts':config.max_review_attempts,
        'selected_template': video['template'],
        'template_name': template_info.get('name', 'GTA Studio'),
        'badge': template_info.get('badge', 'GTA 6'),
        'pacing': template_info.get('pacing', 'fast'),
        'editorial_guideline': template_info.get('editorial_guideline', '')
    },next_agent='cacador')
    stage(video_id,'cacador')
    if not (db.ROOT/'handoff'/video_id/'cacador.json').exists():
        hunt(video)
    previous=db.rows('SELECT attempt,details FROM video_attempts WHERE video_id=:id ORDER BY attempt DESC LIMIT 1',{'id':video_id})
    next_attempt=(previous[0]['attempt']+1) if previous else 1
    previous_details=json.loads(previous[0]['details']) if previous else {}
    corrections=previous_details.get('corrections',[]) if previous else None
    for attempt in range(next_attempt,config.max_review_attempts+1):
        if decision(video_id) in ('discard','approved'):
            return
        db.execute('UPDATE videos SET revision=:r WHERE id=:id',dict(r=attempt,id=video_id))
        final=None;render_error=None
        try:
            stage(video_id,'escritor')
            script=None
            checkpoint=db.ROOT/'handoff'/video_id/'script.json'
            # A technical retry is not a new creative revision: keep the
            # validated script rather than spending a fresh Escritor call.
            if video['status']=='RETRY' and not video.get('test') and checkpoint.is_file():
                try:
                    restored=Script.model_validate_json(checkpoint.read_text('utf-8'))
                    if restored.template==video['template'] and restored.duration==video['duration']:
                        script=restored
                        db.log_event(video_id,'escritor','CHECKPOINT_RESTORED',
                                     'Roteiro validado reaproveitado para nova tentativa técnica.')
                except (OSError,ValueError):
                    pass
            if script is None:
                script=write_script(video,corrections)
            stage(video_id,'redator')
            from backend.redator import polish
            script=polish(video,script,attempt)
            if attempt>1:
                script=preserve_unaffected_scenes(video_id,script,previous_details,attempt-1)
            stage(video_id,'editor')
            # TTS measurements are technical preflight, not evaluation rounds.
            from backend.audio_timeline import TimingBudgetError
            for correction_round in range(3):
                try:
                    final=media.render(video,script,attempt=attempt)
                    break
                except TimingBudgetError as timing_error:
                    if correction_round>=2:
                        raise media.PreflightError('Após dois ajustes do Redator, narração ainda fora do orçamento real: '+str(timing_error))
                    from backend.redator import adjust_timing
                    script=adjust_timing(video,script,timing_error,attempt,correction_round+1)
            # Persist each render before scoring so even rejected files can be previewed.
            db.execute("UPDATE videos SET final_path=:path,render_error=NULL,updated=:now WHERE id=:id AND "
                       "(manual_decision IS NULL OR manual_decision='approve_pending')",
                       {'path':str(final.relative_to(db.ROOT)),'now':time.time(),'id':video_id})
            # Decode and check the REAL output before any LLM review; technical
            # failures pause the production and do not count as review attempts.
            technical=media.technical_check(final,script.duration)
            if not technical['valid']:
                message='Pré-avaliação técnica: '+'; '.join(technical['failures'])
                db.execute("UPDATE videos SET status='PIPELINE_ERROR',stage='editor',error=:error,updated=:now WHERE id=:id",
                           {'error':message,'now':time.time(),'id':video_id})
                db.log_event(video_id,'editor','PREFLIGHT_ERROR',message)
                raise media.PreflightError(message)
            if decision(video_id)=='discard':
                return
            if decision(video_id)=='approve_pending':
                store_attempt(video_id,attempt,{'verdict':'APROVADO_MANUAL','reason_full':'Aprovado manualmente antes da avaliação.',
                                           'scores':{},'corrections':[]},final)
                approve_rendered(video_id,manual=True)
                return
            stage(video_id,'avaliador')
            result=evaluate(video,script,final)
            # Complete the technical and editorial pipeline BEFORE asking the
            # operator to confirm rights for a private source-footage preview.
            from backend.rights_gate import requires_review,pending_sources
            if requires_review(video):
                store_attempt(video_id,attempt,result,final)
                pending=pending_sources(video_id)
                explanation=('Prévia finalizada. '+str(len(pending))+
                             ' fonte(s) da TV aguardam autorização. '
                             'Confirme em Video Studio ou descarte a produção.')
                db.execute("""UPDATE videos SET status='PENDING_RIGHTS_REVIEW',
                    stage='diretor',approved=0,error=:reason,updated=:now WHERE id=:id""",
                    {'id':video_id,'reason':explanation,'now':time.time()})
                db.log_event(video_id,'diretor','PREVIEW_READY_RIGHTS_PENDING',explanation)
                db.notify('rights-review:'+video_id,explanation)
                return
        except PipelineInterrupted:
            return
        except __import__('backend.assets',fromlist=['MissingAssetsError']).MissingAssetsError as exc:
            # A missing resource is not a failed review attempt. Leave all attempts unchanged.
            db.execute("UPDATE videos SET status='PAUSED_MISSING_ASSETS',stage='editor',error=:error,updated=:now WHERE id=:id",
                       {'error':str(exc),'now':time.time(),'id':video_id})
            db.log_event(video_id,'editor','MISSING_ASSETS',str(exc))
            db.notify('missing-assets:'+video_id,str(exc))
            return
        except media.PreflightError as exc:
            db.execute("UPDATE videos SET status='RETRY',stage='editor',error=:error,updated=:now WHERE id=:id",
                       {'error':str(exc),'now':time.time(),'id':video_id})
            db.log_event(video_id,'editor','PREFLIGHT_RETRY',str(exc)[:500])
            raise
        except media.BriefingError as exc:
            # An actual creative inconsistency (not a broken decoder/FFmpeg/TTS)
            # returns to the Escritor under the configured review limit.
            render_error=str(exc)
            result={'verdict':'REVISAR','score':None,'scores':{},'criteria':{},
                    'reason_full':render_error,'summary':'Briefing precisa de revisão criativa.',
                    'corrections':[render_error],'hard_blocks':False}
            if final is None:
                db.execute('UPDATE videos SET render_error=:err WHERE id=:id',{'err':render_error,'id':video_id})
                db.artifact(video_id,'editor',data=result,status='REVISAR',
                    summary='Briefing divergente; devolver ao Escritor.',next_agent='escritor')
        except IntegrationError as exc:
            # Infrastructure/provider failures must propagate to the worker.
            # They are NOT creative review attempts; keep existing artifacts.
            render_error=str(exc)
            db.execute("UPDATE videos SET status='RETRY',stage=:stage,error=:err,render_error=:err,updated=:now WHERE id=:id",
                       {'err':render_error,'stage':'editor' if final is None else 'avaliador',
                        'now':time.time(),'id':video_id})
            db.log_event(video_id,'pipeline','INFRA_RETRY',render_error[:500])
            raise
        store_attempt(video_id,attempt,result,final,render_error)
        if decision(video_id) in ('discard','approved'):
            return
        if decision(video_id)=='approve_pending' and final:
            approve_rendered(video_id,manual=True)
            return
        if result['verdict']=='APROVADO':
            approve_rendered(video_id)
            daily_report()
            return
        corrections=result.get('corrections') or ['Reescrever roteiro e alterar as cenas.']
        previous_details=result
        db.log_event(video_id,'avaliador','REVIEW',f'Tentativa {attempt}/{config.max_review_attempts} reprovada; refazendo.')
    if decision(video_id) in ('discard','approved'):
        return
    latest=db.rows('SELECT details FROM video_attempts WHERE video_id=:id ORDER BY attempt DESC LIMIT 1',{'id':video_id})
    reason=json.loads(latest[0]['details']).get('reason_full','Sem avaliação disponível.') if latest else 'Sem avaliação disponível.'
    db.execute("UPDATE videos SET status='AWAITING_MANUAL_DECISION',stage='diretor',error=:error,updated=:now "
               "WHERE id=:id AND (manual_decision IS NULL OR manual_decision='approve_pending')",
               dict(id=video_id,error=reason,now=time.time()))
    db.notify('manual-decision:'+video_id,'Limite de avaliações atingido para '+video_id+'. Aprovar ou descartar no Video Studio.')
    daily_report()


def distribute(video_id):
    video = db.rows('SELECT * FROM videos WHERE id=:id', {'id': video_id})[0]
    if not video['approved'] or video['rights'] in ('BLOCKED', 'REVIEW_REQUIRED'):
        raise IntegrationError('Distribuição bloqueada pela avaliação ou direitos.')
    config = db.settings()
    if config.emergency_stop:
        raise IntegrationError('Distribuição pausada por emergência.')
    script = Script.model_validate_json((db.ROOT / 'handoff' / video_id / 'script.json').read_text('utf-8')).model_dump()
    credits=set()
    if video['credits']:credits.add(video['credits'])
    manifest=db.ROOT/'handoff'/video_id/'visual-assets.json'
    if manifest.is_file():
        for item in json.loads(manifest.read_text('utf-8')):
            if item.get('source_clip_url'):credits.add(str(item['source_clip_credit'])+' — '+str(item['source_clip_url']))
            elif item.get('overlay_source') and video['platform']=='news':
                credits.add('Fonte da notícia: '+str(item['overlay_source']))
    if credits:
        script['description']=(script['description']+'\n\nFontes e créditos:\n'+'\n'.join(sorted(credits)))[:5000]
    review = (db.read_artifact(video_id, 'avaliador').dados if (db.ROOT/'handoff'/video_id/'avaliador.json').exists() else {'verdict':'APROVADO_MANUAL','summary':'Decisão manual.'})
    final = db.safe_file(video['final_path'])
    for platform in config.platforms:
        if db.settings().emergency_stop:
            break
        if platform in config.paused_integrations:
            continue
        pubid = db.uid()
        db.execute("INSERT OR IGNORE INTO publications(id,video_id,platform,status,updated) VALUES (:id,:video,:platform,'PENDENTE',:now)",
                   dict(id=pubid, video=video_id, platform=platform, now=time.time()))
        pub = db.rows('SELECT * FROM publications WHERE video_id=:video AND platform=:platform', dict(video=video_id, platform=platform))[0]
        if pub['status'] != 'PENDENTE':
            continue
        folder = db.ROOT / 'output' / platform / db.today()
        folder.mkdir(parents=True, exist_ok=True)
        output = folder / f'video_{video_id}.mp4'
        shutil.copy2(final, output)
        from backend.seo import build_seo_package
        seo = build_seo_package(script, video, platform)
        db.atomic(folder / f'metadata_{video_id}.json', json.dumps({**script, 'seo': seo,
            'pinned_comment': seo['pinned_comment'], 'credits': video['credits'], 'source': video['url'],
            'test_only': bool(video['test']), 'review': review, 'publication_id': pub['id']}, ensure_ascii=False, indent=2))
        db.execute('UPDATE publications SET output_path=:path WHERE id=:id', dict(id=pub['id'], path=str(output.relative_to(db.ROOT))))
        # This build never sends content to a social network. The creator downloads,
        # reviews and publishes it personally; pending files are never auto-deleted.
        db.execute("UPDATE publications SET status='AGUARDANDO_PUBLICACAO_MANUAL',updated=:now WHERE id=:id",
                   {'id': pub['id'], 'now': time.time()})
        db.notify('manual:' + pub['id'],
                  f'{platform}: vídeo {video_id} pronto para revisão e publicação manual' +
                  (' (TESTE; não publicar).' if video['test'] else '.'))


def daily_report():
    counts = db.rows('SELECT status,count(*) AS n FROM videos GROUP BY status')
    pubs = db.rows('SELECT status,count(*) AS n FROM publications GROUP BY status')
    lines = [f'# Relatório {db.today()}', 'Contagens acumuladas do estúdio; métricas apenas observadas.',
        f'Oportunidades: {db.rows("SELECT count(*) AS n FROM opportunities")[0]["n"]}']
    lines += [f'Vídeos {x["status"]}: {x["n"]}' for x in counts]
    lines += [f'Publicações {x["status"]}: {x["n"]}' for x in pubs]
    latest={}
    for row in db.rows('''SELECT m.*,v.template FROM metrics m JOIN publications p ON p.id=m.publication_id
        JOIN videos v ON v.id=p.video_id ORDER BY m.observed DESC'''):
        latest.setdefault(row['publication_id'],row)
    groups={}
    for row in latest.values():
        views=json.loads(row['data']).get('views')
        if views is not None:groups.setdefault(row['template'],[]).append(views)
    eligible={k:sum(v)/len(v) for k,v in groups.items() if len(v)>=3}
    suggestion=max(eligible,key=eligible.get) if eligible else None
    db.put_setting('recommendations',{'template':suggestion,'observations':{k:len(v) for k,v in groups.items()},
        'caveat':'Comparação descritiva, sem atribuição causal; idade e alcance das publicações podem diferir.'})
    lines += ['Métricas: consulte Analytics; ausência de dados não equivale a zero.',
        ('Próximo experimento: '+suggestion) if suggestion else 'Próximo ciclo: coletar pelo menos três observações por template antes de priorizar formatos.',
        'Comparações descritivas não demonstram causalidade.','Prioridade: resolver direitos e autenticações pendentes.']
    db.atomic(db.ROOT / 'reports' / f'{db.today()}.md', '\n'.join(lines[:30]))
