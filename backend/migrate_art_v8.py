"""Safely archive bundled v7 SVG sprites; never overwrite a creator-edited PNG.

Run once after extracting the patch, with the original /assets bind mount present.
"""
from __future__ import annotations
import hashlib
import json
import shutil
from pathlib import Path
from backend import core as db
from backend.pose_import import PERSONAS,POSE_SLUGS


def migrate(dry_run:bool=True)->dict:
    report={}
    templates=Path(__file__).resolve().parent.parent/'templates'/'personas'
    for slug in sorted(PERSONAS):
        folder=db.ROOT/'assets'/'personas'/slug/'expressions'
        source=templates/slug/'expressions'
        manifest_path=folder/'manifest.json'
        if not manifest_path.is_file():
            report[slug]='No manifest; nothing to archive';continue
        try:manifest=json.loads(manifest_path.read_text('utf-8'))
        except (OSError,ValueError):
            report[slug]='Invalid manifest; manual review required';continue
        if manifest.get('quality') in ('creator_supplied_high_resolution','creator_supplied_sheet_derived'):
            report[slug]='Creator artwork preserved (may be sheet-derived)';continue
        # Only archive files that are BYTE-FOR-BYTE identical to the v7 bundle.
        bundled=[p for p in source.glob('*.png') if (folder/p.name).is_file()]
        if not bundled or any((folder/p.name).read_bytes()!=p.read_bytes() for p in bundled):
            report[slug]='Creator changes detected or bundle unavailable; preserving files';continue
        destination=db.ROOT/'assets'/'personas'/'_antigo'/slug/('v7-'+db.uid())
        report[slug]={'archive':str(destination.relative_to(db.ROOT)),'matches':len(bundled),'dry_run':dry_run}
        if dry_run:continue
        destination.parent.mkdir(parents=True,exist_ok=True)
        # Move only after verifying the complete original collection.
        shutil.move(str(folder),str(destination))
        folder.mkdir(parents=True,exist_ok=True)
        pending={'personagem':slug,'quality':'pending_individual_high_resolution',
                 'width':None,'height':None,'images':[
                    {'index':i+1,'emotion':emotion,'description':emotion.replace('_',' '),
                     'file':f'{i+1:02}_{emotion}.png','active':False}
                    for i,emotion in enumerate(POSE_SLUGS)]}
        db.atomic(folder/'manifest.json',json.dumps(pending,ensure_ascii=False,indent=2))
    return report


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--apply',action='store_true',help='archive bundled placeholders with backup')
    opts=parser.parse_args()
    print(json.dumps(migrate(dry_run=not opts.apply),ensure_ascii=False,indent=2))
