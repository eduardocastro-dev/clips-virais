"""Read-only inventory of one production's source assets, manifests and previews.

Usage: python -m backend.diagnose_assets [--video VIDEO_ID] [--json]
No keys, source media, videos, or SQLite rows are modified.
"""
from __future__ import annotations
import argparse
import json
import os
import sqlite3
from pathlib import Path


def safe_local(root: Path, value: str | None) -> dict:
    if not value:
        return {"path": None, "exists_now": False, "inside_studio": None}
    path=Path(value)
    if not path.is_absolute():
        path=root / path
    resolved=path.resolve()
    return {"path": str(value), "exists_now": resolved.is_file(),
            "inside_studio": resolved.is_relative_to(root.resolve())}


def read_manifest(root: Path, video_id: str, attempt: int | None) -> tuple[str | None, list]:
    folder=root / 'handoff' / video_id
    candidates=[]
    if attempt:
        candidates.append(folder / f'visual-assets-attempt-{attempt}.json')
    candidates.append(folder / 'visual-assets.json')
    for path in candidates:
        if path.is_file():
            try:
                value=json.loads(path.read_text(encoding='utf-8'))
                if isinstance(value,list):
                    return str(path.relative_to(root)),value
            except (ValueError, OSError):
                return str(path.relative_to(root)),[]
    return None,[]


def report(root: Path, database: Path, video_id: str | None = None) -> dict:
    result={"database_exists": database.is_file(),"video_id":video_id,"status":"NOT_FOUND",
            "agents_in_v5":['diretor','cacador','escritor','editor','avaliador'],
            "scenes": [],"notes": ["Seleção no manifesto não prova que o asset foi usado no MP4; inspecione também os eventos do render."]}
    if not database.is_file():
        result['error']='Banco SQLite não encontrado. Execute no container API da instalação em uso.'
        return result
    conn=sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    conn.row_factory=sqlite3.Row
    try:
        cur=conn.cursor()
        if video_id:
            video=cur.execute('SELECT * FROM videos WHERE id=?',(video_id,)).fetchone()
        else:
            video=cur.execute('SELECT * FROM videos ORDER BY created DESC LIMIT 1').fetchone()
        if video is None:
            result['error']='Nenhuma produção cadastrada ou ID não encontrado.'
            return result
        video=dict(video)
        vid=video['id'];result['video_id']=vid;result['status']=video['status'];result['title']=video['title']
        result['render_final']=safe_local(root,video.get('final_path'))
        attempts=[dict(x) for x in cur.execute('SELECT attempt,verdict,render_path,render_error FROM video_attempts WHERE video_id=? ORDER BY attempt',(vid,))]
        for a in attempts:a['render_file']=safe_local(root,a.get('render_path'))
        result['attempts']=attempts
        selected=attempts[-1]['attempt'] if attempts else None
        manifest_file,manifest=read_manifest(root,vid,selected)
        result['visual_manifest']=manifest_file
        fallbacks=[dict(x) for x in cur.execute("SELECT status,summary,created FROM events WHERE video_id=? AND status IN ('VISUAL_FALLBACK','PERSONA_IMAGE_MISSING') ORDER BY created",(vid,))]
        result['render_fallback_events']=fallbacks
        for scene in manifest:
            segments=[]
            for part in scene.get('segments',[]) or [scene]:
                chosen=safe_local(root,part.get('path'))
                overlay=safe_local(root,part.get('overlay_path'))
                segments.append({'asset_id':part.get('asset_id'),'parent_id':part.get('parent_id'),
                    'kind':part.get('type'),'source':part.get('source'),
                    'source_class':part.get('source_class'),'selected_path':chosen,
                    'overlay_path':overlay,'overlay_label':part.get('overlay_label'),
                    'selected_in_manifest':True,
                    'used_in_render':'UNVERIFIED',
                    'reason': ('fallback de gradiente selecionado' if part.get('type')=='animated_gradient'
                               else ('arquivo de trabalho não existe agora (pode ter sido limpo após render)'
                                     if not chosen['exists_now'] else 'selecionado; confirmar uso no render'))})
            result['scenes'].append({'scene':scene.get('scene'), 'start':scene.get('start'),
                                    'end':scene.get('end'), 'segments':segments})
        persona_raw=cur.execute("SELECT value FROM kv WHERE key='persona'").fetchone()
        try: persona=json.loads(persona_raw[0]) if persona_raw else {}
        except (ValueError,TypeError):persona={}
        image=persona.get('image_path') or ''
        voice=persona.get('voice_model') or os.getenv('PIPER_MODEL','')
        result['persona']={'selected':persona.get('selected','nico_neon'),
                           'image':safe_local(root,image),
                           'voice_model_configured':bool(voice),
                           'voice_model_file_exists':Path(voice).is_file() if voice else False,
                           'dossier_file':'backend/personas.py',
                           'dossier_override_in_kv':bool(persona.get('overrides'))}
        music=cur.execute("SELECT COUNT(*) FROM assets WHERE category='musica' AND status='READY' AND rights_status='AUTHORIZED' AND COALESCE(active,1)=1 AND path IS NOT NULL").fetchone()
        result['authorized_music_rows']=music[0] if music else 0
    except sqlite3.OperationalError as exc:
        result['error']='Esquema de banco incompatível com esta versão: '+str(exc)
    finally:conn.close()
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video',help='ID da produção. Sem ID, escolhe a mais recente.')
    parser.add_argument('--json',action='store_true',help='Saída estruturada para anexar ao diagnóstico')
    args=parser.parse_args()
    root=Path(os.getenv('STUDIO_FILES','.')).resolve()
    database=Path(os.getenv('STUDIO_DATA',str(root/'data')))/'studio.sqlite'
    out=report(root,database,args.video)
    if args.json:
        print(json.dumps(out,ensure_ascii=False,indent=2))
        return
    print('PRODUÇÃO:',out.get('video_id'),'STATUS:',out['status'])
    print('BANCO:', 'encontrado' if out['database_exists'] else 'ausente')
    if out.get('error'):print('ERRO:',out['error'])
    if out.get('persona'):
        print('PERSONA:',out['persona'])
        print('MÚSICAS AUTORIZADAS:',out.get('authorized_music_rows'))
    print('MANIFESTO:',out.get('visual_manifest') or 'ausente')
    for scene in out['scenes']:
        print(f"CENA {scene['scene']}: {scene['start']}s–{scene['end']}s")
        for seg in scene['segments']:
            path=seg['selected_path']
            print(f"  {seg['kind']:<18} arquivo={path['path']} existe_agora={path['exists_now']} "
                  f"uso_no_render={seg['used_in_render']} motivo={seg['reason']}")
            if seg['overlay_path']['path']:
                print(f"    PRINT: {seg['overlay_path']['path']} existe_agora={seg['overlay_path']['exists_now']}")
    for x in out.get('render_fallback_events',[]):
        print('EVENTO RENDER:',x['status'],x['summary'])
    print('NOTA:',*out['notes'])


if __name__=='__main__':main()
