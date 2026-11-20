'use client';
import {useEffect,useState} from 'react';
import {AlertTriangle,Clock3,RotateCcw,Trash2} from 'lucide-react';

type Row=Record<string,any>;
type Props={token:string;videos:Row[];onChanged:()=>Promise<unknown>;onError:(msg:string)=>void};
async function api(token:string,path:string,body?:unknown,method='GET'){
  const r=await fetch('/api/'+path,{method,cache:'no-store',
    headers:{Authorization:'Bearer '+token,
      ...(body!==undefined?{'Content-Type':'application/json'}:{})},
    body:body!==undefined?JSON.stringify(body):undefined});
  if(!r.ok){const x=await r.json().catch(()=>({detail:'HTTP '+r.status}));
    throw Error(x.detail||'Erro de exclusão.');}
  return r.json();
}
function countdown(stamp:number,now:number){
  const remaining=Math.max(0,7200-(now-stamp));
  const h=Math.floor(remaining/3600),m=Math.floor(remaining%3600/60),
    s=Math.floor(remaining%60);
  return remaining===0?'Exclusão pendente de limpeza':
    'Exclui em '+h+'h '+String(m).padStart(2,'0')+
    'min '+String(s).padStart(2,'0')+'s';
}
export default function VideoCleanupPanel({token,videos,onChanged,onError}:Props){
  const [confirm,setConfirm]=useState<Row|null>(null);
  const [now,setNow]=useState(Date.now()/1000);
  const [busy,setBusy]=useState(false);
  const [message,setMessage]=useState('');
  useEffect(()=>{
    const interval=setInterval(()=>setNow(Date.now()/1000),1000);
    return()=>clearInterval(interval);
  },[]);
  async function begin(){
    setBusy(true);setMessage('');
    try{setConfirm(await api(token,'videos/deletion-preview'))}
    catch(e){onError((e as Error).message)}
    finally{setBusy(false)}
  }
  async function clear(){
    if(!confirm)return;
    setBusy(true);setMessage('');
    try{
      const result=await api(token,'videos/clear',{
        expected_total:confirm.total,confirmation:'EXCLUIR_TUDO'
      },'POST');
      setConfirm(null);await onChanged();
      setMessage(result.deleted+' vídeos excluídos · '+
        (result.freed_bytes/1024**3).toFixed(3)+' GB liberados'+
        (result.pending?' · '+result.pending+' ainda em cancelamento seguro':''));
      if(result.errors?.length)onError(
        'Não foi possível remover alguns arquivos: '+result.errors.length+' pendências.');
    }catch(e){onError((e as Error).message)}
    finally{setBusy(false)}
  }
  async function restore(id:string){
    setBusy(true);setMessage('');
    try{
      await api(token,'videos/'+id+'/restore',{},'POST');
      await onChanged();setMessage('Restauração confirmada; exclusão cancelada.');
    }catch(e){onError((e as Error).message)}
    finally{setBusy(false)}
  }
  const discarded=videos.filter(v=>v.discarded_at||v.status==='DELETING');
  return <div className="video-cleanup">
    <button className="danger" disabled={busy} onClick={()=>void begin()}>
      <Trash2 size={15}/> Limpar lista
    </button>
    {message&&<p className="muted">{message}</p>}
    {discarded.length>0&&<details className="video-cleanup-discarded">
      <summary><Clock3 size={14}/> Descartados e exclusões pendentes ({discarded.length})</summary>
      {discarded.map(v=><div key={v.id} className="list-row">
        <div><strong>{v.title||v.id}</strong>
          <small>{v.status==='DELETING'?'Cancelando processos antes da exclusão':
            countdown(Number(v.discarded_at||0),now)}</small>
        </div>
        {v.status==='DISCARDED'&&v.discarded_at&&now-v.discarded_at<7200&&
          <button disabled={busy} onClick={()=>void restore(v.id)}>
            <RotateCcw size={13}/> Restaurar
          </button>}
      </div>)}
    </details>}
    {confirm&&<div className="cleanup-confirmation" role="dialog" aria-modal="true"
      aria-label="Confirmação de exclusão permanente">
      <div className="cleanup-confirm-inner">
        <h3><AlertTriangle size={17}/> Exclusão permanente</h3>
        <p>Excluir <strong>{confirm.total} vídeos</strong>? Aprovados: {confirm.counts.approved} ·
          Pendentes: {confirm.counts.pending} ·
          Em render: {confirm.counts.rendering} ·
          Reprovados/descartados: {confirm.counts.rejected_discarded}.
        </p>
        <p className="muted">MP4s e arquivos temporários privados serão apagados. Fontes
          compartilhadas e registros de direitos serão preservados. Produções
          executando serão canceladas primeiro; seus arquivos só sairão após o worker parar.</p>
        <div className="actions">
          <button onClick={()=>setConfirm(null)} disabled={busy}>Cancelar</button>
          <button className="danger" onClick={()=>void clear()} disabled={busy}>
            Excluir tudo
          </button>
        </div>
      </div>
    </div>}
  </div>;
}
