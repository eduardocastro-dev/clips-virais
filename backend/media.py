import json
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


def binary(name):
    executable = os.getenv(name.upper() + '_BIN') or shutil.which(name)
    if not executable:
        raise IntegrationError(f'{name} não instalado ou não encontrado no PATH.')
    return executable


def run(args, timeout=240, cwd=None):
    try:
        result = subprocess.run(args, capture_output=True, timeout=timeout, cwd=cwd)
    except subprocess.TimeoutExpired:
        raise IntegrationError('Processamento de mídia excedeu o timeout.') from None
    if result.returncode:
        # stderr from media programs is local, but keep it out of handoffs.
        db.atomic(db.ROOT / 'logs' / 'media-last-error.log', result.stderr.decode('utf-8', errors='replace')[-6000:])
        raise IntegrationError('Falha de processamento de mídia; consulte media-last-error.log local.')
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


def transcribe(path):
    """Optional local speech recognition. No transcript is sent wholesale to another agent."""
    result_path=db.ROOT/'cache'/('transcript-'+db.uid()+'.json')
    try:
        run([sys.executable,'-m','backend.transcription',str(path),str(result_path)],timeout=240)
        return json.loads(result_path.read_text('utf-8'))
    finally:
        result_path.unlink(missing_ok=True)


def subtitles(script, style, target, transcript=None):
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1080', 'PlayResY: 1920', '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             f'Style: Default,DejaVu Sans,{style["font_size"]},&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,2,90,90,330,1',
             'Style: Header,DejaVu Sans,65,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,90,90,240,1',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    hook='\\N'.join(textwrap.wrap(clean_subtitle(script.hook),24))
    lines.append(f'Dialogue: 0,0:00:00.00,0:00:03.00,Header,,0,0,0,,{{\\fad(100,100)}}{hook}')
    if script.cta:
        cta='\\N'.join(textwrap.wrap(clean_subtitle(script.cta),28))
        lines.append(f'Dialogue: 2,{subtitle_time(max(0,script.duration-3))},{subtitle_time(script.duration)},Header,,0,0,0,,{{\\an5\\pos(540,1350)\\fad(100,100)}}{cta}')
    for scene in script.scenes:
        text = '\\N'.join(textwrap.wrap(clean_subtitle(scene.text), 24))
        if scene.end>max(3,scene.start):
            lines.append(f'Dialogue: 0,{subtitle_time(max(3,scene.start))},{subtitle_time(scene.end)},Header,,0,0,0,,{{\\fad(150,150)}}{text}')
        # Narration is rendered per scene; phrase timings derive from its fitted duration.
        if transcript:
            continue
        words = clean_subtitle(scene.narration).split()
        chunks = [' '.join(words[i:i+6]) for i in range(0, len(words), 6)]
        for index, chunk in enumerate(chunks):
            start = scene.start + (scene.end - scene.start) * index / len(chunks)
            end = scene.start + (scene.end - scene.start) * (index + 1) / len(chunks)
            lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(end)},Default,,0,0,0,,{{\\fad(70,70)}}{chunk}')
    if transcript:
        words = transcript['words']
        for offset in range(0, len(words), 6):
            chunk = words[offset:offset+6]
            text = clean_subtitle(' '.join(w['text'] for w in chunk))
            lines.append(f'Dialogue: 1,{subtitle_time(chunk[0]["start"])},{subtitle_time(chunk[-1]["end"])},Default,,0,0,0,,{{\\fad(70,70)}}{text}')
    target.write_text('\n'.join(lines), encoding='utf-8')


