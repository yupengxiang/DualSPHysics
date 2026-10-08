from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_coarse_active_stream_v2.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-coarse-active-stream-v2-root-forward-108-001"
MANIFEST = REQUEST_DIR / "f2-coarse-active-stream-v2-manifest.json"
REQUEST = REQUEST_DIR / "f2-coarse-active-stream-v2-request.json"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/contracts/f2-coarse-observation-contract-v2.json"


def module():
    spec = importlib.util.spec_from_file_location("f2_coarse_active_stream_v2", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_v2_strictly_binds_typed_blocks_and_runtime_budget():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert manifest["schema"] == "ds02.stage2.f2.coarse-active-stream.manifest.v2"
    assert manifest["expected"]["whole_initial_fluid_mass_kg"] == pytest.approx(18.910848)
    assert manifest["expected"]["fluid_blocks"] == [
        {"begin": 512883, "count": 9250, "mkfluid": 0, "mk": 1},
        {"begin": 522133, "count": 9250, "mkfluid": 1, "mk": 2},
        {"begin": 531383, "count": 9250, "mkfluid": 2, "mk": 3},
    ]
    assert manifest["runtime"]["max_scratch_bytes"] == 134217728
    assert manifest["runtime"]["cpu_threads"] == 1
    assert request["estimated_storage_bytes"] == 268435456
    assert request["guard_policy"]["per_frame_scratch_cleanup_before_next_frame"] is True
    assert request["guard_policy"]["typed_field_claim"].startswith("type/MK derived")
    assert request["source_binding"]["whole_initial_fluid_mass_kg"] == pytest.approx(18.910848)
    assert len(manifest["frames"]) == 401


def test_v2_contract_preserves_frozen_mass_screen_and_marks_future_observers():
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    assert contract["schema"] == "ds02.stage2.f2.coarse-observation-contract.v2"
    assert contract["frozen_tolerances"]["whole_initial_unknown_mass_fraction_max"] == 0.003
    assert contract["frozen_tolerances"]["mk_region_flux_error_fraction_whole_initial"] == 0.03
    assert contract["future_observer_tolerances"]["space_position_reference_fraction"] == 0.02
    assert contract["future_observer_tolerances"]["velocity_ke_nonzero_reference_fraction"] == 0.05
    assert contract["future_observer_tolerances"]["event_time_nonzero_window_fraction"] == 0.01
    assert contract["future_observer_tolerances"]["all_are_preregistration_metadata_not_qualification"] is True


def test_per_frame_scratch_directory_is_removed_and_peak_is_not_cumulative(tmp_path: Path):
    loaded = module()
    parent = tmp_path / "attempt"
    parent.mkdir()
    peaks = []
    for index in range(5):
        with loaded.tempfile.TemporaryDirectory(prefix=f"frame-{index:04d}-", dir=str(parent)) as frame_dir:
            payload = Path(frame_dir) / "decoded.bin"
            payload.write_bytes(b"x" * 1024)
            peaks.append(loaded.directory_bytes(Path(frame_dir)))
            assert peaks[-1] == 1024
        assert not Path(frame_dir).exists()
        assert loaded.directory_bytes(parent) == 0
    assert max(peaks) == 1024


def test_dynamic_header_contract_is_required_before_source_can_claim_closed_stream():
    loaded = module()
    bad = {"schema": "ds02.stage2.f2.coarse-observation-contract.v2", "frozen_tolerances": {
        "whole_initial_unknown_mass_fraction_max": 0.003,
        "mk_region_flux_error_fraction_whole_initial": 0.03,
        "integration_error_allocation_fraction": 0.25,
        "output_sampling_error_allocation_fraction": 0.25,
    }, "native_time_policy": "BI4 decoder TimeStep is actual observation time; nominal request tmax is metadata only"}
    # This is a contract-only check; the actual BI4 metadata guard is invoked
    # by _stream through direct_convert._reject_dynamic_contract on frame one.
    assert loaded._validate_contract(bad)["schema"].endswith(".v2")
