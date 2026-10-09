#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a source-bound ROOT240 V2 compact F3 comparison request.

Only proof/request/receipt JSON and the three bounded compact summaries are
opened.  The builder does not hash or read native files, RunPARTs, VTK/H5, or
the large full reports referenced by ROOT177/178.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_v2.py"
CONTRACT = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_contract_v2.json"
V1_WORKER = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_v1.py"
V1_CONTRACT = HERE / "stage2_f3_s2_compact_spatial_lifecycle_compare_contract_v1.json"
SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f3-s2.compact-spatial-lifecycle-manifest.v2"
CASE = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERIES = [0.0, 2.0, 4.0, 6.0, 8.0]
MAX_JSON = 4 * 1024 * 1024


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} is not a regular file: {path}")
    return path.absolute()


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size), "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _record(path: Path, label: str, limit: int = MAX_JSON, parse: bool = True) -> tuple[Any, dict[str, Any]]:
    path = _regular(path, label); before = _stat(path)
    if before["bytes"] > limit:
        raise ValueError(f"{label} exceeds bounded input limit: {before['bytes']}")
    digest = hashlib.sha256(); chunks: list[bytes] = []
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk); chunks.append(chunk)
    after = _stat(path)
    if before != after:
        raise RuntimeError(f"{label} changed during read")
    value: Any = None
    if parse:
        value = json.loads(b"".join(chunks).decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError(f"{label} is not a JSON object")
    rec = {"path": str(path), "sha256": digest.hexdigest(), "bytes": after["bytes"], "stat": after, "stable_read": True, "label": label, "content_scope": "bounded_json_metadata_only" if parse else "source_code_or_runtime_metadata"}
    return value, rec


def _code(path: Path, label: str, limit: int = 8 * 1024 * 1024) -> dict[str, Any]:
    return _record(path, label, limit, False)[1]


def _canonical(value: dict[str, Any]) -> str:
    body = {k: v for k, v in value.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()).hexdigest()


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise ValueError(f"refusing to overwrite immutable file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser()
    if not literal.is_symlink():
        raise ValueError(f"literal venv argv0 is not a symlink: {literal}")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {"literal_argv0": str(literal), "literal_argv0_required": True, "resolved": _code(resolved, "resolved venv Python"), "pyvenv_cfg": _code(cfg, "pyvenv.cfg", 1024 * 1024)}


def _linked_output(proof: dict[str, Any], summary: dict[str, Any], summary_rec: dict[str, Any], label: str) -> None:
    found = False
    for key in ("summary", "report", "observer_report", "compact_report", "output", "child_report"):
        value = proof.get(key)
        if isinstance(value, str) and value == summary_rec["path"]:
            found = True
            bound_sha = proof.get(f"{key}_sha256") or proof.get("summary_sha256") or proof.get("report_sha256")
            if bound_sha and str(bound_sha).lower() != summary_rec["sha256"]:
                raise ValueError(f"{label} proof/{key} SHA mismatch")
        elif isinstance(value, dict) and value.get("path") == summary_rec["path"]:
            found = True
            if value.get("sha256") and str(value["sha256"]).lower() != summary_rec["sha256"]:
                raise ValueError(f"{label} proof/{key} SHA mismatch")
    if not found:
        raise ValueError(f"{label} proof does not bind compact output")


def _edge(label: str, proof_path: Path, solver_proof_path: Path, summary_path: Path) -> dict[str, Any]:
    proof, proof_rec = _record(proof_path, f"{label} observer proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} observer proof is not actual")
    req_path, receipt_path = Path(str(proof["request"])), Path(str(proof["receipt"]))
    _, req_rec = _record(req_path, f"{label} observer request")
    receipt, receipt_rec = _record(receipt_path, f"{label} observer receipt")
    if proof.get("request_sha256") != req_rec["sha256"] or proof.get("receipt_sha256") != receipt_rec["sha256"]:
        raise ValueError(f"{label} observer proof/request/receipt SHA join failed")
    if not str(receipt.get("status", "")).lower().startswith(("complete", "success")):
        raise ValueError(f"{label} observer receipt is not completed")
    solver, solver_rec = _record(solver_proof_path, f"{label} solver proof")
    if solver.get("schema") not in {"ds02.stage2.root-actual-verification.v1", "ds02.stage2.root-actual-external-solver-verification.v1"} or "ACTUAL" not in str(solver.get("status", "")):
        raise ValueError(f"{label} solver proof is not actual")
    sreq_rec = _record(Path(str(solver["request"])), f"{label} solver request", 8 * 1024 * 1024)[1]
    sreceipt, srec_rec = _record(Path(str(solver["receipt"])), f"{label} solver receipt", 32 * 1024 * 1024)
    if solver.get("request_sha256") != sreq_rec["sha256"] or solver.get("receipt_sha256") != srec_rec["sha256"]:
        raise ValueError(f"{label} solver proof/request/receipt SHA join failed")
    if not str(sreceipt.get("status", "")).lower().startswith(("complete", "success")):
        raise ValueError(f"{label} solver receipt is not completed")
    summary, summary_rec = _record(summary_path, f"{label} compact summary")
    if not str(summary.get("schema", "")).startswith("ds02.stage2.f3-s2.") or not str(summary.get("status", "")).startswith("PASS"):
        raise ValueError(f"{label} compact summary schema/status is not successful")
    if int(summary.get("frame_count", summary.get("window", {}).get("frame_count", -1))) != 836:
        raise ValueError(f"{label} compact frame count is not 836")
    _linked_output(proof, summary, summary_rec, label)
    return {"label": label, "observer_proof": proof_rec, "observer_request": req_rec, "observer_receipt": receipt_rec, "solver_proof": _record(solver_proof_path, f"{label} solver proof final")[1], "solver_request": sreq_rec, "solver_receipt": srec_rec, "summary": summary_rec}


def _manifest(args: argparse.Namespace) -> dict[str, Any]:
    edges = [
        _edge("coarse", args.coarse_proof, args.coarse_solver_proof, args.coarse_summary),
        _edge("middle", args.middle_proof, args.middle_solver_proof, args.middle_summary),
        _edge("fine", args.fine_proof, args.fine_solver_proof, args.fine_summary),
    ]
    for edge, spacing in zip(edges, (0.015, 0.006, 0.003)):
        edge["solver_spacing_m"] = spacing
    manifest = {"schema": MANIFEST_SCHEMA, "status": "PREPARED_NOT_RUN_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": CASE, "query_times_s": QUERIES, "producers": edges, "scope": {"compact_summary_only": True, "large_full_report_read": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "interpolation": False, "neighbor_grid_truth": False}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}
    manifest["sha256"] = _canonical(manifest)
    return manifest


def build(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _manifest(args)
    _write_once(args.manifest_output, manifest)
    manifest_rec = _record(args.manifest_output, "ROOT240 V2 manifest", parse=False)[1]
    records: dict[str, dict[str, Any]] = {manifest_rec["path"]: manifest_rec}
    for path, label in ((WORKER, "ROOT240 V2 worker"), (CONTRACT, "ROOT240 V2 contract"), (V1_WORKER, "ROOT240 V1 imported worker"), (V1_CONTRACT, "ROOT240 V1 imported contract")):
        rec = _code(path, label); records[rec["path"]] = rec
    py = _python_binding(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    for producer in manifest["producers"]:
        for key in ("observer_proof", "observer_request", "observer_receipt", "solver_proof", "solver_request", "solver_receipt", "summary"):
            records[producer[key]["path"]] = producer[key]
    input_files = sorted(records); input_hashes = {p: records[p]["sha256"] for p in input_files}
    request = {"schema": SCHEMA, "variant_schema": "ds02.stage2.f3-s2.compact-spatial-lifecycle-compare-request.v2", "status": "READY_FOR_PARENT_V8_F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2", "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F3", "sentinel_id": "F3-S2", "physical_case_id": CASE, "case_id": args.case_id, "attempt_id": args.attempt_id, "launch_commit": args.launch_commit, "cwd": str(PRIMARY / "lagrangian-fluid-lab"), "worktree_root": str(PRIMARY), "command": [str(PYTHON), str(WORKER), "--manifest", str(args.manifest_output.absolute()), "--output", "{attempt_root}/comparison/f3_s2_compact_spatial_lifecycle_compare_v2.json"], "input_files": input_files, "input_hashes": input_hashes, "input_sha256": input_hashes, "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 900, "max_memory_bytes": 1024 * 1024 * 1024, "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024, "estimated_input_read_bytes": sum(int(v["bytes"]) for v in records.values()), "estimated_hdf5_read_bytes": 0, "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": False, "solver_launch": False, "native_payload_read": False, "hdf5_read": False, "vtk_read": False, "raw_directory_scan": False, "output_root": "{attempt_root}", "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f3_s2_compact_spatial_lifecycle_compare_v2.json"}, "source_binding": {"query_times_s": QUERIES, "producer_labels": ["coarse", "middle", "fine"], "summary_proof_edge_required": True, "full_report_read": False, "native_payload_read": False, "interpolation": False, "neighbor_grid_truth": False}, "resource_guard": {"runner": "parent-v8-audit", "full_report": "forbidden", "native_payload": "forbidden", "solver_launch": "forbidden"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}}
    request["sha256"] = _canonical(request)
    _write_once(args.output_request, request)
    return request


def _self_test() -> None:
    # This test validates the strict negative that matters for ROOT240: a
    # proof cannot be paired with an unrelated compact output.  No production
    # file is read.
    proof = {"report": "/tmp/expected.json", "report_sha256": "a" * 64}
    summary_rec = {"path": "/tmp/other.json", "sha256": "b" * 64}
    try: _linked_output(proof, {}, summary_rec, "fixture")
    except ValueError: pass
    else: raise AssertionError("unrelated compact output was accepted")
    assert _canonical({"x": 1}) == _canonical({"x": 1})
    print("PASS_F3_S2_COMPACT_SPATIAL_LIFECYCLE_REQUEST_V2_SELFTEST")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--coarse-proof", type=Path); p.add_argument("--coarse-solver-proof", type=Path); p.add_argument("--coarse-summary", type=Path)
    p.add_argument("--middle-proof", type=Path); p.add_argument("--middle-solver-proof", type=Path); p.add_argument("--middle-summary", type=Path)
    p.add_argument("--fine-proof", type=Path); p.add_argument("--fine-solver-proof", type=Path); p.add_argument("--fine-summary", type=Path)
    p.add_argument("--manifest-output", type=Path, default=Path("stage2-f3-s2-compact-spatial-lifecycle-manifest-v2-root240.json")); p.add_argument("--output-request", type=Path); p.add_argument("--case-id", default="F3_S2_COMPACT_SPATIAL_LIFECYCLE_COMPARE_V2_ROOT240"); p.add_argument("--attempt-id", default="f3-s2-compact-spatial-lifecycle-compare-v2-root-240-001"); p.add_argument("--launch-commit", default="SOURCE_ONLY_ROOT240_V2"); p.add_argument("--self-test", action="store_true")
    args = p.parse_args()
    if args.self_test: _self_test(); return 0
    required = ("coarse_proof", "coarse_solver_proof", "coarse_summary", "middle_proof", "middle_solver_proof", "middle_summary", "fine_proof", "fine_solver_proof", "fine_summary", "output_request")
    if any(getattr(args, x) is None for x in required): p.error("all producer proof/solver-proof/summary paths and --output-request are required")
    try:
        req = build(args)
    except Exception as exc:
        print(f"FAILED_F3_S2_COMPACT_SPATIAL_LIFECYCLE_REQUEST_V2: {exc}"); return 2
    print(json.dumps({"status": req["status"], "request": str(args.output_request.absolute()), "manifest": str(args.manifest_output.absolute()), "sha256": req["sha256"]}, sort_keys=True)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
