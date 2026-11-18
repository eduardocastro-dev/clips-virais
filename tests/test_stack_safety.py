"""Safety cases independent of external accounts and real Docker."""
from pathlib import Path
import pytest
from backend import bootstrap, core as db
from scripts import migrate_shared


def test_migration_rejects_missing_legacy_volumes():
    with pytest.raises(migrate_shared.MigrationError, match='ausentes'):
        migrate_shared.assert_legacy_ready({})


def test_migration_never_overwrites_existing_target():
    volumes = {x: x for x in ['postiz-db', 'temporal-db', 'postiz-redis',
                                'omniroute-redis-data', 'shared-redis']}
    with pytest.raises(migrate_shared.MigrationError, match='já existe'):
        migrate_shared.assert_legacy_ready(volumes)


class Response:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code
    def json(self): return self.payload
    def raise_for_status(self):
        assert self.status_code < 400


class OmniClient:
    seen = []
    mode = 'ok'
    def __init__(self, **kwargs): self.policy = None
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def post(self, path, json=None):
        self.seen.append((path, json))
        if path == '/api/auth/login': return Response({})
        if path == '/api/keys': return Response({'id': 'key-id', 'key': 'secret-key'})
        if path == '/api/combos': return Response({'id': 'combo-id'})
        raise AssertionError(path)
    def get(self, path):
        self.seen.append((path, None))
        if path == '/api/combos': return Response({'combos': []})
        if path == '/api/keys/key-id':
            return Response({'key': self.policy if self.mode == 'ok' else {'modelAccessMode': 'all'}})
        raise AssertionError(path)
    def patch(self, path, json=None):
        self.seen.append((path, json))
        self.policy = json
        return Response({})


def test_omniroute_key_restriction_is_patched_and_verified(monkeypatch):
    OmniClient.seen = []
    OmniClient.mode = 'ok'
    monkeypatch.setattr(bootstrap.httpx, 'Client', OmniClient)
    monkeypatch.setenv('OMNIROUTE_PASSWORD', 'does-not-leak')
    monkeypatch.setenv('OMNIROUTE_FREE_MODELS', 'provider/model-a,provider/model-b')
    bootstrap.provision_omniroute()
    assert db.secret('llm_api_key') == 'secret-key'
    assert db.get_setting('omniroute_key_policy_pending') is None
    sent = {path: value for path, value in OmniClient.seen if value is not None}
    assert sent['/api/combos']['models'] == [{'model': 'provider/model-a'}, {'model': 'provider/model-b'}]
    assert sent['/api/keys/key-id']['allowedCombos'] == ['studio-free']
    assert sent['/api/keys/key-id']['modelAccessMode'] == 'restricted'


def test_omniroute_failed_policy_does_not_create_second_key(monkeypatch):
    OmniClient.seen = []
    OmniClient.mode = 'bad'
    monkeypatch.setattr(bootstrap.httpx, 'Client', OmniClient)
    monkeypatch.setenv('OMNIROUTE_PASSWORD', 'test')
    monkeypatch.delenv('OMNIROUTE_FREE_MODELS', raising=False)
    with pytest.raises(RuntimeError, match='política'):
        bootstrap.provision_omniroute()
    assert db.get_setting('omniroute_key_policy_pending') == 'key-id'
    with pytest.raises(RuntimeError, match='política'):
        bootstrap.provision_omniroute()
    assert [path for path, _ in OmniClient.seen].count('/api/keys') == 1
