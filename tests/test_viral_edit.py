"""Regressions for short-form editing without weakening TTS/right validation."""
import json
import re
import shutil
import subprocess

import pytest

from backend import audio_mix, media
from backend.contracts import Script
from backend.viral_edit import caption_groups, camera_profile, overlay_window, short_cta


def sample_script():
    return Script(
        title='GTA 6 Brasil',hook='Olha esse detalhe no GTA 6!',
        description='Explicamos uma referência visual.', hashtags=['GTA6'],
        template='gta-news', duration=10, cta='E você, o que acha deste detalhe? Compartilhe sua opinião nos comentários!',
        scenes=[
            {'start':0,'end':5,'text':'O detalhe aparece','narration':'Olha o detalhe que aparece aqui.','source_id':'a'*32},
            {'start':5,'end':10,'text':'Veja a origem','narration':'A fonte explica o que vemos.','source_id':'a'*32},
        ]
    )


def test_caption_groups_are_measured_and_readable():
    input_words=[
        {'text':'Olha','start':0.5,'end':0.75},
        {'text':'esse','start':0.78,'end':0.95},
        {'text':'detalhe','start':0.98,'end':1.25},
        {'text':'incrível!','start':1.27,'end':1.60},
        {'text':'A','start':2.3,'end':2.5},
        {'text':'fonte','start':2.52,'end':2.9},
    ]
    groups=caption_groups({'words':input_words})
    assert len(groups)==2
    assert groups[0]['start']==.5
    assert len(groups[0]['words'])==4
    assert groups[1]['start']==2.3
    assert caption_groups({'phrases':[{'start':0,'end':3,'text':'sem alinhamento'}]})==[]
    assert caption_groups(None)==[]


def test_studio_cta_and_camera_modes_are_bounded():
    assert len(short_cta('Comente o que você achou dessa notícia, compartilhe com seus amigos e se inscreva!'))<=48
    assert overlay_window(.45) is None
    assert overlay_window(2.4)==(.32,1.9)
    assert [camera_profile(i) for i in range(3)]==['push_in','drift_left','drift_right']
    assert audio_mix.sfx_positions(30,[1,2,3,4,5,6,7,8,9])==[.22,3.0,6.0,9.0]


def test_subtitles_use_four_word_karaoke_instead_of_single_words(tmp_path):
    script=sample_script()
    words=[
        {'text':'Olha','start':.4,'end':.7},
        {'text':'esse','start':.74,'end':.91},
        {'text':'detalhe','start':.95,'end':1.16},
        {'text':'aqui!','start':1.18,'end':1.5},
    ]
    path=tmp_path/'subtitles.ass'
    media.subtitles(script,{'font_size':54,'badge':'RADAR GTA 6','highlight_color':'&H00F4FF&'},
                    path,transcript={'words':words})
    text=path.read_text('utf-8')
    assert r'\kf' in text
    assert len(re.findall(r'^Dialogue: 1,',text,re.MULTILINE))==1
    assert 'Olha' in text and 'aqui!' in text
    assert r'\pos(540,1000)' in text
    assert r'\pos(540,740)' in text
    assert len(short_cta(script.cta))<=48


def test_fallback_does_not_fabricate_word_level_alignment(tmp_path):
    script=sample_script()
    path=tmp_path/'fallback.ass'
    media.subtitles(script,{'font_size':54},path,
                    transcript={'words':[],'phrases':[{'start':.3,'end':4.2,
                    'text':'Esta frase tem um intervalo real medido pelo Piper.'}]})
    text=path.read_text('utf-8')
    assert 'Esta frase' in text
    assert r'\kf' not in text


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'),reason='FFmpeg ausente')
def test_voice_only_mix_is_still_mastered(tmp_path,monkeypatch):
    # Regression: earlier code returned the same -22 LUFS unmastered MP4.
    source=tmp_path/'quiet.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','lavfi','-i','color=c=black:s=216x384:r=15',
                    '-f','lavfi','-i','sine=frequency=440:sample_rate=48000',
                    '-t','2.2','-filter:a','volume=0.08','-c:v','libx264','-pix_fmt','yuv420p',
                    '-c:a','aac',str(source)],check=True,timeout=30)
    monkeypatch.setattr(audio_mix.db,'rows',lambda *args,**kwargs:[])
    mixed=audio_mix.mix('not-published',source,tmp_path,2.2)
    assert mixed!=source and mixed.is_file()
    assert (tmp_path/'sfx_map.json').is_file()
    report=json.loads((tmp_path/'sfx_map.json').read_text('utf-8'))
    assert report['target_integrated_lufs']==-14.0
    assert report['sfx']==[]
    info=media.probe(mixed)
    assert abs(float(info['format']['duration'])-2.2)<.25
