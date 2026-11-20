"""Upload ZIP scenario validation and non-hardcoded layout integration."""
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image,ImageDraw
from backend import core as db
from backend import template_pack as pack
from backend.scenario_renderer import render_segment


def sample_package():
    layout={
      'canvas':[1080,1920],
      'top_panel':{'x':0,'y':0,'w':1080,'h':960},
      'tv_screen':{'x':340,'y':1015,'w':400,'h':225},
      'presenter_zone':{'x':140,'y':1290,'w':800,'h':470},
      'subtitle_band':{'x':140,'y':1560,'w':800,'h':140},
      'plate_offset_y':960
    }
    manifest={'layout':layout,'templates':[]}
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for ident in pack.IDS:
            manifest['templates'].append({'id':ident,
                'files':{'plate':ident+'_plate.png','foreground':ident+'_fg.png'},
                'top_panel':{'mode':'single'}})
            for kind in ('plate','fg'):
                picture=Image.new('RGBA',(1080,960),(18,28,44,255)
                                  if kind=='plate' else (0,0,0,0))
                if kind=='plate':
                    ImageDraw.Draw(picture).rectangle((340,55,740,280),
                                                    fill=(0,0,0,0))
                buffer=io.BytesIO();picture.save(buffer,format='PNG')
                z.writestr('gta_studio_templates/'+ident+'_'+kind+'.png',
                           buffer.getvalue())
        z.writestr('gta_studio_templates/templates.json',json.dumps(manifest))
    return output.getvalue()


def test_package_install_reads_operator_layout_and_pngs(monkeypatch,tmp_path,client):
    monkeypatch.setattr(pack,'PACK_DIR',db.DATA/('pack-'+tmp_path.name))
    content=sample_package()
    response=client.post('/api/templates/package',
                         files={'file':('gta_studio_templates.zip',content,'application/zip')})
    assert response.status_code==200,response.text
    assert response.json()['templates']==pack.IDS
    scene=pack.selected('gta-news')
    assert scene['layout']['tv_screen']=={'x':340,'y':1015,'w':400,'h':225}
    assert scene['foreground'].exists()
    assert pack.status()['template_count']==9
    assert client.get('/api/templates/package').json()['installed']


def test_package_rejects_zip_path_traversal(monkeypatch,tmp_path):
    monkeypatch.setattr(pack,'PACK_DIR',db.DATA/('pack-'+tmp_path.name))
    with zipfile.ZipFile(io.BytesIO(sample_package())):
        pass
    raw=io.BytesIO()
    with zipfile.ZipFile(raw,'w') as z:
        z.writestr('../outside/templates.json','{}')
    with pytest.raises(ValueError):
        pack.install_zip(raw.getvalue())
    assert not (tmp_path/'outside').exists()


def test_render_uses_package_tv_hole_and_has_no_default_credit(monkeypatch,tmp_path):
    monkeypatch.setattr(pack,'PACK_DIR',db.DATA/('pack-'+tmp_path.name))
    pack.install_zip(sample_package())
    source=db.ROOT/'assets'/'test-news-image.png'
    Image.new('RGB',(640,360),(14,26,50)).save(source)
    from backend import media
    calls=[]
    def fake_run(args,timeout):
        calls.append(args)
        Path(args[-1]).write_bytes(b'render')
    monkeypatch.setattr(media,'run',fake_run)
    video={'id':'a'*32,'template':'gta-news','metadata':'{}'}
    segment={'path':str(source.relative_to(db.ROOT)),'rights_status':'AUTHORIZED'}
    output=tmp_path/'test.mp4'
    result=render_segment('ffmpeg',video,segment,3,output,tmp_path,0)
    assert result['tv_bounds']==[340,1015,740,1240]
    assert result['caption_band']['y']==1560
    command=' '.join(calls[0])
    assert 'overlay=x=0:y=960' in command
    assert 'overlay=x=340:y=1015' in command
    assert 'FONTE:' not in command
    assert result['onscreen_credit_drawn'] is False
    assert result['foreground_path'].endswith('01_gta_news_fg.png')
