#!/usr/bin/env python3
"""Prepare an F7-S2 dense ``SaveDt=.01`` NVMe counterpart.

This forward builder binds the exact dense predecessor that was actually
attempted for C60.  That predecessor timed out at its reserved wall limit and
therefore contributes no scientific credit; its full 12-second window and
1202-frame contract are retained here without silently cropping to the old
seven-second C60 run.  The original 949 MB trajectory HDF5 and XMF remain
explicit provenance references and are stat/stat-hash bound, but are excluded
from actionable ``input_files`` so a solver request cannot accidentally reread
the converted reference trajectory.

No half-CFL request is invented: the companion plan remains ``UNKNOWN`` until
an independently generated cfl=0.1 Def/GenCase/receipt closure exists.
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
V4_RUNNER = ROOT / "scripts" / "ds_data02_stage2_external_solver_v4.py"
V1_RUNNER = ROOT / "scripts" / "ds_data02_stage2_external_solver_v1.py"
RUNTIME = ROOT / "scripts" / "ds_data02_runtime_v2.py"
LEDGER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.json")
EXTERNAL_ROOT = Path("/var/tmp/ds02-stage2")
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
SCHEMA = "ds02.stage2.f7-nvme-counterpart-request.v4"
HALF_SCHEMA = "ds02.stage2.f7-nvme-half-cfl-plan.v1"

DENSE_RECEIPT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F7/"
    "F7_S2_ORIGINAL_SAMECFL_DENSE_SAVEDT_V2/"
    "f7-s2-samecfl-dense-savedt-v2-primary-002-v5/execution-receipt.json"
)
DENSE_REQUEST = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/"
    "stage2-priority-four-savedt-v2/f7_s2_same_cfl_savedt_v2.json"
)
DENSE_BINDING = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_savedt_cfl_pair_binding_v1.json"
)
DENSE_OVERLAY = Path(
    "/home/jade/.codex/worktrees/ds-data-02-stage2-reference/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/"
    "stage2_savedt_cfl_pair_inputs_v1/F7_S2/same_cfl/overlay-manifest.json"
)


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


def _stat_binding(path: Path, *, producer_sha256: str | None = None,
                  scope: str = "metadata_only") -> dict[str, Any]:
    stat = path.stat()
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns),
            "producer_sha256": producer_sha256, "scope": scope,
            "opened_by_solver": False}


def _source_paths(row: Mapping[str, Any], dense_request: Mapping[str, Any]) -> tuple[list[Path], list[dict[str, Any]]]:
    """Return actionable files and stat-only provenance references.

    The dense predecessor's input list is authoritative for the prepared
    overlay.  The converted trajectory and XMF are intentionally kept in the
    second return value only; placing either in ``input_files`` would turn a
    solver request into an accidental reference-H5 reread.
    """
    result: list[Path] = []
    seen: set[str] = set()
    provenance: list[dict[str, Any]] = []

    trajectory = Path(str(row.get("trajectory", {}).get("path", ""))).expanduser().resolve()
    xmf = Path(str(row.get("xmf", {}).get("path", ""))).expanduser().resolve()
    if not trajectory.is_file() or int(row.get("trajectory", {}).get("bytes", 0)) <= 0:
        raise CounterpartError(f"trajectory is unavailable for stat-only binding: {trajectory}")
    if not xmf.is_file():
        raise CounterpartError(f"XMF provenance source is unavailable: {xmf}")
    provenance.append(_stat_binding(
        trajectory, producer_sha256=str(row.get("trajectory", {}).get("producer_declared_sha256", "")),
        scope="metadata_only_provenance_no_solver_open"))
    provenance.append(_stat_binding(
        xmf, producer_sha256=str(row.get("xmf", {}).get("recomputed_sha256", "")),
        scope="metadata_only_provenance_no_solver_open"))

    def add(value: Any) -> None:
        if not isinstance(value, str) or not value:
            return
        path = Path(value).expanduser().resolve()
        if path == trajectory or path == xmf:
            return
        if not path.is_file():
            raise CounterpartError(f"actionable source is unavailable: {path}")
        if str(path) not in seen:
            seen.add(str(path))
            result.append(path)

    # The dense prepared overlay and its actual receipt are the solver source
    # closure.  Keep every small guard/source file from that closure, but do
    # not carry old output products into a new run.
    for value in dense_request.get("input_files", []):
        add(value)
    add(str(CURRENT))
    add(row.get("manifest", {}).get("path"))
    for item in row.get("source_bindings", {}).values():
        if isinstance(item, Mapping):
            add(item.get("path"))
    for value in (DENSE_REQUEST, DENSE_BINDING, DENSE_OVERLAY, DENSE_RECEIPT):
        add(str(value))
    for value in (V4_RUNNER, V1_RUNNER, RUNTIME):
        add(str(value))
    return result, provenance


def _input_hashes(paths: Sequence[Path], dense_request: Mapping[str, Any]) -> tuple[list[str], dict[str, str], dict[str, str]]:
    values: list[str] = []
    hashes: dict[str, str] = {}
    scopes: dict[str, str] = {}
    declared = dense_request.get("input_sha256", dense_request.get("input_hashes", {}))
    if not isinstance(declared, Mapping):
        declared = {}
    for path in paths:
        key = str(path)
        values.append(key)
        expected = declared.get(key)
        if isinstance(expected, str) and len(expected) == 64:
            hashes[key] = expected
            scopes[key] = "post_reservation_hash_producer_declared_reverified"
            continue
        # Dense v2 deliberately left the official binary and both prepared
        # BI4 digests for the parent v4 guard.  Hash those concrete files now
        # for a reproducible request, while the parent must still verify the
        # same bytes immediately before launch.  No trajectory HDF5 is in
        # ``paths``.
        hashes[key] = sha256_file(path)
        scopes[key] = ("post_reservation_hash_parent_guard_reverified"
                       if isinstance(expected, str) and expected.startswith("PARENT_")
                       else "post_reservation_hash")
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
    for source in (DENSE_RECEIPT, DENSE_REQUEST, DENSE_BINDING, DENSE_OVERLAY):
        if not source.is_file():
            raise CounterpartError(f"dense SaveDt=.01 predecessor closure is incomplete: {source}")
    predecessor_receipt = load_json(DENSE_RECEIPT)
    dense_request = load_json(DENSE_REQUEST)
    command = list(predecessor_receipt.get("command", []))
    if not command:
        raise CounterpartError("dense predecessor command is missing")
    command = [str(value).replace(str(Path(str(predecessor_receipt.get("output_root", ""))).expanduser().resolve()), "{output_root}")
               for value in command]
    if "-tout:0.01" not in command or not any(str(value).startswith("-tmax:12") for value in command):
        raise CounterpartError("dense predecessor is not the bound 12-second/0.01-second command")
    paths, provenance_files = _source_paths(row, dense_request)
    input_files, input_sha256, input_scopes = _input_hashes(paths, dense_request)
    case_token = case_id.lower().replace("_", "-")
    attempt_id = "f7-s2-a065-same-cfl-dense-savedt-v4-001"
    if output_root is None:
        output_root = EXTERNAL_ROOT / "F7" / "F7_S2_NVME_COUNTERPART_V4" / attempt_id
    output_root = Path(output_root).expanduser().resolve()
    if output_root.exists():
        raise CounterpartError(f"new external output namespace already exists: {output_root}")
    cwd = Path(str(dense_request.get("cwd", ""))).expanduser().resolve()
    if not cwd.is_dir():
        raise CounterpartError(f"solver cwd is unavailable: {cwd}")
    ledger_binding = _ledger_binding()
    predecessor_request = predecessor_receipt.get("request", {})
    predecessor_sha = sha256_file(DENSE_REQUEST)
    predecessor_receipt_sha = sha256_file(DENSE_RECEIPT)
    request: dict[str, Any] = {
        "schema": "ds02.stage2.external-solver-request.v4",
        "status": "READY_FOR_PARENT_GUARD", "role": "DEVELOPMENT",
        "family_id": "F7", "case_id": case_token, "attempt_id": attempt_id,
        "kind": "qualification", "command": command, "cwd": str(cwd),
        "max_wall_seconds": 3600.0, "cpu_threads": int(predecessor_request.get("cpu_threads", 4)),
        "estimated_peak_gpu_mib": int(predecessor_request.get("estimated_peak_gpu_mib", 4096)),
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "runtime_binding": {"path": str(RUNTIME), "sha256": sha256_file(RUNTIME), "role": "shared_runtime_v2"},
        "v1_runner_binding": {"path": str(V1_RUNNER), "sha256": sha256_file(V1_RUNNER)},
        "v4_runner_binding": {"path": str(V4_RUNNER), "sha256": sha256_file(V4_RUNNER)},
        "parent_resource_binding": ledger_binding,
        "storage_scope": {"external_filesystem": str(EXTERNAL_ROOT), "output_root": str(output_root),
                          "external_product_reserved_bytes": 8 * 1024 ** 3,
                          "home_receipt_reserved_bytes": 4 * 1024 ** 2,
                          "new_storage_bytes": 8 * 1024 ** 3 + 4 * 1024 ** 2,
                          "home_min_free_bytes": int(ledger_binding["limits"].get("home_min_free_bytes") or 1),
                          "external_min_free_bytes": 1},
        "gpu": {"required": True, "gpu_uuid": None,
                "selection_policy": "parent_runtime_selected_uuid_must_be_recorded",
                "lease_root": str(Path(ledger_binding["data_root"]) / "leases")},
        "input_files": input_files, "input_sha256": input_sha256,
        "input_content_scope": input_scopes,
        "provenance_reference_files": provenance_files,
        "execution": {"manufactured_only": False, "scientific_status": "DEVELOPMENT_SOURCE_BOUND",
                       "native_raw_hdf5_open": False, "native_bi4_open": True,
                       "reference_hdf5_open_forbidden": True, "reference_xmf_open_forbidden": True,
                       "preflight_cfd_invoked": False, "runtime_cfd_flag_from_process_launch": True},
        "timing_contract": {"entry_to_terminal_deadline": True,
                             "entry_time_includes_request_parse": True,
                             "pre_and_post_input_hash_stat_included": True,
                             "posthash_and_receipt_cpu_included": True, "cancel_cleanup_bounded": True,
                             "receipt_finalization_scope": "small bounded cleanup after timer restore"},
        "source_provenance": {"current_path": str(CURRENT), "current_sha256": sha256_file(CURRENT),
                               "current_row_index": index, "physical_case_id": case_id,
                               "trajectory_path": str(row["trajectory"]["path"]),
                               "trajectory_producer_declared_sha256": row["trajectory"].get("producer_declared_sha256"),
                               "trajectory_scope": "metadata_only_provenance_no_solver_open",
                               "xmf_path": str(row["xmf"]["path"]),
                               "xmf_recomputed_sha256": row["xmf"].get("recomputed_sha256"),
                               "xmf_scope": "metadata_only_provenance_no_solver_open",
                               "frames": 1202, "native_time_window_s": [0.0, 12.00003209155591],
                               "native_save_interval_s": 0.01, "control_variant": "same_cfl_dense_savedt",
                               "cfl_number_from_prepared_Def": 0.2,
                               "dense_predecessor": {"request_path": str(DENSE_REQUEST), "request_sha256": predecessor_sha,
                                                     "receipt_path": str(DENSE_RECEIPT), "receipt_sha256": predecessor_receipt_sha,
                                                     "status": predecessor_receipt.get("status"),
                                                     "termination_reason": predecessor_receipt.get("termination_reason"),
                                                     "save_interval_s": 0.01, "expected_native_frames": 1202,
                                                     "physical_window_s": [0.0, 12.00003209155591],
                                                     "scientific_credit": "NONE_CROPPED_TIMEOUT"},
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
    same_path = output / "f7-s2-same-cfl-nvme-request-v4-001.json"
    half_path = output / "f7-s2-half-cfl-nvme-plan-v1-001.json"
    write_new(same_path, same)
    half_path.write_text(json.dumps(half, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"same_cfl": str(same_path), "same_sha256": same["sha256"],
                      "half_cfl": str(half_path), "half_sha256": canonical_sha(half),
                      "launch_allowed": {"same_cfl": True, "half_cfl": False}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
