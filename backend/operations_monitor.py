"""Read-only, near-live operational status for the GTA Studio dashboard.

No fabricated percentages: each stage is sourced from the persisted job, video,
live-clip and event records. Does not run, retry or modify any production job.
"""
from __future__ import annotations

import time
from backend import core as db

STAGES = {
    "clip": [
        ("VERIFYING", "Verificando origem e direitos"),
        ("DOWNLOADING_AUDIO", "Obtendo áudio autorizado"),
        ("ANALYZING_AUDIO", "Analisando picos de áudio"),
        ("TRANSCRIBING", "Transcrevendo com WhisperX"),
        ("SELECTING", "Selecionando melhor momento"),
        ("DOWNLOADING_EXCERPT", "Obtendo trecho da live"),
        ("RENDERING", "Editando e renderizando MP4"),
        ("VALIDATING", "Validando áudio e vídeo"),
        ("RENDERED", "Corte pronto"),
        ("READY_FOR_REVIEW", "Pronto para revisão humana"),
    ],
    "pipeline": [
        ("diretor", "Planejamento"),
        ("cacador", "Pesquisa e fontes"),
        ("escritor", "Roteiro"),
        ("redator", "Revisão da narração"),
        ("editor", "Edição e render"),
        ("avaliador", "Avaliação final"),
    ],
}

JOB_NAMES = {
    "radar20_scan": "Viral Radar · varredura de canais",
    "top20_refresh": "Atualização do ranking Top 20",
    "discover": "Pesquisa de oportunidades",
    "maintenance": "Manutenção do estúdio",
}


def _priority(kind: str) -> int:
    if kind.startswith("live_cut:"):
        return 0
    if kind == "pipeline":
        return 1
    if kind in ("radar20_scan", "top20_refresh"):
        return 9
    return 3


def _format_job(job, videos, clips, events, now):
    kind = str(job["kind"])
    clip = clips.get(kind.split(":", 1)[1]) if kind.startswith("live_cut:") else None
    video = videos.get(job.get("video_id")) if job.get("video_id") else None
    family = "clip" if clip is not None or kind.startswith("live_cut:") else "pipeline" if kind == "pipeline" else "background"
    source = clip if clip else video if video else {}
    fallback = ("Consulta de fonte" if kind.startswith("source:") else
                "Consulta de canal" if kind.startswith("profile:") else kind)
    label = source.get("title") or JOB_NAMES.get(kind) or fallback
    stage_code = (clip or {}).get("stage") if family == "clip" else (video or {}).get("stage") if family == "pipeline" else None
    if family == "background" and kind == "radar20_scan":
        stage_text = str(db.get_setting("radar20_scan_status", "Consultando canais públicos."))
    elif family == "clip" and stage_code and "_" in stage_code:
        parts=stage_code.rsplit("_",1)
        step=next((text for code,text in STAGES['clip'] if code==parts[0]),None)
        stage_text=(step+" · corte "+parts[1]+"/3") if step and parts[1].isdigit() else stage_code
    else:
        stage_text = next((text for code, text in STAGES.get(family, []) if code == stage_code),
                          stage_code or ("Na fila" if job["status"] == "QUEUED" else "Iniciando"))
    updated_at = float(source.get("updated") or 0)
    last_event = next((e for e in events if e.get("video_id") == job.get("video_id")),
                      None) if video else None
    if last_event and float(last_event["created"]) > updated_at:
        updated_at = float(last_event["created"])
    if updated_at <= 0:
        updated_at = None
    due = float(job["due"] or 0)
    return {
        "id":job["id"],
        "video_id":job.get("video_id"),
        "kind":kind,
        "type":family,
        "title":str(label)[:180],
        "status":job["status"],
        "stage":stage_code,
        "stage_label":stage_text,
        "stages":[{"id":code,"label":text} for code,text in STAGES.get(family,[])],
        "updated_at":updated_at,
        "since_last_step_seconds":round(max(0,now-updated_at)) if updated_at else None,
        "attempts":int(job.get("attempts") or 0),
        "max_attempts":(3 if family == "clip" else
                        3 if family == "pipeline" and job.get("video_id") and
                            db.get_setting("quota_auto_shorts:"+job["video_id"],False)
                        else 5 if family == "pipeline" else 3),
        "due_at":due,
        "scheduled_in_seconds":round(max(0,due-now)),
        "lease_at":job.get("lease"),
        "error":job.get("error") or source.get("error"),
        "last_event":(
            {"agent":last_event["agent"],"summary":last_event["summary"],
             "created":last_event["created"]} if last_event else None
        ),
        "priority":_priority(kind),
        "expected_cuts":int(clip.get("cut_target") or 3) if clip else None,
        "completed_cuts":(
            db.rows("""SELECT COUNT(*) AS n FROM live_clip_outputs WHERE parent_id=:id
                       AND status IN ('REVIEW_PENDING','APPROVED','DISCARDED')
                       AND file_path IS NOT NULL""",
                    {'id':clip['id']})[0]['n'] if clip else None
        ),
    }


def snapshot():
    now = time.time()
    beat = float(db.get_setting("worker_heartbeat", 0) or 0)
    age = round(max(0,now-beat)) if beat else None
    worker_online = beat > 0 and now-beat < 120
    all_jobs = db.rows(
        "SELECT id,video_id,kind,status,attempts,due,lease,error "
        "FROM jobs WHERE status IN ('RUNNING','QUEUED','RETRY') ORDER BY due LIMIT 150")
    failures = db.rows(
        "SELECT id,video_id,kind,status,attempts,due,lease,error FROM jobs "
        "WHERE status='FAILED' ORDER BY due DESC LIMIT 5")
    video_rows = db.rows("SELECT id,title,stage,status,updated,error "
                         "FROM videos ORDER BY updated DESC LIMIT 250")
    clip_rows = db.rows("SELECT id,title,stage,status,updated,error FROM live_clips "
                        "ORDER BY updated DESC LIMIT 250")
    events = db.rows(
        "SELECT video_id,agent,status,summary,created "
        "FROM events ORDER BY created DESC LIMIT 20")
    videos = {v["id"]:v for v in video_rows}
    clips = {v["id"]:v for v in clip_rows}
    live = [_format_job(j,videos,clips,events,now) for j in all_jobs]
    active = sorted(
        (x for x in live if x["status"] == "RUNNING"),
        key=lambda x:(_priority(x["kind"]),x["due_at"])
    )
    queued = sorted(
        (x for x in live if x["status"] != "RUNNING"),
        key=lambda x:(x["scheduled_in_seconds"]>0,_priority(x["kind"]),x["due_at"])
    )
    recent_failed = [_format_job(j,videos,clips,events,now) for j in failures]
    status = ("offline" if not worker_online else
              "running" if active else "waiting" if queued else "idle")
    return {
        "server_time":now,
        "worker":{"online":worker_online,"heartbeat_at":beat or None,
                  "heartbeat_age_seconds":age,"status":status},
        "running":active[:4],
        "queued":queued[:12],
        "counts":{"running":len(active),"queued":len(queued),
                  "retry_waiting":sum(x["scheduled_in_seconds"]>0 for x in queued)},
        "recent_failures":recent_failed,
        "events":[{"agent":e["agent"],"status":e["status"],
                   "summary":e["summary"],"created":e["created"]}
                  for e in events[:7]],
        "scheduler_status":db.get_setting("scheduler_status", ""),
        "radar_status":db.get_setting("radar20_scan_status", ""),
        "manual_publication_only":True,
    }
