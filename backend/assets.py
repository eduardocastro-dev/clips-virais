"""Asset library. Provenance is mandatory and unverified assets never enter published edits."""
from __future__ import annotations
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from backend import core as db
from backend.integrations import IntegrationError

KINDS={'shorts','gameplay','images','persona','uploads','clip','music','sfx'}
CLASSES={'OWNED_GENERATED','OFFICIAL','THIRD_PARTY','FREE_LICENSE'}
ROOT=db.ROOT/'assets'
for kind in KINDS:(ROOT/kind).mkdir(parents=True,exist_ok=True)


def safe_asset(path):
    path=(db.ROOT/path).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():
        raise ValueError('Asset inexistente, fora da biblioteca ou com caminho inválido.')
    return path


def canonical_id(url):
    parsed=urlsplit(url)
    if 'youtu' not in (parsed.hostname or ''):return None
    if parsed.path.startswith('/shorts/'):
        return parsed.path.split('/')[2]
    if parsed.hostname=='youtu.be':return parsed.path.strip('/')
    return parse_qs(parsed.query).get('v',[None])[0]


def register_short(meta):
    """Register one Short for possible download, with consent status explicit."""
    url=meta['url'];vid=canonical_id(url)
    if not vid or not re.fullmatch('[A-Za-z0-9_-]{11}',vid):
        raise ValueError('ID YouTube inválido.')
    found=db.rows('SELECT * FROM assets WHERE source_id=:id AND kind=\'shorts\'',{'id':vid})
    if found:return found[0]['id']
    asset_id=db.uid();now=time.time()
    db.execute('''INSERT OR IGNORE INTO assets (id,kind,source_id,url,title,channel,source_class,rights_status,
        evidence,status,metadata,created,updated) VALUES (:id,'shorts',:source_id,:url,:title,:channel,
        'THIRD_PARTY','REFERENCE_ONLY','','METADATA_ONLY',:metadata,:now,:now)''',
        {'id':asset_id,'source_id':vid,'url':url,'title':str(meta.get('title') or '')[:300],
         'channel':str(meta.get('source_profile') or meta.get('uploader') or '')[:200],
         'metadata':json.dumps(meta,ensure_ascii=False),'now':now})
    return asset_id


