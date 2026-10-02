from __future__ import annotations

import json
from pathlib import Path


FAMILY = Path(__file__).resolve().parents[1]
HANDOFF = FAMILY / "handoff_20261003/rv4_floorsafe_postprocess_v1"
DATA_REPORT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_RV4EQ_FLOORSAFE_NATIVE_PARTVTKOUT_20261003_V1/"
    "rv4-floorsafe-native-preflight-001/"
    "rv4-floorsafe-native-partvtkout-diagnostic.json"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_floor_safe_handoff_binds_two_actual_native_audits_without_qn():
    manifest = load(HANDOFF / "rv4_floorsafe_postprocess_handoff_manifest_v1.json")
    assert manifest["schema"] == "ds-data-02.f2.rv4eq-floorsafe-postprocess-handoff.v1"
    assert manifest["q_n_status"] == "not_assessed"
    assert manifest["launch_policy"] == {
        "solver": False,
        "native_partvtkout": False,
        "conversion": False,
        "labels": False,
        "root_owns_dispatch": True,
    }
    assert [row["background"] for row in manifest["cases"]] == ["CENTER", "OFFSET"]
    assert all(row["native_exclusion_fate"] == "unknown" for row in manifest["cases"])
    assert all(row["status"] == "conversion_deferred_labels_disabled_qn_pending" for row in manifest["cases"])


def test_native_report_matches_full_runparts_unknown_accounting():
    report = load(DATA_REPORT)
    assert report["status"] == "diagnostic_complete_pending_scientific_review"
    expected = {
        "CENTER": (2185, 2185, 2184, 1),
        "OFFSET": (2158, 2158, 2158, 0),
    }
    for case in report["cases"]:
        background = case["background"]
        row_count, np_out, np_out_pos, np_out_rho = expected[background]
        timeline = case["native_timeline"]
        exclusions = case["partvtkout_exclusions"]
        assert timeline["rows"] == 401
        assert timeline["full_window_completed"] is True
        assert timeline["NpOut_sum"] == np_out
        assert exclusions["row_count"] == row_count
        assert exclusions["all_rows_are_native_numerical_unknown"] is True
        assert exclusions["row_count_equals_runparts_NpOutPos_sum"] is (np_out_pos == row_count)
        assert timeline["NpOutRho_sum"] == np_out_rho
        assert all(record["physical_fate"] == "unknown" for record in exclusions["records"])
        assert all(record["motive_class"] == "native_solver_excluded_numerical_unknown" for record in exclusions["records"])
        assert all(record["typed_identity"]["type"] == 3 for record in exclusions["records"])


def test_owner_and_requests_keep_pose_and_h5_deferred():
    for background in ("CENTER", "OFFSET"):
        prefix = f"F2_RV4EQ_DP005_{background}_V1_REDUCED_DT_SAVE010_FLOORSAFE001"
        owner = load(HANDOFF / "owner_metadata" / f"{prefix}.owner.v1-deferred.json")
        conversion = load(HANDOFF / "conversion_requests" / f"{prefix}_conversion_request_v1.json")
        labels = load(HANDOFF / "labels_requests" / f"{prefix}_labels_request_v1_deferred.json")

        assert owner["status"] == "deferred_until_terminal_converter"
        assert owner["q_n_status"] == "not_assessed"
        assert owner["physical_binding"]["same_bi4_bytes"] is True
        assert owner["physical_binding"]["same_motion_bytes"] is True
        assert owner["native_exclusion_evidence"]["all_fate_unknown"] is True
        assert owner["native_exclusion_evidence"]["do_not_reuse_baseline_exclusion_ids_or_motives"] is True
        assert owner["typed_lifecycle_contract"]["moving_pose_required"] is True
        assert owner["fullstate_terminal_binding"]["status"] == "deferred_until_root_conversion_terminal"
        assert owner["fullstate_terminal_binding"]["trajectory_h5"]["sha256"] is None

        assert conversion["runnable"] is True
        assert conversion["launch_allowed"] is False
        assert conversion["root_only"] is True
        assert conversion["cpu_threads"] == 4
        assert conversion["estimated_storage_bytes"] > 50 * 1024**3
        command = " ".join(conversion["command"])
        assert "PartVTK_linux64" in command
        assert "PartVTKOut_linux64" not in command
        assert conversion["source_bindings"]["no_baseline_exclusion_reuse"] is True

        assert labels["status"] == "disabled_until_terminal_fullstate_h5"
        assert labels["runnable"] is False
        assert labels["launch_allowed"] is False
        assert labels["deferred_input_bindings"]["trajectory_h5"]["sha256"] is None
        assert labels["deferred_input_bindings"]["conversion_receipt"]["sha256"] is None
