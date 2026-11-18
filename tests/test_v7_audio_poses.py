"""V7 regressions: no false FFmpeg labels, exactly 72 poses, measurable audio."""
import json
import os
from pathlib import Path
from PIL import Image
from backend import media, core as db
from backend.contracts import Script, Scene, Settings
from backend.personas import expression_file,get_cast
from backend.audio_timeline import split_phrases


def test_pyav_pinned_compatible():
    text=(Path(__file__).resolve().parents[1]/'backend/requirements-video.txt').read_text()
    assert 'faster-whisper==1.2.1' in text
    assert 'av==18.1.0' in text


def test_quality_import_replaces_v7_sprite_placeholders():
    # The v8 release intentionally does not ship SVG-generated production sprites.
    from backend.pose_import import POSE_SLUGS
    assert len(POSE_SLUGS)==24 and len(set(POSE_SLUGS))==24
    root=Path(__file__).resolve().parents[1]
    source=(root/'scripts/generate_expressions.py').read_text('utf-8')
    assert 'Gerador SVG desativado' in source
    with Image.open(root/'templates/personas/dante_palma/portrait-quality.png') as im:
        assert im.mode=='RGBA' and im.width>=1024 and im.height>=1280
        assert im.getpixel((0,0))[3]==0


def test_expression_fallback_no_repetition():
    db.init_db()
    cast=get_cast()
    assert set(cast)>=set(('dante_palma','lia_varela','caio_rivas'))
    path,emotion=expression_file('dante_palma','neutro',previous='neutro')
    assert path.is_file() and emotion!='neutro'
    path2,emotion2=expression_file('dante_palma','unknown',previous='feliz')
    assert path2.is_file() and emotion2=='retrato_qualidade_unico'  # sem fingir 24 poses HD


def test_5_second_budget_schema():
    config=Settings(duration=45)
    assert config.narration_margin_seconds==5
    assert config.duration-config.narration_margin_seconds==40
    assert config.narration_lead_seconds==0.5


def test_split_phrases():
    assert split_phrases('Vamos conferir. O que aconteceu?')==['Vamos conferir.','O que aconteceu?']


def test_python_error_not_mislabeled(monkeypatch):
    class Process:
        returncode=1
        stderr=b'Traceback (most recent call last):\n  File "audio.py", line 3\nTypeError: open() got an unexpected keyword argument "metadata_errors"\n'
        stdout=b''
    monkeypatch.setattr(media.subprocess,'run',lambda *a,**k:Process())
    try:media.run(['python','-m','backend.transcription','x','y'])
    except Exception as exc:
        assert 'Python/PyAV' in str(exc)
        assert 'FFmpeg:' not in str(exc)
    else:assert False
