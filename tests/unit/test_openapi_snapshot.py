"""TASK-07 §14.2 step 9: committed OpenAPI snapshot stays in sync with the app."""

from __future__ import annotations

import json
from pathlib import Path

from app.main import app

SNAPSHOT = Path(__file__).resolve().parents[2] / "docs" / "task07" / "openapi-v1.json"


def test_openapi_snapshot_matches_application():
    committed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert committed == app.openapi()
