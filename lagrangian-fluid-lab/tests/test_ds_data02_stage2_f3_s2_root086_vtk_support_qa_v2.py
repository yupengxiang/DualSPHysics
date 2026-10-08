from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_root086_vtk_support_qa_v2.py"
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f3-s2-root086-vtk-support-qa-v2-root-forward-093-001/"
    / "f3-s2-root086-vtk-support-qa-v2-request.json"
)


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_root086_vtk_support_v2", SCRIPT)
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
    assert request["source_binding"]["worker_pre_record_before_decode"] is True
    assert request["source_binding"]["worker_post_record_after_decode"] is True
    assert request["estimated_native_read_bytes"] == 25_752_343
    assert request["estimated_native_read_bytes"] > sum(item["bytes"] for item in request["deferred_input_stats"].values())


def test_record_contains_complete_identity_fields(tmp_path: Path):
    loaded = module()
    path = tmp_path / "source.json"
    path.write_text("{}\n", encoding="utf-8")
    identity = loaded.record(path)
    assert set(("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "sha256")) <= identity.keys()
    assert identity["bytes"] == path.stat().st_size


def test_prepost_guard_records_before_decoder_and_after_decode(tmp_path: Path):
    loaded = module()
    path = tmp_path / "payload.bin"
    path.write_bytes(b"stable")
    events: list[str] = []
    original_record = loaded.record

    def observing_record(value):
        events.append("record")
        return original_record(value)

    loaded.record = observing_record

    def decoder():
        assert events == ["record"]
        events.append("decode")
        return "decoded"

    result, pre, post = loaded.prepost_guarded_decode({"payload": path}, decoder)
    assert result == "decoded"
    assert events == ["record", "decode", "record"]
    assert pre == post
    assert pre["payload"]["sha256"] == post["payload"]["sha256"]


def test_prepost_guard_rejects_payload_mutation(tmp_path: Path):
    loaded = module()
    path = tmp_path / "payload.bin"
    path.write_bytes(b"before")

    def decoder():
        path.write_bytes(b"after")
        return None

    with pytest.raises(ValueError, match="input changed during decode"):
        loaded.prepost_guarded_decode({"payload": path}, decoder)


def test_v2_manifest_declares_parent_bound_vtk_bytes():
    manifest_path = REQUEST.parent / "f3-s2-root086-vtk-support-qa-v2-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"].endswith("manifest.v2")
    assert manifest["product"]["fluid_vtk"]["bytes"] == 2_835_280
    assert manifest["product"]["bound_vtk"]["bytes"] == 4_803_741
    assert manifest["product"]["fluid_vtk"]["sha256"] == "PARENT_GUARD_COMPUTED"
    assert manifest["input_stability"]["record_fields"][-1] == "sha256"
