"""Pessoa is a local, optional checklist, never an OmniRoute dependency."""
from backend.evaluation import local_viewer_checklist
from backend.contracts import Script


def test_pessoa_checklist_does_not_invent_audience_scores():
    script = Script.model_validate({
        'title':'GTA seis - teste', 'hook':'Uma novidade foi divulgada',
        'template':'gta-news','duration':40,'description':'','hashtags':[],
        'scenes': [
            {'start':0,'end':20,'text':'O anúncio','narration':'Há uma notícia.',
             'source_id':'a'*32},
            {'start':20,'end':40,'text':'Contexto','narration':'Confira a fonte.',
             'source_id':'a'*32},
        ]
    })
    viewer=local_viewer_checklist(script)
    assert set(viewer)=={'hook','clarity','pacing'}
    assert '2/2 cenas' in viewer['clarity']['evidence']
    assert all(item['score'] is None and item['passed'] is None
               and item['informational'] for item in viewer.values())
