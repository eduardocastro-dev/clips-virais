"""Evidence ledger: extracts source claims without converting them into facts."""
import json
import re
from backend import core as db

RUMOR=re.compile(r'(?i)\b(rumor|rumour|supost[oa]s?|vazamento|leak|teoria|teori[ae]s?|alega|aparentemente)\b')

def extract(video, source):
    meta=source if isinstance(source,dict) else {}
    title=str(meta.get('title') or video.get('title') or '')
    description=str(meta.get('description') or '')
    url=str(meta.get('url') or video.get('url') or '')
    lines=[x.strip() for x in re.split(r'(?<=[.!?])\s+|\n+',title+'. '+description) if x.strip()]
    lines=[x[:400] for x in lines[:20] if len(x)>6]
    claims=[{'text':s,'classification':'RUMOR' if RUMOR.search(s) else 'SOURCE_CLAIM',
             'verification':'PENDENTE','source_url':url} for s in lines]
    return {'source_url':url,'source_title':title,'source_channel':meta.get('source_profile') or meta.get('channel'),
            'source_published':meta.get('published'),'today_sao_paulo':db.today(),
            'claims':claims,'rule':'SOURCE_CLAIM significa a fonte diz; não é confirmação externa. '
              'Cite a fonte e diferencie de RUMOR. Nunca invente métricas.'}
