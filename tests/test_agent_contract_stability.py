"""Regression tests for explicit agent handoffs and deterministic pre-validation."""
from types import SimpleNamespace
import json
import pytest
from pydantic import ValidationError
from backend import storyboard, highlights, narration_budget, redator
from backend.contracts import Script

ID='a'*32


def sample_payload(offset=1025, music='unknown_track'):
    return {
        'title':'GTA seis e as cenas do trailer','hook':'Olha esta cena!','description':'Resumo de exemplo.',
        'hashtags':['gta6'],'duration':45,'template':'gta-news','music':music,
        'scenes':[
            {'start':0,'end':18,'text':'Cena inicial','source_id':ID,'source_start':offset,
             'narration':' '.join(['Detalhe']*55)+'.'},
            {'start':18,'end':45,'text':'Nova descoberta','source_id':ID,'source_start':905,
             'narration':' '.join(['Jogo']*48)+'.'},
        ]}


def test_original_validators_remain_strict():
    raw=sample_payload(offset=1025,music='unknown_track')
    with pytest.raises(ValidationError) as error:
        Script.model_validate(raw)
    assert 'source_start' in str(error.value)
    valid_offsets=sample_payload(offset=0,music='unknown_track')
    valid_offsets['scenes'][1]['source_start']=0
    with pytest.raises(ValidationError,match='Música requer catálogo licenciado'):
        Script.model_validate(valid_offsets)


def test_sanitizes_source_and_music_without_deleting_narration():
    raw=sample_payload()
    normalized,fixes=storyboard.normalize(raw,45,'gta-news',ID,source_seconds=100)
    script=Script.model_validate(normalized)
    assert script.music=='none'
    assert all(0 <= sc.source_start <= min(600,100-(sc.end-sc.start)) for sc in script.scenes)
    assert script.scenes[0].narration==raw['scenes'][0]['narration']
    assert script.scenes[1].narration==raw['scenes'][1]['narration']
    assert {'music','scenes[0].source_start','scenes[1].source_start'} <= {f['field'] for f in fixes}
    assert raw['music']=='unknown_track'  # never mutate LLM source payload


def test_reference_without_local_video_uses_zero_offsets():
    normalized,fixes=storyboard.normalize(sample_payload(),45,'gta-news',ID)
    assert all(x['source_start']==0 for x in normalized['scenes'])
    assert any('sem vídeo-fonte' in f['reason'] for f in fixes)


def test_cannot_fake_source_longer_than_actual_clip():
    with pytest.raises(ValueError,match='não cabe na fonte local'):
        storyboard.normalize(sample_payload(),45,'gta-news',ID,source_seconds=4)


def test_out_of_range_offset_from_source_is_auditable():
    normalized, fixes=storyboard.normalize(sample_payload(offset=1280),45,'gta-news',ID,source_seconds=1500)
    assert all(s['source_start']<=600 for s in normalized['scenes'])
    assert any(f['field']=='scenes[0].source_start' and f['from']==1280 for f in fixes)


def test_highlights_uses_first_600_seconds_only():
    payload=sample_payload(offset=1520,music='none')
    payload['scenes'][0]['source_start']=580
    payload['scenes'][1]['source_start']=590
    from backend.contracts import Script
    script=Script.model_validate(payload)
    edl=highlights.fit_cuts(script,{
        'source_seconds':1800,'scene_cuts_seconds':[30,100,230,400,500,560]})
    assert all(0 <= row['source_start'] <= 600 for row in edl)
    assert all(row['source_end'] <= 600.01 for row in edl)


def test_measured_piper_rates_define_word_target(monkeypatch):
    monkeypatch.setattr(narration_budget,'calibrated_wps',lambda *a,**kw:(2.0,'piper_measured'))
    budget=narration_budget.script_budget(45,5,{'dante_palma':{'voice_model':'voice.onnx'}})
    assert (budget['total_words_min'],budget['total_words_target'],budget['total_words_max'])==(76,80,80)
    assert budget['voice_rates'][0]['basis']=='piper_measured'


def test_unavailable_voice_does_not_claim_measurement():
    rate,basis=narration_budget.calibrated_wps({'voice_model':'/nonexistent/voice.onnx'})
    assert rate>0 and basis.startswith('fallback_')


def test_timing_rewrite_has_exact_delta_and_error_context(monkeypatch,tmp_path):
    monkeypatch.setattr(redator.db,'ROOT',tmp_path)
    monkeypatch.setattr(redator.db,'today',lambda:'2026-11-19')
    monkeypatch.setattr(redator.db,'log_event',lambda *a,**kw:None)
    def save(path,value):
        path.parent.mkdir(exist_ok=True,parents=True)
        path.write_text(str(value),encoding='utf-8')
    monkeypatch.setattr(redator.db,'atomic',save)
    raw=sample_payload(offset=0,music='none')
    raw['scenes'][1]['source_start']=0
    script=Script.model_validate(raw)
    prompts=[]
    def fake_llm(agent,video_id,payload,schema):
        prompts.append(payload)
        return {'narrations':[x.narration for x in script.scenes]}
    monkeypatch.setattr(redator,'llm',fake_llm)
    with pytest.raises(Exception,match='não conseguiu alterar'):
        redator.adjust_timing({'id':ID},script,SimpleNamespace(actual=24.85,target=40,scenes=[10,14.85]),1,1)
    assert len(prompts)==3
    assert prompts[0]['delta_seconds']==15.15
    assert prompts[0]['delta_words_exact_target']>0
    assert prompts[0]['measured_words_per_second']>0
    assert prompts[0]['target_total_words']>prompts[0]['current_total_words']
