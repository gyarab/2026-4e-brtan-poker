"""Give tests disposable persistence and lock files without touching a running app."""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

_TEST_RUNTIME = Path(tempfile.mkdtemp(prefix="brtan-poker-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TEST_RUNTIME / 'poker.db').as_posix()}"
os.environ["SERVER_LOCK_PATH"] = str(_TEST_RUNTIME / ".uvicorn.lock")
os.environ["APP_ENV"] = "test"


@pytest.fixture(autouse=True)
def reset_in_memory_state():
    from app.services.game_logic import ROOMS

    ROOMS.clear()
    yield
    ROOMS.clear()
    try:
        from app.main import connected_clients

        connected_clients.clear()
    except ImportError:
        pass


def pytest_sessionfinish(session, exitstatus):
    try:
        from app.database import engine

        engine.dispose()
    except ImportError:
        pass
    shutil.rmtree(_TEST_RUNTIME, ignore_errors=True)
