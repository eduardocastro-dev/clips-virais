'use client';
import {useCallback,useEffect,useState} from 'react';
import {ShieldX,RotateCcw,RefreshCw} from 'lucide-react';

type Veto={id:string;title:string;source_url:string;created:number;expires_at:number};
type Response={items:Veto[];cooldown_days:number};

export default function EditorialRejectionsPanel({token}:{token:string}){
  const [data,setData]=useState<Response|null>(null);
  const [error,setError]=useState('');
  const [busy,setBusy]=useState<string|null>(null);
  const refresh=useCallback(async()=>{
    const response=await fetch('/api/editorial/rejections',{cache:'no-store',
      headers:{Authorization:'Bearer '+token}});
    if(!response.ok)throw new Error('Não foi possível consultar os temas descartados.');
    setData(await response.json());
  },[token]);
  useEffect(()=>{void refresh().catch(e=>setError((e as Error).message))},[refresh]);

  async function unblock(item:Veto){
    if(!window.confirm('Liberar novamente o tema/fonte "'+item.title+'"? A IA poderá voltar a selecioná-lo.'))return;
    setBusy(item.id);setError('');
    try{
      const response=await fetch('/api/editorial/rejections/'+encodeURIComponent(item.id),{
        method:'DELETE',headers:{Authorization:'Bearer '+token}});
      if(!response.ok){
        const detail=await response.json().catch(()=>({detail:'Falha ao liberar tema.'}));
        throw new Error(detail.detail||'Falha ao liberar tema.');
      }
      await refresh();
    }catch(e){setError((e as Error).message)}finally{setBusy(null)}
  }

  return <section className="panel" aria-label="Temas descartados pela revisão humana">
    <div className="section-title">
      <div><h2><ShieldX size={17}/> Temas evitados pela IA</h2>
        <p className="muted">Descartar um vídeo manualmente evita que o automático escolha a mesma fonte
          ou um assunto muito semelhante pelos próximos {data?.cooldown_days??30} dias.
          Erros técnicos não bloqueiam assuntos.</p>
      </div>
      <button type="button" onClick={()=>void refresh().catch(e=>setError(e.message))}
        disabled={Boolean(busy)}><RefreshCw size={14}/> Atualizar</button>
    </div>
    {error&&<p className="error" role="alert">{error}</p>}
    <details>
      <summary>{data?.items.length??0} {data?.items.length===1?'tema/fonte bloqueado':'temas/fontes bloqueados'}
        {' '}· visualizar e gerenciar</summary>
      <div className="editorial-veto-list">
        {data?.items.length?data.items.map(item=><div className="list-row" key={item.id}>
          <div>
            <strong>{item.title}</strong>
            <small>Evitar até {new Date(item.expires_at*1000).toLocaleDateString('pt-BR')}
              {item.source_url?' · URL de origem também bloqueada':''}</small>
          </div>
          <button type="button" disabled={Boolean(busy)}
            onClick={()=>void unblock(item)} title="Remover rejeição editorial">
            <RotateCcw size={14}/> Permitir novamente
          </button>
        </div>):<p className="muted">Nenhum tema bloqueado. Quando você descartar um vídeo, ele será registrado aqui.</p>}
      </div>
    </details>
  </section>;
}
