"""Unit tests for prospective F2 RV4 matched OFFSET terminal NVMe labels v1 and errata sidecar.

Tests strictly use synthetic small fixtures and schema validation (zero unmetered actual-data computation):
1. Module structure & no execute_all bypass.
2. Prospective config, template, and manifest invariants (geometry, physical hash, timing, mass, unknown loss).
3. Safe failure of resolve_labels_request_after_pose when pose outputs do not exist.
4. Successful resolution and validate_request pass using a synthetic small fixture.
5. Additive errata sidecar consistency with Root review 010.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "f2_rv4eq_matched_offset_terminal_nvme_labels_v1.py"
spec = importlib.util.spec_from_file_location("f2_matched_offset_labels_v1", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
labels_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labels_mod)

FAMILY_ROOT = labels_mod.FAMILY_ROOT
INTEGRATION_LAB = labels_mod.INTEGRATION_LAB
HANDOFF_ROOT = labels_mod.HANDOFF_ROOT
CONFIGS_DIR = labels_mod.CONFIGS_DIR
TEMPLATES_DIR = labels_mod.TEMPLATES_DIR
REQUESTS_DIR = labels_mod.REQUESTS_DIR
CASES = labels_mod.CASES
PHYSICAL_HASH = labels_mod.PHYSICAL_HASH

# Import shared runtime validator
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
from ds_data02_runtime_v2 import validate_request


def test_prospective_module_structure_and_no_execute_all():
    assert not hasattr(labels_mod, "execute_all"), "execute_all bypass must not exist"

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "execution-receipt.json" not in script_text or "dump_json" not in script_text.split("execution-receipt.json")[0][-50:], (
        "script must never write execution-receipt.json; execution receipts belong exclusively to the shared runner"
    )


def test_prospective_configs_and_templates_invariants():
    labels_mod.build_prospective_all()

    manifest_path = HANDOFF_ROOT / "prospective_offset_labels_manifest_v1.json"
    assert manifest_path.is_file()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.f2.prospective-offset-labels-manifest.v1"
    assert manifest["status"] == "prospective_preparation_complete"
    assert manifest["physical_condition_hash"] == PHYSICAL_HASH
    assert manifest["save_timing_budget_s"] == 0.0007336390799938275
    assert manifest["save_relaxation"] is False
    assert manifest["storage_estimate_bytes"] >= 512 * 1024 * 1024
    assert manifest["unknown_state_policy"] == "observed native invalid remain strictly unknown, not inferred spill"

    for name, info in CASES.items():
        short = info["short_name"]
        cfg_path = CONFIGS_DIR / f"{short}_labels_nvme_config_v1.json"
        tmpl_path = TEMPLATES_DIR / f"{short}_labels_prospective_template_v1.json"
        assert cfg_path.is_file(), f"missing config: {cfg_path}"
        assert tmpl_path.is_file(), f"missing template: {tmpl_path}"

        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["schema"] == "ds02.f2.prospective-offset-labels-config.v1"
        assert cfg["status"] == "prospective_pose_binding_deferred"
        assert cfg["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"

        # Geometry checks - OFFSET receiver low corner y=-0.16m
        geom = cfg["geometry"]
        assert geom["cup_low_m"] == [0.0, -0.15, 0.65]
        assert geom["cup_size_m"] == [0.425, 0.3, 0.45]
        assert geom["receiver_low_m"] == [0.45, -0.16, 0.0]
        assert geom["receiver_size_m"] == [1.1, 0.6, 0.45]
        assert geom["receiver_offset_y_m"] == 0.14
        assert geom["tray_low_m"] == [-1.2, -1.0, -0.2]
        assert geom["tray_size_m"] == [4.0, 2.0, 0.15]

        # Timing checks - 4.0s, 401 frames, no relaxation
        timing = cfg["timing"]
        assert timing["event_window_s"] == 4.0
        assert timing["frames"] == 401
        assert timing["dt_s"] == 0.010
        assert timing["save_allowance_s"] == 0.0007336390799938275
        assert timing["save_budget_relaxation_applied"] is False

        # Mass semantics - explicit native vs continuous decimal
        mass = cfg["mass_semantics"]
        assert mass["xml_continuous_mass_kg"] == 24.576
        assert mass["source_normalization_applied"] is False
        if name == "coarse":
            assert mass["xml_massfluid_decimal_kg"] == 0.001
            assert math.isclose(mass["native_float32_fluid_sum_kg"], 24.576001167297363, rel_tol=1e-9)
        elif name == "medium":
            assert mass["xml_massfluid_decimal_kg"] == 0.000512
            assert math.isclose(mass["native_float32_fluid_sum_kg"], 24.575999937951565, rel_tol=1e-9)

        # Unknown loss semantics
        unknown = cfg["unknown_loss_semantics"]
        assert unknown["observed_native_invalid_policy"] == "unknown; never inferred as physical spill without geometric segment test"
        assert unknown["physical_spill_inferred_from_invalid"] is False
        assert unknown["destination_precedence"][0] == "unknown_invalid"

        # Storage estimate
        assert cfg["resource_ledger"]["estimated_storage_bytes"] >= 512 * 1024 * 1024

        # Deferred pose bindings
        deferred = cfg["deferred_pose_bindings"]
        assert deferred["binding_status"] == "deferred_until_root_execution"
        assert deferred["pose_attempt_id"] == info["pose_attempt_id"]

        # Template checks
        tmpl = json.loads(tmpl_path.read_text(encoding="utf-8"))
        assert tmpl["schema"] == "ds02.f2.prospective-labels-request-template.v1"
        assert tmpl["case_id"] == info["case_id"]
        assert tmpl["attempt_id"] == info["labels_attempt_id"]
        assert tmpl["estimated_storage_bytes"] >= 512 * 1024 * 1024
        assert tmpl["status"] == "prospective_awaiting_root_pose_execution"
        assert len(tmpl["static_input_files"]) == len(tmpl["static_input_sha256"])


def test_resolve_fails_safely_when_pose_not_yet_executed():
    for name in ["coarse", "medium"]:
        with pytest.raises(labels_mod.PostprocessError, match="missing|deferred"):
            labels_mod.resolve_labels_request_after_pose(name)


def test_resolve_and_validation_with_synthetic_pose_fixture(tmp_path: Path):
    # Create small synthetic pose attempt fixture to test post-pose resolution without actual data
    fake_pose_dir = tmp_path / "mock_pose_attempt"
    fake_pose_dir.mkdir(parents=True, exist_ok=True)

    fake_pose_h5 = fake_pose_dir / "trajectory-with-actual-pose.h5"
    payload = b"synthetic-tiny-pose-h5-content" * 128
    fake_pose_h5.write_bytes(payload)
    pose_sha = hashlib.sha256(payload).hexdigest()

    fake_report = fake_pose_dir / "rigid-body-state.json"
    fake_report.write_text(json.dumps({
        "augmented_trajectory": {
            "path": str(fake_pose_h5),
            "sha256": pose_sha,
            "bytes": len(payload),
        }
    }), encoding="utf-8")

    fake_receipt = fake_pose_dir / "execution-receipt.json"
    fake_receipt.write_text(json.dumps({
        "schema": "ds02.runner-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "attempt_id": "matched-offset-coarse-nvme-pose-v1-001",
    }), encoding="utf-8")

    # Resolve labels request using the synthetic fixture
    resolved_cfg, resolved_req = labels_mod.resolve_labels_request_after_pose("coarse", pose_attempt_dir=fake_pose_dir)

    assert resolved_cfg["status"] == "ready_for_dispatch"
    assert resolved_cfg["pose_bindings"]["pose_h5"]["sha256"] == pose_sha

    assert resolved_req["schema"] == "ds02.runner-request.v2"
    assert resolved_req["case_id"] == CASES["coarse"]["case_id"]
    assert resolved_req["attempt_id"] == CASES["coarse"]["labels_attempt_id"]
    assert resolved_req["estimated_storage_bytes"] >= 512 * 1024 * 1024

    # Validate resolved request using shared runner validator
    verified_hashes = validate_request(resolved_req)
    assert len(verified_hashes) == len(resolved_req["input_files"])
    assert str(fake_pose_h5.resolve()) in verified_hashes


def test_errata_sidecar_consistency():
    errata_path = FAMILY_ROOT / "handoff_20261003/root_review_010_errata_v1/f2_rv4eq_commit_596d6fc0_errata_sidecar_v1.json"
    assert errata_path.is_file(), f"missing errata sidecar: {errata_path}"

    data = json.loads(errata_path.read_text(encoding="utf-8"))
    assert data["schema"] == "ds02.f2.commit-596d6fc0-errata.v1"
    assert data["reviewed_commit"] == "596d6fc0"

    root_rev = data["root_review"]
    assert root_rev["verdict"] == "accepted"
    assert math.isclose(root_rev["conservative_cpu_charge_core_hours"], 9.118222, rel_tol=1e-5)
    assert math.isclose(root_rev["conservative_cpu_charge_core_seconds"], 32825.6, rel_tol=1e-5)

    err1 = data["erratum_1_bitwise_preservation_precision"]
    assert "semantic" in err1["scientific_classification"]
    assert "np.array_equal" in err1["correction"]

    err2 = data["erratum_2_mass_defect_claim_retraction"]
    assert "retracted" in err2["correction"]
    assert "unknown" in err2["scientific_classification"]

    err3 = data["erratum_3_unmetered_test_data_invocation_policy"]
    assert err3["policy_enforced"] is True
