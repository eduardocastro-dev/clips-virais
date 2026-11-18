'use client';
import {useEffect,useState} from 'react';

type Row=Record<string,any>;
type Api=(path:string,body?:unknown,method?:string)=>Promise<any>;
const roles:Record<string,string>={dante_palma:'Apresentador',lia_varela:'Analista',caio_rivas:'Repórter'};
type Pose={index:number;emotion:string;description:string;file:string;active:boolean;exists:boolean;url:string};

function PoseGallery({slug,token,onError}:{slug:string;token:string;onError:(msg:string)=>void}){
  const [poses,setPoses]=useState<Pose[]>([]);
  const [urls,setUrls]=useState<Record<number,string>>({});
  const [busy,setBusy]=useState<number|null>(null);
  const [open,setOpen]=useState(false);
  const auth={Authorization:'Bearer '+token};
  useEffect(()=>{
    if(!open)return;
    let active=true;const blobs:string[]=[];
    void (async()=>{
      try{
        const r=await fetch(`/api/personas/${slug}/expressions`,{headers:auth});
        if(!r.ok)throw new Error('Galeria de poses indisponível.');
        const result=await r.json();const entries:Pose[]=result.images||[];
        if(active)setPoses(entries);
        const loaded:Record<number,string>={};
        await Promise.all(entries.map(async p=>{
          if(!p.exists)return;
          const img=await fetch(p.url,{headers:auth});
          if(img.ok){const url=URL.createObjectURL(await img.blob());blobs.push(url);loaded[p.index]=url;}
        }));
        if(active)setUrls(loaded);
      }catch(e){if(active)onError((e as Error).message)}
    })();
    return()=>{active=false;blobs.forEach(u=>URL.revokeObjectURL(u))};
  },[slug,token,open]);
  const edit=async(index:number,action:'restore'|'toggle'|'replace',file?:File)=>{
    setBusy(index);
    try{
      const current=poses.find(p=>p.index===index);
      if(!current)throw new Error('Pose não encontrada.');
      let url=`/api/personas/${slug}/expressions/${index}`;
      let options:RequestInit={headers:auth};
      if(action==='toggle')options={method:'PATCH',headers:{...auth,'Content-Type':'application/json'},body:JSON.stringify({active:!current.active})};
      if(action==='restore'){options={method:'POST',headers:auth};url+='/restore';}
      if(action==='replace'){
        if(!file)return;
        const body=new FormData();body.append('file',file);
        options={method:'PUT',headers:auth,body};url+='/image';
      }
      const response=await fetch(url,options);
      if(!response.ok){const d=await response.json();throw new Error(d.detail||'Não foi possível atualizar a pose.');}
      const list=await fetch(`/api/personas/${slug}/expressions`,{headers:auth});
      const updated:Pose[]=(await list.json()).images;
      setPoses(updated);
      if(action!=='toggle'){
        const img=await fetch(`/api/personas/${slug}/expressions/${index}/file`,{headers:auth});
        if(img.ok){const fresh=URL.createObjectURL(await img.blob());setUrls(prev=>({...prev,[index]:fresh}));}
      }
    }catch(e){onError((e as Error).message)}finally{setBusy(null)}
  };
  const uploadFile=async(kind:'sheet'|'poses',file:File)=>{
    setBusy(0);
    try{
      const data=new FormData();data.append('file',file);
      const endpoint=kind==='sheet'?`/api/personas/${slug}/pose-sheet`:`/api/personas/${slug}/expressions/import`;
      const result=await fetch(endpoint,{method:'POST',headers:auth,body:data});
      const response=await result.json();
      if(!result.ok)throw new Error(response.detail||'Importação não concluída');
      if(kind==='poses'){
        const list=await fetch(`/api/personas/${slug}/expressions`,{headers:auth});
        if(list.ok)setPoses((await list.json()).images);
      }
      alert(kind==='sheet'?'Folha salva como referência. Para produção, importe 24 PNGs individuais de alta resolução.':'24 PNGs validados e importados. Conjunto antigo preservado em _antigo.');
    }catch(e){onError((e as Error).message)}finally{setBusy(null)}
  };
  return <section style={{marginTop:12}}>
    <button type="button" onClick={()=>setOpen(!open)}>{open?'Ocultar':'Abrir'} galeria de poses (PNG RGBA)</button>
    {open&&<><p className="muted">Para qualidade de busto, importe 24 PNGs individuais (1024×1280 ou mais). Uma folha 4×6 é salva como referência e nunca é ampliada automaticamente.</p>
      <div className="actions">
        <label className="button">Importar folha 4×6<input type="file" accept="image/png" style={{display:'none'}} onChange={e=>{const file=e.target.files?.[0];if(file)void uploadFile('sheet',file)}}/></label>
        <label className="button">Importar ZIP com 24 PNGs<input type="file" accept=".zip" style={{display:'none'}} onChange={e=>{const file=e.target.files?.[0];if(file)void uploadFile('poses',file)}}/></label>
      </div>
      <div className="pose-grid-v8">
        {poses.map(p=><div className="pose-card-v8" key={p.index} style={{opacity:p.active?1:.45}}>
          {urls[p.index]?<img alt={`${p.index}: ${p.emotion}`} src={urls[p.index]} />:<div className="pose-empty">PNG indisponível</div>}
          <div className="pose-card-bottom"><small>{String(p.index).padStart(2,'0')} · {p.emotion.replace(/_/g,' ')}</small>
            <details className="pose-actions-v8"><summary aria-label={'Opções da pose '+p.emotion}>⋯</summary>
              <div className="pose-action-options">
                <button type="button" disabled={busy===p.index} onClick={()=>void edit(p.index,'toggle')}>{p.active?'Desativar':'Ativar'}</button>
                <button type="button" disabled={busy===p.index} onClick={()=>void edit(p.index,'restore')}>Restaurar master</button>
                <label>Trocar PNG<input type="file" accept="image/png" onChange={e=>{const file=e.target.files?.[0];if(file)void edit(p.index,'replace',file)}}/></label>
              </div>
            </details>
          </div>
        </div>)}
      </div>
    </>}
  </section>;
}

