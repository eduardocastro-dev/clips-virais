import json
import hashlib
import os
import shutil
import subprocess
import sys
import textwrap
import re
from difflib import SequenceMatcher
from pathlib import Path
from backend import core as db
from backend.contracts import Script
from backend.integrations import IntegrationError


class BriefingError(IntegrationError):
    """Creative/timing correction required; return to writer instead of retrying infrastructure."""


class PreflightError(IntegrationError):
    # Input, alignment or render quality issue; do not spend an AI review attempt.
    pass


def binary(name):
    executable = os.getenv(name.upper() + '_BIN') or shutil.which(name)
    if not executable:
        raise IntegrationError(f'{name} não instalado ou não encontrado no PATH.')
    return executable


def run(args, timeout=60, cwd=None):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise IntegrationError('Processamento de mídia excedeu o timeout.') from None
    if result.returncode:
        # Preserve the full Python traceback for the local diagnostic. Do not mislabel
        # Python/PyAV failures as failures of the FFmpeg executable.
        stderr=result.stderr.decode('utf-8', errors='replace')
        log=db.ROOT/'logs'/'media-last-error.log'
        db.atomic(log, stderr[-24000:])
        command=Path(str(args[0])).name.lower()
        component=('Python/PyAV/Faster Whisper' if ('python' in command or 'traceback (most recent' in stderr.lower())
                   else 'FFmpeg/ffprobe' if command.startswith(('ffmpeg','ffprobe')) else command)
        detail=next((line.strip() for line in reversed(stderr.splitlines()) if line.strip()), 'stderr vazio')
        raise IntegrationError(f'Falha em {component}: {detail[:600]} (traceback: logs/media-last-error.log)')
    return result.stdout


