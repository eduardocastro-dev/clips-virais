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
    """Readable cinematic captions from measured word timestamps or real TTS phrases."""
    from backend.viral_edit import caption_groups, short_cta
    scenario=bool(style.get('scenario_tv'))
    lines = ['[Script Info]', 'ScriptType: v4.00+', 'PlayResX: 1080', 'PlayResY: 1920', '[V4+ Styles]',
             'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding',
             f'Style: Default,DejaVu Sans,{max(46,min(68,int(style["font_size"])+6))},&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,5,2,2,90,90,850,1',
             'Style: Header,DejaVu Sans,64,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,4,1,8,90,90,255,1',
             'Style: Badge,DejaVu Sans,31,&H00FFFFFF,&H00FFFFFF,&H00101321,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,90,90,90,1',
             '[Events]', 'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text']
    badge = clean_subtitle(str(style.get('badge') or 'GTA 6')).upper()[:24]
    lines.append(fr'Dialogue: 0,0:00:00.00,0:00:02.25,Badge,,0,0,0,,{{\an8\pos(540,94)\fad(80,100)\1c&H00F4FF&}}★ {badge} ★')
    if not styled_hook:
        hook = r'\N'.join(textwrap.wrap(clean_subtitle(script.hook), 23)[:2 if scenario else 3])
        lines.append(fr'Dialogue: 0,0:00:00.16,0:00:02.40,Header,,0,0,0,,{{\an8\pos(540,{1660 if scenario else 245})\fad(90,130)\fscx104\fscy104}}{hook}')
    if script.cta:
        # The old three-second CTA at Y=1350 obscured the presenter and the video.
        cta = short_cta(clean_subtitle(script.cta))
        lines.append(f'Dialogue: 2,{subtitle_time(max(0,script.duration-2.1))},'
                     f'{subtitle_time(script.duration-.12)},Header,,0,0,0,,'
                     fr'{{\an5\pos(540,{1800 if scenario else 740})\fs47\fad(90,140)\bord5}}{cta}')
    for index, scene in enumerate(script.scenes):
        # Do not repeat the same full-screen headline through every scene.
        begin=max(2.55, float(scene.start)+.10)
        end=min(float(scene.end),begin+1.15)
        if end>begin+.20 and index>0 and not scenario:
            text=r'\N'.join(textwrap.wrap(clean_subtitle(scene.text),24)[:2])
            lines.append(f'Dialogue: 0,{subtitle_time(begin)},{subtitle_time(end)},'
                         fr'Header,,0,0,0,,{{\an8\pos(540,248)\fs49\fad(100,120)}}{text}')
    groups=caption_groups(transcript)
    if groups:
        keyword_color = str(style.get('highlight_color') or '&H00F4FF&')
        if not keyword_color.startswith('&H') or not keyword_color.endswith('&'):
            keyword_color='&H00F4FF&'
        for group in groups:
            start=max(0., float(group['start']))
            end=min(float(script.duration),float(group['end'])+.11)
            if end<=start:
                continue
            syllables=[]
            for wi,item in enumerate(group['words']):
                # Karaoke advances on *real* word boundaries, with silent gaps.
                next_start=(group['words'][wi+1]['start'] if wi+1<len(group['words'])
                            else float(item['end']))
                centis=max(1,round((max(float(item['end']),float(next_start))-
                                     (start if wi==0 else float(item['start'])))*100))
                syllables.append(r'{\kf'+str(centis)+'}'+clean_subtitle(item['text']))
            joined=' '.join(syllables)
            effect=r'\an2\pos(540,1000)\bord5\shad2\fad(60,80)'+r'\1c'+keyword_color
            effect+=r'\2c&H00FFFFFF&'
            lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(end)},Default,,0,0,0,,'
                         '{'+effect+'}'+joined)
    elif transcript and transcript.get('phrases'):
        # Only phrase-level durations were measured by Piper + ffprobe: never invent
        # exact individual word timestamps. Keep lines readable where possible.
        for phrase in transcript['phrases']:
            try:
                start,end=float(phrase['start']),float(phrase['end'])
            except (KeyError,TypeError,ValueError):
                continue
            text=clean_subtitle(str(phrase.get('text') or '')).strip()
            if not text or end<=start:
                continue
            wrapped=textwrap.wrap(text, 26 if scenario else 28)
            if len(wrapped)>(2 if scenario else 3):
                wrapped=wrapped[:2 if scenario else 3]
                wrapped[-1]=wrapped[-1].rstrip(' ,.;')+'…'
            words=r'\N'.join(wrapped)
            lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(min(end,script.duration))},'
                         'Default,,0,0,0,,{\\an2\\pos(540,1000)\\fs49\\fad(70,70)}'+words)
    elif not transcript:
        # Test-only synthetic narration keeps prior approximate scene text.
        for scene in script.scenes:
            words=clean_subtitle(scene.narration).split()
            chunks=[' '.join(words[i:i+4]) for i in range(0,len(words),4)]
            for i,chunk in enumerate(chunks):
                start=scene.start+(scene.end-scene.start)*i/max(1,len(chunks))
                end=scene.start+(scene.end-scene.start)*(i+1)/max(1,len(chunks))
                lines.append(f'Dialogue: 1,{subtitle_time(start)},{subtitle_time(end)},'
                             'Default,,0,0,0,,{\\an2\\pos(540,1000)\\fad(60,70)}'+chunk)
    content='\n'.join(lines)
    if scenario:
        from backend.template_pack import selected
        package=selected(script.template)
        if package:
            band=package['layout']['subtitle_band']
            y=band['y']+band['h']//2
            content=content.replace(r'\pos(540,1000)',r'\pos(540,'+str(y)+')')
        else:
            content=content.replace(r'\pos(540,1000)',r'\pos(540,1530)')
    target.write_text(content, encoding='utf-8')


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
    from backend.scenarios import template_for
    scenario=bool(template_for(script.template))
    style['scenario_tv']=scenario
    # Mandatory input check BEFORE invoking TTS, FFmpeg or evaluator.
    from backend.assets import mandatory_assets, MissingAssetsError, sync_library
    sync_library()
    missing=mandatory_assets(script=script)
    if scenario and 'assets/gameplay/' in missing:
        from backend.source_preview import ensure
        if ensure(video):
            missing.remove('assets/gameplay/')
    if scenario:
        # Missing the operator's nine-template ZIP is a missing prerequisite,
        # not a transient editor failure. Pause before costly TTS/FFmpeg/LLM
        # work and allow the operator to upload the real licensed package.
        from backend.template_pack import selected
        if not selected(script.template):
            missing.append('assets/gta_studio_templates.zip')
    if missing:
        detail=('Envie gta_studio_templates.zip em Configurações > Templates '
                'ou copie para assets/gta_studio_templates.zip.'
                if 'assets/gta_studio_templates.zip' in missing else '')
        raise MissingAssetsError(missing,detail=detail)
    from backend.text_styles import active_style, render_hook
    chosen_text_style=active_style()
    hook_overlay=(render_hook(script.hook,work/'text-style-hook.png',chosen_text_style)
                  if chosen_text_style and not scenario else None)
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
    rim=[]
    if scenario:
        for scene_visual in visuals:
            for segment in scene_visual.get('segments',[]):
                sampled=(segment.get('tv_slot') or {}).get('screen_tint_rgb')
                if isinstance(sampled,list) and len(sampled)==3:
                    rim.append(sampled)
    tint=[sum(p[i] for p in rim)/len(rim) for i in range(3)] if rim else None
    rim_filter=(',colorbalance=rs={:.3f}:gs={:.3f}:bs={:.3f}'.format(
        *(max(-.10,min(.10,(channel-127)/127*.10)) for channel in tint))
        if tint else '')
    subtitle_file=work/'subtitles.ass'
    subtitles(script,style,subtitle_file,transcript,styled_hook=bool(hook_overlay))
    # Every used third-party clip is attributed visibly at the right timestamp.
    credit_events=[]
    for scene,item in zip(script.scenes,visuals):
        t=scene.start
        for part in item.get('segments',[]):
            duration=float(part.get('duration') or 0)
            if part.get('source_class')=='THIRD_PARTY' and not scenario:
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
    graph=['[0:v]format=rgba[base]'] if scenario else ['[0:v]ass=subtitles.ass[base]']
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
        if scenario:
            from backend.template_pack import selected
            packed=selected(video['template'])
            if not packed:
                raise PreflightError('Pacote de templates não instalado.')
            z=packed['layout']['presenter_zone']
            graph.append(f'[{input_index}:v]scale={z["w"]}:{z["h"]}:'
                         f'force_original_aspect_ratio=decrease,'
                         f'format=rgba{rim_filter}[avatar{idx}]')
        else:
            graph.append(f'[{input_index}:v]scale=880:1010:force_original_aspect_ratio=decrease,format=rgba[avatar{idx}]')
        label=f'overlay{idx}'
        start,end=section['start'],section['end']
        side_x=(str(z['x'])+'+('+str(z['w'])+'-w)/2') if scenario else ('38' if idx%2==0 else 'W-w-155')
        pose_y=str(z['y']) if scenario else '1110+9*sin(2*PI*t/2.7)'
        graph.append(f"[{current}][avatar{idx}]overlay=x={side_x}:y={pose_y}:enable='between(t,{start:.3f},{end:.3f})'[{label}]")
        current=label
        pose_report.append({'speaker':who,'requested_emotion':section['emotion'],'emotion':actual,
                            'file':str(avatar.relative_to(db.ROOT)),'start':start,'end':end,'layout':'bust','side':'left' if idx%2==0 else 'right',
                            'scale_px':[z['w'],z['h']] if scenario else [880,1010],
                             'safe_zone':'presenter_zone_from_templates_json' if scenario else 'face_above_bottom_18_percent'})
    db.atomic(work/'pose-timeline.json',json.dumps(pose_report,ensure_ascii=False,indent=2))
    if scenario:
        # Full foreground remains over alpha presenter, below subtitles.
        from backend.template_pack import selected
        pack=selected(video['template'])
        if not pack:raise PreflightError('Pacote de templates não instalado.')
        args+=['-loop','1','-framerate','30','-i',str(pack['foreground'])]
        fg_index=len(sections)+(3 if hook_overlay else 2)
        graph.append(f'[{fg_index}:v]format=rgba[foreground]')
        graph.append(f'[{current}][foreground]overlay=x=0:y={pack["layout"]["plate_offset_y"]}:shortest=1[fgcombined]')
        current='fgcombined'
        graph.append(f'[{current}]ass=subtitles.ass[captioned]')
        current='captioned'
    args+=['-filter_complex',';'.join(graph),'-map',f'[{current}]']
    args+=['-map','1:a:0','-t',str(script.duration),'-c:v','libx264','-preset','veryfast','-crf','22',
           '-pix_fmt','yuv420p','-r','30','-c:a','aac','-b:a','192k',
           '-movflags','+faststart','-threads','2',str(temporary)]
    run(args,timeout=600,cwd=work)
    # Soundtrack is optional and never overwrites the original media library.
    from backend.audio_mix import mix
    try:
        # Align licensed SFX to actual montage cuts, not an arbitrary timer.
        cut_events=[]
        elapsed=0.
        for scene_visual in visuals:
            for segment in scene_visual.get('segments',[]):
                elapsed+=float(segment.get('duration') or 0)
                cut_events.append(round(elapsed,3))
        mixed=mix(video['id'],temporary,work,script.duration,events=cut_events[:-1])
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
