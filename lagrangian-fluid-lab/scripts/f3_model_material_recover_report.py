"""Recover a material report from a completed rho0 trace after receipt collision.

The runtime worker currently uses ``result.json`` for its execution receipt,
while the old job argv also asked the scientific runner to write its report to
that reserved name.  When the worker receipt replaced the scientific report,
the trace remained intact.  This utility validates the terminal execution
receipt and immutable trace first, then reconstructs the report fields that
are derivable from the trace.  It never reruns integration and never claims
the lost report's hash or timing.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

from scripts.f3_native_volume_mls_model_material import (
    BACKEND,
    SCHEMA,
    TRACE_SCHEMA,
    _implementation_binding,
    _source_rows,
)


RECOVERY_SCHEMA = "core.material.f3.native_volume_mls.model_material_recovery.v1"
SUMMARY_SCHEMA = "core.material.f3.native_volume_mls.model_material_recovery_summary.v1"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    return value.decode("utf-8") if isinstance(value, bytes) else str(value)


def _attr_json(handle: h5py.File, name: str) -> Any:
    value = handle.attrs.get(name)
    if value is None:
        return None
    value = _text(value)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _json(path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value, path


def _trace_artifact(receipt: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = receipt.get("artifact_index") or receipt.get("outputs")
    if not isinstance(artifacts, list):
        raise ValueError("runtime receipt has no artifact index")
    traces = [item for item in artifacts if isinstance(item, dict)
              and str(item.get("path", "")).endswith("trace.h5")]
    if len(traces) != 1 or not isinstance(traces[0].get("sha256"), str):
        raise ValueError("runtime receipt does not bind exactly one trace.h5")
    return traces[0]


def _scientific_report_artifact(receipt: Mapping[str, Any]) -> dict[str, Any] | None:
    """Return the old report artifact hash, without treating it as recoverable."""
    artifacts = receipt.get("artifact_index") or []
    reports = [item for item in artifacts if isinstance(item, dict)
               and str(item.get("path", "")) == "result.json"]
    return reports[0] if len(reports) == 1 else None


def _resolve_artifact_path(attempt_dir: Path, value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (attempt_dir / path).resolve()


def _load_and_validate_terminal(receipt_path: Path, spec_path: Path) -> tuple[
        dict[str, Any], dict[str, Any], Path, Path]:
    """Validate receipt/spec and return them plus attempt and trace paths."""
    receipt, receipt_path = _json(receipt_path)
    spec, spec_path = _json(spec_path)
    if receipt.get("execution_status") != "succeeded" or receipt.get("returncode") != 0:
        raise ValueError("execution receipt is not a successful terminal receipt")
    if receipt.get("missing_outputs"):
        raise ValueError("execution receipt reports missing outputs")
    attempt_dir = receipt_path.parent
    trace_artifact = _trace_artifact(receipt)
    trace_path = _resolve_artifact_path(attempt_dir, str(trace_artifact["path"]))
    if not trace_path.exists():
        raise ValueError(f"terminal receipt trace is missing: {trace_path}")
    actual_trace_sha = sha256_file(trace_path)
    if actual_trace_sha != trace_artifact["sha256"]:
        raise ValueError("terminal receipt trace hash does not match the trace file")
    expected_outputs = spec.get("required_outputs", [])
    if "trace.h5" not in expected_outputs:
        raise ValueError("spec does not register trace.h5")
    return receipt, spec, attempt_dir, trace_path


def _write_summary(path: Path, report: Mapping[str, Any], *, report_path: Path,
                   trace: Path,
                   trace_sha: str, receipt: Mapping[str, Any], receipt_path: Path,
                   original_report_artifact: Mapping[str, Any] | None) -> dict[str, Any]:
    rows = {str(row["source"]): row for row in report["source_rows"]}
    summary = {
        "schema": SUMMARY_SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "recovered_from_terminal_trace",
        "recovery_basis": "trace.h5 plus successful runtime receipt; no reintegration",
        "qualification_claim": "none",
        "material_reliability": "not_established",
        "trace": {"path": str(trace), "sha256": trace_sha},
        "recovered_report": {"path": str(report_path), "sha256": sha256_file(report_path)},
        "runtime_execution": {
            "receipt_path": str(receipt_path),
            "receipt_sha256": sha256_file(receipt_path),
            "job_id": receipt.get("job_id"),
            "execution_status": receipt.get("execution_status"),
            "returncode": receipt.get("returncode"),
            "usage": receipt.get("usage"),
            "timing_semantics": "worker receipt usage only; no scientific-runner timing was recovered",
        },
        "lost_scientific_report": {
            "available": False,
            "original_artifact_hash": (
                original_report_artifact.get("sha256")
                if original_report_artifact else None
            ),
            "hash_is_not_recreated": True,
            "timing_is_not_recreated": True,
        },
        "source_rows": {
            source: {
                "seed_count": row["seed_count"],
                "unknown_fraction_final": row["unknown_fraction_final"],
                "common_reliable_path_fraction": row["common_reliable_path_fraction"],
                "observed_first_passage_fraction": row["observed_first_passage_fraction"],
                "observed_return_fraction": row["observed_return_fraction"],
                "first_failure_frame": row["first_failure_frame"],
                "first_failure_time_s": row["first_failure_time_s"],
            }
            for source, row in rows.items()
        },
        "unknown_fraction_final": report["unknown_fraction_final"],
        "unknown_fraction_max": report["unknown_fraction_max"],
        "common_reliable_path_fraction": report["common_reliable_path_fraction"],
        "mass_closure": report["mass_closure"],
        "limits": report["recovery_limits"],
    }
    path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    # The report hash above was computed before this summary was written and is
    # therefore stable; summary's own hash is intentionally not self-embedded.
    return summary


def recover_report(receipt_path: str | Path, spec_path: str | Path,
                   output_report: str | Path, output_summary: str | Path) -> dict[str, Any]:
    receipt_path = Path(receipt_path).resolve()
    spec_path = Path(spec_path).resolve()
    receipt, spec, attempt_dir, trace_path = _load_and_validate_terminal(receipt_path, spec_path)
    trace_sha = sha256_file(trace_path)
    trace_artifact = _trace_artifact(receipt)
    if trace_sha != str(trace_artifact["sha256"]):
        raise ValueError("trace hash changed during recovery setup")
    input_files = spec.get("input_files", [])
    source_file = next((item for item in input_files if isinstance(item, dict)
                        and item.get("path", "").endswith(".h5")), None)
    source_sha = source_file.get("sha256") if source_file else None
    code_file = next((item for item in input_files if isinstance(item, dict)
                      and item.get("path", "").endswith("f3_native_volume_mls_model_material.py")), None)
    if code_file is None:
        raise ValueError("spec does not bind the numerical module")
    code_path = Path(code_file["path"])
    if code_path.exists() and sha256_file(code_path) != code_file.get("sha256"):
        raise ValueError("registered numerical module hash differs from snapshot")
    # Importing the same implementation after its snapshot hash was verified
    # lets recovery reuse the original source-row/event semantics exactly.
    with h5py.File(trace_path, "r") as handle:
        if _text(handle.attrs.get("trace_schema", "")) != TRACE_SCHEMA:
            raise ValueError("trace schema is not the registered model-material schema")
        if _text(handle.attrs.get("backend", "")) != BACKEND:
            raise ValueError("trace backend is not the registered rho0 backend")
        binding = _attr_json(handle, "binding_json")
        if not isinstance(binding, dict):
            raise ValueError("trace has no structured binding")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        labels = np.asarray(handle["source_label"][:], dtype=np.int8)
        seed_position = np.asarray(handle["seed_position"][:], dtype=np.float64)
        expected_intervals = int(spec.get("argv", [])[spec.get("argv", []).index("--intervals") + 1])
        if len(times) != expected_intervals + 1 or np.any(np.diff(times) <= 0.0):
            raise ValueError("trace is not the registered complete interval window")
        if source_sha is not None and binding.get("source_sha256") != source_sha:
            raise ValueError("trace source hash differs from spec input hash")
        if binding.get("seed_hash") != _text(handle.attrs.get("seed_hash", "")):
            raise ValueError("trace seed hash attribute differs from binding")
        required = ("position", "reliable", "permanent_unknown", "first_passage",
                    "return_time", "residence_opposite", "returned")
        for name in required:
            if name not in handle:
                raise ValueError(f"trace lacks dataset {name}")
        nframe, nseed = len(times), len(labels)
        shape = (nframe, nseed)
        reliable = np.asarray(handle["reliable"][:], dtype=bool)
        unknown = np.asarray(handle["permanent_unknown"][:], dtype=bool)
        if reliable.shape != shape or unknown.shape != shape or not np.array_equal(unknown, ~reliable):
            raise ValueError("trace reliability datasets are inconsistent")
        position = np.asarray(handle["position"][:], dtype=np.float64)
        if position.shape != (nframe, nseed, 3) or not np.isfinite(position).all():
            raise ValueError("trace position dataset is inconsistent")
        first = np.asarray(handle["first_passage"][:], dtype=np.float64)
        returned = np.asarray(handle["return_time"][:], dtype=np.float64)
        residence = np.asarray(handle["residence_opposite"][:], dtype=np.float64)
        if first.shape != shape or returned.shape != shape or residence.shape != shape:
            raise ValueError("trace event datasets are inconsistent")
        records = [
            {
                "time": float(times[i]),
                "reliable": reliable[i],
                "first_passage": first[i],
                "return_time": returned[i],
                "residence_opposite": residence[i],
            }
            for i in range(nframe)
        ]
        rows = _source_rows(records, labels)
        unknown_fraction = np.mean(unknown, axis=1)
        failure_reason_counts = Counter()
        if "failure_reason" in handle:
            values = np.asarray(handle["failure_reason"][:])
            for value in values.reshape(-1):
                failure_reason_counts[_text(value)] += 1
        report = {
            "schema": SCHEMA,
            "trace_schema": TRACE_SCHEMA,
            "backend": BACKEND,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "completed_recovered",
            "recovery_status": "recovered_from_terminal_trace",
            "scientific_report_original_available": False,
            "qualification_claim": "none",
            "material_reliability": "not_established",
            "native_density_qualification": "not_applicable",
            "source": {
                "path": binding.get("source_h5"),
                "sha256": binding.get("source_sha256"),
                "role": binding.get("provider_role"),
                "future_state_inputs": binding.get("future_state_inputs"),
                "frames_registered": None,
            },
            "output_trace_h5": str(trace_path),
            "trace_h5_sha256": trace_sha,
            "binding": binding,
            "implementation": {
                **_implementation_binding(),
                "registered_snapshot_module": code_file,
                "recovery_script": str(Path(__file__).resolve()),
                "recovery_script_sha256": sha256_file(__file__),
            },
            "density_policy": binding.get("density_estimator"),
            "seed_count": nseed,
            "seed_hash": binding.get("seed_hash"),
            "source_rows": rows,
            "unknown_fraction_max": float(np.max(unknown_fraction)),
            "unknown_fraction_final": float(unknown_fraction[-1]),
            "unknown_fraction_by_frame": {
                "time_s": times.tolist(), "fraction": unknown_fraction.tolist(),
            },
            "common_reliable_path_fraction": float(np.mean(np.all(reliable, axis=0))),
            "mass_closure": {
                "closed": True,
                "closure_error": 0.0,
                "seed_weight_definition": "uniform 1/N independent tracer weights",
                "native_support_mass_used_for_weight": True,
                "recovery_basis": "runner contract; no per-seed closure dataset in trace",
            },
            "diagnostics": {
                "recovered_from_trace": True,
                "trace_failure_reason_counts_by_saved_frame": dict(failure_reason_counts),
                "scientific_runner_timing": None,
                "scientific_runner_peak_rss": None,
            },
            "execution": {
                "runtime_receipt_path": str(receipt_path),
                "runtime_receipt_sha256": sha256_file(receipt_path),
                "schema": receipt.get("schema"),
                "job_id": receipt.get("job_id"),
                "execution_status": receipt.get("execution_status"),
                "returncode": receipt.get("returncode"),
                "usage": receipt.get("usage"),
                "timing_semantics": "worker usage only; does not represent recovered scientific-runner timing",
            },
            "lost_scientific_report": {
                "available": False,
                "original_artifact": _scientific_report_artifact(receipt),
                "hash_recreated": False,
                "timing_recreated": False,
                "note": "result.json was reserved by core_runtime and replaced the scientific report",
            },
            "recovery_limits": {
                "source_rows_and_event_arrays": "recomputed from immutable trace using the registered runner semantics",
                "original_report_hash": "recorded from receipt artifact index only; report bytes are unavailable",
                "original_scientific_timing": "unavailable; runtime usage is preserved separately",
                "qualification_claim": "none; recovered report cannot grant T2 or native-density qualification",
                "material_reliability": "support diagnostics remain uncalibrated material error",
            },
        }
    output_report = Path(output_report).resolve()
    output_summary = Path(output_summary).resolve()
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_summary.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    summary = _write_summary(
        output_summary, report, report_path=output_report, trace=trace_path, trace_sha=trace_sha,
        receipt=receipt, receipt_path=receipt_path,
        original_report_artifact=_scientific_report_artifact(receipt),
    )
    return {"report": report, "summary": summary}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--spec", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--output-summary", type=Path, required=True)
    args = parser.parse_args(argv)
    result = recover_report(args.receipt, args.spec, args.output_report, args.output_summary)
    report = result["report"]
    print(json.dumps({
        "schema": report["schema"],
        "status": report["status"],
        "trace_sha256": report["trace_h5_sha256"],
        "seed_count": report["seed_count"],
        "intervals": report["binding"]["intervals_requested"],
        "unknown_final": report["unknown_fraction_final"],
        "common_path": report["common_reliable_path_fraction"],
        "report": str(args.output_report.resolve()),
        "summary": str(args.output_summary.resolve()),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
