#!/usr/bin/env python3
"""Convert an actual ROOT279 child observer result into compact scalar reports.

The ROOT279 guarded producer is the only component allowed to open native
Part files.  This additive worker runs after that guard, reads only its small
JSON result and the child observer JSON, and writes one compact report per
same/half attempt.  It never reads BI4/VTK/H5/RunPARTs payloads and it never
uses XML mass as a fallback.

The native ``MassFluid`` and ``MassBound`` header values are per-particle
weights.  This worker therefore emits a sample total only when the child
report exposes typed role counts for fluid and all bound roles (or an explicit
per-ID native-weight total).  Header values alone remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
SCHEMA = "ds02.stage2.f1-s2.root279-native-compact-report.v1"
MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-compact-manifest.v1"
CHILD_SCHEMA = "ds02.stage2.f1.native-selected-observer.v1"
GUARD_SCHEMA = "ds02.stage2.f1-s2.root279-native-observer-guarded.v1"
GUARD_STATUS = "PASS_GUARDED_V1_NATIVE_SELECTED_OBSERVABLES"
PASS_STATUS = "COMPLETE_ROOT279_NATIVE_COMPACT_REPORTS_NO_SCIENTIFIC_Q"
UNKNOWN = "UNKNOWN"
JSON_CAP = 10 * 1024 * 1024
OUTPUT_CAP = 2 * 1024 * 1024
QUALIFICATION = {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0}


class CompactFailure(RuntimeError):
    pass


def _abs(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _record_json(path: Path, label: str, expected: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
        raise CompactFailure(f"{label} is not a regular JSON file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise CompactFailure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    digest = _sha(raw)
    if before != after or len(raw) != before["bytes"]:
        raise CompactFailure(f"{label} changed while being read: {path}")
    if isinstance(expected, dict):
        wanted = expected.get("sha256")
        if isinstance(wanted, str) and len(wanted) == 64 and digest.lower() != wanted.lower():
            raise CompactFailure(f"{label} SHA differs from its producer binding")
        bound_stat = expected.get("stat")
        if isinstance(bound_stat, dict):
            for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
                if key in bound_stat and int(bound_stat[key]) != after[key]:
                    raise CompactFailure(f"{label} {key} differs from its producer binding")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CompactFailure(f"{label} is not bounded UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise CompactFailure(f"{label} is not a JSON object")
    return value, {"path": str(path), "sha256": digest, "stat": after,
                   "bytes": len(raw), "payload_read": True, "scope": "bounded_json_only"}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise CompactFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompactFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise CompactFailure(f"{label} is not finite")
    return result


def _vector(value: Any, label: str) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise CompactFailure(f"{label} is not a three-vector")
    return [_finite(item, f"{label}[{index}]") for index, item in enumerate(value)]


def _header_scalar(header: dict[str, Any], name: str, label: str) -> float | None:
    value = header.get(name)
    if isinstance(value, dict):
        if str(value.get("status", "")).startswith("UNKNOWN") or value.get("value") is None:
            return None
        value = value.get("value")
    if value is None or (isinstance(value, str) and value.startswith("UNKNOWN")):
        return None
    return _finite(value, label)


def _role_counts(row: dict[str, Any], label: str) -> tuple[dict[str, int], bool]:
    observables = row.get("observables")
    value = observables.get("role_counts") if isinstance(observables, dict) else row.get("role_counts")
    if not isinstance(value, dict):
        raise CompactFailure(f"{label} has no native typed role_counts")
    result: dict[str, int] = {}
    for key in ("fluid", "fixed", "moving", "floating", "bound", "total", "unknown"):
        if key not in value:
            continue
        number = _finite(value[key], f"{label} role_counts.{key}")
        if number < 0 or not number.is_integer():
            raise CompactFailure(f"{label} role_counts.{key} is not a nonnegative integer")
        result[key] = int(number)
    if "fluid" not in result:
        raise CompactFailure(f"{label} lacks typed fluid count")
    unknown = result.get("unknown", 0)
    complete_bound = False
    if "bound" in result:
        complete_bound = True
    elif all(key in result for key in ("fixed", "moving", "floating")) and unknown == 0:
        result["bound"] = result["fixed"] + result["moving"] + result["floating"]
        complete_bound = True
    if "total" in result and complete_bound and result["total"] != result["fluid"] + result["bound"]:
        raise CompactFailure(f"{label} typed role counts do not sum to total")
    return result, complete_bound


def _compact_row(row: dict[str, Any], label: str) -> dict[str, Any]:
    time_s = _finite(row.get("time_s"), f"{label} time_s")
    header = row.get("native_header")
    if not isinstance(header, dict):
        raise CompactFailure(f"{label} lacks native_header")
    mass_fluid = _header_scalar(header, "MassFluid", f"{label} MassFluid")
    mass_bound = _header_scalar(header, "MassBound", f"{label} MassBound")
    dp = _header_scalar(header, "Dp", f"{label} Dp")
    roles, complete_bound = _role_counts(row, label)
    observables = row.get("observables")
    if not isinstance(observables, dict):
        raise CompactFailure(f"{label} lacks observables")
    fluid = observables.get("fluid_observable_using_native_MassFluid")
    if not isinstance(fluid, dict):
        raise CompactFailure(f"{label} lacks native MassFluid fluid observables")
    if fluid.get("mass_semantics") and "native" not in str(fluid["mass_semantics"]).lower():
        raise CompactFailure(f"{label} fluid mass semantics are not native")
    excluded = observables.get("fixed_moving_excluded_from_fluid_observables")
    if excluded is not True:
        raise CompactFailure(f"{label} does not exclude bound roles from fluid observables")
    count = int(_finite(fluid.get("count"), f"{label} fluid observable count"))
    if count != roles["fluid"]:
        raise CompactFailure(f"{label} fluid observable count differs from typed fluid count")
    weighted_com = fluid.get("weighted_centroid_m")
    weighted_velocity = fluid.get("weighted_velocity_m_per_s")
    if weighted_com is None or weighted_velocity is None:
        raise CompactFailure(f"{label} lacks native fluid COM/velocity")
    sample_mass = fluid.get("sample_mass_kg")
    if sample_mass is not None:
        sample_mass = _finite(sample_mass, f"{label} fluid sample mass")
        if mass_fluid is None or abs(sample_mass - count * mass_fluid) > max(1e-12, abs(sample_mass) * 1e-9):
            raise CompactFailure(f"{label} fluid sample mass is not MassFluid times typed fluid count")
    accounting: dict[str, Any] = {"basis": "UNKNOWN_NATIVE_SAMPLE_TOTAL_REQUIRES_TYPED_ROLE_WEIGHTS"}
    total: float | None = None
    if complete_bound and mass_fluid is not None and mass_bound is not None:
        total = roles["fluid"] * mass_fluid + roles["bound"] * mass_bound
        accounting = {
            "basis": "PER_PARTICLE_NATIVE_HEADER_TIMES_TYPED_ROLE_COUNTS",
            "fluid_count": roles["fluid"], "bound_count": roles["bound"],
            "mass_fluid_per_particle_kg": mass_fluid,
            "mass_bound_per_particle_kg": mass_bound,
        }
    elif isinstance(row.get("native_mass_accounting"), dict) and row["native_mass_accounting"].get("basis") == "PER_ID_NATIVE_MASS_WEIGHTS":
        value = row["native_mass_accounting"].get("total_mass_kg")
        if value is not None:
            total = _finite(value, f"{label} per-ID total mass")
            accounting = {"basis": "PER_ID_NATIVE_MASS_WEIGHTS", "total_mass_kg": total}
    kinetic = fluid.get("kinetic_energy_j")
    kinetic_value = _finite(kinetic, f"{label} fluid kinetic energy") if kinetic is not None else None
    kinetic_basis = fluid.get("kinetic_energy_basis")
    if kinetic_value is not None and kinetic_basis not in {None, "NATIVE_PER_PARTICLE_VELOCITY_SUM"}:
        # The frozen ROOT279 child computes Σ 0.5*m_i*|v_i|² using its
        # native per-particle MassFluid.  A future aggregate/COM field must
        # remain UNKNOWN until it declares a different valid per-ID basis.
        kinetic_value = None
        kinetic_basis = "UNKNOWN_TOTAL_KE_BASIS"
    if kinetic_value is not None:
        kinetic_basis = "NATIVE_PER_PARTICLE_VELOCITY_SUM"
    return {
        "time_s": time_s,
        "native_header": {"MassFluid": mass_fluid, "MassBound": mass_bound, "Dp": dp,
                           "mass_semantics": "PER_PARTICLE_NATIVE_HEADER_WEIGHT"},
        "role_counts": roles,
        "fixed_moving_excluded_from_fluid_observables": True,
        "native_mass_accounting": accounting,
        "native_sample_mass_total_kg": total,
        "fluid": {
            "mass_kg": sample_mass,
            "mass_basis": "native_per_particle_mass_times_typed_fluid_count" if sample_mass is not None else "UNKNOWN_NATIVE_WEIGHT_BASIS",
            "velocity_m_per_s": _vector(weighted_velocity, f"{label} weighted velocity"),
            "com_m": _vector(weighted_com, f"{label} weighted COM"),
            "kinetic_energy_j": kinetic_value,
            "kinetic_energy_basis": kinetic_basis if kinetic_value is not None else "UNKNOWN_TOTAL_KE_BASIS",
            "kinetic_energy_basis_source": "ROOT279_F1_NATIVE_SELECTED_OBSERVER_V1_PER_PARTICLE_MASS_VELOCITY_SUM" if kinetic_value is not None else "UNKNOWN",
            "com_translational_energy_basis": "DERIVED_COM_SPEED_ONLY",
        },
    }


def _write_once(path: Path, value: dict[str, Any]) -> None:
    path = _abs(path)
    if path.exists() or path.is_symlink():
        raise CompactFailure(f"refusing to overwrite compact output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > OUTPUT_CAP:
        raise CompactFailure(f"compact report exceeds 2 MiB: {path}")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(raw)
    os.replace(temporary, path)


def _case_map(child: dict[str, Any]) -> dict[str, dict[str, Any]]:
    cases = child.get("cases")
    if not isinstance(cases, list):
        raise CompactFailure("ROOT279 child report has no cases")
    result: dict[str, dict[str, Any]] = {}
    for case in cases:
        if not isinstance(case, dict) or case.get("label") not in {"same_cfl", "half_cfl"}:
            raise CompactFailure("ROOT279 child case set is invalid")
        label = str(case["label"])
        if label in result:
            raise CompactFailure(f"duplicate ROOT279 child case: {label}")
        result[label] = case
    if set(result) != {"same_cfl", "half_cfl"}:
        raise CompactFailure("ROOT279 child case set is incomplete")
    return result


def _case_report(label: str, case: dict[str, Any], source_identity_digest: str,
                 guard_record: dict[str, Any], child_record: dict[str, Any]) -> dict[str, Any]:
    rows = case.get("selected_observations")
    if not isinstance(rows, list) or not rows:
        raise CompactFailure(f"{label} child case has no selected_observations")
    compact_rows = [_compact_row(row, f"{label} frame {index}") for index, row in enumerate(rows)]
    if any(right["time_s"] <= left["time_s"] for left, right in zip(compact_rows, compact_rows[1:])):
        raise CompactFailure(f"{label} selected times are not strictly increasing")
    identity = case.get("identity") if isinstance(case.get("identity"), dict) else {}
    return {
        "schema": SCHEMA,
        "status": "COMPLETE_ROOT279_NATIVE_COMPACT_REPORT",
        "source_identity_digest": source_identity_digest,
        "world_orientation": UNKNOWN,
        "attempt": {"label": label, "identity": identity},
        "producer": {"guard_result": guard_record, "child_report": child_record,
                      "native_reader": "ROOT279 guarded producer only",
                      "native_payload_read_by_compactor": False},
        "mass_semantics": {
            "MassFluid": "PER_FLUID_PARTICLE_KG",
            "MassBound": "PER_BOUND_PARTICLE_KG",
            "sample_total": "typed_role_counts_or_per_id_weights_only",
            "xml_mass_fallback": False,
        },
        "observations": compact_rows,
        "axis_scope": {"producer_component_basis": True, "producer_to_world_orientation": UNKNOWN,
                        "world_directional_velocity": UNKNOWN, "flux": UNKNOWN, "owner_mass": UNKNOWN},
        "scientific_qualification": dict(QUALIFICATION),
        "read_scope": {"compact_json_only": True, "native_bi4": False, "vtk": False,
                        "hdf5": False, "solver_launch": False, "gencase_launch": False},
    }


def run(manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    manifest, manifest_record = _record_json(manifest_path, "ROOT279 compact manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise CompactFailure("compact manifest schema mismatch")
    if manifest.get("status") not in {"READY_FOR_PARENT_ROOT279_NATIVE_COMPACT", "WAITING_PARENT_ROOT279_NATIVE_COMPACT"}:
        raise CompactFailure("compact manifest is not parent-ready")
    source_digest = manifest.get("source_identity_digest")
    if not isinstance(source_digest, str) or len(source_digest) < 16 or source_digest in {UNKNOWN, "PARENT_AFTER_RESERVATION_REQUIRED"}:
        raise CompactFailure("compact manifest source identity is not bound")
    guard_ref = manifest.get("guard_result")
    child_ref = manifest.get("child_report")
    guard, guard_record = _record_json(Path(guard_ref["path"]), "ROOT279 guarded result", guard_ref)
    child, child_record = _record_json(Path(child_ref["path"]), "ROOT279 child observer result", child_ref)
    if guard.get("schema") != GUARD_SCHEMA or guard.get("status") != GUARD_STATUS:
        raise CompactFailure("ROOT279 guard schema/status is not exact")
    if child.get("schema") != CHILD_SCHEMA or child.get("status") != GUARD_STATUS:
        raise CompactFailure("ROOT279 child schema/status is not exact")
    output_paths = manifest.get("outputs")
    if not isinstance(output_paths, dict):
        raise CompactFailure("compact manifest has no output paths")
    cases = _case_map(child)
    outputs: dict[str, dict[str, Any]] = {}
    for label in ("same_cfl", "half_cfl"):
        ref = output_paths.get(label)
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str):
            raise CompactFailure(f"compact output path missing for {label}")
        report = _case_report(label, cases[label], source_digest, guard_record, child_record)
        _write_once(Path(ref["path"]), report)
        _, out_record = _record_json(Path(ref["path"]), f"{label} compact output")
        outputs[label] = out_record
    result = {
        "schema": "ds02.stage2.f1-s2.root279-native-compact-worker.v1",
        "status": PASS_STATUS,
        "manifest": manifest_record,
        "guard_result": guard_record,
        "child_report": child_record,
        "compact_reports": outputs,
        "source_identity_digest": source_digest,
        "native_header_semantics": "MassFluid/MassBound are per-particle; sample total requires typed counts or per-ID weights",
        "scientific_qualification": dict(QUALIFICATION),
        "read_scope": {"guard_child_json_only": True, "native_payload_read": False,
                        "solver_launch": False, "gencase_launch": False},
    }
    result_path = manifest.get("result_path")
    if isinstance(result_path, str):
        _write_once(Path(result_path), result)
        result["result"] = _record_json(Path(result_path), "compact worker result")[1]
    return result


def _fixture_child(root: Path) -> tuple[Path, Path]:
    guard = root / "guard.json"
    child = root / "child.json"
    guard.write_text(json.dumps({"schema": GUARD_SCHEMA, "status": GUARD_STATUS}) + "\n", encoding="utf-8")
    rows = []
    for i, time_s in enumerate((0.0, 0.25, 0.5)):
        rows.append({"frame": i, "time_s": time_s,
                     "native_header": {"MassFluid": {"value": 2.0}, "MassBound": {"value": 1.0}, "Dp": {"value": .1}},
                     "observables": {"role_counts": {"fluid": 2, "fixed": 1, "moving": 0, "floating": 0, "total": 3},
                                     "fixed_moving_excluded_from_fluid_observables": True,
                                     "fluid_observable_using_native_MassFluid": {
                                         "count": 2, "sample_mass_kg": 4.0,
                                         "weighted_centroid_m": [i + 1.0, 2.0, 3.0],
                                         "weighted_velocity_m_per_s": [3.0 + i, 4.0, 0.0],
                                         "kinetic_energy_j": 0.5 * 4.0 * ((3.0 + i) ** 2 + 16.0),
                                         "kinetic_energy_basis": "NATIVE_PER_PARTICLE_VELOCITY_SUM",
                                         "mass_semantics": "native_header_MassFluid_times_typed_fluid_count",
                                     }} })
    child.write_text(json.dumps({"schema": CHILD_SCHEMA, "status": GUARD_STATUS,
                                 "cases": [{"label": "same_cfl", "identity": {}, "selected_observations": rows},
                                           {"label": "half_cfl", "identity": {}, "selected_observations": rows}]}) + "\n", encoding="utf-8")
    return guard, child


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="root279-compact-worker-") as value:
        root = Path(value); guard, child = _fixture_child(root)
        g = _record_json(guard, "fixture guard")[1]; c = _record_json(child, "fixture child")[1]
        manifest = {"schema": MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                    "source_identity_digest": "fixture-root279-source-identity",
                    "guard_result": g, "child_report": c,
                    "outputs": {label: {"path": str(root / f"{label}.json")} for label in ("same_cfl", "half_cfl")}}
        manifest_path = root / "manifest.json"; manifest_path.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
        result = run(manifest_path, root / "outputs")
        assert result["status"] == PASS_STATUS
        same = json.loads((root / "same_cfl.json").read_text())
        assert same["observations"][0]["native_header"]["MassFluid"] == 2.0
        assert same["observations"][0]["native_mass_accounting"]["basis"] == "PER_PARTICLE_NATIVE_HEADER_TIMES_TYPED_ROLE_COUNTS"
        assert same["observations"][0]["native_sample_mass_total_kg"] == 5.0
        assert same["observations"][0]["fluid"]["kinetic_energy_basis"] == "NATIVE_PER_PARTICLE_VELOCITY_SUM"
        # Header-only reports are rejected rather than silently treated as
        # case totals; the scalar v2 worker separately exercises UNKNOWN.
        bad = json.loads(child.read_text()); bad["cases"][0]["selected_observations"][0]["observables"]["role_counts"] = {"fluid": 2}
        bad_path = root / "bad-child.json"; bad_path.write_text(json.dumps(bad) + "\n")
        bad_manifest = dict(manifest, child_report=dict(c, path=str(bad_path), sha256=_sha(bad_path.read_bytes()), stat=_stat(bad_path)))
        bad_manifest_path = root / "bad-manifest.json"; bad_manifest_path.write_text(json.dumps(bad_manifest) + "\n")
        try:
            run(bad_manifest_path, root / "bad-out")
        except CompactFailure:
            pass
        else:
            raise AssertionError("incomplete typed role report was accepted")
    print("PASS_ROOT279_NATIVE_COMPACT_WORKER_TYPED_MASS_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--run", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.manifest is None or args.output_dir is None:
            parser.error("--run requires --manifest and --output-dir")
        result = run(args.manifest, args.output_dir)
        print(json.dumps({"status": result["status"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (CompactFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_COMPACT_WORKER: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
