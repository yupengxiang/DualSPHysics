"""Compare completed model/reference rho0 material traces.

The model and reference jobs use the same public ``rho0`` density policy, but
read different source H5 files.  This is therefore a registered diagnostic
comparison, rather than a native-density qualification test.  The command
accepts result JSON reports instead of raw trace paths.  It validates both
reports as terminal before opening either H5 file; a running or partial job
cannot be accidentally consumed by the collector.

All source seeds remain in each source denominator.  Permanent support loss is
reported as right-censoring, and unresolved event CDFs are emitted as lower
and upper bounds.  The implementation reuses the fixed-denominator event and
path helpers from ``f3_native_volume_mls_compare`` after normalizing the
model-material trace schema.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import h5py
import numpy as np

from scripts.f3_native_volume_mls_compare import (
    _cdf_sup_difference,
    _json_value,
    _path_comparison,
    _source_rows,
    _unknown_history,
)


SCHEMA = "core.material.f3.native_volume_mls.model_material_comparison.v1"
TRACE_SCHEMA = "core.material.f3.native_volume_mls.model_material_trace.v1"
BACKEND = "f3_native_volume_mls_shared_current_model_rho0_v1"
DENSITY_STRATEGY = "rho0_constant_public_current_state_v1"
MODEL_ROLE = "predicted_model_rollout"
REFERENCE_ROLE = "reference_control_rho0"
EVENT_DEFINITION = {
    "event_plane": "x=0",
    "first_passage": "first usable crossing to opposite x side",
    "residence": "integrated opposite-side time over usable segments",
    "return": "first later usable crossing back to origin side",
    "source_label": "initial_x_ge_0",
}


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    return str(value)


def _attr_json(handle: h5py.File, name: str) -> Any:
    value = handle.attrs.get(name)
    if value is None:
        return None
    value = _text(value)
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return value


def _read_json(path: str | Path) -> tuple[dict[str, Any], Path]:
    path = Path(path).resolve()
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value, path


def _report_trace_path(report: Mapping[str, Any], report_path: Path) -> Path:
    value = report.get("output_trace_h5") or report.get("trace_h5")
    if not isinstance(value, str) or not value:
        raise ValueError(f"{report_path} has no output_trace_h5")
    path = Path(value)
    return path.resolve() if path.is_absolute() else (report_path.parent / path).resolve()


def _validate_terminal_report(report: Mapping[str, Any], report_path: Path,
                             role: str, provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a result report without opening its H5 trace."""
    if report.get("status") not in {"completed", "completed_recovered"}:
        raise ValueError(
            f"{report_path} is not terminal: status={report.get('status')!r}"
        )
    source = report.get("source")
    binding = report.get("binding")
    if not isinstance(source, dict) or not isinstance(binding, dict):
        raise ValueError(f"{report_path} lacks source/binding objects")
    if source.get("role") != role:
        raise ValueError(
            f"{report_path} role {source.get('role')!r} does not match {role!r}"
        )
    if binding.get("trace_schema") != TRACE_SCHEMA:
        raise ValueError(f"{report_path} has an unexpected trace_schema")
    if binding.get("backend") != BACKEND:
        raise ValueError(f"{report_path} has an unexpected backend")
    if binding.get("event_definition") != EVENT_DEFINITION:
        raise ValueError(f"{report_path} has an unexpected event definition")
    if binding.get("density_estimator", {}).get("strategy") != DENSITY_STRATEGY:
        raise ValueError(f"{report_path} does not use the registered rho0 strategy")
    if binding.get("native_reference_density_used", False):
        raise ValueError(f"{report_path} used native reference density")
    if int(binding.get("intervals_requested", -1)) != int(provenance["expected_intervals"]):
        raise ValueError(f"{report_path} does not contain the registered full interval count")
    if int(report.get("seed_count", -1)) != int(provenance["expected_seed_count"]):
        raise ValueError(f"{report_path} does not contain the registered seed count")
    if report.get("seed_hash") != binding.get("seed_hash"):
        raise ValueError(f"{report_path} report and binding seed hashes differ")
    if int(binding.get("substeps_per_saved_interval", -1)) != int(
            provenance.get("expected_substeps_per_saved_interval", 1)):
        raise ValueError(f"{report_path} substeps differ from registered provenance")
    for binding_key, provenance_key in (("dp_m", "expected_dp_m"),
                                        ("h_m", "expected_h_m")):
        if provenance_key in provenance:
            actual = float(binding.get(binding_key, np.nan))
            expected = float(provenance[provenance_key])
            if not np.isfinite(actual) or not np.isclose(actual, expected, rtol=0.0, atol=1.0e-15):
                raise ValueError(f"{report_path} {binding_key} differs from registered provenance")
    expected_seed_hash = provenance.get("expected_seed_hash")
    if expected_seed_hash is not None and binding.get("seed_hash") != expected_seed_hash:
        raise ValueError(f"{report_path} seed hash differs from registered provenance")
    expected_rho0 = float(provenance["rho0_kgm3"])
    actual_rho0 = float(binding["density_estimator"].get("rho0_kgm3", np.nan))
    if not np.isfinite(actual_rho0) or actual_rho0 != expected_rho0:
        raise ValueError(f"{report_path} rho0 does not match registered value")
    expected_source = provenance["expected_source_sha256"][role]
    if source.get("sha256") != expected_source or binding.get("source_sha256") != expected_source:
        raise ValueError(f"{report_path} source hash does not match registered provenance")
    trace_path = _report_trace_path(report, report_path)
    trace_hash = report.get("trace_h5_sha256")
    if not isinstance(trace_hash, str) or len(trace_hash) != 64:
        raise ValueError(f"{report_path} lacks a trace_h5_sha256")
    return {
        "report": str(report_path),
        "report_sha256": sha256_file(report_path),
        "trace": str(trace_path),
        "trace_sha256": trace_hash,
        "source_sha256": expected_source,
        "role": role,
        "binding": binding,
        "report_value": dict(report),
    }


