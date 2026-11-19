"""Install bundled, creator-supplied persona sheets into the persistent /assets bind mount.

Installations are idempotent: a current gallery is never overwritten. Older
SVG-based or incomplete galleries are backed up before installing the new art.
The 4x6 sheet-derived poses are transparent PNGs, but not native HD masters.
"""
from __future__ import annotations
import json
import shutil
from pathlib import Path
from backend import core as db

PERSONAS=('dante_palma','lia_varela','caio_rivas')
ACCEPTED_QUALITY={'creator_supplied_high_resolution','creator_supplied_sheet_derived'}


def _ready(folder: Path) -> bool:
    manifest=folder/'expressions'/'manifest.json'
    if not manifest.is_file():
        return False
    try:
        data=json.loads(manifest.read_text('utf-8'))
        items=data.get('images',[])
        return (data.get('quality') in ACCEPTED_QUALITY
                and len(items)==24
                and all((folder/'expressions'/item['file']).is_file() for item in items)
                and (folder/'avatar.png').is_file())
    except (ValueError,KeyError,OSError,TypeError):
        return False


def install_bundled_personas(*, force: bool=False) -> dict:
    """Seed missing/legacy galleries while keeping custom and previous art safe."""
    base=db.ROOT/'assets'/'personas'
    source=Path(__file__).resolve().parent.parent/'templates'/'personas'
    base.mkdir(parents=True,exist_ok=True)
    results={}
    # Multiple API/worker processes may initialize concurrently in Docker.
    handle=(base/'.install-bundled-personas.lock').open('a+b')
    try:
        try:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_EX)
        except ImportError:
            # Host-side Windows fallback. Docker containers always provide fcntl.
            pass
        for slug in PERSONAS:
            src=source/slug
            dst=base/slug
            if not _ready(src):
                results[slug]='modelo de referência incompleto; nenhuma alteração'
                continue
            if _ready(dst) and not force:
                results[slug]='galeria já instalada; preservada'
            else:
                staging=base/'_incoming'/slug/db.uid()
                backup=None
                try:
                    staging.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copytree(src,staging)
                    if dst.exists():
                        backup=base/'_antigo'/slug/db.uid()
                        backup.parent.mkdir(parents=True,exist_ok=True)
                        dst.rename(backup)
                    try:
                        staging.rename(dst)
                    except OSError:
                        if backup and backup.exists() and not dst.exists():
                            backup.rename(dst)
                        raise
                finally:
                    if staging.exists():shutil.rmtree(staging)
                results[slug]='instalada, anterior arquivada' if backup else 'instalada'
            # Restore masters are an immutable copy of the bundled art. Editing
            # a pose in the gallery must NOT silently change its restore master.
            master=base/'_quality_master'/slug
            bundled_manifest=src/'expressions'/'manifest.json'
            latest=json.loads(bundled_manifest.read_text('utf-8'))
            import hashlib
            bundled_hash=hashlib.sha256(bundled_manifest.read_bytes()).hexdigest()
            marker=master/'.bundle-sha256'
            if (db.ROOT/'assets'/'personas'/slug/'expressions'/'manifest.json').is_file():
                installed=json.loads((dst/'expressions'/'manifest.json').read_text('utf-8'))
                if installed.get('quality')=='creator_supplied_sheet_derived':
                    master_valid=(marker.is_file() and marker.read_text('ascii').strip()==bundled_hash
                        and all((master/item['file']).is_file() for item in latest['images']))
                    if not master_valid:
                        if master.exists():
                            backup=base/'_antigo'/'restauracao'/slug/db.uid()
                            backup.parent.mkdir(parents=True,exist_ok=True)
                            master.rename(backup)
                        master.mkdir(parents=True,exist_ok=True)
                        for item in latest['images']:
                            shutil.copy2(src/'expressions'/item['file'],master/item['file'])
                        shutil.copy2(bundled_manifest,master/'manifest.json')
                        marker.write_text(bundled_hash+'\n',encoding='ascii')
                        results[slug]+='; masters de restauração atualizados'
            reference=base/'_referencia'/f'{slug}_sheet.png'
            bundled=src/'pose-sheet.png'
            if not reference.exists() and bundled.is_file():
                reference.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(bundled,reference)
        return results
    finally:
        try:
            import fcntl
            fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        except ImportError:
            pass
        handle.close()


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser()
    parser.add_argument('--force',action='store_true',help='Substituir mesmo conjuntos completos, com backup')
    print(json.dumps(install_bundled_personas(force=parser.parse_args().force),ensure_ascii=False,indent=2))
