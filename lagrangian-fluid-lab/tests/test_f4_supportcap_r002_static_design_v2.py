from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from scripts import f4_supportcap_r002_static_design_v1 as predecessor
from scripts import f4_supportcap_r002_static_design_v2 as design


def test_build_recipe_never_hashes_or_opens_hdf5_or_npz(monkeypatch):
    original = predecessor._sha256
    seen = []

    def guarded_sha256(path):
        path = Path(path)
        if path.suffix.lower() in {".h5", ".hdf5", ".npz"}:
            pytest.fail(f"static recipe tried to hash binary trajectory: {path}")
        seen.append(path)
        return original(path)

    monkeypatch.setattr(predecessor, "_sha256", guarded_sha256)
    recipe = design.build_recipe()
    assert seen
    assert recipe["static_read_boundary"]["hdf5_npz_stat_open_parse_or_hash_performed"] is False


def test_r001_trace_binding_is_inherited_verbatim_from_attribution_json():
    attribution = json.loads(predecessor.ATTRIBUTION.read_text(encoding="utf-8"))
    source = next(item for item in attribution["bindings"] if item["path"] == design.TRACE_PATH)
    bound = next(item for item in design.parent_bindings(attribution) if item["path"] == design.TRACE_PATH)
    assert bound == {
        "path": source["path"],
        "role": source["role"],
        "bytes": source["bytes"],
        "sha256": source["sha256"],
    }


def test_parent_binding_rejects_unexpected_binary_without_access():
    attribution = json.loads(predecessor.ATTRIBUTION.read_text(encoding="utf-8"))
    attribution["bindings"].append({
        "path": "campaigns/elsewhere/unexpected.h5",
        "role": "unexpected binary",
        "bytes": 1,
        "sha256": "0" * 64,
    })
    with pytest.raises(ValueError, match="unexpected binary parent"):
        design.parent_bindings(attribution)


def test_recipe_preserves_temporal_alignment_and_zero_runtime_authority():
    recipe = design.build_recipe()
    assert recipe["schema"] == design.SCHEMA
    assert recipe["status"] == "static_temporal_alignment_design_v2_for_independent_review"
    attempt = recipe["prospective_attempt"]
    assert attempt["alignment"]["initial_native_frame"] == 0
    assert attempt["alignment"]["target_transition"] == [40, 41]
    assert attempt["alignment"]["expected_saved_rows"] == 42
    assert attempt["denominator"] == 512
    assert attempt["q"] == 0.5
    assert attempt["dp_m"] == 0.0075
    assert attempt["substeps"] == 2
    authority = recipe["execution_authority"]
    assert authority["native_preflight_authorized"] is False
    assert authority["cpu_canary_authorized"] is False
    assert authority["solver_authorized"] is False
    assert authority["gpu_authorized"] is False
    assert authority["worker_or_queue_authorized"] is False
    assert authority["qualification_credit"] == 0


def test_written_v2_receipt_matches_current_text_sources_and_inherited_h5_metadata():
    receipt = json.loads((design.LAB / design.RECEIPT).read_text(encoding="utf-8"))
    assert receipt == design.build_recipe()
    attribution = json.loads(predecessor.ATTRIBUTION.read_text(encoding="utf-8"))
    inherited = {item["path"]: item for item in attribution["bindings"]}
    for binding in receipt["bindings"]:
        source = design.LAB / binding["path"]
        if source.suffix.lower() in {".h5", ".hdf5", ".npz"}:
            assert binding == inherited[binding["path"]]
            continue
        assert source.stat().st_size == binding["bytes"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == binding["sha256"]
