from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_f3_s2_initial_comparability_audit_v1.py"
SPEC = importlib.util.spec_from_file_location("f3_s2_initial_comparability_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_decimal_report_constants_are_finite_but_bool_is_rejected() -> None:
    assert MODULE._finite("0.005", "dp") == pytest.approx(0.005)
    with pytest.raises(MODULE.AuditError):
        MODULE._finite(True, "dp")
    with pytest.raises(MODULE.AuditError):
        MODULE._finite("not-a-number", "dp")


def test_projection_keeps_continuous_owner_fields_resolution_invariant() -> None:
    report = {
        "physical_binding": {
            "control_family_id": "control",
            "controls": {"boundary": 2},
            "density_kg_m3": 1000,
            "geometry": {"fluid": {"low": [0, 0, 0], "size": [1, 1, 1]}},
            "geometry_family_id": "cell3",
            "gravity_m_s2": [0, 0, -9.81],
            "initial_state": {
                "continuum_mass_by_source_kg": {"fluid": 1.0},
                "initial_mass_by_source_kg": {"fluid": 1.0},
                "initial_mass_total_kg": 1.0,
                "mass_policy": "none",
                "source_labels": ["fluid"],
                "source_regions": {"fluid": "pool"},
                "velocities_m_per_s": {"fluid": [0, 0, 0]},
            },
            "mass_policy": "none",
            "mechanism_id": "mechanism",
            "open_inlet": False,
            "paired_background_id": None,
            "periodic_boundary": False,
            "parameters": {"amp": 0.5},
            "physical_case_id": "case",
        }
    }
    same = copy.deepcopy(MODULE._source_report_projection(report))
    assert same == MODULE._source_report_projection(report)
    report["physical_binding"]["parameters"]["amp"] = 0.6
    assert same != MODULE._source_report_projection(report)


def test_vtk_is_stat_only_and_mutation_is_rejected(tmp_path: Path) -> None:
    vtk = tmp_path / "initial_Fluid.vtk"
    vtk.write_bytes(b"synthetic VTK bytes")
    stat = vtk.stat()
    spec = [{"path": str(vtk), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": None}]
    result = MODULE._validate_vtk_stat_only(spec, "target")
    assert result[0]["content_opened"] is False
    vtk.write_bytes(b"changed VTK bytes")
    with pytest.raises(MODULE.AuditError):
        MODULE._validate_vtk_stat_only(spec, "target")


def test_content_binder_rejects_native_and_vtk_even_with_correct_digest(tmp_path: Path) -> None:
    for suffix in (".bi4", ".vtk"):
        path = tmp_path / ("input" + suffix)
        path.write_bytes(b"forbidden content")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        with pytest.raises(MODULE.AuditError):
            MODULE.bind_file({"path": str(path), "sha256": digest, "bytes": path.stat().st_size}, suffix)


def test_forward_request_separates_stat_only_vtk_from_digest_bound_inputs() -> None:
    request_path = ROOT / (
        "campaigns/ds-data-02/stage2/requests/f3-s2-initial-comparability-v1/"
        "f3-s2-initial-comparability-v1-root-forward-001.json"
    )
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["source_cost"]["vtk_bytes_read"] == 0
    assert request["read_policy"]["vtk_content_opened"] is False
    assert request["stat_only_inputs"]
    assert all(Path(item["path"]).suffix.lower() == ".vtk" for item in request["stat_only_inputs"])
    assert all(Path(path).suffix.lower() not in {".vtk", ".bi4", ".h5"} for path in request["input_files"])
    assert set(request["input_sha256"]) == {str(Path(path).resolve()) for path in request["input_files"]}
