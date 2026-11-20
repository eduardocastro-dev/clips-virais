'use client';

import {useMemo,useState} from 'react';
import {ChevronDown,ChevronUp,Clapperboard,ExternalLink,Film,Trash2} from 'lucide-react';
import SeoPanel from './seo-panel';

type Row=Record<string,any>;
type Group={id:string;title:string;publications:Row[];videoIds:string[];updated:number;test:boolean};
type Props={
  publications:Row[];videos:Row[];
  api:(path:string,body?:unknown,method?:string)=>Promise<any>;
  onOpenVideo:(video:Row)=>Promise<void>;
  onChanged:()=>Promise<any>;
  onError:(message:string)=>void;
};

const platformNames:Record<string,string>={youtube:'YouTube',instagram:'Instagram',tiktok:'TikTok'};
const statuses:Record<string,string>={
  PUBLICADO:'Publicado',AGUARDANDO_PUBLICACAO_MANUAL:'Pronto para postar',
  AGENDADO:'Agendado',DISCARDED:'Descartado',PUBLICANDO:'Enviando'
};

export function groupPublications(publications:Row[],videos:Row[]):Group[]{
  const videosById=new Map(videos.map(v=>[v.id,v]));
  const grouped=new Map<string,Group>();
  for(const p of publications){
    // Titles from the main video are canonical; SEO titles may differ by
    // platform. Where several IDs share the same canonical title, display
    // them as one group but keep their individual source-video actions.
    const title=String(videosById.get(p.video_id)?.title||p.title||'Vídeo sem título').trim();
    const titleKey=title.normalize('NFKC').replace(/\s+/g,' ').toLocaleLowerCase('pt-BR');
    const id=titleKey||String(p.video_id||p.id);
    if(!grouped.has(id))grouped.set(id,{
      id,title,publications:[],videoIds:[],updated:0,test:false
    });
    const group=grouped.get(id)!;
    group.publications.push(p);
    if(p.video_id&&!group.videoIds.includes(p.video_id))group.videoIds.push(p.video_id);
    group.updated=Math.max(group.updated,Number(p.updated||0));
    group.test=group.test||Boolean(p.test);
  }
  return [...grouped.values()].sort((a,b)=>b.updated-a.updated);
}

export default function PublicationGroups({publications,videos,api,onOpenVideo,onChanged,onError}:Props){
  const groups=useMemo(()=>groupPublications(publications,videos),[publications,videos]);
  const [expanded,setExpanded]=useState<Record<string,boolean>>({});
  const [publicationUrls,setPublicationUrls]=useState<Record<string,string>>({});
  const [busyId,setBusyId]=useState<string|null>(null);
  const [notice,setNotice]=useState('');
  const byId=new Map(videos.map(v=>[v.id,v]));

  async function run(id:string,operation:()=>Promise<unknown>,message:string){
    setBusyId(id);onError('');setNotice('');
    try{await operation();await onChanged();setNotice(message)}
    catch(e){onError((e as Error).message)}finally{setBusyId(null)}
  }
  if(!groups.length)return <div className="empty">
    <Film size={30}/>
    <h3>Sua fila editorial está vazia</h3>
    <p>Vídeos aprovados aparecerão aqui, agrupados pelo título e com as plataformas disponíveis.</p>
  </div>;
  return <div className="publication-groups">
    {notice&&<p className="success" role="status">{notice}</p>}
    {groups.map(group=>{
      const published=group.publications.filter(p=>p.status==='PUBLICADO').length;
      const pending=group.publications.filter(p=>p.status==='AGUARDANDO_PUBLICACAO_MANUAL').length;
      const open=Boolean(expanded[group.id]);
      return <article className="publication-group" key={group.id}>
        <div className="publication-group-heading">
          <div className="publication-group-cover"><Clapperboard size={24}/></div>
          <div className="publication-group-info">
            <h3>{group.title}</h3>
            <small>{group.publications.length} {group.publications.length===1?'destino':'destinos'} · {group.videoIds.length} {group.videoIds.length===1?'arquivo':'arquivos'} · atualizado em {new Date(group.updated*1000).toLocaleString('pt-BR')}</small>
            {group.test&&<small className="ops-error">VÍDEO TÉCNICO DE TESTE · NÃO PUBLICAR</small>}
            <div className="publication-platforms">{group.publications.map(p=>
              <span className={'publication-platform '+(p.status==='PUBLICADO'?'posted':p.status==='DISCARDED'?'disabled':'')} key={p.id}>
                {platformNames[p.platform]||p.platform} <b>{statuses[p.status]||p.status}</b>
              </span>)}
            </div>
            <small className="publication-progress">
              {published} publicado{published===1?'':'s'} · {pending} pronto{pending===1?'':'s'} para postagem manual
            </small>
          </div>
          <div className="publication-group-actions">
            {group.videoIds.map((videoId,i)=>{
              const video=byId.get(videoId);
              return video?<button key={videoId} disabled={Boolean(busyId)} onClick={()=>run('video:'+videoId,()=>onOpenVideo(video),'Vídeo aberto para revisão.')}>
                <Film size={15}/> {group.videoIds.length>1?'Revisar arquivo '+(i+1):'Revisar / baixar'}
              </button>:null;
            })}
            <button className={open?'primary':''}
              aria-expanded={open}
              onClick={()=>setExpanded(p=>({...p,[group.id]:!p[group.id]}))}>
              {open?<ChevronUp size={16}/>:<ChevronDown size={16}/>}
              {open?'Ocultar detalhes':'Ver plataformas e SEO'}
            </button>
          </div>
        </div>
        {open&&<div className="publication-group-details">
          {group.publications.map(p=>
            <section className="publication-platform-details" key={p.id} aria-label={'Publicação '+p.platform}>
              <div className="publication-platform-detail-head">
                <div><strong>{platformNames[p.platform]||p.platform}</strong>
                  <small>{statuses[p.status]||p.status} · {new Date(p.updated*1000).toLocaleString('pt-BR')}</small>
                </div>
                {p.url&&<a href={p.url} target="_blank" rel="noopener noreferrer">Abrir postagem <ExternalLink size={13}/></a>}
              </div>
              {p.error&&<p className="ops-error">{p.error}</p>}
              <SeoPanel publication={p} api={api}/>
              <div className="publication-group-row-actions">
                {p.status!=='PUBLICADO'&&<button className="danger" disabled={Boolean(busyId)}
                  onClick={()=>{
                    if(window.confirm('Remover '+String(p.platform).toUpperCase()+' desta lista? O vídeo será preservado.'))
                      void run(p.id,()=>api('publications/'+p.id,{},'DELETE'),'Destino removido; os demais permanecem.');
                  }}><Trash2 size={14}/> Remover destino</button>}
                {p.status!=='PUBLICADO'&&!p.test&&<form onSubmit={e=>{
                  e.preventDefault();
                  void run(p.id,()=>api('publications/'+p.id+'/confirm',
                    {url:publicationUrls[p.id]},'POST'),'Publicação confirmada para '+p.platform+'.');
                }}>
                  <input aria-label={'URL publicada no '+p.platform}
                    type="url" required placeholder="Cole o link depois de postar manualmente"
                    value={publicationUrls[p.id]||''}
                    onChange={e=>setPublicationUrls(prev=>({...prev,[p.id]:e.target.value}))}/>
                  <button disabled={Boolean(busyId)}>Confirmar postagem</button>
                </form>}
              </div>
            </section>
          )}
        </div>}
      </article>;
    })}
  </div>;
}
