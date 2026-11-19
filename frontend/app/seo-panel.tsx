'use client';

import {useEffect,useState} from 'react';
import {Check,Clipboard,FileText,Save,Search} from 'lucide-react';

type Row=Record<string,any>;
type SEO={title:string;caption:string;hashtags:string[];tags:string[];pinned_comment:string;cover_text:string;notice?:string;test_only?:boolean;source_url?:string};
type Props={publication:Row;api:(path:string,body?:unknown,method?:string)=>Promise<any>};

export default function SeoPanel({publication,api}:Props){
  const [open,setOpen]=useState(false);
  const [seo,setSeo]=useState<SEO|null>(null);
  const [error,setError]=useState('');
  const [message,setMessage]=useState('');
  const [busy,setBusy]=useState(false);
  const [copied,setCopied]=useState('');
  useEffect(()=>{
    if(!open)return;
    let valid=true;
    setError('');setMessage('');setSeo(null);setBusy(true);
    api('publications/'+publication.id+'/seo').then(x=>{if(valid)setSeo(x)})
      .catch(e=>{if(valid)setError(e.message||'Metadados indisponíveis.')})
      .finally(()=>{if(valid)setBusy(false)});
    return()=>{valid=false};
  },[open,publication.id,api]);
  async function copy(label:string,value:string){
    try{
      await navigator.clipboard.writeText(value);
      setCopied(label);
      setMessage(label+' copiado.');
    }catch{setError('O navegador não permitiu copiar. Selecione o texto e copie manualmente.')}
  }
  async function save(){
    if(!seo)return;
    setError('');setMessage('');setBusy(true);
    try{
      const next=await api('publications/'+publication.id+'/seo',{
        title:seo.title,caption:seo.caption,hashtags:seo.hashtags,
        tags:seo.tags,pinned_comment:seo.pinned_comment,cover_text:seo.cover_text
      },'PUT');
      setSeo(next);setMessage('SEO atualizado e salvo para esta plataforma.');
    }catch(e){setError((e as Error).message)}finally{setBusy(false)}
  }
  const textWithTitle=seo?[seo.title,seo.caption].filter(Boolean).join('\n\n'):'';
  return <div className="seo-panel">
    <button className="seo-toggle" onClick={()=>setOpen(v=>!v)} aria-expanded={open}>
      <Search size={15}/> {open?'Fechar SEO':'SEO pronto para copiar'}
    </button>
    {open&&<div className="seo-editor">
      <p className="muted">Texto exclusivo para <strong>{publication.platform.toUpperCase()}</strong>. Revise informações e créditos antes de publicar manualmente.</p>
      {busy&&!seo&&<small>Carregando metadados…</small>}
      {error&&<p className="error" role="alert">{error}</p>}
      {message&&<p className="success" role="status">{message}</p>}
      {seo&&<>
        {seo.test_only&&<p className="error">Vídeo técnico de teste: não publicar em redes sociais.</p>}
        <label>Título ({seo.title.length}/100)
          <textarea rows={2} maxLength={100} value={seo.title} onChange={e=>setSeo({...seo,title:e.target.value})}/>
        </label>
        <button type="button" onClick={()=>copy('Título',seo.title)}><Clipboard size={14}/> Copiar título</button>
        <label>Legenda / descrição ({seo.caption.length} caracteres)
          <textarea rows={8} value={seo.caption} onChange={e=>setSeo({...seo,caption:e.target.value})}/>
        </label>
        <button type="button" onClick={()=>copy('Legenda',seo.caption)}><Clipboard size={14}/> Copiar legenda</button>
        <label>Hashtags (separadas por vírgula)
          <textarea rows={2} value={seo.hashtags.join(', ')}
            onChange={e=>setSeo({...seo,hashtags:e.target.value.split(',').map(x=>x.trim().replace(/^#/,'')).filter(Boolean)})}/>
        </label>
        <button type="button" onClick={()=>copy('Hashtags',seo.hashtags.map(x=>'#'+x).join(' '))}><Clipboard size={14}/> Copiar hashtags</button>
        {publication.platform==='youtube'&&<>
          <label>Tags do YouTube (separadas por vírgula)
            <textarea rows={3} value={seo.tags.join(', ')}
              onChange={e=>setSeo({...seo,tags:e.target.value.split(',').map(x=>x.trim()).filter(Boolean)})}/>
          </label>
          <button type="button" onClick={()=>copy('Tags',seo.tags.join(', '))}><Clipboard size={14}/> Copiar tags</button>
        </>}
        <label>Comentário fixado
          <textarea rows={2} maxLength={300} value={seo.pinned_comment}
            onChange={e=>setSeo({...seo,pinned_comment:e.target.value})}/>
        </label>
        <button type="button" onClick={()=>copy('Comentário',seo.pinned_comment)}><Clipboard size={14}/> Copiar comentário</button>
        <label>Texto sugerido para capa
          <input maxLength={55} value={seo.cover_text}
            onChange={e=>setSeo({...seo,cover_text:e.target.value})}/>
        </label>
        <div className="seo-actions">
          <button type="button" disabled={busy||publication.status==='PUBLICADO'} onClick={save}><Save size={15}/> Salvar alterações</button>
          <button type="button" className="primary" onClick={()=>copy('Pacote de publicação',textWithTitle)}><FileText size={15}/> Copiar título + legenda</button>
        </div>
        <small>Copiar não envia para nenhuma rede. Alterações precisam ser salvas. SEO não garante visualizações. {seo.notice||''}</small>
      </>}
    </div>}
  </div>;
}
