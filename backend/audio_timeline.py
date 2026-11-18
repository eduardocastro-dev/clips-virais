"""Word timing when Whisper works, precisely measured TTS phrase timing otherwise.
The file narration.wav includes lead silence and the trailing music-only margin,
so its PCM duration matches the video, but speech ends at video-margin+lead.
"""
from __future__ import annotations
import json, hashlib, re, shutil, subprocess
from pathlib import Path
from backend import core as db
from backend.personas import get_cast
from backend.integrations import IntegrationError

class TimingBudgetError(IntegrationError):
    def __init__(self,message,actual,target,scenes):
        super().__init__(message)
        self.actual,self.target,self.scenes=actual,target,scenes


def split_phrases(text):
    return [phrase.strip() for phrase in re.split(r'(?<=[.!?])\s+',text.strip()) if phrase.strip()] or [text.strip()]

def create(script,work,test=False):
    from backend import media
    cfg=db.settings()
    target=round(script.duration-cfg.narration_margin_seconds,3)
    lead=cfg.narration_lead_seconds
    if target<=0 or lead+target>script.duration:
        raise media.PreflightError('Orçamento de narração inválido: margem e silêncio inicial excedem o template.')
    cast=get_cast();parts=[];evidence=[];scenes_durations=[]
    cache=db.ROOT/'cache'/'tts'/'phrases';cache.mkdir(parents=True,exist_ok=True)
    for si,scene in enumerate(script.scenes):
        speaker=cast.get(scene.speaker)
        if not speaker:raise media.PreflightError('Personagem não encontrado: '+scene.speaker)
        model=Path(speaker['voice_model'])
        if not test and not model.is_file():raise media.PreflightError(f'Voz Piper não instalada para {scene.speaker}: {model}. Execute scripts/install_voices.py')
        start_index=len(parts)
        for pi,phrase in enumerate(split_phrases(scene.narration)):
            if test:
                # deterministic synthetic signal for pipeline smoke tests only
                raw=work/f'test-{si:02d}-{pi:02d}.wav'
                test_seconds=max(0.2,target/sum(len(split_phrases(sc.narration)) for sc in script.scenes))
                media.run([media.binary('ffmpeg'),'-y','-f','lavfi','-i','sine=frequency=440:sample_rate=22050','-t',str(test_seconds),str(raw)])
            else:
                key=hashlib.sha256(json.dumps({'voice':str(model),'mtime':model.stat().st_mtime_ns,
                  'phrase':phrase,'speed':speaker.get('speed',1)},sort_keys=True).encode()).hexdigest()
                raw=cache/(key+'.wav')
                if not (raw.is_file() and raw.stat().st_size>100):
                    temp=work/f'tts-{si:02d}-{pi:02d}.wav'
                    speed=float(speaker.get('speed',1))
                    proc=subprocess.run([media.binary('piper'),'--model',str(model),'--length_scale',str(round(1/speed,3)),
                        '--output_file',str(temp)],input=phrase.encode(),capture_output=True,timeout=120)
                    if proc.returncode or not temp.is_file():
                        raise media.PreflightError('Falha no TTS Piper ('+scene.speaker+'): '+proc.stderr.decode('utf-8','replace')[-400:])
                    shutil.copy2(temp,raw)
            length=float(media.probe(raw)['format']['duration'])
            if length<=0:raise media.PreflightError(f'Áudio TTS vazio na cena {si+1}, frase {pi+1}')
            normalized=work/f'phrase-{si:02d}-{pi:02d}.wav'
            # Preserve natural pitch and tempo. Loudness normalize using real PCM.
            media.run([media.binary('ffmpeg'),'-y','-i',str(raw),'-af','loudnorm=I=-14:TP=-1.5:LRA=11',
               '-ar','48000','-ac','2',str(normalized)])
            real=float(media.probe(normalized)['format']['duration'])
            parts.append(normalized)
            evidence.append({'scene':si+1,'speaker':scene.speaker,'emotion':scene.emotion,
                             'text':phrase,'duration':real,'path':str(normalized.relative_to(work))})
        scenes_durations.append(sum(row['duration'] for row in evidence[start_index:]))
    raw_total=sum(row['duration'] for row in evidence)
    # Only a mild, <=10% global tempo correction is allowed. Never silently truncate narration.
    rate=max(1.0,raw_total/target)
    if rate>1.1+1e-5:
        raise TimingBudgetError(f'TTS real ({raw_total:.2f}s) excede alvo de {target:.2f}s; Redator deve encurtar cenas.',
            raw_total,target,scenes_durations)
    if raw_total<target-2:
        raise TimingBudgetError(f'TTS real ({raw_total:.2f}s) abaixo do mínimo de {target-2:.2f}s; Redator deve ampliar contexto.',
            raw_total,target,scenes_durations)
    media_rate=rate if raw_total>target else 1.0
    seq=work/'phrase-list.txt'
    seq.write_text('\n'.join("file '"+p.name+"'" for p in parts),'utf-8')
    # Re-encode to one PCM audio and append the intended silent intro/outro.
    joined=work/'speech-joined.wav'
    media.run([media.binary('ffmpeg'),'-y','-f','concat','-safe','0','-i',seq.name,
        '-af',f'atempo={media_rate:.6f}', '-ar','48000','-ac','2',joined.name],cwd=work)
    # Determine precise offsets using each measured audio part, with the same tempo.
    cursor=lead
    for row in evidence:
        duration=row['duration']/media_rate
        row['start']=round(cursor,3)
        cursor+=duration
        row['end']=round(cursor,3)
    speech_time=cursor-lead
    if speech_time>target+0.06:
        raise TimingBudgetError('Amostras não couberam no orçamento real após normalização.',speech_time,target,scenes_durations)
    output=work/'narration.wav'
    media.run([media.binary('ffmpeg'),'-y','-i',str(joined),'-af',
              f'adelay={round(lead*1000)}:all=1,apad,atrim=0:{script.duration}',
              '-ar','48000','-ac','2',str(output)])
    duration=float(media.probe(output)['format']['duration'])
    if abs(duration-script.duration)>.15:raise media.PreflightError('Áudio final divergiu da duração do vídeo: '+str(duration))
    timeline={'video_seconds':script.duration,'speech_target_seconds':target,'speech_real_seconds':round(speech_time,3),
        'lead_seconds':lead,'ending_without_speech_seconds':round(script.duration-cursor,3),
        'timing_method':'tts_phrase_ffprobe_measured','scenes_measured_seconds':scenes_durations,'phrases':evidence,
        'status':'OK' if target-2<=speech_time<=target+.06 else 'OUT_OF_TARGET'}
    (work/'audio-timeline.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2),'utf-8')
    return output
