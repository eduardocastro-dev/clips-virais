import { NextRequest } from 'next/server';
export const dynamic = 'force-dynamic';
// Stream binary chunks without buffering entire media files in the Next.js process.
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  if (path.some(part => !/^[a-zA-Z0-9_-]+$/.test(part))) return Response.json({detail:'Caminho inválido.'},{status:400});
  const query = request.nextUrl.searchParams.toString();
  const target = `${process.env.API_URL || 'http://127.0.0.1:8000'}/api/${path.join('/')}${query?'?'+query:''}`;
  try {
    const method=request.method;
    const init: RequestInit & {duplex?:'half'} = {
      method,
      headers: {
        Authorization: request.headers.get('authorization') || '',
        ...(request.headers.get('content-type') ? {'Content-Type':request.headers.get('content-type')!}:{}),
        ...(request.headers.get('upload-offset') ? {'Upload-Offset':request.headers.get('upload-offset')!}:{}),
        ...(request.headers.get('range') ? {'Range':request.headers.get('range')!}:{}),
      },
      cache:'no-store',
      signal:AbortSignal.timeout(15*60_000),
    };
    if (!['GET','HEAD'].includes(method) && request.body) {init.body=request.body;init.duplex='half';}
    const response=await fetch(target,init);
    const headers=new Headers();
    for(const name of ['content-type','content-length','content-disposition','accept-ranges','content-range','cache-control']) {
      const v=response.headers.get(name); if(v)headers.set(name,v);
    }
    return new Response(response.body,{status:response.status,headers});
  } catch(e) {
    return Response.json({detail:'Falha de conexão/proxy durante a operação. O upload pode ser retomado.'},{status:503});
  }
}
export {proxy as GET,proxy as POST,proxy as PUT,proxy as DELETE,proxy as PATCH};
