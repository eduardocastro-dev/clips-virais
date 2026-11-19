"""Text-style ZIP/font intake, license, preview and hook render regression tests."""
import io
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from backend import core as db, media
from backend.text_styles import import_style, active_style, activate, deactivate, preview, render_hook
from backend.contracts import Script


def sample_pack():
    out=io.BytesIO()
    preview_bytes=io.BytesIO()
    Image.new('RGB',(120,60),'white').save(preview_bytes,'JPEG')
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('../not-extracted.eps',b'%!PS-Adobe-3.1 EPSF-3.0\n%%BoundingBox: 0 0 100 100\n')
        z.writestr('preview.jpg',preview_bytes.getvalue())
    return out.getvalue()


def test_license_is_required_and_archive_not_extracted(client,tmp_path):
    with pytest.raises(ValueError,match='licença'):
        import_style(name='California',filename='style.zip',content=sample_pack(),
                     source_class='THIRD_PARTY',evidence='',theme='california_sunset')
    result=import_style(name='California',filename='style.zip',content=sample_pack(),
                        source_class='THIRD_PARTY',evidence='Licença comercial registrada para uso',
                        theme='california_sunset')
    assert not (db.ROOT/'not-extracted.eps').exists()
    assert active_style() is None
    assert preview(result['id']).is_file()
    activate(result['id'])
    png=render_hook('GTA 6: NOVOS DETALHES!',tmp_path/'title.png',active_style())
    with Image.open(png) as image:
        assert image.size==(1080,1920) and image.mode=='RGBA'
    deactivate()
    assert active_style() is None


def test_bad_zip_and_fake_font_are_rejected():
    with pytest.raises(ValueError):
        import_style(name='Invalid',filename='invalid.zip',content=b'not zip',
                     source_class='THIRD_PARTY',evidence='Licença comercial',theme='neon_gaming')
    with pytest.raises(ValueError):
        import_style(name='Invalid',filename='fake.ttf',content=b'not a font',
                     source_class='THIRD_PARTY',evidence='Licença comercial',theme='neon_gaming')


def test_upload_preview_and_activation(client):
    r=client.post('/api/text-styles/upload',
                  files={'file':('style.zip',sample_pack(),'application/zip')},
                  data={'name':'Retro','theme':'vintage_shadow',
                        'source_class':'THIRD_PARTY','evidence':'Licença de uso comercial declarada'})
    assert r.status_code==200,r.text
    ident=r.json()['id']
    assert client.get('/api/text-styles').json()['active_id']==''
    assert client.get(f'/api/text-styles/{ident}/preview').status_code==200
    assert client.post(f'/api/text-styles/{ident}/activate').json()['active_id']==ident
    assert client.post('/api/text-styles/deactivate').json()['active_id']==''


def test_subtitles_remain_intact_without_effect(tmp_path):
    script=Script(title='Título',hook='Gancho original',description='',hashtags=[],
                  template='gta-news',duration=10,
                  scenes=[{'start':0,'end':5,'text':'Parte 1','narration':'Uma frase','source_id':'a'*32},
                          {'start':5,'end':10,'text':'Parte 2','narration':'Outra frase','source_id':'a'*32}])
    old=tmp_path/'old.ass'
    new=tmp_path/'new.ass'
    media.subtitles(script,{'font_size':54},old)
    media.subtitles(script,{'font_size':54},new,styled_hook=True)
    assert 'Gancho original' in old.read_text()
    assert 'Gancho original' not in new.read_text()
    assert 'Uma frase' in new.read_text()
