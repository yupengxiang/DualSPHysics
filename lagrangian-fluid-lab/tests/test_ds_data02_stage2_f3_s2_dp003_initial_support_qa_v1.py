from __future__ import annotations

import importlib.util
import json
import struct
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f3_s2_dp003_initial_support_qa_v1.py"
REQUEST = (
    ROOT
    / "campaigns/ds-data-02/stage2/requests/"
    / "f3-s2-dp003-initial-support-qa-v1-root-forward-099-001/"
    / "f3-s2-dp003-initial-support-qa-v1-request.json"
)
MANIFEST = REQUEST.with_name("f3-s2-dp003-initial-support-qa-v1-manifest.json")


def module():
    spec = importlib.util.spec_from_file_location("f3_s2_dp003_initial_support_qa_v1", SCRIPT)
    assert spec and spec.loader
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def test_self_test_and_dp_envelope():
    loaded = module()
    assert loaded.self_test()["status"] == "PASS"
    envelope = loaded.derived_envelope(0.003)
    assert envelope["fluid_selector"]["low_m"] == [-0.4485, -0.0885, 0.0015]
    assert envelope["fluid_selector"]["high_m"] == [0.4485, 0.0885, 0.0885]
    assert envelope["boundary_xml_envelope"]["low_m"] == [-0.4515, -0.0915, -0.0015]
    assert envelope["boundary_xml_envelope"]["high_m"] == [0.4515, 0.0915, 0.51]


def test_vtk_parser_uses_actual_range_and_rejects_wrong_type(tmp_path: Path):
    loaded = module()
    payload = (
        b"# vtk DataFile Version 3.0\nsmall\nBINARY\nDATASET POLYDATA\n"
        b"POINTS 2 float\n"
        + struct.pack(">ffffff", -0.4485, -0.0885, 0.0015, 0.4485, 0.0885, 0.0885)
        + b"\nPOINT_DATA 2\nSCALARS Idp unsigned_int 1\nLOOKUP_TABLE default\n"
        + struct.pack(">II", 540000, 540001) + b"\n"
    )
    path = tmp_path / "fluid.vtk"
    path.write_bytes(payload)
    points, meta = loaded.read_fluid_vtk(path, 2, 540000, 2)
    assert points.shape == (2, 3)
    assert meta["idp_mapping"] == "GLOBAL_XML_PARTICLE_IDS"
    bad = tmp_path / "bad.vtk"
    bad.write_bytes(payload.replace(b"unsigned_int", b"float"))
    with pytest.raises(ValueError, match="unsigned-int Idp"):
        loaded.read_fluid_vtk(bad, 2, 540000, 2)


def test_prepost_guard_records_before_decode_and_rejects_mutation(tmp_path: Path):
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

    def mutate():
        path.write_bytes(b"changed")

    with pytest.raises(ValueError, match="input changed during decode"):
        loaded.prepost_guarded_decode({"payload": path}, mutate)


def test_request_defers_candidate_products_and_keeps_science_unknown():
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert request["cpu_task_kind"] == "audit"
    assert request["solver_launch"] is False
    assert request["gencase_launch"] is False
    assert request["hdf5_read"] is False
    assert request["bi4_read"] is False
    assert request["vtk_read"] is True
    assert request["deferred_input_file_count"] == 6
    assert all(item["sha256"] == "PARENT_GUARD_COMPUTED" for item in request["deferred_input_stats"].values())
    assert all(Path(item).suffix.lower() not in {".vtk", ".bi4", ".h5"} for item in request["input_files"])
    assert request["source_binding"]["continuous_owner"]["mass_kg"] == pytest.approx(14.58)
    assert request["source_binding"]["candidate_actual_xml_only"]["fixed_count"] == "ACTUAL_XML_ONLY"
    assert request["source_binding"]["QI"] == "UNKNOWN"
    assert request["source_binding"]["QN"] == "UNKNOWN"
    assert manifest["candidate"]["actual_xml_requirements"]["fluid_count"] == 540000
    assert manifest["read_policy"]["candidate_outputs_deferred"] is True
    assert manifest["read_policy"]["worker_first_sha_before_xml_or_vtk_decode"] is True


def test_manifest_binds_three_historical_grids_and_source_hashes():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert [row["grid_id"] for row in manifest["historical_grids"]] == ["original_dp006", "coarse_dp0075", "fine_dp0048"]
    assert manifest["source"]["xml"]["sha256"] == "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
    assert manifest["source"]["control"]["sha256"] == "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
    controls = [row["control"]["sha256"] for row in manifest["historical_grids"]]
    assert len(set(controls)) == 2
    assert manifest["candidate"]["actual_xml_requirements"]["fixed_count"] == "ACTUAL_XML_ONLY"
