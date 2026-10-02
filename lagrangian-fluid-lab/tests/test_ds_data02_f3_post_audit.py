from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_f3_post_audit.py"
SPEC = importlib.util.spec_from_file_location("ds_data02_f3_post_audit", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_parent_timeout_rebind_requires_unchanged_input_hashes(tmp_path: Path) -> None:
    hdf5 = tmp_path / "trajectory.h5"
    hdf5.write_bytes(b"immutable")
    parent = {
        "status": "failed",
        "returncode": -15,
        "termination_reason": "reserved_wall_time_exceeded",
        "output_root": str(tmp_path),
        "command": [str(hdf5)],
        "request": {"qualification_claim": "none", "q_n_status": "not_assessed"},
        "input_hashes_at_launch": {"source": "abc"},
        "input_hashes_after_run": {"source": "abc"},
    }
    result = MODULE.verify_parent_timeout(parent, hdf5)
    assert result["all_checks_pass"] is True

    parent["input_hashes_after_run"] = {"source": "changed"}
    result = MODULE.verify_parent_timeout(parent, hdf5)
    assert result["all_checks_pass"] is False
    assert result["checks"]["input_hashes_unchanged"] is False


def test_parent_timeout_accepts_runner_level_unqualified_receipt(tmp_path: Path) -> None:
    hdf5 = tmp_path / "trajectory.h5"
    hdf5.write_bytes(b"immutable")
    parent = {
        "status": "failed",
        "returncode": -15,
        "termination_reason": "reserved_wall_time_exceeded",
        "output_root": str(tmp_path),
        "command": [str(hdf5)],
        "request": {"qualification_claim": "none; request only, Q-N remains not assessed"},
        "numerical_reference_status": "not_assessed",
        "production_product_acceptance": "not_assessed",
        "input_hashes_at_launch": {"source": "abc"},
        "input_hashes_after_run": {"source": "abc"},
    }
    result = MODULE.verify_parent_timeout(parent, hdf5)
    assert result["all_checks_pass"] is True


def test_direct_report_rebind_rejects_wrong_hdf5_digest(tmp_path: Path) -> None:
    hdf5 = tmp_path / "trajectory.h5"
    hdf5.write_bytes(b"native")
    report = {
        "conversion_status": "completed",
        "output_hdf5": str(hdf5),
        "output_sha256": "wrong",
        "frames": MODULE.EXPECTED_FRAMES,
        "particles": MODULE.EXPECTED_PARTICLES,
        "partvtk_validation": {"all_passed": True, "frames": [{}, {}, {}]},
        "source_provenance": {"raw_tree": {"unchanged": True, "before_tree_sha256": "x", "after_tree_sha256": "x"}},
        "lifecycle": {"transient_missing_frame_count": 0},
        "typed_identity": {},
        "q_n_status": "not_assessed",
    }
    result = MODULE.verify_direct_report(report, hdf5, MODULE.sha256_file(hdf5))
    assert result["all_checks_pass"] is False
    assert result["checks"]["output_sha256_matches"] is False


def test_direct_report_rebind_supports_half_dt_frame_count(tmp_path: Path) -> None:
    hdf5 = tmp_path / "trajectory.h5"
    hdf5.write_bytes(b"native")
    report = {
        "conversion_status": "completed",
        "output_hdf5": str(hdf5),
        "output_sha256": MODULE.sha256_file(hdf5),
        "frames": 4001,
        "particles": 108000,
        "partvtk_validation": {"all_passed": True, "frames": [{}, {}, {}]},
        "source_provenance": {"raw_tree": {"unchanged": True, "before_tree_sha256": "x", "after_tree_sha256": "x"}},
        "lifecycle": {"transient_missing_frame_count": 0},
        "typed_identity": {},
        "q_n_status": "not_assessed",
    }
    result = MODULE.verify_direct_report(report, hdf5, MODULE.sha256_file(hdf5), expected_frames=4001)
    assert result["all_checks_pass"] is True
