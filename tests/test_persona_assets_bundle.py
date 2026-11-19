"""Character art shipped in the distribution must be usable by the actual renderer."""
from pathlib import Path
import json
import hashlib
from PIL import Image

from backend.persona_assets import ACCEPTED_QUALITY, PERSONAS
from backend.pose_import import POSE_SLUGS

PROJECT=Path(__file__).resolve().parents[1]


def test_three_complete_bundled_galleries():
    for slug in PERSONAS:
        base=PROJECT/'templates'/'personas'/slug
        folder=base/'expressions'
        manifest=json.loads((folder/'manifest.json').read_text('utf-8'))
        assert manifest['personagem']==slug
        assert manifest['quality'] in ACCEPTED_QUALITY
        assert len(manifest['images'])==24
        assert (base/'avatar.png').is_file()
        assert (base/'portrait-quality.png').is_file()
        for idx,item in enumerate(manifest['images'],1):
            assert item['index']==idx
            assert item['emotion']==POSE_SLUGS[idx-1]
            path=folder/item['file']
            assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']
            with Image.open(path) as picture:
                assert picture.mode=='RGBA' and picture.size==(1024,1536)
                assert all(picture.getpixel(c)[3]==0 for c in [(0,0),(1023,0),(0,1535),(1023,1535)])
                assert picture.getchannel('A').getextrema()[1]>0


def test_install_and_restore_masters(tmp_path,monkeypatch):
    from backend import core as db
    from backend.persona_assets import install_bundled_personas
    monkeypatch.setattr(db,'ROOT',tmp_path)
    first=install_bundled_personas()
    assert all('instalada' in msg for msg in first.values())
    for slug in PERSONAS:
        assert (tmp_path/'assets/personas'/slug/'avatar.png').is_file()
        assert (tmp_path/'assets/personas/_quality_master'/slug/'01_neutro.png').is_file()
    src=tmp_path/'assets/personas/lia_varela/expressions/02_feliz.png'
    master=tmp_path/'assets/personas/_quality_master/lia_varela/02_feliz.png'
    before=master.read_bytes()
    src.write_bytes(b'custom edited copy')
    second=install_bundled_personas()
    assert second['lia_varela'].startswith('galeria já instalada')
    assert src.read_bytes()==b'custom edited copy'
    assert master.read_bytes()==before
