#!/usr/bin/env python3
"""Prepare bounded initial-H5 per-MK audit requests for the 118 CURRENT cases.

This is a request-preparation worker only.  It reads the already-indexed
coverage JSON and filesystem metadata for each H5/conversion pair; it does not
open H5 content and it never launches the static audit.  The v2 static worker
has a hard two-case selector, so this generator emits family-local pairs.  H5
digests are inherited from the source coverage producer declaration and are
revalidated by the shared v4 guard at launch; this avoids silently claiming a
new full-H5 hash during request preparation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any


FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
MAX_CASES_PER_REQUEST = 2
VENV_PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")


class QueueError(RuntimeError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(value: str | Path, label: str) -> Path:
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise QueueError(f"{label} is missing: {path}")
    return path


def read_json(value: str | Path, label: str) -> tuple[Path, dict[str, Any]]:
    path = require_file(value, label)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # pragma: no cover - malformed evidence path
        raise QueueError(f"{label} is invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise QueueError(f"{label} is not an object: {path}")
    return path, payload


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True, ensure_ascii=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def indexed_rows(coverage: dict[str, Any]) -> dict[str, dict[str, Any]]:
    if coverage.get("schema") not in {
        "ds02.stage2.omission-coverage-index.v2",
        "ds02.stage2.omission-coverage-index.v3",
    }:
        raise QueueError("coverage schema must be omission-coverage-index.v2 or v3")
    rows = coverage.get("rows")
    if not isinstance(rows, list) or len(rows) != sum(FAMILY_COUNTS.values()):
        raise QueueError("coverage must contain exactly 118 rows")
    result: dict[str, dict[str, Any]] = {}
    counts = {family: 0 for family in FAMILY_COUNTS}
    for row in rows:
        if not isinstance(row, dict):
            raise QueueError("coverage contains a non-object row")
        family = str(row.get("family_id", ""))
        physical_id = str(row.get("physical_case_id", ""))
        if family not in FAMILY_COUNTS or not physical_id or physical_id in result:
            raise QueueError(f"invalid or duplicate coverage identity: {family}/{physical_id}")
        result[physical_id] = row
        counts[family] += 1
    if counts != FAMILY_COUNTS:
        raise QueueError(f"coverage family counts {counts} != {FAMILY_COUNTS}")
    return result


def source_pair(row: dict[str, Any]) -> dict[str, Any]:
    physical_id = str(row["physical_case_id"])
    identity = row.get("current_identity")
    if not isinstance(identity, dict):
        raise QueueError(f"{physical_id} has no current_identity")
    trajectory = identity.get("trajectory")
    conversion = identity.get("conversion_report")
    if not isinstance(trajectory, dict) or not isinstance(conversion, dict):
        raise QueueError(f"{physical_id} has incomplete trajectory/conversion identity")
    # Do not stat or open the large source files while preparing a queue.  The
    # coverage producer already registered their path/size/digest; the shared
    # v4 guard revalidates existence, size and digest at launch and completion.
    h5_path = str(trajectory.get("path", "")).strip()
    conversion_path = str(conversion.get("path", "")).strip()
    if not h5_path or not conversion_path:
        raise QueueError(f"{physical_id} has an empty trajectory/conversion path")
    h5_bytes = int(trajectory.get("bytes", -1))
    conversion_bytes = int(conversion.get("bytes", -1))
    if h5_bytes < 0 or conversion_bytes < 0:
        raise QueueError(f"{physical_id} has invalid source byte declarations")
    h5_sha = str(trajectory.get("producer_declared_sha256", ""))
    conversion_sha = str(conversion.get("sha256", conversion.get("expected_sha256", "")))
    if len(h5_sha) != 64 or len(conversion_sha) != 64:
        raise QueueError(f"{physical_id} lacks source digest declarations")
    return {
        "physical_case_id": physical_id,
        "trajectory": {
            "path": h5_path,
            "bytes": h5_bytes,
            "sha256": h5_sha,
            "sha256_origin": "coverage current_identity.trajectory.producer_declared_sha256",
        },
        "conversion_report": {
            "path": conversion_path,
            "bytes": conversion_bytes,
            "sha256": conversion_sha,
            "sha256_origin": "coverage current_identity.conversion_report.sha256",
        },
    }


def small_input_hashes(script: Path, coverage_path: Path) -> dict[str, str]:
    files = [
        script,
        script.with_name("ds_data02_batch_runner.py"),
        script.with_name("ds_data02_batch_runner_v4.py"),
        script.with_name("ds_data02_runtime_v2.py"),
        script.with_name("ds_data02_runtime_v4.py"),
        script.with_name("ds_data02_stage2_dispatch_v4.py"),
        script.with_name("ds_data02_strict_dispatch_v4.py"),
        coverage_path,
        VENV_PYTHON,
    ]
    expected: dict[str, str] = {}
    for path in files:
        path = require_file(path, "static queue input")
        expected[str(path)] = sha256(path)
    return expected


def static_inputs(
    script: Path,
    coverage_path: Path,
    pair_rows: list[dict[str, Any]],
    small_hashes: dict[str, str],
) -> tuple[list[str], dict[str, str]]:
    files = [Path(value) for value in small_hashes]
    expected = dict(small_hashes)
    for pair in pair_rows:
        trajectory = pair["trajectory"]
        conversion = pair["conversion_report"]
        files.extend([Path(trajectory["path"]), Path(conversion["path"])])
        # The H5 is deliberately not rehashed during queue construction.  The
        # declared producer digest is a strict expected input digest; v4 guard
        # recomputes it before launch and at completion.
        expected[trajectory["path"]] = trajectory["sha256"]
        expected[conversion["path"]] = conversion["sha256"]
    # The paths in CURRENT coverage are already absolute.  Preserve them
    # verbatim for large inputs and only resolve the small local inputs above.
    unique = list(dict.fromkeys(
        str(path.resolve()) if index < 9 else str(path)
        for index, path in enumerate(files)
    ))
    if set(unique) != set(expected):
        raise QueueError("queue input/hash set is inconsistent")
    return unique, expected


def build_request(
    *,
    coverage_path: Path,
    coverage_schema: str,
    script: Path,
    pair_rows: list[dict[str, Any]],
    family: str,
    ordinal: int,
    output_dir: Path,
    small_hashes: dict[str, str],
) -> dict[str, Any]:
    case_ids = [row["physical_case_id"] for row in pair_rows]
    request_id = f"static-per-mk-h5-{family.lower()}-{ordinal:03d}-v1"
    input_files, input_sha256 = static_inputs(script, coverage_path, pair_rows, small_hashes)
    h5_bytes = {row["physical_case_id"]: int(row["trajectory"]["bytes"]) for row in pair_rows}
    total_h5 = sum(h5_bytes.values())
    command = [
        str(VENV_PYTHON),
        str(script),
        "--coverage", str(coverage_path),
    ]
    for case_id in case_ids:
        command.extend(["--case-id", case_id])
    command.extend(["--output", "{attempt_root}/static-per-mk-h5.json"])
    return {
        "family_id": "infra",
        "case_id": f"STAGE2_STATIC_PER_MK_H5_{family}_{ordinal:03d}",
        "attempt_id": request_id,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(script.parent),
        "worktree_root": str(script.parents[2]),
        "command": command,
        "input_files": input_files,
        "input_sha256": input_sha256,
        "source_read_cost": {
            "selected_case_count": len(pair_rows),
            "trajectory_h5_bytes": h5_bytes,
            "trajectory_h5_total_bytes": total_h5,
            "parent_pre_hash_bytes": total_h5,
            "parent_post_hash_bytes": total_h5,
            "parent_pre_post_hash_bytes": 2 * total_h5,
            "initial_dataset_read_only": True,
            "trajectory_frames_read": False,
        },
        "source_binding": {
            "coverage": {"path": str(coverage_path), "schema": coverage_schema, "sha256": input_sha256[str(coverage_path)]},
            "case_ids": case_ids,
            "trajectory_digest_provenance": "coverage producer declaration; v4 guard must rehash launch/end",
            "conversion_digest_provenance": "coverage current conversion report SHA; v4 guard must rehash launch/end",
        },
        "request_note": (
            "Unlaunched bounded static initial-H5 per-source-MK request for exact CURRENT cases. "
            "Reads only particle_id/particle_zone/initial_type/initial_mk/initial_mass; no trajectory frames, "
            "scientific scan, decoder, solver, CFD, or model. Physical fate, spill/domain interpretation, "
            "dynamics, QN, and QE remain UNKNOWN. H5 content is not hashed during queue preparation; shared "
            "v4 guard must validate the registered producer digest before any execution."
        ),
        "queue_status": "UNLAUNCHED_REQUEST",
        "queue_output_path": None,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    coverage_path, coverage = read_json(args.coverage, "coverage index")
    rows = indexed_rows(coverage)
    script = require_file(args.script, "static audit v2 script")
    if not VENV_PYTHON.is_file():
        raise QueueError(f"fixed interpreter is missing: {VENV_PYTHON}")
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    small_hashes = small_input_hashes(script, coverage_path)
    requests: list[dict[str, Any]] = []
    family_summary: dict[str, Any] = {}
    for family in ("F2", "F4", "F6"):
        family_rows = [source_pair(row) for row in rows.values() if str(row["family_id"]) == family]
        family_rows.sort(key=lambda row: row["physical_case_id"])
        family_requests = []
        for start in range(0, len(family_rows), MAX_CASES_PER_REQUEST):
            pair = family_rows[start:start + MAX_CASES_PER_REQUEST]
            ordinal = start // MAX_CASES_PER_REQUEST + 1
            request = build_request(
                coverage_path=coverage_path,
                coverage_schema=str(coverage["schema"]),
                script=script,
                pair_rows=pair,
                family=family,
                ordinal=ordinal,
                output_dir=output_dir,
                small_hashes=small_hashes,
            )
            request_path = output_dir / f"static-per-mk-h5-{family.lower()}-{ordinal:03d}-v1.json"
            if args.write_requests:
                request["queue_output_path"] = str(request_path.resolve())
                atomic_json(request_path, request)
            family_requests.append({
                "request_path": str(request_path.resolve()) if args.write_requests else None,
                "case_ids": request["source_binding"]["case_ids"],
                "trajectory_h5_total_bytes": request["source_read_cost"]["trajectory_h5_total_bytes"],
                "parent_pre_post_hash_bytes": request["source_read_cost"]["parent_pre_post_hash_bytes"],
                "status": request["queue_status"],
            })
            requests.append(request)
        family_summary[family] = {
            "case_count": len(family_rows),
            "request_count": len(family_requests),
            "requests": family_requests,
        }
    total_h5 = sum(item["source_read_cost"]["trajectory_h5_total_bytes"] for item in requests)
    manifest = {
        "schema": "ds02.stage2.static-per-mk-h5-queue.v1",
        "purpose": "Bounded family-local initial-H5 per-source-MK audit queue for exact CURRENT F2/F4/F6 cases.",
        "generator": {
            "path": str(Path(__file__).resolve()),
            "sha256": sha256(Path(__file__).resolve()),
            "coverage": {"path": str(coverage_path), "sha256": sha256(coverage_path), "schema": coverage["schema"]},
            "h5_content_hashed_during_generation": False,
            "h5_stat_only_during_generation": True,
            "launch_guard_revalidates_h5_digest": True,
        },
        "queue_policy": {
            "max_cases_per_request": MAX_CASES_PER_REQUEST,
            "family_local_batches": True,
            "batch_count": len(requests),
            "case_count": len(rows),
            "all_requests_unlaunched": True,
            "no_trajectory_frames": True,
            "physical_fate": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "aggregate_source_read_cost": {
            "trajectory_h5_total_bytes": total_h5,
            "parent_pre_post_hash_bytes": 2 * total_h5,
            "initial_dataset_only": True,
        },
        "family_summary": family_summary,
        "requests": requests,
    }
    atomic_json(args.manifest.resolve(), manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument(
        "--script", type=Path,
        default=Path(__file__).with_name("ds_data02_stage2_static_per_mk_h5_audit_v2.py"),
    )
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument(
        "--write-requests", action="store_true",
        help="also materialize one JSON request per bounded pair; omitted by default to keep preparation metadata-only",
    )
    args = parser.parse_args()
    try:
        result = build(args)
    except QueueError as exc:
        raise SystemExit(f"QueueError: {exc}")
    print(json.dumps({
        "status": "completed",
        "schema": result["schema"],
        "batch_count": result["queue_policy"]["batch_count"],
        "case_count": result["queue_policy"]["case_count"],
        "output": str(args.manifest.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
