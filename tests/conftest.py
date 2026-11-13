import json
from pathlib import Path
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from kurai.ingestion import import_rows
from kurai.main import create_app

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def rows():
    return json.loads((ROOT/'data/reviewed-events.json').read_text(encoding='utf-8'))


@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.delenv('DATABASE_URL',raising=False)
    url='sqlite:///'+(tmp_path/'test.db').as_posix()
    config=Config(str(ROOT/'alembic.ini'))
    config.set_main_option('script_location',str(ROOT/'migrations'))
    config.set_main_option('sqlalchemy.url',url)
    command.upgrade(config,'head')
    command.upgrade(config,'head')
    application=create_app(url,admin_token='test-only-key')
    yield application
    application.state.engine.dispose()


@pytest.fixture
def client(app,rows):
    with app.state.sessions() as session:
        import_rows(session,rows)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def admin():
    return {'Authorization':'Bearer test-only-key'}
