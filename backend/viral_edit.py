"""Deterministic motion/caption plan for energetic GTA Studio short-form editing.

Adapt *principles* of high-performing short-form storytelling; never reproduce
an identifiable creator's edit, visual identity, audio, or source material.
All timing is derived from actual measured/recognized speech, not guessed WPS.
"""
from __future__ import annotations
import math
import re

EDITORIAL_MODES = {
    'gta-news': 'radar',
    'gta-radar-viral': 'radar',
    'gta-facts': 'details',
    'gta-theory': 'details',
    'gta-comparison': 'details',
    'gta-detail-breakdown': 'details',
    'gta-reaction': 'reaction',
    'gta-hype-reaction': 'reaction',
    'gta-cinematic': 'cinematic',
}
CAPTION_MAX_WORDS = 4
CAPTION_MAX_CHARS = 31
CAPTION_BREAK_GAP = .42


def editorial_mode(template: str) -> str:
    return EDITORIAL_MODES.get(str(template), 'radar')


def short_cta(cta: str, max_chars: int = 48) -> str:
    """Only the verified script's CTA, without creating a new factual claim."""
    value = re.sub(r'\s+', ' ', str(cta or '')).strip()
    if len(value) <= max_chars:
        return value
    words = value.split()
    out = ''
    for word in words:
        candidate = (out + ' ' + word).strip()
        if len(candidate) > max_chars:
            break
        out = candidate
    return out.rstrip(' ,.;:-') or value[:max_chars].rstrip(' ,.;:-')


def caption_groups(transcript: dict | None) -> list[dict]:
    """Chunk *measured* aligned words for continuous, readable 3–4 word captions.

    Does not invent timestamps, split speech based on nominal script duration,
    or claim word-level precision for phrase-level fallbacks.
    """
    if not transcript or not transcript.get('words'):
        return []
    words = []
    for item in transcript['words']:
        try:
            start, end = float(item['start']), float(item['end'])
        except (KeyError, ValueError, TypeError):
            continue
        text = re.sub(r'\s+', ' ', str(item.get('text') or '')).strip()
        if not text or not math.isfinite(start) or not math.isfinite(end):
            continue
        if start < 0 or end <= start:
            continue
        words.append({'text':text, 'start':start, 'end':end})
    words.sort(key=lambda item:(item['start'],item['end']))
    groups, buffer = [], []
    for item in words:
        char_total = len(' '.join(x['text'] for x in buffer+[item]))
        gap = item['start'] - buffer[-1]['end'] if buffer else 0
        end_sentence = bool(buffer and buffer[-1]['text'].endswith(('.', '!', '?')))
        if buffer and (len(buffer) >= CAPTION_MAX_WORDS or char_total > CAPTION_MAX_CHARS or
                       gap > CAPTION_BREAK_GAP or end_sentence):
            groups.append({'start':buffer[0]['start'], 'end':buffer[-1]['end'], 'words':buffer})
            buffer = []
        buffer.append(item)
    if buffer:
        groups.append({'start':buffer[0]['start'], 'end':buffer[-1]['end'], 'words':buffer})
    return groups


def overlay_window(segment_seconds: float) -> tuple[float,float] | None:
    """A news-card should accent the main imagery, not obscure the full shot."""
    seconds = float(segment_seconds)
    begin = .32
    end = min(1.90, seconds - .16)
    if end - begin < .50:
        return None
    return begin, end


def camera_profile(segment_index: int) -> str:
    """Alternating *subtle* virtual camera drift, with no double-strong moves."""
    return ('push_in', 'drift_left', 'drift_right')[segment_index % 3]


def first_three_seconds(script) -> dict:
    """Traceable hook check; never label an unsupported claim as confirmed."""
    hook = re.sub(r'\s+', ' ', str(getattr(script, 'hook', '') or '')).strip()
    return {'hook':hook, 'start':0.10, 'end':min(2.25,float(script.duration)),
            'mode':editorial_mode(script.template)}
