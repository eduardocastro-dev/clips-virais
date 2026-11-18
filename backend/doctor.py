"""Non-destructive runtime diagnostics; does not expose secrets or call paid models."""
import httpx
from backend import core as db


def probe():
    db.init_db()
    s = db.settings()
    result = {'publicacao': 'MANUAL (sem OAuth/Postiz)', 'omniroute': 'PENDENTE', 'modelos': 'NÃO VERIFICADOS',
              'restricao_chave_omniroute': 'PENDENTE'}
    llm_key = db.secret('llm_api_key')
    pending = db.get_setting('omniroute_key_policy_pending')
    result['restricao_chave_omniroute'] = 'NÃO CONFIRMADA' if pending else ('CONFIRMADA' if llm_key else 'PENDENTE')
    if llm_key and s.provider_url:
        try:
            r = httpx.get(s.provider_url.rstrip('/') + '/models',
                          headers={'Authorization': 'Bearer ' + llm_key}, timeout=10)
            result['omniroute'] = 'CONECTADO' if r.status_code == 200 else f'HTTP {r.status_code}'
            if r.status_code == 200:
                models = r.json().get('data', [])
                result['modelos'] = f'{len(models)} disponíveis no catálogo autenticado'
        except (httpx.HTTPError, ValueError, AttributeError):
            result['omniroute'] = 'INDISPONÍVEL'
    return result


if __name__ == '__main__':
    for item, status in probe().items():
        print(f'{item}: {status}', flush=True)
    print('Checagem sem inferência ou publicação externa.', flush=True)
