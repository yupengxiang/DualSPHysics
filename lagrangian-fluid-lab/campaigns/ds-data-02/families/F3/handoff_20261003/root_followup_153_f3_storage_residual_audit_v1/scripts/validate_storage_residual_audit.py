#!/usr/bin/env python3
"""Validate fresh153 without opening scientific payload contents."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
HERE = Path(__file__).resolve().parents[1]
AUDIT = HERE / "metadata/storage-residual-audit.json"
SCIENCE_SUFFIXES = {".h5", ".csv", ".bi4", ".vtk", ".dat", ".xmf", ".hdf5"}
def sha256_metadata(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise AssertionError(f"refusing to hash scientific suffix: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()
def main() -> int:
    d = json.loads(AUDIT.read_text())
    assert d["schema"] == "ds02.f3.storage-residual-audit.v1"
    policy = d["policy"]
    assert policy["read_only"] is True and policy["deletion_performed"] is False
    assert policy["jobs_started"] is False and policy["shared_state_modified"] is False
    assert policy["scientific_payload_contents_read_or_hashed"] is False
    assert policy["payload_paths_stat_only"] is True
    summary = d["f3_residual_summary"]
    assert summary["failed_attempts_total"] == 61
    assert summary["failed_attempts_at_or_above_threshold"] == 1
    assert summary["reclaimable_allocated_bytes"] == 0
    c = d["candidate"]
    assert c["decision"] == "retain" and c["total_allocated_bytes"] >= d["scope"]["threshold_allocated_bytes"]
    assert c["downstream_metadata_references"]["exact_case_metadata_reference_count"] >= 1
    assert c["active_use_checks"]["matching_runtime_reservations"] == []
    assert c["active_use_checks"]["exact_proc_cmdline_matches"] == []
    for f in c["current_stat_checks"]["files"]:
        assert f["sha256"] is None and f["hash_performed"] is False
        p = Path(f["path"]); assert p.exists(); s = p.stat()
        assert s.st_size == f["bytes"] and s.st_blocks * 512 == f["allocated_bytes"]
        assert s.st_ino == f["inode"] and s.st_dev == f["device"]
    for src in d["source_audits"]:
        p = Path(src["path"]); assert p.suffix.lower() not in SCIENCE_SUFFIXES
        assert p.exists() and sha256_metadata(p) == src["sha256"]
    for ref in c["downstream_metadata_references"]["files"]:
        p = Path(ref["path"]); assert p.suffix.lower() not in SCIENCE_SUFFIXES
        assert p.exists() and sha256_metadata(p) == ref["metadata_sha256"]
    ledger = Path(c["downstream_metadata_references"]["runtime_ledger"]["path"])
    assert ledger.exists() and sha256_metadata(ledger) == c["downstream_metadata_references"]["runtime_ledger"]["metadata_sha256"]
    print("fresh153 metadata validator: PASS (retain candidate; 0 bytes proposed for deletion)")
    return 0
if __name__ == "__main__": raise SystemExit(main())
