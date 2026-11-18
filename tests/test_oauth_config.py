from backend import bootstrap, core as db


def test_bootstrap_manual_mode_preserves_ia_without_seeding_rss():
    db.set_secret('llm_api_key', 'already-authenticated')
    settings = db.settings()
    settings.postiz_auto = True
    settings.youtube_auto = True
    settings.postiz_url = 'http://postiz:5000/api/public/v1'
    settings.approval_mode = 'automatic'
    db.put_setting('settings', settings.model_dump())
    bootstrap.configure()
    updated = db.settings()
    assert updated.postiz_url == ''
    assert not updated.postiz_auto and not updated.youtube_auto
    assert updated.approval_mode == 'manual'
    assert db.secret('llm_api_key') == 'already-authenticated'
    assert len(db.rows('SELECT * FROM sources')) == 0
    bootstrap.configure()
    assert len(db.rows('SELECT * FROM sources')) == 0
