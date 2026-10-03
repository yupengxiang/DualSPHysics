#!/usr/bin/env python3
"""Audit one immutable direct H5 and its independently materialized labels.

This audit is deliberately narrower than a numerical or transport Q-N gate. It
checks source/report/receipt closure, typed identity closure, the label schema,
and finite native label values. It never changes either H5 and never claims a
continuous-time transport result from saved-frame chord labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


EXPECTED_SOURCE_SCHEMA = "ds-data-02.hdf5-schema.v1"
EXPECTED_LABEL_SCHEMA = "ds-data-02.native-labels.v1"
EXPECTED_COORDINATE_FRAME = "DualSPHysics case Cartesian coordinates (x,y,z)"
EXPECTED_PARTICLES = 108000
EXPECTED_FLUID_COUNT = 34560
EXPECTED_FIXED_COUNT = 73440
EXPECTED_MASS_KG = 14.58
EXPECTED_LABEL_DATASETS = {
    "time",
    "particle_id",
    "particle_zone",
    "source_label",
    "destination_time_series",
    "final_category",
    "failure_reason",
    "first_passage_interval",
    "first_passage_chord_time",
    "first_passage_censor",
    "residence_time_s",
    "unresolved_interval_time_s",
    "initial_fluid_mass_kg",
    "forward_backward_mass_kg",
    "cumulative_net_flux_kg",
    "unknown_mass_kg",
    "numerical_loss_mass_kg",
    "invalid_state_mass_kg",
    "source_final_mass_kg",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def attr_text(value):
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.bytes_):
        return value.tobytes().decode("utf-8")
    return value


def attr_bool(value):
    """Decode HDF5 bool attributes written as either bools or strings."""
    value = attr_text(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n", ""}:
            return False
    return bool(value)


def json_attr(value):
    value = attr_text(value)
    if isinstance(value, str):
        return json.loads(value)
    return value


def check(checks, name, passed, value):
    checks.append({"name": name, "status": "pass" if passed else "fail", "value": value})


def finite_summary(dataset, *, sample_frames=None):
    """Return finite/min/max evidence without loading a complete trajectory."""
    if sample_frames is None:
        array = dataset[:]
    else:
        array = dataset[sample_frames]
    array = np.asarray(array)
    return {
        "shape": list(dataset.shape),
        "dtype": str(dataset.dtype),
        "finite": bool(np.isfinite(array).all()),
        "min": float(np.nanmin(array)) if array.size else None,
        "max": float(np.nanmax(array)) if array.size else None,
    }


def audit(source_path: Path, labels_path: Path, report_path: Path, direct_receipt_path: Path,
          config_path: Path, operators_path: Path, semantics_path: Path,
          label_request_path: Path, label_receipt_path: Path, output_path: Path,
          expected_frames: int | None = None, variant_name: str = "reference"):
    checks = []
    source_path = source_path.resolve()
    labels_path = labels_path.resolve()
    report_path = report_path.resolve()
    direct_receipt_path = direct_receipt_path.resolve()
    config_path = config_path.resolve()
    operators_path = operators_path.resolve()
    semantics_path = semantics_path.resolve()
    label_request_path = label_request_path.resolve()
    label_receipt_path = label_receipt_path.resolve()
    output_path = output_path.resolve()

    report = json.loads(report_path.read_text())
    direct_receipt = json.loads(direct_receipt_path.read_text())
    config = json.loads(config_path.read_text())
    operators = json.loads(operators_path.read_text())
    semantics = json.loads(semantics_path.read_text())
    label_request = json.loads(label_request_path.read_text())
    label_receipt = json.loads(label_receipt_path.read_text())

    source_sha_before = sha256(source_path)
    labels_sha = sha256(labels_path)
    check(checks, "direct_report_completed", report.get("conversion_status") == "completed",
          report.get("conversion_status"))
    check(checks, "direct_receipt_terminal_success",
          direct_receipt.get("status") == "completed" and direct_receipt.get("returncode") == 0,
          {"status": direct_receipt.get("status"), "returncode": direct_receipt.get("returncode")})
    check(checks, "labels_receipt_terminal_success",
          label_receipt.get("status") == "completed" and label_receipt.get("returncode") == 0,
          {"status": label_receipt.get("status"), "returncode": label_receipt.get("returncode")})
    check(checks, "labels_request_scope",
          label_request.get("cpu_task_kind") == "labels" and label_request.get("q_n_status") == "not_assessed",
          {"cpu_task_kind": label_request.get("cpu_task_kind"), "q_n_status": label_request.get("q_n_status")})
    check(checks, "labels_input_hash_binding",
          label_receipt.get("input_hashes_at_launch") == label_receipt.get("input_hashes_after_run"),
          {"unchanged": label_receipt.get("input_hashes_at_launch") == label_receipt.get("input_hashes_after_run")})
    check(checks, "source_sha_matches_direct_report",
          source_sha_before == report.get("output_sha256"),
          {"actual": source_sha_before, "report": report.get("output_sha256")})

    with h5py.File(source_path, "r") as source, h5py.File(labels_path, "r") as labels:
        source_schema = attr_text(source.attrs.get("schema"))
        source_frame = attr_text(source.attrs.get("coordinate_frame"))
        check(checks, "source_schema", source_schema == EXPECTED_SOURCE_SCHEMA, source_schema)
        check(checks, "source_coordinate_frame", source_frame == EXPECTED_COORDINATE_FRAME, source_frame)
        check(checks, "source_required_datasets",
              {"time", "particle_id", "particle_zone", "position", "valid", "mass", "type"}.issubset(source),
              sorted(set(["time", "particle_id", "particle_zone", "position", "valid", "mass", "type"]) - set(source)))
        time = source["time"][:]
        particle_id = source["particle_id"][:]
        particle_zone = source["particle_zone"][:]
        valid0 = source["valid"][0, :].astype(bool)
        type0 = source["type"][0, :]
        frames, particles = source["valid"].shape
        target_frames = expected_frames or report.get("frames", frames)
        check(checks, "source_shape", (frames, particles) == (target_frames, EXPECTED_PARTICLES),
              {"frames": frames, "particles": particles, "expected_frames": target_frames})
        check(checks, "source_time_monotonic",
              len(time) == frames and np.isfinite(time).all() and np.all(np.diff(time) > 0),
              {"first_s": float(time[0]), "last_s": float(time[-1]), "frames": len(time)})
        keys = np.column_stack((particle_zone, particle_id))
        check(checks, "source_typed_identity_unique",
              len(np.unique(keys, axis=0)) == particles,
              {"unique": int(len(np.unique(keys, axis=0))), "particles": particles})
        check(checks, "source_initial_type_counts",
              int(np.sum(valid0 & (type0 == 3))) == EXPECTED_FLUID_COUNT and int(np.sum(valid0 & (type0 == 0))) == EXPECTED_FIXED_COUNT,
              {"type0": int(np.sum(valid0 & (type0 == 0))), "type3": int(np.sum(valid0 & (type0 == 3)))})
        fluid_mass = np.asarray(source["mass"][0, valid0 & (type0 == 3)], dtype=float)
        initial_mass = float(fluid_mass.sum())
        check(checks, "source_initial_mass", abs(initial_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG <= 0.01,
              {"mass_kg": initial_mass, "relative_error": abs(initial_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG})
        check(checks, "source_initial_mass_finite_positive", bool(np.isfinite(fluid_mass).all() and (fluid_mass > 0).all()),
              {"min_kg": float(fluid_mass.min()), "max_kg": float(fluid_mass.max())})

        sample = [0, frames // 2, frames - 1]
        source_numeric = {}
        for name in ("position", "velocity", "mass", "density", "pressure"):
            if name in source:
                source_numeric[name] = finite_summary(source[name], sample_frames=sample)
        check(checks, "source_anchor_numeric_finite",
              all(item["finite"] for item in source_numeric.values()), source_numeric)
        valid_all = True
        type_stable = True
        for begin in range(0, particles, 16384):
            end = min(particles, begin + 16384)
            valid_chunk = source["valid"][:, begin:end]
            type_chunk = source["type"][:, begin:end]
            valid_all &= bool(np.asarray(valid_chunk).all())
            type_stable &= bool(np.all(np.asarray(type_chunk) == np.asarray(type_chunk)[0:1, :]))
        check(checks, "source_valid_identity_closure", valid_all, {"all_valid": valid_all})
        check(checks, "source_type_identity_closure", type_stable, {"type_stable": type_stable})

        label_schema = attr_text(labels.attrs.get("schema"))
        label_frame = attr_text(labels.attrs.get("coordinate_frame"))
        source_attr = attr_text(labels.attrs.get("source_hdf5_sha256"))
        check(checks, "labels_schema", label_schema == EXPECTED_LABEL_SCHEMA, label_schema)
        check(checks, "labels_coordinate_frame", label_frame == EXPECTED_COORDINATE_FRAME, label_frame)
        check(checks, "labels_source_sha", source_attr == source_sha_before,
              {"labels": source_attr, "source": source_sha_before})
        check(checks, "labels_complete_no_model",
              attr_bool(labels.attrs.get("complete")) and not attr_bool(labels.attrs.get("model_invoked")),
              {"complete": attr_bool(labels.attrs.get("complete")), "model_invoked": attr_bool(labels.attrs.get("model_invoked"))})
        check(checks, "labels_qn_not_assessed", attr_text(labels.attrs.get("q_n_status")) == "not_assessed",
              attr_text(labels.attrs.get("q_n_status")))
        try:
            label_config = json.loads(attr_text(labels.attrs["config_json"]))
            config_equal = label_config == config
        except (KeyError, json.JSONDecodeError, TypeError):
            config_equal = False
            label_config = None
        check(checks, "labels_canonical_config", config_equal,
              {"config_sha256": sha256(config_path), "embedded_equal": config_equal})
        check(checks, "labels_required_datasets", EXPECTED_LABEL_DATASETS.issubset(labels),
              sorted(EXPECTED_LABEL_DATASETS - set(labels)))
        check(checks, "labels_shape_time", labels["time"].shape == (frames,) and np.array_equal(labels["time"][:], time),
              {"shape": list(labels["time"].shape), "frames": frames})
        check(checks, "labels_shape_identity", labels["particle_id"].shape == (particles,) and labels["particle_zone"].shape == (particles,) and
              np.array_equal(labels["particle_id"][:], particle_id) and np.array_equal(labels["particle_zone"][:], particle_zone),
              {"shape": list(labels["particle_id"].shape), "particles": particles})
        label_shapes = {
            "destination_time_series": list(labels["destination_time_series"].shape),
            "first_passage_interval": list(labels["first_passage_interval"].shape),
            "first_passage_chord_time": list(labels["first_passage_chord_time"].shape),
            "residence_time_s": list(labels["residence_time_s"].shape),
            "forward_backward_mass_kg": list(labels["forward_backward_mass_kg"].shape),
        }
        shape_ok = (labels["destination_time_series"].shape == (frames, particles) and
                    labels["first_passage_interval"].shape == (particles, 2, 2) and
                    labels["first_passage_chord_time"].shape == (particles, 2) and
                    labels["residence_time_s"].shape == (particles, 2) and
                    labels["forward_backward_mass_kg"].shape == (frames, 2, 2))
        check(checks, "labels_event_shapes", shape_ok, label_shapes)
        for name in ("source_label", "destination_time_series", "final_category", "failure_reason", "first_passage_censor"):
            values = np.asarray(labels[name][:])
            check(checks, f"labels_{name}_finite", bool(np.isfinite(values).all()), {"shape": list(values.shape)})
        allow_nan = {"first_passage_chord_time", "first_passage_interval"}
        signed_fields = {"cumulative_net_flux_kg"}
        for name in ("first_passage_chord_time", "first_passage_interval", "residence_time_s", "unresolved_interval_time_s",
                     "initial_fluid_mass_kg", "forward_backward_mass_kg", "cumulative_net_flux_kg", "unknown_mass_kg",
                     "numerical_loss_mass_kg", "invalid_state_mass_kg", "source_final_mass_kg"):
            values = np.asarray(labels[name][:])
            finite = np.isfinite(values)
            valid = finite | np.isnan(values) if name in allow_nan else finite
            check(checks, f"labels_{name}_finite_or_censored", bool(valid.all()), {"shape": list(values.shape), "nan_count": int(np.isnan(values).sum())})
            finite_values = values[finite]
            if name in signed_fields:
                check(checks, f"labels_{name}_signed_finite", bool(np.isfinite(finite_values).all()),
                      {"min_finite": float(finite_values.min()) if finite_values.size else None,
                       "max_finite": float(finite_values.max()) if finite_values.size else None,
                       "sign": "signed_net_flux"})
            else:
                check(checks, f"labels_{name}_nonnegative", bool((finite_values >= 0).all()),
                      {"min_finite": float(finite_values.min()) if finite_values.size else None})
        label_mass = float(labels.attrs.get("initial_fluid_mass_kg"))
        check(checks, "labels_initial_mass", abs(label_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG <= 0.01,
              {"mass_kg": label_mass, "relative_error": abs(label_mass - EXPECTED_MASS_KG) / EXPECTED_MASS_KG})
        check(checks, "labels_no_unclassified_initial_fluid",
              float(np.asarray(labels["unknown_mass_kg"][:]).max()) >= 0.0,
              {"unknown_max_kg": float(np.asarray(labels["unknown_mass_kg"][:]).max()),
               "numerical_loss_max_kg": float(np.asarray(labels["numerical_loss_mass_kg"][:]).max()),
               "invalid_max_kg": float(np.asarray(labels["invalid_state_mass_kg"][:]).max())})

    source_sha_after = sha256(source_path)
    check(checks, "source_unchanged_during_audit", source_sha_before == source_sha_after,
          {"before": source_sha_before, "after": source_sha_after})
    failed = [row for row in checks if row["status"] == "fail"]
    result = {
        "schema": f"ds02.f3.historical-cell3-{variant_name}-label-closure.v1",
        "status": "completed_pass" if not failed else "completed_review_required",
        "scope": f"{variant_name.upper()} direct H5 and saved-frame label closure; Q-I evidence only",
        "q_i_status": "completed_pass" if not failed else "review_required",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "model_invoked": False,
        "source": {"path": str(source_path), "sha256": source_sha_after, "report_sha256": sha256(report_path),
                   "direct_receipt_sha256": sha256(direct_receipt_path), "frames": target_frames,
                   "typed_identities": EXPECTED_PARTICLES, "fluid_particles": EXPECTED_FLUID_COUNT,
                   "initial_fluid_mass_kg": float(initial_mass)},
        "labels": {"path": str(labels_path), "sha256": labels_sha, "frames": target_frames,
                   "typed_identities": EXPECTED_PARTICLES, "initial_fluid_mass_kg": float(label_mass)},
        "canonical": {"config_sha256": sha256(config_path), "operators_sha256": sha256(operators_path),
                      "semantics_sha256": sha256(semantics_path)},
        "checks": checks,
        "checks_passed": len(checks) - len(failed),
        "checks_failed": len(failed),
        "label_attempt_id": label_request.get("attempt_id"),
        "note": "Saved-frame linear chord labels retain censored/unknown states; no continuous-time or Q-N claim is made.",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-h5", type=Path, required=True)
    parser.add_argument("--labels-h5", type=Path, required=True)
    parser.add_argument("--direct-report", type=Path, required=True)
    parser.add_argument("--direct-receipt", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--operators", type=Path, required=True)
    parser.add_argument("--semantics", type=Path, required=True)
    parser.add_argument("--label-request", type=Path, required=True)
    parser.add_argument("--label-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-frames", type=int, default=None)
    parser.add_argument("--variant", type=str, default="reference")
    args = parser.parse_args()
    result = audit(
        source_path=args.source_h5,
        labels_path=args.labels_h5,
        report_path=args.direct_report,
        direct_receipt_path=args.direct_receipt,
        config_path=args.config,
        operators_path=args.operators,
        semantics_path=args.semantics,
        label_request_path=args.label_request,
        label_receipt_path=args.label_receipt,
        output_path=args.output,
        expected_frames=args.expected_frames,
        variant_name=args.variant,
    )
    print(json.dumps({"status": result["status"], "checks_failed": result["checks_failed"],
                      "output": str(args.output)}, sort_keys=True))
    return 0 if result["status"] == "completed_pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
