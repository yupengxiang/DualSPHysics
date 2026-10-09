from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_namespace330_v4_actual_verify_v4.py"
SPEC = importlib.util.spec_from_file_location("namespace330_actual_verify_v4_test", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _proof(tmp_path: Path, row: dict) -> list[dict[str, str]]:
    path = tmp_path / "root-mass-verifier-wrapper.json"
    # This is the exact wrapper written by verify_actual_mass313_v1.py and
    # verify_actual_mass30_v1.py after they copy the real V5/V6 verifier's
    # `case_verifications` output into the ROOT proof.  The row itself is
    # obtained from the frozen verifier in the test below, not hand-shaped.
    path.write_text(json.dumps({
        "schema": "ds02.stage2.root-actual-verification.v1",
        "status": "VERIFIED_ACTUAL_V6_SELECTED_TYPED_MASS_CASE_TERMINALS_NO_PHYSICAL_Q",
        "case_verifications": [row],
    }, sort_keys=True) + "\n", encoding="utf-8")
    return [{
        "role": "mass_proof_root_v6_wrapper",
        "path": str(path),
        "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }]


def _run_frozen_v6_fixture(tmp_path: Path) -> dict:
    """Run the frozen worker + V6 verifier to obtain a genuine case row."""
    primary = Path(os.environ.get(
        "DS_STAGE2_PRIMARY_ROOT",
        "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics",
    ))
    test_path = primary / "lagrangian-fluid-lab/scripts/test_ds_data02_stage2_verify_native_typed_mass_impact_v6.py"
    if not test_path.is_file():
        pytest.skip("primary frozen V6 verifier test is not present in this worktree")
    sys.path.insert(0, str(test_path.parent))
    spec = importlib.util.spec_from_file_location("frozen_v6_shape_fixture", test_path)
    assert spec is not None and spec.loader is not None
    frozen_tests = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(frozen_tests)
    manifest, result, _typed = frozen_tests._prepare_v6_fixture(tmp_path)
    output = tmp_path / "frozen-v6-verification.json"
    frozen_tests.subject.verify(
        frozen_tests.argparse.Namespace(manifest=manifest, result=result, output=output)
    )
    return json.loads(output.read_text(encoding="utf-8"))["case_verifications"][0]


def test_real_frozen_v6_case_verifications_are_normalized_without_mass_invention(tmp_path: Path) -> None:
    row = _run_frozen_v6_fixture(tmp_path)
    assert set(row) >= {
        "physical_case_id", "status", "selected_native_id_count",
        "exact_selected_mass_rows", "missing_selected_mass_rows",
    }
    refs = _proof(tmp_path, row)
    result = MODULE.validate_mass_proof_inputs(refs, {row["physical_case_id"]})
    observation = result["observations"][row["physical_case_id"]]

    assert result["summary"]["actual_verifier_rows_normalized"] == 1
    assert observation["selected_native_id_count"] == row["selected_native_id_count"]
    assert observation["selected_initial_mass_sum_kg"] is None
    assert observation["case_total_initial_mass_kg"] is None
    assert observation["selected_initial_mass_status"] == (
        "UNKNOWN_AT_LEAST_ONE_SELECTED_ROW_MASS_MISSING"
    )
    assert observation["verifier_summaries"][0]["exact_selected_mass_rows"] == row["exact_selected_mass_rows"]
    assert observation["verifier_summaries"][0]["missing_selected_mass_rows"] == row["missing_selected_mass_rows"]


def test_actual_verifier_count_tamper_is_rejected(tmp_path: Path) -> None:
    row = _run_frozen_v6_fixture(tmp_path)
    row["missing_selected_mass_rows"] += 1
    refs = _proof(tmp_path, row)
    with pytest.raises(MODULE.Namespace330V4ActualVerificationError, match="counts do not balance"):
        MODULE.validate_mass_proof_inputs(refs, {row["physical_case_id"]})


def test_legacy_v3_mass_rows_remain_supported(tmp_path: Path) -> None:
    row = {
        "physical_case_id": "CASE_LEGACY",
        "status": "COMPLETED",
        "selected_typed_initial_mass": {
            "selected_typed_initial_mass_sum_kg": 1.25,
            "selected_typed_initial_mass_count": 2,
            "selected_typed_initial_mass_status": "COMPLETED",
        },
        "case_total_initial_mass_kg": 1.5,
        "expected_case_total_initial_mass_kg": 1.5,
        "mass_match": True,
    }
    path = tmp_path / "legacy.json"
    path.write_text(json.dumps({"schema": "mass", "status": "COMPLETED", "cases": [row]}) + "\n", encoding="utf-8")
    ref = [{"role": "mass_proof_legacy", "path": str(path), "file_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}]
    result = MODULE.validate_mass_proof_inputs(ref, {"CASE_LEGACY"})
    assert result["observations"]["CASE_LEGACY"]["case_total_initial_mass_kg"] == 1.5
    assert result["summary"]["actual_verifier_rows_normalized"] == 0
