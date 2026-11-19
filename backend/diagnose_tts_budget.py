"""Read-only diagnostic for productions paused by narration/TTS timing.

Run: docker compose exec api python -m backend.diagnose_tts_budget --limit 10
No inference, updates or credential output.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend import core as db


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        return None


def inspect(limit: int=10):
    db.init_db()
    rows=db.rows('''SELECT id,title,status,stage,duration,error,render_error,updated
        FROM videos WHERE status='PIPELINE_ERROR'
        AND (lower(coalesce(error,'')) LIKE '%redator%'
          OR lower(coalesce(error,'')) LIKE '%tts%'
          OR lower(coalesce(error,'')) LIKE '%narra%')
        ORDER BY updated DESC LIMIT :limit''',{'limit':max(1,min(100,limit))})
    report=[]
    for video in rows:
        handoff=db.ROOT/'handoff'/video['id']
        script=_load(handoff/'script.json') or {}
        scenes=script.get('scenes') or []
        timing=sorted(handoff.glob('narration-timing-adjust-*.json'))
        last=_load(timing[-1]) if timing else None
        report.append({
            'id':video['id'],'title':video['title'],'status':video['status'],
            'error':video.get('error') or video.get('render_error'),
            'duration_video_s':video.get('duration'),
            'script_total_words':sum(len(str(s.get('narration','')).split()) for s in scenes),
            'scene_words':[len(str(s.get('narration','')).split()) for s in scenes],
            'timing_rewrites':len(timing),'last_timing_result':last,
        })
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--limit',type=int,default=10)
    args=parser.parse_args()
    print(json.dumps(inspect(args.limit),ensure_ascii=False,indent=2))
