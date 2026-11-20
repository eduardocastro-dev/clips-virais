"""A human discard must not be re-selected by the automatic writer."""
import json
import time

from backend import core as db, deletion, editorial_rejections as er, worker


def _video(ident='a'*32, *, source='https://www.youtube.com/watch?v=abcdefghijk',
           title='GTA 6: mapa de Vice City revela detalhes inéditos'):
    now=time.time()
    db.execute("""INSERT INTO videos
        (id,run_id,url,platform,title,status,approved,metadata,
         created,updated,test,rights,template)
        VALUES (:id,'run',:url,'youtube',:title,'AWAITING_MANUAL_DECISION',0,
                :meta,:now,:now,0,'REFERENCE_ONLY','gta-news')""",
        {'id':ident,'url':source,'title':title,
         'meta':json.dumps({'title':title}),'now':now})
    return ident


def _opportunity(number, title, score=85):
    video_id=f'{number:011d}'
    url='https://www.youtube.com/shorts/'+video_id
    db.execute("""INSERT INTO opportunities
         (id,url,platform,title,metadata,score,created)
         VALUES (:id,:url,'youtube',:title,:meta,:score,:created)""",
         {'id':'op-'+video_id,'url':url,'title':title,
          'meta':json.dumps({'title':title,'url':url,'platform':'youtube'}),
          'score':score,'created':time.time()})
    return video_id


def test_manual_discard_blocks_source_and_near_identical_topic_after_purge(client):
    ident=_video()
    response=client.post('/api/videos/'+ident+'/decision',json={'action':'discard'})
    assert response.status_code==200,response.text
    assert er.blocked('https://www.youtube.com/shorts/abcdefghijk',None)['reason']=='same_source'
    assert er.blocked('https://www.youtube.com/watch?v=zzzzzzzzzzz',
                      'GTA VI — detalhes do mapa de Vice City')['reason']=='same_topic'
    assert er.blocked('https://www.youtube.com/watch?v=zzzzzzzzzzz',
                      'GTA VI: trailer da Lucia') is None
    db.execute('UPDATE videos SET discarded_at=:past WHERE id=:id',
               {'past':time.time()-7300,'id':ident})
    assert deletion.purge_due()['deleted']==1
    assert db.rows('SELECT id FROM videos WHERE id=:id',{'id':ident})==[]
    assert er.blocked('https://www.youtube.com/watch?v=abcdefghijk',
                      'Mapa GTA VI de Vice City')['reason']=='same_source'


def test_restoring_discarded_video_lifts_only_its_veto(client):
    ident=_video()
    assert client.post('/api/videos/'+ident+'/decision',
                       json={'action':'discard'}).status_code==200
    assert len(er.active())==1
    assert client.post('/api/videos/'+ident+'/restore',json={}).status_code==200
    assert er.active()==[]


def test_queue_skips_discards_but_keeps_unrelated_news(client):
    ident=_video()
    assert client.post('/api/videos/'+ident+'/decision',
                       json={'action':'discard'}).status_code==200
    _opportunity(1,'GTA VI: detalhes inéditos do mapa de Vice City',score=99)
    _opportunity(2,'GTA VI — trailer da Lucia ganha nova cena',score=91)
    config=db.settings()
    config.automatic=True
    config.daily_limit=3
    db.put_setting('settings',config.model_dump())
    outcome=worker.queue_opportunities()
    assert outcome['queued'] and outcome['avoided']==1
    rows=db.rows("SELECT url FROM videos WHERE status='QUEUED'")
    assert len(rows)==1
    assert rows[0]['url'].endswith('00000000002')
    # Never generate a second job for the previously rejected subject.
    assert worker.queue_opportunities()['queued'] is False
    assert db.rows("SELECT COUNT(*) AS n FROM videos WHERE status='QUEUED'")[0]['n']==1


