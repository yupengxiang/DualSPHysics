from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_resource_preflight_v2 as preflight_v2
from scripts import f3_material_row30_resource_preflight_v7 as preflight_v7


def test_v7_binds_v6_history_and_preserves_no_worker_scope(monkeypatch) -> None:
    monkeypatch.setattr(preflight_v2, "build", lambda **kwargs: {
        "schema": "core.material.f3.row30.resource_preflight.v2",
        "record_id": "f3-material-row30-resource-preflight-v2",
        "status": "blocked_no_worker_authorized",
        "authorized_scope": "old scope",
        "worker_launch_authorized": False,
        "execution_controls": {"material_worker_started": False, "queue_mutation": 0},
        "bindings": [],
    })

    value = preflight_v7.build(environment_probe=lambda: {}, process_probe=lambda: [])

    assert value["schema"] == preflight_v7.SCHEMA
    assert value["record_id"] == preflight_v7.RECORD_ID
    assert value["authorized_scope"] == preflight_v7.AUTHORITY
    assert value["supersedes"]["path"].endswith("resource-preflight-v6/receipt.json")
    assert value["worker_launch_authorized"] is False
    assert value["execution_controls"]["material_worker_started"] is False
    assert {binding["path"] for binding in value["bindings"]} == {
        "scripts/f3_material_row30_resource_preflight_v7.py",
        "tests/test_f3_material_row30_resource_preflight_v7.py",
    }


def test_v7_write_once_records_lock_without_worker_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(preflight_v7, "build", lambda **kwargs: {
        "schema": preflight_v7.SCHEMA,
        "record_id": preflight_v7.RECORD_ID,
        "status": "blocked_no_worker_authorized",
        "worker_launch_authorized": False,
    })
    scope = tmp_path / "row30-v7"

    value = preflight_v7.write_once(scope_dir=scope)

    assert json.loads((scope / "receipt.json").read_text(encoding="utf-8")) == value
    lock = json.loads((scope / "one-shot-lock.json").read_text(encoding="utf-8"))
    assert lock["worker_launch_authorized"] is False
    assert value["worker_launch_authorized"] is False
    with pytest.raises(FileExistsError, match="namespace already exists"):
        preflight_v7.write_once(scope_dir=scope)


def test_v7_failure_preserves_consumed_lock_and_terminal_failure(tmp_path: Path, monkeypatch) -> None:
    def fail(**kwargs):
        raise RuntimeError("synthetic fail-closed preflight error")

    monkeypatch.setattr(preflight_v7, "build", fail)
    scope = tmp_path / "row30-v7-failure"

    with pytest.raises(RuntimeError, match="synthetic"):
        preflight_v7.write_once(scope_dir=scope)

    assert (scope / "one-shot-lock.json").is_file()
    failure = json.loads((scope / "terminal-failure.json").read_text(encoding="utf-8"))
    assert failure["status"] == "preflight_failed_after_one_shot_consumed"
    assert failure["worker_launch_authorized"] is False