def _require_shape(handle: h5py.File, name: str, shape: tuple[int, ...]) -> np.ndarray:
    if name not in handle:
        raise ValueError(f"trace is missing dataset {name}")
    value = np.asarray(handle[name][:])
    if value.shape != shape:
        raise ValueError(f"trace dataset {name} has shape {value.shape}, expected {shape}")
    return value


def _load_trace(terminal: Mapping[str, Any], provenance: Mapping[str, Any]) -> dict[str, Any]:
    """Open only a report-proven terminal trace and normalize its schema."""
    path = Path(terminal["trace"])
    with h5py.File(path, "r") as handle:
        if _text(handle.attrs.get("trace_schema", "")) != TRACE_SCHEMA:
            raise ValueError(f"{path} has an unexpected trace_schema")
        if _text(handle.attrs.get("backend", "")) != BACKEND:
            raise ValueError(f"{path} has an unexpected backend")
        binding = _attr_json(handle, "binding_json")
        if not isinstance(binding, dict):
            raise ValueError(f"{path} lacks structured binding_json")
        if binding.get("source_sha256") != terminal["source_sha256"]:
            raise ValueError(f"{path} binding source hash differs from terminal report")
        if binding.get("seed_hash") != provenance.get("expected_seed_hash"):
            raise ValueError(f"{path} binding seed hash differs from registered provenance")
        times = np.asarray(handle["time"][:], dtype=np.float64)
        if (times.ndim != 1 or len(times) != int(provenance["expected_intervals"]) + 1
                or not np.isfinite(times).all() or np.any(np.diff(times) <= 0.0)):
            raise ValueError(f"{path} has an incomplete or invalid full time axis")
        if abs(float(times[0]) - float(provenance["expected_time_start_s"])) > 1.0e-12:
            raise ValueError(f"{path} time start differs from registered full window")
        if abs(float(times[-1]) - float(provenance["expected_time_end_s"])) > float(
                provenance.get("endpoint_time_tolerance_s", 3.0e-5)):
            raise ValueError(f"{path} time end differs from registered full window")
        seed_position = np.asarray(handle["seed_position"][:], dtype=np.float64)
        labels = np.asarray(handle["source_label"][:], dtype=np.int8)
        if seed_position.ndim != 2 or seed_position.shape[1:] != (3,):
            raise ValueError(f"{path} has invalid seed_position")
        n = len(labels)
        if n != int(provenance["expected_seed_count"]) or seed_position.shape != (n, 3):
            raise ValueError(f"{path} does not contain the registered seed axis")
        if not np.isfinite(seed_position).all() or not np.isin(labels, [0, 1]).all():
            raise ValueError(f"{path} has invalid seed geometry")
        required = ("position", "reliable", "permanent_unknown", "first_passage",
                    "return_time", "residence_opposite", "returned")
        for name in required:
            if name not in handle:
                raise ValueError(f"{path} is missing dataset {name}")
        frames = len(times)
        position = _require_shape(handle, "position", (frames, n, 3)).astype(np.float64)
        reliable = _require_shape(handle, "reliable", (frames, n)).astype(bool)
        unknown = _require_shape(handle, "permanent_unknown", (frames, n)).astype(bool)
        if not np.array_equal(unknown, ~reliable):
            raise ValueError(f"{path} permanent_unknown is inconsistent with reliable")
        first = _require_shape(handle, "first_passage", (frames, n)).astype(np.float64)
        returned_time = _require_shape(handle, "return_time", (frames, n)).astype(np.float64)
        residence = _require_shape(handle, "residence_opposite", (frames, n)).astype(np.float64)
        returned = _require_shape(handle, "returned", (frames, n)).astype(bool)
        if not np.isfinite(position).all() or not np.isfinite(residence).all():
            raise ValueError(f"{path} contains nonfinite position or residence data")
        actual_hash = sha256_file(path)
        if actual_hash != terminal["trace_sha256"]:
            raise ValueError(f"{path} hash differs from its terminal result report")
        return {
            "path": str(path),
            "sha256": actual_hash,
            "schema": TRACE_SCHEMA,
            "trace_backend": BACKEND,
            "binding": binding,
            "committed": frames - 1,
            "time": times,
            "initial_position": seed_position,
            "source_label": labels,
            "position": position[-1],
            "reliable_history": reliable,
            "unknown_history": unknown,
            "first_passage": first[-1],
            "return_time": returned_time[-1],
            "residence": residence[-1],
            "returned": returned[-1],
            # Model-material H5 has mass closure in result.json, not per-seed
            # H5 rows.  The normalized zero array is only for shared helper
            # shape compatibility; the report values are emitted separately.
            "mass_closure_error": np.zeros((frames, n), dtype=np.float64),
            "material_reliability": _text(handle.attrs.get("material_reliability", "unknown")),
        }


