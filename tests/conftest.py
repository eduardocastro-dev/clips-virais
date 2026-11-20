import os
import tempfile
from pathlib import Path
import pytest

_root = tempfile.mkdtemp(prefix='gta-studio-tests-')
os.environ['STUDIO_FILES'] = _root
os.environ['STUDIO_DATA'] = str(Path(_root) / 'data')
os.environ['STUDIO_TOKEN'] = 'test-token-local-only'
from backend import core as db
from backend.api import app
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset():
    db.init_db()
    for table in ['metrics','publications','video_attempts','live_clip_outputs','live_clips','jobs','events','videos','notifications','profiles','opportunities','sources','usage','cache','assets','kv']:
        db.execute(f'DELETE FROM {table}')
    yield


@pytest.fixture
def client():
    with TestClient(app, headers={'Authorization': 'Bearer test-token-local-only'}) as c:
        yield c
