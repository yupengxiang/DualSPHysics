from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_fresh_v16_proof_request_builder_v2.py"
SPEC = importlib.util.spec_from_file_location("f2_fresh_v16_request_builder_v2", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    original = tmp_path / "original"
    original.mkdir()
    relocated = tmp_path / "relocated"
    target = relocated / "target"
    output = relocated / "output"
    target.mkdir(parents=True)
    output.mkdir(parents=True)
    result = output / "fresh-v16-result.json"
    _write(result, {"schema": "ds02.stage2.f2-s1-replay-result.v16", "status": "PROSPECTIVE"})

    scan = tmp_path / "scientific-scan.json"
    _write(scan, {
        "schema": builder.SCAN_SCHEMA,
        "scan_status": "SCANNED",
        "full_saved_timeline_scanned": True,
        "frames": 2,
        "time_s": [0.0, 1.0],
        "type_ledgers": {"fluid": {
            "type_code": 3,
            "typed_initial_count": 2,
            "initial_active_count": 2,
            "typed_initial_mass_kg": 2.5,
            "initially_absent_count": 0,
            "cumulative_unique_missing": 1,
            "missing_initial_mass_kg": [0.0, 0.5],
            "active_nonfinite": {"position": 0, "velocity": 0, "density": 0, "mass": 0},
        }},
    })

    scan_sha = _sha(scan.read_text(encoding="utf-8"))
    source_files = {
        "current_catalog": _sha("current"),
        "generated_xml": _sha("xml"),
        "motion_dat": _sha("motion"),
        "initial_csv": _sha("initial"),
        "scientific_scan_sidecar": scan_sha,
    }
    v15 = {
        "schema": builder.V15_SCHEMA,
        "role": "DEVELOPMENT",
        "qualification": dict(builder.UNKNOWN),
        "model_invoked": False,
        "case_identity": {"family_id": "F2", "physical_case_id": "F2-S1"},
        "source_files": [
            {"role": role,
             "path": str(scan if role == "scientific_scan_sidecar" else tmp_path / f"{role}.json"),
             "sha256": digest}
            for role, digest in source_files.items()
        ],
        "trajectory_h5": {"producer_declared_sha256": _sha("trajectory")},
        "cohort": {
            "expected_initial_fluid_count": 2,
            "identity_key": "(Zone,Idp)",
            "initial_mk_codes": [1, 2],
            "source_csv_semantics": {"fluid_mk_counts": {"1": 1, "2": 1}},
            "source_identity_set_sha256": _sha("identity"),
            "source_definition": "initial.csv Type=3 and MK in {1,2}",
        },
        "initial_mass_denominator": {
            "denominator_kg": 2.5,
            "initial_missing_mass_kg": 0.0,
            "initially_absent_count": 0,
            "later_missing_unique_count": 1,
            "later_missing_mass_kg": 0.5,
        },
        "window": {"expected_times_s": [0.0, 1.0], "frame_stop": 1},
        "observer_profile": {"sha256": _sha("profile"), "observable_names": ["mass_weighted_com_m"]},
        "label_semantics": {"event_surface_scope": "manufactured"},
    }
    v15_path = tmp_path / "v15-request.json"
    _write(v15_path, v15)
    return v15_path, scan, result, target, output


def test_v2_derives_mass_count_mk_and_time_from_scan(tmp_path: Path) -> None:
    v15, scan, result, target, output = _fixture(tmp_path)
    contract = tmp_path / "derived-source-contract.json"
    request = tmp_path / "fresh-v16-request.json"
    value = builder.derive_and_build(
        v15_request=v15, scan_sidecar=scan, source_contract_output=contract,
        result=result, target_root=target, output_root=output, output=request,
        original_roots=[tmp_path / "original"],
        python_executable=Path("/bin/sh"),
    )
    assert value["status"] == "READY_FOR_PARENT_FRESH_V16_PROOF"
    assert value["qualification"] == builder.UNKNOWN
    built = json.loads(request.read_text(encoding="utf-8"))
    expected = built["expected"]
    assert expected["cohort"]["selected_count"] == 2
    assert expected["cohort"]["initial_mk_counts"] == {"1": 1, "2": 1}
    assert expected["initial_mass_denominator"]["denominator_kg"] == 2.5
    assert expected["initial_mass_denominator"]["later_missing_unique_count"] == 1
    assert expected["time"] == {
        "frame_count": 2, "first_s": 0.0, "last_s": 1.0, "tolerance_s": 0.0,
        "observer_profile_sha256": _sha("profile"),
        "tolerance_source": "exact saved times from frozen scientific-scan sidecar; no builder widening",
    }
    assert json.loads(contract.read_text(encoding="utf-8"))["producer_metadata"]["mass_derivation"]["payload_read"] is False


def test_v2_rejects_scan_mass_that_does_not_match_frozen_v15(tmp_path: Path) -> None:
    v15, scan, result, target, output = _fixture(tmp_path)
    broken = json.loads(scan.read_text(encoding="utf-8"))
    broken["type_ledgers"]["fluid"]["typed_initial_mass_kg"] = 9.0
    _write(scan, broken)
    mutated = json.loads(v15.read_text(encoding="utf-8"))
    for item in mutated["source_files"]:
        if item["role"] == "scientific_scan_sidecar":
            item["sha256"] = _sha(scan.read_text(encoding="utf-8"))
    _write(v15, mutated)
    with pytest.raises(builder.V16DerivedRequestError, match="initial mass"):
        builder.derive_source_contract(
            v15_request=v15, scan_sidecar=scan,
            source_contract_output=tmp_path / "broken-contract.json",
            original_roots=[tmp_path / "original"],
        )
