from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f3_material_row30_root_decision_packet_v1 as packet_module


ROOT = Path(__file__).resolve().parents[1]


def test_packet_is_closed_to_new_row30_authorization_only() -> None:
    value = json.loads(packet_module.OUTPUT.read_text(encoding="utf-8"))
    assert value["status"] == "awaiting_user_root_decision_for_new_row30_attempt"
    assert value["candidate"]["configuration_id"] == "F3-material-30"
    assert value["candidate"]["seeds"] == 4096
    assert value["candidate"]["substeps"] == 4
    assert value["invariants"]["existing_s2_output_reuse_forbidden"] is True
    assert value["invariants"]["T2_macro"] is False
    assert value["no_implicit_selection"] is True
    assert all(value["execution_controls"][key] is False for key in ("material_worker_started", "solver_started", "gpu_started"))
    assert all(value["execution_controls"][key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "matrix_mutation"))
    for item in value["evidence"]:
        path = ROOT / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_packet_is_immutable() -> None:
    with pytest.raises(FileExistsError, match="immutable F3 row30 decision packet"):
        packet_module.write_packet()