def download_short(asset_id):
    """Copy an explicitly licensed Short into the permanent asset library.

    yt-dlp streams progress into SQLite; incomplete output lives in temp/library.
    """
    matches=db.rows("SELECT * FROM assets WHERE id=:id AND kind='shorts'",{'id':asset_id})
    if not matches:raise ValueError('Short não cadastrado.')
    a=matches[0]
    if a['rights_status']!='AUTHORIZED' or not a['evidence'] or len(a['evidence'].strip())<10:
        raise IntegrationError('Download indisponível: registre autorização/licença para este Short.')
    if a['path'] and (db.ROOT/a['path']).is_file():return a['path']
    from datetime import datetime
    from zoneinfo import ZoneInfo
    date=datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%Y-%m-%d')
    channel=re.sub(r'[^A-Za-z0-9_-]+','_',a['channel'] or 'canal')[:48]
    name=f'{date}_{channel}_{a["source_id"]}.mp4'
    dest=ROOT/'shorts'/name
    temp_dir=db.ROOT/'temp'/'library-imports'/asset_id
    temp_dir.mkdir(parents=True,exist_ok=True)
    md=json.loads(a['metadata'] or '{}')
    error=''
    for attempt in range(1,4):
        db.execute("UPDATE assets SET status='DOWNLOADING',updated=:now,error=NULL,metadata=:md WHERE id=:id",
            {'id':asset_id,'now':time.time(),'md':json.dumps({**md,'progress':0,'attempt':attempt})})
        cmd=[sys.executable,'-m','yt_dlp','--no-playlist','--no-warnings',
             '--newline','--no-part','--max-filesize','250M','--socket-timeout','20',
             '--retries','0','-f','best[ext=mp4]/best','--merge-output-format','mp4',
             '-o',str(temp_dir/'source.%(ext)s'),'--',a['url']]
        try:
            process=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                     text=True,encoding='utf-8',errors='replace')
            started=time.monotonic();last=0;lines=[]
            assert process.stdout is not None
            for line in process.stdout:
                lines.append(line.strip()[:220]);lines=lines[-12:]
                if time.monotonic()-started>240:
                    process.kill();raise TimeoutError('Download excedeu 240 segundos.')
                matches_pct=re.search(r'(\d+(?:\.\d+)?)%',line)
                if matches_pct and time.monotonic()-last>1.5:
                    md['progress']=min(99,float(matches_pct.group(1)))
                    db.execute('UPDATE assets SET metadata=:meta,updated=:now WHERE id=:id',
                               {'meta':json.dumps(md,ensure_ascii=False),'now':time.time(),'id':asset_id})
                    last=time.monotonic()
            returncode=process.wait(timeout=10)
            downloaded=list(temp_dir.glob('source.*'))
            candidate=next((p for p in downloaded if p.suffix.lower()=='.mp4'),None)
            if returncode or not candidate:
                raise RuntimeError(' | '.join(lines[-3:]) or 'Vídeo não foi gerado.')
            from backend.media import probe
            duration=float(probe(candidate)['format']['duration'])
            from backend.uploads import promote_across_volumes
            promote_across_volumes(candidate,dest)
            relative=str(dest.relative_to(db.ROOT))
            md.update({'duration':duration,'progress':100,'download_status':'DOWNLOADED',
                'source_url':a['url'],'channel':a['channel'],'downloaded_at':time.time()})
            db.atomic(dest.with_suffix('.json'),json.dumps(md,ensure_ascii=False,indent=2))
            db.execute("UPDATE assets SET path=:path,status='READY',duration=:duration,metadata=:meta,error=NULL,updated=:now WHERE id=:id",
                       {'id':asset_id,'path':relative,'duration':duration,
                        'meta':json.dumps(md,ensure_ascii=False),'now':time.time()})
            shutil.rmtree(temp_dir,ignore_errors=True)
            from backend.clips import mark_for_slicing
            mark_for_slicing(asset_id)
            return relative
        except (OSError,RuntimeError,TimeoutError,subprocess.TimeoutExpired) as exc:
            error=str(exc)[-650:]
            for path in temp_dir.iterdir():
                if path.is_file():path.unlink(missing_ok=True)
            db.execute("UPDATE assets SET status='RETRYING',error=:error,updated=:now WHERE id=:id",
                       {'id':asset_id,'error':f'{attempt}/3 {error}','now':time.time()})
    db.execute("UPDATE assets SET status='FAILED',error=:error,updated=:now WHERE id=:id",
               {'id':asset_id,'error':error,'now':time.time()})
    raise IntegrationError('Download do Short falhou após 3 tentativas: '+error)


class MissingAssetsError(IntegrationError):
    # Missing prerequisites pause a job without consuming review attempts.
    def __init__(self, paths, detail=''):
        self.paths=sorted(set(paths))
        super().__init__('Faltam assets: '+', '.join(self.paths)+'. Coloque em /assets/ e clique Reescanear.'+
                         (' Detalhes: '+detail if detail else ''))


