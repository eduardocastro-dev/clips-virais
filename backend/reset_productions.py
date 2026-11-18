"""Two-phase, operator-approved production reset for a self-hosted single user.

Run in the API container with the worker stopped. Never modifies OmniRoute
providers, credentials, social connections or Redis. Backups remain in /studio.
"""
import argparse
import json
import os
import shutil
import sqlite3
import tarfile
from datetime import datetime, timezone
from pathlib import Path
from backend import core as db
from sqlalchemy import text

TABLES=('videos','jobs','video_attempts','publications','metrics','events','notifications','usage')
ARCHIVE_FOLDERS=('handoff','videos','output','reports')


def counts():
    result={name:db.rows(f'SELECT COUNT(*) AS n FROM {name}')[0]['n'] for name in TABLES}
    result['daily_kv']=db.rows("SELECT COUNT(*) AS n FROM kv WHERE key LIKE 'daily:%'")[0]['n']
    result['cache']=db.rows('SELECT COUNT(*) AS n FROM cache')[0]['n']
    return result


def backup():
    db.init_db()
    name=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+db.uid()[:8]
    root=db.ROOT/'backups'/'production-reset'/name
    root.mkdir(parents=True,exist_ok=False)
    try:
        os.chmod(root,0o700)
    except OSError:
        pass
    src=sqlite3.connect(str(db.DATA/'studio.sqlite'))
    dst=sqlite3.connect(str(root/'studio.sqlite'))
    try:
        src.backup(dst)
        assert dst.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    finally:
        src.close();dst.close()
    export={name:db.rows('SELECT * FROM '+name) for name in TABLES}
    export['legacy_daily_kv']=db.rows("SELECT * FROM kv WHERE key LIKE 'daily:%'")
    (root/'affected-tables.json').write_text(json.dumps(export,ensure_ascii=False,indent=2,default=str),'utf-8')
    key=db.DATA/'secrets.key'
    if key.is_file():
        shutil.copy2(key,root/'secrets.key')
    with tarfile.open(root/'production-files.tar.gz','w:gz') as tar:
        for folder in ARCHIVE_FOLDERS:
            target=db.ROOT/folder
            if target.exists():
                tar.add(target,arcname=folder,recursive=True)
    manifest={'backup_id':name,'created_utc':datetime.now(timezone.utc).isoformat(),
              'counts_before':counts(),'files':[p.name for p in root.iterdir()],
              'note':'Backup SQLite inclui configurações e segredos criptografados. Guardar em local protegido.'}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'backup_id':name,'backup_path':str(root),'counts_before':manifest['counts_before'],
                      'next':'Solicite confirmação ANTES de executar o reset.'},ensure_ascii=False,indent=2))
    return name


def reset(backup_id,confirmation):
    if confirmation!='CONFIRMO_RESET_TOTAL':
        raise SystemExit('Reset bloqueado: confirmação explícita ausente.')
    if not backup_id or not all(ch.isalnum() or ch in '-T' for ch in backup_id):
        raise SystemExit('Backup ID inválido.')
    root=(db.ROOT/'backups'/'production-reset'/backup_id).resolve()
    expected=(db.ROOT/'backups'/'production-reset').resolve()
    if root.parent != expected or not (root/'manifest.json').is_file() or not (root/'studio.sqlite').is_file() or not (root/'production-files.tar.gz').is_file():
        raise SystemExit('Backup completo não encontrado; reset bloqueado.')
    saved=json.loads((root/'manifest.json').read_text('utf-8'))
    if saved['backup_id']!=backup_id:
        raise SystemExit('Identificador de backup divergente.')
    db.init_db()
    with db.transaction() as c:
        # Keep profiles, sources, provider credentials and settings.
        for table in ('metrics','publications','video_attempts','jobs','events','notifications','videos','usage','cache'):
            c.execute(text('DELETE FROM '+table))
        c.execute(text("DELETE FROM kv WHERE key LIKE 'daily:%' OR key LIKE 'budget:%' OR key LIKE 'reservation:%'"))
        c.execute(text("DELETE FROM kv WHERE key IN ('last_search','maintenance','worker_heartbeat')"))
    # Files in media folders were archived in production-files.tar.gz.
    for folder in ('handoff','videos/raw','videos/processing','videos/final','output','reports'):
        base=(db.ROOT/folder).resolve()
        if not base.is_relative_to(db.ROOT.resolve()):
            raise SystemExit('Caminho fora da pasta do Studio; limpeza de mídia bloqueada.')
        if base.exists():
            for child in base.iterdir():
                if child.is_dir() and not child.is_symlink():shutil.rmtree(child)
                else:child.unlink()
    remaining=counts()
    print(json.dumps({'backup_id':backup_id,'after':remaining,
                      'success':all(v==0 for v in remaining.values()),
                      'note':'OmniRoute e Redis externo não foram alterados. Fontes, perfis e segredos mantidos.'},ensure_ascii=False,indent=2))
    if any(v!=0 for v in remaining.values()):
        raise SystemExit('AVISO: alguma tabela não está zerada.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description='Backup primeiro; reset só com confirmação do operador.')
    parser.add_argument('command',choices=('backup','reset','counts'))
    parser.add_argument('--backup-id',default='')
    parser.add_argument('--confirm',default='')
    args=parser.parse_args()
    if args.command=='backup':backup()
    elif args.command=='counts':db.init_db();print(json.dumps(counts(),indent=2))
    else:reset(args.backup_id,args.confirm)
