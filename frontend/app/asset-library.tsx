'use client';
import {useEffect,useState,type ReactElement} from 'react';
import {Eye,Trash2,Save,ShieldCheck,MoreVertical,FolderOpen} from 'lucide-react';
type Row=Record<string,any>;
type Api=(path:string,body?:unknown,method?:string)=>Promise<any>;
const childrenOf=(assets:Row[],id:string)=>assets.filter(a=>a.parent_id===id);
const media=(a:Row)=>a.media_type||(a.kind==='images'?'image':a.kind==='music'?'audio':'video');

function Thumbnail({item,token}:{item:Row;token:string}){
  const [thumb,setThumb]=useState(''),[preview,setPreview]=useState(''),[hover,setHover]=useState(false);
  useEffect(()=>{
    let active=true,source='';
    if(!item.path)return;
    void fetch('/api/assets/'+item.id+'/thumbnail',{headers:{Authorization:'Bearer '+token}})
      .then(r=>r.ok?r.blob():null).then(blob=>{if(!blob)return;source=URL.createObjectURL(blob);if(active)setThumb(source);})
      .catch(()=>{});
    return()=>{active=false;if(source)URL.revokeObjectURL(source)};
  },[item.id,item.path,token]);
  useEffect(()=>{
    if(!hover||!item.path||media(item)!=='video')return;
    let active=true,uri='';
    void fetch('/api/assets/'+item.id+'/preview',{headers:{Authorization:'Bearer '+token}})
     .then(r=>r.ok?r.blob():null).then(blob=>{if(!blob)return;uri=URL.createObjectURL(blob);if(active)setPreview(uri);})
     .catch(()=>{});
    return()=>{active=false;if(uri)URL.revokeObjectURL(uri)};
  },[hover,item.id,item.path,token]);
  return <div className="asset-cover" onMouseEnter={()=>setHover(true)} onMouseLeave={()=>{setHover(false);setPreview('')}}>
    {hover&&preview&&media(item)==='video'?<video src={preview} muted autoPlay playsInline loop className="asset-cover-media"/>:
      thumb?<img src={thumb} alt={'Prévia de '+(item.title||'asset')} className="asset-cover-media"/>:
      <div className="asset-no-cover">{item.path?'Miniatura indisponível':'Somente referência'}</div>}
    {item.duration&&<span className="asset-duration">{Number(item.duration).toFixed(0)}s</span>}
  </div>;
}