def mandatory_assets(persona=None, script=None):
    # A registered asset is not necessarily playable or licensed.
    from backend.personas import get_persona
    persona=persona or get_persona()
    missing=[]
    gameplay=db.rows('''SELECT path,media_type,kind,category FROM assets WHERE path IS NOT NULL AND
        status='READY' AND rights_status='AUTHORIZED' AND COALESCE(active,1)=1
        AND (kind IN ('gameplay','shorts','clip') OR category IN ('gameplay','b-roll'))''')
    if not any(a['path'] and (db.ROOT/a['path']).is_file() and (a['media_type']=='video' or (a['media_type'] is None and Path(a['path']).suffix.lower() in ('.mp4','.mov','.webm','.mkv'))) for a in gameplay):
        missing.append('assets/gameplay/')
    music=db.rows('''SELECT path FROM assets WHERE media_type='audio' AND category='musica' AND
        status='READY' AND rights_status='AUTHORIZED' AND COALESCE(active,1)=1''')
    if not any(a['path'] and (db.ROOT/a['path']).is_file() for a in music):missing.append('assets/music/')
    from backend.personas import get_cast
    cast=get_cast()
    required_speakers={getattr(scene,'speaker','dante_palma') for scene in script.scenes} if script else {persona.get('selected','dante_palma')}
    for speaker in required_speakers:
        character=cast.get(speaker, persona)
        img=character.get('image_path','')
        if not img or not (db.ROOT/img).is_file() or not character.get('production_ready'):
            missing.append('assets/personas/'+speaker+'/expressions/ (24 PNGs de alta qualidade)')
    return missing


