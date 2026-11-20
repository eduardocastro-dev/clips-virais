'use client';
import {useCallback,useEffect,useState} from 'react';
import {RefreshCw,ShieldCheck} from 'lucide-react';
import LiveStudioPanel from './live-studio-panel';

type Row=Record<string,any>;
type Props={token:string;mode:'radar'|'cuts'};
async function call(token:string,path:string,body?:unknown,method='GET'){
  const r=await fetch('/api/'+path,{method,cache:'no-store',
    headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},
    body:body?JSON.stringify(body):undefined});
  if(!r.ok){
    let msg='Falha HTTP '+r.status;
    try{const j=await r.json();msg=String(j.detail||msg)}catch{}
    throw Error(msg);
  }
  return r.json();
}
export default function RadarOps({token,mode}:Props){
  const [quota,setQuota]=useState<Row|null>(null);
  const [creators,setCreators]=useState<Row>({channels:[]});
  const [radar,setRadar]=useState<Row>({radar:{top:[]},recent_lives:{items:[]}});
  const [allow,setAllow]=useState<Row>({channels:[]});
  const [channelId,setChannelId]=useState('');
  const [rightsEvidence,setRightsEvidence]=useState('');
  const [manualLiveUrl,setManualLiveUrl]=useState('');
  const [manualLiveEvidence,setManualLiveEvidence]=useState('');
  const [webcamAnchor,setWebcamAnchor]=useState('bottom_left');
  const [sourceToAuthorize,setSourceToAuthorize]=useState('');
  const [sourceEvidence,setSourceEvidence]=useState('');
  const [deadline,setDeadline]=useState('23:59');
  const [minLiveScore,setMinLiveScore]=useState(70);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const refresh=useCallback(async()=>{
    const entries=await Promise.all([
      call(token,'daily-quota'),call(token,'viral-radar/top-creators'),
      call(token,'viral-radar/latest'),call(token,'clipping-allowlist')
    ]);
    setQuota(entries[0]);setCreators(entries[1]);setRadar(entries[2]);
    setAllow(entries[3]);
    setDeadline(entries[0]?.config?.deadline_local||'23:59');
    setMinLiveScore(entries[0]?.config?.min_live_score||70);
  },[token]);
  useEffect(()=>{refresh().catch(e=>setError(e.message))},[refresh]);
  async function act(path:string,body?:unknown,method='POST',success='Alteração registrada.'){
    setBusy(true);setError('');setNotice('');
    try{await call(token,path,body,method);await refresh();setNotice(success)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function submitManualLive(e:React.FormEvent<HTMLFormElement>){
    e.preventDefault();setBusy(true);setError('');setNotice('');
    try{
      const outcome=await call(token,'live-clips/from-url',{
        url:manualLiveUrl.trim(), evidence:manualLiveEvidence.trim(),
        webcam_anchor:webcamAnchor
      },'POST');
      await refresh();
      setNotice(outcome.message||'Live encaminhada à fila de cortes.');
      setManualLiveUrl('');setManualLiveEvidence('');
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function submitRadarLive(live:Row,permission:string){
    setBusy(true);setError('');setNotice('');
    try{
      const outcome=await call(token,'live-clips/from-url',{
        url:live.url,evidence:permission,webcam_anchor:webcamAnchor
      },'POST');
      await refresh();
      setSourceToAuthorize('');setSourceEvidence('');
      setNotice(outcome.message||'Três cortes da live encaminhados ao worker.');
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const shortCount=quota?.approved?.shorts||0;
  const liveCount=quota?.approved?.lives_cuts||0;
  const failures:Row[]=quota?.failures??[];
  return <div className="radar-ops">
    <section className="panel">
      <div className="section-title"><h2>Cota diária · GTA Studio</h2><button disabled={busy} onClick={()=>refresh().catch(e=>setError(e.message))}><RefreshCw size={14}/> Atualizar</button></div>
      <div className="radar-quota-grid">
        <div><strong>{shortCount} / {quota?.target?.shorts??'—'}</strong><small>Shorts · meta = Vídeos por dia</small></div>
        <div><strong>{liveCount} / 5</strong><small>Cortes de lives aprovados</small></div>
        <div><strong>{quota?.status||'CARREGANDO'}</strong><small>Status do dia</small></div>
        <div><strong>{quota?.pending?.shorts||0} + {quota?.pending?.lives_cuts||0}</strong><small>Itens pendentes</small></div>
      </div>
      <form className="radar-deadline" onSubmit={e=>{e.preventDefault();act('daily-quota/deadline',{deadline_local:deadline},'PUT','Horário limite atualizado.')}}>
        <label>Encerrar produção às (24h) <input type="time" required value={deadline} onChange={e=>setDeadline(e.target.value)}/></label>
        <button disabled={busy}>Salvar limite</button>
      </form>
      <form className="radar-deadline" onSubmit={e=>{e.preventDefault();act('daily-quota/live-score',{min_live_score:minLiveScore},'PUT','Pontuação mínima atualizada.')}}>
        <label>Score mínimo de corte (60–100) <input type="number" min={60} max={100} required value={minLiveScore} onChange={e=>setMinLiveScore(Number(e.target.value))}/></label>
        <button disabled={busy}>Salvar critério</button>
      </form>
      <p className="muted"><strong>Status dos cortes:</strong> {quota?.live_clip_scheduler_status||'Aguardando processamento.'}</p>
      <p className="muted">Um item só conta após validação automática e disponibilização para revisão humana. Nenhuma postagem é feita automaticamente. Tentativas por item: até três nas filas automáticas de cota.</p>
      {failures.length>0&&<details><summary>Falhas registradas ({failures.length})</summary><ul>{failures.map((f:Row,i:number)=><li key={i}>{f.kind}: {f.reason}</li>)}</ul></details>}
    </section>
    {error&&<p className="banner error" role="alert">{error}</p>}
    {notice&&<p className="banner" role="status">{notice}</p>}
    {mode==='radar'?<>
      <section className="panel">
        <div className="section-title"><h2>Top criadores do YouTube</h2><button disabled={busy} onClick={()=>act('viral-radar/top-creators/refresh',undefined,'POST','Atualização do ranking enviada ao worker.')}><RefreshCw size={14}/> Atualizar top 20</button></div>
        <p className="muted">Ranking baseado em fontes públicas; quando configuradas, as integrações do YouTube fornecem metadados oficiais. IDs e inscritos dependem da disponibilidade real. A lista pode ser parcial. Última atualização: {creators.updated_at||'pendente'}. Identificados pelo ranking: {creators.verified_count||0}.</p>
        {(!creators.channels||!creators.channels.length)&&<p>Nenhum canal disponível. Adicione um canal UC manualmente ou atualize o ranking público.</p>}
        <div className="radar-creator-grid">{(creators.channels||[]).map((c:Row)=><article key={c.channel_id}>
          <strong>{c.rank?c.rank+'º · ':''}{c.name}</strong><small>{c.country||'País não disponível'} · {c.language||'Idioma não disponível'}</small>
          <small>{typeof c.subscribers==='number'?c.subscribers.toLocaleString('pt-BR')+' inscritos':'Inscritos não disponíveis'}</small>
        </article>)}</div>
        <form className="radar-deadline" onSubmit={e=>{e.preventDefault();act('viral-radar/channels',{channel_id:channelId},'POST','Canal adicionado à lista.')}}>
          <label>Adicionar canal manualmente (ID UC...) <input value={channelId} onChange={e=>setChannelId(e.target.value)} placeholder="UCxxxxxxxxxxxxxxxxxxxxxx" required/></label>
          <button disabled={busy}>Adicionar</button>
        </form>
      </section>
      <section className="panel">
        <div className="section-title"><h2>Radar viral · últimos 30 dias</h2><button disabled={busy} onClick={()=>act('viral-radar/scan',undefined,'POST','Nova consulta pública agendada.')}><RefreshCw size={14}/> Pesquisar vídeos e lives</button></div>
        <p className="muted">O score usa métricas verificáveis; a chave de API e o login Google são opcionais e podem ampliar os dados disponíveis. Consulta pública não concede licença.</p>
        {(radar.radar?.top||[]).slice(0,25).map((item:Row)=><div className="radar-result" key={item.id}>
          <strong>{item.title}</strong>
          <small>{item.creator} · {item.score??'indisponível'}/100 · publicado {item.published_at?.slice(0,10)}</small>
          <small>{item.reason}</small>
          <a href={item.url} target="_blank" rel="noopener noreferrer">Abrir fonte pública</a>
        </div>)}
        {!radar.radar?.top?.length&&<p className="muted">Nenhuma análise disponível. Atualize o ranking ou adicione canais UC e execute a pesquisa pública.</p>}
      </section>
    </>:<>
      <section className="panel">
        <h2>Enviar link de live · gerar três cortes distintos</h2>
        <p className="muted">Cole o link de um VOD público já encerrado (últimos 30 dias). O sistema consulta a API quando configurada (ou tenta a consulta pública), e produz três cortes distintos acompanhados no Video Studio; nenhuma postagem é automática. A reutilização exige autorização do titular.</p>
        <form className="radar-allowlist" onSubmit={submitManualLive}>
          <label>URL da live encerrada
            <input type="url" required placeholder="https://www.youtube.com/live/..."
              value={manualLiveUrl} onChange={e=>setManualLiveUrl(e.target.value)}/>
          </label>
          <label>Autorização de reutilização da live (obrigatória se o canal ainda não estiver autorizado)
            <textarea rows={3} maxLength={2000} value={manualLiveEvidence}
              onChange={e=>setManualLiveEvidence(e.target.value)}
              placeholder="Link ou termos de permissão do criador para produzir e publicar cortes"/>
          </label>
          <label>Posição da webcam no vídeo-fonte
            <select value={webcamAnchor} onChange={e=>setWebcamAnchor(e.target.value)}>
              <option value="bottom_left">Inferior esquerdo (Patife)</option>
              <option value="top_left">Superior esquerdo</option>
              <option value="bottom_right">Inferior direito</option>
              <option value="top_right">Superior direito</option>
            </select>
          </label>
          <button className="primary" type="submit" disabled={busy||!manualLiveUrl.trim()}>Enviar live · gerar 3 cortes</button>
        </form>
      </section>
      <section className="panel">
        <h2>Permissões para cortes de lives</h2>
        <p className="muted">Só é permitido baixar e editar lives de canais incluídos explicitamente na allowlist com evidência de autorização de uso. Um vídeo público não autoriza cortes por si só.</p>
        <form className="radar-allowlist" onSubmit={e=>{e.preventDefault();act('clipping-allowlist',{channel_id:channelId,evidence:rightsEvidence},'POST','Permissão do canal registrada.')}}>
          <label>Channel ID oficial<input value={channelId} onChange={e=>setChannelId(e.target.value)} placeholder="UCxxxxxxxxxxxxxxxxxxxxxx" required/></label>
          <label>Comprovação da licença<textarea required minLength={15} rows={3} value={rightsEvidence} onChange={e=>setRightsEvidence(e.target.value)} placeholder="Link, termos, licença e escopo de uso autorizado para cortes"/></label>
          <button disabled={busy}><ShieldCheck size={15}/> Autorizar canal</button>
        </form>
        {(allow.channels||[]).map((item:Row)=><div key={item.channel_id} className="radar-result">
          <strong>{item.channel_id}</strong><small>{item.video_id?'Autorização apenas da live '+item.video_id:'Autorização do canal inteiro'} · {item.status} · {item.evidence}</small>
          <button disabled={busy} onClick={()=>act(
            'clipping-allowlist/'+item.channel_id+
             (item.video_id?'/live/'+item.video_id:''),
            undefined,'DELETE','Autorização revogada.')}>
            {item.video_id?'Revogar apenas esta live':'Revogar canal'}
          </button>
        </div>)}
      </section>
      <section className="panel">
        <div className="section-title"><h2>Lives públicas encerradas (M−1)</h2><button disabled={busy} onClick={()=>act('viral-radar/scan',undefined,'POST','Pesquisa agendada.')}><RefreshCw size={14}/> Reescanear</button></div>
        {(radar.recent_lives?.items||[]).slice(0,30).map((l:Row)=><div className="radar-result" key={l.id}>
          <strong>{l.title}</strong><small>{l.creator} · {l.published_at?.slice(0,10)} · score {l.score}</small>
          <small>{(allow.channels||[]).some((a:Row)=>a.channel_id===l.channel_id&&(!a.video_id||a.video_id===l.id))?'Autorização declarada':'Aguardando autorização de corte'}</small>
          <a href={l.url} target="_blank" rel="noopener noreferrer">Assistir ao VOD original</a>
          {(allow.channels||[]).some((a:Row)=>a.channel_id===l.channel_id&&(!a.video_id||a.video_id===l.id))
            ?<button disabled={busy} onClick={()=>void submitRadarLive(l,'')}>Gerar 3 cortes desta live</button>
            :<div className="live-source-authorization">
              <button type="button" disabled={busy}
                onClick={()=>setSourceToAuthorize(sourceToAuthorize===l.id?'':l.id)}>
                <ShieldCheck size={14}/> Incluir autorização e gerar 3 cortes
              </button>
              {sourceToAuthorize===l.id&&<form onSubmit={e=>{e.preventDefault();
                void submitRadarLive(l,sourceEvidence.trim())}}>
                <label>Comprovação de permissão do criador para reutilizar a transmissão
                  <textarea required minLength={15} maxLength={2000} rows={3}
                    placeholder="Link ou licença que autorize produção e publicação de cortes"
                    value={sourceEvidence} onChange={e=>setSourceEvidence(e.target.value)}/>
                </label>
                <button disabled={busy||sourceEvidence.trim().length<15} type="submit">
                  Registrar autorização e iniciar produção
                </button>
              </form>}
            </div>}
        </div>)}
        {!radar.recent_lives?.items?.length&&<p className="muted">Nenhuma live pública encerrada foi identificada neste período.</p>}
      </section>
      <LiveStudioPanel token={token}/>
    </>}
  </div>;
}
