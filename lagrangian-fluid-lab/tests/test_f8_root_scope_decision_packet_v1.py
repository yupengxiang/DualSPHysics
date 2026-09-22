from __future__ import annotations

import hashlib
import json
from pathlib import Path

from scripts.f8_root_scope_decision_packet_v1 import OUTPUT, build_packet


ROOT = Path(__file__).resolve().parents[1]


def test_packet_requires_explicit_scope_choice_and_grants_no_execution() -> None:
    packet = build_packet()
    assert packet["schema"] == "core.cfd.f8.root_scope_decision_packet.v1"
    assert packet["status"] == "awaiting_user_root_scope_ruling"
    assert packet["qualification_credit"] == 0
    assert packet["no_implicit_selection"] is True
    assert set(packet["decision_options"]) == {"mechanism_family_gate", "free_surface_gate"}
    controls = packet["execution_controls"]
    assert all(value is False for value in controls.values() if isinstance(value, bool))
    assert all(value == 0 for key, value in controls.items() if key.endswith("_mutation"))


def test_committed_packet_binds_current_inputs() -> None:
    assert OUTPUT.is_file()
    packet = json.loads(OUTPUT.read_text(encoding="utf-8"))
    assert packet["status"] == "awaiting_user_root_scope_ruling"
    assert len(packet["bindings"]) == 5
    for row in packet["bindings"]:
        path = (ROOT / row["path"]).resolve()
        assert path.is_file(), row["path"]
        assert path.stat().st_size == row["bytes"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