def select_visuals(video,script):
    """Plan 1.5-3s visual changes, avoiding consecutive clip IDs and parent IDs.

    Ranking: scene-tag relevance, different parent, lower usage count. Without
    a usable licensed video, pause the production; no neon fallback.
    """
    from backend import production_media
    folder=production_media.workspace(video['id'])
    from backend.scenarios import template_for
    from backend.source_preview import ensure as ensure_source
    tv_source=ensure_source(video) if template_for(video.get('template')) else None
    # Parent long videos are never used alongside their sliced children.
    candidates=db.rows("""SELECT a.* FROM assets a WHERE a.status='READY'
      AND a.rights_status='AUTHORIZED' AND COALESCE(a.active,1)=1 AND a.path IS NOT NULL
      AND a.kind IN ('clip','gameplay','shorts','images','uploads')
      AND (a.kind='clip' OR NOT EXISTS (SELECT 1 FROM assets c WHERE c.parent_id=a.id))
      ORDER BY COALESCE(a.usage_count,0),a.created DESC LIMIT 500""")
    pool=[]
    for row in candidates:
        media=row.get('media_type') or ('image' if row['kind']=='images' else 'video')
        if media!='video' or row.get('category') in ('logo','musica','efeito sonoro'):
            continue
        try:safe_asset(row['path'])
        except ValueError:continue
        pool.append(row)
    # Library copies are created only inside temp/<production>, never in original paths.
    copy_cache={}
    def copy(row):
        if row['id'] not in copy_cache:
            copy_cache[row['id']]=production_media.copy_original(safe_asset(row['path']),video['id'],f'asset-{row["id"]}')
        return str(copy_cache[row['id']].relative_to(db.ROOT))
    def words(value):
        return set(re.findall(r'[a-zA-ZÀ-ÿ0-9]{3,}',str(value or '').lower()))
    article=production_media.capture_article(video) if video.get('platform') in ('news','youtube','tiktok','instagram') and not video.get('test') else None
    screenshots=(article or {}).get('assets',[])
    # Source frames are extracted only from locally available or explicitly
    # licensed footage. A frame is not assigned a semantic score unless vision
    # actually evaluated it against the narrated text.
    curated={};candidates=[];source_video=None
    if video.get('platform') in ('youtube','tiktok','instagram') and video.get('rights')=='AUTHORIZED':
        from backend import source_frames
        source=production_media.acquire_source_video(video)
        if source and source.is_file():
            source_video=source
            candidates=source_frames.extract(video['id'],source)
            curated=source_frames.review_with_vision(video,script,candidates)
            if not curated and db.settings().routes.get('escritor') and db.settings().routes['escritor'].vision:
                # Try a denser distributed sample before conceding to gameplay.
                candidates=source_frames.extract(video['id'],source,interval=1.0,max_frames=60)
                curated=source_frames.review_with_vision(video,script,candidates)
    db.atomic(db.ROOT/'handoff'/video['id']/'visual-curation.json',
       json.dumps({'candidate_count':len(candidates),'curated':curated,
                   'method':'multimodal_vision' if curated else 'source-not-verified'},
                  ensure_ascii=False,indent=2))
    result=[];last_id=None;last_parent=None;third_seconds=0.;support_seconds=0.;local_usage={}
    for index,scene in enumerate(script.scenes):
        length=float(scene.end-scene.start)
        # Prefer 3-second cuts; merge any very short remainder with previous.
        pieces=[];t=0.
        while t<length-.03:
            remaining=length-t
            if pieces and remaining<1.5:
                pieces[-1]['duration']=round(pieces[-1]['duration']+remaining,3)
                break
            from backend import media
            try:
                cut_target = float(media.template(script.template).get('cut_seconds') or db.settings().visual_cut_seconds)
            except Exception:
                cut_target = float(db.settings().visual_cut_seconds)
            take=min(cut_target,remaining)
            pieces.append({'relative_start':round(t,3),'duration':round(take,3)})
            t+=take
        if not pieces:pieces=[{'relative_start':0.,'duration':round(length,3)}]
        scene_tokens=words(getattr(scene,'text','')+' '+getattr(scene,'narration','')+' '+video.get('title',''))
        segments=[]
        for pi,part in enumerate(pieces):
            take=part['duration']
            eligible=[]
            distinct_parents={x['parent_id'] or x['id'] for x in pool}
            for a in pool:
                origin=a['parent_id'] or a['id']
                if len(distinct_parents)>1 and origin==last_parent:continue
                third=a['source_class']=='THIRD_PARTY'
                # A source classified as third-party can never exceed 5 total seconds.
                if third and (take>4.0 or third_seconds+take>5.0):continue
                if a['id']==last_id and a.get('media_type')!='image' and a['kind']!='images':continue
                tags=json.loads(a.get('tags') or '[]')
                overlap=len(scene_tokens & words(' '.join(tags)+' '+(a.get('title') or '')+' '+(a.get('category') or '')))
                penalty=3 if origin==last_parent else 0
                count=local_usage.get(a['id'],0)+int(a.get('usage_count') or 0)
                eligible.append((a,overlap,penalty,count))
            if not eligible and tv_source:
                # Private preview only: unverified source is never added to
                # the ordinary library candidates eligible for publication.
                eligible.append((tv_source,0,0,0))
            if eligible:
                # Sort first by theme and different parent; then balance usage.
                eligible.sort(key=lambda q:(-q[1],q[2],q[3],q[0]['id']))
                chosen=eligible[0][0]
                parent=chosen['parent_id'] or chosen['id']
                seg={**part,'asset_id':chosen['id'],'parent_id':parent,
                     'path':copy(chosen),'type':'image' if chosen.get('media_type')=='image' or chosen['kind']=='images' else 'video',
                     'source_offset':0.,'source':chosen['url'] or chosen['path'],
                     'source_class':chosen['source_class'],'credits':chosen['channel'] or chosen['url'] or '',
                     'category':chosen.get('category'),'tags':json.loads(chosen.get('tags') or '[]')}
                if chosen.get('media_type')=='video' and chosen.get('duration'):
                    seg['source_offset']=max(0., min(float(chosen['duration'])-take, (index+pi)*2.))
                if chosen['source_class']=='THIRD_PARTY' and chosen.get('rights_status')=='AUTHORIZED':
                    third_seconds+=take
                last_id=chosen['id'];last_parent=parent
                local_usage[chosen['id']]=local_usage.get(chosen['id'],0)+1
            else:
                raise MissingAssetsError(['assets/gameplay/'], 'Nenhum vídeo/imagem licenciado e ativo corresponde à cena '+str(index+1))
            if tv_source:
                seg['tv_source_path']=tv_source['path']
                seg['tv_source_url']=tv_source['url']
                seg['tv_source_rights']=tv_source['rights_status']
                seg['tv_source_asset_id']=tv_source['id']
                seg['tv_source_channel']=tv_source.get('channel','')
                try:
                    tv_meta=json.loads(tv_source.get('metadata') or '{}')
                    seg['tv_source_date']=tv_meta.get('source_date','')
                    seg['requires_onscreen_credit']=bool(tv_meta.get('requires_onscreen_credit',False))
                except (TypeError,ValueError):
                    seg['tv_source_date']=''
                    seg['requires_onscreen_credit']=False
            segments.append(seg)
        # Stagger article screenshot/card over some scene segments, never full article mirrors.
        if segments:
            chosen=segments[0]
            if screenshots and index in (0, min(2, len(script.scenes)-1)):
                ranked=sorted(screenshots,key=lambda shot:
                    (-len(scene_tokens & words(shot.get('excerpt',''))),shot['kind']!='headline'))
                shot=ranked[index%len(ranked)] if len(ranked)>1 else ranked[0]
                overlap=len(scene_tokens & words(shot.get('excerpt','')))
                if overlap>=1 or (index==0 and shot['kind'] in ('headline','thumbnail','article-image')):
                    chosen.update({'overlay_path':shot['path'],'overlay_label':shot['kind'],
                                   'overlay_source':shot['source'],'overlay_rights':'REVIEW_REQUIRED',
                                   'visual_relevance':None,'visual_relevance_method':'lexical',
                                   'visual_reason':'Trecho da fonte relacionado por palavras; revisão visual recomendada.'})
            elif index==0 and video.get('platform') in ('news','youtube','synthetic'):
                chosen.update({'overlay_label':'headline-card','overlay_text':video.get('title','Notícia em análise'),
                               'overlay_source':video.get('url',''),'overlay_rights':'OWNED_GENERATED'})
        if curated.get(index):
            options=curated[index]
            for segment_index,segment in enumerate(segments):
                if segment_index%4==3:continue
                match=options[segment_index%len(options)]
                segment.update({'overlay_path':match['path'], 'overlay_label':'source-frame',
                    'overlay_source':video.get('url',''),
                    'overlay_rights':'AUTHORIZED',
                    'source_frame_at':match.get('source_timestamp'),
                    'visual_relevance':match['relevance'],
                    'visual_relevance_method':'vision',
                    'visual_reason':match['reason']})
        # One short licensed excerpt may replace the gameplay backing where
        # a multimodal match exists or from keyframe candidates. Hard cap: 5s total.
        chosen_candidate = curated.get(index, [None])[0] if curated.get(index) else (candidates[index % len(candidates)] if (source_video and candidates) else None)
        if source_video and chosen_candidate and support_seconds<5 and segments:
            offset=chosen_candidate.get('source_timestamp')
            if offset is not None and float(offset)>=0.0:
                piece=next((x for x in segments if x.get('overlay_path')),segments[0])
                excerpt=min(float(piece['duration']),4.0,5.0-support_seconds)
                if excerpt>=1.0 and abs(excerpt-float(piece['duration']))<.01:
                    piece.update({'source_clip_path':str(source_video.relative_to(db.ROOT)),
                        'source_clip_at':float(offset), 'source_class':'THIRD_PARTY',
                        'credits':video.get('credits') or video.get('url') or '',
                        'overlay_path':None, 'overlay_label':None})
                    support_seconds+=excerpt
        primary=segments[0]
        result.append({'scene':index,'start':scene.start,'end':scene.end,'segments':segments,
                       'tv_source_asset_id':tv_source['id'] if tv_source else None,
                       'type':primary['type'],'path':primary.get('path'),'asset_id':primary.get('asset_id'),
                       'source':primary['source'],'source_class':primary['source_class'],
                       'credits':primary.get('credits',''), 'support_seconds':third_seconds,
                       'source_coverage':round(sum(float(x['duration']) for x in segments if x.get('overlay_path'))/max(.1,length),3)})
    db.atomic(db.ROOT/'handoff'/video['id']/'visual-assets.json',json.dumps(result,indent=2,ensure_ascii=False))
    return result


