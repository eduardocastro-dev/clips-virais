"""Local source-video analysis for *authorized* long-form media.

FFmpeg scene-change sampling + optional local Whisper provide timecoded evidence to
an existing OmniRoute writer. It is not a copyright check or a promise that an
interesting event was detected. Public links are never downloaded here.
"""
import json
import re
import subprocess
from pathlib import Path

from backend import core as db
from backend.integrations import IntegrationError

MAX_SOURCE_SECONDS = 600
MAX_CLIP_SECONDS = 45


def scene_boundaries(path: Path, source_seconds: float) -> list[float]:
    """Sample cut transitions without downloading third-party models."""
    from backend import media
    command = [media.binary('ffmpeg'), '-hide_banner', '-nostdin', '-v', 'info',
               '-i', str(path), '-t', str(min(source_seconds, MAX_SOURCE_SECONDS)),
               '-an', '-vf', r'fps=2,select=gt(scene\,0.32),showinfo', '-f', 'null', '-']
    try:
        completed = subprocess.run(command, capture_output=True, timeout=120)
        if completed.returncode:
            return []
        numbers = [float(value) for value in re.findall(rb'pts_time:([0-9]+(?:\.[0-9]+)?)', completed.stderr)
                   if float(value) < source_seconds - 2]
        return sorted(set(round(n, 2) for n in numbers if n >= 2))[:80]
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return []


def speech_excerpts(path: Path) -> list[dict]:
    """Optional; never fail the video if Whisper isn't installed or can't transcribe gameplay."""
    if not db.settings().transcription:
        return []
    from backend import media
    try:
        transcription = media.transcribe(path, auto_language=True)
        words = transcription.get('words') or []
    except (IntegrationError, ValueError, KeyError):
        return []
    excerpts: list[dict] = []
    batch: list[dict] = []
    for word in words:
        if len(excerpts) >= 25:
            break
        if batch and (float(word['start']) - float(batch[0]['start']) >= 12 or len(batch) >= 32):
            excerpts.append({'start': round(float(batch[0]['start']), 1),
                             'end': round(float(batch[-1]['end']), 1),
                             'text': ' '.join(str(w['text']) for w in batch)[:330]})
            batch = []
        batch.append(word)
    if batch and len(excerpts) < 25:
        excerpts.append({'start': round(float(batch[0]['start']), 1),
                         'end': round(float(batch[-1]['end']), 1),
                         'text': ' '.join(str(w['text']) for w in batch)[:330]})
    return excerpts


def sample_frames(path: Path, source_seconds: float, video_id: str, cuts: list[float]) -> list[dict]:
    """Bounded local thumbnails for optional OmniRoute vision; never sends full video."""
    from backend import media
    directory = db.ROOT / 'videos/processing' / video_id
    directory.mkdir(parents=True, exist_ok=True)
    positions = sorted(set(round(max(1., min(source_seconds - 1, t)), 2) for t in (
        [source_seconds * f for f in (.12,.28,.45,.65,.85)] + cuts[::max(1,len(cuts)//3)][:3])))[:8]
    frames = []
    for i, at in enumerate(positions):
        target = directory / f'candidate-{i:02}.jpg'
        try:
            media.run([media.binary('ffmpeg'), '-nostdin', '-y', '-ss', str(at), '-i', str(path),
                       '-frames:v', '1', '-vf', 'scale=360:640:force_original_aspect_ratio=decrease',
                       '-q:v', '5', str(target)],timeout=25)
            if target.is_file() and target.stat().st_size:
                frames.append({'second':at,'path':str(target.relative_to(db.ROOT))})
        except IntegrationError:
            continue
    return frames


def analyze(path: Path, source_seconds: float, clip_seconds: int, *, video_id: str) -> dict:
    if source_seconds <= MAX_CLIP_SECONDS:
        return {}
    clip_seconds = max(10, min(int(clip_seconds), MAX_CLIP_SECONDS))
    boundaries = scene_boundaries(path, source_seconds)
    frames = sample_frames(path, source_seconds, video_id, boundaries)
    # No false claims of action/emotion: scene cuts are only potential points.
    analysis = {'source_seconds': round(source_seconds, 2), 'target_seconds': clip_seconds,
                'scene_cuts_seconds': boundaries, 'speech_excerpts': speech_excerpts(path),
                'frames': frames,
                'method': 'ffmpeg_scene_changes + optional_local_whisper + omniroute_writer',
                'rights': 'AUTHORIZED',
                'guidance': 'Escolher momentos interessantes e distintos a partir dos timestamps. '
                            'Evitar introduções, menus, pausas e repetição quando a evidência permitir. '
                            'Não inventar acontecimentos não visíveis na fonte.'}
    db.atomic(db.ROOT / 'handoff' / video_id / 'highlights.json', json.dumps(analysis, ensure_ascii=False, indent=2))
    return analysis


def fit_cuts(script, analysis: dict) -> list[dict]:
    """Validate AI offsets; if omitted/unsafe use spread-out scene cuts.

    Do not modify an authorized manual cut plan. Returns an auditable EDL.
    """
    if not analysis:
        return []
    duration = float(analysis['source_seconds'])
    cuts = [float(c) for c in analysis.get('scene_cuts_seconds', [])]
    used: list[tuple[float, float]] = []
    decisions = []
    for i, scene in enumerate(script.scenes):
        length = round(scene.end - scene.start, 2)
        if length > duration:
            raise IntegrationError('A cena é maior que o vídeo de origem.')
        proposed = float(scene.source_start)
        fits = (0 <= proposed <= duration - length + 0.01 and
                all(proposed >= e + 0.5 or proposed + length <= s - 0.5 for s, e in used))
        # Pydantic defaults source_start to zero; repeated zeros are not meaningful montage.
        if not fits or (i > 0 and abs(proposed) < 0.01):
            target = duration * (i + 0.5) / len(script.scenes)
            eligible = [max(0., min(c, duration - length)) for c in cuts]
            eligible += [max(0., min(target - length / 2, duration - length)),
                         max(0., min(duration * i / len(script.scenes), duration - length))]
            choices = [v for v in eligible if all(v >= e + 0.5 or v + length <= s - 0.5 for s, e in used)]
            if not choices:
                raise IntegrationError('Não foi possível escolher trechos distintos na origem.')
            proposed = min(choices, key=lambda start: abs((start + length / 2) - target))
            method = 'fallback_ffmpeg_scenes'
        else:
            method = 'omniroute_script'
        scene.source_start = round(proposed, 2)
        used.append((scene.source_start, scene.source_start + length))
        decisions.append({'output_start': scene.start, 'output_end': scene.end,
                          'source_start': scene.source_start, 'source_end': round(scene.source_start + length, 2),
                          'selection': method})
    return decisions