def narration(script, work, test=False):
    files = []
    for index, scene in enumerate(script.scenes):
        raw = work / f'voice-{index}.wav'
        fitted = work / f'fitted-{index}.wav'
        duration = scene.end - scene.start
        if test:
            run([binary('ffmpeg'), '-y', '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000', '-t', str(duration), '-af', 'volume=0.05', str(raw)])
        else:
            model = os.getenv('PIPER_MODEL', '')
            if not model or not Path(model).is_file():
                raise IntegrationError('Configure uma voz Piper PT-BR licenciada em PIPER_MODEL.')
            result = subprocess.run([binary('piper'), '--model', model, '--output_file', str(raw)],
                                    input=scene.narration.encode(), capture_output=True, timeout=90)
            if result.returncode:
                raise IntegrationError('Falha na síntese Piper.')
        measured = float(probe(raw)['format']['duration'])
        ratio = measured / duration
        if not test and not .65 <= ratio <= 1.4:
            raise BriefingError('Narração não cabe na cena; revisar quantidade de palavras e timestamps.')
        run([binary('ffmpeg'), '-y', '-i', str(raw), '-af', f'atempo={max(.5,min(2,ratio))},apad,atrim=duration={duration},loudnorm=I=-16:TP=-1.5:LRA=11',
             '-ar', '48000', '-ac', '2', str(fitted)])
        files.append(fitted)
    (work / 'audio-list.txt').write_text('\n'.join(f"file '{p.name}'" for p in files), encoding='utf-8')
    run([binary('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', 'audio-list.txt', '-c:a', 'pcm_s16le', 'narration.wav'], cwd=work)
    return work / 'narration.wav'


def render(video, script: Script):
    work = db.ROOT / 'videos/processing' / video['id']
    work.mkdir(parents=True, exist_ok=True)
    style = template(script.template)
    audio = narration(script, work, bool(video['test']))
    transcript = transcribe(audio) if db.settings().transcription and not video['test'] else None
    if transcript:
        db.atomic(work / 'transcript.json', json.dumps(transcript, ensure_ascii=False))
    subtitles(script, style, work / 'subtitles.ass', transcript)
    final = db.ROOT / 'videos/final' / (video['id'] + '.mp4')
    temporary = work / 'render.mp4'
    raw = db.ROOT / 'videos/raw' / (video['id'] + '.mp4')
    args = [binary('ffmpeg'), '-y']
    if video['rights'] == 'AUTHORIZED' and raw.is_file():
        source_duration = float(probe(raw)['format']['duration'])
        for index, scene in enumerate(script.scenes):
            if scene.source_start + scene.end - scene.start > source_duration + .1:
                raise BriefingError('Corte excede a duração da mídia; devolver ao Escritor.')
            run([binary('ffmpeg'), '-y', '-ss', str(scene.source_start), '-i', str(raw), '-t', str(scene.end-scene.start),
                 '-an', '-vf', 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1',
                 '-r', '30', '-c:v', 'libx264', '-preset', 'veryfast', '-pix_fmt', 'yuv420p', '-threads', '2', str(work/f'cut-{index}.mp4')])
        (work/'cuts.txt').write_text('\n'.join(f"file 'cut-{i}.mp4'" for i in range(len(script.scenes))), encoding='utf-8')
        run([binary('ffmpeg'), '-y', '-f', 'concat', '-safe', '0', '-i', 'cuts.txt', '-c', 'copy', 'cuts.mp4'], cwd=work)
        args += ['-i', str(work/'cuts.mp4')]
        vf = 'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1'
    else:
        args += ['-f', 'lavfi', '-i', f'color=c={style["background"]}:s=1080x1920:r=30']
        vf = f'drawbox=x=60:y=120:w=8:h=1680:color={style["accent"]}:t=fill,drawbox=x=100:y=150:w=880:h=6:color={style["accent"]}:t=fill'
    args += ['-i', str(audio), '-vf', vf + ',ass=subtitles.ass', '-map', '0:v:0', '-map', '1:a:0',
             '-t', str(script.duration), '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '22', '-pix_fmt', 'yuv420p',
             '-r', '30', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-threads', '2', str(temporary)]
    run(args, timeout=600, cwd=work)
    os.replace(temporary, final)
    info = probe(final)
    video_stream = next(s for s in info['streams'] if s['codec_type'] == 'video')
    db.artifact(video['id'], 'editor', data={'executed': ['cenas', 'narração', 'legendas', 'template', 'H.264/AAC'],
        'ignored': [], 'failures': [], 'duration': float(info['format']['duration']),
        'resolution': [video_stream['width'], video_stream['height']], 'codec': video_stream['codec_name'],
        'bytes': final.stat().st_size, 'test_audio': bool(video['test']), 'subtitle_timing': 'whisper_words' if transcript else 'estimated_by_phrase'},
        files=[str(final.relative_to(db.ROOT))], next_agent='avaliador')
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
        if b'silence_start:' in result.stderr:
            failures.append('Silêncio prolongado detectado; revisar áudio.')
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