def _validate_pair(left: Mapping[str, Any], right: Mapping[str, Any],
                   provenance: Mapping[str, Any]) -> dict[str, Any]:
    if provenance.get("comparison_mode") != "model_vs_reference_same_rho0":
        raise ValueError("provenance comparison_mode must be model_vs_reference_same_rho0")
    if not provenance.get("allow_source_sha_mismatch", False):
        raise ValueError("rho0 comparison must explicitly allow source hash mismatch")
    if left["binding"].get("seed_hash") != right["binding"].get("seed_hash"):
        raise ValueError("model/reference seed_hash differs")
    if left["binding"].get("event_definition") != right["binding"].get("event_definition"):
        raise ValueError("model/reference event definition differs")
    if left["binding"].get("density_estimator", {}).get("strategy") != \
            right["binding"].get("density_estimator", {}).get("strategy"):
        raise ValueError("model/reference density strategy differs")
    if not np.array_equal(left["initial_position"], right["initial_position"]):
        raise ValueError("model/reference seed positions differ")
    if not np.array_equal(left["source_label"], right["source_label"]):
        raise ValueError("model/reference source labels differ")
    return {
        "comparison_mode": "model_vs_reference_same_rho0",
        "seed_axis_policy": "paired_same_seed_axis_for_diagnostic_endpoints",
        "source_hash_policy": "explicitly_registered_model_reference_mismatch",
        "model_source_sha256": left["binding"].get("source_sha256"),
        "reference_source_sha256": right["binding"].get("source_sha256"),
        "seed_hash": left["binding"].get("seed_hash"),
        "expected_seed_count": int(provenance["expected_seed_count"]),
        "endpoint_time_tolerance_s": float(provenance.get("endpoint_time_tolerance_s", 3.0e-5)),
        "event_definition": EVENT_DEFINITION,
        "density_strategy": DENSITY_STRATEGY,
        "qualification_effect": "none; rho0 model/reference comparison remains diagnostic-only",
    }


