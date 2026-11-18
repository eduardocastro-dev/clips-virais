"""Idempotent local-service account provisioning. Never publishes content."""
import os
import time
import httpx
from backend import core as db


def provision_postiz():
    if db.secret('postiz_api_key'):
        return
    with httpx.Client(base_url='http://postiz:5000/api', timeout=30) as c:
        body = dict(email=os.environ['POSTIZ_ADMIN_EMAIL'],
                    password=os.environ['POSTIZ_ADMIN_PASSWORD'], provider='LOCAL')
        response = c.post('/auth/login', json=body)
        if response.status_code == 400:
            can = c.get('/auth/can-register')
            can.raise_for_status()
            if not can.json().get('register'):
                raise RuntimeError('Postiz já tem uma conta: configure postiz_api_key no estúdio.')
            response = c.post('/auth/register', json={**body, 'company': 'GTA Content Studio'})
        response.raise_for_status()
        # NOT_SECURED supplies this header for self-hosted HTTP installations.
        token = response.headers.get('auth') or c.cookies.get('auth')
        if not token:
            raise RuntimeError('Postiz não retornou sessão; verifique ativação da conta.')
        response = c.get('/user/self', headers={'auth': token})
        response.raise_for_status()
        key = response.json().get('publicApi')
        if not key:
            raise RuntimeError('Postiz não retornou chave da organização.')
        db.set_secret('postiz_api_key', key)


def provision_omniroute():
    if db.secret('llm_api_key'):
        return
    with httpx.Client(base_url='http://omniroute:20128', timeout=30,
                      headers={'Origin': 'http://omniroute:20128'}) as c:
        response = c.post('/api/auth/login', json={'password': os.environ['OMNIROUTE_PASSWORD']})
        response.raise_for_status()
        models = [m.strip() for m in os.getenv('OMNIROUTE_FREE_MODELS', '').split(',') if m.strip()]
        if models:
            response = c.get('/api/combos')
            response.raise_for_status()
            if not any(x.get('name') == 'studio-free' for x in response.json().get('combos', [])):
                response = c.post('/api/combos', json={'name': 'studio-free', 'models': models,
                                                     'strategy': 'priority'})
                response.raise_for_status()
        response = c.post('/api/keys', json={'name': 'GTA Content Studio',
                         'modelAccessMode': 'restricted', 'allowedModels': [],
                         'allowedCombos': ['studio-free']})
        response.raise_for_status()
        key = response.json().get('key')
        if not key:
            raise RuntimeError('OmniRoute não retornou chave de API.')
        db.set_secret('llm_api_key', key)


def configure():
    if db.get_setting('docker_stack_configured'):
        return
    settings = db.settings()
    if not settings.postiz_url:
        settings.postiz_url = 'http://postiz:5000/api/public/v1'
    if settings.provider_url == 'http://host.docker.internal:11434/v1':
        settings.provider_url = 'http://omniroute:20128/v1'
        for route in settings.routes.values():
            if not route.model:
                route.model = 'studio-free'
    db.put_setting('settings', settings.model_dump())
    db.put_setting('docker_stack_configured', True)


def main():
    db.init_db()
    configure()
    for name, operation in [('Postiz', provision_postiz), ('OmniRoute', provision_omniroute)]:
        for attempt in range(30):
            try:
                operation()
                print(f'{name}: integração local configurada.', flush=True)
                break
            except Exception as error:
                # Do not log response bodies, credentials, cookies or exception URLs.
                print(f'{name}: aguardando configuração ({type(error).__name__}, tentativa {attempt + 1}/30).', flush=True)
                if attempt == 29:
                    raise RuntimeError(f'{name}: configuração pendente. Consulte docs/DOCKER.md.') from None
                time.sleep(10)
    print('Concluído. Conecte provedores no OmniRoute e canais no Postiz. Nenhuma publicação foi feita.', flush=True)


if __name__ == '__main__':
    main()
