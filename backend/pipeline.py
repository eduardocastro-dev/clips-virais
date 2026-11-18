import hashlib
import json
import shutil
import time
from pathlib import Path
from pydantic import BaseModel, Field
from sqlalchemy import text
from backend import core as db, media
from backend.contracts import ImportRequest, Script, platform_url
from backend.integrations import IntegrationError, metadata, download_authorized, viral_score, llm, youtube_upload
from backend.distribution import schedule_postiz


AGENTS = ['diretor', 'cacador', 'escritor', 'editor', 'avaliador']


class Review(BaseModel):
    scores: dict[str, float]
    factual_supported: bool
    original: bool
    corrections: list[str] = Field(max_length=12)
    summary: str = Field(max_length=400)


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
        # Store the operational date separately from UTC timestamps; count atomically.
        count = c.execute(text("SELECT value FROM kv WHERE key=:key"), {'key': 'daily:' + db.today()}).scalar()
        count = int(json.loads(count)) if count else 0
        if count >= config.daily_limit:
            raise ValueError('Limite diário de produção atingido.')
        c.execute(text('INSERT INTO kv VALUES (:key,:value) ON CONFLICT(key) DO UPDATE SET value=excluded.value'),
                  dict(key='daily:' + db.today(), value=json.dumps(count + 1)))
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


def stage(video_id, agent):
    if db.settings().emergency_stop:
        raise IntegrationError('Parada de emergência ativa.')
    db.execute("UPDATE videos SET stage=:agent,status='PROCESSING',updated=:now,error=NULL WHERE id=:id",
               dict(id=video_id, agent=agent, now=time.time()))
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
            meta['duration']=float(media.probe(path)['format']['duration'])
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
        result = llm('escritor', video['id'], {'source': source, 'id': video['id'], 'instructions': video['instructions'],
            'duration': video['duration'], 'template': video['template'], 'corrections': corrections or [],
            'constraints': 'Use only supported claims. Original commentary, no source imitation. Visuals are text cards or the authorized source, center crop. No music. Each narration must fit its scene at 2-2.5 words/sec.'}, Script.model_json_schema())
        script = Script.model_validate(result)
        if script.duration != video['duration'] or script.template != video['template']:
            raise IntegrationError('Briefing divergente da duração/template solicitados.')
        if any(s.source_id != video['id'] for s in script.scenes):
            raise IntegrationError('Briefing referencia fonte não autorizada.')
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
    technical = media.technical_check(final, script.duration)
    rights_ok = video['rights'] == 'REFERENCE_ONLY' or (video['rights'] == 'AUTHORIZED' and bool(video['evidence']))
    if not technical['valid'] or not rights_ok:
        result = {'verdict': 'REPROVADO', 'scores': {}, 'corrections': technical['failures'] + ([] if rights_ok else ['Direitos inválidos']), 'hard_blocks': True}
    elif video['test']:
        result = {'verdict': 'APROVADO', 'scores': {'technical_test': 10}, 'corrections': [], 'test_only': True, 'hard_blocks': False}
    else:
        frames = media.samples(final, video['id'])
        config = db.settings()
        visual = config.routes['avaliador'].vision
        audio_check = media.transcript_check(final, script) if config.transcription else None
        if audio_check and not audio_check['valid']:
            result = {'verdict':'REVISAR','scores':{},'corrections':['Narração transcrita diverge do briefing.'],'hard_blocks':True}
            db.artifact(video['id'], 'avaliador', data=result, status='REVISAR', next_agent='escritor')
            return result
        source = db.read_artifact(video['id'], 'cacador').dados
        review = Review.model_validate(llm('avaliador', video['id'], {'script': script.model_dump(), 'source': source,
            'technical': technical, 'editor': db.read_artifact(video['id'], 'editor').dados,
            'sampled_frames': [str(p.relative_to(db.ROOT)) for p in frames],
            'audio_check': audio_check,
            'limitations': 'Frames attached only when vision enabled. No direct audio listening: use measured transcript and silence checks. Missing evidence must require human review.'}, Review.model_json_schema(), images=frames[:6] if visual else None))
        if any(not 0 <= score <= 10 for score in review.scores.values()) or not review.scores:
            raise IntegrationError('Notas de avaliação inválidas.')
        score = sum(review.scores.values()) / len(review.scores)
        verdict = 'APROVADO' if score >= db.settings().approval_score and review.factual_supported and review.original and not review.corrections else 'REVISAR'
        result = {**review.model_dump(), 'verdict': verdict, 'score': score, 'hard_blocks': False,
                  'requires_human_audiovisual_review': not (visual and audio_check and audio_check['valid']), 'technical': technical}
    db.artifact(video['id'], 'avaliador', data=result, status='CONCLUIDO' if result['verdict'] == 'APROVADO' else result['verdict'],
                next_agent='diretor' if result['verdict'] != 'REVISAR' else 'escritor')
    return result


