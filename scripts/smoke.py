"""Read-only operational assertions plus optional restart fixture creation. Never publishes."""
import json
import os
import sys
import time
from pathlib import Path
import httpx

def token():
    if os.getenv('STUDIO_TOKEN'):
        return os.environ['STUDIO_TOKEN']
    env = Path('.env').read_text('utf-8-sig')
    return next(line.split('=',1)[1] for line in env.splitlines() if line.startswith('STUDIO_TOKEN='))

client=httpx.Client(base_url='http://127.0.0.1:8000',headers={'Authorization':'Bearer '+token()},timeout=30)
state=client.get('/api/state');state.raise_for_status();data=state.json()
assert data['worker_online'], 'Worker heartbeat absent'
videos=[v for v in data['videos'] if v['test'] and v['approved']]
assert videos, 'Generate a synthetic video in the panel first'
video=videos[0]
assert len([p for p in data['publications'] if p['video_id']==video['id']])==3
assert not any(p['status']=='PUBLICADO' for p in data['publications']), 'Smoke environment must not publish'
r=client.get('/api/files/'+video['id']);r.raise_for_status()
target=Path('docs/evidence');target.mkdir(parents=True,exist_ok=True)
(target/'pipeline-test.mp4').write_bytes(r.content)
handoffs=client.get('/api/handoffs/'+video['id']);handoffs.raise_for_status()
for name in ['diretor','cacador','escritor','editor','avaliador']:
    assert name+'.json' in handoffs.json()
summary={'video_id':video['id'],'status':video['status'],'bytes':len(r.content),'handoffs':list(handoffs.json()),
         'manual_publications':3,'external_publications':0,'worker_online':True}
record=target/'smoke-before-restart.json'
if '--after-restart' in sys.argv:
    prior=json.loads(record.read_text('utf-8'))
    assert prior['video_id']==video['id'] and prior['bytes']==len(r.content)
    summary['restart_persistence']='passed'
    record=target/'smoke-after-restart.json'
record.write_text(json.dumps(summary,indent=2),encoding='utf-8')
print(json.dumps(summary))
