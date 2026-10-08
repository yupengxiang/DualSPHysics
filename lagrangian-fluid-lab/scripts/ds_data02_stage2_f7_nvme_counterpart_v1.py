#!/usr/bin/env python3
"""Prepare F7-S2 12-second NVMe counterpart requests.

The same-CFL request is a parent-scheduled v3 external-solver request bound to
CURRENT row 290 (F7_OBSTACLE_QUINTIC_B08_A065), its actual generated input,
motion sources, solver receipt, and producer-declared trajectory SHA.  The
builder performs stat-only checks for the HDF5 trajectory and never hashes or
opens it.  The half-CFL counterpart is intentionally a planning request with
``launch_allowed=false``: no F7 half-CFL Def/GenCase/source receipt is present
in CURRENT, so a change to the existing cfl=0.2 file must not be silently
treated as a half-CFL experiment.

Both variants preserve the native 12-second window and 0.02-second save
cadence.  The historical F7 C60 seven-second timeout is referenced only as a
failed/partial predecessor and contributes no cropped scientific credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import os
import sys
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN = ROOT / "campaigns" / "ds-data-02"
CURRENT = CAMPAIGN / "stage2" / "CURRENT336.json"
V3_RUNNER = ROOT / "scripts" / "ds_data02_stage2_external_solver_v3.py"
V1_RUNNER = ROOT / "scripts" / "ds_data02_stage2_external_solver_v1.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.f7-nvme-counterpart-request.v1"
HALF_SCHEMA = "ds02.stage2.f7-nvme-half-cfl-plan.v1"


class CounterpartError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def load_json(path: Path | str) -> dict[str, Any]:
    value = json.loads(Path(path).expanduser().resolve().read_text())
    if not isinstance(value, dict):
        raise CounterpartError(f"JSON object required: {path}")
    return value


def write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise CounterpartError(f"refusing to overwrite request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _case(catalog: Mapping[str, Any], case_id: str) -> tuple[int, dict[str, Any]]:
    values = catalog.get("cases")
    if not isinstance(values, list):
        raise CounterpartError("CURRENT cases list is missing")
    for index, value in enumerate(values):
        if isinstance(value, dict) and value.get("physical_case_id") == case_id:
            return index, value
    raise CounterpartError(f"CURRENT case is missing: {case_id}")


def _source_paths(row: Mapping[str, Any], solver_receipt: Mapping[str, Any]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    def add(value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        path = Path(value).expanduser().resolve()
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)
    add(CURRENT)
    add(row.get("trajectory", {}).get("path"))
    add(row.get("manifest", {}).get("path"))
    add(row.get("xmf", {}).get("path"))
    for item in row.get("source_bindings", {}).values():
        if isinstance(item, Mapping):
            add(item.get("path"))
    request = solver_receipt.get("request", {})
    for value in request.get("input_files", []):
        add(value)
    add(request.get("gencase_prefix"))
    # The generated prefix is not a file; remove it after the source closure
    # has been collected.  The exact binary and prepared files are in
    # request.input_files and remain bound.
    result = [path for path in result if path.is_file()]
    trajectory = Path(str(row.get("trajectory", {}).get("path", ""))).expanduser().resolve()
    if not trajectory.is_file():
        raise CounterpartError(f"trajectory is unavailable (stat-only required): {trajectory}")
    if int(row.get("trajectory", {}).get("bytes", 0)) <= 0:
        raise CounterpartError("trajectory producer byte count is missing")
    return result


def _input_hashes(paths: Sequence[Path], row: Mapping[str, Any], solver_receipt: Mapping[str, Any]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    values: list[str] = []
    hashes: dict[str, str] = {}
    scopes: dict[str, str] = {}
    producer_sha = str(row.get("trajectory", {}).get("producer_declared_sha256", ""))
    trajectory = str(Path(str(row.get("trajectory", {}).get("path", ""))).expanduser().resolve())
    receipt_hashes = solver_receipt.get("input_hashes_at_launch", {})
    for path in paths:
        key = str(path)
        values.append(key)
        if key == trajectory:
            if len(producer_sha) != 64:
                raise CounterpartError("trajectory has no producer-declared SHA")
            hashes[key] = producer_sha
            scopes[key] = "post_reservation_hash_producer_declared_pending_recompute"
        elif isinstance(receipt_hashes, Mapping) and isinstance(receipt_hashes.get(key), str) and len(receipt_hashes[key]) == 64:
            # The producer receipt is the immutable source hash evidence.  Do
            # not reread a prepared BI4 or other multi-GB source merely to
            # recreate a hash already bound by the native launch receipt.
            hashes[key] = str(receipt_hashes[key])
            scopes[key] = "post_reservation_hash_receipt_declared_pending_recompute"
        else:
            if path.stat().st_size > 64 * 1024 * 1024:
                raise CounterpartError(f"large source lacks producer hash evidence: {path}")
            hashes[key] = sha256_file(path)
            scopes[key] = "post_reservation_hash"
    return values, hashes, scopes


def _ledger_binding() -> dict[str, Any]:
    if not LEDGER.is_file():
        raise CounterpartError(f"parent ledger is missing: {LEDGER}")
    ledger = load_json(LEDGER)
    limits = ledger.get("limits", {})
    return {"ledger_path": str(LEDGER), "data_root": str(LEDGER.parent.parent),
            "campaign_id": ledger.get("campaign_id"), "deadline_utc": ledger.get("deadline_utc"),
            "ledger_reset": False, "no_new_data_root": True,
            "limits": {key: limits.get(key) for key in ("cpu_core_seconds", "gpu_seconds",
                                                          "new_storage_bytes", "home_min_free_bytes",
                                                          "home_path", "storage_policy")}}


def build_same_cfl(case_id: str = "F7_OBSTACLE_QUINTIC_B08_A065", *, output_root: Path | str | None = None) -> dict[str, Any]:
    catalog = load_json(CURRENT)
    index, row = _case(catalog, case_id)
    receipt_path = Path(str(row["source_bindings"]["solver_receipt"]["path"])).expanduser().resolve()
    receipt = load_json(receipt_path)
    command = list(receipt.get("command", []))
    if not command:
        raise CounterpartError("solver receipt command is missing")
    command = [str(value).replace(str(Path(str(receipt.get("output_root", ""))).expanduser().resolve()), "{output_root}")
               for value in command]
    if "-tmax:12" not in command or "-tout:0.02" not in command:
        raise CounterpartError("F7-S2 command is not the bound 12-second/0.02-second command")
    paths = _source_paths(row, receipt)
    input_files, input_sha256, input_scopes = _input_hashes(paths, row, receipt)
    case_token = case_id.lower().replace("_", "-")
    attempt_id = "f7-s2-a065-same-cfl-nvme-v3-001"
    if output_root is None:
        output_root = EXTERNAL_ROOT / "F7" / "F7_S2_NVME_COUNTERPART_V3" / attempt_id
    output_root = Path(output_root).expanduser().resolve()
    if output_root.exists():
        raise CounterpartError(f"new external output namespace already exists: {output_root}")
    cwd = Path(str(receipt.get("request", {}).get("cwd", ""))).expanduser().resolve()
    if not cwd.is_dir():
        raise CounterpartError(f"solver cwd is unavailable: {cwd}")
    ledger_binding = _ledger_binding()
    request: dict[str, Any] = {
        "schema": "ds02.stage2.external-solver-request.v3",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": case_token, "attempt_id": attempt_id,
        "kind": "qualification", "command": command, "cwd": str(cwd),
        "max_wall_seconds": 3600.0, "cpu_threads": int(receipt.get("request", {}).get("cpu_threads", 4)),
        "estimated_peak_gpu_mib": int(receipt.get("request", {}).get("estimated_peak_gpu_mib", 4096)),
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "runtime_binding": {"path": str(RUNTIME), "sha256": sha256_file(RUNTIME), "role": "shared_runtime_v2"},
        "v1_runner_binding": {"path": str(V1_RUNNER), "sha256": sha256_file(V1_RUNNER)},
        "parent_resource_binding": ledger_binding,
        "storage_scope": {"external_filesystem": str(EXTERNAL_ROOT), "output_root": str(output_root),
                          "external_product_reserved_bytes": 6 * 1024 ** 3,
                          "home_receipt_reserved_bytes": 4 * 1024 ** 2,
                          "new_storage_bytes": 6 * 1024 ** 3 + 4 * 1024 ** 2,
                          "home_min_free_bytes": int(ledger_binding["limits"].get("home_min_free_bytes") or 1),
                          "external_min_free_bytes": 1},
        "gpu": {"required": True, "gpu_uuid": None,
                "lease_root": str(Path(ledger_binding["data_root"]) / "leases")},
        "input_files": input_files, "input_sha256": input_sha256,
        "input_content_scope": input_scopes,
        "execution": {"manufactured_only": False, "scientific_status": "DEVELOPMENT_SOURCE_BOUND",
                       "native_raw_hdf5_open": False, "native_bi4_open": True},
        "v1_runner_binding": {"path": str(V1_RUNNER), "sha256": sha256_file(V1_RUNNER)},
        "timing_contract": {"entry_to_terminal_deadline": True,
                             "posthash_and_receipt_cpu_included": True, "cancel_cleanup_bounded": True},
        "source_provenance": {"current_path": str(CURRENT), "current_sha256": sha256_file(CURRENT),
                               "current_row_index": index, "physical_case_id": case_id,
                               "trajectory_path": str(row["trajectory"]["path"]),
                               "trajectory_producer_declared_sha256": row["trajectory"].get("producer_declared_sha256"),
                               "trajectory_sha_policy": "producer_declared_until_parent_post_reservation_hash",
                               "frames": row.get("frames"), "native_time_window_s": row.get("actual_time_window_s"),
                               "native_save_interval_s": 0.02, "control_variant": "same_cfl",
                               "cfl_number_from_prepared_Def": 0.2,
                               "historical_c60_timeout_seconds": 7.0,
                               "historical_c60_scientific_credit": "NONE_CROPPED_TIMEOUT"},
        "launch_allowed": True, "raw_opened": False, "hdf5_opened": False,
        "split_role": "DEVELOPMENT_PROSPECTIVE_ONLY", "physical_qualification": "UNKNOWN",
    }
    request["sha256"] = canonical_sha(request)
    return request


def build_half_cfl_plan(case_id: str = "F7_OBSTACLE_QUINTIC_B08_A065") -> dict[str, Any]:
    catalog = load_json(CURRENT)
    index, row = _case(catalog, case_id)
    same = build_same_cfl(case_id)
    return {
        "schema": HALF_SCHEMA, "status": "PENDING_CONTROL_SOURCE", "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": case_id, "current_path": str(CURRENT),
        "current_sha256": sha256_file(CURRENT), "current_row_index": index,
        "physical_case_id": case_id, "source_trajectory": row.get("trajectory"),
        "native_window_s": row.get("actual_time_window_s"), "native_frames": row.get("frames"),
        "save_interval_s": 0.02, "target_cfl": 0.1, "reference_cfl": 0.2,
        "launch_allowed": False, "qualification": dict(UNKNOWN),
        "required_missing_bindings": [
            "half_cfl_Def.xml with an independently hashed cflnumber=0.1 source",
            "half_cfl GenCase output/receipt and initial typed QA",
            "half_cfl motion/solver command and native raw output receipt",
        ],
        "same_cfl_request_sha256": canonical_sha(same),
        "historical_c60": {"timeout_seconds": 7.0, "scientific_credit": "NONE_CROPPED_TIMEOUT"},
        "limitations": ["Do not copy or edit same-CFL Def.xml to claim half-CFL.",
                        "No half-CFL source is launchable until all three bindings exist."],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--case-id", default="F7_OBSTACLE_QUINTIC_B08_A065")
    args = parser.parse_args(argv)
    same = build_same_cfl(args.case_id)
    half = build_half_cfl_plan(args.case_id)
    output = args.output_dir.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    same_path = output / "f7-s2-same-cfl-nvme-request-v3-001.json"
    half_path = output / "f7-s2-half-cfl-nvme-plan-v1-001.json"
    write_new(same_path, same)
    half_path.write_text(json.dumps(half, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"same_cfl": str(same_path), "same_sha256": same["sha256"],
                      "half_cfl": str(half_path), "half_sha256": canonical_sha(half),
                      "launch_allowed": {"same_cfl": True, "half_cfl": False}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
