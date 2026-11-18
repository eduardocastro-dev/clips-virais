"""One-time offline migration of legacy Postiz/Temporal databases and Redis queues.

Requires Python 3.10+ and Docker Compose v2 on the HOST. Never deletes old volumes.
An unsuccessful migration leaves the legacy DB services and their volumes intact.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = 'docker-compose.legacy.yml'
NEW = 'docker-compose.yml'
PG_DBS = (('postiz', 'postiz', 'postiz-postgres'),
          ('temporal', 'temporal', 'temporal-postgresql'),
          ('temporal_visibility', 'temporal', 'temporal-postgresql'))
SOURCES = (('postiz-redis', 0), ('omniroute-redis', 1))
STOP_APPS = ('api', 'worker', 'web', 'bootstrap', 'postiz', 'temporal', 'omniroute')


class MigrationError(RuntimeError):
    pass


def run(*args: str, compose: str | None = None, input_file: Path | None = None,
        output_file: Path | None = None, quiet: bool = True) -> str:
    cmd = ['docker', 'compose', '-f', compose, *args] if compose else ['docker', *args]
    kwargs = {'cwd': ROOT, 'stderr': subprocess.PIPE, 'check': False}
    if input_file is not None:
        kwargs['stdin'] = input_file.open('rb')
    if output_file is not None:
        kwargs['stdout'] = output_file.open('wb')
    else:
        kwargs['stdout'] = subprocess.PIPE
    try:
        completed = subprocess.run(cmd, **kwargs)
    except FileNotFoundError:
        raise MigrationError('Docker CLI indisponível neste computador.') from None
    finally:
        for stream in (kwargs.get('stdin'), kwargs.get('stdout')):
            if hasattr(stream, 'close'):
                stream.close()
    if completed.returncode:
        # Never print docker stderr: it can contain a connection URL/secret.
        raise MigrationError('Comando Docker falhou: ' + ' '.join(args[:3]))
    return (completed.stdout or b'').decode('utf-8', 'strict').strip()


def compose_project() -> str:
    return json.loads(run('config', '--format', 'json', compose=OLD))['name']


def project_volumes(project: str) -> dict[str, str]:
    names = run('volume', 'ls', '-q', '--filter', f'label=com.docker.compose.project={project}')
    result = {}
    for name in names.splitlines():
        data = json.loads(run('volume', 'inspect', name))[0]
        logical = (data.get('Labels') or {}).get('com.docker.compose.volume')
        if logical:
            result[logical] = name
    return result


def assert_legacy_ready(volumes: dict[str, str]):
    required = {'postiz-db', 'temporal-db', 'postiz-redis', 'omniroute-redis-data'}
    missing = sorted(required - set(volumes))
    if missing:
        raise MigrationError('Volumes legados ausentes: ' + ', '.join(missing) +
                             '. Nada foi alterado.')
    if {'shared-postgres', 'shared-redis'} & set(volumes):
        raise MigrationError('Um volume compartilhado já existe; restauração automática bloqueada. '
                             'Verifique-o manualmente antes de prosseguir.')


def table_count(database: str, user: str, service: str, compose: str) -> int:
    query = "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE';"
    return int(run('exec', '-T', service, 'psql', '-X', '-U', user, '-d', database,
                   '-At', '-c', query, compose=compose))


def db_names() -> set[str]:
    names = run('exec', '-T', 'temporal-postgresql', 'psql', '-X', '-U', 'temporal',
                '-d', 'postgres', '-At', '-c',
                'SELECT datname FROM pg_database WHERE datistemplate=false', compose=OLD)
    return set(names.splitlines())


def save_db(database: str, user: str, service: str, directory: Path) -> dict:
    path = directory / f'{database}.dump'
    run('exec', '-T', service, 'pg_dump', '-U', user, '-d', database, '-Fc',
        compose=OLD, output_file=path)
    if path.stat().st_size < 100:
        raise MigrationError(f'Dump {database} pequeno demais; abortado.')
    run('exec', '-T', service, 'pg_restore', '--list', compose=OLD, input_file=path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return {'file': path.name, 'size': path.stat().st_size,
            'sha256': digest, 'tables': table_count(database, user, service, OLD)}


def save_redis(service: str, directory: Path) -> dict:
    # SAVE writes /data/dump.rdb even when the server uses AOF, for an independent backup.
    if run('exec', '-T', service, 'redis-cli', 'SAVE', compose=OLD) != 'OK':
        raise MigrationError(f'Snapshot Redis não confirmado: {service}')
    name = run('ps', '-a', '-q', service, compose=OLD)
    if not name:
        raise MigrationError(f'Container legado Redis não encontrado: {service}')
    path = directory / (service + '.rdb')
    run('cp', f'{name}:/data/dump.rdb', str(path))
    count = int(run('exec', '-T', service, 'redis-cli', 'DBSIZE', compose=OLD))
    return {'file': path.name, 'size': path.stat().st_size,
            'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'keys': count}


def wait_shared():
    for _ in range(40):
        try:
            ok_pg = run('exec', '-T', 'postgres', 'pg_isready', '-U', 'studio_admin',
                        '-d', 'postgres', compose=NEW)
            ok_redis = run('exec', '-T', 'redis', 'sh', '-c',
                           'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli ping', compose=NEW)
            if 'accepting connections' in ok_pg and ok_redis == 'PONG':
                return
        except MigrationError:
            pass
        time.sleep(3)
    raise MigrationError('Bancos compartilhados não ficaram saudáveis.')


def restore_db(database: str, role: str, record: dict, directory: Path):
    if table_count(database, 'studio_admin', 'postgres', NEW):
        raise MigrationError(f'Destino {database} já contém tabelas. Nenhuma restauração será feita.')
    run('exec', '-T', 'postgres', 'pg_restore', '-U', 'studio_admin', '-d', database,
        '--exit-on-error', '--no-owner', '--no-acl', '--role', role,
        compose=NEW, input_file=directory / record['file'])
    actual = table_count(database, 'studio_admin', 'postgres', NEW)
    if actual != record['tables']:
        raise MigrationError(f'Quantidade de tabelas divergente em {database}: {actual} != {record["tables"]}')


def shared_keys(db: int) -> int:
    return int(run('exec', '-T', 'redis', 'sh', '-c',
                   f'REDISCLI_AUTH="$REDIS_PASSWORD" redis-cli -n {db} DBSIZE', compose=NEW))


def copy_redis(service: str, db: int, expected: int, password: str):
    if shared_keys(db):
        raise MigrationError(f'Redis destino DB {db} não está vazio; não sobrescrever.')
    keys = run('exec', '-T', service, 'redis-cli', '--raw', '--scan', compose=OLD).splitlines()
    if len(keys) != expected:
        raise MigrationError(f'Chaves Redis {service} mudaram durante migração.')
    for offset in range(0, len(keys), 40):
        batch = keys[offset:offset + 40]
        # COPY preserves the legacy source keys. REPLACE deliberately omitted.
        result = run('exec', '-T', service, 'redis-cli', 'MIGRATE', 'redis', '6379',
                     '', str(db), '60000', 'COPY', 'AUTH', password, 'KEYS', *batch,
                     compose=OLD)
        if result != 'OK':
            raise MigrationError(f'Cópia das filas Redis {service} não confirmada.')
    if shared_keys(db) != expected:
        raise MigrationError(f'Contagem de chaves Redis não confere no DB {db}.')


def main():
    os.chdir(ROOT)
    env_path = ROOT / '.env'
    if not env_path.is_file():
        raise MigrationError('Crie .env executando o script start primeiro (sem subir nova infraestrutura).')
    env = dict(line.strip().split('=', 1) for line in env_path.read_text('utf-8-sig').splitlines()
               if '=' in line and not line.lstrip().startswith('#'))
    password = env.get('REDIS_PASSWORD')
    if not password:
        raise MigrationError('REDIS_PASSWORD não foi gerada em .env.')
    marker = ROOT / 'data' / 'migration-shared.completed.json'
    if marker.exists():
        raise MigrationError('Migração já registrada. Nada foi refeito.')
    volumes = project_volumes(compose_project())
    assert_legacy_ready(volumes)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory = ROOT / 'data' / 'migration' / stamp
    directory.mkdir(parents=True, exist_ok=False)
    if os.name != 'nt':
        directory.chmod(0o700)
    print('Parando aplicativos para snapshot consistente (volumes não serão removidos).', flush=True)
    run('stop', *STOP_APPS, compose=OLD)
    run('up', '-d', 'postiz-postgres', 'temporal-postgresql',
        'postiz-redis', 'omniroute-redis', compose=OLD)
    databases = db_names()
    if 'temporal' not in databases:
        raise MigrationError('Banco temporal legado ausente.')
    actual_db_list = [d for d in PG_DBS if d[0] != 'temporal_visibility' or 'temporal_visibility' in databases]
    manifest = {'project': compose_project(), 'created_utc': stamp, 'databases': {}, 'redis': {},
                'legacy_volumes': {k: volumes[k] for k in volumes if k in
                                   {'postiz-db', 'temporal-db', 'postiz-redis', 'omniroute-redis-data'}}}
    for db, role, service in actual_db_list:
        manifest['databases'][db] = save_db(db, role, service, directory)
    for service, destination in SOURCES:
        manifest['redis'][service] = save_redis(service, directory)
    mfile = directory / 'manifest.json'
    mfile.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('Backups SQL e Redis verificados; originais preservados.', flush=True)
    run('up', '-d', 'postgres', 'redis', compose=NEW)
    wait_shared()
    for database, role, _ in actual_db_list:
        restore_db(database, role, manifest['databases'][database], directory)
    for service, destination in SOURCES:
        copy_redis(service, destination, manifest['redis'][service]['keys'], password)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'snapshot': str(directory.relative_to(ROOT)), 'project': manifest['project'],
                                  'completed_utc': datetime.now(timezone.utc).isoformat()}, indent=2), encoding='utf-8')
    if os.name != 'nt':
        marker.chmod(0o600)
    run('stop', 'postiz-postgres', 'temporal-postgresql', 'postiz-redis', 'omniroute-redis', compose=OLD)
    print('Migração confirmada. Execute start.ps1 / sh start.sh. Não execute down -v.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except (MigrationError, ValueError, OSError, subprocess.SubprocessError) as error:
        print('MIGRAÇÃO INTERROMPIDA: ' + str(error) + '\n'
              'Volumes e backups legados mantidos. Não inicie o stack novo antes de reconciliar o erro.',
              file=sys.stderr)
        sys.exit(1)
