'use client';
import {useEffect,useRef,useState} from 'react';
import {CloudUpload,FileVideo,Music2,Image as ImageIcon,RefreshCw,CheckCircle2} from 'lucide-react';

type UploadRow={key:string;file:File;category:string;tags:string;source_class:string;evidence:string;status:string;progress:number;error:string;assetId?:string};
const categories=['gameplay','b-roll','musica','efeito sonoro','imagem de fundo','logo','outro'];
function defaultCategory(file:File) {
  const suffix=file.name.split('.').pop()?.toLowerCase()||'';
  if(['mp4','mov','webm','mkv'].includes(suffix))return 'gameplay';
  if(['mp3','wav','m4a'].includes(suffix))return 'musica';
  if(['png','jpg','jpeg','webp','gif'].includes(suffix))return 'imagem de fundo';
  return 'outro';
}
async function fingerprint(file:File):Promise<string>{
  const head=await file.slice(0,65536).arrayBuffer();
  const tail=await file.slice(Math.max(0,file.size-65536)).arrayBuffer();
  const prefix=new TextEncoder().encode(`${file.name}|${file.size}|${file.lastModified}|`);
  const input=new Uint8Array(prefix.byteLength+head.byteLength+tail.byteLength);
  input.set(prefix,0);input.set(new Uint8Array(head),prefix.byteLength);
  input.set(new Uint8Array(tail),prefix.byteLength+head.byteLength);
  const digest=await crypto.subtle.digest('SHA-256',input);
  return Array.from(new Uint8Array(digest)).map(n=>n.toString(16).padStart(2,'0')).join('');
}
function LocalPreview({file}:{file:File}){
  const [url,setUrl]=useState('');
  useEffect(()=>{const next=URL.createObjectURL(file);setUrl(next);return()=>URL.revokeObjectURL(next)},[file]);
  if(!url)return null;
  const ext=file.name.split('.').pop()?.toLowerCase();
  if(['png','jpg','jpeg','webp','gif'].includes(ext||''))return <img className="upload-media-preview" src={url} alt="Miniatura do arquivo enviado"/>;
  if(['mp4','mov','webm','mkv'].includes(ext||''))return <video className="upload-media-preview" src={url} controls preload="metadata" aria-label={'Prévia '+file.name}/>;
  if(['mp3','wav','m4a'].includes(ext||''))return <audio className="upload-audio-preview" controls src={url} aria-label={'Áudio '+file.name}/>;
  return <p className="muted">Prévia visual indisponível para este formato. O arquivo pode ser enviado e cadastrado normalmente.</p>;
}
export default function MediaUpload({token,maxMb,onFinished}:{token:string;maxMb:number;onFinished:()=>Promise<unknown>}){
  const [files,setFiles]=useState<UploadRow[]>([]);
  const [dragging,setDragging]=useState(false);
  const input=useRef<HTMLInputElement>(null);
  const addFiles=(items:FileList|File[])=>setFiles(old=>{
    const existing=new Set(old.map(a=>a.key));
    const additions=Array.from(items).filter(a=>!existing.has(`${a.name}-${a.size}-${a.lastModified}`)).map(file=>({
      key:`${file.name}-${file.size}-${file.lastModified}`,file,category:defaultCategory(file),tags:'',
      source_class:'OWNED_GENERATED',evidence:'',status:'Pendente',progress:0,error:''}));
    return [...old,...additions];
  });
  const change=(key:string,patch:Partial<UploadRow>)=>setFiles(prev=>prev.map(x=>x.key===key?{...x,...patch}:x));
  async function json(path:string,method='GET',body?:unknown){
    const r=await fetch('/api/'+path,{method,headers:{Authorization:'Bearer '+token,...(body?{'Content-Type':'application/json'}:{})},body:body?JSON.stringify(body):undefined});
    const result=await r.json();if(!r.ok)throw new Error(result.detail||`HTTP ${r.status}`);return result;
  }
  async function upload(row:UploadRow){
    change(row.key,{status:'Preparando',error:''});
    try{
      if(row.file.size>maxMb*1024*1024)throw new Error(`Arquivo maior que ${maxMb} MB.`);
      const fp=await fingerprint(row.file);
      const session=await json('uploads/sessions','POST',{
        filename:row.file.name,size:row.file.size,category:row.category,
        tags:row.tags.split(',').map(x=>x.trim()).filter(Boolean),source_class:row.source_class,
        evidence:row.evidence,fingerprint:fp
      });
      let offset=Number(session.offset);
      while(offset<row.file.size){
        const begin=offset;
        const piece=row.file.slice(offset,Math.min(offset+4*1024*1024,row.file.size));
        try{
          offset=await new Promise<number>((resolve,reject)=>{
            const xhr=new XMLHttpRequest();xhr.open('PATCH','/api/uploads/sessions/'+session.id);
            xhr.setRequestHeader('Authorization','Bearer '+token);
            xhr.setRequestHeader('Upload-Offset',String(begin));
            xhr.setRequestHeader('Content-Type','application/octet-stream');
            xhr.upload.onprogress=e=>change(row.key,{status:'Enviando',progress:Math.min(99,Math.round(100*(begin+e.loaded)/row.file.size))});
            xhr.onload=()=>{
              try{const data=JSON.parse(xhr.responseText||'{}');
                if(xhr.status>=400)reject(new Error(data.detail||`HTTP ${xhr.status}`));
                else resolve(Number(data.offset));
              }catch(error){reject(error);}
            };
            xhr.onerror=()=>reject(new Error('Conexão interrompida. Clique Retomar.'));
            xhr.send(piece);
          });
        }catch(error){
          // Server can have accepted the bytes even when a response was lost.
          const state=await json('uploads/sessions/'+session.id);
          if(state.offset<=begin)throw error;
          offset=state.offset;
        }
      }
      change(row.key,{status:'Validando mídia',progress:99});
      const result=await json('uploads/sessions/'+session.id+'/finish','POST');
      change(row.key,{status:result.duplicate?'Arquivo já cadastrado':'Concluído · clipes na fila',progress:100,assetId:result.asset?.id});
      await onFinished();
    }catch(error){change(row.key,{status:'Interrompido',error:(error as Error).message});}
  }
  return <section className="panel upload-panel">
    <h2>Upload de mídia</h2><p className="muted">Envie vários arquivos de uma vez. Os envios em blocos podem ser retomados selecionando o mesmo arquivo novamente; a biblioteca nunca altera o original.</p>
    <div className={`upload-dropzone ${dragging?'dragging':''}`}
      onDragOver={e=>{e.preventDefault();setDragging(true)}} onDragLeave={()=>setDragging(false)}
      onDrop={e=>{e.preventDefault();setDragging(false);addFiles(e.dataTransfer.files)}}
      onClick={()=>input.current?.click()} role="button" tabIndex={0}
      onKeyDown={e=>{if(e.key==='Enter')input.current?.click()}}>
      <CloudUpload size={35}/><strong>Arraste mídias ou clique para selecionar</strong>
      <small>Vídeo, áudio, imagens, GIF, fontes TTF/OTF e legendas SRT · limite {maxMb} MB por arquivo</small>
      <input ref={input} type="file" multiple accept=".mp4,.mov,.webm,.mkv,.mp3,.wav,.m4a,.png,.jpg,.jpeg,.webp,.gif,.ttf,.otf,.srt" hidden
        onChange={e=>{if(e.target.files)addFiles(e.target.files);e.target.value='';}}/>
    </div>
    {files.map(row=><div key={row.key} className="upload-item">
      <div className="upload-item-head">{row.file.type.startsWith('video')?<FileVideo size={18}/>:row.file.type.startsWith('audio')?<Music2 size={18}/>:<ImageIcon size={18}/>}
        <strong title={row.file.name}>{row.file.name}</strong><small>{(row.file.size/1024/1024).toFixed(1)} MB</small></div>
      <LocalPreview file={row.file}/>
      <div className="form-grid"><label>Categoria<select value={row.category} onChange={e=>change(row.key,{category:e.target.value})}>{categories.map(c=><option key={c}>{c}</option>)}</select></label>
        <label>Origem<select value={row.source_class} onChange={e=>change(row.key,{source_class:e.target.value})}>
          <option value="OWNED_GENERATED">Próprio ou gerado</option><option value="OFFICIAL">Press kit / trailer oficial</option><option value="FREE_LICENSE">Licença livre comprovada</option>
          <option value="THIRD_PARTY">Terceiros</option></select></label></div>
      <label>Tags (separadas por vírgula)<input value={row.tags} onChange={e=>change(row.key,{tags:e.target.value})} placeholder="corrida, vice city, carros"/></label>
      <label>Autorização/licença (mín. 10 caracteres para liberar uso)<input value={row.evidence} onChange={e=>change(row.key,{evidence:e.target.value})}
         placeholder="Ex.: Gameplay gravada por mim. / Licença ou autorização verificável"/></label>
      <div className="upload-progress"><span style={{width:`${row.progress}%`}}/></div>
      <div className="upload-status"><span>{row.status} · {row.progress}%</span><button onClick={()=>upload(row)} disabled={['Enviando','Preparando','Validando mídia'].includes(row.status)}>
        {row.progress===100?<CheckCircle2 size={14}/>:<RefreshCw size={14}/>}{row.status==='Interrompido'?'Retomar':row.progress===100?'Enviado':'Enviar'}</button></div>
      {row.error&&<p className="error">{row.error}</p>}
    </div>)}
    {files.some(f=>f.progress<100)&&<button className="primary" disabled={files.some(f=>['Enviando','Preparando','Validando mídia'].includes(f.status))} onClick={()=>{
      // Queue multiple items sequentially to avoid saturating the local disk.
      void (async()=>{for(const item of files.filter(f=>f.progress<100))await upload(item);})();
    }}>Enviar arquivos pendentes</button>}
  </section>
}
