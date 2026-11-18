import hashlib
import json
import shutil
import time
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy import text
from backend import core as db, media, highlights, production_media, storyboard
from backend.contracts import ImportRequest, Script, platform_url
from backend.integrations import IntegrationError, metadata, viral_score, llm


AGENTS = ['diretor', 'cacador', 'escritor', 'editor', 'avaliador']


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
        params.update(url=reference['url'],platform='news',title=reference['title'],rights='REFERENCE_ONLY',evidence='',
                      duration=config.duration,template='gta-news',test=0)
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
        'credits': video['credits'], 'viral_score': viral_score(meta), 'score_method': 'views/hour + engagement + recency; no source baseline available'}, next_agent='escritor')


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
        failures=[]
        script=None
        for repair in range(3):
            try:
                result=llm('escritor',video['id'],{'source':source,'id':video['id'],
                    'persona':persona,'highlight_analysis':clip_analysis,
                    'instructions':video['instructions'],'duration':requested_duration,
                    'template':video['template'],'corrections':(corrections or [])+failures,
                    'repair_attempt':repair,
                    'constraints':'A pessoa narradora é ficcional, não copie personagens conhecidos. '
                    'Fatos verificados separados de rumores. Notícias em comentário original, não copiar matérias. '
                    'Cada cena precisa ter narração e texto, com tempo coerente e sem contradições. '
                    'Conteúdo de terceiros é apenas referência salvo licença documentada.'},
                    Script.model_json_schema(),images=vision_frames)
                normalized,fixes=storyboard.normalize(result,requested_duration,video['template'],video['id'])
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
                'Narração: Piper PT-BR (sinal de teste na homologação).', 'Música: nenhuma.', 'Legendas: frases de seis palavras; fade 70ms.',
                'Enquadramento: centro, corte vertical 1080×1920. Transições: fade de texto 150ms.',
                f'Materiais: {video["rights"]}; fonte {video["url"]}; créditos {video["credits"]}', '## Alterações e roteiro']
    for i, s in enumerate(script.scenes, 1):
        briefing += [f'{i}. {s.start}–{s.end}s | texto + narração | {s.text} | conduzir a narrativa', s.narration]
    briefing += [f'CTA: {script.cta}', f'Descrição: {script.description}', 'Hashtags: ' + ' '.join(script.hashtags)]
    db.atomic(folder / f'escritor_{video["id"]}.md', '\n'.join(briefing))
    db.execute('UPDATE videos SET script_hash=:hash,title=:title WHERE id=:id', dict(hash=fingerprint, title=script.title, id=video['id']))
    db.artifact(video['id'], 'escritor', files=[str((folder / 'script.json').relative_to(db.ROOT)), str((folder / f'escritor_{video["id"]}.md').relative_to(db.ROOT))], next_agent='editor')
    return script


def evaluate(video, script, final):
    config = db.settings()
    criteria = config.evaluation_criteria
    technical = media.technical_check(final, script.duration)
    rights_ok = video['rights'] == 'REFERENCE_ONLY' or (video['rights'] == 'AUTHORIZED' and bool(video['evidence']))
    hard_failures = technical['failures'] + ([] if rights_ok else ['Direitos de reutilização não comprovados.'])
    audio_check = None
    if hard_failures:
        review = None
        scores = {}
        summary = 'Falha técnica ou de direitos impede a aprovação automática.'
        corrections = hard_failures
    elif video['test']:
        review=None
        scores={key:10.0 for key,c in criteria.items() if c.enabled}
        corrections=[]
        summary='Teste técnico sintético aprovado; não comprova fatos sobre GTA 6.'
    else:
        frames = media.samples(final, video['id'])
        visual = config.routes['avaliador'].vision
        audio_check = media.transcript_check(final, script) if config.transcription else None
        source = db.read_artifact(video['id'], 'cacador').dados
        review = Review.model_validate(llm('avaliador', video['id'], {
            'script': script.model_dump(), 'source': source,
            'technical': technical, 'editor': db.read_artifact(video['id'], 'editor').dados,
            'sampled_frames': [str(p.relative_to(db.ROOT)) for p in frames],
            'audio_check': audio_check,
            'evaluation_rubric': {key:c.model_dump() for key,c in criteria.items() if c.enabled},
            'rules': 'Return a 0-10 score for every enabled criterion using its exact key. '
                     'Cite concrete evidence, and specific improvements. Lack of independent visual '
                     'confirmation does not prove a false claim: suggest rewriting uncertain statements '
                     'as rumor or require manual review. Fair use is not a license and mentioning it '
                     'alone must not trigger a rejection. Do not claim to have seen frames when images '
                     'were not attached.'}, Review.model_json_schema(), images=frames[:6] if visual else None))
        scores=review.scores
        if any(not 0 <= score <= 10 for score in scores.values()):
            raise IntegrationError('Notas de avaliação inválidas.')
        corrections=list(review.corrections)
        summary=review.summary
        if audio_check and not audio_check['valid']:
            corrections.append('Narração transcrita diverge do briefing.')
    breakdown={}
    weighted=0.0;weight=0.0;threshold_failures=[]
    for key,c in criteria.items():
        val=scores.get(key)
        passed=None if val is None else val >= c.min_score
        breakdown[key]={**c.model_dump(), 'score':val, 'passed':passed}
        if c.enabled:
            if val is None:
                threshold_failures.append(f'{c.name}: nota não fornecida.')
            else:
                weighted+=c.weight*val;weight+=c.weight
                if not passed:
                    threshold_failures.append(f'{c.name}: {val:.1f} abaixo do mínimo {c.min_score:.1f}.')
    score=round(weighted/weight,2) if weight else 0.0
    factual_ok = review.factual_supported if review else bool(video['test'])
    original_ok = review.original if review else bool(video['test'])
    if review and not factual_ok:
        threshold_failures.append('Afirmações sem suporte; reescrever ou confirmar com fonte verificável.')
    if review and not original_ok:
        threshold_failures.append('Originalidade insuficiente; produzir roteiro e estrutura próprios.')
    if score < config.approval_score:
        threshold_failures.append(f'Nota geral {score:.1f} inferior ao mínimo {config.approval_score:.1f}.')
    corrections=list(dict.fromkeys(corrections+threshold_failures+hard_failures))
    verdict = 'APROVADO' if not corrections and not hard_failures else ('REPROVADO' if hard_failures else 'REVISAR')
    result={'verdict':verdict,'score':score,'scores':scores,'criteria':breakdown,'summary':summary,
            'reason_full':'\n'.join(corrections) if corrections else summary,
            'corrections':corrections,'hard_blocks':bool(hard_failures),
            'requires_human_audiovisual_review': not (config.routes['avaliador'].vision and audio_check and audio_check.get('valid')),
            'technical':technical,'factual_supported':factual_ok,'original':original_ok}
    db.artifact(video['id'], 'avaliador', data=result,
                status='CONCLUIDO' if verdict=='APROVADO' else verdict,
                next_agent='diretor' if verdict=='APROVADO' else 'escritor')
    return result


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
    for name in ('script.json','escritor.json','editor.json','avaliador.json'):
        source=folder/name
        if source.is_file():
            shutil.copy2(source,folder/f'{source.stem}-attempt-{attempt}{source.suffix}')


