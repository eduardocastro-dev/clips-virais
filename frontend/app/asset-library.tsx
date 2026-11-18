'use client';
import {useEffect,useState} from 'react';
import {ChevronDown,Eye,Trash2,Save,ShieldCheck} from 'lucide-react';
type Row=Record<string,any>;
type Api=(path:string,body?:unknown,method?:string)=>Promise<any>;
const group=(a:Row)=>a.parent_id||a.id;
export default function AssetLibrary({assets,token,api,refresh,onError}:{assets:Row[];token:string;api:Api;refresh:()=>Promise<unknown>;onError:(message:string)=>void}){
  const [kind,setKind]=useState('todos'),[source,setSource]=useState('todos'),[term,setTerm]=useState('');
  const [preview,setPreview]=useState(''),[previewType,setPreviewType]=useState('');
  const [edit,setEdit]=useState<Row|null>(null);const [rights,setRights]=useState({source_class:'OWNED_GENERATED',evidence:''});
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview]);
  const children=assets.filter(a=>a.parent_id);
  const originals=assets.filter(a=>!a.parent_id);
  const eligible=(a:Row)=>{
    const text=[a.title,a.category,a.url,a.channel,a.path,a.tags].join(' ').toLowerCase();
    return (kind==='todos'||kind===a.media_type||kind===a.kind||kind===a.category)&&
           (source==='todos'||a.source_class===source)&&text.includes(term.toLowerCase());
  };
  const list=originals.filter(a=>eligible(a)||children.some(c=>c.parent_id===a.id&&eligible(c)));
  async function action(fn:()=>Promise<any>){try{await fn();await refresh();}catch(e){onError((e as Error).message)}}
  async function view(a:Row){
    try{
      if(!a.path)throw new Error('Apenas metadados; a mídia ainda não foi baixada.');
      const r=await fetch('/api/assets/'+a.id+'/file',{headers:{Authorization:'Bearer '+token}});
      if(!r.ok)throw new Error(`Falha ao carregar prévia: HTTP ${r.status}`);
      if(preview)URL.revokeObjectURL(preview);
      setPreview(URL.createObjectURL(await r.blob()));setPreviewType(a.media_type||a.kind);
    }catch(e){onError((e as Error).message)}
  }
  const renderRow=(a:Row,child=false)=><div className={`asset-item ${child?'asset-child':''}`} key={a.id}>
    <div className="asset-header"><strong>{a.title||a.source_id}</strong>
      <span className="muted">{a.category||a.kind} · {a.source_class} · {a.rights_status} · {a.status}</span></div>
    <p className="muted review-prewrap">{a.path||a.url} {a.clip_index?`· clipe ${a.clip_index}/${a.clip_total}`:''} · {a.duration?Number(a.duration).toFixed(1)+'s':''} · usos {a.usage_count||0}</p>
    {a.metadata&&a.status?.startsWith('SPLIT')&&<p className="muted">Fatiamento: {(()=>{try{return JSON.parse(a.metadata)?.split?.progress||0}catch{return 0}})()}%</p>}
    {a.error&&<p className="error review-prewrap">{a.error}</p>}
    <div className="actions"><button disabled={!a.path} onClick={()=>view(a)}><Eye size={14}/> Prévia</button>
      <button onClick={()=>setEdit({id:a.id,title:a.title||'',category:a.category||'outro',tags:((()=>{try{return JSON.parse(a.tags||'[]')}catch{return []}})()).join(', '),active:!!a.active})}><Save size={14}/> Editar</button>
      <button onClick={()=>action(()=>api('assets/'+a.id,{...a,active:!a.active,title:undefined,category:undefined,tags:undefined},'PATCH'))}>{a.active?'Desativar':'Ativar'}</button>
      {a.kind==='shorts'&&a.rights_status==='AUTHORIZED'&&!a.path&&<button onClick={()=>action(()=>api('assets/'+a.id+'/download',{}))}>Baixar autorizado</button>}
      <button onClick={()=>{const count=children.filter(c=>c.parent_id===a.id).length;
        if(confirm(count?`Excluir o original e seus ${count} clipes derivados? Esta operação é irreversível.`:'Excluir definitivamente este asset?'))
          action(()=>api('assets/'+a.id,{confirm_children:true},'DELETE'))}}><Trash2 size={14}/> Apagar</button></div>
    {edit !== null && edit.id === a.id && <form onSubmit={e=>{e.preventDefault();action(async()=>{await api('assets/'+a.id,
         {title:edit?.title,category:edit?.category,tags:(edit?.tags||'').split(',').map((x:string)=>x.trim()).filter(Boolean),active:edit?.active},'PATCH');setEdit(null);});}}>
      <label>Nome<input value={edit?.title ?? ''} onChange={e=>setEdit({...(edit||{}),title:e.target.value})}/></label>
      <label>Categoria<select value={edit?.category ?? 'outro'} onChange={e=>setEdit({...(edit||{}),category:e.target.value})}>{['gameplay','b-roll','musica','efeito sonoro','imagem de fundo','logo','outro'].map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Tags<input value={edit?.tags ?? ''} onChange={e=>setEdit({...(edit||{}),tags:e.target.value})}/></label>
      <label className="checkbox"><input type="checkbox" checked={Boolean(edit?.active)} onChange={e=>setEdit({...(edit||{}),active:e.target.checked})}/>Ativo na montagem</label>
      <button className="primary">Salvar alterações</button><button type="button" onClick={()=>setEdit(null)}>Cancelar</button></form>}
    {a.rights_status!=='AUTHORIZED'&&<form onSubmit={e=>{e.preventDefault();action(()=>api('assets/'+a.id+'/rights',rights,'PUT'))}}>
      <label>Classificação<select value={rights.source_class} onChange={e=>setRights({...rights,source_class:e.target.value})}>
        <option value="OWNED_GENERATED">Próprio / gerado</option><option value="OFFICIAL">Press kit com licença</option>
        <option value="THIRD_PARTY">Terceiros com autorização</option></select></label>
      <label>Evidência de autorização<textarea minLength={10} required value={rights.evidence} onChange={e=>setRights({...rights,evidence:e.target.value})}/></label>
      <button><ShieldCheck size={14}/> Autorizar uso</button></form>}
    {!child&&children.some(c=>c.parent_id===a.id)&&<details className="asset-derived"><summary><ChevronDown size={14}/> {children.filter(c=>c.parent_id===a.id).length} clipes derivados · expandir</summary>
      {children.filter(c=>c.parent_id===a.id).map(c=>renderRow(c,true))}</details>}
  </div>;
  return <div className="two-column"><section className="panel">
    <h2>Biblioteca de assets</h2><p className="muted">Originais intactos · clipes agrupados pelo pai · ativos para montagem somente com direitos autorizados.</p>
    <div className="asset-filters"><select aria-label="Filtrar tipo" value={kind} onChange={e=>setKind(e.target.value)}>{['todos','video','audio','image','font','subtitle','logo','gameplay','b-roll','musica','efeito sonoro','shorts'].map(x=><option key={x}>{x}</option>)}</select>
      <select aria-label="Filtrar origem" value={source} onChange={e=>setSource(e.target.value)}>{[['todos','Todas origens'],['OWNED_GENERATED','Próprios'],['OFFICIAL','Oficiais'],['THIRD_PARTY','Terceiros']].map(([id,title])=><option key={id} value={id}>{title}</option>)}</select>
      <input aria-label="Buscar tags, nomes ou fontes" placeholder="Filtrar por tag ou nome" value={term} onChange={e=>setTerm(e.target.value)}/></div>
    {list.map(a=>renderRow(a))}
    {!list.length&&<p className="muted">Nenhum asset corresponde aos filtros.</p>}
  </section><section className="panel"><h2>Prévia do asset</h2>
    {preview?(previewType==='audio'?<audio controls src={preview} style={{width:'100%'}}/>:
      ['image','images','persona','logo'].includes(previewType)?<img src={preview} alt="Prévia do asset" style={{maxWidth:'100%'}}/>:
      ['video','clip','shorts','gameplay','uploads'].includes(previewType)?<video controls src={preview} style={{maxWidth:'100%'}}/>:
      <a className="button" href={preview} download="arquivo">Baixar arquivo</a>)
      :<p className="muted">Clique em Prévia. Vídeos e áudios possuem player; imagens exibem miniatura.</p>}
    <p className="muted">Pastas: /assets/uploads/, /assets/clips/, /assets/gameplay/, /assets/shorts/. Clipes são cópias derivadas e nunca substituem o original.</p></section></div>;
}
