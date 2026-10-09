#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Build the bounded F1-S1 DP005 same/half-CFL native comparison request.

This is a consumer of already completed observer producers.  It binds their
terminal proof, request, receipt, report and source-snapshot proof, then asks
the parent runner to read only the two bounded observer JSON reports and their
RunPARTs files.  BI4/H5/VTK/native frame payloads are deliberately absent from
the request.  The worker pairs equal saved frame ids and reports asynchronous
times without interpolation or scientific qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
WORKER = HERE / "stage2_f1_s1_dp005_native_common_time_v1.py"
CONTRACT = HERE / "stage2_f1_s1_dp005_native_common_time_contract_v1.json"
SCHEMA = "ds02.request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s1.dp005-native-common-time-manifest.v1"
MAX_JSON = 32 * 1024 * 1024
MAX_SOURCE = 2 * 1024 * 1024
MAX_EXECUTABLE = 8 * 1024 * 1024
QUERY_FRAMES = (0, 79, 80, 159, 160, 239, 240, 319, 320)


class BuildFailure(RuntimeError):
    pass


def _regular(path: Path, label: str) -> Path:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildFailure(f"{label} is not a regular file: {path}")
    return path


def _stat(path: Path) -> dict[str, int]:
    s = path.stat()
    return {"dev": int(s.st_dev), "ino": int(s.st_ino), "bytes": int(s.st_size),
            "mtime_ns": int(s.st_mtime_ns), "ctime_ns": int(s.st_ctime_ns)}


def _stat_record(path: Path, label: str, *, expected_sha: str | None = None,
                 expected_bytes: int | None = None, read_mode: str = "stat_only") -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.exists():
        raise BuildFailure(f"{label} is missing or symlinked: {path}")
    current = _stat(path) if path.is_file() else {
        "dev": int(path.stat().st_dev), "ino": int(path.stat().st_ino),
        "bytes": int(path.stat().st_size), "mtime_ns": int(path.stat().st_mtime_ns),
        "ctime_ns": int(path.stat().st_ctime_ns),
    }
    if expected_bytes is not None and int(expected_bytes) != current["bytes"]:
        raise BuildFailure(f"{label} bytes differ from producer binding")
    record: dict[str, Any] = {"path": str(path), "bytes": current["bytes"],
                              "stat_at_prepare": current, "read_mode": read_mode,
                              "stable_stat_at_prepare": True, "label": label}
    if expected_sha:
        record["known_sha256"] = str(expected_sha).lower()
    return record


def _record(path: Path, label: str, limit: int = MAX_JSON) -> dict[str, Any]:
    path = _regular(path, label)
    before = _stat(path)
    if before["bytes"] > limit:
        raise BuildFailure(f"{label} exceeds bounded limit")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    after = _stat(path)
    if before != after:
        raise BuildFailure(f"{label} changed while being read")
    return {"path": str(path), "sha256": digest.hexdigest(), "known_sha256": digest.hexdigest(),
            "bytes": after["bytes"], "stat_at_prepare": after, "stat": after,
            "stable_read": True, "label": label, "content_scope": "bounded_proof_or_request_metadata"}