def _report_closure(terminal: Mapping[str, Any]) -> dict[str, Any]:
    value = terminal["report_value"].get("mass_closure")
    if not isinstance(value, dict):
        return {"status": "missing_from_result_report"}
    return {
        "status": "closed" if value.get("closed") is True else "not_closed",
        "closed": value.get("closed"),
        "closure_error": value.get("closure_error"),
        "seed_weight_definition": value.get("seed_weight_definition"),
        "native_support_mass_used_for_weight": value.get("native_support_mass_used_for_weight"),
    }


def compare_model_material_reports(model_report: str | Path,
                                   reference_report: str | Path,
                                   provenance: Mapping[str, Any] | str | Path,
                                   output: str | Path | None = None) -> dict[str, Any]:
    prov, prov_path = _read_json(provenance) if isinstance(provenance, (str, Path)) \
        else (dict(provenance), None)
    model_value, model_path = _read_json(model_report)
    reference_value, reference_path = _read_json(reference_report)
    expected_roles = prov.get("expected_source_sha256")
    if not isinstance(expected_roles, dict) or set(expected_roles) != {MODEL_ROLE, REFERENCE_ROLE}:
        raise ValueError("provenance expected_source_sha256 must bind model and reference roles")
    model_terminal = _validate_terminal_report(model_value, model_path, MODEL_ROLE, prov)
    reference_terminal = _validate_terminal_report(
        reference_value, reference_path, REFERENCE_ROLE, prov,
    )
    # Only now open the H5 traces.  A nonterminal report cannot cause an H5
    # read, which protects active/resumable jobs from this postprocessor.
    left = _load_trace(model_terminal, prov)
    right = _load_trace(reference_terminal, prov)
    common_binding = _validate_pair(left, right, prov)
    left_rows = _source_rows(left)
    right_rows = _source_rows(right)
    source_comparison: dict[str, Any] = {}
    for source in sorted(left_rows):
        if source not in right_rows:
            raise ValueError(f"source group {source} missing from reference trace")
        l, r = left_rows[source], right_rows[source]
        source_comparison[source] = {
            "model": l,
            "reference": r,
            "difference": {
                "unknown_fraction_reference_minus_model": (
                    r["final_unknown_fraction"] - l["final_unknown_fraction"]
                ),
                "first_passage_lower_fraction_reference_minus_model": (
                    r["first_passage_event_fraction_bounds"]["lower"]
                    - l["first_passage_event_fraction_bounds"]["lower"]
                ),
                "first_passage_upper_fraction_reference_minus_model": (
                    r["first_passage_event_fraction_bounds"]["upper"]
                    - l["first_passage_event_fraction_bounds"]["upper"]
                ),
                "residence_mean_lower_s_reference_minus_model": (
                    r["residence_mean_s_bounds"]["lower"]
                    - l["residence_mean_s_bounds"]["lower"]
                ),
                "residence_mean_upper_s_reference_minus_model": (
                    r["residence_mean_s_bounds"]["upper"]
                    - l["residence_mean_s_bounds"]["upper"]
                ),
                "first_passage_cdf_sup_abs_difference_bound": _cdf_sup_difference(
                    l["first_passage_cdf_bounds"], r["first_passage_cdf_bounds"]
                )["sup_abs_difference_bound"],
                "return_cdf_sup_abs_difference_bound": _cdf_sup_difference(
                    l["return_cdf_bounds"], r["return_cdf_bounds"]
                )["sup_abs_difference_bound"],
                "residence_cdf_sup_abs_difference_bound": _cdf_sup_difference(
                    l["residence_cdf_bounds"], r["residence_cdf_bounds"]
                )["sup_abs_difference_bound"],
            },
            "cdf_sup_difference_bounds": {
                "first_passage": _cdf_sup_difference(
                    l["first_passage_cdf_bounds"], r["first_passage_cdf_bounds"]
                ),
                "return": _cdf_sup_difference(
                    l["return_cdf_bounds"], r["return_cdf_bounds"]
                ),
                "residence": _cdf_sup_difference(
                    l["residence_cdf_bounds"], r["residence_cdf_bounds"]
                ),
            },
        }
    common_horizon = min(float(left["time"][-1]), float(right["time"][-1]))
    result = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "implementation": {
            "script": str(Path(__file__).resolve()),
            "script_sha256": sha256_file(__file__),
        },
        "comparison_mode": "model_vs_reference_same_rho0",
        "status": "diagnostic_only",
        "qualification_claim": "none",
        "material_reliability_status": (
            "not_established; numerical support_unknown is not material reliability"
        ),
        "density_policy": {
            "strategy": DENSITY_STRATEGY,
            "rho0_kgm3": float(prov["rho0_kgm3"]),
            "model_future_state_inputs": False,
            "reference_native_density_used": False,
        },
        "model": {
            "report": model_terminal["report"],
            "report_sha256": model_terminal["report_sha256"],
            "trace": left["path"],
            "trace_sha256": left["sha256"],
            "source_sha256": left["binding"].get("source_sha256"),
            "time_end_s": float(left["time"][-1]),
            "frame_count": int(len(left["time"])),
            "material_reliability": left["material_reliability"],
            "mass_closure": _report_closure(model_terminal),
        },
        "reference": {
            "report": reference_terminal["report"],
            "report_sha256": reference_terminal["report_sha256"],
            "trace": right["path"],
            "trace_sha256": right["sha256"],
            "source_sha256": right["binding"].get("source_sha256"),
            "time_end_s": float(right["time"][-1]),
            "frame_count": int(len(right["time"])),
            "material_reliability": right["material_reliability"],
            "mass_closure": _report_closure(reference_terminal),
        },
        "common_binding": common_binding,
        "provenance": {
            **prov,
            "path": str(prov_path) if prov_path is not None else None,
        },
        "denominator_policy": {
            "seed_count": int(len(left["source_label"])),
            "source_mass": "all independent geometric seeds; uniform weight 1/N per trace",
            "unknown": "permanent_unknown seeds remain in each source denominator",
            "unobserved_events": "lower bound uses observed finite times; upper bound adds unresolved unknown mass from first possible failure",
            "residence": "reliable no-event seeds contribute observed zero; unknown seeds receive remaining-window upper censoring",
        },
        "source_comparison": source_comparison,
        "unknown_mass_by_frame": {
            "model": _unknown_history(left),
            "reference": _unknown_history(right),
        },
        "common_reliable_path": _path_comparison(left, right, common_horizon),
        "comparison_limits": {
            "source_difference": "model and reference read distinct source H5 files; endpoint pairing is diagnostic only",
            "rho0": "public constant density estimate is shared by policy but is not native CFD density",
            "material_reliability": "support pass/fail is numerical support only; no calibrated material error bound",
            "t2": "not assessed; this comparison cannot grant T2 qualification",
            "unknown_gate_1_percent": "reported only; no threshold is waived or reinterpreted",
        },
    }
    if output is not None:
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(_json_value(result), indent=2, sort_keys=True) + "\n")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-report", type=Path, required=True)
    parser.add_argument("--reference-report", type=Path, required=True)
    parser.add_argument("--provenance", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = compare_model_material_reports(
        args.model_report, args.reference_report, args.provenance, args.output,
    )
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "output": str(args.output.resolve()),
        "seed_count": result["denominator_policy"]["seed_count"],
        "model_unknown": {
            sid: row["model"]["final_unknown_fraction"]
            for sid, row in result["source_comparison"].items()
        },
        "reference_unknown": {
            sid: row["reference"]["final_unknown_fraction"]
            for sid, row in result["source_comparison"].items()
        },
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
