"""Import creator-supplied pose art, without upscaling a low-resolution contact sheet.

The 4x6 sheet is a visual reference, not automatically 24 high-resolution masters.
24 individual high-resolution transparent PNGs are required for production import.
"""
from __future__ import annotations
import hashlib
import io
import json
import re
import shutil
import tempfile
import zipfile
from pathlib import Path
from PIL import Image
from backend import core as db

PERSONAS={'dante_palma','lia_varela','caio_rivas'}
POSE_SLUGS=['neutro','feliz','rindo','empolgado','surpreso','chocado','confuso',
 'pensativo','cetico','irritado','triste','entediado','apontando_direita','apontando_esquerda',
 'apontando_cima','joinha','bracos_cruzados','dando_ombros','piscando','sussurrando',
 'comemorando','ultimo_minuto','acenando','chamando_comentar']


def _folder(slug):
    if slug not in PERSONAS:raise ValueError('Personagem desconhecido.')
    return db.ROOT/'assets'/'personas'/slug/'expressions'


def validate_png(path:Path):
    with Image.open(path) as image:
        if image.format!='PNG' or image.mode!='RGBA':raise ValueError('Pose deve ser PNG RGBA.')
        width,height=image.size
        if width<1024 or height<1280:raise ValueError('Pose individual precisa ter no mínimo 1024x1280, sem ampliar células da folha.')
        if any(image.getpixel(p)[3]>0 for p in ((0,0),(width-1,0),(0,height-1),(width-1,height-1))):
            raise ValueError('Pose tem fundo ou bordas não transparentes.')
        if image.getchannel('A').getextrema()[1]<255:raise ValueError('Pose não contém pixels opacos.')
    return width,height


def import_poses(slug:str, zip_path:Path) -> dict:
    """Validate all 24 masters before atomically swapping the gallery directory.

    Staging and active gallery live on the same /assets mount, avoiding EXDEV.
    Previous gallery is moved to _antigo and never deleted by the importer.
    """
    folder=_folder(slug)
    with tempfile.TemporaryDirectory(prefix='gta-poses-') as td:
        incoming=Path(td)
        with zipfile.ZipFile(zip_path) as archive:
            files=[f for f in archive.infolist() if not f.is_dir() and f.filename.lower().endswith('.png')]
            if len(files)!=24:raise ValueError('Envie exatamente 24 PNGs individuais de alta resolução.')
            paths={}
            for item in files:
                filename=Path(item.filename).name
                match=re.fullmatch(r'(0[1-9]|1[0-9]|2[0-4])_([a-z0-9_]+)\.png',filename)
                if not match:raise ValueError('Nome inválido: '+filename)
                index=int(match.group(1));expected=POSE_SLUGS[index-1]
                if match.group(2)!=expected or index in paths:raise ValueError('Pose ou índice inválido: '+filename)
                if item.file_size>18*1024*1024:raise ValueError('Pose excede 18 MB: '+filename)
                target=incoming/filename
                with archive.open(item) as src,target.open('wb') as out:
                    shutil.copyfileobj(src,out)
                paths[index]=target
            dimensions={validate_png(x) for x in paths.values()}
            if len(dimensions)!=1:raise ValueError('Todos os PNGs devem ter dimensões idênticas.')
        manifest={'personagem':slug,'width':next(iter(dimensions))[0],
                  'height':next(iter(dimensions))[1],'quality':'creator_supplied_high_resolution',
                  'images':[]}
        for index in range(1,25):
            path=paths[index]
            manifest['images'].append({'index':index,'emotion':POSE_SLUGS[index-1],
                'description':POSE_SLUGS[index-1].replace('_',' '),'file':path.name,'active':True,
                'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        base=db.ROOT/'assets'/'personas'
        staged=base/'_incoming'/slug/db.uid()
        staged.mkdir(parents=True,exist_ok=False)
        backup=base/'_antigo'/slug/db.uid()
        previous_moved=False
        try:
            for path in paths.values():shutil.copy2(path,staged/path.name)
            db.atomic(staged/'manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
            if folder.exists():
                backup.parent.mkdir(parents=True,exist_ok=True)
                folder.rename(backup)
                previous_moved=True
            try:
                staged.rename(folder)
            except OSError:
                if previous_moved and not folder.exists():backup.rename(folder)
                raise
            masters=base/'_quality_master'/slug
            masters.mkdir(parents=True,exist_ok=True)
            for index in range(1,25):shutil.copy2(folder/paths[index].name,masters/paths[index].name)
        finally:
            if staged.exists():shutil.rmtree(staged)
    return {'ok':True,'count':24,'dimensions':list(dimensions)[0],
            'previous_poses_backup':str(backup.relative_to(db.ROOT)) if previous_moved else None}


def save_sheet(slug, payload:bytes):
    if len(payload)>15*1024*1024:raise ValueError('Folha excede 15MB.')
    with Image.open(io.BytesIO(payload)) as image:
        if image.format!='PNG':raise ValueError('Folha deve ser PNG.')
        if image.width<800 or image.height<1200:raise ValueError('Folha muito pequena.')
    folder=db.ROOT/'assets'/'personas'/'_referencia'
    folder.mkdir(parents=True,exist_ok=True)
    target=folder/(slug+'_sheet.png')
    temporary=target.with_suffix('.png.tmp')
    temporary.write_bytes(payload)
    temporary.replace(target)
    return {'path':str(target.relative_to(db.ROOT)),
            'note':'Folha salva somente como referência. Não foi ampliada nem colocada na produção.'}
