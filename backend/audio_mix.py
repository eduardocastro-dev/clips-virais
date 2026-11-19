"""Rights-cleared audio mix with audible narrator and reliable final mastering.

The previous pipeline returned the unmastered input when no licensed soundtrack
was selected. Real exports could end at -22.7 LUFS despite per-phrase TTS
normalization. This module always masters the final mix to -14 LUFS (TP -1.5)
without stretching, truncating, or changing the measured Piper timing.
"""
from __future__ import annotations
import json
from backend import core as db

TARGET_LUFS = -14.0
TARGET_TRUE_PEAK = -1.5


def sfx_positions(duration, events=None):
    """Cue only the opening and actual edit boundaries, not arbitrary 5s intervals."""
    candidates = [0.22] + [float(x) for x in (events or [])[2::3]]
    result = []
    for value in candidates:
        if 0 <= value <= float(duration) - .65 and not any(abs(value - prev) < .35 for prev in result):
            result.append(round(value, 3))
    return result[:7]


def mix(video_id, path, work, duration, events=None):
    from backend import media, production_media
    sounds = db.rows("""SELECT * FROM assets WHERE media_type='audio' AND status='READY'
        AND rights_status='AUTHORIZED' AND COALESCE(active,1)=1 AND path IS NOT NULL
        AND category IN ('musica','efeito sonoro') ORDER BY COALESCE(usage_count,0),created DESC""")
    # License proofs are mandatory; do not consume the first unverified track.
    sounds = [asset for asset in sounds if str(asset.get('evidence') or '').strip()]
    music = next((a for a in sounds if a['category'] == 'musica'), None)
    effects = next((a for a in sounds if a['category'] == 'efeito sonoro'), None)
    ff = media.binary('ffmpeg')
    cmd = [ff, '-hide_banner', '-loglevel', 'error', '-y', '-i', str(path)]
    # Moderate presence EQ and compression keep Piper intelligible and forward.
    graph = ['[0:a]highpass=f=80,equalizer=f=2500:t=q:w=1.2:g=1.5,'
             'acompressor=threshold=0.12:ratio=2.2:attack=12:release=110:makeup=1.3[voice]']
    selected = []
    music_index = None
    fx_index = None
    if music:
        copy = production_media.copy_original(db.safe_file(music['path']), video_id, 'music-' + music['id'])
        cmd += ['-stream_loop', '-1', '-i', str(copy)]
        selected.append(music['id'])
        music_index = 1
    if effects:
        copy = production_media.copy_original(db.safe_file(effects['path']), video_id, 'effect-' + effects['id'])
        cmd += ['-i', str(copy)]
        selected.append(effects['id'])
        fx_index = 2 if music else 1
    audio = '[voice]'
    if music_index is not None:
        volume = db.settings().music_volume
        graph.append(f'[{music_index}:a]volume={volume:.3f}[music]')
        graph.append('[music][voice]sidechaincompress=threshold=0.045:ratio=8:attack=12:release=250[ducked]')
        graph.append('[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0[voicemusic]')
        audio = '[voicemusic]'
    cue_times = sfx_positions(duration, events) if effects else []
    if fx_index is not None and cue_times:
        labels = ''.join(f'[fx{i}]' for i in range(len(cue_times)))
        graph.append(f'[{fx_index}:a]atrim=0:0.45,asetpts=PTS-STARTPTS,asplit={len(cue_times)}{labels}')
        delayed = []
        for i,second in enumerate(cue_times):
            graph.append(f'[fx{i}]volume=0.090,adelay={round(second * 1000)}:all=1[accent{i}]')
            delayed.append(f'[accent{i}]')
        graph.append(''.join(delayed) + f'amix=inputs={len(delayed)}:duration=longest:dropout_transition=0[sfx]')
        graph.append(f'{audio}[sfx]amix=inputs=2:duration=first:dropout_transition=0[withfx]')
        audio = '[withfx]'
    # IMPORTANT: normalize *after* mixing, even with no soundtrack or SFX.
    graph.append(f'{audio}loudnorm=I={TARGET_LUFS:g}:TP={TARGET_TRUE_PEAK:g}:LRA=9[aout]')
    final = work / 'soundtrack-mix.mp4'
    cmd += ['-filter_complex', ';'.join(graph), '-map', '0:v:0', '-map', '[aout]',
            '-t', str(duration), '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k',
            '-movflags', '+faststart', str(final)]
    media.run(cmd, timeout=300)
    manifest = {'target_integrated_lufs': TARGET_LUFS, 'target_true_peak_dbfs': TARGET_TRUE_PEAK,
                'mastering': 'voice_presence_compressor_and_final_loudnorm',
                'voice_is_priority': True, 'music_ducking': bool(music),
                'selected_music_id': music['id'] if music else None,
                'sfx': [{'asset_id':effects['id'], 'at_seconds':t, 'at_frame':round(t*30),
                         'license_evidence':effects['evidence'], 'volume_ratio':0.09}
                        for t in cue_times] if effects else []}
    db.atomic(work/'sfx_map.json', json.dumps(manifest, ensure_ascii=False, indent=2))
    for asset_id in selected:
        db.execute('UPDATE assets SET usage_count=COALESCE(usage_count,0)+1 WHERE id=:id', {'id':asset_id})
    return final
