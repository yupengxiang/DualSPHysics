#!/usr/bin/env python3
"""Prepare source-bound original-grid same/half-CFL dense requests.

The 13 non-F2-S1 sentinels receive one request at the CURRENT original
particle spacing with the source CFL and one request with a materialized,
hash-bound execution XML whose only numerical change is CFL -> CFL/2.  The
generated half-CFL XML and hard-linked ``.bi4`` preserve the immutable source
particle state; source XML/BI4/receipts are never modified.  Requests are
launch-disabled preparation artifacts for the primary GPU dispatcher.

This module does not start a solver, read HDF5, or create solver output.  It
does create new half-CFL input XML/motion links and records their hashes.  The
two ``-tout`` values are output-save cadences.  Actual step sequences and
clamp events remain UNKNOWN until a guarded solver receipt contains suitable
evidence; they are never inferred from CFL or output cadence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.original-cfl-pair-requests.v2"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
GRAPH_PATH = REFERENCE / "stage2_minimal14_study_graph_v2.json"
INPUT_ROOT = REFERENCE / "stage2_original_cfl_pair_inputs_v2"
REQUEST_ROOT = STAGE2 / "requests/stage2-original-cfl-pairs-v2"
REPORT_PATH = REFERENCE / "stage2_original_cfl_pair_cost_manifest_v2.json"
DISPATCH_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DISPATCH = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py"
STRICT = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v4.py"
RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v4.py"
BASE_RUNTIME = DISPATCH_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
SOLVER = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
)
PROTECTED_GPU = {
    "index": 6,
    "uuid": "GPU-0889376f-e3a7-cf47-0279-e56f8eb60fec",
    "pid": 601689,
    "action": "do_not_touch",
}
SENTINEL_ORDER = [
    "F1-S1", "F1-S2", "F2-S2", "F3-S1", "F3-S2", "F4-S1", "F4-S2",
    "F5-S1", "F5-S2", "F6-S1", "F6-S2", "F7-S1", "F7-S2",
]
OBSERVER_RESERVATION = 512 * 1024 * 1024
TEMPORARY_MARGIN = 2 * 1024 * 1024 * 1024


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_HASH_CACHE: dict[str, str] = {}


def file_record(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(path)
    stat = path.stat()
    key = str(path.resolve())
    if hash_file:
        if key not in _HASH_CACHE:
            _HASH_CACHE[key] = sha256_file(path)
        digest: str | None = _HASH_CACHE[key]
    else:
        digest = None
    result: dict[str, Any] = {
        "path": key,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }
    if digest is not None:
        result["sha256"] = digest
    return result


def atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise FileExistsError(f"refuse to overwrite differing file: {path}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def git_head() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPO, check=True,
        capture_output=True, text=True,
    ).stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def safe_token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_")


def dp_token(dp: float) -> str:
    return f"{dp:.6f}".rstrip("0").rstrip(".").replace(".", "p")


def round_frames(end_s: float, cadence_s: float) -> int:
    return max(1, math.ceil(end_s / cadence_s - 1e-12) + 1)


def graph_row(graph: dict[str, Any], sentinel_id: str) -> dict[str, Any]:
    rows = [row for row in graph["sentinels"] if row.get("sentinel_id") == sentinel_id]
    if len(rows) != 1:
        raise ValueError(f"expected one sentinel row: {sentinel_id}")
    return rows[0]


def cost_row(graph: dict[str, Any], sentinel_id: str, cfl_mode: str) -> dict[str, Any]:
    rows = [
        row for row in graph["cost_rows"]
        if row.get("sentinel_id") == sentinel_id
        and row.get("grid") == "original"
        and row.get("cfl_mode") == cfl_mode
        and row.get("cadence_kind") == "dense"
    ]
    if len(rows) != 1:
        raise ValueError(f"expected one original dense {cfl_mode} cost row: {sentinel_id}; found {len(rows)}")
    return rows[0]


def read_source_cfl(xml_path: Path) -> tuple[float, list[str]]:
    root = ET.parse(xml_path).getroot()
    values = [
        node.get("value") for node in root.findall(".//cflnumber")
        if node.get("value") is not None
    ]
    if len(values) != 2:
        raise ValueError(f"expected casedef and execution cflnumber entries: {xml_path}: {values}")
    parsed = [float(value) for value in values]
    if max(parsed) - min(parsed) > 1e-9:
        raise ValueError(f"source cfl entries disagree: {xml_path}: {values}")
    return parsed[0], values


def relative_input_files(xml_path: Path) -> list[Path]:
    root = ET.parse(xml_path).getroot()
    paths: list[Path] = []
    seen: set[str] = set()
    for node in root.findall(".//file"):
        name = node.get("name")
        if not name:
            continue
        path = (xml_path.parent / name).resolve()
        if str(path) not in seen:
            seen.add(str(path))
            paths.append(path)
    return paths


def link_or_copy(source: Path, destination: Path) -> dict[str, Any]:
    if not source.is_file():
        raise FileNotFoundError(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if not destination.is_file() or sha256_file(destination) != sha256_file(source):
            raise FileExistsError(f"existing overlay differs: {destination}")
    else:
        try:
            os.link(source, destination)
        except OSError:
            shutil.copy2(source, destination)
    stat = destination.stat()
    return {
        "source": file_record(source),
        "destination": file_record(destination),
        "materialization": "hardlink_same_inode" if os.stat(source).st_ino == stat.st_ino and os.stat(source).st_dev == stat.st_dev else "byte_copy",
    }


def half_input(graph_row_value: dict[str, Any]) -> dict[str, Any]:
    sid = graph_row_value["sentinel_id"]
    source_xml = Path(graph_row_value["source_xml"]["path"]).resolve()
    source_bi4 = source_xml.with_suffix(".bi4")
    source_cfl_value, source_cfl_strings = read_source_cfl(source_xml)
    half = source_cfl_value / 2.0
    source_text = source_xml.read_text(encoding="utf-8")
    # Replace both casedef and execution constants without normalizing any
    # other geometry/motion/particle bytes.
    replaced, count = re.subn(
        r'(<cflnumber\s+value=")[^"]+("[^>]*/>)',
        lambda match: f"{match.group(1)}{half:.17g}{match.group(2)}",
        source_text,
    )
    if count != 2:
        raise ValueError(f"expected two cflnumber replacements for {sid}, got {count}")
    stem = f"{safe_token(sid)}_ORIGINAL_DP{dp_token(float(graph_row_value['source_dp_m']))}_HALFCFL"
    directory = INPUT_ROOT / safe_token(sid) / "half_cfl"
    overlay_xml = directory / f"{stem}.xml"
    overlay_bi4 = directory / f"{stem}.bi4"
    atomic_bytes(overlay_xml, replaced.encode("utf-8"))
    bi4_record = link_or_copy(source_bi4, overlay_bi4)
    dependency_records: list[dict[str, Any]] = []
    for dependency in relative_input_files(source_xml):
        relative = dependency.relative_to(source_xml.parent)
        dependency_records.append(link_or_copy(dependency, directory / relative))
    manifest_path = directory / "overlay-manifest.json"
    manifest = {
        "schema": "ds02.stage2.original-half-cfl-overlay.v2",
        "sentinel_id": sid,
        "family_id": graph_row_value["family_id"],
        "physical_case_id": graph_row_value["physical_case_id"],
        "source": {
            "xml": file_record(source_xml),
            "bi4": file_record(source_bi4),
            "cfl_values_text": source_cfl_strings,
            "cfl_value": source_cfl_value,
        },
        "overlay": {
            "xml": file_record(overlay_xml),
            "bi4": bi4_record,
            "cfl_values_text": [f"{half:.17g}", f"{half:.17g}"],
            "cfl_value": half,
            "only_declared_change": "both cflnumber values in casedef/constantsdef and execution/constants; XML bytes otherwise preserved",
            "particle_state": "source .bi4 hard-linked or byte-identically copied; no particle mass, dp, geometry, motion, or initial state change",
        },
        "motion_dependencies": dependency_records,
        "solver_launch": False,
        "hdf5_read": False,
    }
    atomic_json(manifest_path, manifest)
    return {
        "directory": str(directory.resolve()),
        "xml": file_record(overlay_xml),
        "bi4": file_record(overlay_bi4),
        "manifest": file_record(manifest_path),
        "motion_dependencies": dependency_records,
        "source_xml": file_record(source_xml),
        "source_bi4": file_record(source_bi4),
                "source_cfl": source_cfl_value,
        "effective_cfl": half,
    }


def source_command_info(receipt_path: Path) -> dict[str, Any]:
    receipt = load_json(receipt_path)
    command = receipt.get("command")
    if not isinstance(command, list) or not command:
        raise ValueError(f"source solver receipt has no command: {receipt_path}")
    return {
        "receipt": file_record(receipt_path),
        "command": command,
        "actual_tmax_s": next((float(x.split(":", 1)[1]) for x in command if x.startswith("-tmax:")), None),
        "actual_tout_s": next((float(x.split(":", 1)[1]) for x in command if x.startswith("-tout:")), None),
        "status": receipt.get("status"),
        "returncode": receipt.get("returncode"),
        "elapsed_seconds": receipt.get("elapsed_seconds"),
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "gpu_seconds": receipt.get("gpu_seconds"),
        "bytes": receipt.get("bytes"),
        "output_root": receipt.get("output_root"),
    }


def source_dependencies(row: dict[str, Any]) -> list[Path]:
    source_xml = Path(row["source_xml"]["path"]).resolve()
    source_bi4 = source_xml.with_suffix(".bi4")
    gencase_receipt = Path(row["current_binding"]["gencase_receipt"]["path"]).resolve()
    solver_receipt = Path(row["source_solver_controls"]["receipt_runtime"]["path"]).resolve()
    dependencies = [source_xml, source_bi4, gencase_receipt, solver_receipt]
    for path in relative_input_files(source_xml):
        if path not in dependencies:
            dependencies.append(path)
    return dependencies


def request_inputs(row: dict[str, Any], overlay: dict[str, Any] | None) -> list[Path]:
    paths = [
        DISPATCH.resolve(), STRICT.resolve(), RUNTIME.resolve(), BASE_RUNTIME.resolve(), SOLVER.resolve(),
        Path(__file__).resolve(), GRAPH_PATH.resolve(),
    ] + source_dependencies(row)
    if overlay is not None:
        paths.extend([
            Path(overlay["xml"]["path"]), Path(overlay["bi4"]["path"]),
            Path(overlay["manifest"]["path"]),
        ])
        paths.extend(Path(item["destination"]["path"]) for item in overlay["motion_dependencies"])
    unique: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.resolve()
        if str(path) not in seen:
            seen.add(str(path))
            unique.append(path)
    return unique


def query_times(window: list[float]) -> list[float]:
    start, end = window
    return [start, start + (end - start) * 0.25, start + (end - start) * 0.5,
            start + (end - start) * 0.75, end]


def rounded_reservation(raw_reserved: int) -> int:
    target = raw_reserved + OBSERVER_RESERVATION + TEMPORARY_MARGIN
    gib = 1024 ** 3
    return int(math.ceil(target / gib) * gib)


def proxy_wall(source: dict[str, Any], *, half: bool) -> tuple[int, float]:
    # This is a planning proxy from an actual source receipt, not a wall-time
    # guarantee.  Dense output doubles saved frames; half CFL is a separate
    # numerical recipe and is conservatively assigned another factor two.
    source_seconds = float(source.get("gpu_seconds") or source.get("elapsed_seconds") or 0.0)
    factor = 4.0 if half else 2.0
    proxy_seconds = source_seconds * factor
    max_wall = int(min(7200, max(900, math.ceil(proxy_seconds * 4.0))))
    return max_wall, proxy_seconds


def build_request(row: dict[str, Any], graph: dict[str, Any], mode: str,
                  overlay: dict[str, Any] | None, launch_commit: str) -> tuple[dict[str, Any], dict[str, Any]]:
    sid = row["sentinel_id"]
    if mode not in {"same_cfl", "half_cfl"}:
        raise ValueError(mode)
    source_xml = Path(row["source_xml"]["path"]).resolve()
    source_prefix = source_xml.with_suffix("")
    source_gencase = Path(row["current_binding"]["gencase_receipt"]["path"]).resolve()
    source_solver_receipt = Path(row["source_solver_controls"]["receipt_runtime"]["path"]).resolve()
    source_controls = source_command_info(source_solver_receipt)
    cost = cost_row(graph, sid, mode)
    window = [float(x) for x in row["effective_time_window_s"]]
    cadence = float(row["dense_output_cadence_s"])
    source_dp = float(row["source_dp_m"])
    source_cfl_value, _ = read_source_cfl(source_xml)
    effective_cfl = source_cfl_value if mode == "same_cfl" else source_cfl_value / 2.0
    mode_label = "SAMECFL" if mode == "same_cfl" else "HALFCFL"
    case_id = f"{safe_token(sid)}_ORIGINAL_DP{dp_token(source_dp)}_{mode_label}_DENSE_T"
    end_token = f"{window[1]:.6f}".rstrip("0").rstrip(".").replace(".", "p")
    case_id += end_token
    attempt_id = f"{case_id.lower()}-root-001"
    input_paths = request_inputs(row, overlay)
    input_files = [str(path) for path in input_paths]
    input_hashes = {str(path): sha256_file(path) for path in input_paths}
    if mode == "same_cfl":
        input_prefix = source_prefix
        cwd = source_xml.parent
    else:
        if overlay is None:
            raise ValueError(f"missing half-CFL overlay for {sid}")
        input_prefix = Path(overlay["xml"]["path"]).with_suffix("")
        cwd = Path(overlay["directory"])
    max_wall, proxy_gpu_seconds = proxy_wall(source_controls, half=mode == "half_cfl")
    reservation = rounded_reservation(int(cost["raw_native_reserved_bytes"]))
    request_path = REQUEST_ROOT / f"{safe_token(sid).lower()}_original_{mode}_cfl_dense.json"
    request = {
        "schema": REQUEST_SCHEMA,
        "family_id": row["family_id"],
        "case_id": case_id,
        "physical_case_id": row["physical_case_id"],
        "attempt_id": attempt_id,
        "kind": "qualification",
        "qualification_stage": "stage2_original_cfl_pair_pending_primary_dispatch",
        "cpu_task_kind": "solver",
        "cpu_threads": 2,
        "omp_threads": 2,
        "max_wall_seconds": max_wall,
        "estimated_storage_bytes": reservation,
        "estimated_peak_gpu_mib": 4096,
        "worktree_root": str(REPO),
        "cwd": str(cwd),
        "command": [str(SOLVER), str(input_prefix), "{attempt_root}/solver_output",
                     f"-tmax:{window[1]:.12g}", f"-tout:{cadence:.12g}"],
        "gencase_receipt": str(source_gencase),
        "gencase_receipt_sha256": sha256_file(source_gencase),
        "expected_particles": int(row["source_particles"]),
        "expected_fluid_particles": int(row["source_fluid_particles"]),
        "expected_native_frames": round_frames(window[1], cadence),
        "expected_dimension": 3,
        "physical_window_s": window,
        "save_interval_s": cadence,
        "source_binding": {
            "schema": "ds02.stage2.original-cfl-pair-binding.v1",
            "sentinel_id": sid,
            "family_id": row["family_id"],
            "physical_case_id": row["physical_case_id"],
            "grid": "original",
            "source": {
                "current_xml": file_record(source_xml),
                "current_bi4": file_record(source_xml.with_suffix(".bi4")),
                "gencase_receipt": file_record(source_gencase),
                "solver_receipt": file_record(source_solver_receipt),
                "source_cfl": source_cfl_value,
                "source_command": source_controls["command"],
                "source_actual_tmax_s": source_controls["actual_tmax_s"],
                "source_actual_tout_s": source_controls["actual_tout_s"],
                "source_elapsed_seconds": source_controls["elapsed_seconds"],
                "source_gpu_seconds": source_controls["gpu_seconds"],
                "source_output_bytes": source_controls["bytes"],
            },
            "effective_conditions": {
                "cfl_mode": mode,
                "source_cfl": source_cfl_value,
                "effective_cfl": effective_cfl,
                "dp_m": source_dp,
                "massfluid_and_particles": "unchanged source original state",
                "continuous_geometry_motion_control": "unchanged source XML and referenced files",
                "overlay": overlay if mode == "half_cfl" else None,
            },
            "output_control": {
                "requested_tmax_s": window[1],
                "requested_tout_s": cadence,
                "full_physical_window_retained": True,
                "tout_is_saved_output_cadence": True,
                "dt_sequence": "UNKNOWN_UNTIL_GUARDED_RECEIPT",
                "dt_clamp_events": "UNKNOWN_UNTIL_GUARDED_RECEIPT",
                "savedt_or_dtallinfo": "UNKNOWN; no complete per-step trace is inferred from CFL or output frames",
            },
        },
        "cost": {
            "graph_row": cost,
            "source_receipt_runtime": source_controls,
            "planned_frame_count": round_frames(window[1], cadence),
            "raw_native_full_window_bytes_unreserved": int(cost["raw_native_unreserved_bytes"]),
            "raw_native_full_window_bytes_reserved": int(cost["raw_native_reserved_bytes"]),
            "one_stream_observer_reserved_bytes": OBSERVER_RESERVATION,
            "minimal_execution_storage_reservation_bytes": reservation,
            "typed_full_h5": "NOT_PLANNED; selected query anchors only after raw retention",
            "lossless_full_window_bytes": "UNKNOWN_UNTIL_FULL_WINDOW_ROUNDTRIP",
            "two_frame_archive_ratio": cost.get("archive_ratio_measured_pair"),
            "two_frame_ratio_use": "diagnostic context only; excluded from full-window reservation",
            "source_scaled_gpu_seconds_proxy": proxy_gpu_seconds,
            "source_scaled_gpu_hours_proxy": proxy_gpu_seconds / 3600.0,
            "runtime_proxy_warning": "source receipt scaling is planning only, not a wall-time upper bound; parent guard terminal receipt is authoritative",
        },
        "output_plan": {
            "native_raw": "{attempt_root}/solver_output/data/Part_*.bi4; retain every saved frame over the complete physical window",
            "native_source_role": "immutable primary scientific array source; no deletion, replacement, or favorable-subset pruning",
            "stream_observer": {
                "mode": "one sequential pass over complete native frames",
                "output": "{attempt_root}/observer/stream-observables.jsonl",
                "scope": "pre-registered observables only; does not replace native arrays",
                "status": "PENDING_CONSUMER_CALIBRATION",
            },
            "typed": {
                "mode": "selected query-time replay anchors only",
                "query_times_s": query_times(window),
                "output": "{attempt_root}/typed/query-anchors/",
                "time_policy": "EXACT/BRACKETED using actual saved times; no frame-number hardcoding or extrapolation",
                "full_h5": "deferred separate request; native arrays remain accessible through decoder/reader contract",
            },
            "lossless_archive": {
                "mode": "deferred full-window streaming roundtrip benchmark",
                "required_proof": ["every source frame included", "compressed bytes", "decompressed byte-for-byte SHA", "complete array decoder access"],
                "status": "PENDING_FULL_WINDOW_CANARY",
                "ratio": "UNKNOWN",
            },
            "downsample": "derived only after retaining complete raw; no solver replacement",
            "overwrite_policy": "all output paths must be new and absent",
        },
        "launch_policy": {
            "launch_disabled": True,
            "execution_allowed": False,
            "solver_launch_owner": "root",
            "primary_gpu_dispatch_required": True,
            "gpu_uuid_authorization": "PENDING_PRIMARY_LEDGER",
            "protected_external_gpu": PROTECTED_GPU,
            "parent_guard": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v4.py",
        },
        "input_files": input_files,
        "input_hashes": input_hashes,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "launch_commit": launch_commit,
            "cpu_parent_binding": "required",
            "gpu_uuid_lease": "primary only; none granted in preparation",
            "source_output_protection": "new attempt output only; immutable CURRENT source inputs",
            "estimated_cpu_core_hours": 2 * max_wall / 3600.0,
            "estimated_gpu_hours_proxy": proxy_gpu_seconds / 3600.0,
            "estimated_new_storage_bytes": reservation,
        },
        "scope": {
            "physical_case_id": row["physical_case_id"],
            "sentinel_id": sid,
            "source_original_dp_m": source_dp,
            "cfl_mode": mode,
            "same_cfl_or_half_cfl_dense": True,
            "full_time_hdf5_read_in_preparation": False,
            "solver_started": False,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    return request, {
        "request_path": str(request_path.resolve()),
        "sentinel_id": sid,
        "family_id": row["family_id"],
        "physical_case_id": row["physical_case_id"],
        "mode": mode,
        "request": file_record(request_path, hash_file=False) if request_path.exists() else {"path": str(request_path.resolve())},
        "graph_cost": cost,
        "source_receipt": source_controls,
        "input_xml": str(input_prefix.with_suffix(".xml")),
        "input_bi4": str(input_prefix.with_suffix(".bi4")),
        "launch_disabled": True,
        "proxy_gpu_seconds": proxy_gpu_seconds,
        "raw_reserved_bytes": int(cost["raw_native_reserved_bytes"]),
        "request_storage_reservation_bytes": reservation,
    }


def write_request(path: Path, request: dict[str, Any]) -> None:
    atomic_json(path, request)


def prepare(graph: dict[str, Any]) -> dict[str, Any]:
    launch_commit = git_head()
    overlays: dict[str, dict[str, Any]] = {}
    for sid in SENTINEL_ORDER:
        overlays[sid] = half_input(graph_row(graph, sid))
    request_records: list[dict[str, Any]] = []
    request_paths: list[str] = []
    for sid in SENTINEL_ORDER:
        row = graph_row(graph, sid)
        for mode in ("same_cfl", "half_cfl"):
            overlay = overlays[sid] if mode == "half_cfl" else None
            request, record = build_request(row, graph, mode, overlay, launch_commit)
            output_path = REQUEST_ROOT / f"{safe_token(sid).lower()}_original_{mode}_cfl_dense.json"
            write_request(output_path, request)
            request_paths.append(str(output_path.resolve()))
            record["request"] = file_record(output_path)
            record["input_hashes_digest"] = hashlib.sha256(
                "\n".join(f"{k}={v}" for k, v in sorted(request["input_hashes"].items())).encode()
            ).hexdigest()
            request_records.append(record)
    raw_unreserved = sum(r["graph_cost"]["raw_native_unreserved_bytes"] for r in request_records)
    raw_reserved = sum(r["graph_cost"]["raw_native_reserved_bytes"] for r in request_records)
    minimal_reserved = sum(r["request_storage_reservation_bytes"] for r in request_records)
    proxy_gpu_seconds = sum(r["proxy_gpu_seconds"] for r in request_records)
    report = {
        "schema": "ds02.stage2.original-cfl-pair-cost-manifest.v2",
        "status": "PREPARED_LAUNCH_DISABLED_26_REQUESTS",
        "generated_at_commit": launch_commit,
        "scope": {
            "sentinels": SENTINEL_ORDER,
            "sentinel_count": len(SENTINEL_ORDER),
            "requests": len(request_records),
            "variants": ["original_same_cfl_dense", "original_half_cfl_dense"],
            "excluded": "F2-S1 already has separate source-bound full-window canary requests; it is not duplicated here",
            "hdf5_read": False,
            "solver_started": False,
            "gpu_started": False,
        },
        "source_binding_policy": {
            "current_xml_bi4_receipts": "exact CURRENT graph row source XML, same-stem native BI4, current GenCase receipt and completed solver receipt",
            "physical_identity": "exact graph sentinel physical_case_id; no latest glob or family alias",
            "same_cfl": "direct immutable CURRENT original source prefix",
            "half_cfl": "new overlay changes only both XML cflnumber values to source CFL/2; source particle BI4 and motion dependencies are byte-identical",
            "continuous_geometry_motion": "unchanged source files",
        },
        "cost_policy": {
            "raw_native": "complete physical window and every dense saved frame retained; reserved bytes use graph actual source Part_0000 size × planned frame count plus safety factor",
            "stream_observer": {"reserved_bytes_per_request": OBSERVER_RESERVATION, "mode": "one sequential pass; derived observables do not replace raw"},
            "typed": "selected query anchors only; no second full H5 copy in these requests",
            "downsample": "derived from retained dense native output; no additional solver",
            "lossless_full_window": "separate postrun reconstruction plan; full-time bytes and ratio UNKNOWN until an end-to-end roundtrip canary",
            "two_frame_ratio": "retained only as diagnostic context and excluded from reservation",
            "temporary_margin_bytes": TEMPORARY_MARGIN,
        },
        "aggregate": {
            "raw_native_unreserved_bytes": raw_unreserved,
            "raw_native_reserved_bytes": raw_reserved,
            "minimal_execution_reservation_bytes": minimal_reserved,
            "source_scaled_gpu_seconds_proxy": proxy_gpu_seconds,
            "source_scaled_gpu_hours_proxy": proxy_gpu_seconds / 3600.0,
            "proxy_warning": "planning proxy only; actual guarded solver receipt and terminal storage check are authoritative",
        },
        "requests": request_records,
        "full_window_stream_and_lossless_design": {
            "execution_graph": [
                "run one source-bound full-window solver at a time under primary UUID/lease guard",
                "retain all native Part_*.bi4 as immutable primary arrays",
                "perform one sequential observer pass over native frames",
                "derive output downsampling only after raw retention",
                "reconstruct lossless archive in a separate bounded postrun stream, verifying each frame SHA and decoder access",
            ],
            "full_time_lossless_ratio": "UNKNOWN; the measured 28-pair/early-frame ratio is not a full-window upper bound",
            "access_contract": "archive must preserve every scientific array and random/sequential decode access, not only summaries",
            "risk": "full-window lossless temporary peak and typed replay bytes require actual canary measurement; they are excluded from these solver reservation claims",
        },
        "unknowns": [
            "actual per-step dt sequence for same and half CFL",
            "dt clamp events and DtMin effects",
            "observer calibration and scientific QI/QN/QE",
            "full-window lossless bytes/ratio and temporary peak",
            "solver wall time beyond source-scaled planning proxy",
        ],
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REPORT_PATH, report)
    return {"report": str(REPORT_PATH), "requests": request_paths, "overlays": overlays, "manifest": report}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true")
    args = parser.parse_args()
    if not args.prepare:
        parser.error("choose --prepare")
    graph = load_json(GRAPH_PATH)
    result = prepare(graph)
    print(json.dumps({
        "status": "PASS",
        "report": result["report"],
        "request_count": len(result["requests"]),
        "sentinel_count": len(SENTINEL_ORDER),
        "solver_started": False,
        "hdf5_read": False,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