def approve_rendered(video_id, manual=False, by='local_operator'):
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0]
    if video['manual_decision']=='discard':
        raise PipelineInterrupted('Produção descartada.')
    if video['rights'] in ('BLOCKED','REVIEW_REQUIRED') or (video['rights']=='AUTHORIZED' and not video['evidence']):
        raise IntegrationError('Aprovação bloqueada: direitos de uso não verificados.')
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


def run_pipeline(video_id):
    video = db.rows('SELECT * FROM videos WHERE id=:id', {'id': video_id})[0]
    if video['manual_decision'] in ('discard','approved'):
        return
    if video['approved']:
        distribute(video_id)
        return
    stage(video_id, 'diretor')
    config=db.settings()
    db.artifact(video_id,'diretor',data={'daily_limit':config.daily_limit,
        'max_review_attempts':config.max_review_attempts},next_agent='cacador')
    stage(video_id,'cacador')
    if not (db.ROOT/'handoff'/video_id/'cacador.json').exists():
        hunt(video)
    previous=db.rows('SELECT attempt,details FROM video_attempts WHERE video_id=:id ORDER BY attempt DESC LIMIT 1',{'id':video_id})
    next_attempt=(previous[0]['attempt']+1) if previous else 1
    corrections=json.loads(previous[0]['details']).get('corrections',[]) if previous else None
    for attempt in range(next_attempt,config.max_review_attempts+1):
        if decision(video_id) in ('discard','approved'):
            return
        db.execute('UPDATE videos SET revision=:r WHERE id=:id',dict(r=attempt,id=video_id))
        final=None;render_error=None
        try:
            stage(video_id,'escritor')
            script=write_script(video,corrections)
            stage(video_id,'editor')
            final=media.render(video,script,attempt=attempt)
            # Persist each render before scoring so even rejected files can be previewed.
            db.execute("UPDATE videos SET final_path=:path,render_error=NULL,updated=:now WHERE id=:id AND "
                       "(manual_decision IS NULL OR manual_decision='approve_pending')",
                       {'path':str(final.relative_to(db.ROOT)),'now':time.time(),'id':video_id})
            if decision(video_id)=='discard':
                return
            if decision(video_id)=='approve_pending':
                store_attempt(video_id,attempt,{'verdict':'APROVADO_MANUAL','reason_full':'Aprovado manualmente antes da avaliação.',
                                           'scores':{},'corrections':[]},final)
                approve_rendered(video_id,manual=True)
                return
            stage(video_id,'avaliador')
            result=evaluate(video,script,final)
        except PipelineInterrupted:
            return
        except (media.BriefingError,IntegrationError) as exc:
            render_error=str(exc)
            result={'verdict':'REVISAR','score':None,'scores':{},'criteria':{},
                    'reason_full':render_error,'summary':'Falha na edição ou avaliação.',
                    'corrections':[render_error],'hard_blocks':False}
            if final is None:
                db.execute('UPDATE videos SET render_error=:err WHERE id=:id',{'err':render_error,'id':video_id})
                db.artifact(video_id,'editor',data=result,status='REVISAR',
                            summary='Render falhou; consultar motivo completo.',next_agent='escritor')
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
        db.atomic(folder / f'metadata_{video_id}.json', json.dumps({**script, 'credits': video['credits'], 'source': video['url'],
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
