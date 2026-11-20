"""Validate and install the operator-supplied gta_studio_templates ZIP.

Canonical source is templates.json plus nine *real* PNG plates/fg files.
No hardcoded rendering coordinates. Installation is in persistent STUDIO_DATA.
"""
from __future__ import annotations
import io
import json
import os
import re
import shutil
import time
import zipfile
from pathlib import Path
from PIL import Image
from backend import core as db

IDS=[
 '01_gta_news','02_gta_theory','03_gta_comparison','04_gta_cinematic',
 '05_gta_facts','06_gta_reaction','07_radar_gta6_viral',
 '08_gta_em_detalhes','09_vice_city_talk_hype'
]
NAMES={
 'gta-news':'01_gta_news','gta-theory':'02_gta_theory',
 'gta-comparison':'03_gta_comparison','gta-cinematic':'04_gta_cinematic',
 'gta-facts':'05_gta_facts','gta-reaction':'06_gta_reaction',
 'gta-radar-viral':'07_radar_gta6_viral',
 'gta-detail-breakdown':'08_gta_em_detalhes',
 'gta-hype-reaction':'09_vice_city_talk_hype'
}
PACK_DIR=db.DATA/'gta_studio_templates'
MAX_ZIP=24*1024*1024
MAX_UNPACKED=75*1024*1024


def _validate_spec(data):
    layout=data.get('layout') or {}
    if layout.get('canvas')!=[1080,1920] or len(data.get('templates') or [])!=9:
        raise ValueError('templates.json deve descrever 9 templates 1080x1920.')
    if set(t.get('id') for t in data['templates'])!=set(IDS):
        raise ValueError('IDs de templates não correspondem ao pacote oficial.')
    for region in ('tv_screen','presenter_zone','subtitle_band','top_panel'):
        coords=layout.get(region)
        if not isinstance(coords,dict) or not all(
          isinstance(coords.get(k),int) for k in ('x','y','w','h')):
            raise ValueError('Região '+region+' inválida em templates.json.')
        if (coords['x']<0 or coords['y']<0 or coords['w']<=0 or
            coords['h']<=0 or coords['x']+coords['w']>1080 or
            coords['y']+coords['h']>1920):
            raise ValueError('Região '+region+' fora do canvas.')
    if layout.get('plate_offset_y')!=960:
        raise ValueError('O pacote precisa instalar o plate em y=960.')
    return data


def install_zip(content:bytes):
    if len(content)>MAX_ZIP:raise ValueError('ZIP de templates excede 24 MB.')
    try:archive=zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise ValueError('Pacote ZIP inválido.') from None
    all_files={}
    for item in archive.infolist():
        if item.is_dir():continue
        if item.file_size>20*1024*1024 or item.flag_bits&1:
            raise ValueError('Pacote contém arquivo grande demais ou criptografado.')
        name=Path(item.filename).name
        if item.filename.count('/')>1 or '..' in Path(item.filename).parts:
            raise ValueError('Caminho de arquivo inseguro no ZIP.')
        if name in all_files:raise ValueError('Nomes duplicados no pacote.')
        if not (name=='templates.json' or
                any(name==f'{key}_{suffix}.{ext}'
                    for key in IDS for suffix in ('plate','fg')
                    for ext in ('png','svg'))):
            # Preview sheets can be ignored but never executed.
            continue
        all_files[name]=item
    total=sum(item.file_size for item in all_files.values())
    if total>MAX_UNPACKED:raise ValueError('Pacote descompactado excede 75 MB.')
    if 'templates.json' not in all_files:
        raise ValueError('templates.json não encontrado.')
    try:manifest=_validate_spec(json.loads(archive.read(all_files['templates.json'])))
    except (ValueError,json.JSONDecodeError) as exc:
        raise ValueError('Manifesto de templates inválido: '+str(exc)) from None
    for t in manifest['templates']:
        for kind in ('plate','foreground'):
            name=t['files'][kind]
            expected=t['id']+('_plate.png' if kind=='plate' else '_fg.png')
            if name!=expected or name not in all_files:
                raise ValueError('Falta arquivo PNG obrigatório: '+expected)
            with Image.open(io.BytesIO(archive.read(all_files[name]))) as im:
                if im.size!=(1080,960) or im.mode!='RGBA':
                    raise ValueError(expected+' deve ser RGBA 1080x960.')
                if kind=='plate':
                    tv=manifest['layout']['tv_screen']
                    center=(tv['x']+tv['w']//2,tv['y']-960+tv['h']//2)
                    if not 0<=center[1]<960 or im.getpixel(center)[3]!=0:
                        raise ValueError('O plate não tem furo transparente na TV: '+expected)
    staging=db.DATA/('gta_studio_templates_staging_'+db.uid())
    staging.mkdir(parents=True,exist_ok=False)
    try:
        for name,item in all_files.items():
            (staging/name).write_bytes(archive.read(item))
        (staging/'installed.json').write_text(json.dumps({
            'at':time.time(),'ids':IDS,'version':'operator-pack-v1'
        },ensure_ascii=False),encoding='utf-8')
        PACK_DIR.mkdir(parents=True,exist_ok=True)
        # File-by-file updates preserve a valid old package if validation fails.
        for f in staging.iterdir():
            os.replace(f,PACK_DIR/f.name)
    finally:shutil.rmtree(staging,ignore_errors=True)
    return {'installed':True,'templates':IDS,'files':len(all_files)}


def auto_install():
    if (PACK_DIR/'installed.json').exists():return
    source=db.ROOT/'assets'/'gta_studio_templates.zip'
    if source.is_file() and source.stat().st_size<MAX_ZIP:
        install_zip(source.read_bytes())


def manifest():
    auto_install()
    file=PACK_DIR/'templates.json'
    if not file.is_file():return None
    try:return _validate_spec(json.loads(file.read_text('utf-8')))
    except (ValueError,OSError):return None


def selected(template):
    data=manifest()
    if not data:return None
    ident=NAMES.get(template)
    if not ident:return None
    entry=next(t for t in data['templates'] if t['id']==ident)
    return {'layout':data['layout'],'template':entry,
            'plate':PACK_DIR/entry['files']['plate'],
            'foreground':PACK_DIR/entry['files']['foreground'],
            'id':ident}


def status():
    item=manifest()
    return {'installed':bool(item),'template_count':len(item['templates']) if item else 0,
            'expected_ids':IDS,
            'hint':'Envie gta_studio_templates.zip em Configurações ou copie para assets/gta_studio_templates.zip.'}
