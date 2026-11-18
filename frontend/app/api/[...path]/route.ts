import { NextRequest } from 'next/server';
export const dynamic = 'force-dynamic';
async function proxy(request: NextRequest, context: {params: Promise<{path: string[]}>}) {
  const {path} = await context.params;
  if (path.some(part => !/^[a-zA-Z0-9_-]+$/.test(part))) return new Response('Invalid path', {status: 400});
  const target = `${process.env.API_URL || 'http://127.0.0.1:8000'}/api/${path.join('/')}`;
  try {
    const response = await fetch(target, {method: request.method, headers: {
      'Authorization': request.headers.get('authorization') || '', 'Content-Type':'application/json',
      ...(request.headers.get('range') ? {'Range': request.headers.get('range')!} : {})
    }, body: ['GET','HEAD'].includes(request.method) ? undefined : await request.text(), cache:'no-store', signal: AbortSignal.timeout(60000)});
    const headers = new Headers();
    for (const name of ['content-type','content-length','content-disposition','accept-ranges','content-range']) {
      const value = response.headers.get(name); if(value) headers.set(name, value);
    }
    return new Response(response.body, {status:response.status, headers});
  } catch {return Response.json({detail:'Backend indisponível. Verifique o serviço API.'}, {status:503});}
}
export {proxy as GET, proxy as POST, proxy as PUT, proxy as DELETE};
