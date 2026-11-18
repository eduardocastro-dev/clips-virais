"""Optional rights-cleared music/SFX under voice, local FFmpeg only."""
from __future__ import annotations
from backend import core as db


def mix(video_id, path, work, duration):
    from backend import media, production_media
    sounds=db.rows("""SELECT * FROM assets WHERE media_type='audio' AND status='READY'
        AND rights_status='AUTHORIZED' AND COALESCE(active,1)=1 AND path IS NOT NULL
        AND category IN ('musica','efeito sonoro') ORDER BY COALESCE(usage_count,0),created DESC""")
    music=next((a for a in sounds if a['category']=='musica'),None)
    effects=next((a for a in sounds if a['category']=='efeito sonoro'),None)
    if not music and not effects:return path
    ff=media.binary('ffmpeg');cmd=[ff,'-hide_banner','-loglevel','error','-y','-i',str(path)]
    graph=['[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[voice]']
    selected=[];music_index=None;fx_index=None
    if music:
        copy=production_media.copy_original(db.safe_file(music['path']),video_id,'music-'+music['id'])
        cmd+=['-stream_loop','-1','-i',str(copy)];selected.append(music['id']);music_index=1
    if effects:
        copy=production_media.copy_original(db.safe_file(effects['path']),video_id,'effect-'+effects['id'])
        cmd+=['-i',str(copy)];selected.append(effects['id']);fx_index=2 if music else 1
    audio='[voice]'
    if music_index is not None:
        volume=db.settings().music_volume
        graph.append(f'[{music_index}:a]volume={volume:.3f}[music]')
        graph.append('[music][voice]sidechaincompress=threshold=0.045:ratio=8:attack=12:release=250[ducked]')
        graph.append('[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0[voicemusic]')
        audio='[voicemusic]'
    if fx_index is not None:
        graph.append(f'[{fx_index}:a]volume=0.18,adelay=900:all=1[sfx]')
        graph.append(f'{audio}[sfx]amix=inputs=2:duration=first:dropout_transition=0[withfx]')
        audio='[withfx]'
    graph.append(f'{audio}alimiter=limit=0.95[aout]')
    final=work/'soundtrack-mix.mp4'
    cmd+=['-filter_complex',';'.join(graph),'-map','0:v:0','-map','[aout]','-t',str(duration),
          '-c:v','copy','-c:a','aac','-b:a','192k','-movflags','+faststart',str(final)]
    media.run(cmd,timeout=300)
    for asset_id in selected:
        db.execute('UPDATE assets SET usage_count=COALESCE(usage_count,0)+1 WHERE id=:id',{'id':asset_id})
    return final
