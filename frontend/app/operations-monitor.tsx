'use client';

import {useEffect,useState} from 'react';
import {Activity,AlertTriangle,CheckCircle2,Clock3,Clapperboard,Film,LoaderCircle,Radio,RefreshCw,ShieldCheck} from 'lucide-react';

type Job = {
  id:string;video_id?:string|null;kind:string;type:string;title:string;
  status:string;stage?:string|null;stage_label:string;attempts:number;
  max_attempts:number;due_at:number;scheduled_in_seconds:number;
  since_last_step_seconds:number|null;error?:string|null;
  last_event?:{agent:string;summary:string;created:number}|null;
  stages:{id:string;label:string}[];
};
type Monitor = {
  server_time:number;worker:{online:boolean;heartbeat_age_seconds:number|null;status:string};
  running:Job[];queued:Job[];recent_failures:Job[];
  counts:{running:number;queued:number;retry_waiting:number};
  events:{agent:string;status:string;summary:string;created:number}[];
  scheduler_status:string;radar_status:string;manual_publication_only:boolean;
};
type Props={token:string;onOpenAgents:()=>void;onOpenLiveCuts:()=>void};

function duration(seconds:number|null|undefined){
  if(seconds===null||seconds===undefined)return 'não informado';
  if(seconds<60)return Math.max(0,Math.round(seconds))+'s';
  if(seconds<3600)return Math.floor(seconds/60)+'min '+Math.round(seconds%60)+'s';
  return Math.floor(seconds/3600)+'h '+Math.floor((seconds%3600)/60)+'min';
}
function taskKind(job:Job){
  return job.type==='clip'?'Corte de live':job.type==='pipeline'?'Short / Pipeline':'Pesquisa e manutenção';
}
function CurrentJob({job,onOpenAgents,onOpenLiveCuts}:{
  job:Job;onOpenAgents:()=>void;onOpenLiveCuts:()=>void
}){
  const current=job.stages.findIndex(s=>
    s.id===job.stage||Boolean(job.stage?.startsWith(s.id+'_')));
  const stale=job.since_last_step_seconds!==null&&job.since_last_step_seconds>=300;
  return <article className="ops-current" key={job.id}>
    <div className="ops-current-head">
      <span className="ops-kind">{job.type==='clip'?<Film size={15}/>:<Clapperboard size={15}/>} {taskKind(job)}</span>
      <span className="ops-running"><LoaderCircle size={14} className="spin"/> Executando</span>
    </div>
    <h3>{job.title}</h3>
    <div className="ops-step">
      <strong>{job.stage_label||'Iniciando job'}</strong>
      <small>Tentativa {job.attempts} de {job.max_attempts} · Etapa registrada há {duration(job.since_last_step_seconds)}</small>
    </div>
    {job.stages.length>0&&<ol className="ops-stages" aria-label="Etapas da produção">
      {job.stages.map((stage,i)=><li className={i<current?'completed':i===current?'active':''} key={stage.id}>
        <span>{i<current?<CheckCircle2 size={12}/>:i+1}</span>
        <small>{stage.label}</small>
      </li>)}
    </ol>}
    {stale&&<p className="ops-warning"><Clock3 size={15}/> Esta etapa está sem mudança registrada há {duration(job.since_last_step_seconds)}. Processos longos podem manter a mesma etapa enquanto o worker continua ativo.</p>}
    {job.last_event?.summary&&<p className="ops-event"><Activity size={14}/> {job.last_event.agent}: {job.last_event.summary}</p>}
    <button className="ops-jump" onClick={job.type==='clip'?onOpenLiveCuts:onOpenAgents}>
      {job.type==='clip'?'Ver cortes de lives':'Ver fila e agentes'}
    </button>
  </article>;
}