export default function AssetLibrary({assets,token,api,refresh,onError}:{assets:Row[];token:string;api:Api;refresh:()=>Promise<unknown>;onError:(message:string)=>void}){
  const [kind,setKind]=useState('todos'),[source,setSource]=useState('todos'),[status,setStatus]=useState('todos'),[term,setTerm]=useState('');
  const [selected,setSelected]=useState<string[]>([]),[limit,setLimit]=useState(48);
  const [focused,setFocused]=useState<Row|null>(null),[preview,setPreview]=useState(''),[previewType,setPreviewType]=useState('');
  const [edit,setEdit]=useState<Row|null>(null),[rights,setRights]=useState({source_class:'OWNED_GENERATED',evidence:''});
  const [expanded,setExpanded]=useState<string[]>([]);
  useEffect(()=>()=>{if(preview)URL.revokeObjectURL(preview)},[preview]);
  const children=assets.filter(a=>a.parent_id);
  const originals=assets.filter(a=>!a.parent_id);
  const eligible=(a:Row)=>{
    const content=[a.title,a.category,a.url,a.channel,a.path,a.tags].join(' ').toLowerCase();
    const rights=String(a.rights_status||'');
    return (kind==='todos'||kind===media(a)||kind===a.kind||kind===a.category)&&
       (source==='todos'||a.source_class===source)&&
       (status==='todos'||status==='ativos'&&!!a.active||status==='revogados'&&!a.active||status==='pendentes'&&rights!=='AUTHORIZED')&&
       content.includes(term.toLowerCase());
  };
  const listed=originals.filter(a=>eligible(a)||children.some(c=>c.parent_id===a.id&&eligible(c)));
  const toggleSelected=(id:string)=>setSelected(old=>old.includes(id)?old.filter(x=>x!==id):[...old,id]);
  async function action(fn:()=>Promise<any>){try{await fn();await refresh()}catch(e){onError((e as Error).message)}}
  async function bulk(operation:'activate'|'deactivate'|'delete'|'recategorize',category?:string){
    if(!selected.length)return;
    if(operation==='delete'&&!confirm(`Excluir permanentemente ${selected.length} assets e seus derivados?`))return;
    await action(async()=>{
      const result=await api('assets/bulk',{ids:selected,operation,category,confirm_delete:operation==='delete'},'POST');
      if(Object.keys(result.errors||{}).length)throw new Error(Object.values(result.errors).join(' · '));
      setSelected([]);
    });
  }
  async function view(a:Row){
    setFocused(a);
    if(preview){URL.revokeObjectURL(preview);setPreview('')}
    if(!a.path)return;
    try{
      const type=media(a);
      const endpoint=type==='video'?`assets/${a.id}/preview`:`assets/${a.id}/file`;
      const response=await fetch('/api/'+endpoint,{headers:{Authorization:'Bearer '+token}});
      if(!response.ok)throw new Error(`Não foi possível abrir prévia: HTTP ${response.status}`);
      setPreview(URL.createObjectURL(await response.blob()));setPreviewType(type);
    }catch(e){onError((e as Error).message)}
  }
  const card=(a:Row,derived=false):ReactElement=><article className="asset-gallery-card" key={a.id}>
    <div className="asset-tile-top">
      <label className="asset-tile-check"><input aria-label={'Selecionar '+a.title} type="checkbox" checked={selected.includes(a.id)} onChange={()=>toggleSelected(a.id)}/></label>
      <span className="asset-state">{a.active?'Ativo':'Revogado'}</span>
    </div>
    <button type="button" className="asset-thumbnail-button" onClick={()=>view(a)} aria-label={'Ver '+a.title}><Thumbnail item={a} token={token}/></button>
    <div className="asset-card-meta"><strong title={a.title||a.path}>{a.title||a.source_id||'Asset sem nome'}</strong>
      <small>{a.category||a.kind} · {a.source_class||'origem não informada'}</small>
      <small>{a.clip_index?`Clipe ${a.clip_index}/${a.clip_total} · `:''}{a.usage_count||0} usos · {a.rights_status}</small>
    </div>
    <div className="asset-card-actions">
      <button onClick={()=>view(a)}><Eye size={14}/> Ver</button>
      <details className="asset-card-menu"><summary aria-label="Opções do asset"><MoreVertical size={16}/></summary>
        <div className="asset-card-menu-content">
          <button onClick={()=>setEdit({id:a.id,title:a.title||'',category:a.category||'outro',tags:(()=>{try{return JSON.parse(a.tags||'[]').join(', ')}catch{return ''}})(),active:!!a.active})}><Save size={13}/> Editar</button>
          <button onClick={()=>action(()=>api('assets/'+a.id,{active:!a.active},'PATCH'))}>{a.active?'Revogar uso':'Reativar'}</button>
          {a.kind==='shorts'&&a.rights_status==='AUTHORIZED'&&!a.path&&<button onClick={()=>action(()=>api('assets/'+a.id+'/download',{}))}>Baixar mídia autorizada</button>}
          <button onClick={()=>{if(confirm('Excluir este asset e seus derivados?'))void action(()=>api('assets/'+a.id,{confirm_children:true},'DELETE'));}}><Trash2 size={13}/> Excluir</button>
        </div>
      </details>
    </div>
    {!derived&&childrenOf(assets,a.id).length>0&&<button className="asset-expand" onClick={()=>setExpanded(x=>x.includes(a.id)?x.filter(id=>id!==a.id):[...x,a.id])}>
      <FolderOpen size={14}/> {childrenOf(assets,a.id).length} clipes · {expanded.includes(a.id)?'Ocultar':'Expandir'}
    </button>}
    {expanded.includes(a.id)&&!derived&&<div className="asset-derived-grid">{childrenOf(assets,a.id).map(child=>card(child,true))}</div>}
  </article>;
  return <div className="asset-gallery-layout"><section className="panel">
    <div className="section-heading"><h2>Biblioteca de assets</h2><button onClick={()=>void action(()=>api('assets/rescan',{},'POST'))}>Reescanear /assets</button></div>
    <p className="muted">Disponibilidade no Estúdio é diferente de licença para publicar. Apenas mídias com direitos documentados entram nos renders finais.</p>
    <div className="asset-filters">
      <select aria-label="Tipo" value={kind} onChange={e=>setKind(e.target.value)}>{['todos','video','audio','image','font','subtitle','gameplay','b-roll','musica','efeito sonoro','shorts'].map(x=><option key={x}>{x}</option>)}</select>
      <select aria-label="Origem" value={source} onChange={e=>setSource(e.target.value)}>{[['todos','Todas origens'],['OWNED_GENERATED','Próprios'],['OFFICIAL','Oficiais'],['FREE_LICENSE','Licença livre'],['THIRD_PARTY','Terceiros']].map(([id,title])=><option key={id} value={id}>{title}</option>)}</select>
      <select aria-label="Status" value={status} onChange={e=>setStatus(e.target.value)}>{[['todos','Todos'],['ativos','Ativos'],['revogados','Revogados'],['pendentes','Direitos pendentes']].map(([id,title])=><option value={id} key={id}>{title}</option>)}</select>
      <input aria-label="Buscar assets" value={term} placeholder="Buscar nome, tags ou canal" onChange={e=>setTerm(e.target.value)}/>
    </div>
    {!!selected.length&&<div className="asset-bulk"><strong>{selected.length} selecionados</strong>
      <button onClick={()=>void bulk('activate')}>Ativar</button><button onClick={()=>void bulk('deactivate')}>Revogar</button>
      <button onClick={()=>void bulk('recategorize','b-roll')}>Classificar como B-roll</button>
      <button onClick={()=>void bulk('delete')}>Excluir</button><button onClick={()=>setSelected([])}>Limpar seleção</button>
    </div>}
    <div className="asset-gallery-grid">{listed.slice(0,limit).map(a=>card(a))}</div>
    {listed.length>limit&&<button onClick={()=>setLimit(x=>x+48)}>Mostrar mais 48 assets</button>}
    {!listed.length&&<p className="muted">Nenhum asset corresponde aos filtros.</p>}
  </section>
  <section className="panel"><h2>Detalhes e pré-visualização</h2>
    {focused?<><h3>{focused.title}</h3><p className="muted review-prewrap">{focused.path||focused.url} · Fonte: {focused.channel||focused.url||'não informada'} · {focused.usage_count||0} usos</p>
      {previewType==='video'&&preview?<video controls src={preview} style={{width:'100%'}}/>:
       previewType==='audio'&&preview?<audio controls src={preview} style={{width:'100%'}}/>:
       preview?<img src={preview} alt="Pré-visualização" style={{maxWidth:'100%'}}/>:
       <p className="muted">Somente metadados ou arquivo indisponível.</p>}
      {previewType==='video'&&<small>Prévia compacta de 3 segundos; o original permanece intacto.</small>}
      <p className="muted">Status de licença: {focused.rights_status} · {focused.evidence||'Evidência não cadastrada'}</p>
      {focused.rights_status!=='AUTHORIZED'&&<form onSubmit={e=>{e.preventDefault();void action(()=>api('assets/'+focused.id+'/rights',rights,'PUT'));}}>
        <label>Origem<select value={rights.source_class} onChange={e=>setRights({...rights,source_class:e.target.value})}>{[['OWNED_GENERATED','Próprio/gerado'],['OFFICIAL','Oficial com permissão'],['FREE_LICENSE','Livre com licença'],['THIRD_PARTY','Terceiro com autorização']].map(([a,b])=><option value={a} key={a}>{b}</option>)}</select></label>
        <label>Evidência verificável<textarea required minLength={10} value={rights.evidence} onChange={e=>setRights({...rights,evidence:e.target.value})}/></label>
        <button><ShieldCheck size={14}/> Documentar direitos</button>
      </form>}
    </>:<p className="muted">Selecione uma miniatura para abrir os detalhes.</p>}
    {edit&&<form onSubmit={e=>{e.preventDefault();const current=edit;void action(async()=>{await api('assets/'+current.id,{title:current.title,category:current.category,tags:String(current.tags||'').split(',').map(x=>x.trim()).filter(Boolean),active:current.active},'PATCH');setEdit(null)})}}>
      <h3>Editar asset</h3><label>Título<input value={edit.title||''} onChange={e=>setEdit({...edit,title:e.target.value})}/></label>
      <label>Categoria<select value={edit.category||'outro'} onChange={e=>setEdit({...edit,category:e.target.value})}>{['gameplay','b-roll','musica','efeito sonoro','imagem de fundo','logo','outro'].map(x=><option key={x}>{x}</option>)}</select></label>
      <label>Tags<input value={edit.tags||''} onChange={e=>setEdit({...edit,tags:e.target.value})}/></label>
      <label className="checkbox"><input type="checkbox" checked={!!edit.active} onChange={e=>setEdit({...edit,active:e.target.checked})}/> Ativo</label>
      <button className="primary">Salvar</button><button type="button" onClick={()=>setEdit(null)}>Cancelar</button>
    </form>}
  </section></div>;
}
