#!/usr/bin/env python3
"""Prepare the source-bound ROOT225 nearest-native-endpoint audit.

The builder reads only ROOT223/ROOT207 compact JSON, generated XML, solver
receipts, and RunPARTs CSVs.  It never opens, stats, or hashes a production
Part_*.bi4 file.  Native Part paths are deferred records whose SHA/stat are
obtained by the parent-reserved worker immediately before and after decoding.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
import os
from typing import Any
import xml.etree.ElementTree as ET


HERE = Path(__file__).resolve().parent
WORKER = HERE / "stage2_f1_s2_query_endpoint_observer_v1.py"
CONTRACT = HERE / "stage2_f1_s2_query_endpoint_contract_v1.json"
V1_WORKER = HERE / "stage2_f1_native_selected_observer_v1.py"
BASE_OBSERVER = HERE / "stage2_native_physical_observer_v2.py"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
PROJECT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
ROOT223_PROOF = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/F1_S2_COMPONENT_COMPARE_V1_ACTUAL_ROOT_VERIFICATION_223.json")
ROOT223_SHA = "23f79366541c609e3cfb42c99ec0419ddf4fecca63aaf9d5c12c9ecbc22a9b84"
ROOT207_SHA = "c2016d5a36922230eafc57c49baadaeff3a2bc920bb953b5fef215eb9fda30ab"
ROOT207_CHILD_SHA = "d588f17021c3b1418ac73e343d6c323f2d8850d2be1148d39bba7243ce101fb2"
ROOT217_SHA = "7df9b02c339e3b3eb8bae8f108c16d5db0fd2b6cb3f03d192c4edc827ae1bdf0"
REQUEST_SCHEMA = "ds02.request.v1"
VARIANT_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-request.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.query-endpoint-manifest.v1"
MAX_BYTES = 16 * 1024 * 1024


class BuildError(RuntimeError):
    pass


def stable_hash(path: Path, label: str, *, max_bytes: int = MAX_BYTES) -> dict[str, Any]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise BuildError(f"{label} is not a regular non-symlink file: {path}")
    before = path.stat()
    if before.st_size > max_bytes:
        raise BuildError(f"{label} exceeds bounded metadata read: {path}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    after = path.stat()
    before_tuple = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_tuple = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_tuple != after_tuple:
        raise BuildError(f"{label} changed while being read: {path}")
    return {
        "path": str(path),
        "label": label,
        "bytes": int(after.st_size),
        "sha256": digest,
        "stat": {"dev": int(after.st_dev), "ino": int(after.st_ino), "mtime_ns": int(after.st_mtime_ns), "ctime_ns": int(after.st_ctime_ns)},
    }


def read_json(path: Path, label: str, expected_sha: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    record = stable_hash(path, label)
    if expected_sha is not None and record["sha256"] != expected_sha:
        raise BuildError(f"{label} SHA mismatch: {record['sha256']} != {expected_sha}")
    try:
        value = json.loads(Path(record["path"]).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"{label} root is not an object")
    return value, record


def parse_runparts(path: Path) -> list[dict[str, Any]]:
    path = path.expanduser().absolute()
    rows: list[dict[str, Any]] = []
    header: list[str] | None = None
    with path.open(encoding="utf-8") as stream:
        for raw in stream:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("Part;"):
                header = line.split(";")
                continue
            if header is None:
                continue
            values = line.split(";")
            if len(values) != len(header):
                continue
            row = dict(zip(header, values))
            try:
                part = int(row["Part"])
                time_s = float(row["TimeStep [s]"].replace(",", ""))
            except (KeyError, ValueError):
                continue
            rows.append({"frame": part, "time_s": time_s})
    if not rows or any(right["time_s"] <= left["time_s"] for left, right in zip(rows, rows[1:])):
        raise BuildError(f"RunPARTs has no strictly increasing actual rows: {path}")
    return rows


def nearest(rows: list[dict[str, Any]], query: float) -> tuple[dict[str, Any], dict[str, Any]]:
    lower = [row for row in rows if row["time_s"] <= query]
    upper = [row for row in rows if row["time_s"] >= query]
    if not lower or not upper:
        raise BuildError(f"query {query} is outside RunPARTs window")
    return max(lower, key=lambda row: row["time_s"]), min(upper, key=lambda row: row["time_s"])


def xml_timeout(path: Path) -> str | None:
    root = ET.fromstring(path.read_bytes())
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] == "parameter" and node.get("key") == "TimeOut":
            return node.get("value")
    return None


def command_tout(command: Any) -> str | None:
    if not isinstance(command, list):
        return None
    for item in command:
        if isinstance(item, str) and item.startswith("-tout:"):
            return item.split(":", 1)[1]
    return None


def write_once(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise BuildError(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temp.replace(path)


def build(output_manifest: Path, output_request: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    contract, contract_rec = read_json(CONTRACT, "endpoint contract")
    if contract.get("schema") != "ds02.stage2.f1-s2.query-endpoint-contract.v1":
        raise BuildError("endpoint contract schema mismatch")
    proof, proof_rec = read_json(ROOT223_PROOF, "ROOT223 proof", ROOT223_SHA)
    if proof.get("status") != "VERIFIED_ACTUAL_F1_S2_THREE_GRID_SELECTED_COMPONENT_DIAGNOSTICS_ONLY":
        raise BuildError("ROOT223 proof status mismatch")
    report_path = Path(proof["report"])
    report, report_rec = read_json(report_path, "ROOT223 compact report", proof.get("report_sha256"))
    if report.get("schema") != "ds02.stage2.f1-s2.component-space-compare.v1":
        raise BuildError("ROOT223 report schema mismatch")
    producer = proof.get("source_producer_proof", {})
    if producer.get("sha256") != ROOT207_SHA:
        raise BuildError("ROOT223 does not bind ROOT207 proof")
    child_binding = proof.get("actual_native_child_report", {})
    if child_binding.get("sha256") != ROOT207_CHILD_SHA:
        raise BuildError("ROOT223 does not bind ROOT207 child report")
    child, child_rec = read_json(Path(child_binding["path"]), "ROOT207 child report", ROOT207_CHILD_SHA)
    if child.get("schema") != "ds02.stage2.f1.native-selected-observer.v1":
        raise BuildError("ROOT207 child schema mismatch")
    cases = {case.get("label"): case for case in child.get("cases", []) if isinstance(case, dict)}
    selected = {
        "coarse": "F1_S2_DP0225_COARSE",
        "medium": "F1_S2_DP020_MEDIUM",
        "fine": "F1_S2_DP017_FINE",
    }
    grid_records: list[dict[str, Any]] = []
    deferred: list[dict[str, Any]] = []
    static: list[dict[str, Any]] = [
        stable_hash(WORKER, "ROOT225 endpoint worker"),
        stable_hash(CONTRACT, "ROOT225 endpoint contract"),
        stable_hash(V1_WORKER, "calibrated V1 native observer worker"),
        stable_hash(BASE_OBSERVER, "calibrated native physical observer"),
        proof_rec,
        report_rec,
        child_rec,
    ]
    for label, case_label in selected.items():
        case = cases.get(case_label)
        if case is None:
            raise BuildError(f"ROOT207 child lacks {case_label}")
        source = case.get("source", {})
        raw_root = Path(source["raw_root"])
        runparts_path = Path(source["runparts"]["path"])
        generated_xml = Path(source["generated_xml"]["path"])
        decoder = Path(source["decoder"]["path"])
        decoder_source = Path(source["decoder_source"]["path"])
        receipt_path = runparts_path.parents[1] / "execution-receipt.json"
        receipt, receipt_rec = read_json(receipt_path, f"{label} solver receipt")
        runparts_rec = stable_hash(runparts_path, f"{label} RunPARTs")
        xml_rec = stable_hash(generated_xml, f"{label} generated XML")
        decoder_rec = stable_hash(decoder, f"{label} official decoder")
        decoder_source_rec = stable_hash(decoder_source, f"{label} decoder source")
        rows = parse_runparts(runparts_path)
        lower, upper = nearest(rows, 1.0)
        request = receipt.get("request", {})
        if receipt.get("status") != "completed" or receipt.get("returncode") not in (0, "0"):
            raise BuildError(f"{label} solver receipt is not completed/0")
        # The coarse/fine Stage2 requests carry the F1-S2 physical identity
        # directly.  The pre-existing medium run is the older runner-v2
        # request and carries only its F1 case id; accepting it by a generic
        # missing-field fallback would allow an unrelated receipt, so bind
        # its exact historical case explicitly.
        if label in {"coarse", "fine"}:
            if request.get("sentinel_id") != "F1-S2" or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1":
                raise BuildError(f"{label} solver receipt identity mismatch")
            receipt_identity_status = "REQUEST_V1_F1_S2_PHYSICAL_IDENTITY"
        else:
            if (
                request.get("family_id") != "F1"
                or request.get("case_id") != "F1_STAGE1_DUAL_H340_DP020"
                or request.get("sentinel_id") is not None
                or request.get("physical_case_id") != "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1"
            ):
                raise BuildError(f"{label} historical runner-v2 solver receipt identity mismatch")
            receipt_identity_status = "HISTORICAL_RUNNER_V2_EXACT_F1_CASE_ID_PHYSICAL_IDENTITY_ABSENT"
        tout = command_tout(request.get("command"))
        xml_tout = xml_timeout(generated_xml)
        if tout is None or xml_tout is None:
            raise BuildError(f"{label} actual/xml TimeOut is unavailable")
        grid = {
            "label": label,
            "case_label": case_label,
            "identity": case["identity"],
            "raw_root": str(raw_root),
            "runparts": runparts_rec,
            "generated_xml": xml_rec,
            "solver_receipt": receipt_rec,
            "decoder": decoder_rec,
            "decoder_source": decoder_source_rec,
            "expected_frame_count": len(rows),
            "first_frame": rows[0],
            "last_frame": rows[-1],
            "query_time_s": 1.0,
            "lower": lower,
            "upper": upper,
            "xml_TimeOut_s": float(xml_tout),
            "actual_request_tout_s": float(tout),
            "actual_request_command": request.get("command"),
            "actual_request_sha256": receipt.get("request_sha256"),
            "receipt_identity_status": receipt_identity_status,
            "run_txt_present": (runparts_path.parents[1] / "Run.txt").is_file(),
            "run_out_present": (runparts_path.parents[1] / "Run.out").is_file(),
            "control_status": "RUNTIME_OVERRIDE_VERIFIED_FROM_COMPLETED_RECEIPT" if float(tout) != float(xml_tout) else "RECEIPT_TIME_OUT_MATCHES_GENERATED_XML",
            "native_sha_policy": "PARENT_AFTER_RESERVATION_PRE_AND_POST_SHA_STAT",
        }
        grid_records.append(grid)
        for frame_name, endpoint in (("lower", lower), ("upper", upper)):
            part = raw_root / f"Part_{int(endpoint['frame']):04d}.bi4"
            deferred.append({
                "path": str(part),
                "grid": label,
                "endpoint": frame_name,
                "frame": int(endpoint["frame"]),
                "expected_time_s": endpoint["time_s"],
                "sha256": "PARENT_AFTER_RESERVATION",
                "stat_at_prepare": "UNKNOWN_UNTIL_PARENT_RESERVATION",
                "worker_owned_after_reservation": True,
            })
        static.extend([receipt_rec, runparts_rec, xml_rec, decoder_rec, decoder_source_rec])
    # Deduplicate static records while preserving the first record.
    unique: dict[str, dict[str, Any]] = {item["path"]: item for item in static}
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_NOT_RUN_ROOT225_SOURCE_AND_ENDPOINT_AUDIT",
        "sentinel_id": "F1-S2",
        "family_id": "F1",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "query": contract["query"],
        "contract": {"path": str(CONTRACT), "sha256": contract_rec["sha256"]},
        "root223": {"path": str(ROOT223_PROOF), "sha256": ROOT223_SHA, "report": report_rec, "root207_child": child_rec},
        "root217": {"path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/OFFICIAL_WRITER_CALIBRATION_V4_ACTUAL_ROOT_VERIFICATION_217.json", "sha256": ROOT217_SHA},
        "grids": grid_records,
        "deferred_native_records": deferred,
        "static_source_records": list(unique.values()),
        "read_scope": contract["read_scope"],
        "qualification": contract["qualification"],
    }
    # The request is built after the manifest so its SHA can be input-bound.
    manifest_path = output_manifest.expanduser().absolute()
    request_path = output_request.expanduser().absolute()
    write_once(manifest_path, manifest)
    manifest_rec = stable_hash(manifest_path, "ROOT225 manifest")
    input_records = list(unique.values()) + [manifest_rec]
    request = {
        "schema": REQUEST_SCHEMA,
        "variant_schema": VARIANT_SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED",
        "kind": "audit",
        "cpu_task_kind": "audit",
        "request_id": "f1-s2-query-endpoint-audit-root225-001",
        "family_id": "F1",
        "sentinel_id": "F1-S2",
        "physical_case_id": "F1_DUAL_HEAD_340_UNCHANGED_MOTHER_GEOMETRY_V1",
        "case_id": "F1_S2_QUERY_ENDPOINT_AUDIT_ROOT225",
        "attempt_id": "f1-s2-query-endpoint-audit-root225-001",
        "command": [str(PYTHON), str(WORKER), "--manifest", "{attempt_root}/inputs/f1_s2_query_endpoint_manifest_v1.json", "--attempt-root", "{attempt_root}", "--output", "{attempt_root}/observer/f1_s2_query_endpoint_observer_v1.json"],
        "input_files": sorted(record["path"] for record in input_records),
        "input_sha256": {record["path"]: record["sha256"] for record in input_records},
        "deferred_input_records": deferred,
        "resources": {"gpu": False, "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 1800, "memory_max_bytes": 2 * 1024 * 1024 * 1024, "external_storage_max_bytes": 512 * 1024 * 1024, "home_storage_max_bytes": 64 * 1024 * 1024, "log_max_bytes": 512 * 1024, "parent_guard_required": True},
        "storage_scope": {"output_root": "{attempt_root}", "native_payload_read": "six deferred Part files only", "h5_vtk_allowed": False, "full_native_tree_scan": False},
        "source_binding": {"manifest": str(manifest_path), "root223_proof": {"path": str(ROOT223_PROOF), "sha256": ROOT223_SHA}, "root207_child_report": {"path": str(child_binding["path"]), "sha256": ROOT207_CHILD_SHA}, "root217_calibration_proof": {"path": manifest["root217"]["path"], "sha256": ROOT217_SHA}, "actual_time_query_s": 1.0, "interpolation": "FORBIDDEN", "neighbor_grid_truth": False},
        "scope": {"actual_control_override_verified_from_receipt": True, "one_query_time_s": [1.0], "nearest_lower_upper_native_frames": True, "science_Q": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "credit": 0}},
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "native_payload_read": False,
        "hdf5_read": False,
        "ledger_mutation": False,
        "qualification_credit": 0,
    }
    write_once(request_path, request)
    return manifest, request


def self_test() -> None:
    rows = [{"frame": 0, "time_s": 0.0}, {"frame": 199, "time_s": 0.995}, {"frame": 200, "time_s": 1.0001}]
    lower, upper = nearest(rows, 1.0)
    assert lower["frame"] == 199 and upper["frame"] == 200
    assert command_tout(["solver", "-tout:0.005"]) == "0.005"
    print("PASS_F1_S2_QUERY_ENDPOINT_REQUEST_V1_SELFTEST")


def main() -> int:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output-manifest", type=Path)
    parser.add_argument("--output-request", type=Path)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if args.output_manifest is None or args.output_request is None:
        parser.error("--output-manifest and --output-request are required with --build")
    try:
        build(args.output_manifest, args.output_request)
    except (BuildError, OSError, ValueError, KeyError) as exc:
        print(f"FAIL_F1_S2_QUERY_ENDPOINT_REQUEST: {exc}")
        return 2
    print(f"PASS_PREPARED_F1_S2_QUERY_ENDPOINT {args.output_manifest} {args.output_request}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
