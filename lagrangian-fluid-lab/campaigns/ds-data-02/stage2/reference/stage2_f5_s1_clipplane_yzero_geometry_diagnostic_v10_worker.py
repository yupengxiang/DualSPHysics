#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""F5 ROOT124 geometry diagnostic with strict q123/receipt binding.

The consumed V9 worker remains the payload reader.  This forward wrapper
closes the producer tuple before V9 opens XML/Fluid/Bound payloads, then marks
the global pointref phase comparison as pending.  The strings describing
fluid/boundary/forcing scope are contracts, not evidence that all shapes were
compared; no such qualification is emitted here.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V9_WORKER_PATH = HERE / "stage2_f5_s1_clipplane_geometry_diagnostic_yzero_v9.py"
SCHEMA = "ds02.stage2.f5-s1.clipplane-yzero-geometry-diagnostic.v10"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V9 = load_module("stage2_f5_yzero_geometry_v9_for_v10", V9_WORKER_PATH)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {resolved}")
    return resolved


def load_json(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _identity(value: dict[str, Any]) -> dict[str, Any]:
    scope = value.get("scope") if isinstance(value.get("scope"), dict) else {}
    result: dict[str, Any] = {}
    for key in ("family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        direct = value.get(key)
        if direct is None:
            direct = scope.get(key)
        if direct is not None:
            result[key] = direct
    return result


def strict_q_receipt_join(q_path: Path, receipt_path: Path) -> dict[str, Any]:
    q_path = regular(q_path, "F5 q123 GenCase request")
    receipt_path = regular(receipt_path, "F5 q123 GenCase receipt")
    q = load_json(q_path, "F5 q123 GenCase request")
    receipt = load_json(receipt_path, "F5 q123 GenCase receipt")
    if q.get("schema") != REQUEST_SCHEMA or q.get("family_id") != "F5" or q.get("sentinel_id") != "F5-S1":
        raise ValueError("F5-S1 q123 identity mismatch")
    if q.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F5 physical case identity mismatch")
    binding = q.get("source_binding")
    if not isinstance(binding, dict) or binding.get("grid") != "dp005" or tuple(binding.get("pointref_m", ())) != (0.0125, 0.0, 0.0125):
        raise ValueError("q123 is not the registered Y-zero dp005 source")
    q_identity = _identity(q)
    if not all(q_identity.get(key) for key in ("case_id", "attempt_id")):
        raise ValueError("q123 case_id/attempt_id is missing")
    if receipt.get("request") != q:
        raise ValueError("q123 receipt.request is not exactly the supplied request object")
    q_sha = sha256(q_path)
    if receipt.get("request_sha256") != q_sha:
        raise ValueError("q123 receipt.request_sha256 does not match q123 request SHA")
    top_identity = _identity(receipt)
    for key, value in top_identity.items():
        if key in q_identity and value != q_identity[key]:
            raise ValueError(f"q123 receipt top-level {key} mismatch")
    if str(receipt.get("status", "")).lower() not in {"completed", "complete", "success", "completed0"} or receipt.get("returncode") not in (0, None):
        raise ValueError("q123 receipt is not completed zero-return")
    actual_value = receipt.get("output_root")
    if not isinstance(actual_value, str) or not actual_value.strip():
        raise ValueError("q123 receipt output_root is missing")
    actual_root = Path(actual_value).expanduser().resolve()
    if not actual_root.is_dir():
        raise FileNotFoundError(f"q123 receipt output_root is not a directory: {actual_root}")
    planned_value = q.get("output_root")
    planned_root = Path(str(planned_value)).expanduser().resolve() if planned_value else None
    return {
        "q_path": str(q_path), "q_sha256": q_sha, "receipt_path": str(receipt_path),
        "receipt_request_exact_q": True, "receipt_request_sha256_exact_q": True,
        "request_identity": q_identity, "receipt_request_identity": _identity(receipt["request"]),
        "receipt_top_level_identity": top_identity,
        "actual_receipt_output_root": str(actual_root),
        "planned_output_root": str(planned_root) if planned_root else "UNKNOWN_NOT_DECLARED_BY_SOURCE_REQUEST",
        "planned_root_matches_receipt": planned_root == actual_root if planned_root else "UNKNOWN_SOURCE_REQUEST_NO_OUTPUT_ROOT",
        "actual_receipt_output_root_authoritative": True,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    join = strict_q_receipt_join(args.gencase_request, args.receipt)
    report = dict(V9.build_report(args))
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F5_YZERO_GEOMETRY_IDP_OVERLAP_DIAGNOSTIC_V10"
    report.setdefault("gencase_binding", {})["strict_q_receipt_join"] = join
    report["source_closure"] = dict(report.get("source_closure", {}))
    report["source_closure"]["strict_q_receipt_join_before_dynamic_payload"] = True
    report["source_closure"]["actual_receipt_output_root_authoritative"] = True
    report["all_shapes_comparison"] = {
        "status": "NOT_EXECUTED_BY_THIS_GEOMETRY_WORKER",
        "required_scopes": ["fluid", "fixed_boundary", "moving_boundary", "forcing", "shape_operations"],
        "all_shapes_require_comparison": True,
        "bound_per_mk_assignment": "UNKNOWN_UNTIL_BOUND_IDP_MAPPING_EXISTS",
        "control_motion_identity_is_not_shape_comparison": True,
    }
    candidate = report.setdefault("candidate_contract", {})
    candidate["all_shapes_require_comparison"] = True
    candidate["all_shapes_comparison_status"] = "PENDING_JSON_ONLY_COMPARISON"
    candidate["fluid_boundary_forcing_not_assumed_equal"] = True
    qualification = report.setdefault("qualification", {})
    qualification.update({"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
    qualification["reason"] = "Y-zero VTK geometry diagnostic; all-shape comparison is a separate JSON-only task and no qualification is granted"
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable F5 V10 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
            handle.flush(); os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="f5-v10-join-") as directory:
        root = Path(directory) / "actual"
        root.mkdir()
        q_path = Path(directory) / "q.json"
        receipt_path = Path(directory) / "receipt.json"
        q = {"schema": REQUEST_SCHEMA, "family_id": "F5", "sentinel_id": "F5-S1", "physical_case_id": PHYSICAL_CASE_ID, "case_id": "C", "attempt_id": "A", "source_binding": {"grid": "dp005", "pointref_m": [0.0125, 0.0, 0.0125]}}
        q_path.write_text(json.dumps(q, sort_keys=True) + "\n", encoding="utf-8")
        receipt = {"status": "completed", "returncode": 0, "request": q, "request_sha256": sha256(q_path), "output_root": str(root)}
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        evidence = strict_q_receipt_join(q_path, receipt_path)
        if not evidence["receipt_request_exact_q"] or not evidence["actual_receipt_output_root_authoritative"]:
            raise AssertionError(evidence)
        bad = dict(receipt); bad["request_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
        try:
            strict_q_receipt_join(q_path, receipt_path)
        except ValueError:
            pass
        else:
            raise AssertionError("wrong q123 SHA accepted")
    return {"status": "PASS", "schema": SCHEMA, "strict_q_receipt_join": True, "all_shapes_comparison_not_claimed": True, "solver_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("generated-xml", "fluid-vtk", "bound-vtk", "receipt", "candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    for name in ("candidate-def", "source-def", "candidate-motion", "source-motion", "clip-evidence", "gencase-request", "generated-xml", "receipt", "support-contract"):
        parser.add_argument(f"--expected-{name}-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2)); return 0
    required = [args.generated_xml, args.fluid_vtk, args.bound_vtk, args.receipt, args.candidate_def, args.source_def, args.candidate_motion, args.source_motion, args.clip_evidence, args.gencase_request, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all terminal/static paths, --support-contract and --output are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "all_shapes_comparison": report["all_shapes_comparison"]["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
