# GTA Studio - delete failed/rejected videos and synthetic tests only.
# Compatible with Windows PowerShell 5.1 and PowerShell 7.
$ErrorActionPreference = 'Stop'
$previousEncoding = $OutputEncoding
$OutputEncoding = [System.Text.Encoding]::UTF8
$workerWasRunning = $false
$workerStopped = $false

try {
    docker compose version | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Docker Compose indisponivel.' }

    $runningServices = @(docker compose ps --status running --services)
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao consultar containers.' }
    $workerWasRunning = $runningServices -contains 'worker'
    if ($workerWasRunning) {
        Write-Host 'Pausando o worker para impedir processamento durante a limpeza...'
        docker compose stop worker
        if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel parar o worker.' }
        $workerStopped = $true
    }

    $python = @'
from pathlib import Path
from datetime import datetime
import sqlite3
import shutil
import sys

from backend import core as db

DB = db.DATA / 'studio.sqlite'
ROOT = db.ROOT.resolve()
if not DB.is_file():
    raise SystemExit('Banco do GTA Studio nao encontrado. Nada foi removido.')

# An online SQLite backup also includes uncheckpointed WAL transactions.
backup_dir = db.DATA / 'backups'
backup_dir.mkdir(parents=True, exist_ok=True)
backup = backup_dir / ('studio-before-clean-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f') + '.sqlite')
with sqlite3.connect(str(DB), timeout=30) as source:
    with sqlite3.connect(str(backup), timeout=30) as dest:
        source.backup(dest)
print('Backup do banco:', backup, flush=True)

conn = sqlite3.connect(str(DB), timeout=30)
conn.execute('PRAGMA foreign_keys=ON')
conn.execute('PRAGMA busy_timeout=30000')
try:
    conn.execute('BEGIN IMMEDIATE')
    targets = conn.execute('''
        SELECT v.id, v.status, v.test
          FROM videos v
         WHERE v.test = 1
            OR v.status IN ('FAILED', 'REJECTED')
            OR EXISTS (SELECT 1 FROM jobs j WHERE j.video_id = v.id AND j.status = 'FAILED')
    ''').fetchall()
    if not targets:
        conn.rollback()
        print('Nenhum video com falha/reprovado ou marcado como teste. Nada a excluir.')
        sys.exit(0)

    ids = [r[0] for r in targets]
    marks = ','.join('?' for _ in ids)
    pubs = conn.execute('SELECT id, video_id, output_path FROM publications WHERE video_id IN (' + marks + ')', ids).fetchall()
    jobs = conn.execute('SELECT id FROM jobs WHERE video_id IN (' + marks + ')', ids).fetchall()

    print('Videos selecionados para exclusao:', len(ids))
    for vid, status, test in targets:
        print('  ', vid, '| estado:', status, '| teste:', bool(test))

    # Foreign key order: metrics -> publications -> jobs -> videos.
    conn.execute('DELETE FROM metrics WHERE publication_id IN (SELECT id FROM publications WHERE video_id IN (' + marks + '))', ids)
    conn.execute('DELETE FROM publications WHERE video_id IN (' + marks + ')', ids)
    conn.execute('DELETE FROM jobs WHERE video_id IN (' + marks + ')', ids)
    conn.execute('DELETE FROM events WHERE video_id IN (' + marks + ')', ids)
    keys = ['manual:' + p[0] for p in pubs] + ['job-error:' + j[0] for j in jobs] + ['rejected:' + v for v in ids]
    if keys:
        conn.execute('DELETE FROM notifications WHERE event_key IN (' + ','.join('?' for _ in keys) + ')', keys)
    conn.execute('DELETE FROM videos WHERE id IN (' + marks + ')', ids)
    conn.commit()
finally:
    conn.close()

# Files are deleted only from the known per-video locations inside /studio.
def remove_safe(path, folder):
    allowed = (ROOT / folder).resolve()
    path = Path(path)
    if path.is_symlink():
        print('Ignorando link simbolico:', path)
        return 0
    resolved = path.resolve()
    if not resolved.is_relative_to(allowed):
        print('Ignorando caminho fora da pasta permitida:', path)
        return 0
    if path.is_dir():
        shutil.rmtree(path)
        return 1
    if path.is_file():
        path.unlink()
        return 1
    return 0

removed = 0
for vid in ids:
    removed += remove_safe(ROOT / 'handoff' / vid, 'handoff')
    removed += remove_safe(ROOT / 'videos' / 'processing' / vid, 'videos/processing')
    removed += remove_safe(ROOT / 'videos' / 'raw' / (vid + '.mp4'), 'videos/raw')
    removed += remove_safe(ROOT / 'videos' / 'final' / (vid + '.mp4'), 'videos/final')
    for path in (ROOT / 'output').glob('*/[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]/video_' + vid + '.mp4'):
        removed += remove_safe(path, 'output')
        removed += remove_safe(path.with_name('metadata_' + vid + '.json'), 'output')
for _pid, vid, rel in pubs:
    if not rel:
        continue
    path = ROOT / rel
    if path.name == 'video_' + vid + '.mp4':
        removed += remove_safe(path, 'output')
        removed += remove_safe(path.with_name('metadata_' + vid + '.json'), 'output')

try:
    from backend.pipeline import daily_report
    daily_report()
except Exception as exc:
    print('Aviso: relatorio nao atualizado:', type(exc).__name__)
print('Limpeza concluida:', len(ids), 'videos retirados da esteira;', removed, 'arquivos/pastas removidos.')
print('Aprovados e uso de IA preservados.')
'@

    Write-Host 'Executando backup e limpeza seletiva...'
    $python | docker compose exec -T api python -
    if ($LASTEXITCODE -ne 0) { throw 'Limpeza interrompida. Verifique o log e o backup antes de repetir.' }
}
finally {
    $OutputEncoding = $previousEncoding
    if ($workerStopped) {
        Write-Host 'Reiniciando o worker...'
        docker compose start worker
        if ($LASTEXITCODE -ne 0) { Write-Warning 'O worker precisa ser reiniciado manualmente: docker compose start worker' }
    }
}