def probe(path):
    return json.loads(run([binary('ffprobe'), '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)]))


def template(name):
    choices = json.loads((Path(__file__).resolve().parent.parent / 'templates' / 'catalog.json').read_text('utf-8'))
    overrides = db.get_setting('templates', {})
    if name not in choices:
        raise IntegrationError('Template não encontrado.')
    return {**choices[name], **overrides.get(name, {})}


def subtitle_time(seconds):
    cs = round(seconds * 100)
    return f'{cs // 360000}:{cs // 6000 % 60:02}:{cs // 100 % 60:02}.{cs % 100:02}'


def clean_subtitle(value):
    return value.replace('\\', '').replace('{', '').replace('}', '').replace('\n', ' ')


def transcribe(path, auto_language=False):
    """Optional local speech recognition. No transcript is sent wholesale to another agent."""
    result_path=db.ROOT/'cache'/('transcript-'+db.uid()+'.json')
    try:
        run([sys.executable,'-m','backend.transcription',str(path),str(result_path)] + (['auto'] if auto_language else []),timeout=240)
        return json.loads(result_path.read_text('utf-8'))
    finally:
        result_path.unlink(missing_ok=True)


def subtitles(script, style, target, transcript=None, styled_hook=False):
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1080', 'PlayResY: 1920', '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             f'Style: Default,DejaVu Sans,{style["font_size"]},&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,2,90,90,745,1',
             'Style: Header,DejaVu Sans,65,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,90,90,240,1',
             'Style: Badge,DejaVu Sans,34,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,2,1,8,90,90,90,1',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    badge_label = clean_subtitle(str(style.get('badge') or 'GTA 6')).upper()
    lines.append(f'Dialogue: 0,0:00:00.00,0:00:03.00,Badge,,0,0,0,,{{\\an8\\pos(540,95)\\fad(100,100)\\1c&H00F4FF&}}★ {badge_label} ★')
    if not styled_hook:
        hook='\\N'.join(textwrap.wrap(clean_subtitle(script.hook),24))
        lines.append(f'Dialogue: 0,0:00:00.15,0:00:03.00,Header,,0,0,0,,{{\\fad(120,100)}}{hook}')
    if script.cta:
        cta='\\N'.join(textwrap.wrap(clean_subtitle(script.cta),28))
        lines.append(f'Dialogue: 2,{subtitle_time(max(0,script.duration-3))},{subtitle_time(script.duration)},Header,,0,0,0,,{{\\an5\\pos(540,1350)\\fad(100,100)}}{cta}')
    for scene in script.scenes:
        text = '\\N'.join(textwrap.wrap(clean_subtitle(scene.text), 24))
        if scene.end>max(3,scene.start):
            lines.append(f'Dialogue: 0,{subtitle_time(max(3,scene.start))},{subtitle_time(scene.end)},Header,,0,0,0,,{{\\fad(150,150)}}{text}')
        if transcript:
            continue
        words = clean_subtitle(scene.narration).split()
        chunks = [' '.join(words[i:i+6]) for i in range(0, len(words), 6)]
        for index, chunk in enumerate(chunks):
            start = scene.start + (scene.end - scene.start) * index / len(chunks)
            end = scene.start + (scene.end - scene.start) * (index + 1) / len(chunks)
            lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(end)},Default,,0,0,0,,{{\\fad(70,70)}}{chunk}')
    if transcript and transcript.get('words'):
        highlight_color = str(style.get('highlight_color') or '&H00F4FF&').replace('&', r'\1c&')
        if not highlight_color.startswith(r'\1c'): highlight_color = r'\1c' + highlight_color
        keywords={'GTA','VI','6','VICE','CITY','ROCKSTAR','TRAILER','GAMEPLAY','NOVO','OFICIAL','DATA','MAPA','LUCIA','JASON'}
        for item in transcript['words']:
            token=clean_subtitle(str(item.get('text','')).strip())
            if not token:continue
            color=highlight_color if any(x.upper() in keywords for x in re.findall(r'[A-Za-zÀ-ÿ0-9]+',token)) else ''
            start=float(item['start']);end=max(start+.06,float(item['end']))
            effect=r'\fscx114\fscy114\fad(40,60)'+color
            lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(end)},Default,,0,0,0,,{{{effect}}}{token}')
    target.write_text('\n'.join(lines), encoding='utf-8')


def narration(script, work, test=False):
    from backend.audio_timeline import create
    return create(script,work,test)


def render(video, script: Script, attempt=1):
    """Create all video scenes before the evaluator, preserving every attempt."""
    from backend.visual_renderer import montage
    from backend.personas import get_persona
    work=db.ROOT/'videos/processing'/video['id']/f'attempt-{attempt:02d}'
    work.mkdir(parents=True,exist_ok=True)
    style=template(script.template)
    # Mandatory input check BEFORE invoking TTS, FFmpeg or evaluator.
    from backend.assets import mandatory_assets, MissingAssetsError, sync_library
    sync_library()
    missing=mandatory_assets(script=script)
    if missing:
        raise MissingAssetsError(missing)
    from backend.text_styles import active_style, render_hook
    chosen_text_style=active_style()
    hook_overlay=(render_hook(script.hook,work/'text-style-hook.png',chosen_text_style)
                  if chosen_text_style else None)
    audio=narration(script,work,bool(video['test']))
    # Forced word timestamp alignment for real videos (Whisper local).
    # Never label estimated phrase timings as synchronized subtitles.
    timeline=json.loads((work/'audio-timeline.json').read_text('utf-8'))
    try:
        transcript=transcribe(audio) if not video['test'] else None
        if not video['test'] and (not transcript or not transcript.get('words')):
            raise IntegrationError('Faster Whisper não retornou palavras alinhadas.')
        if transcript:transcript['method']='whisper_words'
    except (IntegrationError,RuntimeError,TypeError) as exc:
        # We synthesized each sentence separately and measured its REAL PCM duration.
        # This fallback is phrase-level, not an estimated word-level alignment.
        db.log_event(video['id'],'media','ASR_FALLBACK','PyAV/Faster Whisper: '+str(exc)[:400])
        transcript={'words':[],'phrases':timeline['phrases'],'method':'tts_phrase_ffprobe_measured',
                    'asr_error':str(exc)[:600]}
    if not transcript and not video['test']:
        raise PreflightError('Nenhum alinhamento temporal disponível (ASR e TTS).')
    if transcript:db.atomic(work/'transcript.json',json.dumps(transcript,ensure_ascii=False))
    visual,visuals=montage(video,script,attempt,work)
    subtitle_file=work/'subtitles.ass'
    subtitles(script,style,subtitle_file,transcript,styled_hook=bool(hook_overlay))
    # Every used third-party clip is attributed visibly at the right timestamp.
    credit_events=[]
    for scene,item in zip(script.scenes,visuals):
        t=scene.start
        for part in item.get('segments',[]):
            duration=float(part.get('duration') or 0)
            if part.get('source_class')=='THIRD_PARTY':
                credit=(part.get('credits') or part.get('source') or '').strip()
                if credit:
                    credit=clean_subtitle('Fonte: '+credit)[:75].replace(',', ' ')
                    credit_events.append(f'Dialogue: 3,{subtitle_time(t)},{subtitle_time(t+duration)},Default,,0,0,0,,{{\\an9\\pos(990,150)\\fs25}}{credit}')
            t+=duration
    if credit_events:
        subtitle_file.write_text(subtitle_file.read_text('utf-8')+'\n'+'\n'.join(credit_events),encoding='utf-8')
    final=db.ROOT/'videos/final'/video['id']/f'attempt-{attempt:02d}.mp4'
    final.parent.mkdir(parents=True,exist_ok=True)
    temporary=work/'render.mp4'
    ff=binary('ffmpeg')
    args=[ff,'-y','-i',str(visual),'-i',str(audio)]
    # Use a transparent 24-pose expression per segment; each input remains immutable.
    from backend.personas import expression_file
    graph=['[0:v]ass=subtitles.ass[base]']
    current='base'
    if hook_overlay:
        # Generated from the live script and licensed inputs, not EPS example text.
        args+=['-loop','1','-framerate','30','-i',str(hook_overlay)]
        graph.append('[2:v]format=rgba,fade=t=in:st=0:d=0.16:alpha=1[titlefx]')
        graph.append("[base][titlefx]overlay=x=0:y=0:enable='between(t,0.10,2.90)'[styledbase]")
        current='styledbase'
    previous_emotion_by_speaker={}
    timeline_phrases=timeline.get('phrases',[])
    # Use actual TTS speaking boundaries (rather than estimated scene timestamps)
    # so that the character switches when the voice actually switches.
    sections=[]
    for phrase in timeline_phrases:
        if not sections or sections[-1]['speaker']!=phrase['speaker'] or sections[-1]['emotion']!=phrase['emotion']:
            sections.append({'speaker':phrase['speaker'],'emotion':phrase['emotion'],
                             'start':phrase['start'],'end':phrase['end']})
        else:sections[-1]['end']=phrase['end']
    if not sections:
        sections=[{'speaker':sc.speaker,'emotion':sc.emotion,'start':sc.start,'end':sc.end} for sc in script.scenes]
    pose_report=[]
    for idx,section in enumerate(sections):
        who=section['speaker']
        try:
            avatar,actual=expression_file(who,section['emotion'],previous_emotion_by_speaker.get(who))
        except (ValueError,OSError) as exc:
            raise PreflightError(f'Pose obrigatória indisponível para {who}: {exc}') from exc
        previous_emotion_by_speaker[who]=actual
        args+=['-loop','1','-framerate','1','-i',str(avatar)]
        input_index=idx+(3 if hook_overlay else 2)
        graph.append(f'[{input_index}:v]scale=720:850:force_original_aspect_ratio=decrease,format=rgba[avatar{idx}]')
        label=f'overlay{idx}'
        start,end=section['start'],section['end']
        side_x='38' if idx%2==0 else 'W-w-155'
        graph.append(f"[{current}][avatar{idx}]overlay=x={side_x}:y=1110+5*sin(2*PI*t/3):enable='between(t,{start:.3f},{end:.3f})'[{label}]")
        current=label
        pose_report.append({'speaker':who,'requested_emotion':section['emotion'],'emotion':actual,
                            'file':str(avatar.relative_to(db.ROOT)),'start':start,'end':end,'layout':'bust','side':'left' if idx%2==0 else 'right',
                            'scale_px':[720,850], 'safe_zone':'face_above_bottom_18_percent'})
    db.atomic(work/'pose-timeline.json',json.dumps(pose_report,ensure_ascii=False,indent=2))
    args+=['-filter_complex',';'.join(graph),'-map',f'[{current}]']
    args+=['-map','1:a:0','-t',str(script.duration),'-c:v','libx264','-preset','veryfast','-crf','22',
           '-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','192k',
           '-movflags','+faststart','-threads','2',str(temporary)]
    run(args,timeout=600,cwd=work)
    # Soundtrack is optional and never overwrites the original media library.
    from backend.audio_mix import mix
    try:
        mixed=mix(video['id'],temporary,work,script.duration)
    except IntegrationError as exc:
        raise PreflightError('Não foi possível mixar música/narração com os assets cadastrados: '+str(exc)) from exc
    os.replace(mixed,final)
    from backend.assets import count_usage
    count_usage(visuals)
    info=probe(final)
    # Make a real export cover from the final render; never a fabricated image.
    try:
        cover=final.parent/f'attempt-{attempt:02d}-cover.jpg'
        run([ff,'-y','-ss','1.0','-i',str(final),'-frames:v','1',
             '-q:v','3',str(cover)],timeout=25)
    except IntegrationError as exc:
        db.log_event(video['id'],'media','COVER_FAILED',str(exc)[:300])
    stream=next(s for s in info['streams'] if s['codec_type']=='video')
    db.artifact(video['id'],'editor',data={'executed':['cenário por cena','narracao','legendas','origem dos assets','H.264/AAC'],
        'ignored':[],'failures':[],'duration':float(info['format']['duration']),
        'resolution':[stream['width'],stream['height']],'codec':stream['codec_name'],
        'bytes':final.stat().st_size,'test_audio':bool(video['test']),
        'visual_manifest':f'handoff/{video["id"]}/visual-assets.json',
        'subtitle_timing':(transcript.get('method') if transcript else 'synthetic_test_only'),
        'audio_timeline':f'videos/processing/{video["id"]}/attempt-{attempt:02d}/audio-timeline.json'},
        files=[str(final.relative_to(db.ROOT)),f'handoff/{video["id"]}/visual-assets.json'],next_agent='avaliador')
    return final


def technical_check(path, expected_duration):
    failures = []
    try:
        info = probe(path)
        v = next((s for s in info['streams'] if s['codec_type'] == 'video'), {})
        a = next((s for s in info['streams'] if s['codec_type'] == 'audio'), {})
        if (v.get('width'), v.get('height')) != (1080, 1920) or v.get('codec_name') != 'h264':
            failures.append('Resolução ou codec inválido.')
        if a.get('codec_name') != 'aac':
            failures.append('Áudio AAC ausente.')
        duration = float(info.get('format', {}).get('duration', 0))
        if abs(duration - expected_duration) > .5:
            failures.append('Duração divergente do briefing.')
        run([binary('ffmpeg'), '-v', 'error', '-xerror', '-i', str(path), '-f', 'null', '-'], timeout=180)
        result = subprocess.run([binary('ffmpeg'), '-i', str(path), '-af', 'silencedetect=noise=-40dB:d=2', '-f', 'null', '-'], capture_output=True, timeout=180)
        # Planned voice-free outro is intentional and must not be a technical failure.
        begins=[float(v) for v in re.findall(rb'silence_start:\s*([0-9.]+)',result.stderr)]
        boundary=max(0,expected_duration-db.settings().narration_margin_seconds)
        if any(v < boundary-0.5 for v in begins):
            failures.append('Silêncio prolongado antes do fechamento planejado.')
        return {'valid': not failures, 'failures': failures, 'duration': duration, 'resolution': [v.get('width'), v.get('height')]}
    except (IntegrationError, ValueError, KeyError, subprocess.TimeoutExpired):
        return {'valid': False, 'failures': ['Arquivo inválido, ilegível ou não decodificável.']}


def samples(path, video_id):
    dest = db.ROOT / 'videos/processing' / video_id
    run([binary('ffmpeg'), '-y', '-i', str(path), '-vf', f'fps=1/{db.settings().sample_seconds},scale=270:480', '-frames:v', '12', str(dest / 'frame-%02d.jpg')])
    return sorted(dest.glob('frame-*.jpg'))


def transcript_check(path, script):
    transcript = transcribe(path)
    normalize = lambda s: re.sub(r'[^\w\s]', '', s.lower()).split()
    expected = normalize(' '.join(s.narration for s in script.scenes))
    actual = normalize(transcript['text'])
    match = SequenceMatcher(None, expected, actual).ratio()
    return {'language': transcript['language'], 'word_match': round(match, 3), 'recognized_words': len(actual),
            'valid': match >= .8 and transcript['language'] == 'pt', 'summary': transcript['text'][:1500]}
