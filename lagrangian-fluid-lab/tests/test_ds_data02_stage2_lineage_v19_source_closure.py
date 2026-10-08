from __future__ import annotations

import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_lineage_v19_source_closure as v19  # noqa: E402


CURRENT = ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"
PLAN_ROOT = ROOT / "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans"


def _physical_owner(*, owner_hash: str, case_id: str = "case-a", geometry_size: float = 1.0) -> dict:
    return {
        "case_id": case_id,
        "physical_case_id": case_id,
        "physical_condition_sha256": owner_hash,
        "physical_binding": {
            "family_id": "F2",
            "physical_case_id": case_id,
            "mechanism_id": "offset_spill",
            "geometry": {"receiver": {"low_m": [0.0, 0.0, 0.0], "size_m": [geometry_size, 1.0, 1.0]}},
            "initial_state": {"source_regions": {"fluid": {"low_m": [0.0, 0.0, 0.0], "size_m": [0.2, 0.2, 0.2]}}},
            "controls": {"motion_file_sha256": "opaque-control-hash", "rotation_amplitude_deg": -105.0},
            "parameters": {"rotation_duration_s": 0.9, "dp_m": 0.01},
            "event_window": {"time_end_s": 4.0},
        },
        "resolution": {"dp_m": 0.01},
        "solver_parameters": {"TimeMax": 4.0},
    }


def test_nested_solver_output_is_explicit_and_neighbour_is_not_used(tmp_path: Path) -> None:
    root = tmp_path / "attempt"
    nested = root / "solver_output"
    nested.mkdir(parents=True)
    (nested / "Run.out").write_text("nested\n")
    neighbour = tmp_path / "other-latest" / "solver_output"
    neighbour.mkdir(parents=True)
    (neighbour / "Run.out").write_text("neighbour\n")
    receipt = {"output_root": str(root), "command": ["solver", "case", str(nested)]}
    resolved = v19.resolve_run_out(receipt)
    assert resolved["status"] == "EXACT_EXPLICIT_RUN_OUT"
    assert Path(resolved["run_out_path"]) == nested / "Run.out"
    assert str(neighbour) not in json.dumps(resolved)


def test_two_explicit_run_out_candidates_are_ambiguous() -> None:
    # A receipt cannot select one of two explicit locations merely by order.
    # Use the public resolver with a real temporary tree so this exercises
    # the same stat/path branch as a nested native solver receipt.
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory) / "attempt"
        first = root / "solver_output"
        second = root / "alternate_solver_output"
        first.mkdir(parents=True)
        second.mkdir(parents=True)
        (root / "Run.out").write_text("root\n")
        (first / "Run.out").write_text("first\n")
        (second / "Run.out").write_text("second\n")
        result = v19.resolve_run_out({"output_root": str(root), "command": ["solver", str(first), str(second)]})
        assert result["status"] == "AMBIGUOUS_EXPLICIT_RUN_OUT"


def test_completed_status_without_finish_evidence_stays_launch_only() -> None:
    result = v19._receipt_finish_status({"status": "completed", "returncode": 0, "command": ["GenCase"]})
    assert result["complete"] is False
    assert result["status"] == "LAUNCH_ONLY_OR_INCOMPLETE_FINISH"


def test_opaque_owner_hash_and_case_id_do_not_split_same_semantic_payload() -> None:
    left = v19.effective_physical_key("F2", _physical_owner(owner_hash="aaa", case_id="case-a"))
    right = v19.effective_physical_key("F2", _physical_owner(owner_hash="bbb", case_id="case-b"))
    changed = v19.effective_physical_key("F2", _physical_owner(owner_hash="ccc", case_id="case-c", geometry_size=2.0))
    assert left["key"] == right["key"]
    assert left["key"] != changed["key"]
    assert left["split_safe"] is False


def test_producer_only_binding_and_selection_policy_are_conservative(tmp_path: Path) -> None:
    source = tmp_path / "source.h5"
    source.write_bytes(b"small fixture")
    binding = v19.classify_binding({
        "path": str(source),
        "producer_declared_sha256": "a" * 64,
        "recomputed_sha256": None,
    })
    assert binding["status"] == "PRODUCER_DECLARED_ONLY"
    assert v19.validate_selection_policy({"source_exact_current_row": True, "selector": "latest glob"})["valid"] is False
    assert v19.validate_selection_policy({"source_exact_current_row": True, "selector": "CURRENT row"})["valid"] is True


def test_actual_current_build_emits_seven_development_cards_without_raw_reads(tmp_path: Path) -> None:
    result = v19.build(CURRENT, tmp_path / "v19", plan_root=PLAN_ROOT)
    report = json.loads(Path(result["report"]).read_text())
    assert report["catalog_binding"]["catalog_case_count"] == 336
    assert report["read_scope"] == {
        "hdf5_opened": False,
        "bi4_opened": False,
        "large_source_rehashed": False,
        "metadata_json_max_bytes": v19.MAX_SMALL_JSON_BYTES,
        "small_source_json_and_stat_only": True,
    }
    assert report["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
    assert set(report["family_cards"]) == {f"F{i}" for i in range(1, 8)}
    for family in report["family_cards"]:
        card = json.loads((tmp_path / "v19" / f"{family}-family-card-v19-development.json").read_text())
        assert card["case_count"] == 48
        assert card["development_split"]["split_safe"] is False
        assert card["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
        assert card["raw_anchor"]["hidden"] is False
