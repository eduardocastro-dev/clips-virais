"""Per-platform copy-ready metadata; no network or extra LLM requests."""
import json
import time

import pytest

from backend import core as db, pipeline
from backend.seo import build_seo_package, normalize_editor_update
from backend.contracts import Script


@pytest.fixture
def approved_publications():
    video_id = pipeline.create_video(test=True)
    final = db.ROOT / 'videos' / 'final' / (video_id + '.mp4')
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(b'fixture')
    db.execute("UPDATE videos SET approved=1,status='APPROVED',final_path=:path WHERE id=:id",
               {'id':video_id,'path':str(final.relative_to(db.ROOT))})
    folder = db.ROOT / 'handoff' / video_id
    folder.mkdir(parents=True, exist_ok=True)
    script = Script(
        title='Detalhes do GTA 6 analisados', hook='Um detalhe chamou atenção',
        description='Explicamos o detalhe mostrado no material analisado.',
        hashtags=['GTA6','Games','gta6'], template='gta-news', duration=10,
        scenes=[
            {'start':0,'end':5,'text':'Detalhe','narration':'Um detalhe chamou a atenção dos jogadores.','source_id':video_id},
            {'start':5,'end':10,'text':'Discussão','narration':'Veja a fonte e diga o que achou.','source_id':video_id},
        ],
        cta='O que você achou desse detalhe?'
    )
    (folder/'script.json').write_text(script.model_dump_json(),encoding='utf-8')
    db.artifact(video_id,'avaliador',{'verdict':'APROVADO'})
    pipeline.distribute(video_id)
    return video_id,script


def test_platform_copy_is_specific_and_grounded():
    script = {
        'title':'Detalhes de GTA 6',
        'hook':'Olha este detalhe!',
        'description':'Analisamos a imagem divulgada, sem confirmar rumores.',
        'hashtags':['GTA6','#gta6','Games'],
        'cta':'Você concorda?'
    }
    video={'url':'https://example.com/source','credits':'Fonte: produção própria','test':False}
    items={platform:build_seo_package(script,video,platform)
           for platform in ('youtube','tiktok','instagram')}
    assert items['youtube']['platform']=='youtube'
    assert items['instagram']['platform']=='instagram'
    assert items['tiktok']['caption']!=items['youtube']['caption']
    for platform,item in items.items():
        assert item['title']
        assert len(item['title'])<=100
        assert len(item['caption'])<=({'youtube':5000,'tiktok':2200,'instagram':2200}[platform])
        assert 'https://example.com/source' in item['caption']
        assert 'produção própria' in item['caption']
        assert item['pinned_comment']=='Você concorda?'
        assert len([x.lower() for x in item['hashtags']])==len(set(x.lower() for x in item['hashtags']))
        assert item['generated_by']=='deterministic_script_seo_v1'
        assert item['mode']=='manual_copy_and_paste'


def test_unsupported_platform_fails():
    with pytest.raises(ValueError,match='Plataforma'):
        build_seo_package({}, {}, 'facebook')


def test_editor_update_keeps_verified_source_and_rejects_overlong_copy():
    initial=build_seo_package({'title':'GTA 6','description':'Fato presente no roteiro.'},
                              {'url':'https://example.com/original'},'youtube')
    edited=normalize_editor_update({
        'title':'GTA 6: veja o vídeo',
        'caption':'Nova legenda revisada #GTA6',
        'hashtags':['GTA6','gta6','Games'], 'tags':['GTA 6'],
        'pinned_comment':'E aí?', 'cover_text':'Novo detalhe'
    },'youtube',initial)
    assert edited['source_url']=='https://example.com/original'
    assert edited['hashtags']==['GTA6','Games']
    with pytest.raises(ValueError):
        normalize_editor_update({**edited,'caption':'x'*5001},'youtube',initial)


def test_seo_created_for_all_distributed_platforms(client,approved_publications):
    video_id,_=approved_publications
    pubs=db.rows('SELECT * FROM publications WHERE video_id=:id',{'id':video_id})
    assert {p['platform'] for p in pubs}=={'youtube','tiktok','instagram'}
    for pub in pubs:
        file=db.safe_file(str(__import__('pathlib').Path(pub['output_path']).parent /
                              f'metadata_{video_id}.json'))
        contents=json.loads(file.read_text('utf-8'))
        assert contents['seo']['platform']==pub['platform']
        response=client.get('/api/publications/'+pub['id']+'/seo')
        assert response.status_code==200
        seo=response.json()
        assert seo['test_only']
        assert seo['caption']
        assert seo['source_url']==''  # Synthetic test URLs are never published as sources.
        assert seo['pinned_comment']


def test_existing_metadata_is_backfilled_and_human_edits_persist(client,approved_publications):
    video_id,_=approved_publications
    pub=db.rows("SELECT * FROM publications WHERE video_id=:id AND platform='youtube'",{'id':video_id})[0]
    path=db.safe_file(str(__import__('pathlib').Path(pub['output_path']).parent /
                          f'metadata_{video_id}.json'))
    old=json.loads(path.read_text('utf-8'))
    old.pop('seo')
    db.atomic(path,json.dumps(old))
    url='/api/publications/'+pub['id']+'/seo'
    backfilled=client.get(url)
    assert backfilled.status_code==200
    payload=backfilled.json()
    update={key:payload[key] for key in ('title','caption','hashtags','tags','pinned_comment','cover_text')}
    update['title']='GTA 6 Brasil: uma novidade'
    update['caption']='Descrição revisada manualmente.'
    response=client.put(url,json=update)
    assert response.status_code==200,response.text
    assert response.json()['title']==update['title']
    assert client.get(url).json()['caption']==update['caption']
    assert json.loads(path.read_text('utf-8'))['seo']['caption']==update['caption']
    assert client.put(url,json={**update,'caption':'x'*5001}).status_code==422
    db.execute("UPDATE publications SET status='PUBLICADO' WHERE id=:id",{'id':pub['id']})
    assert client.put(url,json=update).status_code==409