def test_discards_do_not_starve_candidacy_after_first_thirty(client):
    ident=_video()
    assert client.post('/api/videos/'+ident+'/decision',
                       json={'action':'discard'}).status_code==200
    for i in range(1,41):
        _opportunity(i,'Novos detalhes do mapa de Vice City em GTA 6',score=100-i/100)
    _opportunity(41,'GTA VI: Lucia no trailer com novas imagens',score=50)
    config=db.settings()
    config.automatic=True
    config.daily_limit=3
    db.put_setting('settings',config.model_dump())
    outcome=worker.queue_opportunities()
    assert outcome['queued'] and outcome['avoided']==40
    queued=db.rows("SELECT url FROM videos WHERE status='QUEUED'")
    assert len(queued)==1 and queued[0]['url'].endswith('00000000041')


def test_technical_failure_or_full_clear_does_not_block_subject(client):
    ident=_video()
    deletion.mark_discarded(ident,reason='esgotou tentativas técnicas')
    assert er.active()==[]
    deletion.request_clear_all(1)
    assert er.active()==[]


def test_early_manual_discard_records_title_from_opportunity(client):
    video_id='c'*32
    _video(video_id,source='https://www.youtube.com/watch?v=00000000017',
           title='Aguardando pesquisa')
    _opportunity(17,'GTA 6: comparativo do mapa de Vice City',score=99)
    response=client.post('/api/videos/'+video_id+'/decision',
                         json={'action':'discard'})
    assert response.status_code==200
    assert er.blocked('https://www.youtube.com/watch?v=00000000018',
                      'Vice City: comparativo do mapa de GTA VI') is not None


def test_legacy_purged_manual_discard_log_is_imported_once(client):
    old='f'*32
    log=db.DATA/'deletion_log.json'
    log.write_text(json.dumps({'entries':[
        {'id':old,'title':'GTA 6: detalhes do mapa de Vice City',
         'reason':'manual','discarded_at':time.time()-60},
        {'id':'e'*32,'title':'GTA VI: trailer da Lucia',
         'reason':'esgotou tentativas técnicas','discarded_at':time.time()-60}
    ]}),encoding='utf-8')
    assert er.blocked('https://www.youtube.com/watch?v=00000000018',
                      'GTA VI revela detalhes do mapa Vice City')
    assert er.blocked('https://www.youtube.com/watch?v=00000000018',
                      'Lucia aparece em trailer de GTA 6') is None
    assert len(er.active())==1


def test_unblock_api_allows_operator_to_reuse_topic(client):
    ident=_video()
    assert client.post('/api/videos/'+ident+'/decision',
                       json={'action':'discard'}).status_code==200
    response=client.get('/api/editorial/rejections')
    assert response.status_code==200
    assert response.json()['cooldown_days']==30
    assert len(response.json()['items'])==1
    entry=response.json()['items'][0]['id']
    assert client.delete('/api/editorial/rejections/'+entry).status_code==200
    assert er.active()==[]


def test_generic_gta_6_does_not_block_unrelated_topics():
    assert er.topic_tokens('GTA 6')==frozenset()
    assert not er.same_topic('GTA 6', 'GTA 6: Lucia no trailer')
    assert not er.same_topic('GTA 6: mapa detalhado', 'GTA 6: gráficos realistas')


def test_unblocked_topic_stays_allowed_after_discard_media_purge(client):
    ident=_video('d'*32)
    assert client.post('/api/videos/'+ident+'/decision',
                       json={'action':'discard'}).status_code==200
    entry=client.get('/api/editorial/rejections').json()['items'][0]['id']
    assert client.delete('/api/editorial/rejections/'+entry).status_code==200
    db.execute('UPDATE videos SET discarded_at=:past WHERE id=:id',
               {'past':time.time()-7300,'id':ident})
    assert deletion.purge_due()['deleted']==1
    assert er.active()==[]
    assert er.blocked('https://www.youtube.com/shorts/abcdefghijk',
                      'GTA VI detalhes de Vice City mapa') is None
