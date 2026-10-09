#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""F3-S2 support audit worker with a strict GenCase q/receipt join.

This is an additive forward worker.  The v3 parser/worker remains immutable;
this wrapper performs the missing identity check before it delegates to v3.
The completed receipt must contain the *exact* request object supplied by
``--gencase-request`` and its ``request_sha256`` must be the SHA-256 of that
request file.  The receipt's actual output_root is authoritative: a planned
request path is recorded only as metadata and is never used as a substitute.

No GenCase, solver, BI4, HDF5, or additional VTK operation is introduced by
the wrapper.  After the join succeeds, the frozen v3 worker performs the
already reviewed source and VTK audit under the parent guard.
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
V3_WORKER_PATH = HERE / "stage2_f3_s2_initial_support_audit_v3.py"
SCHEMA = "ds02.stage2.f3.s2.initial-support-audit.v5"
REQUEST_SCHEMA = "ds02.request.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"


def load_v3_worker():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_initial_support_audit_v3_for_v5", V3_WORKER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V3_WORKER_PATH)
    module = importlib.util.module_from_spec(spec)
    # Register before exec: dataclasses and exception classes in the frozen
    # module need a real sys.modules entry, and this keeps one module identity
    # throughout the delegated call.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V3 = load_v3_worker()


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
    for key in ("family_id", "case_id", "attempt_id", "sentinel_id", "physical_case_id"):
        direct = value.get(key)
        if direct is None:
            direct = scope.get(key)
        if direct is not None:
            result[key] = direct
    return result


def strict_q_receipt_join(q_path: Path, receipt_path: Path) -> dict[str, Any]:
    """Validate the producer request/receipt tuple before any dynamic read."""

    q_path = regular(q_path, "F3 GenCase request")
    receipt_path = regular(receipt_path, "F3 GenCase receipt")
    q = load_json(q_path, "F3 GenCase request")
    receipt = load_json(receipt_path, "F3 GenCase receipt")

    if q.get("schema") != REQUEST_SCHEMA:
        raise ValueError("F3 GenCase request schema mismatch")
    q_identity = _identity(q)
    if q_identity.get("family_id") != "F3" or q_identity.get("sentinel_id") != "F3-S2":
        raise ValueError("F3-S2 request identity mismatch")
    if q_identity.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F3 physical case identity mismatch")
    if not all(q_identity.get(key) for key in ("case_id", "attempt_id")):
        raise ValueError("F3 request case_id/attempt_id is missing")

    receipt_request = receipt.get("request")
    if not isinstance(receipt_request, dict):
        raise ValueError("receipt.request is missing; cannot establish exact producer identity")
    if receipt_request != q:
        raise ValueError("receipt.request is not byte-semantic equal to the supplied GenCase request object")

    request_sha = sha256(q_path)
    if receipt.get("request_sha256") != request_sha:
        raise ValueError("receipt.request_sha256 does not match the supplied GenCase request file")

    receipt_identity = _identity(receipt_request)
    for key in ("family_id", "case_id", "attempt_id"):
        if receipt_identity.get(key) != q_identity.get(key):
            raise ValueError(f"receipt/request {key} mismatch")
    receipt_top_identity = _identity(receipt)
    for key, value in receipt_top_identity.items():
        if key in q_identity and value != q_identity[key]:
            raise ValueError(f"receipt top-level {key} mismatches supplied request")

    status = str(receipt.get("status", "")).lower()
    if status not in {"completed", "complete", "success", "completed0"}:
        raise ValueError(f"GenCase receipt is not completed: {receipt.get('status')!r}")
    if receipt.get("returncode") not in (0, None):
        raise ValueError(f"GenCase receipt returncode is not zero: {receipt.get('returncode')!r}")
    actual_root_value = receipt.get("output_root")
    if not isinstance(actual_root_value, str) or not actual_root_value.strip():
        raise ValueError("receipt.output_root is missing; actual producer root is required")
    actual_root = Path(actual_root_value).expanduser().resolve()
    if not actual_root.is_dir():
        raise FileNotFoundError(f"receipt actual output_root is not a directory: {actual_root}")

    planned_root_value = q.get("output_root")
    planned_root = Path(str(planned_root_value)).expanduser().resolve() if planned_root_value else None
    return {
        "q_path": str(q_path),
        "q_sha256": request_sha,
        "receipt_path": str(receipt_path),
        "receipt_request_exact_q": True,
        "receipt_request_sha256_exact_q": True,
        "receipt_status": receipt.get("status"),
        "receipt_returncode": receipt.get("returncode"),
        "request_identity": q_identity,
        "receipt_request_identity": receipt_identity,
        "receipt_top_level_identity": receipt_top_identity,
        "receipt_identity_source": "receipt.request_exact_q",
        "actual_receipt_output_root": str(actual_root),
        "planned_output_root": str(planned_root) if planned_root else "UNKNOWN_NOT_DECLARED_BY_SOURCE_REQUEST",
        "planned_root_matches_receipt": planned_root == actual_root if planned_root else "UNKNOWN_SOURCE_REQUEST_NO_OUTPUT_ROOT",
        "actual_receipt_output_root_authoritative": True,
    }


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    q_path = args.gencase_request.expanduser().resolve()
    receipt_path = args.receipt.expanduser().resolve()
    join = strict_q_receipt_join(q_path, receipt_path)

    # Delegate all source/XML/VTK semantics to the consumed v3 implementation
    # after the strict producer tuple is closed.  No v3 byte is modified.
    report = V3.build_report(args)
    report = dict(report)
    report["schema"] = SCHEMA
    report["status"] = "COMPLETED_F3_S2_INITIAL_SUPPORT_AUDIT_V5"
    report["forward_worker"] = {
        "schema": SCHEMA,
        "delegated_worker_schema": "ds02.stage2.f3.s2.initial-support-audit.v3",
        "strict_q_receipt_join": join,
        "planned_output_root_is_non_authoritative": True,
        "actual_receipt_output_root_used_for_terminal_binding": True,
    }
    report.setdefault("gencase_binding", {})["strict_q_receipt_join"] = join
    report.setdefault("scope", {})["strict_q_receipt_join_before_dynamic_read"] = True
    return report


