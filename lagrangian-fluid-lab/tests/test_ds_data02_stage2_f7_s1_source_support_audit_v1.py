from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_source_support_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f7_s1_source_support_audit_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

MANIFEST = ROOT / (
    "campaigns/ds-data-02/stage2/requests/"
    "f7-s1-source-support-audit-v1-root-forward-137-001/"
    "f7-s1-source-support-audit-v1-manifest.json"
)
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/requests/"
    "f7-s1-source-support-audit-v1-root-forward-137-001/"
    "f7-s1-source-support-audit-v1-request.json"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest_with_json_mutation(tmp_path: Path, key: str, mutate) -> Path:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entry = next(item for item in manifest["source_refs"] if item["key"] == key)
    original = Path(entry["path"])
    value = json.loads(original.read_text(encoding="utf-8"))
    mutate(value)
    replacement = tmp_path / f"{key}.json"
    replacement.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    entry["path"] = str(replacement)
    entry["sha256"] = _sha256(replacement)
    output = tmp_path / f"manifest-{key}.json"
    output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return output


def _f7_sentinel(value):
    if isinstance(value, dict):
        if value.get("sentinel_id") == "F7-S1":
            return value
        for child in value.values():
            found = _f7_sentinel(child)
            if found is not None:
                return found
    elif isinstance(value, list):
        for child in value:
            found = _f7_sentinel(child)
            if found is not None:
                return found
    return None


def test_actual_manifest_derives_source_only_f7_s1_scope() -> None:
    result = MODULE.derive(MANIFEST)
    assert result["status"] == "COMPLETED_F7_S1_SOURCE_SUPPORT_AUDIT_V1_JSON_AND_SMALL_SOURCE_ONLY"
    assert result["current_binding"]["current_index"] == 288
    assert result["source_recipe"]["source_control"]["control_equivalence"] == "UNKNOWN"
    assert result["initial_support_and_mass"]["source_initial"]["fluid_particle_count"] == 40700
    assert result["mass_semantics"]["owner_metadata_continuum_mass_kg"] == pytest.approx(320.1984)
    assert result["mass_semantics"]["discrete_source_sample_mass_kg"] == pytest.approx(325.60001628000003)
    assert result["task_eligibility"]["continuous_owner_equivalence"] == "UNKNOWN"
    assert result["task_eligibility"]["QI"] == "UNKNOWN"
    assert result["read_policy"]["h5_opened"] is False
    assert result["read_policy"]["bi4_opened"] is False
    assert result["read_policy"]["vtk_opened"] is False
    assert result["read_policy"]["solver_started"] is False


def test_request_binds_current_worker_and_forbids_payload_inputs() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    # The producer request intentionally retains its forensic-worktree path;
    # a root clone may use a different absolute path.  Bind by the declared
    # request role and require byte identity with this checked-in worker,
    # rather than assuming a portable absolute path.
    declared_script = str(Path(request["command"][1]).resolve())
    assert request["input_sha256"][declared_script] == _sha256(SCRIPT)
    assert request["source_binding"]["script_sha256"] == _sha256(SCRIPT)
    assert set(request["input_files"]) == set(request["input_sha256"])
    assert request["hdf5_read"] is False
    assert request["bi4_read"] is False
    assert request["partout_read"] is False
    assert request["vtk_read"] is False
    assert request["solver_launch"] is False
    assert request["gpu_launch"] is False
    assert all(Path(path).suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4", ".vtk"} for path in request["input_files"])


def test_current_physical_identity_mutation_is_rejected(tmp_path: Path) -> None:
    def mutate(current):
        row = next(row for row in current["cases"] if row.get("physical_case_id") == "F7_OBSTACLE_QUINTIC_TARGET_EXPLICIT_WET_BASE_V1")
        row["runtime_case_alias"] = "F7_WRONG_CASE_ALIAS"

    manifest = _manifest_with_json_mutation(tmp_path, "current336", mutate)
    with pytest.raises(MODULE.AuditError, match="F7 CURRENT alias"):
        MODULE.derive(manifest)


def test_source_status_case_mutation_is_rejected(tmp_path: Path) -> None:
    def mutate(status):
        sentinel = _f7_sentinel(status)
        assert sentinel is not None
        sentinel["physical_case_id"] = "F7_UNRELATED_CASE"

    manifest = _manifest_with_json_mutation(tmp_path, "source_status", mutate)
    with pytest.raises(MODULE.AuditError, match="F7-S1 physical case"):
        MODULE.derive(manifest)


def test_label_proof_qualification_or_status_mutation_is_rejected(tmp_path: Path) -> None:
    def mutate(proof):
        proof["status"] = "PASS_WITH_UNSUPPORTED_QUALIFICATION"

    manifest = _manifest_with_json_mutation(tmp_path, "f7_label_proof", mutate)
    with pytest.raises(MODULE.AuditError, match="F7 label proof status"):
        MODULE.derive(manifest)
