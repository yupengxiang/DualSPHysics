"""Unit tests for resolved F2 RV4 matched OFFSET terminal NVMe labels v2 and errata sidecar.

Tests strictly enforce campaign write isolation and schema validation (zero unmetered actual-data computation):
1. Module structure & no execute_all bypass.
2. Resolved v2 configs and runner requests invariants bound to Root actual completed poses.
3. Shared runner validate_request compliance on published requests.
4. Strict campaign write isolation when build_all is invoked with an explicit output_root fixture.
5. Additive errata sidecar consistency with Root review 011.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import sys
import pytest

SCRIPT_PATH = Path(__file__).resolve().parents[1] / "f2_rv4eq_matched_offset_terminal_nvme_labels_v2.py"
import importlib.util
spec = importlib.util.spec_from_file_location("f2_matched_offset_labels_v2", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
labels_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(labels_mod)

FAMILY_ROOT = labels_mod.FAMILY_ROOT
INTEGRATION_LAB = labels_mod.INTEGRATION_LAB
HANDOFF_ROOT = labels_mod.HANDOFF_ROOT
CONFIGS_DIR = labels_mod.CONFIGS_DIR
REQUESTS_DIR = labels_mod.REQUESTS_DIR
CASES = labels_mod.CASES
PHYSICAL_HASH = labels_mod.PHYSICAL_HASH

# Import shared runtime validator
sys.path.insert(0, str(INTEGRATION_LAB / "scripts"))
from ds_data02_runtime_v2 import validate_request


def test_v2_module_structure_and_no_execute_all():
    assert not hasattr(labels_mod, "execute_all"), "execute_all bypass must not exist"

    script_text = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "execution-receipt.json" not in script_text or "dump_json" not in script_text.split("execution-receipt.json")[0][-50:], (
        "script must never write execution-receipt.json; execution receipts belong exclusively to the shared runner"
    )


def test_resolved_configs_and_requests_invariants():
    manifest_path = HANDOFF_ROOT / "resolved_offset_labels_manifest_v2.json"
    assert manifest_path.is_file(), f"missing manifest: {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.f2.resolved-offset-labels-manifest.v2"
    assert manifest["status"] == "resolved_preparation_complete"
    assert manifest["physical_condition_hash"] == PHYSICAL_HASH
    assert manifest["save_timing_budget_s"] == 0.0007336390799938275
    assert manifest["save_relaxation"] is False
    assert manifest["storage_estimate_bytes"] >= 600 * 1024 * 1024
    assert manifest["unknown_state_policy"] == "observed native invalid remain strictly unknown, not inferred spill"

    expected_pose_hashes = {
        "coarse": "0ec74f531db62e4921f78e6fd1cb4faed2fb4d9a96838dfa1df30d6e819659a2",
        "medium": "a83a0a810a3c6f86f9fb8dee885f3dadc84406fdb34b3d97e6ca44f95463510a",
    }
    expected_pose_attempts = {
        "coarse": "root-offset-coarse-actual-native-pose-v1-011",
        "medium": "root-offset-medium-actual-native-pose-v1-011",
    }

    for name, info in CASES.items():
        short = info["short_name"]
        cfg_path = CONFIGS_DIR / f"{short}_labels_nvme_config_v2.json"
        req_path = REQUESTS_DIR / f"{short}_labels_nvme_request_v2.json"
        assert cfg_path.is_file(), f"missing config: {cfg_path}"
        assert req_path.is_file(), f"missing request: {req_path}"

        # 1. Config checks
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        assert cfg["schema"] == "ds02.f2.matched-offset-labels-config.v2"
        assert cfg["status"] == "ready_for_root_dispatch"
        assert cfg["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"

        # Geometry
        geom = cfg["geometry"]
        assert geom["cup_low_m"] == [0.0, -0.15, 0.65]
        assert geom["cup_size_m"] == [0.425, 0.3, 0.45]
        assert geom["receiver_low_m"] == [0.45, -0.16, 0.0]
        assert geom["receiver_size_m"] == [1.1, 0.6, 0.45]
        assert geom["receiver_offset_y_m"] == 0.14
        assert geom["tray_low_m"] == [-1.2, -1.0, -0.2]
        assert geom["tray_size_m"] == [4.0, 2.0, 0.15]

        # Timing
        timing = cfg["timing"]
        assert timing["event_window_s"] == 4.0
        assert timing["frames"] == 401
        assert timing["dt_s"] == 0.010
        assert timing["save_allowance_s"] == 0.0007336390799938275
        assert timing["save_budget_relaxation_applied"] is False

        # Mass semantics
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

        # Pose bindings bound to Root actual completed poses
        pose_b = cfg["pose_bindings"]
        assert pose_b["pose_attempt_id"] == expected_pose_attempts[name]
        assert pose_b["pose_h5"]["sha256"] == expected_pose_hashes[name]
        assert Path(pose_b["pose_h5"]["path"]).is_file()
        assert Path(pose_b["pose_report"]["path"]).is_file()
        assert Path(pose_b["pose_receipt"]["path"]).is_file()

        # 2. Request checks
        req = json.loads(req_path.read_text(encoding="utf-8"))
        assert req["schema"] == "ds02.runner-request.v2"
        assert req["family_id"] == "F2"
        assert req["case_id"] == info["case_id"]
        assert req["attempt_id"] == f"matched-offset-{name}-nvme-labels-v2-001"
        assert req["kind"] == "cpu"
        assert req["cpu_task_kind"] == "labels"
        assert req["cpu_threads"] == 2
        assert req["max_wall_seconds"] <= 3600
        assert req["estimated_storage_bytes"] >= 600 * 1024 * 1024
        assert req["conversion_launch_forbidden"] is True
        assert req["claim_boundary"]["q_n"] == "not_assessed"
        assert req["independent_case_count_increment"] == 0

        # Validate with shared runner
        verified_hashes = validate_request(req)
        assert len(verified_hashes) == len(req["input_files"])


def test_campaign_write_isolation_in_build_all(tmp_path: Path):
    fixture_root = tmp_path / "test_isolated_output"
    fixture_root.mkdir(parents=True, exist_ok=True)

    # Calling build_all with fixture_root must write ONLY inside fixture_root
    configs_out, requests_out = labels_mod.build_all(output_root=fixture_root)

    for name in ["coarse", "medium"]:
        cfg_p = configs_out[name]
        req_p = requests_out[name]
        assert cfg_p.is_file()
        assert req_p.is_file()
        assert str(fixture_root) in str(cfg_p)
        assert str(fixture_root) in str(req_p)

    assert (fixture_root / "resolved_offset_labels_manifest_v2.json").is_file()


def test_errata_sidecar_review_011():
    errata_path = FAMILY_ROOT / "handoff_20261003/root_review_011_errata_v1/f2_rv4eq_commit_599435c7_errata_sidecar_v1.json"
    assert errata_path.is_file(), f"missing errata sidecar: {errata_path}"

    data = json.loads(errata_path.read_text(encoding="utf-8"))
    assert data["schema"] == "ds02.f2.commit-599435c7-errata.v1"
    assert data["reviewed_commit"] == "599435c7"
    assert "contaminated_file" in data["issue_diagnosis"]
    assert "isolation_remedy" in data["issue_diagnosis"]

    poses = data["root_completed_offset_pose_evidence"]
    assert poses["coarse"]["pose_attempt_id"] == "root-offset-coarse-actual-native-pose-v1-011"
    assert poses["coarse"]["pose_h5_sha256"] == "0ec74f531db62e4921f78e6fd1cb4faed2fb4d9a96838dfa1df30d6e819659a2"
    assert poses["medium"]["pose_attempt_id"] == "root-offset-medium-actual-native-pose-v1-011"
    assert poses["medium"]["pose_h5_sha256"] == "a83a0a810a3c6f86f9fb8dee885f3dadc84406fdb34b3d97e6ca44f95463510a"

    bounds = data["scientific_invariants_and_boundaries"]
    assert bounds["physical_condition_hash"] == "327899e38bbad63951206d5b2fd3ef354c049a32f6671af1af7913a48b77c7ef"
    assert bounds["receiver_low_corner_m"] == [0.45, -0.16, 0.0]
    assert bounds["receiver_offset_y_m"] == 0.14
    assert bounds["storage_estimate_bytes"] >= 600 * 1024 * 1024
    assert bounds["q_n_grant"] is False