def grant(asset_id,classification,evidence):
    if classification not in CLASSES:raise ValueError('Categoria de origem desconhecida.')
    if len(evidence.strip())<10:raise ValueError('Registre evidência de direito de utilização (mínimo 10 caracteres).')
    db.execute("UPDATE assets SET source_class=:class,rights_status='AUTHORIZED',evidence=:evidence,updated=:now WHERE id=:id",
               {'id':asset_id,'class':classification,'evidence':evidence[:2000],'now':time.time()})


def delete(asset_id,confirm_children=False):
    items=db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})
    if not items:return False
    a=items[0]
    children=db.rows('SELECT * FROM assets WHERE parent_id=:id',{'id':asset_id})
    if children and not confirm_children:
        raise ValueError('O original possui clipes derivados. Confirme para excluir o original e todos os clipes.')
    if db.rows("SELECT id FROM videos WHERE status='PROCESSING'"):
        raise ValueError('Pare as produções ativas antes de excluir a biblioteca.')
    paths=[]
    for item in [*children,a]:
        if item['path']:
            try:paths.append(safe_asset(item['path']))
            except ValueError:pass
    # Database rows removed together; files only from the controlled assets root.
    with db.transaction() as conn:
        conn.exec_driver_sql('DELETE FROM assets WHERE parent_id=?',(asset_id,))
        conn.exec_driver_sql('DELETE FROM assets WHERE id=?',(asset_id,))
    for target in paths:
        target.unlink(missing_ok=True)
        target.with_suffix('.json').unlink(missing_ok=True)
    derived=ROOT/'clips'/asset_id
    if derived.is_dir() and not derived.is_symlink() and derived.resolve().parent==(ROOT/'clips').resolve():
        shutil.rmtree(derived)
    return True


