from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_resource_preflight_v2 as preflight_v2
from scripts import f3_material_row30_resource_preflight_v3 as preflight_v3


def test_v3_reversions_v2_blocked_observation_without_worker_authority(monkeypatch) -> None:
    monkeypatch.setattr(preflight_v2, "build", lambda **kwargs: {
        "schema": "core.material.f3.row30.resource_preflight.v2",
        "record_id": "f3-material-row30-resource-preflight-v2",
        "status": "blocked_no_worker_authorized",
        "authorized_scope": "old scope",
        "worker_launch_authorized": False,
        "execution_controls": {"material_worker_started": False, "queue_mutation": 0},
        "bindings": [],
    })

    value = preflight_v3.build(
        environment_probe=lambda: {}, process_probe=lambda: [],
    )

    assert value["schema"] == "core.material.f3.row30.resource_preflight.v3"
    assert value["record_id"] == "f3-material-row30-resource-preflight-v3"
    assert value["authorized_scope"] == preflight_v3.AUTHORITY
    assert value["supersedes"]["path"].endswith("resource-preflight-v2/receipt.json")
    assert value["worker_launch_authorized"] is False
    assert all("v3" in item["path"] for item in value["bindings"])


def test_v3_write_once_consumes_lock_and_never_authorizes_worker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight_v3, "build", lambda **kwargs: {
        "schema": preflight_v3.SCHEMA,
        "record_id": preflight_v3.RECORD_ID,
        "status": "blocked_no_worker_authorized",
        "worker_launch_authorized": False,
    })
    scope = tmp_path / "row30-v3"

    value = preflight_v3.write_once(scope_dir=scope)

    assert json.loads((scope / "receipt.json").read_text(encoding="utf-8")) == value
    assert json.loads((scope / "one-shot-lock.json").read_text(encoding="utf-8"))["worker_launch_authorized"] is False
    assert value["worker_launch_authorized"] is False
    with pytest.raises(FileExistsError, match="namespace already exists"):
        preflight_v3.write_once(scope_dir=scope)
