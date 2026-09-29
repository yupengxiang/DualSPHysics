#!/usr/bin/env python3
"""Fail-closed, read-only intake for the completed F3 material coarse s4 run.

The scheduler-owned attempt is intentionally treated as a diagnostic runtime
reference.  This module binds the terminal JSON and scheduler artifact hashes
without opening the native source HDF5, mutating the attempt, or touching any
Core registry, ledger, denominator, gate, completion, or qualification state.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
from typing import Any, Mapping, Sequence


LAB_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "core.material.f3.coarse.s4.terminal_result_intake.v1"
REPORT_SCHEMA = "core.material.f3.coarse.s4.terminal_result_intake_report.v1"
RECORD_ID = "f3-material-coarse-s4-terminal-result-intake-2026-09-29-rerun1"

ATTEMPT_RELATIVE = Path(
    "campaigns/core-v1/runtime/attempts/core-f3-material-coarse-s4-rerun1/"
    "20260929T122756-ab18fca003d8"
)
ATTEMPT_ID = ATTEMPT_RELATIVE.name
ATTEMPT_ROOT_ID = ATTEMPT_RELATIVE.parent.name
JOB_ID = "core-f3-material-coarse-s4-rerun1"
LOGICAL_ID = "CORE-F3-MATERIAL-COARSE-s4-RERUN1"
EXPECTED_SOURCE_SNAPSHOT_SHA256 = "1ce54606f2922ac4a2aeb3b04dc97e4d4f70b09541ffd77f2515bdfce5d56e69"
EXPECTED_SOURCE_INPUT_SHA256 = "3d178d8c5e6ee4057a10a384c9289df5723bcabbfe58850803cf54996c4a9575"
EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX = (
    "/campaigns/core-v1/runtime/snapshots/"
    "1ce54606f2922ac4a2aeb3b04dc97e4d4f70b09541ffd77f2515bdfce5d56e69/"
    "lagrangian-fluid-lab"
)
EXPECTED_FRAME_COUNT = 836
EXPECTED_TRANSITION_COUNT = 835
UNKNOWN_LIMIT = 0.01
MASS_CLOSURE_ERROR_LIMIT = 1.0e-12
MAX_JSON_BYTES = 16 * 1024 * 1024
MAX_ARTIFACT_BYTES = 1024 * 1024 * 1024
SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")

REQUIRED_JSON_FILES = ("result.json", "spec.json", "material.json")
IDENTITY_JSON_FILES = ("launch.json", "heartbeat.json")
REQUIRED_ARTIFACTS = (
    "material.h5",
    "material.json",
    "material.h5.checkpoint.npz",
    "material.h5.checkpoint.json",
)

# These are the terminal bytes observed from the actual scheduler attempt.
# Keeping the three intake inputs pinned makes a checked-in report fail closed
# if the ignored runtime directory is later replaced by a different attempt.
EXPECTED_FILE_BINDINGS = {
    "result.json": (3406, "377dfa41e77e015225add266e9f4849cb20fed60da7ea2688c2f74c787ff37c5"),
    "spec.json": (4891, "bfac635a316a62734bb22276b91263ff5d967fd2d9a8773221eaa91afcf710c2"),
    "material.json": (81926, "0e31b456ba1ba24ac19bd57159486f679b871dad0556a3e2031fe789bfa709e3"),
    "launch.json": (214, "2c3698dce0585c2df396adba7c7ed504996a477f188d072dc79774b073605eab"),
    "heartbeat.json": (421, "10c5a78231c140020f467c4372732e9367b423efa219623fc1424b5fa4ac0de6"),
}

EXPECTED_INPUTS = {
    "read_only_coarse_native_source": EXPECTED_SOURCE_INPUT_SHA256,
    "runtime_contract": "06c2d549d971d679f48b0d46480a7decc64d1ab58a3e35ece8cb5a61a04a1aa9",
    "current_worker_entrypoint_source": "9e294e64c431c725717caf86eb001dc3a3505a312e279386796b6a472b5ee94e",
    "current_scheduler_runtime_source": "a4c6e03a13cb1ff80c0da7f7f9bd442e5e2de4d64e23551bf92a0220c6afa8c4",
    "immutable_historical_lineage_spec": "89a376b36c3d8c31c8b050b6bbd5a3aa6014d1877c7d7d918ed7cb4eeb889c1b",
}

DEFAULT_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-S4-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.json"
)
DEFAULT_ZH_REPORT = Path(
    "reports/F3-MATERIAL-COARSE-S4-TERMINAL-RESULT-INTAKE-2026-09-29-RERUN1.zh-CN.md"
)


class IntakeError(ValueError):
    """Raised when bounded intake input is malformed."""


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _sha256(value: Any) -> bool:
    return isinstance(value, str) and SHA256_RE.fullmatch(value) is not None


def _reject_constant(token: str) -> Any:
    raise IntakeError(f"non-finite JSON number: {token}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IntakeError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _relative(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _safe_relative(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = Path(value)
    return not path.is_absolute() and ".." not in path.parts and "" not in path.parts


def _stable_bytes(path: Path, *, limit: int) -> tuple[bytes | None, dict[str, Any], str | None]:
    """Read a regular file once and reject a replacement during the read."""

    try:
        before = os.lstat(path)
    except OSError as error:
        return None, {"path": str(path), "exists": False, "bytes": None, "sha256": None}, f"lstat:{type(error).__name__}"
    if not os.path.isfile(path) or os.path.islink(path):
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, "not_a_regular_non_symlink_file"
    if before.st_size > limit:
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, "file_exceeds_bound"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
        with os.fdopen(fd, "rb", closefd=True) as stream:
            raw = stream.read(limit + 1)
            descriptor = os.fstat(stream.fileno())
    except OSError as error:
        return None, {"path": str(path), "exists": True, "bytes": before.st_size, "sha256": None}, f"read:{type(error).__name__}"
    if len(raw) > limit:
        return None, {"path": str(path), "exists": True, "bytes": len(raw), "sha256": None}, "file_exceeds_bound"
    try:
        after = os.lstat(path)
    except OSError as error:
        return None, {"path": str(path), "exists": True, "bytes": len(raw), "sha256": None}, f"post_lstat:{type(error).__name__}"
    stable = (
        descriptor.st_dev == before.st_dev
        and descriptor.st_ino == before.st_ino
        and descriptor.st_size == before.st_size == len(raw)
        and after.st_dev == before.st_dev
        and after.st_ino == before.st_ino
        and after.st_size == before.st_size
        and after.st_mtime_ns == before.st_mtime_ns
        and after.st_ctime_ns == before.st_ctime_ns
    )
    reference = {
        "path": str(path),
        "exists": True,
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "content_read": True,
        "stable_read": stable,
    }
    if not stable:
        return None, reference, "path_changed_during_read"
    return raw, reference, None


def _read_json(path: Path) -> tuple[Mapping[str, Any] | None, dict[str, Any], str | None]:
    raw, reference, error = _stable_bytes(path, limit=MAX_JSON_BYTES)
    if error is not None or raw is None:
        return None, reference, error
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, IntakeError) as exc:
        return None, reference, f"json:{type(exc).__name__}:{exc}"
    if not isinstance(value, Mapping):
        return None, reference, "json:top_level_not_object"
    return value, reference, None


def _attempt_path(root: Path, attempt: str | Path) -> tuple[Path, str]:
    relative = Path(attempt)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise IntakeError("attempt path must be a safe repository-relative path")
    return root / relative, relative.as_posix()


def _check(name: str, passed: bool, reason: str, observed: Any = None, expected: Any = None) -> dict[str, Any]:
    return {"check": name, "passed": bool(passed), "reason": reason, "observed": observed, "expected": expected}


def _required_ref_shape(value: Any, label: str, errors: list[str]) -> None:
    ref = _mapping(value)
    for key in ("path", "bytes", "sha256"):
        if key not in ref:
            errors.append(f"{label}.{key}")
    if not isinstance(ref.get("path"), str) or not ref.get("path"):
        errors.append(f"{label}.path")
    if not isinstance(ref.get("bytes"), int) or isinstance(ref.get("bytes"), bool) or ref.get("bytes", -1) < 0:
        errors.append(f"{label}.bytes")
    if not _sha256(ref.get("sha256")):
        errors.append(f"{label}.sha256")


def _file_ref(root: Path, attempt_root: Path, name: str, role: str) -> tuple[dict[str, Any], Mapping[str, Any] | None, str | None]:
    value, reference, error = _read_json(attempt_root / name)
    reference = dict(reference)
    reference["path"] = _relative(root, attempt_root / name)
    reference["role"] = role
    expected = EXPECTED_FILE_BINDINGS.get(name)
    reference["expected_bytes"] = expected[0] if expected else None
    reference["expected_sha256"] = expected[1] if expected else None
    reference["expected_binding_match"] = (
        expected is not None
        and reference.get("bytes") == expected[0]
        and reference.get("sha256") == expected[1]
    )
    return reference, value, error


def _normalize_argv(argv: Any, attempt_root: Path) -> list[str] | None:
    if not isinstance(argv, list) or not all(isinstance(item, str) for item in argv):
        return None
    output_path = str(attempt_root / "material.h5")
    return ["{attempt_dir}/material.h5" if item == output_path else item for item in argv]


def _source_projection(spec: Mapping[str, Any], result: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    spec_snapshot = _mapping(spec.get("source_snapshot"))
    result_snapshot = _mapping(result.get("source_snapshot"))
    inputs = spec.get("input_files")
    rows = [item for item in inputs if isinstance(item, Mapping)] if isinstance(inputs, list) else []
    source_rows = [item for item in rows if item.get("role") == "read_only_coarse_native_source"]
    source = source_rows[0] if len(source_rows) == 1 else {}
    input_projection = [
        {
            "role": item.get("role"),
            "path": item.get("path"),
            "sha256": item.get("sha256"),
            "hash_recomputed": False,
        }
        for item in rows
    ]
    runtime = {
        role: next((item.get("sha256") for item in rows if item.get("role") == role), None)
        for role in EXPECTED_INPUTS
    }
    source_projection = {
        "source_snapshot": {
            "path": spec_snapshot.get("path"),
            "sha256": spec_snapshot.get("sha256"),
            "result_path": result_snapshot.get("path"),
            "result_sha256": result_snapshot.get("sha256"),
        },
        "source_input": {
            "path": source.get("path"),
            "role": source.get("role"),
            "sha256": source.get("sha256"),
            "opened": False,
            "read": False,
            "hash_recomputed": False,
        },
        "input_files": input_projection,
        "runtime_sha256": runtime,
        "source_hdf5_hash_recomputed": False,
    }
    spec_source = None
    result_source = None
    for argv, target in ((spec.get("argv"), "spec"), (result.get("argv"), "result")):
        if isinstance(argv, list) and "--source" in argv:
            index = argv.index("--source") + 1
            if index < len(argv):
                if target == "spec":
                    spec_source = argv[index]
                else:
                    result_source = argv[index]
    checks = [
        _check(
            "source_snapshot_sha_bound",
            source_projection["source_snapshot"]["sha256"]
            == source_projection["source_snapshot"]["result_sha256"]
            == EXPECTED_SOURCE_SNAPSHOT_SHA256,
            "spec and result must bind the same current snapshot SHA",
            observed=source_projection["source_snapshot"],
            expected=EXPECTED_SOURCE_SNAPSHOT_SHA256,
        ),
        _check(
            "source_snapshot_path_bound",
            source_projection["source_snapshot"]["path"]
            == source_projection["source_snapshot"]["result_path"]
            and isinstance(source_projection["source_snapshot"]["path"], str)
            and source_projection["source_snapshot"]["path"].endswith(EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX),
            "snapshot path must agree in spec and result and identify the pinned snapshot",
            observed=source_projection["source_snapshot"],
            expected=EXPECTED_SOURCE_SNAPSHOT_PATH_SUFFIX,
        ),
        _check(
            "source_input_sha_bound",
            source_projection["source_input"]["sha256"] == EXPECTED_SOURCE_INPUT_SHA256,
            "the read-only native source must carry the expected input SHA claim",
            observed=source_projection["source_input"],
            expected=EXPECTED_SOURCE_INPUT_SHA256,
        ),
        _check(
            "source_input_argv_bound",
            source_projection["source_input"]["path"] == spec_source == result_source,
            "spec input and both argv records must name the same native source",
            observed={"input": source_projection["source_input"]["path"], "spec_argv": spec_source, "result_argv": result_source},
            expected="one identical source path",
        ),
        _check(
            "source_input_read_boundary",
            source_projection["source_input"]["opened"] is False
            and source_projection["source_input"]["read"] is False
            and source_projection["source_input"]["hash_recomputed"] is False,
            "intake must not open or rehash the native source HDF5",
            observed=source_projection["source_input"],
            expected={"opened": False, "read": False, "hash_recomputed": False},
        ),
        _check(
            "runtime_input_shas_bound",
            all(source_projection["runtime_sha256"].get(role) == expected for role, expected in EXPECTED_INPUTS.items()),
            "worker, scheduler, contract, and historical lineage SHA claims must remain pinned",
            observed=source_projection["runtime_sha256"],
            expected=EXPECTED_INPUTS,
        ),
    ]
    return source_projection, checks


def _identity_projection(
    root: Path,
    attempt_root: Path,
    spec: Mapping[str, Any],
    result: Mapping[str, Any],
    launch: Mapping[str, Any],
    heartbeat: Mapping[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    worker = _mapping(launch.get("worker_identity"))
    heartbeat_worker = _mapping(heartbeat.get("worker_identity"))
    child = _mapping(heartbeat.get("child_identity"))
    spec_allocation = _mapping(spec.get("allocation"))
    result_allocation = _mapping(result.get("allocation"))
    identity = {
        "job_id": JOB_ID,
        "attempt_id": ATTEMPT_ID,
        "attempt_root_id": ATTEMPT_ROOT_ID,
        "host": spec.get("host"),
        "spec_allocation_host": spec_allocation.get("_host"),
        "result_allocation_host": result_allocation.get("_host"),
        "gpu_uuid": result_allocation.get("gpu_uuid"),
        "reserved_gpu_mib": result_allocation.get("reserved_gpu_mib"),
        "worker": {
            "boot_id": worker.get("boot_id"),
            "pid": worker.get("pid"),
            "start_ticks": worker.get("start_ticks"),
        },
        "heartbeat_worker": {
            "boot_id": heartbeat_worker.get("boot_id"),
            "pid": heartbeat_worker.get("pid"),
            "start_ticks": heartbeat_worker.get("start_ticks"),
        },
        "child": {
            "boot_id": child.get("boot_id"),
            "pid": child.get("pid"),
            "start_ticks": child.get("start_ticks"),
        },
        "launch_job_id": launch.get("job_id"),
        "namespace": _mapping(spec.get("namespace")),
    }
    checks = [
        _check(
            "scheduler_job_identity",
            result.get("job_id") == spec.get("job_id") == launch.get("job_id") == JOB_ID,
            "result, spec, and launch identity must carry the requested job",
            observed={"result": result.get("job_id"), "spec": spec.get("job_id"), "launch": launch.get("job_id")},
            expected=JOB_ID,
        ),
        _check(
            "scheduler_attempt_identity",
            _mapping(spec.get("namespace")).get("attempt_root") == ATTEMPT_RELATIVE.parent.as_posix()
            and _mapping(spec.get("namespace")).get("template") == ATTEMPT_RELATIVE.parent.as_posix() + "/<fresh-attempt-id>"
            and _mapping(spec.get("namespace")).get("attempt_id_source") == "scheduler_generated"
            and _mapping(spec.get("namespace")).get("fresh_required") is True
            and _mapping(spec.get("namespace")).get("historical_reuse_forbidden") is True,
            "the path must be the fresh scheduler-generated s4 attempt namespace",
            observed={"attempt_id": ATTEMPT_ID, "namespace": _mapping(spec.get("namespace"))},
            expected={"attempt_root": ATTEMPT_RELATIVE.parent.as_posix(), "attempt_id_source": "scheduler_generated"},
        ),
        _check(
            "worker_identity_bound",
            all(isinstance(worker.get(key), (str, int)) and worker.get(key) not in (None, "") for key in ("boot_id", "pid", "start_ticks"))
            and worker == heartbeat_worker
            and child.get("boot_id") == worker.get("boot_id"),
            "launch and terminal heartbeat must bind one worker identity",
            observed={"launch": worker, "heartbeat_worker": heartbeat_worker, "child": child},
            expected="same worker boot/pid/start identity",
        ),
        _check(
            "host_identity_bound",
            spec.get("host") == spec_allocation.get("_host") == result_allocation.get("_host") == "ada",
            "spec and result allocation must agree on the scheduler host",
            observed={"spec_host": spec.get("host"), "spec_allocation": spec_allocation.get("_host"), "result_allocation": result_allocation.get("_host")},
            expected="ada",
        ),
        _check(
            "cpu_only_allocation",
            result_allocation.get("gpu_uuid") is None and result_allocation.get("reserved_gpu_mib") == 0,
            "this s4 diagnostic receipt must remain CPU-only",
            observed=result_allocation,
            expected={"gpu_uuid": None, "reserved_gpu_mib": 0},
        ),
    ]
    return identity, checks


def _execution_projection(result: Mapping[str, Any], spec: Mapping[str, Any], attempt_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    required_outputs = spec.get("required_outputs")
    result_outputs = result.get("outputs")
    normalized_result_argv = _normalize_argv(result.get("argv"), attempt_root)
    checks = [
        _check(
            "execution_receipt_success",
            result.get("schema") == "core.execution_receipt.v1"
            and result.get("execution_status") == "succeeded"
            and result.get("returncode") == 0
            and result.get("error") is None
            and result.get("timeout") is False
            and result.get("missing_outputs") == [],
            "scheduler terminal receipt must be successful, non-timeout, and zero-return",
            observed={key: result.get(key) for key in ("schema", "execution_status", "returncode", "error", "timeout", "missing_outputs")},
            expected={"schema": "core.execution_receipt.v1", "execution_status": "succeeded", "returncode": 0},
        ),
        _check(
            "required_outputs_complete",
            isinstance(required_outputs, list)
            and set(required_outputs) == set(REQUIRED_ARTIFACTS)
            and isinstance(result_outputs, list)
            and {item.get("path") for item in result_outputs if isinstance(item, Mapping)} >= set(REQUIRED_ARTIFACTS),
            "the successful receipt must retain all required material outputs",
            observed={"spec": required_outputs, "result": result_outputs},
            expected=list(REQUIRED_ARTIFACTS),
        ),
        _check(
            "argv_cwd_bound",
            normalized_result_argv is not None
            and normalized_result_argv == spec.get("argv")
            and spec.get("cwd") == str(LAB_ROOT)
            and normalized_result_argv[0] == str(LAB_ROOT / ".venv/bin/python"),
            "terminal argv must normalize exactly to the submitted spec and lab cwd",
            observed={"spec_argv": spec.get("argv"), "result_argv": normalized_result_argv, "cwd": spec.get("cwd")},
            expected={"cwd": str(LAB_ROOT), "output": "{attempt_dir}/material.h5"},
        ),
    ]
    projection = {
        "schema": result.get("schema"),
        "status": result.get("execution_status"),
        "returncode": result.get("returncode"),
        "timeout": result.get("timeout"),
        "missing_outputs": result.get("missing_outputs"),
        "job_id": result.get("job_id"),
        "attempt_id": ATTEMPT_ID,
        "logical_id": spec.get("logical_id"),
        "argv": normalized_result_argv,
        "cwd": spec.get("cwd"),
        "scientific_status": result.get("scientific_status"),
        "started": result.get("started"),
        "finished": result.get("finished"),
        "usage": result.get("usage"),
        "source_snapshot_sha256": _mapping(result.get("source_snapshot")).get("sha256"),
    }
    return projection, checks


def _material_projection(material: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    rows = material.get("by_source") if isinstance(material.get("by_source"), list) else []
    sources: list[dict[str, Any]] = []
    errors: list[str] = []
    for index, value in enumerate(rows):
        row = _mapping(value)
        categories = _mapping(row.get("terminal_categories"))
        category_values = {key: categories.get(key) for key in ("left", "right", "unknown")}
        category_sum = sum(float(item) for item in category_values.values()) if all(_finite_number(item) for item in category_values.values()) else None
        source = {
            "source": row.get("source"),
            "initial_mass_fraction": row.get("initial_mass_fraction"),
            "mass_closure_fraction": row.get("mass_closure_fraction"),
            "mass_closure_error": row.get("mass_closure_error"),
            "terminal_categories": category_values,
            "terminal_category_sum": category_sum,
            "terminal_mass_vector_length": len(row.get("terminal", [])) if isinstance(row.get("terminal"), list) else None,
            "terminal_upper_vector_length": len(row.get("terminal_upper", [])) if isinstance(row.get("terminal_upper"), list) else None,
            "unknown_fraction": row.get("unknown_fraction"),
            "unknown_fraction_max": row.get("unknown_fraction_max"),
            "unknown_first_passage_fraction_max": row.get("unknown_first_passage_fraction_max"),
            "unknown_fraction_monotone": row.get("unknown_fraction_monotone"),
            "reliable_path_coverage": row.get("reliable_path_coverage"),
            "final_unknown_fraction": row.get("final_unknown_fraction"),
            "first_unreliable_frame": row.get("first_unreliable_frame"),
            "first_unreliable_time_s": row.get("first_unreliable_time_s"),
            "observed_first_passage_fraction": row.get("observed_first_passage_fraction"),
            "observed_return_fraction": row.get("observed_return_fraction"),
            "residence_right_censored_unknown_mass_fraction": row.get("residence_right_censored_unknown_mass_fraction"),
        }
        sources.append(source)
        if source["source"] != index:
            errors.append(f"source_{index}.identity")
    mass_rows_valid = len(sources) == 2 and [row.get("source") for row in sources] == [0, 1]
    per_source_mass = all(
        _finite_number(row.get("mass_closure_fraction"))
        and abs(float(row["mass_closure_fraction"]) - 1.0) <= MASS_CLOSURE_ERROR_LIMIT
        and _finite_number(row.get("mass_closure_error"))
        and abs(float(row["mass_closure_error"])) <= MASS_CLOSURE_ERROR_LIMIT
        and _finite_number(row.get("terminal_category_sum"))
        and abs(float(row["terminal_category_sum"]) - 1.0) <= MASS_CLOSURE_ERROR_LIMIT
        and row.get("terminal_mass_vector_length") == 2
        and row.get("terminal_upper_vector_length") == 2
        for row in sources
    )
    unknown_values = [row.get("unknown_fraction_max") for row in sources]
    unknown_valid = bool(unknown_values) and all(_finite_number(value) and 0.0 <= float(value) <= 1.0 for value in unknown_values)
    unknown_max = max((float(value) for value in unknown_values), default=None) if unknown_valid else None
    coverage_values = [row.get("reliable_path_coverage") for row in sources]
    coverage_valid = bool(coverage_values) and all(_finite_number(value) and 0.0 <= float(value) <= 1.0 for value in coverage_values)
    weights = [row.get("initial_mass_fraction") for row in sources]
    weighted_coverage = (
        sum(float(weight) * float(row["reliable_path_coverage"]) for weight, row in zip(weights, sources))
        if coverage_valid and all(_finite_number(weight) for weight in weights)
        else None
    )
    top_coverage = material.get("common_reliable_path_coverage")
    projection = {
        "schema": material.get("schema"),
        "status": material.get("status"),
        "native_frame_count": material.get("native_frame_count"),
        "committed_frame": material.get("committed_frame"),
        "transition_count": material.get("native_frame_count") - 1 if isinstance(material.get("native_frame_count"), int) else None,
        "committed_transition": material.get("committed_frame"),
        "committed_time_s": material.get("committed_time_s"),
        "elapsed_seconds": material.get("elapsed_seconds"),
        "max_rss_kib": material.get("max_rss_kib"),
        "source_count": len(sources),
        "sources": sources,
        "mass_closed": material.get("mass_closed"),
        "unknown_fraction_monotone": material.get("unknown_fraction_monotone"),
        "unknown_gate_pass": material.get("unknown_gate_pass"),
        "unknown_fraction_max": unknown_max,
        "unknown_fraction_limit": UNKNOWN_LIMIT,
        "common_reliable_path_coverage": top_coverage,
        "coverage_weighted_from_sources": weighted_coverage,
        "material_reliability": material.get("material_reliability"),
        "qualification_claim": material.get("qualification_claim"),
        "qualified_T2_macro": material.get("qualified_T2_macro"),
        "qualified_T2_path": material.get("qualified_T2_path"),
    }
    checks = [
        _check("material_status_completed", material.get("status") == "completed", "material sidecar must be terminally completed", material.get("status"), "completed"),
        _check(
            "full_frame_transition_semantics",
            material.get("native_frame_count") == EXPECTED_FRAME_COUNT
            and material.get("committed_frame") == EXPECTED_TRANSITION_COUNT
            and material.get("native_frame_count") - 1 == EXPECTED_TRANSITION_COUNT,
            "the terminal material sidecar must preserve all native frames and transitions",
            {"native_frame_count": material.get("native_frame_count"), "committed_frame": material.get("committed_frame")},
            {"native_frame_count": EXPECTED_FRAME_COUNT, "transition_count": EXPECTED_TRANSITION_COUNT},
        ),
        _check("mass_closure", material.get("mass_closed") is True and mass_rows_valid and per_source_mass, "top-level and per-source mass must close", {"mass_closed": material.get("mass_closed"), "sources": sources}, True),
        _check(
            "unknown_monotonicity",
            material.get("unknown_fraction_monotone") is True and bool(sources) and all(row.get("unknown_fraction_monotone") is True for row in sources),
            "top-level and every source must report monotone unknown accumulation",
            {"top": material.get("unknown_fraction_monotone"), "sources": [row.get("unknown_fraction_monotone") for row in sources]},
            True,
        ),
        _check(
            "unknown_gate",
            unknown_valid and material.get("unknown_gate_pass") is (unknown_max is not None and unknown_max <= UNKNOWN_LIMIT),
            "the 1% gate must be internally consistent with the observed terminal maximum",
            {"max": unknown_max, "limit": UNKNOWN_LIMIT, "declared_pass": material.get("unknown_gate_pass")},
            {"max_at_most": UNKNOWN_LIMIT, "declared_pass": False},
        ),
        _check(
            "coverage",
            _finite_number(top_coverage)
            and 0.0 <= float(top_coverage) <= 1.0
            and weighted_coverage is not None
            and abs(float(top_coverage) - weighted_coverage) <= MASS_CLOSURE_ERROR_LIMIT,
            "common reliable coverage must agree with the initial-mass weighted source coverage",
            {"top": top_coverage, "weighted_from_sources": weighted_coverage, "per_source": coverage_values},
            "finite [0,1] and weighted aggregate",
        ),
        _check(
            "diagnostic_non_qualification_boundary",
            material.get("qualification_claim") == "none" and material.get("qualified_T2_macro") is False and material.get("qualified_T2_path") is False,
            "the material terminal result must not claim qualification",
            {"qualification_claim": material.get("qualification_claim"), "qualified_T2_macro": material.get("qualified_T2_macro"), "qualified_T2_path": material.get("qualified_T2_path")},
            {"qualification_claim": "none", "qualified_T2_macro": False, "qualified_T2_path": False},
        ),
    ]
    errors.extend(check["check"] for check in checks if not check["passed"] and check["check"] != "unknown_gate")
    return projection, checks, errors


def _artifact_projection(attempt_root: Path, result: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    entries = result.get("artifact_index")
    if not isinstance(entries, list):
        return [], [], ["artifact_index.not_list"]
    projection: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(entries):
        entry = _mapping(value)
        path_value = entry.get("path")
        if not _safe_relative(path_value) or path_value in seen:
            errors.append(f"artifact_index[{index}].path")
            continue
        seen.add(path_value)
        raw, actual, read_error = _stable_bytes(attempt_root / path_value, limit=MAX_ARTIFACT_BYTES)
        match = read_error is None and raw is not None and entry.get("bytes") == actual.get("bytes") and entry.get("sha256") == actual.get("sha256") and _sha256(entry.get("sha256"))
        projection.append(
            {
                "path": path_value,
                "declared_bytes": entry.get("bytes"),
                "declared_sha256": entry.get("sha256"),
                "actual_bytes": actual.get("bytes"),
                "actual_sha256": actual.get("sha256"),
                "stable_read": actual.get("stable_read") is True,
                "read_error": read_error,
                "hash_match": match,
            }
        )
        if not match:
            errors.append(f"artifact_index[{index}].hash")
    required_present = {row["path"] for row in projection} >= set(REQUIRED_ARTIFACTS)
    checks = [
        _check(
            "artifact_hashes_bound",
            bool(entries) and not errors and required_present and all(row["hash_match"] for row in projection),
            "scheduler artifact-index hashes must match stable reads of the existing attempt",
            {"artifact_count": len(projection), "required_present": required_present, "errors": errors},
            {"required_artifacts": list(REQUIRED_ARTIFACTS)},
        )
    ]
    return projection, checks, errors


def _authorization() -> dict[str, Any]:
    return {
        "diagnostic_only": True,
        "formal": False,
        "formal_eligible": False,
        "launch_admitted": False,
        "qualification": False,
        "T1_numerical": False,
        "T2_macro": False,
        "T2_path": False,
        "credit": 0,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
    }


def _execution_controls() -> dict[str, Any]:
    return {
        "attempt_opened_for_write": False,
        "attempt_mutations": 0,
        "source_hdf5_opened": False,
        "source_hdf5_read": False,
        "source_hdf5_hash_recomputed": False,
        "artifact_hashes_recomputed": True,
        "solver_started": False,
        "worker_started": False,
        "gpu_started": False,
        "queue_started": False,
        "registry_mutations": 0,
        "ledger_mutations": 0,
        "denominator_mutations": 0,
        "gate_mutations": 0,
        "completion_mutations": 0,
    }


def build_report(root: Path = LAB_ROOT, attempt: str | Path = ATTEMPT_RELATIVE) -> dict[str, Any]:
    root = Path(root).resolve()
    try:
        attempt_root, attempt_relative = _attempt_path(root, attempt)
        path_error = None
    except (IntakeError, OSError) as error:
        attempt_root = root / ATTEMPT_RELATIVE
        attempt_relative = ATTEMPT_RELATIVE.as_posix()
        path_error = f"{type(error).__name__}:{error}"

    values: dict[str, Mapping[str, Any]] = {}
    file_bindings: dict[str, dict[str, Any]] = {}
    load_errors: list[str] = []
    for name in (*REQUIRED_JSON_FILES, *IDENTITY_JSON_FILES):
        reference, value, error = _file_ref(root, attempt_root, name, f"scheduler_attempt_{name.removesuffix('.json')}")
        file_bindings[name] = reference
        if value is None:
            load_errors.append(f"{name}:{error or 'missing'}")
        else:
            values[name] = value

    result = values.get("result.json", {})
    spec = values.get("spec.json", {})
    material = values.get("material.json", {})
    launch = values.get("launch.json", {})
    heartbeat = values.get("heartbeat.json", {})
    source, source_checks = _source_projection(spec, result)
    identity, identity_checks = _identity_projection(root, attempt_root, spec, result, launch, heartbeat)
    execution, execution_checks = _execution_projection(result, spec, attempt_root)
    material_terminal, material_checks, material_errors = _material_projection(material)
    artifacts, artifact_checks, artifact_errors = _artifact_projection(attempt_root, result)
    all_checks = source_checks + identity_checks + execution_checks + artifact_checks + material_checks
    all_errors = load_errors + material_errors + artifact_errors
    unknown_check = next((item for item in material_checks if item["check"] == "unknown_gate"), {"passed": False})
    unknown_max = material_terminal.get("unknown_fraction_max")
    unknown_negative = (
        _finite_number(unknown_max)
        and float(unknown_max) > UNKNOWN_LIMIT
        and unknown_check.get("passed") is True
        and material.get("unknown_gate_pass") is False
    )
    other_checks_passed = all(item["passed"] for item in all_checks if item["check"] != "unknown_gate")
    if not other_checks_passed or not unknown_negative or path_error is not None:
        status = "blocked_fail_closed"
    else:
        status = "negative_diagnostic"
    if not unknown_negative:
        all_errors.append("unknown_gate.negative_diagnostic_missing_or_inconsistent")

    report = {
        "schema": REPORT_SCHEMA,
        "record_id": RECORD_ID,
        "created_at": "2026-09-29",
        "status": status,
        "scope": {
            "family": "F3",
            "direction": "material",
            "variant": "coarse-s4",
            "candidate": LOGICAL_ID,
            "job_id": JOB_ID,
            "logical_id": LOGICAL_ID,
            "attempt_id": ATTEMPT_ID,
            "attempt_root_id": ATTEMPT_ROOT_ID,
        },
        "runtime_reference": {
            "attempt_path": attempt_relative,
            "scheduler_owned": True,
            "repository_tracked": False,
            "portable_artifact": False,
            "static_formal_receipt": False,
            "classification": "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt",
            "path_is_metadata_only_for_this_report": True,
            "historical_attempt_reused": False,
            "attempt_opened_for_write": False,
        },
        "input_bindings": {
            "result_json": file_bindings.get("result.json"),
            "spec_json": file_bindings.get("spec.json"),
            "material_json": file_bindings.get("material.json"),
            "identity_json": {name: file_bindings.get(name) for name in IDENTITY_JSON_FILES},
            "source": source,
        },
        "artifact_hashes": {
            "scheduler_artifact_index": artifacts,
            "hashes_recomputed_from_existing_attempt": True,
            "source_hdf5_hash_recomputed": False,
        },
        "scheduler_identity": identity,
        "execution_receipt": execution,
        "material_terminal": material_terminal,
        "validation": {
            "checks": all_checks,
            "errors": list(dict.fromkeys(all_errors)),
            "unknown_gate_negative_diagnostic": {
                "recorded": unknown_negative,
                "observed_unknown_fraction_max": unknown_max,
                "limit": UNKNOWN_LIMIT,
                "above_one_percent": bool(_finite_number(unknown_max) and float(unknown_max) > UNKNOWN_LIMIT),
                "message": "unknown_fraction_max exceeds 1%; retain as negative diagnostic and do not promote.",
            },
            "path_error": path_error,
        },
        "authorization": _authorization(),
        "execution_controls": _execution_controls(),
        "next_safe_action": "Use this negative diagnostic to refine F3 material coarse s4; do not promote or mutate Core state.",
    }
    return report


def validate_report(value: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if not isinstance(value, Mapping):
        return ["report.not_object"]
    if value.get("schema") != REPORT_SCHEMA:
        errors.append("report.schema")
    if value.get("record_id") != RECORD_ID:
        errors.append("report.record_id")
    if value.get("status") != "negative_diagnostic":
        errors.append("report.status")
    scope = _mapping(value.get("scope"))
    if any(scope.get(key) != expected for key, expected in {
        "family": "F3", "direction": "material", "variant": "coarse-s4", "job_id": JOB_ID,
        "logical_id": LOGICAL_ID, "attempt_id": ATTEMPT_ID, "attempt_root_id": ATTEMPT_ROOT_ID,
    }.items()):
        errors.append("report.scope")
    runtime = _mapping(value.get("runtime_reference"))
    expected_runtime = {
        "scheduler_owned": True,
        "repository_tracked": False,
        "portable_artifact": False,
        "static_formal_receipt": False,
        "classification": "scheduler_owned_runtime_receipt_reference_not_static_formal_receipt",
        "historical_attempt_reused": False,
        "attempt_opened_for_write": False,
    }
    for key, expected in expected_runtime.items():
        if runtime.get(key) != expected:
            errors.append(f"report.runtime_reference.{key}")
    if runtime.get("attempt_path") != ATTEMPT_RELATIVE.as_posix():
        errors.append("report.runtime_reference.attempt_path")

    bindings = _mapping(value.get("input_bindings"))
    for name in REQUIRED_JSON_FILES:
        label = name.removesuffix(".json") + "_json"
        ref = _mapping(bindings.get(label))
        _required_ref_shape(ref, f"input_bindings.{label}", errors)
        expected = EXPECTED_FILE_BINDINGS[name]
        if ref.get("path") != (ATTEMPT_RELATIVE / name).as_posix() or ref.get("bytes") != expected[0] or ref.get("sha256") != expected[1]:
            errors.append(f"input_bindings.{label}.binding")
        if ref.get("content_read") is not True or ref.get("stable_read") is not True or ref.get("expected_binding_match") is not True:
            errors.append(f"input_bindings.{label}.stable_read")
    identity_json = _mapping(bindings.get("identity_json"))
    for name in IDENTITY_JSON_FILES:
        ref = _mapping(identity_json.get(name))
        _required_ref_shape(ref, f"input_bindings.identity_json.{name}", errors)
        expected = EXPECTED_FILE_BINDINGS[name]
        if ref.get("path") != (ATTEMPT_RELATIVE / name).as_posix() or ref.get("bytes") != expected[0] or ref.get("sha256") != expected[1]:
            errors.append(f"input_bindings.identity_json.{name}.binding")

    source = _mapping(bindings.get("source"))
    snapshot = _mapping(source.get("source_snapshot"))
    source_input = _mapping(source.get("source_input"))
    runtime_sha = _mapping(source.get("runtime_sha256"))
    if snapshot.get("sha256") != snapshot.get("result_sha256") or snapshot.get("sha256") != EXPECTED_SOURCE_SNAPSHOT_SHA256:
        errors.append("input_bindings.source.snapshot_sha256")
    if source_input.get("sha256") != EXPECTED_SOURCE_INPUT_SHA256 or source_input.get("role") != "read_only_coarse_native_source":
        errors.append("input_bindings.source.input_sha256")
    if any(source_input.get(key) is not False for key in ("opened", "read", "hash_recomputed")):
        errors.append("input_bindings.source.read_boundary")
    if any(runtime_sha.get(role) != expected for role, expected in EXPECTED_INPUTS.items()):
        errors.append("input_bindings.source.runtime_sha256")

    identity = _mapping(value.get("scheduler_identity"))
    if identity.get("job_id") != JOB_ID or identity.get("attempt_id") != ATTEMPT_ID or identity.get("host") != "ada":
        errors.append("scheduler_identity.job_attempt_host")
    worker = _mapping(identity.get("worker"))
    heartbeat_worker = _mapping(identity.get("heartbeat_worker"))
    if worker != heartbeat_worker or not worker.get("boot_id") or not isinstance(worker.get("pid"), int) or not isinstance(worker.get("start_ticks"), int):
        errors.append("scheduler_identity.worker")
    if identity.get("spec_allocation_host") != "ada" or identity.get("result_allocation_host") != "ada":
        errors.append("scheduler_identity.host")

    artifact_hashes = _mapping(value.get("artifact_hashes"))
    rows = artifact_hashes.get("scheduler_artifact_index")
    if not isinstance(rows, list) or not rows:
        errors.append("artifact_hashes.scheduler_artifact_index")
    else:
        seen: set[str] = set()
        for index, row_value in enumerate(rows):
            row = _mapping(row_value)
            path = row.get("path")
            if not _safe_relative(path) or path in seen:
                errors.append(f"artifact_hashes[{index}].path")
            seen.add(path)
            if row.get("hash_match") is not True or row.get("stable_read") is not True:
                errors.append(f"artifact_hashes[{index}].hash_match")
            if row.get("declared_bytes") != row.get("actual_bytes") or row.get("declared_sha256") != row.get("actual_sha256") or not _sha256(row.get("declared_sha256")):
                errors.append(f"artifact_hashes[{index}].declared_actual")
        if set(REQUIRED_ARTIFACTS) - seen:
            errors.append("artifact_hashes.required_artifacts")

    execution = _mapping(value.get("execution_receipt"))
    if execution.get("schema") != "core.execution_receipt.v1" or execution.get("status") != "succeeded" or execution.get("returncode") != 0 or execution.get("attempt_id") != ATTEMPT_ID:
        errors.append("execution_receipt.success")
    material = _mapping(value.get("material_terminal"))
    for key, expected in {
        "native_frame_count": EXPECTED_FRAME_COUNT,
        "committed_frame": EXPECTED_TRANSITION_COUNT,
        "transition_count": EXPECTED_TRANSITION_COUNT,
        "committed_transition": EXPECTED_TRANSITION_COUNT,
        "unknown_fraction_limit": UNKNOWN_LIMIT,
    }.items():
        if material.get(key) != expected:
            errors.append(f"material_terminal.{key}")
    unknown_max = material.get("unknown_fraction_max")
    if not _finite_number(unknown_max) or float(unknown_max) <= UNKNOWN_LIMIT:
        errors.append("material_terminal.unknown_fraction_max")
    coverage = material.get("common_reliable_path_coverage")
    if not _finite_number(coverage) or not 0.0 <= float(coverage) <= 1.0:
        errors.append("material_terminal.common_reliable_path_coverage")
    checks = _mapping(value.get("validation")).get("checks")
    check_map = {item.get("check"): item for item in checks if isinstance(item, Mapping)} if isinstance(checks, list) else {}
    required_true = (
        "source_snapshot_sha_bound", "source_snapshot_path_bound", "source_input_sha_bound", "source_input_argv_bound", "source_input_read_boundary", "runtime_input_shas_bound",
        "scheduler_job_identity", "scheduler_attempt_identity", "worker_identity_bound", "host_identity_bound", "cpu_only_allocation",
        "execution_receipt_success", "required_outputs_complete", "argv_cwd_bound", "artifact_hashes_bound",
        "material_status_completed", "full_frame_transition_semantics", "mass_closure", "unknown_monotonicity", "coverage", "diagnostic_non_qualification_boundary",
    )
    for name in required_true:
        if _mapping(check_map.get(name)).get("passed") is not True:
            errors.append(f"validation.checks.{name}")
    unknown_check = _mapping(check_map.get("unknown_gate"))
    negative = _mapping(_mapping(value.get("validation")).get("unknown_gate_negative_diagnostic"))
    if unknown_check.get("passed") is not True or negative.get("recorded") is not True or negative.get("above_one_percent") is not True or negative.get("observed_unknown_fraction_max") != unknown_max:
        errors.append("validation.unknown_gate_negative_diagnostic")
    if _mapping(value.get("validation")).get("errors"):
        errors.append("report.negative_diagnostic_has_unexpected_errors")
    authorization = _mapping(value.get("authorization"))
    if any(authorization.get(key) != expected for key, expected in _authorization().items()):
        errors.append("authorization.no_promotion")
    controls = _mapping(value.get("execution_controls"))
    for key in ("attempt_opened_for_write", "source_hdf5_opened", "source_hdf5_read", "source_hdf5_hash_recomputed", "solver_started", "worker_started", "gpu_started", "queue_started"):
        if controls.get(key) is not False:
            errors.append(f"execution_controls.{key}")
    for key in ("attempt_mutations", "registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations"):
        if controls.get(key) != 0:
            errors.append(f"execution_controls.{key}")
    return list(dict.fromkeys(errors))


def render_zh_cn(value: Mapping[str, Any]) -> str:
    material = _mapping(value.get("material_terminal"))
    negative = _mapping(_mapping(value.get("validation")).get("unknown_gate_negative_diagnostic"))
    execution = _mapping(value.get("execution_receipt"))
    identity = _mapping(value.get("scheduler_identity"))
    return "\n".join(
        [
            "# F3 material coarse s4 terminal-result intake RERUN1",
            "",
            f"- 状态：`{value.get('status')}`（仅诊断；不授予 T1/T2/credit）。",
            f"- scheduler job：`{execution.get('job_id')}`；attempt：`{execution.get('attempt_id')}`；worker pid：`{_mapping(identity.get('worker')).get('pid')}`；host：`{identity.get('host')}`。",
            f"- execution receipt：`{execution.get('status')}`，return code=`{execution.get('returncode')}`；GPU reservation=`{identity.get('reserved_gpu_mib')}` MiB。",
            f"- 完整时域：`{material.get('native_frame_count')}` native frames / `{material.get('transition_count')}` transitions，committed frame=`{material.get('committed_frame')}`。",
            f"- mass closure：`{next((item.get('passed') for item in _mapping(value.get('validation')).get('checks', []) if item.get('check') == 'mass_closure'), False)}`；unknown monotonicity：`{next((item.get('passed') for item in _mapping(value.get('validation')).get('checks', []) if item.get('check') == 'unknown_monotonicity'), False)}`。",
            f"- coverage：common reliable path=`{material.get('common_reliable_path_coverage')}`；unknown max=`{negative.get('observed_unknown_fraction_max')}`，阈值=`{negative.get('limit')}`；超过 1%，明确记录为 `negative diagnostic`。",
            "",
            "该路径位于 git 忽略的 scheduler runtime 下；本报告只是 scheduler-owned runtime attempt 的只读引用，不是可携带的静态 formal receipt。",
            "本 intake 只读绑定 result/spec/material JSON、worker/host identity 与 scheduler artifact hashes；未读取或重算 native source HDF5，未修改 runtime attempt、历史 receipts、registry、ledger、denominator、gate 或 completion。",
            "",
        ]
    )


def write_report(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("invalid terminal-result intake: " + ", ".join(errors))
    path = Path(output)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    return path


def write_zh_cn(value: Mapping[str, Any], output: str | Path) -> Path:
    errors = validate_report(value)
    if errors:
        raise ValueError("invalid terminal-result intake: " + ", ".join(errors))
    path = Path(output)
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_zh_cn(value), encoding="utf-8")
    return path


def _load_report(path: Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_strict_object, parse_constant=_reject_constant)
    if not isinstance(value, Mapping):
        raise ValueError("report must be a JSON object")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempt", type=Path, default=ATTEMPT_RELATIVE)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--zh-output", type=Path, default=DEFAULT_ZH_REPORT)
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args(argv)
    if args.verify is not None:
        errors = validate_report(_load_report(args.verify))
        if errors:
            for error in errors:
                print(error)
            return 2
        print(f"valid: {args.verify}")
        return 0
    report = build_report(LAB_ROOT, args.attempt)
    write_report(report, args.output)
    write_zh_cn(report, args.zh_output)
    print(f"wrote {args.output}")
    print(f"wrote {args.zh_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
