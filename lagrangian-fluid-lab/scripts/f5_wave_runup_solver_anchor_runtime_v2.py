#!/usr/bin/env python3
"""F5 protected solver-anchor runtime worker, revision 2.

This file is intentionally independent of the revision-1 worker.  It keeps
the protected-anchor contract (exactly one anchor, fixed denominator, and
zero qualification/matrix credit), while fixing two runtime bugs observed in
the completed v1 attempt:

* DualSPHysics records the output cadence as ``Output.....: ... dt:...``;
  ``TimeOut=`` is not the cadence gate.
* A worker may execute from a Core runtime snapshot while its attempt output
  lives in the source lab.  Paths outside the snapshot are therefore emitted
  as absolute paths instead of being passed to ``relative_to`` unguarded.

``run`` is the separately authorized execution entry point.  Importing this
module, parsing a closed ``Run.out``, or auditing a gauge never starts a
solver, GPU, queue, registry, ledger, or matrix operation.  This turn only
tests those read-only paths; the worker must be bound by a new root review
before any future submission.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from typing import Any

import numpy as np


LAB = Path(__file__).resolve().parents[1]
if str(LAB) not in sys.path:
    sys.path.insert(0, str(LAB))

from scripts.core_cfd import native_frame


ROOT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2"
DEFAULT_JOB = ROOT / "solver-anchor-job-spec-v1.json"
DEFAULT_REVIEW = ROOT / "solver-anchor-root-review-v1.json"
SOLVER = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DECODER = LAB / "campaigns/l1-resume/artifacts/bi4_dump"
EXPECTED_GAUGES = tuple([f"WG{i}" for i in range(1, 5)] + [f"Run-up{i}" for i in range(1, 8)])
EXPECTED_FRAMES = 801
TMAX = 16.0
TOUT = 0.02
_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
_TIMEMAX_RE = re.compile(rf"^\s*TimeMax\s*=\s*({_NUMBER})\s*$", re.MULTILINE)
_TIMEOUT_RE = re.compile(rf"^\s*TimeOut\s*=\s*({_NUMBER})\s*$", re.MULTILINE)
_OUTPUT_DT_RE = re.compile(
    rf"^\s*Output\.{{5,}}\s*:\s*[^\r\n]*?\bdt\s*:\s*({_NUMBER})\s*$",
    re.MULTILINE,
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def rel(path: Path, *, base: Path | None = None) -> str:
    """Return a stable label even when *path* is outside a worker snapshot.

    Core workers are copied into ``runtime/snapshots/<hash>/``.  Attempt
    products remain in the real lab, so ``relative_to(LAB)`` is not valid for
    those products.  Relative labels are useful when available; an absolute
    label is the lossless fallback and, crucially, never raises ``ValueError``.
    """

    resolved = Path(path).resolve()
    root = Path(base or LAB).resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _bound_path(item: dict[str, Any]) -> Path:
    raw = Path(item["path"])
    path = raw.resolve() if raw.is_absolute() else (LAB / raw).resolve()
    if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
        raise ValueError(f"stale or missing input binding: {path}")
    return path


def _schema_family(value: Any, stem: str) -> bool:
    return isinstance(value, str) and value.startswith(stem)


def verify_authorization(job_path: Path, review_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate a new v2-bound root/job pair without changing protected state."""

    job = load(job_path)
    review = load(review_path)
    if not _schema_family(job.get("schema"), "core.f5.third_t1.solver_anchor_job_spec."):
        raise ValueError("wrong F5 anchor job schema")
    if job.get("job_spec_status") != "root_review_only_not_submitted":
        raise ValueError("anchor job is not the immutable pre-submission spec")
    if job.get("root_review_only") is not True:
        raise ValueError("anchor job is not root-review-only")
    if job.get("exactly_one_anchor") is not True or job.get("qualification_claim") != "none" or job.get("matrix_credit") != 0:
        raise ValueError("anchor job carries credit or is not single-use")

    decision = review.get("review_decision", {})
    if not _schema_family(review.get("schema"), "core.f5.third_t1.solver_anchor_root_review_receipt."):
        raise ValueError("wrong F5 anchor root review schema")
    status = str(review.get("status", ""))
    if not (status.startswith("root_review_only_") and "not_submitted" in status):
        raise ValueError("F5 solver anchor is not root-review-authorized")
    if (
        decision.get("authorized_solver") is not True
        or decision.get("authorized_gpu") is not True
        or decision.get("authorized_queue") is not True
        or decision.get("exactly_one_anchor") is not True
    ):
        raise ValueError("root review does not authorize one protected solver/GPU anchor")
    if any(decision.get(key) for key in ("authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens a forbidden scientific mutation path")
    if review.get("qualification_claim") != "none" or review.get("matrix_credit") != 0:
        raise ValueError("root review carries qualification or matrix credit")
    review_controls = review.get("execution_controls", {})
    for key in ("queue_mutation", "ledger_mutation", "registry_mutation", "matrix_materialized", "matrix_submitted", "qualification_credit"):
        if review_controls.get(key) not in (0, False):
            raise ValueError(f"root review opens forbidden protected state: {key}")
    if job.get("root_review", {}).get("sha256") != sha256(review_path):
        raise ValueError("job/root-review hash mismatch")

    for item in job.get("hash_bindings", {}).values():
        if not isinstance(item, dict):
            raise ValueError("malformed job hash binding")
        _bound_path(item)

    worker = job.get("worker", {})
    if worker.get("runtime_enabled") is not False:
        raise ValueError("contract-only worker was opened")
    runtime = job.get("runtime_worker", {})
    expected_path = f"scripts/{Path(__file__).name}"
    if runtime.get("path") != expected_path:
        raise ValueError("root/job pair is not bound to runtime worker v2")
    if runtime.get("sha256") != sha256(Path(__file__)):
        raise ValueError("runtime worker v2 hash binding is stale")
    if runtime.get("runtime_enabled") is not True or runtime.get("single_use") is not True:
        raise ValueError("runtime worker v2 is not single-use and enabled")
    if runtime.get("solver_calls") != 1 or runtime.get("gpu_calls") != 1:
        raise ValueError("runtime worker v2 call budget is not exactly one solver/GPU anchor")
    for key in ("queue_mutations", "ledger_mutations", "registry_mutations", "matrix_mutations"):
        if runtime.get(key) not in (0, False):
            raise ValueError(f"runtime worker opens forbidden mutation path: {key}")
    policy = job.get("execution_policy", {})
    for key in ("submit_allowed", "queue_mutation", "ledger_mutation", "registry_mutation", "matrix_submission", "matrix_expansion", "same_input_retry"):
        if policy.get(key) not in (False, 0):
            raise ValueError(f"execution policy opens forbidden protected state: {key}")
    if policy.get("one_anchor_only") is not True or policy.get("failure_credit") not in (0, False):
        raise ValueError("execution policy is not exact-one zero-credit")
    failure = job.get("failure_policy", {})
    if failure.get("same_input_retry") not in (False, 0) or failure.get("failure_zero_credit") is not True:
        raise ValueError("failure policy opens retry or credit")
    return job, review


def _finite(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _run_summary(run_out: Path) -> dict[str, Any]:
    """Summarize a closed solver log using native ``Output ... dt:`` records."""

    run_out = Path(run_out)
    text = run_out.read_text(encoding="utf-8", errors="replace") if run_out.is_file() else ""
    timemax_values = [value for raw in _TIMEMAX_RE.findall(text) if (value := _finite(raw)) is not None]
    timeout_values = [value for raw in _TIMEOUT_RE.findall(text) if (value := _finite(raw)) is not None]
    output_values = [value for raw in _OUTPUT_DT_RE.findall(text) if (value := _finite(raw)) is not None]
    unique_output = sorted(set(output_values))
    excluded = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    steps = re.search(r"Steps of simulation\.+:\s*([\d,]+)", text)
    return {
        "path": rel(run_out),
        "present": run_out.is_file(),
        "finished_code_zero": "Finished execution (code=0)" in text,
        "timemax_s": timemax_values[-1] if timemax_values else None,
        "timemax_values_s": timemax_values,
        # Retain this diagnostic for forensics, but never use it as cadence.
        "timeout_s": timeout_values[-1] if timeout_values else None,
        "timeout_values_s": timeout_values,
        "output_dt_values_s": unique_output,
        "output_record_count": len(output_values),
        "output_cadence_s": unique_output[0] if len(unique_output) == 1 else None,
        "cadence_s": unique_output[0] if len(unique_output) == 1 else None,
        "native_output_records_present": bool(output_values),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "steps": int(steps.group(1).replace(",", "")) if steps else None,
        "sha256": sha256(run_out) if run_out.is_file() else None,
        "bytes": run_out.stat().st_size if run_out.is_file() else 0,
    }


def _parse_gauge(path: Path) -> dict[str, Any]:
    path = Path(path)
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        fields = line.replace(";", " ").split()
        try:
            values = [float(value) for value in fields]
        except ValueError:
            continue
        if len(values) >= 4:
            rows.append(values[:4])
    array = np.asarray(rows, dtype=np.float64)
    issues: list[str] = []
    if array.ndim != 2 or array.shape[1] != 4 or len(array) < 800:
        issues.append("fewer_than_800_data_rows")
    if len(array) and not np.isfinite(array).all():
        issues.append("nonfinite_values")
    times = array[:, 0] if len(array) else np.empty(0)
    dt = np.diff(times) if len(times) > 1 else np.empty(0)
    if len(dt) and (not np.all(dt > 0) or not np.isclose(float(np.median(dt)), TOUT, atol=0.003, rtol=0)):
        issues.append("time_cadence_invalid")
    if len(times) and float(times[-1]) < TMAX - 0.05:
        issues.append("gauge_window_short")
    z = array[:, 3] if len(array) else np.empty(0)
    return {
        "path": rel(path),
        "rows": int(len(array)),
        "time_start_s": float(times[0]) if len(times) else None,
        "time_end_s": float(times[-1]) if len(times) else None,
        "dt_median_s": float(np.median(dt)) if len(dt) else None,
        "swl_min_m": float(z.min()) if len(z) else None,
        "swl_max_m": float(z.max()) if len(z) else None,
        "dynamic": bool(len(z) > 1 and np.ptp(z) > 1e-6),
        "issues": issues,
        "sha256": sha256(path),
    }


def _native_endpoint_audit(frames: list[Path], *, decoder: Path, output: Path | None = None) -> dict[str, Any]:
    """Decode only first/last existing frames for finite identity checks."""

    result: dict[str, Any] = {"frames_checked": [], "pass": False}
    if len(frames) < 2:
        return result
    with tempfile.TemporaryDirectory(prefix="f5-anchor-native-v2-") as temporary:
        decoded: list[tuple[np.ndarray, dict[str, str]]] = []
        for frame in (frames[0], frames[-1]):
            stem = Path(temporary) / frame.stem
            ids, pos, vel, rho, metadata, _info, _folder = native_frame(frame, stem, decoder)
            finite = bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all())
            unique = len(np.unique(ids)) == len(ids)
            decoded.append((ids, metadata))
            raw_fluid = metadata.get("CaseNfluid")
            fluid_count = int(float(raw_fluid)) if raw_fluid else None
            result["frames_checked"].append(
                {
                    "path": rel(frame),
                    "particles": int(len(ids)),
                    "unique_ids": unique,
                    "finite": finite,
                    "fluid_count": fluid_count,
                }
            )
        result["same_native_ids_first_last"] = bool(np.array_equal(decoded[0][0], decoded[1][0]))
        first_fluid = decoded[0][1].get("CaseNfluid")
        last_fluid = decoded[1][1].get("CaseNfluid")
        result["same_fluid_count_first_last"] = first_fluid == last_fluid
        result["pass"] = bool(
            all(item["unique_ids"] and item["finite"] for item in result["frames_checked"])
            and result["same_native_ids_first_last"]
            and result["same_fluid_count_first_last"]
        )
    return result


def _cadence_gate(summary: dict[str, Any]) -> bool:
    values = summary.get("output_dt_values_s", [])
    return bool(
        summary.get("native_output_records_present")
        and len(values) == 1
        and math.isclose(float(values[0]), TOUT, rel_tol=0.0, abs_tol=1e-9)
    )


def run(job_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    """Execute one separately authorized anchor into a fresh attempt product."""

    job, review = verify_authorization(Path(job_path).resolve(), Path(review_path).resolve())
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"anchor output is not fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)
    solver_dir = output / "solver"
    solver_dir.mkdir()
    input_info = job["anchor_input"]
    prefix = (LAB / input_info["generated_prefix"]).resolve()
    if not prefix.with_suffix(".xml").is_file() or not prefix.with_suffix(".bi4").is_file():
        raise FileNotFoundError("generated anchor XML/BI4 missing")
    command = [str(SOLVER), "-gpu:0", str(prefix), str(solver_dir), f"-tmax:{TMAX:g}", f"-tout:{TOUT:g}"]
    env = os.environ.copy()
    env["LD_LIBRARY_PATH"] = str(SOLVER.parent) + os.pathsep + env.get("LD_LIBRARY_PATH", "")
    env.setdefault("OMP_NUM_THREADS", "4")
    env.setdefault("OPENBLAS_NUM_THREADS", "4")
    env.setdefault("MKL_NUM_THREADS", "4")
    started = time.time()
    run_out = solver_dir / "Run.out"
    error: str | None = None
    returncode: int | None = None
    solver_invoked = False
    try:
        solver_invoked = True
        with run_out.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=prefix.parent, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        returncode = process.returncode
    except Exception as exc:  # preserve a machine-readable failed anchor receipt
        error = repr(exc)
    finished = time.time()
    frames = sorted((solver_dir / "data").glob("Part_*.bi4")) if (solver_dir / "data").is_dir() else []
    frame_indices: list[int] = []
    for path in frames:
        match = re.fullmatch(r"Part_(\d+)\.bi4", path.name)
        if match:
            frame_indices.append(int(match.group(1)))
    gauges = {
        path.stem.removeprefix("GaugesSWL_"): _parse_gauge(path)
        for path in sorted(solver_dir.glob("GaugesSWL_*.csv"))
    }
    run_summary = _run_summary(run_out)
    native = _native_endpoint_audit(frames, decoder=DECODER, output=output) if len(frames) >= 2 else {"pass": False, "frames_checked": []}
    hard = {
        "solver_return_code_zero": returncode == 0 and error is None,
        "run_finished_code_zero": run_summary["finished_code_zero"],
        "timemax_matches_registered": run_summary["timemax_s"] is not None and math.isclose(run_summary["timemax_s"], TMAX, rel_tol=0.0, abs_tol=1e-9),
        "output_cadence_matches_registered": _cadence_gate(run_summary),
        "excluded_particles_zero": run_summary["excluded_particles"] == 0,
        "saved_frame_count": len(frames) == EXPECTED_FRAMES and frame_indices == list(range(EXPECTED_FRAMES)),
        "native_endpoint_identity_finite": native.get("pass") is True,
        "all_expected_gauges_present": set(gauges) == set(EXPECTED_GAUGES),
        "all_gauges_structurally_valid": bool(gauges) and all(not row["issues"] for row in gauges.values()),
    }
    audit = {
        "schema": "core.f5.third_t1.solver_anchor_audit.v2",
        "runtime_revision": "v2",
        "status": "anchor_execution_complete_pending_scientific_review" if all(hard.values()) else "anchor_execution_failed_hard_audit",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "exactly_one_anchor": True,
        "fixed_denominator": {
            "planned_rows": job.get("matrix_row", {}).get("denominator_rows", 15),
            "required_pass_rows": job.get("matrix_row", {}).get("denominator_rows", 15),
            "numerator_rows": 0,
            "anchor_credit": 0,
            "all_rows_retained": True,
            "partial_credit": False,
        },
        "case_id": job["prepared_case_id"],
        "family": "F5",
        "scope_id": job["scope_id"],
        "root_review": {"path": rel(review_path), "sha256": sha256(review_path)},
        "job_spec": {"path": rel(job_path), "sha256": sha256(job_path)},
        "runtime_worker": {"path": rel(Path(__file__)), "sha256": sha256(Path(__file__))},
        "input": {key: value for key, value in input_info.items() if key in {"generated_prefix", "generated_xml", "native_bi4", "output_stem"}},
        "command": command,
        "started_at_unix": started,
        "finished_at_unix": finished,
        "returncode": returncode,
        "error": error,
        "run": run_summary,
        "frames": {"count": len(frames), "indices_first": frame_indices[:3], "indices_last": frame_indices[-3:]},
        "native_endpoint_audit": native,
        "gauges": gauges,
        "hard_gates": hard,
        "scientific_review_pending": {
            "saved_chord_crossings": "pending_geometry_audit",
            "closed_face_endpoint": "pending_geometry_audit",
            "domain_containment": "pending_geometry_audit",
            "mass_change_full_window": "pending_full_trajectory_audit",
            "incident_runup_return_events": "pending_event_observer",
            "external_CIEMito_alignment": "pending_reference_time_alignment",
        },
        "execution_controls": {
            "solver_invoked": solver_invoked,
            "gpu_started": solver_invoked,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
    }
    observations = {
        "schema": "core.f5.third_t1.solver_anchor_observations.v2",
        "runtime_revision": "v2",
        "case_id": audit["case_id"],
        "gauge_count": len(gauges),
        "gauge_names": sorted(gauges),
        "dynamic_gauges": sorted(name for name, row in gauges.items() if row.get("dynamic")),
        "native_output_cadence_s": run_summary.get("output_cadence_s"),
        "event_status": "pending_scientific_review",
        "qualification_claim": "none",
        "qualified": False,
        "matrix_credit": 0,
        "exactly_one_anchor": True,
    }
    (output / "audit.json").write_text(json.dumps(audit, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (output / "observations.json").write_text(json.dumps(observations, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return audit


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job", type=Path, default=DEFAULT_JOB)
    parser.add_argument("--review", type=Path, default=DEFAULT_REVIEW)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = run(args.job.resolve(), args.review.resolve(), args.output.resolve())
    print(
        json.dumps(
            {
                "status": audit["status"],
                "runtime_revision": "v2",
                "case_id": audit["case_id"],
                "matrix_credit": 0,
                "exactly_one_anchor": True,
                "frames": audit["frames"]["count"],
                "qualification_claim": "none",
            },
            indent=2,
        )
    )
    return 0 if audit["status"] == "anchor_execution_complete_pending_scientific_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
