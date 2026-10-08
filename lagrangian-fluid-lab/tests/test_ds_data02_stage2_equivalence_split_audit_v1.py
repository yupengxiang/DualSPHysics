from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_equivalence_split_audit_v1.py"
spec = importlib.util.spec_from_file_location("equivalence_split_audit", SCRIPT)
assert spec and spec.loader
AUDIT = importlib.util.module_from_spec(spec)
spec.loader.exec_module(AUDIT)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _semantic(depth: float = 0.1, boundary: int = 1) -> dict:
    return {
        "controls": {"boundary": boundary},
        "density_kg_m3": 1000,
        "geometry": {"tank": {"low_m": [0, 0, 0], "size_m": [1, 1, 1]}},
        "gravity_m_s2": [0, 0, -9.81],
        "initial_state": {"mass_policy": "native_massfluid_no_rescaling", "velocities_m_per_s": {"fluid": [0, 0, 0]}},
        "lineage_group_id": "shared-semantic-group",
        "mass_policy": "native_massfluid_no_rescaling",
        "mechanism_id": "manufactured-mechanism",
        "parameters": {"depth_m": depth, "physical_top_open": True},
        "periodic_boundary": False,
        "schema": "ds-data-02.physical-binding.v1",
    }


def _current_row(family: str, physical: str, alias: str, trajectory: str, *, frames: int = 10,
                 end: float = 1.0) -> dict:
    return {
        "family_id": family,
        "physical_case_id": physical,
        "runtime_case_alias": alias,
        "frames": frames,
        "particles": 12,
        "actual_time_window_s": [0.0, end],
        "known_numeric_physical_parameters": {"dp_m": 0.01},
        "trajectory": {"path": f"/raw/{physical}/trajectory.h5", "producer_declared_sha256": trajectory, "recomputed_sha256": None, "bytes": 10},
    }


def _link(row: dict, semantic: dict | None, *, unknown: bool = False,
          recovery: str = "UNKNOWN_PENDING_EXPLICIT_RESTART_OR_RECOVERY_EVIDENCE",
          window_group: str | None = None, case_index: int = 0) -> dict:
    if unknown:
        group = {
            "key": f"{row['family_id']}:UNKNOWN_CONSERVATIVE_GROUP",
            "reason": "insufficient evidence",
            "split_safe": False,
            "status": "PROVISIONAL_UNKNOWN",
        }
    else:
        assert semantic is not None
        key = f"{row['family_id']}:physical:{AUDIT._digest(semantic)}"
        group = {
            "key": key,
            "reason": "semantic payload observed",
            "semantic_payload": semantic,
            "split_safe": False,
            "status": "SOURCE_SUPPORTED_DEVELOPMENT_GROUP",
        }
    variation = {
        "frame_count": row["frames"],
        "particle_count": row["particles"],
        "resolution": None,
        "owner_resolution": "fixture",
        "owner_solver_parameters_present": True,
        "recovery": recovery,
        "time_window_s": row["actual_time_window_s"],
    }
    if window_group is not None:
        variation["window_group_id"] = window_group
    return {
        "case_index": case_index,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "runtime_case_alias": row["runtime_case_alias"],
        "physical_group": group,
        "variation_dimensions": variation,
        "source_closure": {
            "closure_status": "CONTENT_PENDING_PARENT_GUARD",
            "roles": {"trajectory": {"expected_sha256": row["trajectory"]["producer_declared_sha256"], "status": "PRODUCER_DECLARED_ONLY"}},
        },
    }


def _fixture(tmp_path: Path) -> tuple[Path, Path, list[dict]]:
    rows = [
        _current_row("F1", "P_A", "alias-a", "a" * 64, frames=10, end=1.0),
        # Different physical IDs and aliases, but exactly the same semantic
        # source: they must remain one component.
        _current_row("F1", "P_B", "alias-b", "b" * 64, frames=20, end=2.0),
        _current_row("F1", "P_C", "alias-c", "c" * 64, frames=30, end=3.0),
        _current_row("F1", "P_D", "alias-d", "d" * 64, frames=10, end=1.0),
        # Same semantic payload as P_A but family boundary is conservative.
        _current_row("F2", "P_E", "alias-e", "e" * 64, frames=10, end=1.0),
        _current_row("F1", "P_U", "alias-u", "f" * 64, frames=10, end=1.0),
        _current_row("F1", "P_U2", "alias-u2", "1" * 64, frames=11, end=1.1),
    ]
    current = {"schema": AUDIT.CURRENT_SCHEMA, "cases": rows}
    current_path = tmp_path / "CURRENT336.json"
    current_path.write_text(json.dumps(current, sort_keys=True), encoding="utf-8")
    links = [
        _link(rows[0], _semantic(), case_index=0),
        _link(rows[1], _semantic(), case_index=1),
        # Multiple saved windows/recovery variants are deliberately kept in
        # the same component; no continuity proof is supplied.
        _link(rows[2], _semantic(), recovery="UNKNOWN_PENDING_EXPLICIT_RESTART_OR_RECOVERY_EVIDENCE", case_index=2),
        _link(rows[3], _semantic(depth=0.2), case_index=3),
        _link(rows[4], _semantic(), case_index=4),
        _link(rows[5], None, unknown=True, case_index=5),
        _link(rows[6], None, unknown=True, case_index=6),
    ]
    lineage = {
        "schema": AUDIT.LINEAGE_SCHEMA,
        "status": "DEVELOPMENT_ONLY; SEMANTIC_CLOSURE_PARTIAL",
        "sha256": "producer-canonical",
        "catalog_binding": {
            "catalog_case_count": len(rows),
            "current_json_sha256": AUDIT.sha256_file(current_path),
        },
        "case_source_links": links,
    }
    lineage_path = tmp_path / "lineage-v19.json"
    lineage_path.write_text(json.dumps(lineage, sort_keys=True), encoding="utf-8")
    return current_path, lineage_path, rows