def update_metadata(asset_id, title=None, category=None, tags=None, active=None):
    item=db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})
    if not item:raise ValueError('Asset não encontrado.')
    updates=[];args={'id':asset_id,'now':time.time()}
    if title is not None:
        if not title.strip():raise ValueError('Título vazio.')
        updates.append('title=:title');args['title']=title.strip()[:300]
    if category is not None:
        from backend.uploads import CATEGORIES
        if category not in CATEGORIES:raise ValueError('Categoria inválida.')
        updates.append('category=:category');args['category']=category
    if tags is not None:
        if len(tags)>25 or any(len(x)>40 for x in tags):raise ValueError('Muitas tags ou tags longas.')
        updates.append('tags=:tags');args['tags']=json.dumps([x.strip().lower() for x in tags if x.strip()],ensure_ascii=False)
    if active is not None:
        updates.append('active=:active');args['active']=int(active)
    if not updates:return item[0]
    db.execute('UPDATE assets SET '+','.join(updates)+',updated=:now WHERE id=:id',args)
    # Derived clips inherit parent edits to category, tags, activity and attribution.
    if item[0]['kind']!='clip':
        mirror={k:args[k] for k in ('category','tags','active') if k in args}
        if mirror:
            db.execute('UPDATE assets SET '+','.join(f'{k}=:{k}' for k in mirror)+',updated=:now WHERE parent_id=:id',
                       {**mirror,'id':asset_id,'now':time.time()})
    return db.rows('SELECT * FROM assets WHERE id=:id',{'id':asset_id})[0]


def count_usage(visuals):
    tally={}
    for scene in visuals:
        for part in scene.get('segments',[]):
            identifier=part.get('asset_id')
            if identifier:tally[identifier]=tally.get(identifier,0)+1
    for asset_id,amount in tally.items():
        db.execute('UPDATE assets SET usage_count=COALESCE(usage_count,0)+:count WHERE id=:id',
                   {'count':amount,'id':asset_id})


