"""Audio-first, permission-gated YouTube live cutting.

Reuses the attached cortes-de-live skill's core concepts: audio-first intake,
word alignment, audio peaks, context-safe clip boundaries, vertical composite,
and proof sheets. Does not call any cookies/login or download unauthorized VODs.
"""
from __future__ import annotations
import json
import math
import re
import statistics
import subprocess
import sys
import time
import wave
from pathlib import Path
from backend import core as db
from backend.integrations import IntegrationError
from backend.live_cuts import verified_live, record_right, MIN_SCORE, MIN_DURATION, MAX_DURATION
from backend import media

# Never use the live's opening/waiting screen as a YouTube highlight.
INTRO_SKIP_SECONDS = 5 * 60
SELECTION_POLICY_VERSION = 2
MIN_SEPARATION_SECONDS = 90
# At most 12 × 120 seconds of a multi-hour VOD enter WhisperX. Audio-level
# analysis still observes the entire stream; excerpts cover its whole timeline.
MAX_ANALYSIS_WINDOWS = 12
ANALYSIS_WINDOW_SECONDS = 120
TRANSCRIPTION_SAMPLING_VERSION = 1


def _run(args, timeout):
    try:
        completed=subprocess.run(args,capture_output=True,timeout=timeout)
    except subprocess.TimeoutExpired:
        raise IntegrationError('A operação da live excedeu o tempo limite.') from None
    if completed.returncode:
        detail=completed.stderr.decode('utf-8','replace')[-350:]
        raise IntegrationError('Falha ao processar live pública autorizada: '+detail)
    return completed.stdout


def _audio_first(url: str, folder: Path):
    ready=sorted(folder.glob('live-audio.*'))
    if ready:
        return ready[0]
    _run([sys.executable,'-m','yt_dlp','--no-playlist','--no-progress',
          '--no-warnings','--no-part', '-f','bestaudio/best',
          '-o',str(folder/'live-audio.%(ext)s'),url],timeout=3600)
    ready=sorted(folder.glob('live-audio.*'))
    if not ready:
        raise IntegrationError('Áudio da live não está disponível publicamente.')
    return ready[0]


def _volume_levels(path: Path, folder: Path):
    """RMS each second, streaming the transcoded audio instead of loading a 4h VOD."""
    wav=folder/'audio-16k.wav'
    if not wav.is_file():
        _run([media.binary('ffmpeg'),'-hide_banner','-loglevel','error','-y',
              '-i',str(path),'-vn','-ac','1','-ar','16000','-c:a','pcm_s16le',
              str(wav)],timeout=3600)
    levels=[]
    import array
    with wave.open(str(wav),'rb') as w:
        while True:
            chunk=w.readframes(16000)
            if not chunk:
                break
            raw=array.array('h')
            raw.frombytes(chunk)
            if not raw:
                break
            rms=math.sqrt(sum(float(x)*x for x in raw)/len(raw))/32768
            levels.append(round(20*math.log10(max(rms,1e-8)),2))
    return levels,wav


