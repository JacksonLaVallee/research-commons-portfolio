import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import pytest
from backend import db
from server import initialize, app
from fastapi.testclient import TestClient

@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(db,'WORKSPACE',str(tmp_path))
    db.ACTIVE_PROJECT.set('default')
    initialize()
    with TestClient(app) as c: yield c

@pytest.fixture
def c(client):
    conn=db.connect()
    yield conn
    conn.close()