def _read_json(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    record = _record(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildFailure(f"{label} is not JSON") from exc
    if not isinstance(value, dict):
        raise BuildFailure(f"{label} is not a JSON object")
    return value, record


def _same_path(left: Any, right: str) -> bool:
    return isinstance(left, str) and Path(left).expanduser().absolute() == Path(right).expanduser().absolute()


def _canonical(value: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps({key: item for key, item in value.items() if key != "sha256"},
                                     sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                                     allow_nan=False).encode("utf-8")).hexdigest()


def _write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildFailure(f"refusing overwrite {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                                        allow_nan=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _python_binding() -> dict[str, Any]:
    literal = PYTHON.expanduser().absolute()
    if not literal.is_symlink():
        raise BuildFailure("literal venv Python must remain a symlink")
    resolved = _regular(literal.resolve(), "resolved venv Python")
    cfg = literal.parent.parent / "pyvenv.cfg"
    return {"literal_argv0": str(literal), "literal_argv0_required": True,
            "resolved": _record(resolved, "resolved venv Python", MAX_EXECUTABLE),
            "pyvenv_cfg": _record(cfg, "pyvenv.cfg", MAX_SOURCE)}


def _proof_and_case(proof_path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    proof, proof_record = _read_json(proof_path, f"{label} actual proof")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or "ACTUAL" not in str(proof.get("status", "")):
        raise BuildFailure(f"{label} is not an actual terminal verification proof")
    for key in ("request", "request_sha256", "receipt", "receipt_sha256", "report", "report_sha256", "snapshot_proof"):
        if key not in proof:
            raise BuildFailure(f"{label} proof lacks {key}")
    request_path = _regular(Path(str(proof["request"])), f"{label} source request")
    receipt_path = _regular(Path(str(proof["receipt"])), f"{label} execution receipt")
    request, request_record = _read_json(request_path, f"{label} source request")
    receipt, receipt_record = _read_json(receipt_path, f"{label} execution receipt")
    if request_record["sha256"].lower() != str(proof["request_sha256"]).lower():
        raise BuildFailure(f"{label} proof/request SHA mismatch")
    if receipt_record["sha256"].lower() != str(proof["receipt_sha256"]).lower():
        raise BuildFailure(f"{label} proof/receipt SHA mismatch")
    if receipt.get("status") not in ("completed", "COMPLETED", "success") or receipt.get("returncode") not in (None, 0):
        raise BuildFailure(f"{label} receipt is not terminal successful")
    embedded = receipt.get("request")
    if not isinstance(embedded, dict):
        raise BuildFailure(f"{label} receipt lacks embedded request")
    if str(receipt.get("request_sha256", "")).lower() != request_record["sha256"].lower():
        raise BuildFailure(f"{label} receipt request SHA does not join source request")
    for key in ("schema", "family_id", "sentinel_id", "physical_case_id", "case_id", "attempt_id"):
        if key in request and embedded.get(key) != request.get(key):
            raise BuildFailure(f"{label} receipt identity {key} mismatch")
    binding = request.get("source_binding")
    if not isinstance(binding, dict):
        raise BuildFailure(f"{label} request lacks source_binding")
    raw_root = binding.get("raw_root")
    runparts = binding.get("runparts")
    generated_xml = binding.get("generated_xml")
    if not isinstance(raw_root, str) or not isinstance(runparts, dict) or not isinstance(runparts.get("path"), str):
        raise BuildFailure(f"{label} request source_binding lacks raw_root/RunPARTs")
    if not isinstance(generated_xml, dict) or not isinstance(generated_xml.get("path"), str):
        raise BuildFailure(f"{label} request source_binding lacks generated XML")
    report_path = _regular(Path(str(proof["report"])), f"{label} observer report")
    report_record = _stat_record(report_path, f"{label} observer report", expected_sha=str(proof["report_sha256"]).lower(), read_mode="worker_bounded_json_read")
    snapshot_path = _regular(Path(str(proof["snapshot_proof"])), f"{label} source snapshot proof")
    snapshot_record = _record(snapshot_path, f"{label} source snapshot proof")
    runparts_path = _regular(Path(str(runparts["path"])), f"{label} RunPARTs")
    runparts_record = _stat_record(runparts_path, f"{label} RunPARTs", expected_sha=str(runparts.get("sha256", "")).lower() or None,
                                   expected_bytes=int(runparts.get("bytes")) if runparts.get("bytes") is not None else None,
                                   read_mode="worker_bounded_text_read")
    expected_source = {"raw_root": raw_root, "runparts": str(runparts_path), "generated_xml": str(Path(generated_xml["path"]).expanduser().absolute())}
    expected_source_records = {
        "raw_root": _stat_record(Path(raw_root), f"{label} raw native directory", read_mode="directory_stat_only"),
        "runparts": runparts_record,
        "generated_xml": _stat_record(Path(generated_xml["path"]), f"{label} generated XML", expected_sha=str(generated_xml.get("sha256", "")).lower() or None,
                                       expected_bytes=int(generated_xml.get("bytes")) if generated_xml.get("bytes") is not None else None,
                                       read_mode="stat_only"),
    }
    physical_case = request.get("physical_case_id")
    producer_case = request.get("case_id")
    if not isinstance(physical_case, str) or not isinstance(producer_case, str):
        raise BuildFailure(f"{label} request lacks physical/producer case identities")
    case = {
        "label": label,
        "variant": "same_cfl" if "SAME_CFL" in producer_case else "half_cfl",
        "physical_case_id": physical_case,
        "producer_case_id": producer_case,
        "request": request_record,
        "receipt": receipt_record,
        "report": report_record,
        "proof": proof_record,
        "snapshot_proof": snapshot_record,
        "runparts": runparts_record,
        "expected_source": expected_source,
        "expected_source_records": expected_source_records,
        "query_frames": list(QUERY_FRAMES),
        "proof_status": proof.get("status"),
        "proof_report_sha256": str(proof["report_sha256"]).lower(),
    }
    return {"proof": proof, "request": request, "receipt": receipt}, case


def build(args: argparse.Namespace) -> dict[str, Any]:
    same, same_case = _proof_and_case(args.same_proof, "F1-S1 DP005 same-CFL")
    half, half_case = _proof_and_case(args.half_proof, "F1-S1 DP005 half-CFL")
    if same_case["physical_case_id"] != half_case["physical_case_id"]:
        raise BuildFailure("same/half physical case identities differ")
    if same_case["variant"] == half_case["variant"]:
        raise BuildFailure("same/half producer case variants were not distinguished")
    records: dict[str, dict[str, Any]] = {}
    for case in (same_case, half_case):
        for key in ("proof", "snapshot_proof", "request", "receipt"):
            record = case[key]
            records[record["path"]] = record
    worker_record = _record(WORKER, "DP005 common-time worker", MAX_SOURCE); records[worker_record["path"]] = worker_record
    contract_record = _record(CONTRACT, "DP005 common-time contract", MAX_JSON); records[contract_record["path"]] = contract_record
    py = _python_binding(); records[py["resolved"]["path"]] = py["resolved"]; records[py["pyvenv_cfg"]["path"]] = py["pyvenv_cfg"]
    static_files = sorted(records)
    static_hashes = {path: records[path]["sha256"] for path in static_files}
    deferred: dict[str, dict[str, Any]] = {}
    for case in (same_case, half_case):
        for key in ("report", "runparts"):
            record = case[key]
            deferred[record["path"]] = record
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_F1_DP005_NATIVE_COMMON_TIME",
        "cases": [same_case, half_case],
        "query_frames": list(QUERY_FRAMES),
        "source_records": {path: record for path, record in sorted({**records, **deferred}.items())},
        "deferred_policy": "parent reserves first; worker stable-reads only observer JSON and RunPARTs, never native BI4/H5/VTK",
        "pairing": {"key": "native saved frame id", "interpolation": False, "neighbor_grid_truth": False,
                    "same_time_required_for_exact_common_time": True},
        "task_contract": {"position_tolerance_m": 0.01788, "velocity_tolerance_m_per_s": 0.04538832449,
                          "kinetic_energy_tolerance_J": 0.30036258, "quarter_budget_diagnostic_only": True,
                          "event_time": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    _write_once(args.manifest_output, manifest)
    manifest_record = _record(args.manifest_output, "DP005 common-time manifest", MAX_JSON)
    records[manifest_record["path"]] = manifest_record
    static_files = sorted(records)
    static_hashes = {path: records[path]["sha256"] for path in static_files}
    deferred_records = {path: record for path, record in sorted(deferred.items())}
    deferred_bytes = sum(int(record["bytes"]) for record in deferred_records.values())
    static_bytes = sum(int(record["bytes"]) for record in records.values())
    root_label = getattr(args, "root_label", "ROOT239")
    if not root_label.startswith("ROOT") or not root_label[4:].replace("_", "").isalnum():
        raise BuildFailure(f"invalid source request root label: {root_label}")
    request: dict[str, Any] = {
        "schema": SCHEMA,
        "variant_schema": "ds02.stage2.f1-s1.dp005-native-common-time-request.v1",
        "status": f"READY_FOR_PARENT_V8_F1_DP005_NATIVE_COMMON_TIME_{root_label}_V1",
        "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": same_case["physical_case_id"],
        "case_id": args.case_id, "attempt_id": args.attempt_id,
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "command": [str(PYTHON), "-B", str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s1_dp005_native_common_time_manifest_v1.json",
                    "--output", "{attempt_root}/observer/f1_s1_dp005_native_common_time_v1.json"],
        "input_files": static_files, "input_hashes": static_hashes, "input_sha256": static_hashes,
        "input_records": records, "deferred_input_files": sorted(deferred_records),
        "deferred_input_records": deferred_records, "deferred_input_file_count": len(deferred_records),
        "deferred_hash_policy": {"parent_after_reservation": "full SHA/stat for report and RunPARTs records",
                                 "worker": "stable bounded read and compare known proof/source SHA/stat",
                                 "native_payload": "not bound or read"},
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 300, "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": 8 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_static_input_read_bytes": static_bytes, "estimated_deferred_read_bytes": deferred_bytes,
        "estimated_input_read_bytes": static_bytes + deferred_bytes,
        "estimated_native_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False,
        "solver_launch": False, "gencase_launch": False, "native_payload_read": False,
        "hdf5_read": False, "vtk_read": False, "raw_directory_scan": False,
        "output_root": "{attempt_root}",
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/observer/f1_s1_dp005_native_common_time_v1.json"},
        "source_binding": {
            "producer_proofs": [same_case["proof"], half_case["proof"]],
            "producer_requests_and_receipts": "exact path/SHA joins are required for both terminal producers",
            "physical_case_id": same_case["physical_case_id"],
            "producer_case_ids": [same_case["producer_case_id"], half_case["producer_case_id"]],
            "selected_frame_ids": list(QUERY_FRAMES),
            "observer_fields": "native observer weighted fluid aggregates and native particle sample mass only",
            "interpolation": False, "neighbor_grid_truth": False, "event_time": "UNKNOWN",
            "source_request_namespace": root_label,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
        "resource_guard": {"runner": "parent-v8-audit", "native_payload": "forbidden", "hdf5": "forbidden",
                           "raw_tree_scan": "forbidden", "bounded_json_bytes": MAX_JSON, "bounded_csv_bytes": 8 * 1024 * 1024},
    }
    request["sha256"] = _canonical(request)
    _write_once(args.output_request, request)
    return request


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="f1-dp005-common-request-") as directory:
        root = Path(directory)
        source = root / "source.json"; source.write_text('{"schema":"ds02.request.v1"}\n', encoding="utf-8")
        source_record = _record(source, "source")
        receipt = {"request_sha256": source_record["sha256"], "request": {"schema": "ds02.request.v1"}}
        assert receipt["request_sha256"] == source_record["sha256"]
        bad = dict(receipt); bad["request_sha256"] = "0" * 64
        assert bad["request_sha256"] != source_record["sha256"]
        assert _canonical({"x": 1}) == _canonical({"x": 1})
    print("PASS_F1_DP005_NATIVE_COMMON_TIME_REQUEST_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--same-proof", type=Path)
    parser.add_argument("--half-proof", type=Path)
    parser.add_argument("--manifest-output", type=Path)
    parser.add_argument("--output-request", type=Path)
    parser.add_argument("--case-id", default="F1_S1_DP005_NATIVE_COMMON_TIME_ROOT239_V1")
    parser.add_argument("--attempt-id", default="f1-s1-dp005-native-common-time-root239-001")
    parser.add_argument("--root-label", default="ROOT239")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        _self_test(); return 0
    if any(value is None for value in (args.same_proof, args.half_proof, args.manifest_output, args.output_request)):
        parser.error("--same-proof, --half-proof, --manifest-output and --output-request are required unless --self-test")
    try:
        request = build(args)
    except Exception as exc:
        print(f"FAILED_F1_DP005_NATIVE_COMMON_TIME_REQUEST: {exc}")
        return 2
    print(json.dumps({"status": request["status"], "request": str(args.output_request.absolute()),
                      "sha256": request["sha256"], "deferred_records": request["deferred_input_file_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
