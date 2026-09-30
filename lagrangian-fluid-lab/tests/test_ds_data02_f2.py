from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import ds_data02_f2 as f2


def test_w06_history_is_classified_without_formal_reuse() -> None:
    audit = f2._read_w06_history()
    assert audit["counts"] == {
        "total": 12,
        "zero_missing": 5,
        "missing_classified": 7,
        "formal_reuse": 0,
    }
    assert all(row["formal_reuse"] is False for row in audit["records"])


def test_registry_is_48_cases_with_pair_preserving_split() -> None:
    rows = f2._candidate_records()
    assert len(rows) == 48
    assert len({row["physical_case_id"] for row in rows}) == 48
    assert Counter(row["mechanism_id"] for row in rows) == Counter({"center_catch": 24, "offset_spill": 24})
    assert Counter(row["split"] for row in rows) == Counter(
        {"train": 24, "validation": 6, "id_test": 6, "parameter_ood": 6, "geometry_control_ood": 6}
    )
    for pair in {row["paired_background_id"] for row in rows}:
        assert len({row["split"] for row in rows if row["paired_background_id"] == pair}) == 1


def test_dynamic_offset_definition_has_real_3d_geometry_and_motion() -> None:
    case = f2.make_case(
        "offset_spill",
        "medium",
        case_id="F2_TEST_OFFSET",
        physical_case_id="F2_TEST_OFFSET",
        values={"fill_ratio": 0.8, "rotation_duration_s": 0.65, "receiver_y_m": 0.14},
    )
    with tempfile.TemporaryDirectory() as directory:
        written = f2.write_case(case, directory)
        report = f2.preflight_definition(written["definition_path"], written["metadata_path"])
    assert report["status"] == "pass", report
    assert report["solver_dimension_declared"] == 3
    assert report["motion"]["final_angle_deg"] == f2.ROTATION_ANGLE_DEG


def test_committed_reference_matrix_and_gencase_evidence_are_fail_closed() -> None:
    family = ROOT / "campaigns/ds-data-02/families/F2"
    matrix = json.loads((family / "definitions/reference_matrix.json").read_text())
    assert matrix["all_preflight"] is True
    assert len(matrix["matrix"]) == 6
    evidence = json.loads((family / "gencase_preflight_evidence.json").read_text())
    assert evidence["checks"]["both_completed"] is True
    assert evidence["checks"]["both_3d"] is True
    assert evidence["checks"]["both_nonzero_fluid"] is True
    for name in ("qualification_center_catch_request.json", "qualification_offset_spill_request.json"):
        request = json.loads((family / name).read_text())
        assert request["kind"] == "qualification"
        assert request["solver_dimension_required"] == 3
        assert request["qualification_launch_authority"] == "shared_ds_data_02_runner_only_primary_process"