def test_components_hold_aliases_dp_windows_and_unknowns_without_promotion(tmp_path: Path) -> None:
    current, lineage, rows = _fixture(tmp_path)
    result = AUDIT.audit(current, lineage)
    assert result["universe"]["current_case_count"] == 7
    assert result["universe"]["hidden_test_claim"] is False
    by_id = {row["physical_case_id"]: row for row in result["cases"]}
    assert by_id["P_A"]["component_id"] == by_id["P_B"]["component_id"] == by_id["P_C"]["component_id"]
    assert by_id["P_A"]["development_role"] == by_id["P_B"]["development_role"] == by_id["P_C"]["development_role"]
    assert by_id["P_A"]["component_id"] != by_id["P_E"]["component_id"]
    assert by_id["P_U"]["component_id"] == by_id["P_U2"]["component_id"]
    assert by_id["P_U"]["unresolved_exclusion"] is True
    assert "physical_group_provisional_unknown" in by_id["P_U"]["unresolved_reasons"]
    assert all(row["known_split_safe_value"] is not True for row in result["cases"])
    assert result["diagnostics"]["known_false_split_safe_preserved"] is True
    assert result["diagnostics"]["component_not_split"] is True
    assert result["diagnostics"]["producer_declared_only_trajectory_case_count"] == 7
    assert result["diagnostics"]["promotion_eligible_case_counts"] == {
        "development_train": 0, "development_validation": 0, "development_test": 0,
    }


def test_metadata_root_proof_is_not_treated_as_h5_guard(tmp_path: Path) -> None:
    current, lineage, _ = _fixture(tmp_path)
    root = {
        "schema": AUDIT.ROOT_PROOF_SCHEMA,
        "status": "PASS_EXACT_CURRENT_MEMBERSHIP_AND_SEVEN_PROVISIONAL_CARD_BINDINGS",
        "current_sha256": AUDIT.sha256_file(current),
        "cases": 7,
        "root_h5_bi4_read": False,
    }
    root_path = tmp_path / "root-proof.json"
    root_path.write_text(json.dumps(root), encoding="utf-8")
    result = AUDIT.audit(current, lineage, root_path)
    assert result["inputs"]["root_metadata_verification"]["scope"].startswith("metadata_membership_only")
    assert result["diagnostics"]["metadata_only_trajectory_case_count"] == 7
    assert result["diagnostics"]["guard_verified_trajectory_case_count"] == 0


def test_changed_physical_group_digest_is_rejected(tmp_path: Path) -> None:
    current, lineage, _ = _fixture(tmp_path)
    payload = json.loads(lineage.read_text(encoding="utf-8"))
    payload["case_source_links"][0]["physical_group"]["key"] = "F1:physical:" + "0" * 64
    lineage.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(AUDIT.SplitAuditError, match="physical_key_payload_mismatch"):
        AUDIT.audit(current, lineage)


def test_request_is_metadata_only_and_fails_closed_when_guard_runtime_missing(tmp_path: Path) -> None:
    current, lineage, _ = _fixture(tmp_path)
    worker_root = tmp_path / "root"
    script_dir = worker_root / "lagrangian-fluid-lab" / "scripts"
    script_dir.mkdir(parents=True)
    worker = script_dir / SCRIPT.name
    worker.write_text("# fixture worker\n", encoding="utf-8")
    request_path = tmp_path / "request.json"
    request = AUDIT.make_request(current, lineage, None, request_path, worker_root,
                                 runtime_paths=[script_dir / "runtime.py"])
    assert request["launch_allowed"] is False
    assert request["source_cost"]["original_trajectory_h5_bytes_read"] == 0
    assert request["source_cost"]["part_bi4_bytes_read"] == 0
    assert request["split_policy"]["hidden_test_claim"] is False
    assert any("runtime.py" in value for value in request["missing_guard_sources"])
