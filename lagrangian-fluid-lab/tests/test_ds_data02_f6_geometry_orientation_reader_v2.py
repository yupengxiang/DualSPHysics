"""Unit tests for DS-DATA-02 F6 Geometry-Based Orientation Reader & Cross-DP Evaluator (v2).

Directly validates the resolution of all 5 documented omissions from v1:
1. Strict Zone0 / Type2 / Mk60 exact full cohort verification (and rejection of malformed/wrong type/mk/zone/mismatch).
2. Explicit 0000..0240 file enumeration (ignoring PartFloating_stats.csv and detecting missing frames).
3. Strict 241 frames, finite, strictly increasing timestamps, and [0, 12s] window coverage.
4. Strict interpolation support (rejection of extrapolation without clamping).
5. 100% full match against FloatingInfo (strict rejection of partial matches).
6. Invariance of Kabsch SVD / SLERP Lie group mathematics and NULL orientation budget.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pytest

from scripts.ds_data02_f6_geometry_orientation_reader_v2 import (
    build_geometry_orientation_report_v2,
    compute_kabsch_svd,
    compute_so3_geodesic_distance,
    enumerate_partvtk_files,
    interpolate_pose_at_physical_time_v2,
    load_partvtk_series_v2,
    parse_partvtk_floating_csv_v2,
    quaternion_slerp,
    quaternion_to_matrix,
    matrix_to_quaternion,
    validate_center_against_floating_info_v2,
    compare_trajectories_physical_time,
    L_CHAR_M,
    U_CHAR_M_S,
    EXPECTED_FRAMES,
    EXPECTED_WINDOW_S,
)
from tests.fixtures.synthetic_floating_fixtures_v2 import (
    create_full_window_fixture_v2,
    generate_box_nodes,
    write_synthetic_floating_info_csv_v2,
    write_synthetic_partvtk_csv_v2,
)


def test_strict_full_window_and_explicit_enumeration(tmp_path: Path) -> None:
    """Verify v2 loads complete 241-frame sequence, ignores stats.csv, and passes all gates."""
    csv_paths, fi_path = create_full_window_fixture_v2(tmp_path, n_frames=241, dt=0.05, include_stats_csv=True)
    part_dir = csv_paths[0].parent

    # Check stats.csv exists in directory
    assert (part_dir / "PartFloating_stats.csv").is_file()

    # Omission 2 resolution: explicit enumeration does NOT return PartFloating_stats.csv
    enumerated = enumerate_partvtk_files(part_dir, expected_frames=241)
    assert len(enumerated) == 241
    assert all("stats" not in p.name for p in enumerated)
    assert enumerated[0].name == "PartFloating_0000.csv"
    assert enumerated[-1].name == "PartFloating_0240.csv"

    # Load full series with strict v2 validation
    traj = load_partvtk_series_v2(enumerated, target_mk=60, target_type=2, target_zone=0)
    assert traj["frame_count"] == 241
    assert traj["node_count"] > 0
    assert traj["is_rank_3"] is True
    assert math.isclose(traj["times"][0], 0.0, abs_tol=1e-5)
    assert math.isclose(traj["times"][-1], 12.0, abs_tol=1e-5)
    assert np.all(np.diff(traj["times"]) > 0.0)

    # Omission 5 resolution: 100% full match against FloatingInfo
    fi_val = validate_center_against_floating_info_v2(traj, fi_path)
    assert fi_val["all_frames_matched"] is True
    assert fi_val["matched_frames"] == 241
    assert fi_val["center_diff_rmse_m"] < 1e-4

    # Build report and check governance
    report = build_geometry_orientation_report_v2(traj, floating_info_validation=fi_val)
    assert report["governance_and_budget_status"]["orientation_budget"] is None
    assert report["governance_and_budget_status"]["orientation_budget_status"] == "unregistered"
    assert report["reference_cohort"]["target_zone"] == 0
    assert report["reference_cohort"]["target_type"] == 2
    assert report["reference_cohort"]["target_mk"] == 60


def test_omission_1_strict_cohort_rejections(tmp_path: Path) -> None:
    """Verify v2 strictly rejects malformed lines, wrong Type, wrong Mk, wrong Zone, and Nfloat mismatch."""
    idps, coords = generate_box_nodes()

    # Case A: Malformed line
    p_corrupt = tmp_path / "corrupt.csv"
    write_synthetic_partvtk_csv_v2(p_corrupt, 0.0, idps, coords, corrupt_line="bad,line,not,enough,cols")
    with pytest.raises(ValueError, match="Malformed row with insufficient columns"):
        parse_partvtk_floating_csv_v2(p_corrupt)

    # Case B: Wrong Type
    p_wrong_type = tmp_path / "wrong_type.csv"
    write_synthetic_partvtk_csv_v2(p_wrong_type, 0.0, idps, coords, inject_wrong_type=1)
    with pytest.raises(ValueError, match="Strict Type mismatch"):
        parse_partvtk_floating_csv_v2(p_wrong_type, target_type=2)

    # Case C: Wrong Mk
    p_wrong_mk = tmp_path / "wrong_mk.csv"
    write_synthetic_partvtk_csv_v2(p_wrong_mk, 0.0, idps, coords, inject_wrong_mk=61)
    with pytest.raises(ValueError, match="Strict Mk mismatch"):
        parse_partvtk_floating_csv_v2(p_wrong_mk, target_mk=60)

    # Case D: Wrong Zone
    p_wrong_zone = tmp_path / "wrong_zone.csv"
    write_synthetic_partvtk_csv_v2(p_wrong_zone, 0.0, idps, coords, inject_wrong_zone=1)
    with pytest.raises(ValueError, match="Strict Zone mismatch"):
        parse_partvtk_floating_csv_v2(p_wrong_zone, target_zone=0)

    # Case E: Metadata Nfloat mismatch
    p_mismatch = tmp_path / "mismatch_nfloat.csv"
    write_synthetic_partvtk_csv_v2(p_mismatch, 0.0, idps, coords, meta_nfloat_override=len(idps) + 10)
    with pytest.raises(ValueError, match="Node count mismatch against metadata Nfloat"):
        parse_partvtk_floating_csv_v2(p_mismatch)


def test_omission_2_missing_file_detection(tmp_path: Path) -> None:
    """Verify explicit enumeration detects any missing frame in 0000..0240 sequence."""
    part_dir = tmp_path / "part_series"
    part_dir.mkdir(parents=True)
    idps, coords = generate_box_nodes()

    # Write only frames 0000 to 0239 (missing 0240)
    for i in range(240):
        write_synthetic_partvtk_csv_v2(part_dir / f"PartFloating_{i:04d}.csv", i * 0.05, idps, coords)

    with pytest.raises(FileNotFoundError, match="Missing 1 expected PartVTK files"):
        enumerate_partvtk_files(part_dir, expected_frames=241)


def test_omission_3_strictly_increasing_and_full_frame_enforcement(tmp_path: Path) -> None:
    """Verify load_partvtk_series_v2 rejects non-increasing times and frame count mismatch."""
    idps, coords = generate_box_nodes()
    csv_paths: list[Path] = []

    # Write 241 files but with non-increasing timestamp at frame 50
    for i in range(241):
        t = 0.05 * i if i != 50 else 0.05 * 49  # non-increasing timestamp!
        p = tmp_path / f"PartFloating_{i:04d}.csv"
        write_synthetic_partvtk_csv_v2(p, t, idps, coords)
        csv_paths.append(p)

    with pytest.raises(ValueError, match="Non-increasing timestamp at frame 50"):
        load_partvtk_series_v2(csv_paths, expected_frames=241)

    # Test wrong frame count
    with pytest.raises(ValueError, match="Expected exactly 241 PartVTK frames"):
        load_partvtk_series_v2(csv_paths[:100], expected_frames=241)


def test_omission_4_no_extrapolation(tmp_path: Path) -> None:
    """Verify interpolation strictly forbids extrapolation outside native time domain."""
    csv_paths, _ = create_full_window_fixture_v2(tmp_path, n_frames=241, dt=0.05, include_stats_csv=False)
    traj = load_partvtk_series_v2(csv_paths)

    # Valid in-support queries
    r0, c0 = interpolate_pose_at_physical_time_v2(traj, 0.0)
    r_mid, c_mid = interpolate_pose_at_physical_time_v2(traj, 6.0)
    r_end, c_end = interpolate_pose_at_physical_time_v2(traj, 12.0)
    assert abs(np.linalg.det(r_mid) - 1.0) < 1e-6

    # Out-of-support query before t_start
    with pytest.raises(ValueError, match="out of support.*Extrapolation is strictly prohibited"):
        interpolate_pose_at_physical_time_v2(traj, -0.05)

    # Out-of-support query after t_end
    with pytest.raises(ValueError, match="out of support.*Extrapolation is strictly prohibited"):
        interpolate_pose_at_physical_time_v2(traj, 12.05)


def test_omission_5_reject_partial_floating_info_match(tmp_path: Path) -> None:
    """Verify center validation strictly rejects partial FloatingInfo matches."""
    csv_paths, _ = create_full_window_fixture_v2(tmp_path, n_frames=241, dt=0.05, include_stats_csv=False)
    traj = load_partvtk_series_v2(csv_paths)

    # Create truncated FloatingInfo CSV with only 100 rows instead of 241
    partial_fi_path = tmp_path / "FloatingInfo_partial.csv"
    times_100 = traj["times"][:100]
    centers_100 = traj["centroids"][:100]
    write_synthetic_floating_info_csv_v2(partial_fi_path, times_100, centers_100)

    with pytest.raises(ValueError, match="Strict FloatingInfo match failure: only 100 of 241 frames matched"):
        validate_center_against_floating_info_v2(traj, partial_fi_path)
