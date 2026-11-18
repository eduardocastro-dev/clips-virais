"""Offline diagnostics only: do not print OAuth IDs, keys, or passwords."""
from pathlib import Path
from urllib.parse import urlsplit


def read_env(path: Path):
    env = {}
    if path.exists():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            env[name.strip()] = value.strip().strip('"').strip("'")
    return env


def audit(env):
    pairs = {
        'YouTube (Google Cloud OAuth)': ('YOUTUBE_CLIENT_ID', 'YOUTUBE_CLIENT_SECRET'),
        'TikTok Developers': ('TIKTOK_CLIENT_ID', 'TIKTOK_CLIENT_SECRET'),
        'Instagram Facebook Business': ('FACEBOOK_APP_ID', 'FACEBOOK_APP_SECRET'),
        'Instagram Standalone': ('INSTAGRAM_APP_ID', 'INSTAGRAM_APP_SECRET'),
    }
    for label, keys in pairs.items():
        ok = all(bool(env.get(key)) for key in keys)
        print(f'{label}: {"CONFIGURADO (não testado)" if ok else "PENDENTE"}')
    url = env.get('POSTIZ_PUBLIC_URL', 'http://localhost:4007').rstrip('/')
    parsed = urlsplit(url)
    print('URL pública do Postiz: ' + ('https' if parsed.scheme == 'https' else 'http/local') +
          '; redirect YouTube: ' + url + '/integrations/social/youtube')
    if parsed.hostname not in ('localhost', '127.0.0.1') and parsed.scheme != 'https':
        print('ALERTA: plataforma pública deve usar HTTPS para OAuth.')
    print('Segredos não foram exibidos. Estado real dos canais e API keys deve ser verificado nos painéis.')


if __name__ == '__main__':
    audit(read_env(Path(__file__).resolve().parents[1] / '.env'))
