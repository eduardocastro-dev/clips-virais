from scripts.setup_stack import prepare
from backend import bootstrap, core as db


def test_setup_preserves_secrets_and_custom_settings(tmp_path):
    (tmp_path / '.env').write_text('STUDIO_TOKEN=existing-token\nCUSTOM=yes\n')
    prepare(tmp_path)
    first = (tmp_path / '.env').read_text()
    prepare(tmp_path)
    assert (tmp_path / '.env').read_text() == first
    assert 'STUDIO_TOKEN=existing-token' in first
    assert 'CUSTOM=yes' in first
    values = dict(line.split('=', 1) for line in first.splitlines())
    assert len(values['REDIS_PASSWORD']) == 64
    assert values['OMNIROUTE_PASSWORD']
    assert 'POSTIZ_DB_PASSWORD' not in values


def test_stack_defaults_preserve_user_choices():
    settings = db.settings()
    settings.daily_limit = 7
    db.put_setting('settings', settings.model_dump())
    bootstrap.configure()
    assert db.settings().provider_url == 'http://omniroute:20128/v1'
    assert db.settings().routes['escritor'].model == 'studio-free'
    assert db.settings().daily_limit == 7
    assert not db.settings().automatic
    settings = db.settings()
    settings.provider_url = 'http://custom-provider:8080/v1'
    db.put_setting('settings', settings.model_dump())
    bootstrap.configure()
    assert db.settings().provider_url == settings.provider_url


def test_existing_credentials_are_not_rotated(monkeypatch):
    db.set_secret('llm_api_key', 'existing-llm')
    db.set_secret('postiz_api_key', 'existing-postiz')
    monkeypatch.setattr(bootstrap.httpx, 'Client', lambda **kw: (_ for _ in ()).throw(AssertionError('No request expected')))
    bootstrap.provision_omniroute()
    assert db.secret('llm_api_key') == 'existing-llm'
    assert db.secret('postiz_api_key') == 'existing-postiz'
