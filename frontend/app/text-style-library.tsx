'use client';
import {useCallback,useEffect,useState} from 'react';
import {Check,Image as ImageIcon,UploadCloud,ShieldCheck} from 'lucide-react';

type Style={id:string;title:string;kind:'eps'|'font';theme:string;active:boolean;license_evidence:string;rendering:string;rights_status:string};
type Data={items:Style[];active_id:string};
const themes=[
  {value:'california_sunset',name:'California Sunset — coral, laranja e roxo'},
  {value:'vintage_shadow',name:'Vintage Shadow — creme e sombra preta'},
  {value:'neon_gaming',name:'Neon Gaming — ciano e violeta'}
];
function Preview({id,token}:{id:string;token:string}){
  const [src,setSrc]=useState('');
  useEffect(()=>{
    let active=true;
    fetch('/api/text-styles/'+id+'/preview',{headers:{Authorization:'Bearer '+token}})
      .then(async r=>{if(!r.ok)throw Error('Prévia indisponível');return URL.createObjectURL(await r.blob())})
      .then(url=>{if(active)setSrc(url);else URL.revokeObjectURL(url)}).catch(()=>{});
    return()=>{active=false};
  },[id,token]);
  useEffect(()=>()=>{if(src)URL.revokeObjectURL(src)},[src]);
  return src?<img className="text-style-preview" src={src} alt="Prévia do efeito de texto"/>:<div className="text-style-preview empty-preview"><ImageIcon size={23}/></div>;
}
export default function TextStyleLibrary({token}:{token:string}){
  const [data,setData]=useState<Data>({items:[],active_id:''});
  const [file,setFile]=useState<File|null>(null);
  const [name,setName]=useState('');
  const [theme,setTheme]=useState('california_sunset');
  const [sourceClass,setSourceClass]=useState('THIRD_PARTY');
  const [evidence,setEvidence]=useState('');
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [loading,setLoading]=useState(false);
  const api=useCallback(async(path:string,init?:RequestInit)=>{
    const response=await fetch('/api/'+path,{...init,headers:{Authorization:'Bearer '+token,...init?.headers}});
    if(!response.ok){let detail='Falha na biblioteca.';try{const obj=await response.json();detail=String(obj.detail||detail)}catch{}throw Error(detail)}
    return response.json();
  },[token]);
  const load=useCallback(async()=>setData(await api('text-styles')),[api]);
  useEffect(()=>{load().catch(e=>setError(e.message))},[load]);
  function choose(f:File|null){
    setFile(f);if(!f)return;
    setName(f.name.replace(/\.(zip|ttf|otf)$/i,'').replace(/[-_]+/g,' '));
    const lower=f.name.toLowerCase();
    if(lower.includes('california'))setTheme('california_sunset');
    else if(lower.includes('vintage'))setTheme('vintage_shadow');
  }
  async function upload(e:React.FormEvent<HTMLFormElement>){
    e.preventDefault();setError('');setNotice('');
    if(!file){setError('Escolha o ZIP EPS/JPG ou um arquivo TTF/OTF.');return}
    if(file.size>25*1024*1024){setError('O tamanho máximo é de 25 MB.');return}
    if(evidence.trim().length<10){setError('Informe a licença ou comprovante de uso.');return}
    const form=new FormData();form.append('file',file);form.append('name',name);form.append('theme',theme);
    form.append('source_class',sourceClass);form.append('evidence',evidence);
    setLoading(true);
    try{
      await api('text-styles/upload',{method:'POST',body:form});await load();
      setNotice('Asset salvo. Selecione Ativar para usá-lo em novas renderizações.');setFile(null);setName('');
    }catch(err){setError((err as Error).message)}finally{setLoading(false)}
  }
  async function toggle(id?:string){
    setLoading(true);setError('');setNotice('');
    try{
      await api(id?'text-styles/'+id+'/activate':'text-styles/deactivate',{method:'POST'});
      await load();setNotice(id?'Estilo ativado para novas edições.':'Estilo desativado. Editor padrão restaurado.');
    }catch(err){setError((err as Error).message)}finally{setLoading(false)}
  }
  return <div className="text-style-library">
    <section className="panel">
      <h2>Fontes e efeitos de texto para os vídeos</h2>
      <p className="muted">Envie fontes TTF/OTF ou pacotes de efeitos EPS com JPG/PNG. Os arquivos ficam na biblioteca persistente e só entram no vídeo após ativação e registro da licença.</p>
      <p className="muted"><strong>Atenção:</strong> EPS é arte vetorial, não fonte. Os dois ZIPs Retro servem como referência para uma aproximação de cores e sombras. Para utilizar as mesmas letras, envie a fonte TTF/OTF licenciada.</p>
      <form className="text-style-form" onSubmit={upload}>
        <label>Arquivo ZIP / TTF / OTF<input required type="file" accept=".zip,.ttf,.otf" onChange={e=>choose(e.currentTarget.files?.[0]||null)}/></label>
        <label>Nome do estilo<input required maxLength={100} value={name} onChange={e=>setName(e.target.value)}/></label>
        <label>Paleta e efeito<select value={theme} onChange={e=>setTheme(e.target.value)}>{themes.map(t=><option value={t.value} key={t.value}>{t.name}</option>)}</select></label>
        <label>Origem e licença<select value={sourceClass} onChange={e=>setSourceClass(e.target.value)}>
          <option value="THIRD_PARTY">Adquirido de terceiros (Envato, marketplace etc.)</option>
          <option value="FREE_LICENSE">Licença livre com uso comercial permitido</option>
          <option value="OWNED_GENERATED">Criado por você e com direitos de uso</option>
        </select></label>
        <label>Comprovante / termos de uso<textarea rows={3} required minLength={10} maxLength={2000} value={evidence} onChange={e=>setEvidence(e.target.value)} placeholder="ID ou link da licença, data de aquisição e usos permitidos"/></label>
        <button type="submit" className="primary" disabled={loading||!file}><UploadCloud size={16}/>{loading?'Processando...':'Adicionar à biblioteca'}</button>
      </form>
      {error&&<p role="alert" className="error">{error}</p>}
      {notice&&<p role="status" className="success">{notice}</p>}
    </section>
    <section className="panel">
      <div className="section-title"><h2>Estilos disponíveis ({data.items.length})</h2>{data.active_id&&<button disabled={loading} onClick={()=>toggle()}>Desativar efeito</button>}</div>
      {!data.items.length&&<p className="muted">Nenhum estilo anexado. Envie um dos ZIPs e ative-o.</p>}
      <div className="text-style-grid">
        {data.items.map(item=><article className="text-style-card" key={item.id}>
          <Preview id={item.id} token={token}/>
          <div><h3>{item.title}</h3><small>{item.kind==='font'?'Fonte instalável':'Efeito vetorial EPS/JPG'} · {themes.find(x=>x.value===item.theme)?.name||item.theme}</small>
            <small><ShieldCheck size={12}/> Licença declarada · arquivos preservados no estúdio</small>
            {item.active?<strong className="success"><Check size={14}/> Estilo ativo</strong>:<button disabled={loading} onClick={()=>toggle(item.id)}>Usar nas próximas edições</button>}
          </div>
        </article>)}
      </div>
      <small>O efeito ativo estiliza o gancho de novos renders. Vídeos já finalizados não mudam. Sem um estilo ativo, o Editor mantém a aparência anterior.</small>
    </section>
  </div>;
}
