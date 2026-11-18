"""Contract tests: passed evaluations are reused only across unchanged dependencies."""
from backend.evaluation import locked_from_previous
from backend.contracts import Settings


def test_retain_independent_scores_only():
    old={'script':'s1','narration':'n1','visual':'v1','format':'f1','rights':'r1'}
    previous={'review_context':old,'criteria':{
        'accuracy':{'score':8,'passed':True},'cuts':{'score':9,'passed':True},
        'audio':{'score':8,'passed':True},'rights':{'score':9,'passed':True}},
        'viewer':{'attention':{'score':8,'passed':True}}}
    changed={**old,'visual':'v2'}
    tech,viewer=locked_from_previous(previous,changed)
    assert 'accuracy' in tech and 'audio' in tech and 'rights' in tech
    assert 'cuts' not in tech and 'attention' not in viewer


def test_legacy_routes_inherit_from_known_agents():
    s=Settings.model_validate({'routes':{'escritor':{'model':'studio-free'},
                                         'avaliador':{'model':'studio-free'}}})
    assert s.routes['redator'].model=='studio-free'
    assert s.routes['pessoa'].model=='studio-free'


def test_targeted_refaction_keeps_unaffected_scenes():
    from backend import core as db
    from backend.pipeline import preserve_unaffected_scenes
    from backend.contracts import Script
    video_id=db.uid()
    old={
        'title':'Teste narrativo','hook':'Um gancho curto','template':'gta-news',
        'duration':12,'description':'','hashtags':[],
        'scenes':[
            {'start':0,'end':4,'text':'Fato um','narration':'Primeira cena correta.','source_id':video_id},
            {'start':4,'end':8,'text':'Fato dois','narration':'Segunda cena precisa de ajuste.','source_id':video_id},
            {'start':8,'end':12,'text':'Fato três','narration':'Terceira cena correta.','source_id':video_id},
        ]}
    before=Script.model_validate(old)
    path=db.ROOT/'handoff'/video_id/'script-attempt-1.json'
    db.atomic(path,before.model_dump_json(indent=2))
    revised=before.model_dump()
    for row in revised['scenes']:
        row['text']='Alterado por IA'
        row['narration']='Novo texto indiscriminado.'
    after=preserve_unaffected_scenes(video_id,Script.model_validate(revised),
              {'issues':[{'criterion':'audio','evidence':'áudio truncado na cena 2, 6s'}]},1)
    assert after.scenes[0].narration=='Primeira cena correta.'
    assert after.scenes[1].narration=='Novo texto indiscriminado.'
    assert after.scenes[2].narration=='Terceira cena correta.'
    assert (db.ROOT/'handoff'/video_id/'surgical-attempt-2.json').is_file()
