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


def _whisperx_words(path: Path, folder: Path):
    """WhisperX forced alignment is mandatory for automated clip acceptance."""
    cached=folder/'transcript.json'
    if cached.is_file():
        data=json.loads(cached.read_text('utf-8'))
        if data.get('method')=='whisperx_forced_alignment' and data.get('words'):
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
    model=whisperx.load_model('small',device,compute_type=compute_type,language='pt')
    audio=whisperx.load_audio(str(path))
    result=model.transcribe(audio,batch_size=8,language='pt')
    align_model,metadata=whisperx.load_align_model(language_code=result['language'],device=device)
    aligned=whisperx.align(result['segments'],align_model,metadata,audio,device,
                            return_char_alignments=False)
    words=[]
    for seg in aligned.get('segments',[]):
        for item in seg.get('words',[]):
            if 'start' in item and 'end' in item and item.get('word'):
                words.append({'text':item['word'].strip(),'start':float(item['start']),
                              'end':float(item['end']),
                              'confidence':float(item.get('score') or 0)})
    if not words:
        raise IntegrationError('WhisperX não retornou timestamps alinhados; corte suspenso.')
    payload={'method':'whisperx_forced_alignment','language':result.get('language','pt'),
             'words':words,'segments':aligned.get('segments',[])}
    db.atomic(cached,json.dumps(payload,ensure_ascii=False))
    return payload


def _score_candidates(transcript: dict, volumes: list[float], min_score=MIN_SCORE):
    """Heuristic, independently auditable, 0-100 clip score; no score inflation."""
    segments=transcript.get('segments',[])
    if len(segments)<2:
        return []
    # Ignore silence; focus on peaks relative to the stream itself.
    baseline=statistics.median(volumes) if volumes else -32.0
    indexed=[]
    for i,start in enumerate(segments):
        try:
            begin=float(start['start'])
        except (KeyError,ValueError,TypeError):
            continue
        cursor=i
        while cursor+1<len(segments) and float(segments[cursor]['end'])-begin<28:
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
        indexed.append({'start':max(0,round(begin-.25,2)),
                        'end':round(finish+.30,2),'score':float(score),
                        'type':'destaque com contexto',
                        'transcript':text[:1800],
                        'reason':f'gancho={hook}; contexto={context}; clímax={peak}; '
                                 f'pico áudio={max_gain:.1f}dB; interação={engage}',
                        'peak_db_above_median':round(max_gain,1)})
    indexed.sort(key=lambda x:x['score'],reverse=True)
    selected=[]
    for item in indexed:
        if all(item['end']<=existing['start'] or item['start']>=existing['end'] for existing in selected):
            selected.append(item)
        if len(selected)>=3:
            break
    return selected


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
                     +r'{\an2\pos(540,1000)\fad(45,50)}'+' '.join(timecodes))
    target.write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return len(groups)


def _set_stage(clip_id, stage):
    db.execute("UPDATE live_clips SET stage=:stage,updated=:now WHERE id=:id",
               {'id':clip_id,'stage':stage,'now':time.time()})


