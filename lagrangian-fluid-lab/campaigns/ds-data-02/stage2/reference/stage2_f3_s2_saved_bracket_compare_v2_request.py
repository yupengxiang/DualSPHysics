#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build a parent-guard request for the F3 three-grid saved-bracket report.

The three observer JSON reports are deferred inputs.  In particular, the
ROOT150 coarse report is a large JSON sidecar and is never opened or hashed by
this builder.  The parent worker performs the stable read and report/proof
SHA join after reservation.  Only the small verification proofs and source
code are hashed while building this request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.saved-bracket-comparison-request.v2"
WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_saved_bracket_compare_v2.py"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with _regular(path, "hash input").open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _record(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha256(path),
        "content_scope": "small_proof_or_source_hashed_by_builder_and_parent_v8",
    }


def _record_literal(path: Path, label: str) -> dict[str, Any]:
    path = path.expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    resolved = path.resolve()
    if not resolved.is_file() or resolved.is_symlink():
        raise FileNotFoundError(f"{label} resolved target: {resolved}")
    pyvenv = path.parent.parent / "pyvenv.cfg"
    if not pyvenv.is_file() or pyvenv.is_symlink():
        raise FileNotFoundError(f"{label} has no stable pyvenv.cfg: {pyvenv}")
    stat = resolved.stat()
    return {
        "path": str(path),
        "resolved_path": str(resolved),
        "label": label,
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha256(resolved),
        "resolved_sha256": _sha256(resolved),
        "pyvenv_cfg_path": str(pyvenv),
        "pyvenv_cfg_sha256": _sha256(pyvenv),
        "content_scope": "literal_venv_interpreter_path_with_resolved_binary_and_pyvenv_binding",
    }


