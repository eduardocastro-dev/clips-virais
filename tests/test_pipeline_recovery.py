"""Regression tests for durable retries and measured narration timing."""
from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from backend import core as db, integrations, pipeline, redator, worker, media
from backend.contracts import ModelRoute, Script
from backend.integrations import IntegrationError


def sample_script():
    return Script(
        title='GTA seis - recuperação', hook='Uma notícia',
        description='Comentário original', hashtags=['GTA6'], template='gta-news',
        duration=45, scenes=[
            {'start': 0, 'end': 22, 'text': 'Fato principal',
             'narration': 'A comunidade acompanha a notícia sobre GTA seis e discute seus efeitos.',
             'source_id': 'a'*32},
            {'start': 22, 'end': 45, 'text': 'Repercussão',
             'narration': 'O assunto desperta interesse dos jogadores. O que você acha?',
             'source_id': 'a'*32}
        ], cta='Comente sua opinião.'
    )


def test_5497_seconds_cannot_be_silently_accepted(monkeypatch, tmp_path):
    monkeypatch.setattr(redator.db, 'ROOT', tmp_path)
    monkeypatch.setattr(redator.db, 'today', lambda: '2026-11-19')
    monkeypatch.setattr(redator.db, 'log_event', lambda *a, **kw: None)
    calls = []
    script = sample_script()
    def no_change(agent, video_id, payload, schema):
        calls.append(agent)
        return {'narrations': [scene.narration for scene in script.scenes]}
    monkeypatch.setattr(redator, 'llm', no_change)
    with pytest.raises(media.PreflightError, match=r'Áudio real 54.97s fora de 38.00s–40.00s'):
        redator.adjust_timing({'id': 'b'*32}, script,
                              SimpleNamespace(actual=54.97, target=40., scenes=[28, 26.97]), 1, 1)
    assert calls == ['redator', 'redator', 'escritor']


def test_polish_uses_existing_script_if_provider_fails(monkeypatch, tmp_path):
    cfg = SimpleNamespace(redator_ai=True, narration_margin_seconds=5)
    monkeypatch.setattr(redator.db, 'settings', lambda: cfg)
    monkeypatch.setattr(redator.db, 'ROOT', tmp_path)
    monkeypatch.setattr(redator.db, 'today', lambda: '2026-11-19')
    monkeypatch.setattr(redator.db, 'read_artifact', lambda *a: SimpleNamespace(dados={}))
    monkeypatch.setattr(redator.db, 'log_event', lambda *a, **k: None)
    monkeypatch.setattr(redator.db, 'artifact', lambda *a, **k: None)
    monkeypatch.setattr(redator.db, 'atomic',
                        lambda path, data: Path(path).write_text(str(data), encoding='utf8'))
    monkeypatch.setattr(redator, 'get_cast', lambda: {'dante_palma': {'voice_model': '/missing.onnx'}})
    monkeypatch.setattr('backend.narration_budget.script_budget', lambda *a, **k: {'total_words_target': 33})
    monkeypatch.setattr(redator, 'llm',
                        lambda *a, **k: (_ for _ in ()).throw(IntegrationError('HTTP 429')))
    (tmp_path/'handoff'/('b'*32)).mkdir(parents=True)
    result = redator.polish({'id': 'b'*32, 'test': False}, sample_script())
    assert len(result.scenes) == 2
    assert (tmp_path/'handoff'/('b'*32)/'script.json').exists()


def test_http_200_invalid_json_is_retried(monkeypatch):
    config = db.settings()
    config.routes['redator'] = ModelRoute(model='fake', max_tokens=256)
    monkeypatch.setattr(integrations.db, 'settings', lambda: config)
    monkeypatch.setattr(integrations.time, 'sleep', lambda _: None)
    calls = []
    def fake_request(method, url, **kwargs):
        calls.append(1)
        raw = 'não é JSON' if len(calls) == 1 else json.dumps({'narrations': ['Teste']})
        return SimpleNamespace(json=lambda: {
            'choices': [{'message': {'content': raw}}],
            'usage': {'total_tokens': 9}
        })
    monkeypatch.setattr(integrations, 'request', fake_request)
    result = integrations.llm('redator', None, {}, {'type': 'object', 'required': ['narrations']})
    assert result['narrations'] == ['Teste']
    assert len(calls) == 2


def test_preflight_failures_propagate_to_worker(monkeypatch):
    video_id = pipeline.create_video(test=True)
    monkeypatch.setattr(pipeline.media, 'render', lambda *a, **k: (_ for _ in ()).throw(
        media.PreflightError('TTS real 54.97s fora do alvo')))
    with pytest.raises(media.PreflightError, match='54.97s'):
        pipeline.run_pipeline(video_id)
    assert db.rows('SELECT status FROM videos WHERE id=:id', {'id': video_id})[0]['status'] == 'RETRY'


def test_worker_does_not_reject_video_after_exhausted_technical_retries(monkeypatch):
    video_id = pipeline.create_video(test=True)
    monkeypatch.setattr(worker, 'scheduler', lambda: None)
    monkeypatch.setattr(worker, 'deliver_notifications', lambda: None)
    monkeypatch.setattr(worker, 'run_pipeline', lambda _: (_ for _ in ()).throw(
        IntegrationError('Resposta inválida do redator')))
    for attempt in range(5):
        db.execute("UPDATE jobs SET due=0 WHERE kind='pipeline'")
        worker.tick()
        job = db.rows("SELECT status,attempts FROM jobs WHERE video_id=:id", {'id': video_id})[0]
        assert job['attempts'] == attempt+1
        assert job['status'] == ('FAILED' if attempt == 4 else 'QUEUED')
    video = db.rows('SELECT status,error FROM videos WHERE id=:id', {'id': video_id})[0]
    assert video['status'] == 'PIPELINE_ERROR'
    assert 'Resposta inválida' in video['error']
