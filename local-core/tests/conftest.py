import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client():
    # In-memory DB per test → full isolation.
    app = create_app(db_path=":memory:")
    with TestClient(app) as c:
        yield c
    app.state.db.close()
