"""Three distinct editorial fixtures: real writer/redator validation, offline model stubs.

These tests do NOT claim to exercise OmniRoute, Piper or real video rendering.
"""
import json
import pytest
from backend import core as db, pipeline, redator, facts
from backend.contracts import Script

TOPICS = [
    'Cenas do trailer e detalhes visuais',
    'Corridas e carros mostrados no gameplay',
    'A ambientação e os programas de rádio',
]

@pytest.mark.parametrize('topic',TOPICS)
def test_three_different_topics_validate_on_first_script(monkeypatch,topic):
    monkeypatch.setattr(facts,'extract',lambda video,source:{
        'source_title':topic,'claims':[{'text':'A fonte descreve '+topic,'status':'source_attribution'}]})
    def fake_llm(agent,video_id,payload,schema,images=None):
        assert agent=='escritor'
        assert payload['narration_word_budget']['total_words_target']>0
        assert payload['source_start_unit'].startswith('seconds')
        assert payload['source_start_max_seconds']==0
        assert payload['allowed_script_music']=='none'
        return {
            'title':topic,'hook':'Olha este detalhe.','description':'Fonte declarada.',
            'hashtags':['GTA6'],'template':'gta-news','duration':45,'music':'random_unlicensed.mp3',
            'scenes':[
                {'start':0,'end':15,'text':'Gancho','narration':
                    'Veja o que está chamando atenção na comunidade. '+topic+' tem vários detalhes interessantes.',
                    'source_start':1025,'source_id':video_id},
                {'start':15,'end':30,'text':'Explicação','narration':
                    'A publicação mostra informações sobre '+topic+'. Vale olhar cada cena com atenção.',
                    'source_start':905,'source_id':video_id},
                {'start':30,'end':45,'text':'Comentário','narration':
                    'A conversa continua entre jogadores, e você pode contar qual parte mais gostou.',
                    'source_start':1520,'source_id':video_id},
            ]}
    monkeypatch.setattr(pipeline,'llm',fake_llm)
    cfg=db.settings();cfg.redator_ai=False;cfg.duration=45;db.put_setting('settings',cfg.model_dump())
    video_id=pipeline.create_video(reference={
        'url':'https://example.com/gta6/'+str(TOPICS.index(topic)),
        'title':topic,'description':topic,'metrics':{}},variant_key=None)
    video=db.rows('SELECT * FROM videos WHERE id=:id',{'id':video_id})[0]
    db.artifact(video_id,'cacador',data={'title':topic,'description':topic,'url':video['url']},next_agent='escritor')
    script=pipeline.write_script(video)
    assert script.music=='none'
    assert len(script.scenes)==3
    assert all(x.source_start==0 for x in script.scenes)
    assert script.duration==45
    result=redator.polish(video,script,1)
    assert Script.model_validate(result.model_dump()).music=='none'
    fixes=json.loads((db.ROOT/'handoff'/video_id/'briefing-fixes-1.json').read_text('utf-8'))
    assert sum(f['field'].endswith('.source_start') for f in fixes)==3
    assert any(f['field']=='music' for f in fixes)
    assert not (db.ROOT/'handoff'/video_id/'briefing-fixes-2.json').exists()
