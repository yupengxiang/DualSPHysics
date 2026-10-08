from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v1.py"
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f3-s2-root086-vtk-support-qa-v1-root-forward-090-001/"
    / "f3-s2-root086-vtk-support-qa-v1-request.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_root086_vtk_support_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_self_test_and_owner_relation_contract():
    loaded = module()
    assert loaded.self_test()["status"] == "PASS"
    points = np.asarray([
        [-0.45, -0.09, 0.0],
        [0.45, 0.09, 0.09],
        [0.4501, 0.0, 0.0],
    ], dtype=np.float64)
    relation = loaded.owner_relation(points, 0.006)
    assert relation["inside_owner_closed_count"] == 2
    assert relation["outside_owner_closed_count"] == 1


def test_vtk_parser_rejects_wrong_idp_type_and_accepts_global_ids(tmp_path: Path):
    loaded = module()
    payload = (
        b"# vtk DataFile Version 3.0\nsmall\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 2 float\n"
        + struct.pack(">ffffff", 0.0, 0.0, 0.0, 0.006, 0.0, 0.0)
        + b"\nPOINT_DATA 2\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n"
        + struct.pack(">II", 111708, 111709)
        + b"\n"
    )
    path = tmp_path / "fluid.vtk"
    path.write_bytes(payload)
    points, meta = loaded.read_fluid_vtk(path, 2, 111708, 2)
    assert points.shape == (2, 3)
    assert meta["idp_mapping"] == "GLOBAL_XML_PARTICLE_IDS"
    bad = tmp_path / "bad.vtk"
    bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
    with pytest.raises(ValueError, match="unsigned-int Idp"):
        loaded.read_fluid_vtk(bad, 2, 111708, 2)


def test_request_defers_only_vtk_payloads_and_keeps_science_unknown():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    assert request["cpu_task_kind"] == "audit"
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["hdf5_read"] is False
    assert request["vtk_read"] is True
    assert request["deferred_input_file_count"] == 2
    assert all(
        Path(item["path"]).suffix.lower() == ".vtk"
        and item["sha256"] == "PARENT_GUARD_COMPUTED"
        for item in request["deferred_input_stats"].values()
    )
    assert all(Path(item).suffix.lower() not in {".vtk", ".bi4", ".h5"} for item in request["input_files"])
    assert request["source_binding"]["continuous_owner"]["mass_kg"] == pytest.approx(14.58)
    assert request["source_binding"]["fine_selector_interpretation"].startswith("discrete selector")
    assert request["guard_policy"]["old_products_immutable"] is True
