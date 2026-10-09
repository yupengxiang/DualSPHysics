#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build ROOT172 V4 saved-bracket comparison request.

This forward request accepts the legacy ROOT150 proof and the compact
ROOT177/ROOT178 proofs.  The builder reads only small proof/request/receipt/
summary JSON and filesystem metadata for the deferred full reports.  It never
opens or hashes a full report.  The V4 worker performs the full-report read,
SHA and stable pre/post-stat check only after the parent guard reserves the
request.
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
V4_WORKER = Path(__file__).resolve().with_name("stage2_f3_s2_saved_bracket_compare_v4.py")
V2_WORKER = PRIMARY_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f3_s2_saved_bracket_compare_v2.py"
SCHEMA = "ds02.request.v1"
VARIANT = "ds02.stage2.f3-s2.saved-bracket-comparison-request.v4"
FAMILY_ID = "F3"
SENTINEL_ID = "F3-S2"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
QUERY_TIMES_S = (0.0, 2.0, 4.0, 6.0, 8.0)


def _regular(path: Path, label: str) -> Path:
    raw = path.expanduser()
    if raw.is_symlink() or not raw.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {raw}")
    path = raw.resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} resolved target is not regular: {path}")
    return path


def _stat_tuple(path: Path) -> tuple[int, int, int, int, int, int]:
    stat = path.stat()
    return (int(stat.st_size), int(stat.st_mtime_ns), int(stat.st_ctime_ns), int(stat.st_dev), int(stat.st_ino), int(stat.st_mode))


def _stat_dict(value: tuple[int, int, int, int, int, int]) -> dict[str, int]:
    return {"bytes": value[0], "mtime_ns": value[1], "ctime_ns": value[2], "st_dev": value[3], "st_ino": value[4], "mode": value[5]}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_small_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    data = path.read_bytes()
    after = _stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being read: {path}")
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value, {"path": str(path), "bytes": len(data), "sha256": _sha_bytes(data), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True}


def _record_source(path: Path, label: str) -> dict[str, Any]:
    value, record = _read_small_json(path, label)
    del value
    record["label"] = label
    record["content_scope"] = "small_json_hashed_by_builder_and_parent"
    return record


