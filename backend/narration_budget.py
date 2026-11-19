"""TTS word budgets: derive words/second from the installed Piper voice.

The budget is an editorial constraint, not an audio-duration measurement.
Only the audio_timeline ffprobe step verifies the actual resulting seconds.
"""
from __future__ import annotations
import hashlib
import json
import math
import subprocess
import tempfile
from pathlib import Path

_SAMPLE = ('Nesta edição vamos conhecer os detalhes mais interessantes da notícia. '
           'Veja o que aparece na gravação e entenda por que a comunidade está comentando este assunto.')
_DEFAULT_WPS = 2.5  # transparent fallback when a live Piper calibration cannot be performed


def word_count(text: str) -> int:
    return len(str(text).split())


def calibrated_wps(cast_member: dict, *, root: Path | None = None) -> tuple[float, str]:
    """Generate one short *real* Piper sample per installed voice/speed and cache its rate.

    Never claim the default rate is measured. A failed calibration never blocks
    an otherwise valid production; ffprobe still gates the eventual narration.
    """
    from backend import core as db, media
    root = root or db.ROOT
    model = Path(str(cast_member.get('voice_model') or ''))
    speed = float(cast_member.get('speed') or 1.0)
    if not model.is_file():
        return _DEFAULT_WPS, 'fallback_no_installed_voice'
    key = hashlib.sha256(f'{model.resolve()}:{model.stat().st_mtime_ns}:{speed}'.encode()).hexdigest()
    output = root/'cache'/'voice_calibration'/f'{key}.json'
    if output.exists():
        try:
            cached = json.loads(output.read_text('utf-8'))
            if 0.5 <= float(cached['words_per_second']) <= 6:
                return float(cached['words_per_second']), 'piper_measured_cached'
        except (OSError, ValueError, KeyError, TypeError):
            pass
    try:
        with tempfile.TemporaryDirectory(prefix='piper-rate-', dir=None) as tmp:
            target = Path(tmp)/'calibrate.wav'
            proc = subprocess.run([
                media.binary('piper'), '--model', str(model), '--length_scale',
                str(round(1.0/speed, 3)), '--output_file', str(target)
            ], input=_SAMPLE.encode('utf-8'), capture_output=True, timeout=120)
            if proc.returncode != 0 or not target.exists():
                raise RuntimeError(proc.stderr.decode('utf-8', 'replace')[-200:])
            seconds = float(media.probe(target)['format']['duration'])
            if seconds <= 0:
                raise ValueError('sample duration is zero')
            rate = word_count(_SAMPLE)/seconds
            if not 0.5 <= rate <= 6:
                raise ValueError('out-of-range voice rate')
        output.parent.mkdir(parents=True, exist_ok=True)
        db.atomic(output, json.dumps({'words_per_second': rate, 'voice_model':str(model),
                                      'speed':speed, 'sample_words':word_count(_SAMPLE)}))
        return rate, 'piper_measured'
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
        return _DEFAULT_WPS, 'fallback_calibration_failed'


def script_budget(duration: float, margin: float, cast: dict, scenes=None) -> dict:
    """Return min/target/max words with source of measured per-voice rate.

    `scenes` is optional for the initial Escritor. For the Redator, scene
    weights follow existing timestamps and speaker assignments.
    """
    target_seconds = max(0.0, float(duration) - float(margin))
    low_seconds = max(0.0, target_seconds - 2.0)
    rows = list(scenes or [])
    if rows:
        weights = [max(0.1,float(sc.end)-float(sc.start)) for sc in rows]
        total = sum(weights)
        members = [cast.get(sc.speaker, cast.get('dante_palma',{})) for sc in rows]
    else:
        weights, total = [1.0], 1.0
        members = [cast.get('dante_palma') or next(iter(cast.values()),{})]
    rates = []
    for member in members:
        rates.append(calibrated_wps(member))
    target_per = [max(1,round(target_seconds * duration_fraction/total * rate))
                  for duration_fraction,(rate,_) in zip(weights,rates)]
    min_per = [max(1,math.floor(low_seconds * duration_fraction/total * rate))
               for duration_fraction,(rate,_) in zip(weights,rates)]
    max_per = [max(1,math.ceil(target_seconds * duration_fraction/total * rate))
               for duration_fraction,(rate,_) in zip(weights,rates)]
    return {
        'speech_target_seconds':target_seconds,
        'speech_min_seconds':low_seconds,
        'total_words_min':sum(min_per),
        'total_words_target':sum(target_per),
        'total_words_max':sum(max_per),
        'words_by_scene_min':min_per,
        'words_by_scene_target':target_per,
        'words_by_scene_max':max_per,
        'voice_rates': [{'words_per_second':round(rate,4),'basis':basis}
                        for rate,basis in rates],
        'note':'Faixa de palavras calculada da voz; aprovação temporal depende do TTS e ffprobe reais.'
    }