export default function OperationsMonitor({token,onOpenAgents,onOpenLiveCuts}:Props){
  const [state,setState]=useState<Monitor|null>(null);
  const [error,setError]=useState('');
  useEffect(()=>{
    if(!token)return;
    let closed=false,loading=false;
    const controller=new AbortController();
    async function poll(){
      if(closed||loading)return;
      loading=true;
      try{
        const res=await fetch('/api/operations/live',{
          headers:{Authorization:'Bearer '+token},cache:'no-store',
          signal:controller.signal
        });
        if(!res.ok)throw Error('HTTP '+res.status);
        const payload:Monitor=await res.json();
        if(!closed){setState(payload);setError('')}
      }catch(e){
        if(!closed)setError('Monitor indisponível: '+(e as Error).message);
      }finally{loading=false}
    }
    void poll();
    const interval=setInterval(()=>{void poll()},4000);
    return()=>{closed=true;clearInterval(interval);controller.abort()};
  },[token]);
  const status=state?.worker.status;
  const active=state?.running||[];
  const queued=state?.queued||[];
  return <section className="panel ops-monitor" aria-label="Monitor operacional da produção">
    <div className="section-title ops-title">
      <div>
        <h2><Radio size={17}/> Monitor de produção</h2>
        <p>Dados reais da fila e do worker · atualização automática a cada 4 segundos</p>
      </div>
      <span className={'ops-health '+(state?.worker.online?'online':'offline')} role="status">
        <span className="ops-health-dot"/>
        {!state?'Conectando…':!state.worker.online?'Worker sem heartbeat':status==='running'?'Produzindo agora':status==='waiting'?'Fila aguardando':'Worker disponível'}
      </span>
    </div>
    {error&&<p className="ops-warning" role="alert"><AlertTriangle size={16}/>{error} — mostrando a última leitura disponível.</p>}
    {!state?<div className="ops-loading"><LoaderCircle className="spin" size={18}/> Consultando a fila de trabalhos…</div>:<>
      <div className="ops-summary">
        <div><strong>{state.counts.running}</strong><small>Em execução</small></div>
        <div><strong>{state.counts.queued}</strong><small>Na fila</small></div>
        <div><strong>{state.counts.retry_waiting}</strong><small>Aguardando retentativa</small></div>
        <div><strong>{duration(state.worker.heartbeat_age_seconds)}</strong><small>Último heartbeat</small></div>
      </div>
      {!state.worker.online&&<p className="ops-warning" role="alert"><AlertTriangle size={16}/> Sem sinal recente do worker. Os jobs podem não estar avançando; consulte os logs do container antes de retomar.</p>}
      <div className="ops-columns">
        <div className="ops-stack">
          <h3>Executando agora</h3>
          {active.length?active.map(j=><CurrentJob key={j.id} job={j} onOpenAgents={onOpenAgents} onOpenLiveCuts={onOpenLiveCuts}/>)
          :<div className="ops-empty">{queued.length?'Nenhum job em execução neste instante. Os próximos estão listados ao lado.':'Nenhuma produção ativa neste momento.'}</div>}
        </div>
        <div className="ops-stack">
          <div className="ops-stack-title"><h3>Próximos trabalhos</h3><button className="text-button" onClick={onOpenAgents}>Abrir fila completa</button></div>
          {queued.length?queued.slice(0,6).map((j,i)=><div className="ops-queued" key={j.id}>
            <span className="ops-position">{i+1}</span>
            <div><strong>{j.title}</strong><small>{taskKind(j)} · {j.status==='QUEUED'?'Na fila':j.status}</small>
            {j.scheduled_in_seconds>0&&<small>Elegível em {duration(j.scheduled_in_seconds)}</small>}
            {j.error&&<small className="ops-error">{j.error}</small>}</div>
          </div>):<p className="muted">Fila vazia. O worker aguarda novas tarefas.</p>}
        </div>
      </div>
      <div className="ops-bottom">
        <div><h3>Atividade recente</h3>
          {state.events.length?state.events.slice(0,4).map((e,i)=><div className="ops-activity" key={e.created+':'+i}>
            <Activity size={14}/><span><strong>{e.agent}</strong> · {e.summary}<small>{new Date(e.created*1000).toLocaleString('pt-BR')}</small></span>
          </div>):<small>O histórico aparecerá quando houver eventos registrados.</small>}
        </div>
        <div><h3>Diagnóstico</h3>
          <p className="ops-diagnostic"><ShieldCheck size={15}/> {state.scheduler_status||'Agendador aguardando tarefas.'}</p>
          {state.radar_status&&<p className="ops-diagnostic"><RefreshCw size={15}/> {state.radar_status}</p>}
          {state.recent_failures.length>0&&<details><summary>Últimas falhas ({state.recent_failures.length})</summary>
            {state.recent_failures.slice(0,3).map(j=><p className="ops-error" key={j.id}><strong>{j.title}:</strong> {j.error||'Falha registrada sem detalhes.'}</p>)}
          </details>}
        </div>
      </div>
      <small className="ops-footnote">O monitor exibe etapas confirmadas, não porcentagens estimadas. Todos os vídeos ainda exigem revisão e publicação manual.</small>
    </>}
  </section>;
}