def _record_code(path: Path, label: str) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat_tuple(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _stat_tuple(path)
    if before != after:
        raise RuntimeError(f"{label} changed while being hashed: {path}")
    return {"path": str(path), "bytes": before[0], "sha256": digest.hexdigest(), "stat_before": _stat_dict(before), "stat_after": _stat_dict(after), "stable_read": True, "label": label, "content_scope": "source_code_hashed_by_builder_and_parent"}


def _record_literal_python(path: Path) -> dict[str, Any]:
    raw = path.expanduser()
    if not raw.is_symlink():
        raise ValueError(f"literal interpreter must remain a symlink: {raw}")
    resolved = _regular(raw.resolve(), "resolved interpreter")
    record = _record_code(resolved, "resolved venv interpreter")
    pyvenv = raw.parent.parent / "pyvenv.cfg"
    pyvenv_record = _record_code(pyvenv, "pyvenv.cfg")
    record.update({"literal_path": str(raw), "resolved_path": str(resolved), "literal_is_symlink": True, "pyvenv_cfg": pyvenv_record})
    return record


def _hex(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value.lower()):
        raise ValueError(f"{label} must be a SHA-256")
    return value.lower()


def _check_expected_stat(path: Path, expected: dict[str, Any], label: str) -> dict[str, int]:
    current = _stat_tuple(_regular(path, label))
    observed = _stat_dict(current)
    for key in ("bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino", "mode"):
        if key in expected and int(expected[key]) != int(observed[key]):
            raise ValueError(f"{label} current {key} differs from proof")
    return observed


def _proof_source_binding(proof_path: Path, report_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    proof, proof_record = _read_small_json(proof_path, f"{label} root proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise ValueError(f"{label} is not an actual root proof")
    report_path = _regular(report_path, f"{label} full report")
    top_request = _regular(Path(str(proof.get("request", ""))), f"{label} proof request")
    top_receipt = _regular(Path(str(proof.get("receipt", ""))), f"{label} proof receipt")
    request_record = _record_code(top_request, f"{label} actual audit request")
    receipt_record = _record_code(top_receipt, f"{label} execution receipt")
    if request_record["sha256"] != _hex(proof.get("request_sha256"), f"{label} proof request"):
        raise ValueError(f"{label} proof request SHA differs")
    if receipt_record["sha256"] != _hex(proof.get("receipt_sha256"), f"{label} proof receipt"):
        raise ValueError(f"{label} proof receipt SHA differs")

    case_binding = proof.get("case_binding")
    terminal_record = None
    if isinstance(case_binding, dict) and isinstance(case_binding.get("request_record"), dict):
        item = case_binding["request_record"]
        terminal_record = _record_code(Path(str(item.get("path", ""))), f"{label} terminal solver request")
        if terminal_record["sha256"] != _hex(item.get("sha256"), f"{label} terminal request"):
            raise ValueError(f"{label} terminal request SHA differs")
        if case_binding.get("terminal_request_sha256") not in (None, terminal_record["sha256"]):
            raise ValueError(f"{label} case binding terminal request SHA differs")

    compact = proof.get("full_report_stat_only")
    summary_record = None
    if isinstance(compact, dict):
        if compact.get("stable_read") is not True or compact.get("stat_before") != compact.get("stat_after"):
            raise ValueError(f"{label} compact full-report proof is not stable")
        expected_report = _regular(Path(str(compact.get("path", ""))), f"{label} compact full report")
        if expected_report != report_path:
            raise ValueError(f"{label} compact report path differs")
        expected_report_sha = _hex(compact.get("sha256"), f"{label} compact full report")
        _check_expected_stat(report_path, compact.get("stat_after", {}), f"{label} compact full report")
        summary_path = _regular(Path(str(proof.get("summary", ""))), f"{label} compact summary")
        summary_value, summary_record = _read_small_json(summary_path, f"{label} compact summary")
        del summary_value
        if summary_record["sha256"] != _hex(proof.get("summary_sha256"), f"{label} summary"):
            raise ValueError(f"{label} summary SHA differs")
        if proof.get("summary_bytes") not in (None, summary_record["bytes"]):
            raise ValueError(f"{label} summary byte count differs")
        deferred = {"path": str(report_path), "expected_sha256": expected_report_sha, "estimated_bytes": int(compact.get("bytes", report_path.stat().st_size)), "proof_stat": compact.get("stat_after"), "summary_path": summary_record["path"], "summary_sha256": summary_record["sha256"], "stable_read_required": True, "content_scope": "full report read/hash/parse only by guarded V4 worker"}
    else:
        expected_report = _regular(Path(str(proof.get("report", ""))), f"{label} legacy full report")
        if expected_report != report_path:
            raise ValueError(f"{label} legacy report path differs")
        expected_report_sha = _hex(proof.get("report_sha256"), f"{label} legacy full report")
        if proof.get("report_bytes") not in (None, report_path.stat().st_size):
            raise ValueError(f"{label} legacy report byte count differs")
        deferred = {"path": str(report_path), "expected_sha256": expected_report_sha, "estimated_bytes": int(proof.get("report_bytes", report_path.stat().st_size)), "proof_stat": _stat_dict(_stat_tuple(report_path)), "summary_path": None, "summary_sha256": None, "stable_read_required": True, "content_scope": "legacy full report read/hash/parse only by guarded V4 worker"}

    binding = {
        "label": label,
        "proof": proof_record,
        "request": request_record,
        "receipt": receipt_record,
        "terminal_request": terminal_record,
        "summary": summary_record,
        "deferred_report": deferred,
        "proof_status": proof.get("status"),
        "case_binding": case_binding,
    }
    return proof, binding, deferred


def _canonical(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False, default=str).encode("utf-8")).hexdigest()


def build(args: argparse.Namespace) -> dict[str, Any]:
    reports = {"coarse": args.coarse_report.expanduser().resolve(), "middle": args.middle_report.expanduser().resolve(), "fine": args.fine_report.expanduser().resolve()}
    proofs = {"coarse": args.coarse_proof.expanduser().resolve(), "middle": args.middle_proof.expanduser().resolve(), "fine": args.fine_proof.expanduser().resolve()}
    bindings: dict[str, dict[str, Any]] = {}
    deferred: dict[str, dict[str, Any]] = {}
    proof_objects: dict[str, dict[str, Any]] = {}
    for label in ("coarse", "middle", "fine"):
        proof, binding, record = _proof_source_binding(proofs[label], reports[label], label)
        proof_objects[label] = proof
        bindings[label] = binding
        deferred[label] = record

    worker_record = _record_code(V4_WORKER, "ROOT172 V4 saved-bracket worker")
    dependency_record = _record_code(V2_WORKER, "consumed V2 saved-bracket comparison dependency")
    python_record = _record_literal_python(PYTHON)
    input_records: dict[str, dict[str, Any]] = {
        worker_record["path"]: worker_record,
        dependency_record["path"]: dependency_record,
        python_record["resolved_path"]: python_record,
        python_record["pyvenv_cfg"]["path"]: python_record["pyvenv_cfg"],
    }
    for label in ("coarse", "middle", "fine"):
        binding = bindings[label]
        for key in ("proof", "request", "receipt", "terminal_request", "summary"):
            record = binding.get(key)
            if isinstance(record, dict):
                record = dict(record)
                record["label"] = f"{label} {key} source"
                record["content_scope"] = "small_json_hashed_by_builder_and_parent"
                input_records[record["path"]] = record

    input_files = sorted(input_records)
    input_hashes = {path: input_records[path]["sha256"] for path in input_files}
    command = [str(PYTHON), str(V4_WORKER)]
    for label in ("coarse", "middle", "fine"):
        command += [f"--{label}-report", str(reports[label]), f"--{label}-proof", str(proofs[label])]
    command += ["--query-times", *(repr(value) for value in QUERY_TIMES_S), "--output", "{attempt_root}/comparison/f3_s2_saved_bracket_comparison_v4.json"]
    deferred_bytes = sum(item["estimated_bytes"] for item in deferred.values())
    small_bytes = sum(int(item.get("bytes", 0)) for item in input_records.values())
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": VARIANT,
        "status": "READY_FOR_PARENT_V8_F3_SAVED_BRACKET_COMPARISON_V4",
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
        "input_hashes": input_hashes,
        "input_sha256": input_hashes,
        "input_records": input_records,
        "deferred_input_files": sorted(item["path"] for item in deferred.values()),
        "deferred_input_records": deferred,
        "deferred_input_policy": "full report read/hash/parse only by V4 worker after parent reservation; proof/request/receipt/summary were small-read and SHA/stat joined by builder",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 1800,
        "max_memory_bytes": 8 * 1024**3,
        "estimated_storage_bytes": 64 * 1024**2,
        "estimated_peak_memory_bytes": 8 * 1024**3,
        "estimated_input_read_bytes": small_bytes + deferred_bytes,
        "estimated_small_input_read_bytes": small_bytes,
        "estimated_deferred_full_report_bytes": deferred_bytes,
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
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/comparison/f3_s2_saved_bracket_comparison_v4.json"},
        "source_binding": {
            "schema": VARIANT,
            "proofs": {label: str(proofs[label]) for label in ("coarse", "middle", "fine")},
            "reports": deferred,
            "queries_s": list(QUERY_TIMES_S),
            "saved_endpoint_only": True,
            "interpolation": False,
            "adjacent_grid_truth": False,
            "integration_output_error_bound": "UNKNOWN_NOT_ESTIMATED",
            "compact_proof_support": {"ROOT150": "legacy report/report_sha256", "ROOT177": "full_report_stat_only+summary", "ROOT178": "full_report_stat_only+summary"},
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": "parent-v8-audit",
            "cpu_parent_binding": "required",
            "full_report_read": "only after reservation, one stable bytes read/hash/parse per report",
            "native_payload_read": "forbidden",
            "solver_launch": "forbidden",
        },
        "qualification_stage": "stage2_f3_s2_saved_bracket_report_only_diagnostics_v4",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "actual saved endpoint fields/brackets only; asynchronous time and output/integration error bounds remain UNKNOWN; no neighbouring-grid truth"},
    }
    payload["sha256"] = _canonical(payload)
    return payload