def sync_library():
    # Index non-empty, user-dropped media without inferring authorization.
    from backend.clips import mark_for_slicing
    folders={
       'gameplay':('gameplay','gameplay',{'.mp4','.mov','.webm','.mkv'}),
       'images':('images','imagem de fundo',{'.png','.jpg','.jpeg','.webp','.gif'}),
       'shorts':('shorts','gameplay',{'.mp4','.webm','.mov'}),
       'music':('music','musica',{'.mp3','.m4a','.wav'}),
       'sfx':('sfx','efeito sonoro',{'.mp3','.m4a','.wav'}),
       'personas':('persona','imagem de fundo',{'.png','.jpg','.jpeg','.webp'}),
       'persona':('persona','imagem de fundo',{'.png','.jpg','.jpeg','.webp'}),
       'uploads':('uploads','outro',{'.mp4','.mov','.webm','.mkv','.mp3','.m4a','.wav',
                                  '.png','.jpg','.jpeg','.webp','.gif','.ttf','.otf','.srt'}),
    }
    found=0;queued=0
    for folder,(kind,category,extensions) in folders.items():
        base=ROOT/folder;base.mkdir(parents=True,exist_ok=True)
        for path in base.rglob('*'):
            if not path.is_file() or path.is_symlink() or not path.stat().st_size or path.suffix.lower() not in extensions:
                continue
            # Use path and file hash to prevent duplicate registration after a rename.
            rel=str(path.relative_to(db.ROOT))
            if db.rows('SELECT id FROM assets WHERE path=:path',{'path':rel}):continue
            from backend.clips import file_sha256
            sha=file_sha256(path)
            if db.rows('SELECT id FROM assets WHERE sha256=:sha AND parent_id IS NULL AND path IS NOT NULL',{'sha':sha}):
                continue
            suffix=path.suffix.lower()
            media_type=('video' if suffix in ('.mp4','.mov','.mkv','.webm') else
                        'audio' if suffix in ('.mp3','.wav','.m4a') else
                        'image' if suffix in ('.png','.jpg','.jpeg','.webp','.gif') else
                        'font' if suffix in ('.ttf','.otf') else 'subtitle')
            if folder=='uploads':
                category=('gameplay' if media_type=='video' else 'musica' if media_type=='audio' else
                          'imagem de fundo' if media_type=='image' else 'outro')
            now=time.time();id=db.uid()
            db.execute('''INSERT OR IGNORE INTO assets
                (id,kind,source_id,url,title,channel,source_class,rights_status,evidence,path,
                 status,metadata,created,updated,category,tags,active,sha256,media_type,size_bytes)
                VALUES (:id,:kind,:source_id,'',:title,'','THIRD_PARTY','REVIEW_REQUIRED','',:path,
                'PENDING_RIGHTS','{}',:now,:now,:category,'[]',1,:sha,:media,:size)''',
                {'id':id,'kind':kind,'source_id':'local:'+sha,'title':path.stem[:300],
                 'path':rel,'now':now,'category':category,'sha':sha,'media':media_type,'size':path.stat().st_size})
            found+=1
            # Clip only after documented usage authorization; ensure no duplicate jobs.
            if media_type=='video':
                try:
                    mark_for_slicing(id);queued+=1
                except (OSError,ValueError,RuntimeError) as exc:
                    db.log_event(None,'assets','SPLIT_ERROR',str(exc)[:500])
    return {'registered':found,'clips_queued':queued}


def set_license(asset_id,classification,evidence):
    grant(asset_id,classification,evidence)
    db.execute("UPDATE assets SET status='READY' WHERE id=:id AND path IS NOT NULL AND status NOT IN ('SPLITTING','SPLIT_QUEUED')",{'id':asset_id})
    # A change to the original's license must immediately propagate to all derivatives.
    db.execute("UPDATE assets SET source_class=:class,rights_status='AUTHORIZED',evidence=:evidence,updated=:now WHERE parent_id=:id",
               {'class':classification,'evidence':evidence[:2000],'now':time.time(),'id':asset_id})

