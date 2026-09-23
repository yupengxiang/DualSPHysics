#!/usr/bin/env python3
"""JSON-only terminal assessment for the single authorized F3 row30 r003 run.

The audit verifies execution receipts and fixed scientific gates without
opening or hashing the HDF5 trace or NPZ checkpoint payloads.  It cannot grant
T2 credit or authorize another attempt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import f3_native_mls_acceptance_adapter_v1 as acceptance_v1
from scripts import f3_native_mls_matrix_acceptance_v2 as matrix_v2


SCHEMA = "core.material.f3.row30.r003.terminal_audit.v1"
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-r003-terminal-audit-v1/receipt.json"
)
DEFAULT_ATTEMPT_DIR = Path(
    "campaigns/core-v1/runtime/attempts/f3-material-30-canonical-s4-r003/"
    "20260923T105621-d33cb17f4735"
)
AUTHORIZATION = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-core-cpu-r003-authorization-v1/authorization.json"
)
JOB_SPEC = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-core-cpu-r003-authorization-v1/job-spec.json"
)


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _read_json(path: Path) -> tuple[dict[str, Any], bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value, raw


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _display(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path.resolve())


def _bind(root: Path, path: Path) -> dict[str, Any]:
    resolved = _resolve(root, path)
    raw = resolved.read_bytes()
    return {"path": _display(root, resolved), "bytes": len(raw), "sha256": _sha256(raw)}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    return float(value)


def _assert_output_binding(
    attempt_dir: Path,
    result: dict[str, Any],
    filename: str,
) -> dict[str, Any]:
    path = attempt_dir / filename
    raw = path.read_bytes()
    size = len(raw)
    digest = _sha256(raw)
    for collection_name in ("outputs", "artifact_index"):
        collection = result.get(collection_name)
        if not isinstance(collection, list):
            raise ValueError(f"execution receipt has no {collection_name} list")
        matches = [item for item in collection if isinstance(item, dict) and item.get("path") == filename]
        if len(matches) != 1:
            raise ValueError(f"execution receipt must bind exactly one {filename} in {collection_name}")
        if matches[0].get("bytes") != size or matches[0].get("sha256") != digest:
            raise ValueError(f"execution receipt binding mismatch for JSON output {filename}")
    return {"path": filename, "bytes": size, "sha256": digest}


def assess_terminal_result(
    *,
    authorization: dict[str, Any],
    job_spec: dict[str, Any],
    result: dict[str, Any],
    trace_summary: dict[str, Any],
    source_preflight: dict[str, Any],
    checkpoint: dict[str, Any],
    verified_json_outputs: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate = authorization.get("candidate", {})
    resources = authorization.get("resource_pool", {})
    if authorization.get("schema") != "core.material.f3.row30.core_cpu_r003_authorization.v1":
        raise ValueError("r003 authorization schema mismatch")
    expected = {
        "matrix_row": 30,
        "configuration_id": "F3-material-30",
        "q": 0.5,
        "seeds": 4096,
        "substeps": 4,
        "full_native_interval_count": 835,
    }
    if any(candidate.get(key) != value for key, value in expected.items()):
        raise ValueError("r003 authorization does not match the frozen row30 candidate")
    if resources.get("max_attempts") != 1 or resources.get("cpu_cores") != 1:
        raise ValueError("r003 authorization is not a single-core one-attempt grant")
    if authorization.get("invariants", {}).get("solver_forbidden") is not True:
        raise ValueError("r003 authorization does not forbid solver work")
    if authorization.get("invariants", {}).get("gpu_forbidden") is not True:
        raise ValueError("r003 authorization does not forbid GPU work")

    argv = job_spec.get("argv", [])
    if job_spec.get("schema") != "core.runtime.job_spec.v1":
        raise ValueError("r003 job-spec schema mismatch")
    for flag, value in (("--seeds", "4096"), ("--substeps", "4"), ("--stop-after", "835")):
        if not isinstance(argv, list) or argv.count(flag) != 1:
            raise ValueError(f"r003 job spec must contain exactly one {flag}")
        index = argv.index(flag)
        if argv[index + 1 : index + 2] != [value]:
            raise ValueError(f"r003 job spec has a noncanonical value for {flag}")

    if result.get("schema") != "core.execution_receipt.v1":
        raise ValueError("r003 execution receipt schema mismatch")
    if result.get("job_id") != "f3-material-30-canonical-s4-r003":
        raise ValueError("execution receipt belongs to a different job")
    if result.get("execution_status") != "succeeded" or result.get("returncode") != 0:
        raise ValueError("r003 did not complete successfully at the execution layer")
    if result.get("missing_outputs") != []:
        raise ValueError("r003 execution receipt reports missing outputs")
    if trace_summary.get("schema") != "core.material.f3.native_volume_mls.short_canary_result.v1":
        raise ValueError("r003 trace summary schema mismatch")
    if trace_summary.get("status") != "completed" or trace_summary.get("qualification_claim") != "none":
        raise ValueError("r003 trace summary is incomplete or claims qualification")
    if trace_summary.get("seed_count") != 4096:
        raise ValueError("r003 trace summary seed count mismatch")
    binding = trace_summary.get("binding", {})
    if binding.get("substeps") != 4 or binding.get("stop_after") != 835:
        raise ValueError("r003 trace summary does not bind the authorized full-window configuration")
    if source_preflight.get("status") != "preflight_passed":
        raise ValueError("r003 source preflight did not pass")
    if source_preflight.get("qualification_claim") != "none":
        raise ValueError("r003 source preflight unexpectedly claims qualification")

    window = trace_summary.get("source_window", {})
    first_frame = window.get("first_frame")
    last_frame = window.get("last_frame")
    frame_count = window.get("frame_count_committed")
    if (first_frame, last_frame, frame_count) != (0, 835, 836):
        raise ValueError("r003 does not contain the full 836-frame source window")
    if checkpoint.get("schema") != "core.material.f3.native_volume_mls.checkpoint.v1":
        raise ValueError("r003 checkpoint manifest schema mismatch")
    if checkpoint.get("committed_frame") != 835:
        raise ValueError("r003 checkpoint does not commit the terminal frame")

    source_rows = trace_summary.get("source_rows")
    if not isinstance(source_rows, list) or len(source_rows) != 2:
        raise ValueError("r003 summary must contain both F3 source halves")
    normalized_sources: list[dict[str, Any]] = []
    for row in source_rows:
        source_id = row.get("source")
        if source_id not in (0, 1):
            raise ValueError("r003 summary contains an invalid source id")
        unknown = _finite(row.get("unknown_fraction"), f"source {source_id} unknown_fraction")
        if not 0.0 <= unknown <= 1.0:
            raise ValueError("source unknown fraction must be in [0,1]")
        normalized_sources.append(
            {
                "source": source_id,
                "final_unknown_fraction": unknown,
                "unknown_gate_pass": unknown <= acceptance_v1.UNKNOWN_LIMIT,
                "reliable_path_coverage": row.get("reliable_path_coverage"),
                "residence_censored_fraction": row.get("residence_censored_fraction"),
            }
        )
    if {row["source"] for row in normalized_sources} != {0, 1}:
        raise ValueError("r003 source summary must uniquely cover source halves 0 and 1")
    normalized_sources.sort(key=lambda row: row["source"])
    maximum_unknown = max(row["final_unknown_fraction"] for row in normalized_sources)
    unknown_pass = all(row["unknown_gate_pass"] for row in normalized_sources)

    usage = result.get("usage", {})
    wall_seconds = _finite(usage.get("wall_seconds"), "wall_seconds")
    cpu_seconds = _finite(usage.get("cpu_seconds_children"), "cpu_seconds_children")
    peak_rss_mib = _finite(usage.get("max_child_rss_mib"), "max_child_rss_mib")
    peak_gpu_mib = _finite(usage.get("peak_gpu_mib_sampled"), "peak_gpu_mib_sampled")
    if wall_seconds > resources.get("timeout_seconds", 0):
        raise ValueError("r003 execution exceeded its authorized wall timeout")
    if cpu_seconds / 3600 > resources.get("cpu_core_hour_cap", 0):
        raise ValueError("r003 execution exceeded its authorized CPU-hour cap")
    if peak_rss_mib > resources.get("ram_mib", 0) or peak_gpu_mib != 0:
        raise ValueError("r003 execution exceeded its authorized memory/GPU boundary")

    trace_artifacts = [
        item for item in result.get("artifact_index", [])
        if isinstance(item, dict) and item.get("path") == "trace.h5"
    ]
    if len(trace_artifacts) != 1:
        raise ValueError("execution receipt does not bind exactly one trace artifact")
    trace_artifact = trace_artifacts[0]
    trace_output = trace_summary.get("output", {})
    if trace_output.get("sha256") != trace_artifact.get("sha256"):
        raise ValueError("trace summary and execution receipt disagree on the declared trace digest")
    generation = checkpoint.get("generation")
    checkpoint_path = checkpoint.get("checkpoint_npz", "")
    if not isinstance(generation, str) or not checkpoint_path.endswith(generation):
        raise ValueError("checkpoint manifest generation binding is malformed")
    if not any(
        isinstance(item, dict) and item.get("path") == generation
        for item in result.get("artifact_index", [])
    ):
        raise ValueError("execution receipt does not declare the checkpoint generation")

    unknown_pass = unknown_pass and maximum_unknown <= acceptance_v1.UNKNOWN_LIMIT
    return {
        "schema": SCHEMA,
        "status": "completed_scientific_gate_failure" if not unknown_pass else "execution_complete_acceptance_incomplete",
        "candidate": expected,
        "attempt_id": result["job_id"],
        "execution": {
            "status": result["execution_status"],
            "returncode": result["returncode"],
            "missing_outputs": result["missing_outputs"],
            "full_native_window_complete": True,
            "first_frame": first_frame,
            "last_frame": last_frame,
            "committed_frame_count": frame_count,
            "mass_closed": trace_summary.get("mass_closed") is True,
            "qualification_claim": "none",
        },
        "fixed_scientific_gates": {
            "maximum_per_source_unknown_fraction": acceptance_v1.UNKNOWN_LIMIT,
            "observed_per_source_unknown_fraction": normalized_sources,
            "maximum_observed_unknown_fraction": maximum_unknown,
            "per_source_unknown_gate_pass": unknown_pass,
            "mass_closed": trace_summary.get("mass_closed") is True,
            "cdf_comparison_available": False,
            "row_acceptance": False,
            "failure_reasons": [
                *([] if unknown_pass else ["at least one source exceeds the frozen 1% unknown-mass gate"]),
                "independent matched 512-versus-4096 CDF comparison is not bound in this attempt receipt",
            ],
        },
        "resource_usage": {
            "wall_hours": wall_seconds / 3600,
            "cpu_hours": cpu_seconds / 3600,
            "authorized_cpu_core_hour_cap": resources["cpu_core_hour_cap"],
            "peak_rss_mib": peak_rss_mib,
            "authorized_ram_mib": resources["ram_mib"],
            "peak_gpu_mib": peak_gpu_mib,
        },
        "declared_artifacts": {
            "trace_hdf5": {
                "path": trace_artifact["path"],
                "bytes": trace_artifact["bytes"],
                "sha256": trace_artifact["sha256"],
                "payload_hash_independently_verified": False,
            },
            "checkpoint_npz_generation": generation,
            "checkpoint_npz_payload_opened_or_hashed": False,
            "verified_json_outputs": verified_json_outputs,
        },
        "authorization_boundary": {
            "single_authorized_attempt_consumed": True,
            "automatic_retry_authorized": False,
            "new_attempt_authorized_by_this_audit": False,
            "solver_started_by_this_audit": False,
            "gpu_started_by_this_audit": False,
            "queue_or_ledger_mutation": 0,
        },
        "qualification_boundary": {
            "T2_macro": False,
            "T2_path": False,
            "qualification_credit": 0,
            "reason": "execution success and full-window completion do not override the failed unknown gate or missing independent CDF comparison",
        },
        "scope": {
            "only_json_receipts_and_source_text_read": True,
            "hdf5_opened_or_hashed": False,
            "npz_opened_or_hashed": False,
            "solver_or_gpu_started": False,
        },
    }


def build_audit(lab_root: str | Path, attempt_dir: str | Path = DEFAULT_ATTEMPT_DIR) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    attempt = _resolve(root, Path(attempt_dir))
    authorization, _ = _read_json(_resolve(root, AUTHORIZATION))
    job_spec, _ = _read_json(_resolve(root, JOB_SPEC))
    result, _ = _read_json(attempt / "result.json")
    trace_summary, _ = _read_json(attempt / "trace.summary.json")
    source_preflight, _ = _read_json(attempt / "source-preflight.json")
    checkpoint, _ = _read_json(attempt / "trace.h5.checkpoint.json")

    verified_json_outputs = [
        _assert_output_binding(attempt, result, name)
        for name in ("trace.summary.json", "source-preflight.json", "trace.h5.checkpoint.json")
    ]
    audit = assess_terminal_result(
        authorization=authorization,
        job_spec=job_spec,
        result=result,
        trace_summary=trace_summary,
        source_preflight=source_preflight,
        checkpoint=checkpoint,
        verified_json_outputs=verified_json_outputs,
    )
    input_paths = {
        "row30_r003_authorization": AUTHORIZATION,
        "row30_r003_job_spec": JOB_SPEC,
        "matrix_acceptance_adapter_v1": Path("scripts/f3_native_mls_acceptance_adapter_v1.py"),
        "matrix_acceptance_adapter_v2": Path("scripts/f3_native_mls_matrix_acceptance_v2.py"),
        "execution_receipt_json": attempt / "result.json",
        "trace_summary_json": attempt / "trace.summary.json",
        "source_preflight_json": attempt / "source-preflight.json",
        "checkpoint_manifest_json": attempt / "trace.h5.checkpoint.json",
        "terminal_audit_implementation": Path(__file__).resolve(),
    }
    audit["input_bindings"] = {
        name: _bind(root, path) for name, path in input_paths.items()
    }
    return audit


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--attempt-dir", type=Path, default=DEFAULT_ATTEMPT_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    root = args.lab_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(
        build_audit(root, args.attempt_dir), indent=2, sort_keys=True, allow_nan=False
    ) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"schema": SCHEMA, "status": json.loads(encoded)["status"], "output": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
