#!/usr/bin/env python3
"""Run one hash-bound F5 solver anchor through the Core worker queue.

The root review and the job specification authorize one canary only.  This
worker writes into its immutable attempt directory, never registers a case,
and never awards qualification or matrix credit.  A successful process is
therefore an executable reference anchor, not a T1 result.
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


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"expected JSON object: {path}")
    return value


def rel(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def bound_path(item: dict[str, Any]) -> Path:
    path = (LAB / item["path"]).resolve()
    if not path.is_file() or path.stat().st_size != item.get("bytes") or sha256(path) != item.get("sha256"):
        raise ValueError(f"stale or missing input binding: {path}")
    return path


def verify_authorization(job_path: Path, review_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    job = load(job_path)
    review = load(review_path)
    if job.get("schema") != "core.f5.third_t1.solver_anchor_job_spec.v1":
        raise ValueError("wrong F5 anchor job schema")
    if job.get("job_spec_status") != "root_review_only_not_submitted":
        raise ValueError("anchor job is not the immutable pre-submission spec")
    if job.get("exactly_one_anchor") is not True or job.get("qualification_claim") != "none" or job.get("matrix_credit") != 0:
        raise ValueError("anchor job carries credit or is not single-use")
    decision = review.get("review_decision", {})
    if review.get("schema") != "core.f5.third_t1.solver_anchor_root_review_receipt.v1":
        raise ValueError("wrong F5 anchor root review schema")
    if review.get("status") != "root_review_only_protected_gpu_solver_anchor_authorized_not_submitted":
        raise ValueError("F5 solver anchor is not root-review-authorized")
    if decision.get("authorized_solver") is not True or decision.get("authorized_gpu") is not True or decision.get("exactly_one_anchor") is not True:
        raise ValueError("root review does not authorize one solver/GPU anchor")
    if decision.get("authorized_queue") is not True:
        raise ValueError("root review does not authorize the protected queue execution")
    if any(decision.get(key) for key in ("authorized_registry", "authorized_ledger", "authorized_matrix")):
        raise ValueError("root review opens a forbidden scientific mutation path")
    if job.get("root_review", {}).get("sha256") != sha256(review_path):
        raise ValueError("job/root-review hash mismatch")
    for item in job.get("hash_bindings", {}).values():
        bound_path(item)
    runtime = job.get("runtime_worker", {})
    if runtime.get("path") != rel(Path(__file__)):
        raise ValueError("runtime worker path is not bound")
    if runtime.get("sha256") != sha256(Path(__file__)):
        raise ValueError("runtime worker hash binding is stale")
    # The static contract worker remains part of the root review; the runtime
    # worker is a separately bound implementation and cannot replace it.
    if job.get("worker", {}).get("runtime_enabled") is not False:
        raise ValueError("contract-only worker was opened")
    return job, review


def _parse_gauge(path: Path) -> dict[str, Any]:
    rows: list[list[float]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
        fields = line.replace(";", " ").split()
        try:
            values = [float(x) for x in fields]
        except ValueError:
            continue
        if len(values) >= 4:
            rows.append(values)
    array = np.asarray(rows, dtype=np.float64)
    issues: list[str] = []
    if array.ndim != 2 or array.shape[1] < 4 or len(array) < 800:
        issues.append("fewer_than_800_data_rows")
    if len(array) and not np.isfinite(array[:, :4]).all():
        issues.append("nonfinite_values")
    times = array[:, 0] if len(array) else np.empty(0)
    dt = np.diff(times) if len(times) > 1 else np.empty(0)
    if len(dt) and (not np.all(dt > 0) or not np.isclose(float(np.median(dt)), TOUT, atol=0.003)):
        issues.append("time_cadence_invalid")
    if len(times) and float(times[-1]) < 15.95:
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


def _run_summary(run_out: Path) -> dict[str, Any]:
    text = run_out.read_text(encoding="utf-8", errors="replace") if run_out.is_file() else ""
    def number(pattern: str) -> float | None:
        match = re.search(pattern, text, re.MULTILINE)
        if not match:
            return None
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            return None
        return value if math.isfinite(value) else None
    excluded = re.search(r"Excluded particles\.+:\s*([\d,]+)", text)
    steps = re.search(r"Steps of simulation\.+:\s*([\d,]+)", text)
    return {
        "finished_code_zero": "Finished execution (code=0)" in text,
        "timemax_s": number(r"TimeMax=([\d.eE+-]+)"),
        "timeout_s": number(r"TimeOut=([\d.eE+-]+)"),
        "excluded_particles": int(excluded.group(1).replace(",", "")) if excluded else None,
        "steps": int(steps.group(1).replace(",", "")) if steps else None,
        "sha256": sha256(run_out) if run_out.is_file() else None,
        "bytes": run_out.stat().st_size if run_out.is_file() else 0,
    }


def _native_endpoint_audit(frames: list[Path], *, decoder: Path, output: Path) -> dict[str, Any]:
    """Decode only the first and last saved frames for identity/finite checks."""
    result: dict[str, Any] = {"frames_checked": [], "pass": False}
    with tempfile.TemporaryDirectory(prefix="f5-anchor-native-") as temporary:
        decoded: list[tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, str]]] = []
        for frame in (frames[0], frames[-1]):
            stem = Path(temporary) / frame.stem
            ids, pos, vel, rho, metadata, _info, _folder = native_frame(frame, stem, decoder)
            finite = bool(np.isfinite(pos).all() and np.isfinite(vel).all() and np.isfinite(rho).all())
            unique = len(np.unique(ids)) == len(ids)
            decoded.append((ids, pos, rho, metadata))
            result["frames_checked"].append({"path": rel(frame), "particles": int(len(ids)), "unique_ids": unique, "finite": finite,
                                               "fluid_count": int(float(metadata.get("CaseNfluid", "nan"))) if metadata.get("CaseNfluid") else None})
        first, last = decoded
        same_ids = bool(np.array_equal(first[0], last[0]))
        fluid_same = int(float(first[3].get("CaseNfluid", "-1"))) == int(float(last[3].get("CaseNfluid", "-2")))
        result["same_native_ids_first_last"] = same_ids
        result["same_fluid_count_first_last"] = fluid_same
        result["pass"] = bool(all(item["unique_ids"] and item["finite"] for item in result["frames_checked"]) and same_ids and fluid_same)
    return result


def run(job_path: Path, review_path: Path, output: Path) -> dict[str, Any]:
    job, review = verify_authorization(job_path, review_path)
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
    try:
        with run_out.open("w", encoding="utf-8") as stream:
            process = subprocess.run(command, cwd=prefix.parent, env=env, stdout=stream, stderr=subprocess.STDOUT, check=False)
        returncode = process.returncode
    except Exception as exc:  # preserve a machine-readable failed anchor receipt
        error = repr(exc)
    finished = time.time()
    frames = sorted((solver_dir / "data").glob("Part_*.bi4")) if (solver_dir / "data").is_dir() else []
    frame_indices = []
    for path in frames:
        match = re.fullmatch(r"Part_(\d+)\.bi4", path.name)
        if match:
            frame_indices.append(int(match.group(1)))
    gauges = {path.stem.removeprefix("GaugesSWL_"): _parse_gauge(path) for path in sorted(solver_dir.glob("GaugesSWL_*.csv"))}
    run_summary = _run_summary(run_out)
    native = _native_endpoint_audit(frames, decoder=DECODER, output=output) if len(frames) >= 2 else {"pass": False, "frames_checked": []}
    hard = {
        "solver_return_code_zero": returncode == 0 and error is None,
        "run_finished_code_zero": run_summary["finished_code_zero"],
        "timemax_matches_registered": run_summary["timemax_s"] is not None and abs(run_summary["timemax_s"] - TMAX) < 1e-9,
        "timeout_matches_registered": run_summary["timeout_s"] is not None and abs(run_summary["timeout_s"] - TOUT) < 1e-9,
        "excluded_particles_zero": run_summary["excluded_particles"] == 0,
        "saved_frame_count": len(frames) == EXPECTED_FRAMES and frame_indices == list(range(EXPECTED_FRAMES)),
        "native_endpoint_identity_finite": native.get("pass") is True,
        "all_expected_gauges_present": set(gauges) == set(EXPECTED_GAUGES),
        "all_gauges_structurally_valid": bool(gauges) and all(not row["issues"] for row in gauges.values()),
    }
    # Geometry chord/endpoint and event thresholds remain a separate scientific
    # review.  The anchor does not silently promote these pending gates.
    audit = {
        "schema": "core.f5.third_t1.solver_anchor_audit.v1",
        "status": "anchor_execution_complete_pending_scientific_review" if all(hard.values()) else "anchor_execution_failed_hard_audit",
        "qualification_claim": "none",
        "matrix_credit": 0,
        "case_id": job["prepared_case_id"],
        "family": "F5",
        "scope_id": job["scope_id"],
        "root_review": {"path": rel(review_path), "sha256": sha256(review_path)},
        "job_spec": {"path": rel(job_path), "sha256": sha256(job_path)},
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
            "solver_invoked": True,
            "gpu_started": True,
            "queue_mutation": 0,
            "ledger_mutation": 0,
            "registry_mutation": 0,
            "matrix_mutation": 0,
            "qualification_credit": 0,
        },
    }
    observations = {
        "schema": "core.f5.third_t1.solver_anchor_observations.v1",
        "case_id": audit["case_id"],
        "gauge_count": len(gauges),
        "gauge_names": sorted(gauges),
        "dynamic_gauges": sorted(name for name, row in gauges.items() if row.get("dynamic")),
        "event_status": "pending_scientific_review",
        "qualification_claim": "none",
        "matrix_credit": 0,
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
    print(json.dumps({"status": audit["status"], "case_id": audit["case_id"], "matrix_credit": 0,
                      "frames": audit["frames"]["count"], "qualification_claim": "none"}, indent=2))
    return 0 if audit["status"] == "anchor_execution_complete_pending_scientific_review" else 1


if __name__ == "__main__":
    raise SystemExit(main())
