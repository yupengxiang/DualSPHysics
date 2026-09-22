from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f8_r002_continuation_decision_packet_v1 as packet_module


ROOT = Path(__file__).resolve().parents[1]


def test_r002_packet_preserves_r001_closure_and_grants_no_execution() -> None:
    packet = json.loads(packet_module.OUTPUT.read_text(encoding="utf-8"))
    assert packet["status"] == "awaiting_user_r002_continuation_ruling"
    assert packet["closed_scope"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R001"
    assert packet["proposed_new_scope"] == "F8_OSCILLATORY_PRESSURE_CHANNEL_WOMERSLEY_R002"
    assert packet["r001_retained_failure"]["same_input_retry_forbidden"] is True
    assert packet["r001_retained_failure"]["fixed_boundary_particle_count"] == 0
    assert packet["qualification_credit"] == 0
    assert packet["no_implicit_selection"] is True
    assert all(value is False for key, value in packet["execution_controls"].items() if key.endswith(("written", "invoked", "started")))
    assert all(packet["execution_controls"][key] == 0 for key in ("queue_mutation", "registry_mutation", "ledger_mutation", "denominator_mutation"))
    for item in packet["evidence"]:
        path = Path(item["path"])
        if not path.is_absolute():
            path = ROOT / path
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]


def test_r002_packet_is_immutable() -> None:
    with pytest.raises(FileExistsError, match="immutable F8 r002 decision packet"):
        packet_module.write_packet()
