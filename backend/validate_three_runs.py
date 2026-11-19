"""Read-only report for the three most recent real GTA Studio productions.

Run inside Docker: python -m backend.validate_three_runs --latest 3
Never requeues work, publishes videos or changes any database record.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from backend import core as db, media, storyboard
from backend.contracts import Script


def inspect(limit: int = 3) -> list[dict]:
    rows=db.rows('''SELECT id,title,status,error,duration,rights,final_path FROM videos
                   WHERE test=0 ORDER BY created DESC LIMIT :limit''',{'limit':limit})
    results=[]
    margin=db.settings().narration_margin_seconds
    for row in rows:
        vid=row['id']
        record={'id':vid,'title':row['title'],'status':row['status'],
                'video_expected_seconds':row['duration'],'problems':[],
                'render_path':row['final_path'],'pipeline_error':row['error']}
        script_file=db.ROOT/'handoff'/vid/'script.json'
        if not script_file.is_file():
            record['problems'].append('Script ausente')
        else:
            try:
                script=Script.model_validate_json(script_file.read_text('utf-8'))
                record['script_valid']=True
                record['script_music']=script.music
                record['source_starts_seconds']=[x.source_start for x in script.scenes]
                if script.duration!=row['duration']:
                    record['problems'].append('Duração do Script diferente da produção')
                local_seconds=storyboard.local_source_seconds(db.ROOT,vid,row['rights'])
                if local_seconds is not None:
                    for idx,scene in enumerate(script.scenes,1):
                        if scene.source_start+scene.end-scene.start>local_seconds+.01:
                            record['problems'].append(f'Cena {idx} excede duração local da fonte')
            except (OSError,ValueError,TypeError) as exc:
                record['script_valid']=False
                record['problems'].append('Script inválido: '+str(exc)[:240])
        render_path = (db.ROOT/row['final_path']) if row['final_path'] else None
        if render_path and render_path.is_file():
            try:
                technical=media.technical_check(render_path,row['duration'])
                record['render_valid']=bool(technical.get('valid'))
                record['render_report']=technical
                if not technical.get('valid'):
                    record['problems'].append('Render tecnicamente inválido: '+str(technical.get('failures'))[:260])
            except (ValueError,OSError,RuntimeError) as exc:
                record['render_valid']=False
                record['problems'].append('Não foi possível ler o render: '+str(exc)[:240])
        else:
            record['render_valid']=False
            record['problems'].append('MP4 final ausente')
        timelines=sorted((db.ROOT/'videos'/'processing'/vid).glob('attempt-*/audio-timeline.json'))
        if timelines:
            try:
                timeline=json.loads(timelines[-1].read_text('utf-8'))
                target=float(row['duration'])-float(margin)
                seconds=float(timeline['speech_real_seconds'])
                record['narration_seconds']=seconds
                record['narration_target_seconds']=target
                if not target-2-.1<=seconds<=target+.1:
                    record['problems'].append(f'Narração fora do orçamento: {seconds:.2f}s, meta {target-2:.2f}–{target:.2f}s')
            except (OSError,ValueError,KeyError,TypeError) as exc:
                record['problems'].append('Linha do tempo inválida: '+str(exc)[:200])
        else:
            record['problems'].append('Áudio medido não encontrado')
        record['passed']=not record['problems']
        results.append(record)
    return results


def main() -> int:
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--latest',type=int,default=3)
    args=ap.parse_args()
    if not 1<=args.latest<=30:ap.error('--latest deve estar entre 1 e 30')
    report=inspect(args.latest)
    print(json.dumps({'runs_found':len(report),'runs_expected':args.latest,
                      'all_passed':len(report)==args.latest and all(r['passed'] for r in report),
                      'runs':report},indent=2,ensure_ascii=False,default=str))
    return 0 if len(report)==args.latest and all(r['passed'] for r in report) else 1


if __name__=='__main__':raise SystemExit(main())