function CastCard({slug,person,token,api,refresh,onError}:{slug:string;person:Row;token:string;api:Api;refresh:()=>Promise<any>;onError:(msg:string)=>void}){
  const [draft,setDraft]=useState<Row>({});
  const [avatar,setAvatar]=useState('');
  const [voice,setVoice]=useState('');
  const [busy,setBusy]=useState(false);
  useEffect(()=>setDraft({look:person.look,personality:person.personality,voice:person.voice,
    voice_model:person.voice_model||'',image_path:person.image_path||'',speed:person.speed||1}),[person]);
  useEffect(()=>{
    let active=true;let url='';
    void fetch('/api/personas/'+slug+'/avatar',{headers:{Authorization:'Bearer '+token}}).then(r=>r.ok?r.blob():null).then(b=>{
      if(b){url=URL.createObjectURL(b);if(active)setAvatar(url)}
    }).catch(()=>{});
    return()=>{active=false;if(url)URL.revokeObjectURL(url)};
  },[slug,token,person.image_path,person.image_mtime_ns]);
  useEffect(()=>()=>{if(voice)URL.revokeObjectURL(voice)},[voice]);
  const save=async()=>{setBusy(true);try{await api('personas/'+slug,draft,'PUT');await refresh()}catch(e){onError((e as Error).message)}finally{setBusy(false)}};
  const sample=async()=>{
    try{
      const r=await fetch('/api/personas/'+slug+'/sample',{headers:{Authorization:'Bearer '+token}});
      if(!r.ok){const response=await r.json();throw new Error(response.detail||'Não foi possível sintetizar a voz')}
      if(voice)URL.revokeObjectURL(voice);
      setVoice(URL.createObjectURL(await r.blob()));
    }catch(e){onError((e as Error).message)}
  };
  return <article className="panel" style={{minWidth:280,flex:'1 1 320px'}}>
    <h3>{person.name} · {roles[slug]}</h3>
    {!person.production_ready&&<p className="error">Arte individual de qualidade pendente. As ilustrações SVG antigas não serão usadas nos vídeos.</p>}
    {avatar?<img alt={'Referência original de '+person.name} src={avatar} style={{width:150,height:150,objectFit:'cover',borderRadius:12}}/>:<p className="error">Imagem ainda não encontrada em /assets/personas/{slug}/avatar.png</p>}
    <p className="muted">{person.catchphrases?.slice(0,2).join(' · ')}</p>
    <label>Visual<input value={draft.look||''} onChange={e=>setDraft({...draft,look:e.target.value})}/></label>
    <label>Personalidade<textarea rows={3} value={draft.personality||''} onChange={e=>setDraft({...draft,personality:e.target.value})}/></label>
    <label>Voz e entonação<input value={draft.voice||''} onChange={e=>setDraft({...draft,voice:e.target.value})}/></label>
    <label>Modelo Piper (.onnx em /models)<input value={draft.voice_model||''} onChange={e=>setDraft({...draft,voice_model:e.target.value})}/></label>
    <label>Avatar (caminho relativo em /assets)<input value={draft.image_path||''} onChange={e=>setDraft({...draft,image_path:e.target.value})}/></label>
    <label>Velocidade <input type="number" min="0.7" max="1.3" step="0.05" value={draft.speed||1} onChange={e=>setDraft({...draft,speed:Number(e.target.value)})}/></label>
    <div className="actions"><button disabled={busy} onClick={save}>Salvar personagem</button><button disabled={busy} onClick={sample}>Ouvir amostra</button></div>
    {voice&&<audio controls autoPlay src={voice} style={{width:'100%'}}/>}
    <PoseGallery slug={slug} token={token} onError={onError}/>
  </article>;
}
export default function CastPanel({cast,token,api,refresh,onError}:{cast:Row;token:string;api:Api;refresh:()=>Promise<any>;onError:(msg:string)=>void}){
  return <section className="panel"><h2>Elenco e vozes — 3 personagens originais</h2><p className="muted">O roteiro registra personagem e emoção; cada voz usa um modelo Piper PT-BR distinto quando instalado. As amostras são geradas com o modelo real. As 24 poses vêm dos PNGs incluídos no pacote.</p>
    <div style={{display:'flex',flexWrap:'wrap',gap:12}}>{Object.entries(cast||{}).filter(([key])=>key in roles).map(([slug,person])=><CastCard key={slug} slug={slug} person={person as Row} token={token} api={api} refresh={refresh} onError={onError}/>)}</div>
  </section>
}
