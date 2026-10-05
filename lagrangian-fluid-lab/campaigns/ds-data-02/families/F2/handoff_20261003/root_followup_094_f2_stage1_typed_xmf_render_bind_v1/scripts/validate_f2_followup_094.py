#!/usr/bin/env python3
"""Metadata-only validator for the F2 fresh094 handoff.

It opens JSON/XML/source metadata only.  It never opens or hashes H5, BI4,
CSV, VTK, or related science artifacts.  The root runner owns those reads.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path

SCIENCE = {".h5", ".bi4", ".ibi4", ".csv", ".vtk", ".vtp", ".vtu", ".pvd", ".raw"}

def digest(path: Path) -> str:
    if path.suffix.lower() in SCIENCE:
        raise AssertionError(f"science artifact read attempted: {path}")
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def obj(path, label):
    p = Path(path)
    if p.suffix.lower() in SCIENCE:
        raise AssertionError(f"{label} is science data")
    if not p.is_file():
        raise AssertionError(f"{label} missing: {p}")
    actual = digest(p)
    d = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d, dict):
        raise AssertionError(f"{label} must be an object")
    return p, actual, d

def eq(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")

def check_receipt(path, status, rc, label):
    _, actual, d = obj(path, label)
    eq(d.get("status"), status, label + ".status")
    eq(d.get("returncode"), rc, label + ".returncode")
    return {"path": str(path), "sha256": actual, "status": status, "returncode": rc}

def check_case(binding_path, expected_lifecycle):
    _, binding_sha, b = obj(binding_path, "binding")
    eq(b.get("schema"), "ds02.f2.stage1.fresh094-binding.v1", "binding.schema")
    eq(b.get("source_only"), True, "binding.source_only")
    eq(b.get("independent_case_count_increment"), 0, "binding.case_count")
    counts = b["actual_native_counts"]
    eq(counts, {"dimension": 3, "total": 418104, "fluid": 21114, "fixed": 372840, "moving": 24150}, "native counts")
    eq(b["actual_native"]["frames"], 401, "native frames")
    eq(b["actual_native"]["save_interval_s"], 0.01, "native tout")
    eq(b["actual_native"]["time_max_s"], 4.0, "native tmax")
    eq(b["actual_native"]["mdbc_added"], False, "native mdbc")
    eq(b["source_physical_condition_sha256"] != b["canonical_physical_binding_sha256"], True, "source/canonical separation")

    _, _, owner = obj(b["owner"]["path"], "owner")
    eq(owner["case_id"], b["case_id"], "owner case")
    eq(owner["canonical_physical_binding_sha256"], b["canonical_physical_binding_sha256"], "owner canonical")
    eq(owner["physical_condition_sha256"], b["source_physical_condition_sha256"], "owner source condition")
    _, _, native = obj(b["native_binding"]["path"], "native binding")
    eq(native["canonical_physical_binding_sha256"], b["canonical_physical_binding_sha256"], "native canonical")
    eq(native["actual_solver"]["status"], "completed", "native binding status")

    check_receipt(b["gencase"]["receipt"]["path"], "completed", 0, "gencase")
    _, _, qa = obj(b["initial_qa"]["report"]["path"], "initial QA report")
    eq(qa.get("status"), "pass", "initial QA report status")
    eq(all(v is True for v in qa["checks"].values()), True, "initial QA checks")
    check_receipt(b["initial_qa"]["receipt"]["path"], "completed", 0, "initial QA receipt")
    check_receipt(b["native"]["receipt"]["path"], "completed", 0, "native receipt")

    _, _, report = obj(b["typed"]["report"]["path"], "typed report")
    eq(report.get("frames"), 401, "typed report frames")
    eq(report.get("particles"), 418104, "typed report particles")
    eq(report.get("conversion_status"), "completed", "typed report status")
    typed_receipt = obj(b["typed"]["receipt"]["path"], "typed receipt")[2]

    if expected_lifecycle == "true_converter_completed0":
        eq(typed_receipt.get("status"), "completed", "P01 typed receipt status")
        eq(typed_receipt.get("returncode"), 0, "P01 typed receipt returncode")
        eq(b["typed"]["lifecycle"], expected_lifecycle, "P01 lifecycle")
        check_receipt(b["xmf"]["receipt"]["path"], "completed", 0, "P01 XMF receipt")
        _, _, xr = obj(b["xmf"]["manifest"]["path"], "P01 XMF manifest")
        eq(xr.get("frames"), 401, "P01 XMF frames")
        check_receipt(b["root023"]["receipt"]["path"], "completed", 0, "P01 Root023 receipt")
        _, _, rr = obj(b["root023"]["report"]["path"], "P01 Root023 report")
        eq(rr.get("frames"), 401, "P01 render frames")
    elif expected_lifecycle == "recovered_artifact_original_143_unknown":
        eq(typed_receipt.get("status"), "running", "P03 original typed status")
        eq(typed_receipt.get("returncode"), None, "P03 original typed returncode")
        eq(b["typed"]["original_tool_status"], 143, "P03 original tool status")
        eq(b["typed"]["lifecycle"], expected_lifecycle, "P03 lifecycle")
        _, _, ar = obj(b["recovery_audit"]["report"]["path"], "P03 recovery audit")
        eq(ar.get("artifact_integrity_status"), "completed", "P03 audit status")
        eq(ar.get("worker_returncode"), 0, "P03 audit returncode")
        eq(ar.get("opaque_hash_only"), True, "P03 audit opaque")
        eq(ar.get("arrays_decoded"), False, "P03 audit array policy")
        eq(ar.get("source_conversion_reclassified"), False, "P03 source lifecycle")
        eq(ar.get("source_receipt_edited"), False, "P03 source receipt")
        eq(ar.get("verified_frames"), 401, "P03 audit frames")
        eq(ar.get("verified_particles"), 418104, "P03 audit particles")
        check_receipt(b["recovery_audit"]["receipt"]["path"], "completed", 0, "P03 audit receipt")
        check_receipt(b["recovery"]["xmf_receipt"]["path"], "completed", 0, "P03 XMF receipt")
        _, _, d = obj(b["recovery"]["render_receipt"]["path"], "P03 Root023 receipt")
        eq(d.get("request", {}).get("attempt_id"), "root-stage1-f2-offset-p03-recovery-aware-root023-preview-093", "P03 render attempt")
    else:
        raise AssertionError(expected_lifecycle)
    return {"case_id": b["case_id"], "binding_sha256": binding_sha, "lifecycle": expected_lifecycle}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--case", choices=["all", "P01", "P03"], default="all")
    args = ap.parse_args()
    _, _, m = obj(args.manifest, "manifest")
    eq(m.get("schema"), "ds02.f2.stage1.fresh094-handoff.v1", "manifest.schema")
    eq(m.get("source_only"), True, "manifest.source_only")
    eq(m.get("launch_allowed"), False, "manifest.launch_allowed")
    eq(m.get("execution_allowed"), False, "manifest.execution_allowed")
    out = []
    for c in m["cases"]:
        if args.case != "all" and c["tag"] != args.case:
            continue
        out.append(check_case(c["binding"], c["lifecycle"]))
    print(json.dumps({"pass": True, "cases": out, "array_policy": "no H5/BI4/CSV/VTK opened"}, indent=2))

if __name__ == "__main__":
    main()