def _analysis_windows(volumes: list[float], duration: float) -> list[tuple[int,int]]:
    """Sample a bounded amount of speech across the *entire* post-intro VOD.

    Each temporal bin contributes one window, chosen by audible activity among
    five positions inside that bin. This is candidate *discovery*, not a
    substitute for scoring or WhisperX word alignment.
    """
    available=max(0.0,float(duration)-INTRO_SKIP_SECONDS)
    if available<MIN_DURATION:
        return []
    count=max(1,min(MAX_ANALYSIS_WINDOWS,int(available//ANALYSIS_WINDOW_SECONDS)))
    width=available/count
    windows=[]
    for index in range(count):
        lower=INTRO_SKIP_SECONDS+index*width
        upper=min(float(duration),INTRO_SKIP_SECONDS+(index+1)*width)
        span=min(float(ANALYSIS_WINDOW_SECONDS),upper-lower)
        if span<MIN_DURATION:
            continue
        free=max(0.0,upper-lower-span)
        starts=sorted(set(int(round(lower+free*f)) for f in (0,.25,.5,.75,1)))
        def activity(start):
            # High speech/activity energy is a hint, not a virality score.
            sample=volumes[max(0,start):min(len(volumes),start+int(span))]
            if not sample:
                return -1000.0
            top=sorted(sample,reverse=True)[:min(15,len(sample))]
            return sum(top)/len(top)
        selected=max(starts,key=lambda start:(activity(start),
                              -abs(start-(lower+free/2))))
        stop=min(int(duration),selected+int(span))
        if stop-selected>=MIN_DURATION:
            windows.append((selected,stop))
    return windows


def _extract_analysis_window(source: Path, output: Path, start: int,
                             stop: int) -> None:
    """Copy only this PCM window; never load a multi-hour WAV into RAM."""
    with wave.open(str(source),'rb') as origin:
        rate=origin.getframerate()
        if (origin.getnchannels()!=1 or origin.getsampwidth()!=2 or
            rate!=16000 or origin.getcomptype()!='NONE'):
            raise IntegrationError('WhisperX exige o WAV de análise PCM mono 16 kHz.')
        origin.setpos(min(origin.getnframes(),int(start*rate)))
        with wave.open(str(output),'wb') as target:
            target.setparams(origin.getparams())
            target.writeframes(origin.readframes(int((stop-start)*rate)))


def _offset_alignment(aligned: dict, start: int, stop: int) -> dict:
    """Translate only genuine aligned timestamps back to the original VOD."""
    segments=[]
    words=[]
    duration=stop-start
    for segment in aligned.get('segments',[]):
        local_words=[]
        for word in segment.get('words',[]):
            try:
                a,b=float(word['start']),float(word['end'])
            except (TypeError,ValueError,KeyError):
                continue
            if not all(math.isfinite(v) for v in (a,b)) or not 0<=a<b<=duration+.5:
                continue
            token=str(word.get('word') or word.get('text') or '').strip()
            if not token:
                continue
            item={'text':token,'start':round(start+a,3),
                  'end':round(start+b,3),'confidence':float(word.get('score') or 0)}
            local_words.append(item)
        if not local_words:
            # Inaccurate/unaligned ASR segments are not eligible highlights.
            continue
        # A complete segment must be backed by aligned words. Keep its actual
        # segment boundaries, clamped to the sampled window, in global time.
        try:
            a,b=float(segment['start']),float(segment['end'])
        except (KeyError,ValueError,TypeError):
            a=local_words[0]['start']-start
            b=local_words[-1]['end']-start
        if not all(math.isfinite(v) for v in (a,b)):
            continue
        a=max(0.0,a)
        b=min(float(duration),b)
        if b<=a:
            continue
        segments.append({'start':round(start+a,3),'end':round(start+b,3),
                         'text':str(segment.get('text') or
                            ' '.join(word['text'] for word in local_words)).strip()})
        words.extend(local_words)
    return {'segments':segments,'words':words}


def _whisperx_words(path: Path, folder: Path, volumes: list[float]|None=None,
                    clip_id: str|None=None):
    """WhisperX forced alignment on bounded windows with resumable checkpoints."""
    cached=folder/'transcript.json'
    with wave.open(str(path),'rb') as source:
        duration=source.getnframes()/source.getframerate()
    windows=_analysis_windows(volumes or [],duration)
    if not windows:
        raise IntegrationError('Live muito curta após os cinco minutos de introdução.')
    if cached.is_file():
        try:
            data=json.loads(cached.read_text('utf-8'))
        except (OSError,ValueError):
            data={}
        if (data.get('method')=='whisperx_forced_alignment' and
            data.get('words') and data.get('segments') and
            (data.get('scope') is None or
             (data.get('scope')=='sampled' and
              data.get('sampling_version')==TRANSCRIPTION_SAMPLING_VERSION and
              data.get('windows')==[list(window) for window in windows] and
              abs(float(data.get('source_duration',0))-duration)<.1))):
            return data
    try:
        import whisperx
    except (ImportError,OSError) as exc:
        raise IntegrationError(
            'Cortes automáticos exigem WhisperX com forced alignment instalado no worker. '
            'A captura/edição foi pausada sem usar timestamps inventados.') from exc
    import os
    device=os.environ.get('WHISPERX_DEVICE','cpu')
    compute_type='int8' if device=='cpu' else 'float16'
    model=None
    alignment=None
    metadata=None
    segments=[]
    words=[]
    for index,(start,stop) in enumerate(windows,1):
        if clip_id:
            _set_stage(clip_id,f'TRANSCRIBING_{index}_OF_{len(windows)}')
            db.put_setting('worker_heartbeat',time.time())
        chunk=folder/f'transcript-window-{start}-{stop}.json'
        current=None
        if chunk.is_file():
            try:
                item=json.loads(chunk.read_text('utf-8'))
                if (item.get('method')=='whisperx_forced_alignment' and
                    item.get('sampling_version')==TRANSCRIPTION_SAMPLING_VERSION and
                    item.get('window')==[start,stop]):
                    current=item
            except (OSError,ValueError):
                pass
        if current is None:
            if model is None:
                model=whisperx.load_model('small',device,compute_type=compute_type,
                                         language='pt')
            if alignment is None:
                alignment,metadata=whisperx.load_align_model(language_code='pt',
                                                             device=device)
            window_file=folder/f'analysis-window-{index:02d}.wav'
            try:
                _extract_analysis_window(path,window_file,start,stop)
                audio=whisperx.load_audio(str(window_file))
                result=model.transcribe(audio,batch_size=8,language='pt')
                if result.get('segments'):
                    aligned=whisperx.align(result['segments'],alignment,metadata,
                                           audio,device,return_char_alignments=False)
                    current=_offset_alignment(aligned,start,stop)
                else:
                    current={'segments':[],'words':[]}
            finally:
                window_file.unlink(missing_ok=True)
            current.update({'method':'whisperx_forced_alignment',
                            'sampling_version':TRANSCRIPTION_SAMPLING_VERSION,
                            'window':[start,stop]})
            db.atomic(chunk,json.dumps(current,ensure_ascii=False))
        segments.extend(current['segments'])
        words.extend(current['words'])
        if clip_id:
            db.put_setting('worker_heartbeat',time.time())
            db.log_event(None,'live_cuts','TRANSCRIPTION_WINDOW',
                         f'Live {clip_id}: janela {index}/{len(windows)} '
                         f'({start}s–{stop}s) analisada com WhisperX.')
    if not words or not segments:
        raise IntegrationError('Nenhum trecho com palavras alinhadas encontrado nas janelas da live.')
    segments.sort(key=lambda x:x['start'])
    words.sort(key=lambda x:x['start'])
    payload={'method':'whisperx_forced_alignment','language':'pt','scope':'sampled',
             'sampling_version':TRANSCRIPTION_SAMPLING_VERSION,
             'source_duration':duration,'windows':[list(window) for window in windows],
             'analyzed_seconds':sum(stop-start for start,stop in windows),
             'words':words,'segments':segments}
    db.atomic(cached,json.dumps(payload,ensure_ascii=False))
    return payload


def _minimum_gap(stream_duration: float) -> float:
    """Spacing between clip *edges*, scaled to the whole VOD.

    For long streams, prefer at least ten minutes between clips. For shorter
    eligible VODs, enforce a minimum of 90 seconds instead of adjacent cuts.
    """
    available=max(0.0,stream_duration-INTRO_SKIP_SECONDS)
    return max(float(MIN_SEPARATION_SECONDS),min(600.0,available/6.0))


def _interval_gap(a: dict, b: dict) -> float:
    """Positive distance between non-overlapping excerpts, otherwise negative."""
    return max(float(a['start'])-float(b['end']),
               float(b['start'])-float(a['end']))


def _spread_candidates(candidates: list[dict], stream_duration: float,
                       count: int=3) -> list[dict]:
    """Keep score qualification, then prioritize diversity over similar timestamps.

    The strongest qualifying moment anchors selection; subsequent moments are
    chosen by max-min temporal distance across the full stream. Equal distances
    prefer the better score. Never fill the quota with low-quality filler.
    """
    if count<=0 or not candidates:
        return []
    ordered=sorted(candidates,key=lambda x:(-float(x['score']),float(x['start'])))
    minimum_gap=_minimum_gap(stream_duration)
    selected=[ordered[0]]
    while len(selected)<count:
        eligible=[x for x in ordered if x not in selected and
                  all(_interval_gap(x,previous)>=minimum_gap for previous in selected)]
        if not eligible:
            break
        chosen=max(eligible,key=lambda x:(
            min(_interval_gap(x,previous) for previous in selected),
            float(x['score']),-float(x['start'])))
        selected.append(chosen)
    return sorted(selected,key=lambda x:x['start'])


def _selection_valid(candidates, count: int, min_score: float,
                     stream_duration: float) -> bool:
    """Validate cached or regenerated choices before any download/render."""
    if not isinstance(candidates,list) or len(candidates)<count:
        return False
    try:
        selections=candidates[:count]
        for item in selections:
            start,end,score=(float(item[key]) for key in ('start','end','score'))
            if (not all(math.isfinite(v) for v in (start,end,score)) or
                start<INTRO_SKIP_SECONDS or end<=start or
                not MIN_DURATION-.3<=end-start<=MAX_DURATION+.3 or
                end>stream_duration+1 or score<min_score):
                return False
        return all(_interval_gap(left,right)>=_minimum_gap(stream_duration)
                   for i,left in enumerate(selections) for right in selections[i+1:])
    except (KeyError,TypeError,ValueError):
        return False


def _score_candidates(transcript: dict, volumes: list[float],
                      min_score=MIN_SCORE, max_cuts: int=3):
    """Score full-VOD highlights, excluding intro and spreading distinct moments."""
    segments=transcript.get('segments',[])
    if len(segments)<2:
        return []
    duration=max(float(len(volumes)),max(
        (float(s.get('end') or 0) for s in segments),default=0.0))
    if duration<INTRO_SKIP_SECONDS+MIN_DURATION:
        return []
    # Ignore silence; focus on peaks relative to the stream itself.
    baseline=statistics.median(volumes) if volumes else -32.0
    indexed=[]
    for i,start in enumerate(segments):
        try:
            begin=float(start['start'])
            if not math.isfinite(begin) or begin<INTRO_SKIP_SECONDS:
                continue
        except (KeyError,ValueError,TypeError):
            continue
        cursor=i
        while (cursor+1<len(segments) and
               float(segments[cursor]['end'])-begin<28 and
               float(segments[cursor+1]['start'])-float(segments[cursor]['end'])<=3):
            # Sampled windows have real gaps between them. Never assemble
            # an artificial sentence across two distant analysis windows.
            cursor+=1
        if cursor>=len(segments):
            continue
        finish=float(segments[cursor].get('end',begin))
        if not MIN_DURATION<=finish-begin<=MAX_DURATION:
            continue
        text=' '.join(str(x.get('text') or '').strip() for x in segments[i:cursor+1])
        if len(text.split())<18:
            continue
        lead=str(start.get('text') or '').strip()
        first_word=lead.lower().split(' ',1)[0].strip('.,!?') if lead else ''
        is_independent=first_word not in {'então','aí','porque','mas','e','tipo','enfim'} and len(lead.split())>=3
        window=volumes[max(0,int(begin)):min(len(volumes),int(finish)+1)] if volumes else []
        max_gain=max(window)-baseline if window else 0
        peaked=max_gain>=5
        climax=('!' in text or '?' in text or peaked)
        hook=min(30,30 if is_independent else 8)
        context=25 if is_independent else 6
        peak=25 if climax else 4
        evidence=10 if peaked else 0
        engage=10 if re.search(r'\?|!|olha|caramba|incr.vel|surpresa|aconteceu',text,re.I) else 0
        score=hook+context+peak+evidence+engage
        if score < min_score:
            continue
        indexed.append({'start':max(INTRO_SKIP_SECONDS,round(begin-.25,2)),
                        'end':round(min(finish+.30,begin+MAX_DURATION-.25),2),
                        'score':float(score),
                        'type':'destaque com contexto',
                        'transcript':text[:1800],
                        'reason':f'gancho={hook}; contexto={context}; clímax={peak}; '
                                 f'pico áudio={max_gain:.1f}dB; interação={engage}',
                        'peak_db_above_median':round(max_gain,1)})
    return _spread_candidates(indexed,duration,max_cuts)


def _get_range(url: str, start: float, end: float, folder: Path):
    outputs=sorted(folder.glob('source-clip.*'))
    if outputs:
        return outputs[0]
    # Only this authorized excerpt is requested; no logged-in cookies/age bypass.
    args=[sys.executable,'-m','yt_dlp','--no-playlist','--no-progress','--no-warnings',
          '--download-sections',f'*{start:.2f}-{end:.2f}',
          '--force-keyframes-at-cuts','-f','bv*+ba/b','--merge-output-format','mp4',
          '-o',str(folder/'source-clip.%(ext)s'),url]
    _run(args,timeout=1800)
    outputs=sorted(p for p in folder.glob('source-clip.*')
                   if p.suffix.lower() in ('.mp4','.webm','.mkv','.mov'))
    if not outputs:
        raise IntegrationError('Não foi possível obter um trecho autorizado do VOD.')
    return outputs[0]


def _subtitles(words, start, end, target):
    from backend.media import subtitle_time, clean_subtitle
    from backend.viral_edit import caption_groups
    shifted=[{**w,'start':max(0,float(w['start'])-start),
              'end':max(0,float(w['end'])-start)} for w in words
             if float(w['start'])>=start and float(w['end'])<=end]
    groups=caption_groups({'words':shifted})
    if not groups:
        raise IntegrationError('Não há palavras alinhadas dentro do corte.')
    lines=['[Script Info]','ScriptType: v4.00+','PlayResX: 1080','PlayResY: 1920',
           '[V4+ Styles]',
           'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
           'Style: Default,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,850,1',
           '[Events]','Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    for group in groups:
        timecodes=[]
        for word in group['words']:
            centis=max(1,round((word['end']-word['start'])*100))
            timecodes.append(r'{\kf'+str(centis)+'}'+clean_subtitle(word['text']))
        lines.append('Dialogue: 0,'+subtitle_time(group['start'])+','+
                     subtitle_time(group['end']+.08)+',Default,,0,0,0,,'
                     +r'{\an2\pos(540,1735)\fad(45,50)}'+' '.join(timecodes))
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return len(groups)


def _set_stage(clip_id, stage):
    db.execute("UPDATE live_clips SET stage=:stage,updated=:now WHERE id=:id",
               {'id':clip_id,'stage':stage,'now':time.time()})


def _metadata_for(clip, choice, ordinal, total, target_lufs):
    return {
        'title':(clip['title'][:68]+' — corte '+str(ordinal)+'/'+str(total))[:100],
        'description':'Trecho da live original: '+clip['source_url']+
            f' (de {choice["start"]:.0f}s a {choice["end"]:.0f}s). Canal: '+
            clip['channel_id']+'. Créditos ao criador original. Uso autorizado pelo operador.',
        'hashtags':['#GTA6','#CortesDeLive','#Games'],
        'source_url':clip['source_url'],'channel_id':clip['channel_id'],
        'parent_live_id':clip['id'],'ordinal':ordinal,'total_cuts':total,
        'start_seconds':choice['start'],'end_seconds':choice['end'],
        'score':choice['score'],'reason':choice['reason'],
        'alignment':'whisperx_forced_alignment','licensed':True,
        'human_review_required':True,'loudness_target_lufs':target_lufs,
        'layout':'streamer_top_gameplay_bottom',
        'webcam_anchor':clip.get('webcam_anchor') or 'bottom_left',
    }


def _persist_output(clip, choice, ordinal, output, cover, metadata_file, title):
    previous=db.rows(
        'SELECT id FROM live_clip_outputs WHERE parent_id=:parent AND ordinal=:ordinal',
        {'parent':clip['id'],'ordinal':ordinal})
    record_id=previous[0]['id'] if previous else db.uid()
    now=time.time()
    params={'id':record_id,'parent':clip['id'],'ordinal':ordinal,'title':title,
            'score':choice['score'],'start':choice['start'],'end':choice['end'],
            'file':str(output.relative_to(db.ROOT)),
            'cover':str(cover.relative_to(db.ROOT)),
            'meta':str(metadata_file.relative_to(db.ROOT)),'now':now}
    if previous:
        db.execute("""UPDATE live_clip_outputs SET status='REVIEW_PENDING',
            score=:score,segment_start=:start,segment_end=:end,title=:title,
            file_path=:file,cover_path=:cover,metadata_path=:meta,
            error=NULL,updated=:now WHERE id=:id""",params)
    else:
        db.execute("""INSERT INTO live_clip_outputs
            (id,parent_id,ordinal,title,status,score,segment_start,segment_end,
             file_path,cover_path,metadata_path,created,updated)
            VALUES (:id,:parent,:ordinal,:title,'REVIEW_PENDING',:score,:start,
                    :end,:file,:cover,:meta,:now,:now)""",params)


def _validated_output(clip, ordinal, choice=None):
    rows=db.rows("""SELECT * FROM live_clip_outputs WHERE parent_id=:parent
                    AND ordinal=:ordinal""",
                 {'parent':clip['id'],'ordinal':ordinal})
    if not rows:
        return None
    row=rows[0]
    if choice is not None and (
        row['segment_start'] is None or row['segment_end'] is None or
        abs(float(row['segment_start'])-float(choice['start']))>.01 or
        abs(float(row['segment_end'])-float(choice['end']))>.01):
        # Older cached cuts can violate the new intro/spread policy. Never
        # silently replace an already human-approved deliverable.
        if row['status']=='APPROVED':
            raise IntegrationError(
                'Corte já aprovado usa timestamps antigos. '
                'Reprocesse a live explicitamente para aplicar a nova política.')
        return None
    if row['status'] in ('REVIEW_PENDING','APPROVED') and row['file_path']:
        try:
            file=db.safe_file(row['file_path'])
        except ValueError:
            return None
        if file.is_file() and file.stat().st_size>1024:
            return row
    return None


def render_clip(clip_id):
    """One WhisperX analysis, three distinct complete render/validation passes.

    Each completed child persists before the next begins so technical retries
    do not download/re-render already accepted cuts.
    """
    from backend.live_cuts import authorized_channel
    from backend.audio_mix import TARGET_LUFS
    from backend.live_clip_layout import graph as live_graph,validate_anchor
    from backend.daily_quota import config as quota_config,within_deadline
    records=db.rows('SELECT * FROM live_clips WHERE id=:id',{'id':clip_id})
    if not records:raise ValueError('Live não encontrada.')
    clip=records[0]
    if not authorized_channel(clip['channel_id'],clip['video_id']):
        raise IntegrationError('Direitos de cortes não documentados na allowlist.')
    if not within_deadline(quota_config()):
        raise IntegrationError('Deadline diário atingido antes do início da live.')
    anchor=validate_anchor(clip.get('webcam_anchor') or 'bottom_left')
    total=max(3,int(clip.get('cut_target') or 3))
    db.execute("""UPDATE live_clips SET status='PROCESSING',stage='VERIFYING',
                  updated=:now,error=NULL WHERE id=:id""",
               {'now':time.time(),'id':clip_id})
    verified_live({'id':clip['video_id'],'channel_id':clip['channel_id']})
    folder=db.ROOT/'videos'/'processing'/'live_cuts'/clip_id
    folder.mkdir(parents=True,exist_ok=True)
    _set_stage(clip_id,'DOWNLOADING_AUDIO')
    audio=_audio_first(clip['source_url'],folder)
    _set_stage(clip_id,'ANALYZING_AUDIO')
    volume,wav=_volume_levels(audio,folder)
    _set_stage(clip_id,'TRANSCRIBING')
    transcript=_whisperx_words(wav,folder,volumes=volume,clip_id=clip_id)
    _set_stage(clip_id,'SELECTING')
    choices_file=folder/'candidates.json'
    stream_duration=max(float(len(volume)),max(
        (float(s.get('end') or 0) for s in transcript.get('segments',[])),default=0.0))
    threshold=quota_config()['min_live_score']
    cached={}
    if choices_file.is_file():
        try:
            cached=json.loads(choices_file.read_text('utf-8'))
        except (OSError,ValueError):
            cached={}
    # Old array-only caches were generated with no intro/spacing guard.
    candidates=(cached.get('cuts',[]) if isinstance(cached,dict) and
                cached.get('selection_policy_version')==SELECTION_POLICY_VERSION and
                cached.get('stream_duration')==stream_duration else [])
    if not _selection_valid(candidates,total,threshold,stream_duration):
        candidates=_score_candidates(
            transcript,volume,min_score=threshold,max_cuts=total)
        if not _selection_valid(candidates,total,threshold,stream_duration):
            raise IntegrationError(
                f'Só {len(candidates)} trechos válidos ficaram disponíveis após ignorar '
                f'os primeiros 5 minutos, aplicar o score mínimo {threshold} e exigir '
                f'espaçamento de {_minimum_gap(stream_duration):.0f}s entre cortes. '
                f'São necessários {total}; não serão criados cortes repetidos ou artificiais.')
        db.atomic(choices_file,json.dumps({
            'selection_policy_version':SELECTION_POLICY_VERSION,
            'stream_duration':stream_duration,'score_threshold':threshold,
            'cuts':candidates},ensure_ascii=False,indent=2))
    selections=candidates[:total]
    output_dir=db.ROOT/'videos'/'final'/'live_cuts'/clip_id
    output_dir.mkdir(parents=True,exist_ok=True)
    ff=media.binary('ffmpeg')
    latest=None
    for index,choice in enumerate(selections,1):
        if not authorized_channel(clip['channel_id'],clip['video_id']):
            raise IntegrationError('Autorização de corte revogada durante a produção.')
        if _validated_output(clip,index,choice):
            _set_stage(clip_id,f'RENDERED_{index}')
            continue
        if not within_deadline(quota_config()):
            raise IntegrationError('Deadline da produção atingido antes de concluir os três cortes.')
        # A changed score threshold can pick another timestamp on a rerun.
        # Cache excerpt bytes by their actual time window, not just ordinal.
        window_key=f"{int(round(choice['start']*100)):08d}-{int(round(choice['end']*100)):08d}"
        individual=folder/f'cut-{index:02d}-{window_key}'
        individual.mkdir(parents=True,exist_ok=True)
        _set_stage(clip_id,f'DOWNLOADING_EXCERPT_{index}')
        source=_get_range(clip['source_url'],choice['start'],choice['end'],individual)
        subtitles=individual/'live-captions.ass'
        count=_subtitles(transcript['words'],choice['start'],choice['end'],subtitles)
        if not count:
            raise IntegrationError(f'Corte {index}: legenda alinhada indisponível.')
        _set_stage(clip_id,f'RENDERING_{index}')
        temporary=individual/'render.mp4'
        _run([ff,'-hide_banner','-loglevel','error','-y','-i',str(source),
              '-filter_complex',live_graph(str(subtitles),anchor),
              '-map','[v]','-map','[a]','-t',str(choice['end']-choice['start']),
              '-c:v','libx264','-preset','veryfast','-crf','22','-r','30',
              '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
              '-movflags','+faststart',str(temporary)],timeout=1800)
        _set_stage(clip_id,f'VALIDATING_{index}')
        probe=media.probe(temporary)
        video_stream=next((x for x in probe['streams'] if x['codec_type']=='video'),{})
        if (video_stream.get('codec_name')!='h264' or
            (video_stream.get('width'),video_stream.get('height'))!=(1080,1920)):
            raise IntegrationError(f'Corte {index}: exportação não está em H264 1080x1920.')
        duration=float(probe['format']['duration'])
        if not MIN_DURATION-.3<=duration<=MAX_DURATION+.3:
            raise IntegrationError(f'Corte {index}: duração fora de 20–60 s.')
        media.run([ff,'-v','error','-xerror','-i',str(temporary),
                   '-f','null','-'],timeout=180)
        measured=subprocess.run([ff,'-hide_banner','-nostats','-i',str(temporary),
                                 '-af','ebur128=peak=true','-f','null','-'],
                                capture_output=True,timeout=180)
        if measured.returncode:
            raise IntegrationError(f'Corte {index}: não foi possível medir loudness.')
        values=re.findall(rb'I:\s*(-?\d+(?:\.\d+)?)\s*LUFS',measured.stderr)
        if not values or abs(float(values[-1])-TARGET_LUFS)>1.0:
            raise IntegrationError(f'Corte {index}: loudness fora de -14 LUFS ±1.')
        import shutil
        published=output_dir/f'cut-{index:02d}.mp4'
        shutil.copy2(temporary,published)
        cover=output_dir/f'cover-{index:02d}.jpg'
        media.run([ff,'-v','error','-y','-ss','1','-i',str(published),
                   '-frames:v','1','-q:v','3',str(cover)],timeout=30)
        metadata=_metadata_for(clip,choice,index,total,TARGET_LUFS)
        metadata_file=output_dir/f'metadata-{index:02d}.json'
        db.atomic(metadata_file,json.dumps(metadata,ensure_ascii=False,indent=2))
        _persist_output(clip,choice,index,published,cover,metadata_file,
                        metadata['title'])
        db.log_event(None,'live_cuts','CUT_READY',
                     f"{clip['title']}: corte {index}/{total} renderizado e validado.")
        latest=metadata
    completed=db.rows("""SELECT * FROM live_clip_outputs WHERE parent_id=:id
                         AND status IN ('REVIEW_PENDING','APPROVED')
                         AND file_path IS NOT NULL ORDER BY ordinal""",
                      {'id':clip_id})
    if not authorized_channel(clip['channel_id'],clip['video_id']):
        raise IntegrationError('Autorização de corte revogada antes da revisão humana.')
    if len(completed)<total:
        raise IntegrationError(
            f'Foram concluídos somente {len(completed)}/{total} cortes; '
            'manter produção pendente e retentar os restantes.')
    first=completed[0]
    db.execute("""UPDATE live_clips SET status='REVIEW_PENDING',
        stage='READY_FOR_REVIEW',score=:score,segment_start=:start,
        segment_end=:end,file_path=:path,error=NULL,updated=:now WHERE id=:id""",
        {'id':clip_id,'score':first['score'],'start':first['segment_start'],
         'end':first['segment_end'],'path':first['file_path'],
         'now':time.time()})
    record_right(clip['video_id'],clip['channel_id'],'REVIEW_PENDING',
                 f'{total} cortes distintos renderizados, validados e aguardando revisão humana.')
    return {'parent_live_id':clip_id,'total_cuts':total,
            'status':'REVIEW_PENDING','last_cut':latest}