def write_new(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable F3 v5 report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write((json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    os.replace(temporary, path)


def self_test() -> dict[str, Any]:
    delegated = V3.self_test()
    if delegated.get("status") != "PASS":
        raise AssertionError(delegated)
    with tempfile.TemporaryDirectory(prefix="f3-v5-join-") as tmp:
        root = Path(tmp) / "actual-producer-root"
        root.mkdir()
        q_path = Path(tmp) / "q.json"
        receipt_path = Path(tmp) / "receipt.json"
        q = {
            "schema": REQUEST_SCHEMA,
            "family_id": "F3",
            "sentinel_id": "F3-S2",
            "physical_case_id": PHYSICAL_CASE_ID,
            "case_id": "C",
            "attempt_id": "A",
        }
        q_path.write_text(json.dumps(q, sort_keys=True) + "\n", encoding="utf-8")
        receipt = {"status": "completed", "returncode": 0, "request": q, "request_sha256": sha256(q_path), "output_root": str(root)}
        receipt_path.write_text(json.dumps(receipt, sort_keys=True) + "\n", encoding="utf-8")
        evidence = strict_q_receipt_join(q_path, receipt_path)
        if not evidence["receipt_request_exact_q"] or not evidence["actual_receipt_output_root_authoritative"]:
            raise AssertionError(evidence)
        bad = dict(receipt)
        bad["request_sha256"] = "0" * 64
        receipt_path.write_text(json.dumps(bad, sort_keys=True) + "\n", encoding="utf-8")
        try:
            strict_q_receipt_join(q_path, receipt_path)
        except ValueError:
            pass
        else:
            raise AssertionError("wrong request SHA was accepted")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "delegated_worker_schema": "ds02.stage2.f3.s2.initial-support-audit.v3",
        "strict_q_receipt_join": True,
        "wrong_request_sha_rejected": True,
        "planned_output_root_non_authoritative": True,
        "solver_started": False,
        "bi4_read": False,
        "hdf5_read": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    for name in ("gencase-request", "receipt", "generated-xml", "fluid-vtk", "bound-vtk", "source-xml", "source-control", "support-contract", "output"):
        parser.add_argument(f"--{name}", type=Path)
    parser.add_argument("--expected-generated-xml-sha")
    parser.add_argument("--expected-support-contract-sha")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
        return 0
    required = [args.gencase_request, args.receipt, args.generated_xml, args.fluid_vtk, args.bound_vtk, args.source_xml, args.source_control, args.support_contract, args.output]
    if any(value is None for value in required):
        parser.error("all q/receipt/generated/source/support-contract/output paths are required")
    report = build_report(args)
    write_new(args.output, report)
    print(json.dumps({"status": report["status"], "schema": SCHEMA, "output": str(args.output.resolve()), "strict_q_receipt_join": True}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
