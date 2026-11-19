"""Regression: OmniRoute no-op results must not halt every video."""
import json
from types import SimpleNamespace
from pathlib import Path
import pytest
from backend import redator
from backend.contracts import Script
from backend.media import PreflightError


def sample_script():
    return Script(
        title='GTA seis - teste de narração',
        hook='O que apareceu na fonte?', description='Comentário original.',
        hashtags=['GTA6'], template='gta-news', duration=45,
        scenes=[
            {'start':0,'end':22,'text':'Detalhes sobre GTA',
             'narration':'A notícia está circulando na comunidade de GTA seis. Vamos conferir os detalhes.',
             'source_id':'a'*32},
            {'start':22,'end':45,'text':'O que vem a seguir?',
             'narration':'Segundo a matéria, o assunto ainda está sendo discutido por jogadores. E você?',
             'source_id':'a'*32}
        ], cta='Comente abaixo.'
    )


def issue(seconds=27.68):
    return SimpleNamespace(actual=seconds, target=40.0, scenes=[seconds/2]*2)


def build_monkeypatch(monkeypatch, tmp_path):
    monkeypatch.setattr(redator.db, 'ROOT', tmp_path)
    monkeypatch.setattr(redator.db,'today', lambda:'2026-11-19')
    monkeypatch.setattr(redator.db,'log_event',lambda *args,**kwargs:None)
    def fake_atomic(path, value):
        Path(path).parent.mkdir(parents=True,exist_ok=True)
        Path(path).write_text(str(value),encoding='utf-8')
    monkeypatch.setattr(redator.db,'atomic',fake_atomic)


def expanded():
    return [
        'A notícia está circulando na comunidade de GTA seis. O interesse aumentou porque jogadores querem entender melhor o que aparece na publicação. A fonte descreve o assunto e a comunidade debate possíveis interpretações. Vale observar os detalhes antes de tirar conclusões.',
        'Segundo a matéria, o assunto ainda está sendo discutido por jogadores. A conversa mostra como cada pequena informação gera curiosidade. Pense no que isso pode significar para os próximos vídeos. E você, qual detalhe mais chamou sua atenção?'
    ]


def test_retry_when_model_returns_identical_text(monkeypatch,tmp_path):
    build_monkeypatch(monkeypatch,tmp_path)
    before=sample_script()
    calls=[]
    def fake_llm(agent,video_id,payload,schema):
        calls.append((agent,payload))
        if len(calls)==1:
            return {'narrations':[s.narration for s in before.scenes]}
        return {'narrations':expanded()}
    monkeypatch.setattr(redator,'llm',fake_llm)
    result=redator.adjust_timing({'id':'b'*32},before,issue(),1,1)
    assert len(calls)==2
    assert all(agent=='redator' for agent,_ in calls)
    assert result.duration==45
    assert result.template==before.template
    assert result.scenes[0].start==before.scenes[0].start
    assert result.scenes[0].end==before.scenes[0].end
    assert result.scenes[0].speaker==before.scenes[0].speaker
    assert len(result.scenes[0].narration)>len(before.scenes[0].narration)
    log=json.loads((tmp_path/'handoff'/('b'*32)/'narration-timing-adjust-1-1.json').read_text())
    assert log['word_count_after']>log['word_count_before']
    assert log['failed_rewrites'][0].endswith('sem alterações')


def test_writer_fallback_only_after_two_unchanged_redator_results(monkeypatch,tmp_path):
    build_monkeypatch(monkeypatch,tmp_path)
    before=sample_script()
    calls=[]
    def fake_llm(agent,video_id,payload,schema):
        calls.append(agent)
        if agent=='escritor':
            return {'narrations':expanded()}
        return {'narrations':[s.narration for s in before.scenes]}
    monkeypatch.setattr(redator,'llm',fake_llm)
    result=redator.adjust_timing({'id':'b'*32},before,issue(),2,1)
    assert calls==['redator','redator','escritor']
    assert 'comunidade' in result.scenes[0].narration


def test_reject_noop_with_actionable_explanation(monkeypatch,tmp_path):
    build_monkeypatch(monkeypatch,tmp_path)
    before=sample_script()
    monkeypatch.setattr(redator,'llm',lambda agent,video_id,payload,schema: {'narrations':[s.narration for s in before.scenes]})
    with pytest.raises(PreflightError,match=r'Áudio real 27.68s.*palavras atuais=.*combo OmniRoute'):
        redator.adjust_timing({'id':'b'*32},before,issue(),1,1)


def test_measured_targets_from_tts_not_fixed_wps():
    script=sample_script()
    target=redator._timing_targets(script,27.68,40)
    assert sum(target)>sum(len(scene.narration.split()) for scene in script.scenes)
    assert redator._timing_targets(script,44,40)[0]<len(script.scenes[0].narration.split())