def render_clip(clip_id):
    from backend.live_cuts import authorized_channel
    from backend.audio_mix import TARGET_LUFS
    records=db.rows('SELECT * FROM live_clips WHERE id=:id',{'id':clip_id})
    if not records:
        raise ValueError('Corte de live não encontrado.')
    clip=records[0]
    if not authorized_channel(clip['channel_id']):
        raise IntegrationError('Direitos de cortes não documentados na allowlist.')
    from backend.daily_quota import config as quota_config,within_deadline
    if not within_deadline(quota_config()):
        raise IntegrationError('Deadline diário atingido antes do início do corte.')
    db.execute("UPDATE live_clips SET status='PROCESSING',stage='VERIFYING',updated=:now WHERE id=:id",
               {'now':time.time(),'id':clip_id})
    verified_live({'id':clip['video_id'],'channel_id':clip['channel_id']})
    folder=db.ROOT/'videos'/'processing'/'live_cuts'/clip_id
    folder.mkdir(parents=True,exist_ok=True)
    _set_stage(clip_id,'DOWNLOADING_AUDIO')
    audio=_audio_first(clip['source_url'],folder)
    _set_stage(clip_id,'ANALYZING_AUDIO')
    volume,wav=_volume_levels(audio,folder)
    _set_stage(clip_id,'TRANSCRIBING')
    transcript=_whisperx_words(wav,folder)
    from backend.daily_quota import config as quota_config
    _set_stage(clip_id,'SELECTING')
    candidates=_score_candidates(transcript,volume,min_score=quota_config()['min_live_score'])
    if not candidates:
        raise IntegrationError('Sem momento autossuficiente acima do score mínimo configurado; selecionar outra live.')
    choice=candidates[0]
    _set_stage(clip_id,'DOWNLOADING_EXCERPT')
    source=_get_range(clip['source_url'],choice['start'],choice['end'],folder)
    sub=folder/'live-captions.ass'
    count=_subtitles(transcript['words'],choice['start'],choice['end'],sub)
    if not count:
        raise IntegrationError('Sem legenda alinhada para o trecho escolhido.')
    target=db.ROOT/'videos'/'final'/'live_cuts'/clip_id
    target.mkdir(parents=True,exist_ok=True)
    output=target/'cut.mp4'
    ff=media.binary('ffmpeg')
    # Respect the original picture by keeping the entire gameplay frame in a
    # centered band. Background fills 9:16 with a blurred, licensed source copy.
    graph=(
        '[0:v]split=2[orig][blurinput];'
        '[blurinput]scale=1080:1920:force_original_aspect_ratio=increase,'
        'crop=1080:1920,boxblur=30:2[bg];'
        '[orig]scale=1080:-2:force_original_aspect_ratio=decrease,'
        'setsar=1[fg];'
        '[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2:shortest=1,'
        'ass='+str(sub).replace('\\','\\\\').replace(':',r'\:')+'[v];'
        '[0:a]highpass=f=80,acompressor=threshold=0.12:ratio=2.2:attack=12:'
        'release=110,loudnorm=I=-14:TP=-1.5:LRA=9[a]'
    )
    _set_stage(clip_id,'RENDERING')
    temporary=folder/'render.mp4'
    _run([ff,'-hide_banner','-loglevel','error','-y','-i',str(source),
          '-filter_complex',graph,'-map','[v]','-map','[a]',
          '-c:v','libx264','-preset','veryfast','-crf','22','-r','30',
          '-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',
          '-movflags','+faststart',str(temporary)],timeout=1500)
    _set_stage(clip_id,'VALIDATING')
    probe=media.probe(temporary)
    stream=next((x for x in probe['streams'] if x['codec_type']=='video'),{})
    if stream.get('codec_name')!='h264' or (stream.get('width'),stream.get('height'))!=(1080,1920):
        raise IntegrationError('Exportação do corte não está em H264 1080x1920.')
    duration=float(probe['format']['duration'])
    if not MIN_DURATION-.3<=duration<=MAX_DURATION+.3:
        raise IntegrationError('Duração do corte fora da janela 20–60 segundos.')
    # Real decode and final integrated loudness checks BEFORE review acceptance.
    media.run([ff,'-v','error','-xerror','-i',str(temporary),'-f','null','-'],timeout=180)
    measured=subprocess.run([ff,'-hide_banner','-nostats','-i',str(temporary),
                             '-af','ebur128=peak=true','-f','null','-'],
                            capture_output=True,timeout=180)
    if measured.returncode:
        raise IntegrationError('Não foi possível medir o loudness do corte.')
    readings=re.findall(rb'I:\s*(-?\d+(?:\.\d+)?)\s*LUFS',measured.stderr)
    if not readings or abs(float(readings[-1])-(-14.0))>1.0:
        raise IntegrationError('Loudness final fora de -14 LUFS ±1; reprovar corte.')
    if not within_deadline(quota_config()):
        raise IntegrationError('Corte excedeu o deadline e não pode contar para a cota de hoje.')
    import shutil
    shutil.copy2(temporary,output)
    cover=target/'cover.jpg'
    media.run([ff,'-v','error','-y','-ss','1','-i',str(output),
               '-frames:v','1','-q:v','3',str(cover)],timeout=30)
    title=(clip['title'][:72]+' — destaque da live')[:100]
    metadata={'title':title,'description':'Trecho da live original: '+clip['source_url']+
              f' (início em {choice["start"]:.0f}s). Canal: {clip["channel_id"]}. '
              'Créditos ao criador original. Uso autorizado pelo operador.',
              'hashtags':['#GTA6','#CortesDeLive','#Games'],
              'source_url':clip['source_url'],'channel_id':clip['channel_id'],
              'start_seconds':choice['start'],'end_seconds':choice['end'],
              'score':choice['score'],'reason':choice['reason'],
              'alignment':'whisperx_forced_alignment','licensed':True,
              'human_review_required':True,'loudness_target_lufs':TARGET_LUFS}
    db.atomic(target/'metadata.json',json.dumps(metadata,ensure_ascii=False,indent=2))
    db.execute("""UPDATE live_clips SET status='REVIEW_PENDING',stage='READY_FOR_REVIEW',score=:score,
        segment_start=:start,segment_end=:end,file_path=:file,updated=:now,error=NULL
        WHERE id=:id""",{'id':clip_id,'score':choice['score'],
                          'start':choice['start'],'end':choice['end'],
                          'file':str(output.relative_to(db.ROOT)),'now':time.time()})
    record_right(clip['video_id'],clip['channel_id'],'REVIEW_PENDING',
                 'VOD público, licença declarada, legenda alinhada e render validado; aguardando operador.')
    return metadata
