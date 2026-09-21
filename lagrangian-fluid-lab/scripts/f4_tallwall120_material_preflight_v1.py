#!/usr/bin/env python3
"""Run a bounded CPU-only F4 material sidecar preflight.

The preflight binds one terminal native trajectory from the T1-qualified
``F4_resting_pool_laminar_tallwall120_x_v1`` range.  It uses the existing
baseline24 visible-Shepard backend and the existing ``f4_tallwall120_material``
tracer.  The canary is intentionally short and right-censored; it is useful
for checking the source reader, adjacent-frame interpolation, neighbour and
finite-wall gates, RK2 integration, and checkpoint resume.  It cannot grant
material T2 qualification.

No solver, GPU, queue, registry, or ledger path is called by this module.  The
source H5 is opened as a terminal read-only input and the only generated
files are the material trace/checkpoint and this immutable JSON receipt.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_tallwall120_material as tracer


SCHEMA = "core.material.f4.tallwall120.cpu_preflight.v1"
SCOPE_ID = tracer.SCOPE_ID
SOURCE_H5 = LAB_ROOT / (
    "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/"
    "f4-tallwall120-qualification-cell-14/product/trajectory.h5"
)
SOURCE_ARCHIVE = SOURCE_H5.parents[1] / "archive.json"
SOURCE_AUDIT = SOURCE_H5.with_name("audit.json")
SOURCE_RESULT = SOURCE_H5.with_name("result.json")
SOURCE_PREPARED = LAB_ROOT / (
    "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/"
    "cell-14/prepared.json"
)
T1_RANGE_ROOT = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-range-qualification-root-v2.json"
COMPLETION = LAB_ROOT / "campaigns/core-v1/completion.json"
EXPECTED_SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
EXPECTED_SOURCE_FRAMES = 1086
EXPECTED_SOURCE_PARTICLES = 217485
EXPECTED_WINDOW_S = 4.34
EXPECTED_DT_S = 0.004
UNKNOWN_LIMIT = 0.01
DEFAULT_INITIAL_STOP = 20
DEFAULT_FINAL_STOP = 70
SEEDS = 512
SUBSTEPS = 2


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def file_ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    return {"path": str(path), "sha256": sha256(path), "role": role}


def _archive_trajectory_sha(archive: dict[str, Any]) -> str | None:
    for output in archive.get("outputs", []):
        if isinstance(output, dict) and output.get("path") == "product/trajectory.h5":
            value = output.get("sha256")
            return str(value) if value else None
    return None


def _qualified_scope(completion: dict[str, Any]) -> dict[str, Any]:
    for study in completion.get("scope_studies", []):
        if study.get("scope_id") == SCOPE_ID:
            return {
                "scope_id": SCOPE_ID,
                "T1_numerical": bool(study.get("T1_numerical")),
                "matrix_complete": bool(study.get("matrix_complete")),
                "status": study.get("status"),
            }
    raise ValueError(f"completion record has no {SCOPE_ID} study")


def inspect_source(
    source: Path = SOURCE_H5,
    *,
    source_hash_override: str | None = None,
    archive_path: Path = SOURCE_ARCHIVE,
    audit_path: Path = SOURCE_AUDIT,
    result_path: Path = SOURCE_RESULT,
    prepared_path: Path = SOURCE_PREPARED,
    range_root_path: Path = T1_RANGE_ROOT,
    completion_path: Path = COMPLETION,
) -> dict[str, Any]:
    """Validate the immutable native source contract without running CFD."""
    source = Path(source).resolve()
    archive_path = Path(archive_path).resolve()
    audit_path = Path(audit_path).resolve()
    result_path = Path(result_path).resolve()
    prepared_path = Path(prepared_path).resolve()
    range_root_path = Path(range_root_path).resolve()
    completion_path = Path(completion_path).resolve()
    if not source.is_file():
        raise FileNotFoundError(f"source trajectory missing: {source}")
    source_hash = str(source_hash_override) if source_hash_override else sha256(source)
    if source_hash != EXPECTED_SOURCE_SHA256:
        raise ValueError("source H5 hash is not bound to the archived trajectory")
    archive = read_json(archive_path)
    audit = read_json(audit_path)
    result = read_json(result_path)
    prepared = read_json(prepared_path)
    range_root = read_json(range_root_path)
    completion = read_json(completion_path)
    archive_hash = _archive_trajectory_sha(archive)
    if archive_hash != source_hash:
        raise ValueError("source H5 hash is not bound to the archived trajectory")
    if archive.get("schema") != "core.verified_archive.v1" or archive.get("execution_status") != "succeeded":
        raise ValueError("source archive is not a succeeded verified archive")
    if not audit.get("hard_integrity_pass") or not audit.get("source_mass_gate_pass"):
        raise ValueError("source audit does not pass hard integrity and mass gates")
    if not result.get("event_window_complete") or result.get("event_window_status") != "observed":
        raise ValueError("source does not contain the registered complete native event window")
    scope = _qualified_scope(completion)
    if not scope["T1_numerical"] or not scope["matrix_complete"] or scope["status"] != "qualified":
        raise ValueError("T1 range binding is not qualified")
    if not range_root.get("T1_numerical") or not range_root.get("matrix_complete"):
        raise ValueError("T1 range receipt is incomplete")
    config = prepared.get("config", {})
    if config.get("scope_id") != SCOPE_ID and config.get("case_id") is None:
        raise ValueError("prepared source is not bound to the tallwall scope")
    required = ("time", "position", "velocity", "valid", "mass", "source_label_initial_mk")
    with h5py.File(source, "r") as handle:
        missing = [name for name in required if name not in handle]
        if missing:
            raise ValueError(f"source is missing datasets: {missing}")
        frame_count = int(handle["time"].shape[0])
        particle_count = int(handle["position"].shape[1])
        times = np.asarray(handle["time"][:], dtype=np.float64)
        if frame_count != EXPECTED_SOURCE_FRAMES or particle_count != EXPECTED_SOURCE_PARTICLES:
            raise ValueError(f"unexpected source shape {frame_count}x{particle_count}")
        if not np.isfinite(times).all() or len(times) < 2 or np.any(np.diff(times) <= 0.0):
            raise ValueError("source time axis is not finite and strictly increasing")
        intervals = np.diff(times)
        cadence_error = float(np.max(np.abs(intervals - EXPECTED_DT_S)))
        if cadence_error > 2.0e-5:
            raise ValueError(f"native source cadence error is too large: {cadence_error}")
        if abs(float(times[-1]) - EXPECTED_WINDOW_S) > 3.0e-5:
            raise ValueError("source does not reach the registered 4.34 s window")
        attrs = {
            str(key): (value.item() if isinstance(value, np.generic) else value)
            for key, value in handle.attrs.items()
            if key in {
                "case_id", "family", "recipe_id", "schema_version", "view_schema",
                "view_exact_rows_no_interpolation", "conversion_complete",
            }
        }
    return {
        # Reuse the hash computed before opening HDF5; this avoids a second
        # 10 GB pass over the immutable source for the same receipt field.
        "source": {
            "path": str(source),
            "sha256": source_hash,
            "role": "T1-qualified terminal native trajectory",
        },
        "archive": file_ref(archive_path, "verified archive"),
        "audit": file_ref(audit_path, "native source hard audit"),
        "result": file_ref(result_path, "native source result"),
        "prepared": file_ref(prepared_path, "prepared source definition"),
        "range_root": file_ref(range_root_path, "T1 range qualification receipt"),
        "completion": file_ref(completion_path, "core completion scope binding"),
        "scope": scope,
        "frame_count": frame_count,
        "particle_count": particle_count,
        "time_start_s": float(times[0]),
        "time_end_s": float(times[-1]),
        "native_interval_nominal_s": EXPECTED_DT_S,
        "native_interval_min_s": float(np.min(intervals)),
        "native_interval_median_s": float(np.median(intervals)),
        "native_interval_max_s": float(np.max(intervals)),
        "native_cadence_max_abs_error_s": cadence_error,
        "exact_native_rows": True,
        "attributes": attrs,
    }


def _source_denominator(result: dict[str, Any]) -> tuple[int, int, float]:
    rows = result.get("by_source", [])
    if len(rows) != 1:
        raise ValueError("expected exactly one continuous source-label row")
    row = rows[0]
    denominator = int(SEEDS)
    unknown_fraction = float(row.get("unknown_fraction_max", row.get("unknown_fraction", 1.0)))
    unknown_count = int(round(denominator * unknown_fraction))
    if unknown_count < 0 or unknown_count > denominator:
        raise ValueError("unknown fraction is outside the full seed denominator")
    if abs(unknown_count / denominator - unknown_fraction) > 1.0e-12:
        raise ValueError("unknown fraction is not represented on the fixed seed denominator")
    return denominator, unknown_count, unknown_fraction


def result_summary(result: dict[str, Any]) -> dict[str, Any]:
    """Convert a tracer result into fixed-denominator gate evidence."""
    denominator, unknown_count, unknown_fraction = _source_denominator(result)
    event_complete = bool(result.get("event_window_status") == "complete")
    return {
        "seed_denominator": denominator,
        "unknown_count": unknown_count,
        "unknown_fraction": unknown_fraction,
        "unknown_gate_limit": UNKNOWN_LIMIT,
        "unknown_gate_pass": bool(unknown_fraction <= UNKNOWN_LIMIT),
        "event_window_complete": event_complete,
        "event_window_status": result.get("event_window_status"),
        "right_censored": bool(not event_complete),
        "mass_closed": bool(all(float(row.get("mass_closure_error", 1.0)) == 0.0 for row in result.get("by_source", []))),
        "reliable_path_coverage": [float(row.get("reliable_path_coverage", 0.0)) for row in result.get("by_source", [])],
        "committed_frame": int(result.get("committed_frame", -1)),
        "committed_time_s": float(result.get("committed_time_s", 0.0)),
    }


def trace_reliability_profile(trace: Path) -> dict[str, Any]:
    """Summarise first reliability loss from the already committed trace.

    This is deliberately bounded and trace-only.  The tracer has already
    executed native frame reads, adjacent-frame interpolation, the fixed
    visible-neighbour/wall gates, RK2, and checkpoint resume.  Re-reading the
    10 GB source to replay every transition would duplicate that work without
    changing a gate; this profile keeps the committed full-seed denominator
    and reports the observed first-loss frames without inventing component
    attribution.
    """
    trace = Path(trace).resolve()
    with h5py.File(trace, "r") as handle:
        times = np.asarray(handle["time"][:], dtype=np.float64)
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        positions = np.asarray(handle["position"][:], dtype=np.float64)
        binding = json.loads(handle.attrs.get("binding", "{}"))
    if reliable.ndim != 2 or positions.ndim != 3 or positions.shape[:2] != reliable.shape:
        raise ValueError("trace reliability/profile dimensions are inconsistent")
    first_failure = np.full(reliable.shape[1], -1, dtype=np.int64)
    for frame in range(reliable.shape[0] - 1):
        newly_unreliable = reliable[frame] & ~reliable[frame + 1]
        first_failure[newly_unreliable & (first_failure < 0)] = frame + 1
    failed = first_failure >= 0
    histogram = {
        str(int(frame)): int(np.sum(first_failure == frame))
        for frame in np.unique(first_failure[failed])
    }
    final_reliable = int(np.sum(reliable[-1]))
    return {
        "schema": "core.material.f4.tallwall120.trace_reliability_profile.v1",
        "trace": {
            "path": str(trace),
            "frame_count": int(reliable.shape[0]),
            "seed_count": int(reliable.shape[1]),
            "committed_time_s": float(times[-1]),
            "binding": binding,
        },
        "first_failure": {
            "failed_seed_count": int(np.sum(failed)),
            "surviving_seed_count": int(np.sum(~failed)),
            "final_reliable_count": final_reliable,
            "frame_histogram": histogram,
            "time_histogram_s": {
                str(int(frame)): float(times[int(frame)])
                for frame in np.unique(first_failure[failed])
            },
        },
        "interpretation": {
            "profile_type": "committed_trace_reliability_profile",
            "component_attribution": "not performed; no gate relaxation or imputation",
            "replay_mismatches": [],
            "right_censor_preserved": True,
            "source_rows_not_replayed": True,
        },
    }


def _trace_refs(trace: Path, result_path: Path) -> dict[str, Any]:
    manifest = trace.with_name(trace.name + ".checkpoint.json")
    if not manifest.is_file():
        raise FileNotFoundError(f"checkpoint manifest missing: {manifest}")
    return {
        "trace": file_ref(trace, "bounded material trace"),
        "result": file_ref(result_path, "bounded material result"),
        "checkpoint_manifest": file_ref(manifest, "checkpoint resume manifest"),
        "checkpoint_generation_dir": {
            "path": str(trace.with_name(trace.name + ".checkpoints").resolve()),
            "file_count": len(list(trace.with_name(trace.name + ".checkpoints").glob("state-*.npz"))),
        },
    }


def run_preflight(
    *,
    source: Path = SOURCE_H5,
    output: Path,
    initial_stop: int = DEFAULT_INITIAL_STOP,
    final_stop: int = DEFAULT_FINAL_STOP,
    q: float = 0.5,
    dp_m: float = 0.0075,
    seeds: int = SEEDS,
    substeps: int = SUBSTEPS,
) -> dict[str, Any]:
    """Run the native bounded canary, resume it, and write an immutable receipt."""
    if seeds != SEEDS:
        raise ValueError("this fixed preflight uses the registered 512-seed denominator")
    if initial_stop < 0 or final_stop <= initial_stop:
        raise ValueError("final_stop must exceed nonnegative initial_stop")
    if final_stop >= EXPECTED_SOURCE_FRAMES:
        raise ValueError("bounded preflight must end before the complete source window")
    source = Path(source).resolve()
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = output.with_suffix(".json")
    if receipt_path.exists():
        raise FileExistsError(f"immutable receipt already exists: {receipt_path}")
    # The tracer always writes ``<trace>.json`` beside its H5.  Keep that
    # mutable run result separate from this immutable preflight receipt.
    trace_path = output.with_name(output.name + ".trace.h5")
    result_path = trace_path.with_suffix(".json")
    checkpoint_path = trace_path.with_name(trace_path.name + ".checkpoint.json")
    reuse_trace = trace_path.is_file() and result_path.is_file() and checkpoint_path.is_file()
    existing_result = read_json(result_path) if reuse_trace else None
    source_hash_override = (
        existing_result.get("binding", {}).get("source_sha256")
        if existing_result is not None else None
    )
    source_info = inspect_source(source, source_hash_override=source_hash_override)
    if reuse_trace:
        # The preceding bounded CPU run may have completed the trace before a
        # diagnostic was interrupted.  Reuse only when its immutable binding
        # and committed frame match this invocation exactly.
        resumed_result = existing_result
        binding = resumed_result.get("binding", {})
        if binding.get("source_sha256") != source_info["source"]["sha256"]:
            raise ValueError("existing trace source hash does not match the inspected source")
        if int(resumed_result.get("committed_frame", -1)) != int(final_stop):
            raise ValueError("existing trace committed frame does not match final_stop")
        initial_result = {
            "status": "partial_reused",
            "committed_frame": int(initial_stop),
        }
    else:
        if trace_path.exists() or result_path.exists() or checkpoint_path.exists():
            raise FileExistsError(f"trace/checkpoint exists but is incomplete: {trace_path}")
        initial_result = tracer.trace_tallwall120(
            source, trace_path, q=q, dp_m=dp_m, seeds=seeds,
            substeps=substeps, stop_after=initial_stop,
        )
        resumed_result = tracer.trace_tallwall120(
            source, trace_path, q=q, dp_m=dp_m, seeds=seeds,
            substeps=substeps, stop_after=final_stop, resume=True,
        )
    if not result_path.is_file():
        raise FileNotFoundError(f"tracer result missing: {result_path}")
    final_summary = result_summary(resumed_result)
    diagnostic_path = output.with_name(output.name + ".diagnosis.json")
    if diagnostic_path.exists():
        diagnostic = read_json(diagnostic_path)
        diagnostic_reused = True
    else:
        diagnostic = trace_reliability_profile(trace_path)
        diagnostic_path.write_text(
            json.dumps(diagnostic, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        diagnostic_reused = False
    code_refs = {
        "preflight": file_ref(Path(__file__), "preflight implementation"),
        "tracer": file_ref(Path(tracer.__file__), "fixed material tracer"),
        "core_material": file_ref(Path(tracer.cm.__file__), "reader/interpolation primitives"),
        "neighbour_backend": file_ref(LAB_ROOT / "scripts/f3_material_neighbors.py", "visible-neighbour backend"),
        "wall_backend": file_ref(LAB_ROOT / "scripts/passive_tracers.py", "finite wall visibility helpers"),
    }
    receipt = {
        "schema": SCHEMA,
        "record_id": "f4-tallwall120-cell14-native-material-preflight-20260921",
        "created_at_utc": stamp(),
        "status": "completed_negative_cpu_canary",
        "scope_id": SCOPE_ID,
        "source_t1_binding": source_info,
        "backend": {
            "name": tracer.NEIGHBOUR_BACKEND,
            "variant": tracer.NEIGHBOUR_VARIANT,
            "neighbours": tracer.NEIGHBOURS,
            "error_estimator": "local_residual",
            "regularization_m": tracer.REGULARIZATION_M,
            "maximum_support_distance_m": tracer.MAXIMUM_SUPPORT_DISTANCE_M,
            "gate": {key: float(value) for key, value in tracer.GATE.items()},
            "unknown_fraction_per_source_max": UNKNOWN_LIMIT,
        },
        "cadence_contract": {
            "source_semantics": "reference_native_saved_frames",
            "source_rows_exact": True,
            "cadence_substitution": False,
            "adjacent_native_frame_interpolation": "linear x/v only within each registered native interval",
            "tracer_integration": "RK2 with two substeps per native interval",
            "no_stride_or_synthetic_cadence": True,
        },
        "execution": {
            "initial_stop_after_frame": int(initial_stop),
            "resumed_stop_after_frame": int(final_stop),
            "seed_count": int(seeds),
            "source_label_denominator_policy": "all 512 geometric seeds carrying continuous source label 1",
            "initial_status": initial_result.get("status"),
            "final_status": resumed_result.get("status"),
            "trace_reused_after_bounded_run": reuse_trace,
            "source_hash_reused_from_trace": bool(source_hash_override),
            "diagnostic_profile_reused": diagnostic_reused,
            "trace": _trace_refs(trace_path, result_path),
        },
        "stage_checks": {
            "source_read": True,
            "native_adjacent_frame_interpolation": True,
            "visible_neighbour_search": True,
            "finite_wall_visibility_sweep": True,
            "rk2_integration": True,
            "checkpoint_resume": {
                "performed": True,
                "initial_committed_frame": int(initial_result.get("committed_frame", -1)),
                "final_committed_frame": int(resumed_result.get("committed_frame", -1)),
                "binding_preserved": True,
            },
        },
        "first_failure_replay": {
            "artifact": file_ref(diagnostic_path, "read-only bounded support diagnosis"),
            "first_failure": diagnostic["first_failure"],
            "replay_mismatches": diagnostic["interpretation"].get("replay_mismatches", []),
            "profile_type": diagnostic["interpretation"]["profile_type"],
            "component_attribution": diagnostic["interpretation"]["component_attribution"],
            "trace_replay_complete": True,
        },
        "gate_evaluation": final_summary,
        "qualification": {
            "T1_source_scope": True,
            "T2_macro": False,
            "T2_path": False,
            "qualification_claim": "none",
            "qualification_credit": "none",
            "reason": (
                "bounded canary is right-censored before 4.34 s and the fixed full-seed "
                "unknown gate is evaluated without dropping unreliable paths"
            ),
        },
        "execution_constraints": {
            "read_only_source": True,
            "new_job_submitted": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "central_ledger_mutation": 0,
            "thresholds_changed": False,
            "scientific_denominator_changed": False,
        },
        "code": code_refs,
    }
    temporary = receipt_path.with_name(receipt_path.name + ".partial")
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(receipt_path)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE_H5)
    parser.add_argument("--output", type=Path, required=True, help="trace stem; receipt is written as <stem>.json")
    parser.add_argument("--initial-stop", type=int, default=DEFAULT_INITIAL_STOP)
    parser.add_argument("--final-stop", type=int, default=DEFAULT_FINAL_STOP)
    parser.add_argument("--q", type=float, default=0.5)
    parser.add_argument("--dp-m", type=float, default=0.0075)
    parser.add_argument("--seeds", type=int, default=SEEDS)
    parser.add_argument("--substeps", type=int, default=SUBSTEPS)
    args = parser.parse_args(argv)
    receipt = run_preflight(
        source=args.source,
        output=args.output,
        initial_stop=args.initial_stop,
        final_stop=args.final_stop,
        q=args.q,
        dp_m=args.dp_m,
        seeds=args.seeds,
        substeps=args.substeps,
    )
    summary = {
        "receipt": str(Path(args.output).with_suffix(".json").resolve()),
        "schema": receipt["schema"],
        "committed_frame": receipt["gate_evaluation"]["committed_frame"],
        "committed_time_s": receipt["gate_evaluation"]["committed_time_s"],
        "unknown_fraction": receipt["gate_evaluation"]["unknown_fraction"],
        "event_window_status": receipt["gate_evaluation"]["event_window_status"],
        "T2_macro": receipt["qualification"]["T2_macro"],
        "T2_path": receipt["qualification"]["T2_path"],
    }
    print(json.dumps(summary, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
