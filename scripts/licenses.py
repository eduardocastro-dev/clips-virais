"""Fetch public package metadata; never reads application credentials."""
import json
import urllib.request
from pathlib import Path

root = Path(__file__).resolve().parent.parent
packages = ['fastapi','uvicorn','SQLAlchemy','pydantic-settings','httpx','cryptography','feedparser','yt-dlp','piper-tts','faster-whisper','tzdata']
result=[]
for name in packages:
    with urllib.request.urlopen(f'https://pypi.org/pypi/{name}/json',timeout=30) as response:
        info=json.load(response)['info']
    result.append({'package':name,'metadata_version':info['version'],'license_expression':info.get('license_expression'),
        'license':info.get('license'),'classifiers':[c for c in info.get('classifiers',[]) if c.startswith('License')],
        'project_urls':info.get('project_urls'),'source':f'https://pypi.org/pypi/{name}/json'})
for name in ['next','react','tailwindcss','lucide-react']:
    with urllib.request.urlopen('https://registry.npmjs.org/'+name+'/latest',timeout=30) as response:
        info=json.load(response)
    result.append({'package':name,'metadata_version':info['version'],'license':info.get('license'),'source':'https://registry.npmjs.org/'+name+'/latest'})
(root/'docs/licenses-observed.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('Saved public metadata for',len(result),'packages.')