def run_pipeline(video_id):
    video = db.rows('SELECT * FROM videos WHERE id=:id', {'id': video_id})[0]
    if video['approved']:
        distribute(video_id)
        return
    stage(video_id, 'diretor')
    db.artifact(video_id, 'diretor', data={'daily_limit': db.settings().daily_limit, 'revision_limit': 2}, next_agent='cacador')
    stage(video_id, 'cacador')
    if not (db.ROOT / 'handoff' / video_id / 'cacador.json').exists():
        hunt(video)
    corrections = None
    for revision in range(video['revision'], 3):
        db.execute('UPDATE videos SET revision=:r WHERE id=:id', dict(r=revision, id=video_id))
        stage(video_id, 'escritor')
        script = write_script(video, corrections)
        stage(video_id, 'editor')
        try:
            final = media.render(video, script)
        except media.BriefingError as exc:
            result={'verdict':'REVISAR','scores':{},'corrections':[str(exc)],'hard_blocks':True}
            db.artifact(video_id,'editor',data=result,status='REVISAR',summary='Briefing requer correção de timing/cortes.',next_agent='escritor')
        else:
            stage(video_id, 'avaliador')
            result = evaluate(video, script, final)
        # Archive each evaluation; overwriting the latest handoff does not erase history.
        db.atomic(db.ROOT / 'handoff' / video_id / f'review-{revision}.json', json.dumps(result, ensure_ascii=False))
        if result['verdict'] == 'APROVADO':
            db.execute("UPDATE videos SET approved=1,status='APPROVED',stage='diretor',final_path=:path,updated=:now WHERE id=:id",
                       dict(id=video_id, path=str(final.relative_to(db.ROOT)), now=time.time()))
            db.log_event(video_id, 'diretor', 'DONE', 'Vídeo aprovado. Testes e revisão audiovisual seguem restrições de distribuição.')
            distribute(video_id)
            daily_report()
            return
        if result['verdict'] == 'REPROVADO':
            break
        corrections = result['corrections']
    db.execute("UPDATE videos SET status='REJECTED',stage='diretor',error=:error WHERE id=:id", dict(id=video_id, error='; '.join(result['corrections'])[:600] or 'Limite de duas revisões atingido.'))
    db.notify('rejected:' + video_id, 'Vídeo reprovado: ' + video_id + '. Consulte a avaliação.')
    daily_report()


def distribute(video_id):
    video = db.rows('SELECT * FROM videos WHERE id=:id', {'id': video_id})[0]
    if not video['approved'] or video['rights'] in ('BLOCKED', 'REVIEW_REQUIRED'):
        raise IntegrationError('Distribuição bloqueada pela avaliação ou direitos.')
    config = db.settings()
    if config.emergency_stop:
        raise IntegrationError('Distribuição pausada por emergência.')
    script = Script.model_validate_json((db.ROOT / 'handoff' / video_id / 'script.json').read_text('utf-8')).model_dump()
    if video['credits']:
        script['description'] = (script['description'] + '\n\nCréditos: ' + video['credits'])[:5000]
    review = db.read_artifact(video_id, 'avaliador').dados
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
        can_auto = (platform == 'youtube' and config.youtube_auto and config.approval_mode == 'automatic'
                    and not video['test'] and not review.get('requires_human_audiovisual_review'))
        can_postiz = (config.postiz_auto and platform in config.postiz_channels and config.approval_mode == 'automatic'
                      and not video['test'] and not review.get('requires_human_audiovisual_review'))
        if can_postiz:
            try:
                schedule_postiz(pub, final, script)
            except IntegrationError:
                current = db.rows('SELECT status FROM publications WHERE id=:id',{'id':pub['id']})[0]['status']
                # PENDENTE means the non-idempotent create call was not started.
                db.execute('UPDATE publications SET status=:status,error=:error WHERE id=:id',dict(id=pub['id'],
                    status='AGUARDANDO_PUBLICACAO_MANUAL' if current=='PENDENTE' else 'PUBLICANDO',
                    error='Postiz indisponível ou resposta incerta. Consulte a integração; arquivo manual preservado.'))
                db.notify('postiz-error:'+pub['id'],'Postiz requer atenção; não será realizado reenvio automático.')
        elif can_auto:
            # Durable intent before network call; ambiguous failures are never blindly retried.
            changed = db.execute("UPDATE publications SET status='PUBLICANDO',updated=:now WHERE id=:id AND status='PENDENTE'", dict(id=pub['id'], now=time.time()))
            if changed:
                try:
                    external, url = youtube_upload(final, script)
                    db.execute("UPDATE publications SET status='PUBLICADO',external_id=:external,url=:url,updated=:now WHERE id=:id",
                               dict(id=pub['id'], external=external, url=url, now=time.time()))
                    db.notify('published:' + pub['id'], 'Upload YouTube confirmado (privado): ' + url)
                except IntegrationError:
                    db.execute("UPDATE publications SET status='REQUER_AUTENTICACAO',error='Verifique autenticação e reconcilie possível upload antes de repetir.' WHERE id=:id", {'id': pub['id']})
                    db.notify('auth:' + pub['id'], 'YouTube: autenticação ou reconciliação necessária; arquivo manual preservado.')
        else:
            db.execute("UPDATE publications SET status='AGUARDANDO_PUBLICACAO_MANUAL',updated=:now WHERE id=:id", dict(id=pub['id'], now=time.time()))
            db.notify('manual:' + pub['id'], f'{platform}: vídeo {video_id} pronto para revisão e publicação manual' + (' (TESTE; não publicar).' if video['test'] else '.'))


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
