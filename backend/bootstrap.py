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
        if response.status_code in (400, 401):
            can = c.get('/auth/can-register', params={'provider': 'LOCAL'})
            can.raise_for_status()
            eligibility = can.json()
            allowed = (eligibility if isinstance(eligibility, bool) else
                       eligibility.get('register', eligibility.get('canRegister', False)))
            if not allowed:
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
    """Provision an inference-only key; PATCH + verify its restrictions.

    Some OmniRoute releases ignore permissions passed directly to POST /api/keys.
    Persist an unfinished key ID so retries never manufacture extra keys.
    """
    existing = db.secret('llm_api_key')
    pending = db.get_setting('omniroute_key_policy_pending')
    if existing and not pending:
        return
    with httpx.Client(base_url='http://omniroute:20128', timeout=30,
                      headers={'Origin': 'http://omniroute:20128'}) as c:
        response = c.post('/api/auth/login', json={'password': os.environ['OMNIROUTE_PASSWORD']})
        response.raise_for_status()
        models = [m.strip() for m in os.getenv('OMNIROUTE_FREE_MODELS', '').split(',') if m.strip()]
        if models:
            response = c.get('/api/combos')
            response.raise_for_status()
            listing = response.json()
            combos = listing if isinstance(listing, list) else listing.get('combos', [])
            if not any(x.get('name') == 'studio-free' for x in combos):
                response = c.post('/api/combos', json={
                    'name': 'studio-free', 'strategy': 'priority',
                    'models': [{'model': m} for m in models]})
                response.raise_for_status()
        if not existing:
            response = c.post('/api/keys', json={'name': 'GTA Content Studio'})
            response.raise_for_status()
            payload = response.json()
            key, key_id = payload.get('key'), payload.get('id')
            if not key or not key_id:
                raise RuntimeError('OmniRoute não confirmou chave e ID.')
            db.set_secret('llm_api_key', key)
            db.put_setting('omniroute_key_policy_pending', key_id)
            pending = key_id
        # Do not silently accept a permissive key. Apply and read back permissions.
        policy = {'modelAccessMode': 'restricted', 'allowedModels': [],
                  'allowedCombos': ['studio-free'], 'allowAutoCombos': False,
                  'catalogScope': 'combos'}
        response = c.patch(f'/api/keys/{pending}', json=policy)
        response.raise_for_status()
        response = c.get(f'/api/keys/{pending}')
        response.raise_for_status()
        observed = response.json()
        observed = observed.get('key', observed) if isinstance(observed, dict) else {}
        for field, value in policy.items():
            if observed.get(field) != value:
                raise RuntimeError(f'OmniRoute não confirmou política de acesso ({field}).')
        db.put_setting('omniroute_key_policy_pending', None)


def configure():
    settings = db.settings()
    # Manual publishing is mandatory in this streamlined edition, including
    # installations migrated from the previous Postiz-enabled version.
    settings.postiz_url = ''
    settings.postiz_auto = False
    settings.postiz_channels = {}
    settings.youtube_auto = False
    settings.approval_mode = 'manual'
    if settings.provider_url == 'http://host.docker.internal:11434/v1':
        settings.provider_url = 'http://omniroute:20128/v1'
        for route in settings.routes.values():
            if not route.model:
                route.model = 'studio-free'
    db.put_setting('settings', settings.model_dump())
    db.put_setting('docker_stack_configured', True)
    # Discovery is YouTube Shorts-only; do not seed news RSS.


def main():
    db.init_db()
    configure()
    if db.secret('llm_api_key') and not db.get_setting('omniroute_key_policy_pending'):
        print('OmniRoute: chave existente preservada.', flush=True)
        return
    for attempt in range(5):
        try:
            provision_omniroute()
            print('OmniRoute: chave local configurada.', flush=True)
            break
        except Exception as error:
            print(f'OmniRoute: provisionamento pendente ({type(error).__name__}, tentativa {attempt+1}/5).', flush=True)
            if attempt < 4:
                time.sleep(5)
    else:
        print('OmniRoute: utilize Configurações > Chave de IA caso o provisionamento falhe.', flush=True)
    print('Modo manual: pesquisa, vídeo e pacote de metadados; nenhuma publicação automática.', flush=True)


if __name__ == '__main__':
    main()
