'use client';
import {useCallback,useEffect,useState} from 'react';
import {RefreshCw,ShieldCheck,Download,Clipboard} from 'lucide-react';

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
  const [cuts,setCuts]=useState<Row[]>([]);
  const [channelId,setChannelId]=useState('');
  const [rightsEvidence,setRightsEvidence]=useState('');
  const [deadline,setDeadline]=useState('23:59');
  const [minLiveScore,setMinLiveScore]=useState(70);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [busy,setBusy]=useState(false);
  const [videoUrl,setVideoUrl]=useState('');
  const [videoId,setVideoId]=useState('');
  const refresh=useCallback(async()=>{
    const entries=await Promise.all([
      call(token,'daily-quota'),call(token,'viral-radar/top-creators'),
      call(token,'viral-radar/latest'),call(token,'clipping-allowlist'),call(token,'live-clips')
    ]);
    setQuota(entries[0]);setCreators(entries[1]);setRadar(entries[2]);
    setAllow(entries[3]);setCuts(entries[4].items||[]);
    setDeadline(entries[0]?.config?.deadline_local||'23:59');
    setMinLiveScore(entries[0]?.config?.min_live_score||70);
  },[token]);
  useEffect(()=>{refresh().catch(e=>setError(e.message))},[refresh]);
  useEffect(()=>()=>{if(videoUrl)URL.revokeObjectURL(videoUrl)},[videoUrl]);
  async function act(path:string,body?:unknown,method='POST',success='Alteração registrada.'){
    setBusy(true);setError('');setNotice('');
    try{await call(token,path,body,method);await refresh();setNotice(success)}
    catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  async function preview(id:string,download=false){
    setError('');setBusy(true);
    try{
      const r=await fetch('/api/live-clips/'+id+'/file',{headers:{Authorization:'Bearer '+token}});
      if(!r.ok)throw Error('Arquivo de vídeo indisponível: HTTP '+r.status);
      const url=URL.createObjectURL(await r.blob());
      if(download){
        const a=document.createElement('a');a.href=url;a.download='corte-live-'+id+'.mp4';
        document.body.appendChild(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),120000);
      }else{setVideoUrl(url);setVideoId(id)}
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const shortCount=quota?.approved?.shorts||0;
  const liveCount=quota?.approved?.lives_cuts||0;
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
      {quota?.failures?.length>0&&<details><summary>Falhas registradas ({quota.failures.length})</summary><ul>{quota.failures.map((f:Row,i:number)=><li key={i}>{f.kind}: {f.reason}</li>)}</ul></details>}
    </section>
    {error&&<p className="banner error" role="alert">{error}</p>}
    {notice&&<p className="banner" role="status">{notice}</p>}
    {mode==='radar'?<>
      <section className="panel">
        <div className="section-title"><h2>Top criadores do YouTube</h2><button disabled={busy} onClick={()=>act('viral-radar/top-creators/refresh',undefined,'POST','Atualização do ranking enviada ao worker.')}><RefreshCw size={14}/> Atualizar top 20</button></div>
        <p className="muted">Ranking público atualizado mensalmente, identificado pela API oficial do YouTube. Não é uma lista fixa. Última atualização: {creators.updated_at||'pendente'}. Verificados: {creators.verified_count||0}.</p>
        {(!creators.channels||!creators.channels.length)&&<p>Nenhum canal verificado. Configure a chave YouTube Data API e clique em Atualizar top 20.</p>}
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
        <p className="muted">O score considera views/hora, curtidas/views, comentários/views e desempenho frente à mediana recente do próprio canal. Dados públicos não concedem licença de reutilização.</p>
        {(radar.radar?.top||[]).slice(0,25).map((item:Row)=><div className="radar-result" key={item.id}>
          <strong>{item.title}</strong>
          <small>{item.creator} · {item.score}/100 · publicado {item.published_at?.slice(0,10)}</small>
          <small>{item.reason}</small>
          <a href={item.url} target="_blank" rel="noopener noreferrer">Abrir fonte pública</a>
        </div>)}
        {!radar.radar?.top?.length&&<p className="muted">Nenhuma análise disponível. Configure a API e execute a pesquisa.</p>}
      </section>
    </>:<>
      <section className="panel">
        <h2>Permissões para cortes de lives</h2>
        <p className="muted">Só é permitido baixar e editar lives de canais incluídos explicitamente na allowlist com evidência de autorização de uso. Um vídeo público não autoriza cortes por si só.</p>
        <form className="radar-allowlist" onSubmit={e=>{e.preventDefault();act('clipping-allowlist',{channel_id:channelId,evidence:rightsEvidence},'POST','Permissão do canal registrada.')}}>
          <label>Channel ID oficial<input value={channelId} onChange={e=>setChannelId(e.target.value)} placeholder="UCxxxxxxxxxxxxxxxxxxxxxx" required/></label>
          <label>Comprovação da licença<textarea required minLength={15} rows={3} value={rightsEvidence} onChange={e=>setRightsEvidence(e.target.value)} placeholder="Link, termos, licença e escopo de uso autorizado para cortes"/></label>
          <button disabled={busy}><ShieldCheck size={15}/> Autorizar canal</button>
        </form>
        {(allow.channels||[]).map((item:Row)=><div key={item.channel_id} className="radar-result">
          <strong>{item.channel_id}</strong><small>{item.status} · {item.evidence}</small>
          <button disabled={busy} onClick={()=>act('clipping-allowlist/'+item.channel_id,undefined,'DELETE','Autorização revogada.')}>Revogar</button>
        </div>)}
      </section>
      <section className="panel">
        <div className="section-title"><h2>Lives públicas encerradas (M−1)</h2><button disabled={busy} onClick={()=>act('viral-radar/scan',undefined,'POST','Pesquisa agendada.')}><RefreshCw size={14}/> Reescanear</button></div>
        {(radar.recent_lives?.items||[]).slice(0,30).map((l:Row)=><div className="radar-result" key={l.id}>
          <strong>{l.title}</strong><small>{l.creator} · {l.published_at?.slice(0,10)} · score {l.score}</small>
          <small>{(allow.channels||[]).some((a:Row)=>a.channel_id===l.channel_id)?'Autorização declarada':'Aguardando autorização de corte'}</small>
          <a href={l.url} target="_blank" rel="noopener noreferrer">Assistir ao VOD original</a>
        </div>)}
        {!radar.recent_lives?.items?.length&&<p className="muted">Nenhuma live pública encerrada foi identificada neste período.</p>}
      </section>
      <section className="panel">
        <h2>Cortes para revisão humana</h2>
        {!cuts.length&&<p className="muted">Nenhum corte iniciado. O worker busca apenas lives recentes, encerradas e autorizadas.</p>}
        {cuts.map((item:Row)=><div className="radar-result" key={item.id}>
          <strong>{item.title}</strong>
          <small>Status {item.status} · nota {item.score??'não avaliado'}/100 · tentativas {item.attempts||0}/3</small>
          {item.error&&<p className="error">{item.error}</p>}
          {item.status==='REVIEW_PENDING'&&<div className="actions">
            <button disabled={busy} onClick={()=>act('live-clips/'+item.id+'/decision',{decision:'approve'},'POST','Corte revisado e aprovado manualmente.')}>Aprovar para postagem manual</button>
            <button disabled={busy} onClick={()=>{if(window.confirm('Descartar este corte? O MP4 permanece no histórico.'))act('live-clips/'+item.id+'/decision',{decision:'discard'},'POST','Corte descartado da fila.')}}>Descartar</button>
          </div>}
          {item.file_path&&<div className="actions">
            <button disabled={busy} onClick={()=>preview(item.id)}><Clipboard size={14}/> Revisar</button>
            <button disabled={busy} onClick={()=>preview(item.id,true)}><Download size={14}/> Baixar MP4</button>
            <button onClick={()=>call(token,'live-clips/'+item.id+'/metadata').then(m=>navigator.clipboard.writeText([m.title,m.description,(m.hashtags||[]).join(' ')].join('\n\n'))).then(()=>setNotice('Texto da postagem copiado.')).catch(e=>setError(e.message))}><Clipboard size={14}/> Copiar texto</button>
          </div>}
        </div>)}
        {videoUrl&&<div className="radar-player"><strong>Revisando corte {videoId}</strong><video src={videoUrl} controls playsInline preload="metadata"/><button onClick={()=>setVideoUrl('')}>Fechar prévia</button></div>}
      </section>
    </>}
  </div>;
}
