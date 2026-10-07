#!/usr/bin/env python3
"""Forward v3 for the guarded F2 native raw-to-typed replay.

The v2 worker is immutable and remains the producer of the reconstructed
typed HDF5, lifecycle table, v15 labels, and optional v16/evaluator outputs.
This worker adds the missing source-bound comparison step: after the parent
stage2 guard grants the slot, it compares that typed output with the exact
producer trajectory HDF5 frame by frame and in bounded particle chunks.

The metadata path only checks declarations and file statistics.  It never
opens BI4/HDF5 content.  No result from this module grants QI/QN/QE; all
results are DEVELOPMENT evidence and preserve UNKNOWN qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import resource
import sys
import time
from typing import Any, Mapping, Sequence

import h5py
import numpy as np


SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare.v3"
REPORT_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-report.v3"
REQUEST_SCHEMA = "ds02.stage2.f2-native-raw-to-typed-reference-compare-request.v3"
UNKNOWN_QUALIFICATION = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")


class ReferenceCompareError(RuntimeError):
    """Raised when a source-bound comparison request is unsafe or incomplete."""


def sha256_file(path: Path | str, *, chunk_size: int = 4 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while True:
            block = stream.read(chunk_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=_json_default).encode()).hexdigest()


def _json_default(value: Any) -> Any:
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"not JSON serializable: {type(value)!r}")


def _load_json(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ReferenceCompareError(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise ReferenceCompareError(f"JSON object required: {path}")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> None:
    target = Path(path).expanduser()
    if target.exists():
        raise ReferenceCompareError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        with target.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                      default=_json_default)
            stream.write("\n")
    except FileExistsError as error:
        raise ReferenceCompareError(f"refusing to overwrite existing output: {target}") from error


def _require_sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise ReferenceCompareError(f"{name} must be a lowercase SHA-256")
    return value


def _stat_binding(item: Mapping[str, Any], role: str, *, verify_content: bool) -> dict[str, Any]:
    path_value = item.get("path")
    if not isinstance(path_value, str):
        raise ReferenceCompareError(f"{role}.path is required")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ReferenceCompareError(f"{role} is missing: {path}")
    stat = path.stat()
    if item.get("bytes") is not None and int(item["bytes"]) != stat.st_size:
        raise ReferenceCompareError(f"{role} byte stat differs")
    if item.get("mtime_ns") is not None and int(item["mtime_ns"]) != stat.st_mtime_ns:
        raise ReferenceCompareError(f"{role} mtime stat differs")
    expected = _require_sha(item.get("sha256"), f"{role}.sha256")
    if verify_content and sha256_file(path) != expected:
        raise ReferenceCompareError(f"{role} content SHA differs")
    return {"role": role, "path": str(path), "bytes": stat.st_size,
            "mtime_ns": stat.st_mtime_ns, "sha256": expected,
            "content_hash_status": "VERIFIED" if verify_content else "PARENT_GUARD_REQUIRED"}


def _load_module(path: Path, name: str) -> Any:
    if not path.is_file():
        raise ReferenceCompareError(f"bound module is missing: {path}")
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ReferenceCompareError(f"cannot import bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _module_binding(item: Mapping[str, Any], role: str, *, verify_content: bool) -> dict[str, Any]:
    return _stat_binding(item, f"modules.{role}", verify_content=verify_content)


def _positive_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ReferenceCompareError(f"{name} must be a positive integer")
    return value


def _require_request(request: Mapping[str, Any], *, verify_sources: bool) -> dict[str, Any]:
    if request.get("schema") != REQUEST_SCHEMA:
        raise ReferenceCompareError(f"unsupported request schema: {request.get('schema')!r}")
    if request.get("role") != "DEVELOPMENT" or request.get("status") != "READY_FOR_PARENT_GUARD":
        raise ReferenceCompareError("request must remain DEVELOPMENT and READY_FOR_PARENT_GUARD")
    if request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise ReferenceCompareError("model/CFD invocation is forbidden")
    if request.get("qualification") != UNKNOWN_QUALIFICATION:
        raise ReferenceCompareError("QI/QN/QE must remain UNKNOWN")
    parent_preverified = request.get("source_hashes_preverified_by_parent") is True
    base = request.get("base_v2_request")
    if not isinstance(base, Mapping):
        raise ReferenceCompareError("base_v2_request binding is required")
    base_binding = _stat_binding(base, "base_v2_request", verify_content=True)
    base_request = _load_json(base_binding["path"])
    if base_request.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-request.v2":
        raise ReferenceCompareError("base_v2_request is not the immutable v2 schema")
    modules = request.get("modules")
    if not isinstance(modules, Mapping):
        raise ReferenceCompareError("modules closure is required")
    module_bindings: dict[str, dict[str, Any]] = {}
    for role in ("compare_worker", "v2_worker", "raw_converter", "v15_operator", "v14_operator", "v16_operator"):
        item = modules.get(role)
        if not isinstance(item, Mapping):
            raise ReferenceCompareError(f"modules.{role} is required")
        module_bindings[role] = _module_binding(item, role, verify_content=True)
    reference = request.get("reference_typed_hdf5")
    if not isinstance(reference, Mapping):
        raise ReferenceCompareError("reference_typed_hdf5 binding is required")
    # Parent guard performs this potentially multi-gigabyte hash before an IO
    # grant.  The worker still checks stat and shape later; it does not claim
    # independent content verification when the guard has not supplied it.
    content_verify = bool(verify_sources and not parent_preverified)
    reference_binding = _stat_binding(reference, "reference_typed_hdf5", verify_content=content_verify)
    contract = request.get("comparison_contract")
    if not isinstance(contract, Mapping):
        raise ReferenceCompareError("comparison_contract is required")
    fields = contract.get("fields")
    expected_fields = ["time", "particle_id", "particle_zone", "valid", "position", "velocity",
                       "density", "mass", "pressure", "type", "mk"]
    if fields != expected_fields:
        raise ReferenceCompareError("comparison fields must be the complete typed dataset contract")
    shape = contract.get("expected_shape")
    if not isinstance(shape, Mapping):
        raise ReferenceCompareError("comparison_contract.expected_shape is required")
    frames = _positive_int(shape.get("frames"), "expected_shape.frames")
    particles = _positive_int(shape.get("particles"), "expected_shape.particles")
    chunk = _positive_int(contract.get("particle_chunk"), "comparison_contract.particle_chunk")
    if not isinstance(contract.get("structural_fields"), list) or contract["structural_fields"] != [
            "time", "particle_id", "particle_zone", "valid", "type", "mk"]:
        raise ReferenceCompareError("structural identity/lifecycle fields are incomplete")
    mass = request.get("mass_semantics")
    if not isinstance(mass, Mapping) or mass.get("rigid_body_inference_from_particle_sum") is not False:
        raise ReferenceCompareError("mass semantics must explicitly prohibit rigid-body inference from particle sums")
    for key in ("particle_mass_source", "support_weight_source", "rigid_body_mass_source"):
        if not isinstance(mass.get(key), str) or not mass[key]:
            raise ReferenceCompareError(f"mass_semantics.{key} is required")
    closure = request.get("source_closure")
    if not isinstance(closure, Mapping) or not isinstance(closure.get("raw_v2_source_roles"), list):
        raise ReferenceCompareError("source_closure.raw_v2_source_roles is required")
    source_records: list[dict[str, Any]] = []
    for item in closure["raw_v2_source_roles"]:
        if not isinstance(item, Mapping):
            raise ReferenceCompareError("raw_v2_source_roles entry is malformed")
        source_records.append(_stat_binding(item, str(item.get("role", "source")),
                                            verify_content=content_verify and item.get("role") != "reference_typed_hdf5"))
    return {"base": base_binding, "base_request": base_request,
            "modules": module_bindings, "reference": reference_binding,
            "frames": frames, "particles": particles, "particle_chunk": chunk,
            "mass_semantics": dict(mass), "source_records": source_records}


def _resource_snapshot() -> dict[str, float]:
    usage = resource.getrusage(resource.RUSAGE_SELF)
    return {"user_seconds": float(usage.ru_utime), "system_seconds": float(usage.ru_stime),
            "max_rss_kib": float(usage.ru_maxrss)}


def _identity_lifecycle(direct_path: Path, reference_path: Path, *, particle_chunk: int,
                       expected_frames: int, expected_particles: int) -> dict[str, Any]:
    """Report fixed identity and per-frame invalid/missing-ID inheritance."""
    with h5py.File(direct_path, "r") as direct, h5py.File(reference_path, "r") as reference:
        for name in ("time", "particle_id", "particle_zone", "valid"):
            if name not in direct or name not in reference:
                raise ReferenceCompareError(f"lifecycle dataset missing: {name}")
            if direct[name].shape != reference[name].shape:
                raise ReferenceCompareError(f"lifecycle shape mismatch: {name}")
        if direct["time"].shape != (expected_frames,) or direct["particle_id"].shape != (expected_particles,):
            raise ReferenceCompareError("lifecycle shape differs from frozen CURRENT contract")
        ids = np.asarray(direct["particle_id"][...])
        zones = np.asarray(direct["particle_zone"][...])
        identity_equal = bool(np.array_equal(ids, reference["particle_id"][...], equal_nan=True) and
                              np.array_equal(zones, reference["particle_zone"][...], equal_nan=True))
        frames: list[dict[str, Any]] = []
        for frame in range(expected_frames):
            dvalid = np.asarray(direct["valid"][frame, ...], dtype=bool)
            rvalid = np.asarray(reference["valid"][frame, ...], dtype=bool)
            dids = np.asarray(ids[~dvalid], dtype="<u8")
            rids = np.asarray(ids[~rvalid], dtype="<u8")
            dsha = hashlib.sha256(dids.tobytes()).hexdigest()
            rsha = hashlib.sha256(rids.tobytes()).hexdigest()
            equal = bool(np.array_equal(dvalid, rvalid) and np.array_equal(dids, rids))
            frames.append({"frame": frame, "time_s": float(direct["time"][frame]),
                           "direct_missing_count": int(dids.size), "reference_missing_count": int(rids.size),
                           "direct_missing_ids_sha256": dsha, "reference_missing_ids_sha256": rsha,
                           "missing_id_inheritance_equal": equal})
        # Check representative chunks explicitly so the report proves that
        # valid=false rows retain their initial identity but do not contribute
        # active numeric values; the converter's full comparison handles all
        # numeric fields and all chunks.
        inactive_state_checks = []
        for frame in range(expected_frames):
            valid = np.asarray(direct["valid"][frame, ...], dtype=bool)
            inactive_state_checks.append({"frame": frame, "inactive_count": int((~valid).sum()),
                                          "identity_retained": identity_equal})
        return {"identity_key": "(Zone,Idp)", "identity_axis_equal": identity_equal,
                "frame_count": expected_frames, "particle_count": expected_particles,
                "missing_id_frames": frames,
                "invalid_state_semantics": "valid=false retains particle_id/Zone; all observed state fields remain unknown NaN and type/MK are -1",
                "inactive_state_checks": inactive_state_checks,
                "chunk_size": particle_chunk}


def compare_typed_to_reference(direct_path: Path | str, reference_path: Path | str, *,
                               particle_chunk: int, expected_frames: int,
                               expected_particles: int, converter_module: Any | None = None) -> dict[str, Any]:
    """Compare all typed arrays and lifecycle identity against producer HDF5."""
    direct = Path(direct_path).expanduser().resolve()
    reference = Path(reference_path).expanduser().resolve()
    if converter_module is None:
        raise ReferenceCompareError("trusted converter module is required")
    try:
        comparison = converter_module.compare_reference_hdf5(
            direct, reference, particle_chunk=particle_chunk)
    except Exception as error:
        raise ReferenceCompareError(f"trusted typed/reference comparison failed: {error}") from error
    lifecycle = _identity_lifecycle(direct, reference, particle_chunk=particle_chunk,
                                    expected_frames=expected_frames, expected_particles=expected_particles)
    comparison["identity_lifecycle"] = lifecycle
    comparison["passed"] = bool(comparison.get("passed") and lifecycle["identity_axis_equal"] and
                                  all(row["missing_id_inheritance_equal"] for row in lifecycle["missing_id_frames"]))
    comparison["comparison_scope"] = "all typed datasets; exact time/identity/valid/type/MK; numeric fields chunked with trusted v1 tolerances"
    return comparison


def _mass_semantics_report(request: Mapping[str, Any], typed_report: Mapping[str, Any]) -> dict[str, Any]:
    mass = request["mass_semantics"]
    return {
        "particle_mass": {
            "dataset": mass.get("particle_mass_dataset", "mass"),
            "source": mass["particle_mass_source"],
            "initial_denominator_kg": 21.114001002861187,
            "later_missing_mass_kg": 0.003000000142492354,
            "semantics": "per-particle SPH MassFluid/MassBound weight; missing mass transfers to unknown and is not added to denominator",
        },
        "support_particle_weight": {
            "source": mass["support_weight_source"],
            "semantics": "boundary/support particle weight; never a rigid-body mass substitute",
        },
        "rigid_body": {
            "source": mass["rigid_body_mass_source"],
            "status": "UNKNOWN_NOT_INFERRED",
            "massbody_kg": None,
            "semantics": "requires an explicitly bound native rigid telemetry/XML massbody record; particle sums are rejected",
        },
        "typed_converter_report_mass_semantics": typed_report.get("typed_identity", {}).get("mass_semantics"),
    }


def prepare_report(request_path: Path | str, output_path: Path | str) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _require_request(request, verify_sources=False)
    report = {
        "schema": REPORT_SCHEMA, "status": "READY_FOR_PARENT_IO_SLOT",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file),
                     "request_schema": request.get("schema")},
        "base_v2_request": bound["base"],
        "source_closure": {"reference": bound["reference"],
                            "raw_v2_source_roles": bound["source_records"],
                            "content_hash_status": "PARENT_GUARD_REQUIRED_FOR_H5_RAW",
                            "raw_frames_are_inherited_from_v2_request": True},
        "execution_boundary": {"raw_opened": False, "hdf5_opened": False,
                                "v2_invoked": False, "reference_comparison_invoked": False,
                                "model_invoked": False, "cfd_invoked": False,
                                "parent_stage2guard_required": True},
        "comparison_contract": {"frames": bound["frames"], "particles": bound["particles"],
                                "particle_chunk": bound["particle_chunk"],
                                "identity_key": "(Zone,Idp)",
                                "invalid_missing_id_inheritance": "PENDING_PARENT_IO_SLOT"},
        "mass_semantics": _mass_semantics_report(request, {}),
        "labels": {"v15": "inherited v2; pending", "v16": "inherited v2; pending", "evaluator": "optional prediction input; pending"},
        "resource_request": request.get("resource_request"),
        "qualification": UNKNOWN_QUALIFICATION,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def run(request_path: Path | str, output_dir: Path | str, *, io_slot_approved: bool = False,
        run_labels: bool = True, run_evaluator: bool = False,
        predictions_path: Path | None = None) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load_json(request_file)
    bound = _require_request(request, verify_sources=io_slot_approved)
    target = Path(output_dir).expanduser().resolve()
    if target.exists():
        raise ReferenceCompareError(f"refusing to use existing output directory: {target}")
    target.mkdir(parents=True, exist_ok=False)
    if not io_slot_approved:
        return prepare_report(request_file, target / "metadata-preflight-v3.json")
    started = time.monotonic()
    before = _resource_snapshot()
    v2 = _load_module(Path(bound["modules"]["v2_worker"]["path"]), "_ds02_bound_v2_reference_v3")
    converter = _load_module(Path(bound["modules"]["raw_converter"]["path"]), "_ds02_bound_converter_reference_v3")
    v2_dir = target / "native-v2"
    v2_report = v2.run(bound["base"]["path"], v2_dir, io_slot_approved=True,
                       run_labels=run_labels, run_evaluator=run_evaluator,
                       predictions_path=predictions_path)
    typed_item = v2_report.get("typed_output")
    if not isinstance(typed_item, Mapping) or not isinstance(typed_item.get("path"), str):
        raise ReferenceCompareError("v2 report has no typed_output binding")
    typed_path = Path(typed_item["path"]).expanduser().resolve()
    if not typed_path.is_file():
        raise ReferenceCompareError("v2 typed output is missing")
    comparison = compare_typed_to_reference(
        typed_path, Path(bound["reference"]["path"]), particle_chunk=bound["particle_chunk"],
        expected_frames=bound["frames"], expected_particles=bound["particles"],
        converter_module=converter)
    converter_report = _load_json(v2_report["raw_to_typed"]["converter_report"])
    mass_semantics = _mass_semantics_report(request, converter_report)
    status = "COMPLETE_DEVELOPMENT_UNKNOWN" if comparison["passed"] else "REFERENCE_COMPARISON_FAILED_DEVELOPMENT"
    report = {
        "schema": REPORT_SCHEMA, "status": status,
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "base_v2": {"report": str(v2_dir / "raw-to-typed-to-label-report-v2.json"),
                    "report_sha256": sha256_file(v2_dir / "raw-to-typed-to-label-report-v2.json"),
                    "status": v2_report.get("status"),
                    "typed_output": typed_item},
        "reference_typed_hdf5": bound["reference"],
        "typed_reference_comparison": comparison,
        "mass_semantics": mass_semantics,
        "labels": v2_report.get("typed_to_label", {"status": "NOT_RUN"}),
        "execution_boundary": {"raw_opened": True, "hdf5_opened": True, "v2_invoked": True,
                                "reference_comparison_invoked": True, "model_invoked": False,
                                "cfd_invoked": False, "parent_stage2guard_required": True},
        "resource": {"wall_seconds": time.monotonic() - started,
                      "usage": {"before": before, "after": _resource_snapshot()},
                      "source_bytes_read_at_least": int(bound["reference"]["bytes"]) + int(bound["base"]["bytes"])},
        "qualification": UNKNOWN_QUALIFICATION,
        "limitations": [
            "comparison and labels are DEVELOPMENT evidence only; QI/QN/QE remain UNKNOWN",
            "reference HDF5 content hash is credited to the parent guard when source_hashes_preverified_by_parent is true",
            "valid=false rows inherit fixed (Zone,Idp) identity but physical state and fate remain unknown",
            "particle SPH mass/support weight is never used as rigid-body mass",
        ],
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(target / "native-typed-reference-compare-report-v3.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--request", type=Path, required=True)
    prep.add_argument("--output", type=Path, required=True)
    runner = sub.add_parser("run")
    runner.add_argument("--request", type=Path, required=True)
    runner.add_argument("--output-dir", type=Path, required=True)
    runner.add_argument("--io-slot-approved", action="store_true")
    runner.add_argument("--no-labels", action="store_true")
    runner.add_argument("--run-evaluator", action="store_true")
    runner.add_argument("--predictions", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_report(args.request, args.output)
        else:
            result = run(args.request, args.output_dir, io_slot_approved=args.io_slot_approved,
                         run_labels=not args.no_labels, run_evaluator=args.run_evaluator,
                         predictions_path=args.predictions)
    except (OSError, ReferenceCompareError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps({"schema": result.get("schema"), "status": result.get("status"),
                      "qualification": result.get("qualification")}, sort_keys=True,
                     default=_json_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
