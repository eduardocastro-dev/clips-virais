"""Generate local installation secrets inside a disposable Docker container."""
import os
import secrets
from pathlib import Path


def prepare(root: Path):
    path = root / '.env'
    original = path.read_text('utf-8-sig') if path.exists() else ''
    values = dict(line.split('=', 1) for line in original.splitlines()
                  if '=' in line and not line.lstrip().startswith('#'))
    defaults = {
        'STUDIO_TOKEN': secrets.token_hex(32),
        'POSTIZ_DB_PASSWORD': secrets.token_hex(32),
        'POSTGRES_ADMIN_PASSWORD': secrets.token_hex(32),
        'REDIS_PASSWORD': secrets.token_hex(32),
        'TEMPORAL_DB_PASSWORD': secrets.token_hex(32),
        'POSTIZ_JWT_SECRET': secrets.token_hex(64),
        'OMNIROUTE_JWT_SECRET': secrets.token_hex(64),
        'OMNIROUTE_API_KEY_SECRET': secrets.token_hex(32),
        'OMNIROUTE_PASSWORD': secrets.token_hex(24),
        'POSTIZ_ADMIN_PASSWORD': secrets.token_hex(24),
        'POSTIZ_ADMIN_EMAIL': 'admin@studio.local',
        'POSTIZ_PUBLIC_URL': 'http://localhost:4007',
        'STUDIO_TIMEZONE': 'America/Sao_Paulo',
    }
    additions = {k: v for k, v in defaults.items() if not values.get(k)}
    # Empty placeholders must be replaced, not duplicated. Preserve custom settings.
    lines = [line for line in original.splitlines() if line.split('=', 1)[0] not in additions]
    lines += [f'{k}={v}' for k, v in additions.items()]
    tmp = path.with_suffix('.setup-tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    print('Configuração local pronta. Segredos preservados em .env (não são exibidos nos logs).')


if __name__ == '__main__':
    prepare(Path(os.environ.get('SETUP_ROOT', '/workspace')))
