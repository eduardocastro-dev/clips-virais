'use client';

import {useCallback,useEffect,useState} from 'react';
import {CheckCircle2,Clapperboard,Clock3,Download,Eye,RefreshCw,ShieldCheck,Film} from 'lucide-react';

type Row=Record<string,any>;
type Props={token:string;embedded?:boolean;onActivityChange?:(active:{id:string;title:string}|null)=>void};
const anchors=[
  {value:'bottom_left',label:'Inferior esquerdo (Patife / padrão)'},
  {value:'top_left',label:'Superior esquerdo'},
  {value:'bottom_right',label:'Inferior direito'},
  {value:'top_right',label:'Superior direito'}
];

function humanStatus(value:string){
  return ({
    QUEUED:'Na fila',PROCESSING:'Editando',RETRY:'Nova tentativa',
    REVIEW_PENDING:'Pronto para sua revisão',APPROVED:'Aprovado para postagem manual',
    DISCARDED:'Descartado',FAILED:'Falha',
    BLOCKED:'Bloqueado'
  } as Record<string,string>)[value]||value||'Aguardando';
}
const stages=[
  ['VERIFYING','Validar origem'],
  ['DOWNLOADING_AUDIO','Baixar áudio'],
  ['ANALYZING_AUDIO','Analisar som'],
  ['TRANSCRIBING','Transcrever (WhisperX)'],
  ['SELECTING','Selecionar 3 momentos'],
  ['DOWNLOADING_EXCERPT','Preparar trechos'],
  ['RENDERING','Compor webcam/jogo'],
  ['VALIDATING','Validar áudio e vídeo'],
  ['READY_FOR_REVIEW','Revisão humana']
];
function stageName(stage:string){
  const match=/^(DOWNLOADING_EXCERPT|RENDERING|VALIDATING|RENDERED)_(\d+)$/.exec(stage||'');
  if(match)return ({
    DOWNLOADING_EXCERPT:'Obtendo fonte',RENDERING:'Montando layout',
    VALIDATING:'Validando',RENDERED:'Corte finalizado'
  } as Record<string,string>)[match[1]]+' · corte '+match[2]+'/3';
  return stages.find(x=>x[0]===stage)?.[1]||'Preparando produção';
}
async function api(token:string,path:string,body?:unknown,method='GET'){
  const res=await fetch('/api/'+path,{
    method,headers:{Authorization:'Bearer '+token,
      ...(body!==undefined?{'Content-Type':'application/json'}:{})},
    body:body!==undefined?JSON.stringify(body):undefined,cache:'no-store'
  });
  if(!res.ok){
    let msg='HTTP '+res.status;
    try{msg=(await res.json()).detail||msg}catch{}
    throw new Error(String(msg));
  }
  return res.json();
}
export default function LiveStudioPanel({token,embedded=false,onActivityChange}:Props){
  const [lives,setLives]=useState<Row[]>([]);
  const [busy,setBusy]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [selected,setSelected]=useState('');
  const [videoUrl,setVideoUrl]=useState('');
  const [positions,setPositions]=useState<Record<string,string>>({});
  const refresh=useCallback(async()=>{
    const result=await api(token,'live-clips');
    const items:Row[]=(result.items||[]).filter((live:Row)=>live.status!=='DISCARDED')
      .map((live:Row)=>({...live,outputs:(live.outputs||[])
        .filter((cut:Row)=>cut.status!=='DISCARDED')}));
    setLives(items);
    const active=items.find(live=>live.job?.status==='RUNNING');
    onActivityChange?.(active?{id:active.id,title:active.title}:null);
  },[token,onActivityChange]);
  useEffect(()=>{
    let alive=true;
    void refresh().catch(e=>{if(alive)setError(e.message)});
    const interval=setInterval(()=>{void refresh().catch(e=>{if(alive)setError(e.message)})},4000);
    return()=>{alive=false;clearInterval(interval)};
  },[refresh]);
  useEffect(()=>()=>{if(videoUrl)URL.revokeObjectURL(videoUrl)},[videoUrl]);
  useEffect(()=>{
    if(selected&&!lives.some(l=>l.outputs?.some((cut:Row)=>cut.id===selected))){
      setSelected('');
      setVideoUrl('');
    }
  },[selected,lives]);
  async function perform(label:string,fn:()=>Promise<unknown>,success:string){
    setBusy(label);setError('');setNotice('');
    try{await fn();await refresh();setNotice(success)}
    catch(e){setError((e as Error).message)}
    finally{setBusy('')}
  }
  async function openFile(parentId:string,outputId:string,download=false){
    await perform('file:'+outputId,async()=>{
      const response=await fetch('/api/live-clips/'+parentId+'/outputs/'+outputId+'/file',{
        headers:{Authorization:'Bearer '+token}
      });
      if(!response.ok)throw new Error('MP4 do corte não está disponível para visualização.');
      const url=URL.createObjectURL(await response.blob());
      if(download){
        const a=document.createElement('a');a.href=url;a.download='corte-'+outputId+'.mp4';
        document.body.appendChild(a);a.click();a.remove();
        setTimeout(()=>URL.revokeObjectURL(url),60000);
      }else{setVideoUrl(url);setSelected(outputId)}
    },download?'MP4 enviado para download.':'Revisão do corte aberta.');
  }
  async function copySeo(parentId:string,outputId:string){
    await perform('seo:'+outputId,async()=>{
      const m=await api(token,'live-clips/'+parentId+'/outputs/'+outputId+'/metadata');
      await navigator.clipboard.writeText(
        [m.title,m.description,(m.hashtags||[]).join(' ')].join('\n\n')
      );
    },'Título, descrição, créditos e hashtags copiados.');
  }
  return <section className={'panel live-studio '+(embedded?'live-studio-embedded':'')} aria-label="Pipeline de cortes de lives">
    <div className="section-title">
      <div><h2><Clapperboard size={18}/> Pipeline de lives · 3 cortes por transmissão</h2>
        <p className="muted">Transcrição única por live, cortes independentes e revisão individual. Atualização a cada 4s.</p>
      </div>
      <button disabled={Boolean(busy)} onClick={()=>refresh().catch(e=>setError(e.message))}>
        <RefreshCw size={14}/> Atualizar
      </button>
    </div>
    {error&&<p className="banner error" role="alert">{error}</p>}
    {notice&&<p className="banner" role="status">{notice}</p>}
    {!lives.length&&<p className="muted">Nenhuma live cadastrada. Envie um VOD em Cortes de Lives para iniciar a produção.</p>}
    {lives.map(live=>{
      const outputs:Row[]=live.outputs||[];
      const completed=live.completed_cuts||0;
      const expected=live.expected_cuts||3;
      const current=stageName(live.stage||'');
      const canRegenerate=!['QUEUED','PROCESSING','RETRY'].includes(live.status)&&
          !outputs.some(o=>o.status==='APPROVED');
      const anchor=positions[live.id]||live.webcam_anchor||'bottom_left';
      return <article className="live-production" key={live.id}>
        <div className="live-production-header">
          <div className="live-production-info">
            <strong>{live.title}</strong>
            <small>{humanStatus(live.status)} · {completed}/{expected} cortes avaliados · {outputs.length} visíveis · tentativas {live.attempts||0}/3</small>
            <small><Clock3 size={12}/> {current} · Layout: streamer em cima e gameplay embaixo</small>
            {live.job?.status==='RUNNING'&&<small className="live-active-dot"><span/> Worker executando agora</small>}
          </div>
          <a href={live.source_url} target="_blank" rel="noopener noreferrer">Assistir live original</a>
        </div>
        <div className="live-cuts-progress" aria-label={'Cortes concluídos: '+completed+' de '+expected}>
          {Array.from({length:expected},(_,i)=><span key={i}
            className={i<completed?'ready':''} title={'Corte '+(i+1)}/>)}
        </div>
        <div className="live-stage-track">
          {stages.map(([id,title],i)=>{
            const code=live.stage||'';
            const currentIndex=stages.findIndex(([key])=>code.startsWith(key));
            const done=i<currentIndex||code==='READY_FOR_REVIEW'||['REVIEW_PENDING','APPROVED'].includes(live.status);
            return <div className={done?'done':i===currentIndex?'active':''} key={id}>
              <span>{done?<CheckCircle2 size={12}/>:i+1}</span><small>{title}</small>
            </div>;
          })}
        </div>
        {live.error&&<p className="error live-error">{live.error}</p>}
        <div className="live-cut-children">
          {outputs.map((cut:Row)=><div className="live-cut-item" key={cut.id}>
            <div>
              <strong>Corte {cut.ordinal} / {expected}</strong>
              <small>{humanStatus(cut.status)} · {cut.score??'—'}/100 · {cut.segment_start!=null?cut.segment_start.toFixed(1)+'s–'+cut.segment_end.toFixed(1)+'s':'trecho ainda não marcado'}</small>
            </div>
            <div className="actions">
              {cut.file_path&&<button disabled={Boolean(busy)} onClick={()=>void openFile(live.id,cut.id)}>
                <Eye size={14}/> Assistir
              </button>}
              {cut.file_path&&<button disabled={Boolean(busy)} onClick={()=>void openFile(live.id,cut.id,true)}>
                <Download size={14}/> MP4
              </button>}
              {cut.file_path&&<button disabled={Boolean(busy)}
                onClick={()=>void copySeo(live.id,cut.id)}>Copiar SEO</button>}
              {cut.status==='REVIEW_PENDING'&&<>
                <button disabled={Boolean(busy)} onClick={()=>void perform(cut.id,
                  ()=>api(token,'live-clips/'+live.id+'/outputs/'+cut.id+'/decision',
                    {decision:'approve'},'POST'),'Corte aprovado para postagem manual.')}>
                  <ShieldCheck size={14}/> Aprovar
                </button>
                <button disabled={Boolean(busy)} onClick={()=>{
                  if(window.confirm('Descartar somente este corte da live?'))
                    void perform(cut.id,async()=>{
                      await api(token,'live-clips/'+live.id+'/outputs/'+cut.id+
                        '/decision',{decision:'discard'},'POST');
                      if(selected===cut.id){setSelected('');setVideoUrl('')}
                    },'Corte descartado, arquivos removidos e item retirado da lista.');
                }}>Descartar</button>
              </>}
            </div>
          </div>)}
          {!outputs.length&&<p className="muted">Os três cortes aparecerão aqui individualmente, assim que forem validados.</p>}
        </div>
        {canRegenerate&&<form className="live-reprocess" onSubmit={e=>{
          e.preventDefault();
          if(!window.confirm('Recriar três cortes com o layout selecionado? Os MP4s antigos permanecem preservados no disco.'))return;
          void perform('rerender:'+live.id,()=>api(token,'live-clips/'+live.id+
              '/reprocess',{webcam_anchor:anchor},'POST'),
            'Regeneração dos três cortes encaminhada ao worker.');
        }}>
          <label>Posição da webcam na live original
            <select value={anchor}
              onChange={e=>setPositions(prev=>({...prev,[live.id]:e.target.value}))}>
              {anchors.map(a=><option key={a.value} value={a.value}>{a.label}</option>)}
            </select>
          </label>
          <button disabled={Boolean(busy)} type="submit">
            <RefreshCw size={14}/> Regerar 3 cortes com webcam em cima
          </button>
        </form>}
        {selected&&outputs.some(x=>x.id===selected)&&videoUrl&&
          <div className="live-cut-preview">
            <strong>Prévia do corte selecionado</strong>
            <video controls playsInline preload="metadata" src={videoUrl}/>
            <button onClick={()=>{setVideoUrl('');setSelected('')}}>Fechar prévia</button>
          </div>}
      </article>;
    })}
  </section>;
}