def _source_only_preflight(request_path: Path) -> dict[str, Any]:
    """Validate only small JSON/source/stat edges; never open deferred reports."""

    request, request_record = _read_small_json(request_path, "V4 comparison request")
    if request.get("schema") != SCHEMA or request.get("variant_schema") != VARIANT:
        raise ValueError("request schema/variant mismatch")
    if request.get("sha256") != _canonical(request):
        raise ValueError("request canonical SHA mismatch")
    input_records = request.get("input_records")
    input_hashes = request.get("input_sha256")
    if not isinstance(input_records, dict) or not isinstance(input_hashes, dict):
        raise ValueError("request source input closure is missing")
    small_total = 0
    for path_string, record in input_records.items():
        path = _regular(Path(path_string), "small actionable input")
        observed = _record_code(path, str(record.get("label", "small input")))
        if observed["sha256"] != input_hashes.get(path_string):
            raise ValueError(f"small input SHA differs: {path}")
        small_total += observed["bytes"]
    source_binding = request.get("source_binding")
    deferred = request.get("deferred_input_records")
    if not isinstance(source_binding, dict) or not isinstance(deferred, dict):
        raise ValueError("deferred report closure is missing")
    proofs = source_binding.get("proofs")
    reports = source_binding.get("reports")
    if not isinstance(proofs, dict) or not isinstance(reports, dict):
        raise ValueError("proof/report source binding is missing")
    checked: dict[str, Any] = {}
    for label in ("coarse", "middle", "fine"):
        report_path = Path(str(reports[label]["path"])).expanduser().resolve()
        proof_path = Path(str(proofs[label])).expanduser().resolve()
        _, binding, record = _proof_source_binding(proof_path, report_path, label)
        # _proof_source_binding only stats the full report; it never reads or hashes it.
        if binding["deferred_report"]["expected_sha256"] != deferred[label]["expected_sha256"]:
            raise ValueError(f"{label} deferred full-report SHA differs")
        current = _check_expected_stat(report_path, binding["deferred_report"].get("proof_stat", {}), f"{label} deferred full report")
        checked[label] = {"report_path": str(report_path), "expected_sha256": record["expected_sha256"], "bytes": current["bytes"], "stat": current, "summary_path": record.get("summary_path"), "summary_sha256": record.get("summary_sha256")}
    return {
        "status": "PASS_F3_SAVED_BRACKET_V4_SOURCE_ONLY_PREFLIGHT",
        "request": str(request_record["path"]),
        "request_sha256": request_record["sha256"],
        "input_count": len(input_records),
        "small_json_and_source_bytes_read": small_total,
        "deferred_full_report_bytes_stat_only": sum(int(item["estimated_bytes"]) for item in deferred.values()),
        "deferred_reports": checked,
        "full_report_read_by_builder": False,
        "native_payload_read": False,
        "interpolation": False,
        "truth_credit": False,
        "solver_started": False,
        "ledger_mutated": False,
    }


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
    if not PYTHON.is_symlink() or not V4_WORKER.is_file():
        raise AssertionError("literal/runtime V4 source closure is unavailable")
    return {"status": "PASS", "schema": SCHEMA, "variant_schema": VARIANT, "compact_proof_support": ["ROOT150_legacy", "ROOT177_compact", "ROOT178_compact"], "full_report_read_by_builder": False, "summary_read_by_builder": True, "stable_stat_join": True, "interpolation": False, "truth_credit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-request", action="store_true")
    mode.add_argument("--preflight", action="store_true")
    for label in ("coarse", "middle", "fine"):
        parser.add_argument(f"--{label}-report", type=Path)
        parser.add_argument(f"--{label}-proof", type=Path)
    parser.add_argument("--launch-commit")
    parser.add_argument("--output", type=Path, default=LOCAL_REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/f3-s2-saved-bracket-comparison-v4-root172-001.json")
    parser.add_argument("--case-id", default="F3_S2_SAVED_BRACKET_COMPARISON_ROOT172_V4")
    parser.add_argument("--attempt-id", default="f3-s2-saved-bracket-comparison-root-172-v4-001")
    parser.add_argument("--request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2))
        return 0
    if args.preflight:
        if args.request is None:
            parser.error("--preflight requires --request")
        try:
            print(json.dumps(_source_only_preflight(args.request), ensure_ascii=False, indent=2))
            return 0
        except BaseException as exc:
            print(json.dumps({"status": "FAILED_F3_SAVED_BRACKET_V4_SOURCE_ONLY_PREFLIGHT", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
            return 1
    required = tuple(getattr(args, f"{label}_{suffix}") for label in ("coarse", "middle", "fine") for suffix in ("report", "proof")) + (args.launch_commit,)
    if any(value is None for value in required):
        parser.error("--build-request requires all three report/proof paths and --launch-commit")
    try:
        value = build(args)
        _write_once(args.output, value)
    except BaseException as exc:
        print(json.dumps({"status": "FAILED_F3_SAVED_BRACKET_V4_REQUEST_BUILD", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False))
        return 1
    print(json.dumps({"status": value["status"], "output": str(args.output.expanduser().resolve()), "input_count": len(value["input_files"]), "estimated_deferred_full_report_bytes": value["estimated_deferred_full_report_bytes"], "full_report_read_by_builder": False, "interpolation": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