def _load_small(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(_regular(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _proof_binding(proof_path: Path, report_path: Path, expected_report_sha: str, label: str) -> dict[str, Any]:
    proof = _load_small(proof_path, f"{label} proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1":
        raise ValueError(f"{label} proof schema mismatch")
    if "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} proof is not an actual verification")
    bound_report = proof.get("report")
    if bound_report is None or Path(str(bound_report)).expanduser().resolve() != report_path.expanduser().resolve():
        raise ValueError(f"{label} proof report path mismatch")
    if proof.get("report_sha256") != expected_report_sha:
        raise ValueError(f"{label} proof report SHA differs from the supplied deferred SHA")
    return proof


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    report_paths = {
        "coarse": args.coarse_report.expanduser().resolve(),
        "middle": args.middle_report.expanduser().resolve(),
        "fine": args.fine_report.expanduser().resolve(),
    }
    proof_paths = {
        "coarse": args.coarse_proof.expanduser().resolve(),
        "middle": args.middle_proof.expanduser().resolve(),
        "fine": args.fine_proof.expanduser().resolve(),
    }
    expected_sha = {"coarse": args.coarse_report_sha256, "middle": args.middle_report_sha256, "fine": args.fine_report_sha256}
    for label in ("coarse", "middle", "fine"):
        if len(expected_sha[label]) != 64 or any(char not in "0123456789abcdef" for char in expected_sha[label].lower()):
            raise ValueError(f"{label} deferred report SHA must be a 64-character hexadecimal string")
        _proof_binding(proof_paths[label], report_paths[label], expected_sha[label], label)
    worker = WORKER if WORKER.is_file() and not WORKER.is_symlink() else LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_saved_bracket_compare_v2.py"
    records: dict[str, dict[str, Any]] = {
        str(worker.resolve()): _record(worker, "F3 saved-bracket comparison worker"),
        str(PYTHON): _record_literal(PYTHON, "literal venv interpreter"),
    }
    for label, path in proof_paths.items():
        records[str(path)] = _record(path, f"F3 {label} verification proof")
    proofs = {label: str(path) for label, path in proof_paths.items()}
    command = [
        str(PYTHON), str(worker.resolve()),
        "--coarse-report", str(report_paths["coarse"]), "--coarse-proof", proofs["coarse"],
        "--middle-report", str(report_paths["middle"]), "--middle-proof", proofs["middle"],
        "--fine-report", str(report_paths["fine"]), "--fine-proof", proofs["fine"],
        "--query-times", *(repr(value) for value in QUERY_TIMES_S),
        "--output", "{attempt_root}/comparison/f3_s2_saved_bracket_comparison_v2.json",
    ]
    input_files = sorted(records)
    hashes = {path: records[path]["sha256"] for path in input_files}
    deferred_records = {
        label: {
            "path": str(report_paths[label]),
            "expected_sha256": expected_sha[label],
            "estimated_bytes": int(getattr(args, f"estimated_{label}_bytes")),
            "content_scope": "observer JSON read and full SHA/stat checked by worker only after parent reservation",
            "native_payload_read": False,
        }
        for label in ("coarse", "middle", "fine")
    }
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_SAVED_BRACKET_COMPARISON",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "family_id": FAMILY_ID,
        "sentinel_id": SENTINEL_ID,
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": args.case_id,
        "attempt_id": args.attempt_id,
        "launch_commit": args.launch_commit,
        "cwd": str(PRIMARY_REPO / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY_REPO),
        "command": command,
        "input_files": input_files,
        "input_hashes": hashes,
        "input_sha256": hashes,
        "input_records": records,
        "deferred_input_files": sorted(report_paths.values(), key=str),
        "deferred_input_records": deferred_records,
        "deferred_input_policy": "worker reads each observer JSON only after parent reservation, verifies report SHA against its proof and stable pre/post stat, then compares actual saved endpoints",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 768 * 1024**2,
        "estimated_storage_bytes": 32 * 1024**2,
        "estimated_peak_memory_bytes": 128 * 1024**2,
        "estimated_input_read_bytes": sum(item["bytes"] for item in records.values()) + sum(item["estimated_bytes"] for item in deferred_records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": False,
        "solver_launch": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f3_s2_saved_bracket_comparison_v2.json"},
        "source_binding": {
            "schema": VARIANT,
            "reports": {label: {"path": str(report_paths[label]), "expected_sha256": expected_sha[label]} for label in ("coarse", "middle", "fine")},
            "proofs": proofs,
            "queries_s": list(QUERY_TIMES_S),
            "saved_endpoint_only": True,
            "interpolation": False,
            "adjacent_grid_truth": False,
            "integration_output_error_bound": "UNKNOWN_NOT_ESTIMATED",
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "cpu_parent_binding": "required",
            "payload_read": "JSON observer reports only after reservation",
            "solver_launch": "forbidden",
        },
        "qualification_stage": "stage2_f3_s2_saved_bracket_report_only_diagnostics_v2",
        "scientific_qualification": {
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "reason": "actual saved endpoint fields only; asynchronous run differences are not time/output error bounds or spatial truth",
        },
    }
    payload["sha256"] = _canonical(payload)
    return payload


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    if not str(PYTHON).endswith("/.venv/bin/python"):
        raise AssertionError("literal venv binding changed")
    return {
        "status": "PASS",
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "deferred_report_sha_required": True,
        "root150_large_report_read_by_builder": False,
        "native_payload_read": False,
        "interpolation": False,
        "truth_credit": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    parser.add_argument("--coarse-report", type=Path)
    parser.add_argument("--coarse-proof", type=Path)
    parser.add_argument("--coarse-report-sha256")
    parser.add_argument("--estimated-coarse-bytes", type=int)
    parser.add_argument("--middle-report", type=Path)
    parser.add_argument("--middle-proof", type=Path)
    parser.add_argument("--middle-report-sha256")
    parser.add_argument("--estimated-middle-bytes", type=int)
    parser.add_argument("--fine-report", type=Path)
    parser.add_argument("--fine-proof", type=Path)
    parser.add_argument("--fine-report-sha256")
    parser.add_argument("--estimated-fine-bytes", type=int)
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-saved-bracket-comparison-v2-root172-001.json")
    parser.add_argument("--case-id", default="F3_S2_SAVED_BRACKET_COMPARISON_ROOT172")
    parser.add_argument("--attempt-id", default="f3-s2-saved-bracket-comparison-root-172-001")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    required = (
        args.coarse_report, args.coarse_proof, args.coarse_report_sha256, args.estimated_coarse_bytes,
        args.middle_report, args.middle_proof, args.middle_report_sha256, args.estimated_middle_bytes,
        args.fine_report, args.fine_proof, args.fine_report_sha256, args.estimated_fine_bytes,
        args.launch_commit,
    )
    if any(value is None for value in required):
        parser.error("--build-request requires all three deferred report/proof paths, SHA/size estimates, and --launch-commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_SAVED_BRACKET_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False), flush=True)
        return 1
    print(json.dumps({"status": value["status"], "output": str(args.output.expanduser().resolve()), "native_payload_read": False, "interpolation": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
