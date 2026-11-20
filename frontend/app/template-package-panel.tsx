'use client';

import {useCallback,useEffect,useState} from 'react';
import {Upload,CheckCircle2} from 'lucide-react';

type Info={installed:boolean,template_count:number,expected_ids:string[],hint:string};
export default function TemplatePackagePanel({token}:{token:string}){
  const [file,setFile]=useState<File|null>(null);
  const [info,setInfo]=useState<Info|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const refresh=useCallback(async()=>{
    const res=await fetch('/api/templates/package',{headers:{Authorization:'Bearer '+token}});
    if(!res.ok)throw Error('Falha ao consultar templates instalados.');
    setInfo(await res.json());
  },[token]);
  useEffect(()=>{void refresh().catch(e=>setError(e.message))},[refresh]);
  async function install(event:React.FormEvent<HTMLFormElement>){
    event.preventDefault();
    if(!file)return;
    setBusy(true);setError('');setNotice('');
    try{
      const body=new FormData();body.append('file',file);
      const r=await fetch('/api/templates/package',{
        method:'POST',headers:{Authorization:'Bearer '+token},body});
      const result=await r.json();
      if(!r.ok)throw Error(result.detail||'Pacote rejeitado.');
      await refresh();setFile(null);
      setNotice('Os 9 templates PNG + suas camadas foram instalados no volume persistente.');
    }catch(e){setError((e as Error).message)}
    finally{setBusy(false)}
  }
  return <section className="panel templates-package">
    <div className="section-title"><div><h2>Cenários dos Shorts · pacote oficial</h2>
      <p className="muted">O arquivo templates.json do pacote é a fonte única das coordenadas e camadas.</p>
    </div>
    {info?.installed?<span className="good"><CheckCircle2 size={16}/> {info.template_count} cenários instalados</span>
     :<strong>Pacote não instalado</strong>}</div>
    <form onSubmit={e=>void install(e)} className="inline-form">
      <label>Arquivo gta_studio_templates.zip
        <input type="file" accept=".zip,application/zip"
               onChange={e=>setFile(e.target.files?.[0]||null)} required/>
      </label>
      <button className="primary" type="submit" disabled={busy||!file}>
        <Upload size={15}/> {busy?'Validando…':'Instalar pacote'}
      </button>
    </form>
    {error&&<p className="banner error">{error}</p>}
    {notice&&<p className="banner">{notice}</p>}
    <p className="muted">Inclui 9 plates transparentes, 9 overlays de primeiro plano,
      SVGs originais e templates.json. A TV inferior é uma janela transparente;
      a mídia da notícia ocupa a área superior. Sem etiqueta de fonte sobre o vídeo,
      salvo quando exigida pela licença.</p>
  </section>;
}
