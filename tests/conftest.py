"""Test-wide fixtures: build a fresh Highway Bites SQLite DB once per session
and point the repository's cached connection at it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from drive_thru.db import init_db as init_db_mod
from drive_thru.db import repository as repo


@pytest.fixture(scope="session")
def seeded_db_path(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("db") / "drive_thru.db"
    init_db_mod.init_db(path, reset=True)
    return path


@pytest.fixture(autouse=True)
def _point_repo_at_test_db(seeded_db_path, monkeypatch):
    """Make every test use the seeded DB regardless of DB_PATH env."""
    repo.close_all()
    monkeypatch.setattr(repo, "DEFAULT_DB_PATH", seeded_db_path)
    yield
    repo.close_all()
