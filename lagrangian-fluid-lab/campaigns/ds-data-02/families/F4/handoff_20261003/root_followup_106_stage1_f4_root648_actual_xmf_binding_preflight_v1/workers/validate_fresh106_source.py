#!/usr/bin/env python3
"""Validate fresh106 JSON/source contracts; never opens scientific payloads."""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

RAW_SUFFIXES = {".bi4", ".h5", ".hdf5", ".vtk", ".vtu", ".vtp", ".csv", ".dat"}
STALE = ("fresh104", "fresh105", "fresh097", "fresh098", "fresh099")

def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))

def main() -> None:
    ap = argparse.ArgumentParser(); ap.add_argument("--package", type=Path, required=True)
    p = ap.parse_args().package.resolve()
    m = load(p / "manifest.json"); assert m["case_count"] == 24 and m["request_count"] == 24 and m["typed_request_count"] == 0
    idx = load(p / "requests/index.json"); assert idx["case_count"] == 24 and idx["request_count"] == 24 and idx["all_disabled"]
    assert len(idx["requests"]) == 24
    sys.path.insert(0, str(p / "workers"))
    from verify_export_xmf_binding import preflight_binding
    cases = set()
    for row in idx["requests"]:
        assert row["kind"] == "render" and row["disabled"] is True
        q = load(Path(row["path"])); cases.add(q["case_id"])
        assert q["disabled"] and not q["execution_allowed"] and not q["launch"] and not q["launch_allowed"]
        assert q["source_only"] and not q["jobs_started_by_source"] and q["shared_registry_write_by_source"] is False
        assert q["depends_on_attempts"] and q["case_xmf"] is None and q["manifest"] is None
        assert "{root666_manifest}" in q["deferred_input_files"]
        assert all(v is None for v in q["future_hashes"].values())
        assert all(v is None for v in q["deferred_input_sha256"].values())
        for path in q["input_files"]:
            assert Path(path).suffix.lower() not in RAW_SUFFIXES
        for path in q["command"]:
            assert not any(marker in str(path).lower() for marker in STALE)
    assert len(cases) == 24
    xmf_cases = set()
    for path in sorted((p / "bindings").glob("*.export-xmf-binding.json")):
        b = load(path); xmf_cases.add(b["case_id"])
        assert b["typed_receipt"] is None and b["conversion_report"] is None and b["trajectory_h5"] is None
        out = preflight_binding(b, typed_status="WAIT")
        assert out["status"].startswith("WAIT")
        assert "root619" in b["native_receipt"].lower()
    assert xmf_cases == cases
    for path in (p / "bindings").glob("*.render-binding.json"):
        b = load(path); assert b["case_id"] in cases and b["case_xmf"] is None and b["manifest"] is None
        assert all(v is None for v in b["future_hashes"].values())
    for path in (p / "requests").glob("*.json"):
        assert "typed" not in path.name
    contract = load(p / "metadata/export-xmf-binding-contract.json")
    assert contract["path_contract"]["nested_path_sha_objects_rejected"]
    assert contract["semantic_contract"]["expected_frames"] == 1201
    print("fresh106 source contract: PASS (24 WAIT exporter bindings, 24 disabled Root023 successors, no typed requests/payload access)")

if __name__ == "__main__":
    main()
