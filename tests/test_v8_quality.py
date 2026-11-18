"""V8 anti-fake visual content, source extraction, and transparent pose import."""
import io
import os
import zipfile
from pathlib import Path
from PIL import Image
import pytest

from backend.editorial_style import screen_copy
from backend.source_frames import image_quality
from backend.pose_import import POSE_SLUGS,validate_png,import_poses
from backend import core as db


def test_editorial_badges_become_normal_text():
    assert screen_copy('Fato ou especulação?')=='Olha esse detalhe!'
    assert screen_copy('FATO OU FAKE?')=='Olha esse detalhe!'
    assert screen_copy('Vice City apareceu em cena.')=='Vice City apareceu em cena.'


def test_dedup_dark_and_motionless_frames(tmp_path):
    black=tmp_path/'black.png';Image.new('RGB',(300,300),'black').save(black)
    assert not image_quality(black,set())
    image=Image.new('RGB',(300,300),'white')
    for x in range(0,300,10):
        for y in range(0,300,10):
            if (x//10+y//10)%2:image.paste('purple',(x,y,x+10,y+10))
    path=tmp_path/'complex.png';image.save(path)
    previous=set();assert image_quality(path,previous)
    assert not image_quality(path,previous)


def test_individual_pose_must_have_real_alpha_and_resolution(tmp_path):
    bad=tmp_path/'bad.png';Image.new('RGBA',(1024,1280),(0,0,0,255)).save(bad)
    with pytest.raises(ValueError,match='fundo'):
        validate_png(bad)
    good=tmp_path/'good.png';im=Image.new('RGBA',(1024,1280),(0,0,0,0))
    im.paste((255,0,0,255),(200,200,800,1250));im.save(good)
    assert validate_png(good)==(1024,1280)


def test_zip_requires_24_individual_images(tmp_path):
    archive=tmp_path/'short.zip'
    with zipfile.ZipFile(archive,'w') as z:z.writestr('01_neutro.png',b'not a PNG')
    with pytest.raises(ValueError,match='24 PNGs'):
        import_poses('dante_palma',archive)


def test_bundle_quality_art_is_not_svg_placeholder():
    root=Path(__file__).resolve().parent.parent
    portrait=root/'templates/personas/dante_palma/portrait-quality.png'
    assert portrait.is_file()
    with Image.open(portrait) as image:
        assert image.mode=='RGBA'
        assert image.width>=1024 and image.height>=1280
        assert image.getpixel((0,0))[3]==0
