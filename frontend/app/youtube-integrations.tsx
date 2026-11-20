'use client';

import {useCallback,useEffect,useState} from 'react';
import {CheckCircle2,Clipboard,Eye,EyeOff,Link2,RefreshCw,ShieldCheck,Trash2} from 'lucide-react';

type Data=Record<string,any>;
async function req(token:string,path:string,body?:unknown,method='GET'){
  const res=await fetch('/api/youtube/'+path,{
    method,cache:'no-store',headers:{
      Authorization:'Bearer '+token,
      ...(body!==undefined?{'Content-Type':'application/json'}:{})},
    body:body!==undefined?JSON.stringify(body):undefined});
  if(!res.ok){
    const data=await res.json().catch(()=>({detail:'Erro HTTP '+res.status}));
    throw Error(data.detail||'Erro HTTP '+res.status);
  }
  return res.json();
}
export default function YouTubeIntegrations({token}:{token:string}){
  const [data,setData]=useState<Data|null>(null);
  const [key,setKey]=useState('');
  const [keyVisible,setKeyVisible]=useState(false);
  const [clientId,setClientId]=useState('');
  const [clientSecret,setClientSecret]=useState('');
  const [clientVisible,setClientVisible]=useState(false);
  const [test,setTest]=useState<Data|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const callback=(typeof window!=='undefined'?window.location.origin:'http://127.0.0.1:3000')+
    '/api/youtube/oauth/callback';
  const refresh=useCallback(async()=>{
    setData(await req(token,'status'));
  },[token]);
  useEffect(()=>{refresh().catch(e=>setError(e.message))},[refresh]);
  async function act(fn:()=>Promise<void>,message:string){
    setBusy(true);setError('');setNotice('');
    try{await fn();await refresh();setNotice(message)}
    catch(e){setError((e as Error).message)}
    finally{setBusy(false)}
  }
  const keyStatus= !data?.key_configured?'Não configurada':
    test?.status==='VALID'?'Válida':
    test?.status==='INVALID'?'Inválida':
    test?.status==='QUOTA_EXCEEDED'?'Cota excedida':
    'Configurada · ainda não testada';
  return <section className="panel youtube-integrations">
    <div className="section-title">
      <div><h2>YouTube · API v3 e Login Google</h2>
        <p className="muted">A chave e os tokens ficam criptografados no servidor. Apenas o final da chave é exibido.</p>
      </div><button onClick={()=>void refresh().catch(e=>setError(e.message))}
        disabled={busy}><RefreshCw size={14}/> Atualizar</button>
    </div>
    {error&&<p className="banner error" role="alert">{error}</p>}
    {notice&&<p className="banner" role="status">{notice}</p>}
    <div className="youtube-integrations-grid">
      <div>
        <h3>Chave da API</h3>
        <p className="muted">Estado: <strong>{keyStatus}</strong>
          {data?.key_last4&&' · final '+data.key_last4}</p>
        <label>YouTube Data API v3
          <input type={keyVisible?'text':'password'} autoComplete="off"
            value={key} onChange={e=>setKey(e.target.value)}
            placeholder="Cole sua chave; o servidor não a devolve"/>
        </label>
        <div className="actions">
          <button type="button" onClick={()=>setKeyVisible(v=>!v)}>
            {keyVisible?<EyeOff size={14}/>:<Eye size={14}/>}
            {keyVisible?'Ocultar':'Mostrar'}</button>
          <button type="button" onClick={()=>void navigator.clipboard.readText()
            .then(setKey).catch(()=>setError('O navegador não permitiu ler a área de transferência.'))}>
            <Clipboard size={14}/> Colar</button>
          <button disabled={busy||key.trim().length<16} onClick={()=>void act(async()=>{
            await req(token,'key',{key:key.trim()},'PUT');setKey('');setTest(null);
          },'Chave salva de modo criptografado.')}>Salvar</button>
          <button disabled={busy||!data?.key_configured}
            onClick={()=>void act(async()=>{
              const result=await req(token,'key/test',{},'POST');
              setTest(result);if(result.status!=='VALID')throw Error(result.message);
            },'Chave verificada com videos.list (1 chamada).')}>Testar chave</button>
          <button disabled={busy||!data?.key_configured} onClick={()=>{
            if(window.confirm('Remover a chave da API do cofre do Studio?'))
              void act(async()=>{await req(token,'key',undefined,'DELETE');setTest(null)},
                       'Chave removida do servidor.');
          }}><Trash2 size={14}/> Remover</button>
        </div>
        <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com"
          target="_blank" rel="noopener noreferrer">
          Como criar e restringir uma chave no Google Cloud
        </a>
        <p className="muted">Ative YouTube Data API v3 e restrinja a chave somente a essa API. Não use uma chave de administrador.</p>
      </div>
      <div>
        <h3>Login com Google (OAuth 2.0 / PKCE)</h3>
        <p className="muted">Conta: {data?.account||'Não conectada'}
          {data?.oauth_connected?' · Conectada':' · Desconectada'}
          {data?.oauth_expires_at?' · token expira '+new Date(data.oauth_expires_at*1000).toLocaleString('pt-BR'):''}
        </p>
        <form onSubmit={e=>{
          e.preventDefault();
          void act(async()=>{
            await req(token,'oauth/client',{client_id:clientId,client_secret:clientSecret},'PUT');
            setClientId('');setClientSecret('');
          },'Credenciais OAuth salvas no cofre.');
        }}>
          <label>Client ID Google<input type="text" autoComplete="off"
            value={clientId} onChange={e=>setClientId(e.target.value)}
            placeholder="ID de cliente OAuth 2.0"/>
          </label>
          <label>Client Secret
            <input type={clientVisible?'text':'password'} autoComplete="off"
              value={clientSecret} onChange={e=>setClientSecret(e.target.value)}/>
          </label>
          <div className="actions">
            <button type="button" onClick={()=>setClientVisible(v=>!v)}>
              {clientVisible?'Ocultar':'Mostrar'}</button>
            <button disabled={busy||!clientId.trim()||!clientSecret.trim()}
              type="submit">Salvar Client ID e Secret</button>
          </div>
        </form>
        <label>Redirect URI (cadastrar exatamente no Google Cloud)
          <input readOnly value={callback}/>
        </label>
        <div className="actions">
          <button onClick={()=>void navigator.clipboard.writeText(callback)
            .then(()=>setNotice('Redirect URI copiado.'))
            .catch(()=>setError('Não foi possível copiar.'))}>
            <Clipboard size={14}/> Copiar Redirect URI</button>
          <button disabled={busy||!data?.client_configured}
            onClick={()=>void act(async()=>{
              const result=await req(token,'oauth/begin',{redirect_uri:callback},'POST');
              window.open(result.authorization_url,'_blank','noopener,noreferrer');
            },'Abra a nova aba do Google para concluir o login.')}>
            <Link2 size={14}/> {data?.oauth_connected?'Reconectar':'Entrar com Google'}
          </button>
          <button disabled={busy||!data?.oauth_connected}
            onClick={()=>{if(window.confirm('Revogar e desconectar a conta Google?'))
              void act(async()=>{await req(token,'oauth',undefined,'DELETE')},
                       'Conta desconectada; tokens locais invalidados.')}}>
            Desconectar
          </button>
        </div>
        <p className="muted">Escopo mínimo: <code>youtube.readonly</code>. Apps em modo de teste podem exigir reconexão após 7 dias.</p>
      </div>
    </div>
    <div className="youtube-quota">
      <h3>Consumo estimado da API · dia do Pacífico</h3>
      <strong>{data?.quota?.estimated_used??'—'} / {data?.quota?.daily_allocation_assumed??'10.000'} unidades</strong>
      <progress value={data?.quota?.estimated_used||0} max={data?.quota?.daily_allocation_assumed||10000}/>
      <p className="muted">{data?.quota?.note||'Aguardando conexão.'}
        {data?.quota?.warning_80pct?' · Atenção: atingiu 80% da estimativa.':''}
        {data?.quota?.blocked?' · Chamadas suspensas até a virada do dia no Pacífico.':''}
      </p>
      <small>Sem search.list no fluxo normal; uploads dos canais e vídeos em lotes até 50 IDs.</small>
    </div>
  </section>;
}
