#!/usr/bin/env python3
"""Independently verify the ROOT279 compact→scalar diagnostic chain.

This verifier is deliberately separate from both the native producer and the
scalar consumer.  It reads only bounded JSON: the compact reports, the scalar
manifest/result, and the producer guard/child records carried by the compact
manifest.  It checks exact source identity and SHA/stat joins, per-particle
MassFluid/MassBound semantics, typed-role accounting, exact-time matching,
and the permanent no-Q scope.  It never opens native Part/BI4/VTK/H5 data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
COMPACT_SCHEMA = "ds02.stage2.f1-s2.root279-native-compact-report.v1"
COMPACT_MANIFEST_SCHEMA = "ds02.stage2.f1-s2.root279-native-compact-manifest.v1"
SCALAR_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-observer.v2"
SCALAR_MANIFEST_SCHEMA = "ds02.stage2.rotation-invariant-native-scalar-manifest.v2"
SCALAR_STATUS = "COMPLETE_ROTATION_INVARIANT_NATIVE_SCALAR_DIAGNOSTIC"
STATUS = "VERIFIED_ROOT279_NATIVE_SCALAR_COMPACT_CHAIN_METADATA_ONLY"
JSON_CAP = 10 * 1024 * 1024
UNKNOWN = "UNKNOWN"


class VerificationFailure(RuntimeError):
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


def _read(path: Path, label: str, expected: dict[str, Any] | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.suffix.lower() != ".json" or path.is_symlink() or not path.is_file():
        raise VerificationFailure(f"{label} is not a regular JSON file")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise VerificationFailure(f"{label} exceeds 10 MiB metadata cap")
    raw = path.read_bytes(); after = _stat(path); digest = _sha(raw)
    if before != after:
        raise VerificationFailure(f"{label} changed while being read")
    if isinstance(expected, dict):
        if isinstance(expected.get("sha256"), str) and len(expected["sha256"]) == 64 and digest.lower() != expected["sha256"].lower():
            raise VerificationFailure(f"{label} SHA differs from bound source")
        bound = expected.get("stat")
        if isinstance(bound, dict):
            for key in ("device", "inode", "bytes", "mtime_ns", "ctime_ns"):
                if key in bound and int(bound[key]) != after[key]:
                    raise VerificationFailure(f"{label} {key} differs from bound source")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VerificationFailure(f"{label} is not valid bounded JSON") from exc
    if not isinstance(value, dict):
        raise VerificationFailure(f"{label} root is not an object")
    return value, {"path": str(path), "sha256": digest, "stat": after, "bytes": len(raw)}


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool):
        raise VerificationFailure(f"{label} is boolean")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise VerificationFailure(f"{label} is not numeric") from exc
    if not math.isfinite(result):
        raise VerificationFailure(f"{label} is not finite")
    return result


def _rows(report: dict[str, Any], label: str) -> list[dict[str, Any]]:
    if report.get("schema") != COMPACT_SCHEMA or report.get("status") != "COMPLETE_ROOT279_NATIVE_COMPACT_REPORT":
        raise VerificationFailure(f"{label} compact schema/status mismatch")
    if report.get("world_orientation") != UNKNOWN:
        raise VerificationFailure(f"{label} asserts producer world orientation")
    rows = report.get("observations")
    if not isinstance(rows, list) or not rows:
        raise VerificationFailure(f"{label} compact report has no observations")
    last = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise VerificationFailure(f"{label} row {index} is malformed")
        time_s = _finite(row.get("time_s"), f"{label} row time")
        if last is not None and time_s <= last:
            raise VerificationFailure(f"{label} saved times are not increasing")
        last = time_s
        header = row.get("native_header")
        if not isinstance(header, dict) or header.get("mass_semantics") != "PER_PARTICLE_NATIVE_HEADER_WEIGHT":
            raise VerificationFailure(f"{label} row does not declare per-particle header semantics")
        accounting = row.get("native_mass_accounting")
        if not isinstance(accounting, dict):
            raise VerificationFailure(f"{label} row lacks native mass accounting status")
        basis = accounting.get("basis")
        roles = row.get("role_counts")
        if not isinstance(roles, dict) or not isinstance(roles.get("fluid"), int):
            raise VerificationFailure(f"{label} row lacks typed fluid role count")
        total = row.get("native_sample_mass_total_kg")
        # The compact report intentionally does not carry a precomputed total;
        # the scalar worker computes it from this exact accounting basis.  If a
        # future producer does carry one, verify rather than trust it.
        if total is not None:
            _finite(total, f"{label} sample total")
        if basis == "PER_PARTICLE_NATIVE_HEADER_TIMES_TYPED_ROLE_COUNTS":
            if not isinstance(roles.get("bound"), int):
                raise VerificationFailure(f"{label} typed-total row lacks bound count")
            mf = header.get("MassFluid"); mb = header.get("MassBound")
            if mf is None or mb is None:
                raise VerificationFailure(f"{label} typed-total row lacks both per-particle weights")
            expected_total = roles["fluid"] * _finite(mf, f"{label} MassFluid") + roles["bound"] * _finite(mb, f"{label} MassBound")
            if total is None or abs(float(total) - expected_total) > max(1e-12, abs(expected_total) * 1e-9):
                raise VerificationFailure(f"{label} typed sample total is not the per-particle weighted sum")
        elif basis not in {"UNKNOWN_NATIVE_SAMPLE_TOTAL_REQUIRES_TYPED_ROLE_WEIGHTS", "PER_ID_NATIVE_MASS_WEIGHTS"}:
            raise VerificationFailure(f"{label} has unsupported mass accounting basis")
        elif basis == "UNKNOWN_NATIVE_SAMPLE_TOTAL_REQUIRES_TYPED_ROLE_WEIGHTS" and total is not None:
            raise VerificationFailure(f"{label} reports a sample total without typed/native weights")
        fluid = row.get("fluid")
        if not isinstance(fluid, dict) or fluid.get("mass_basis") not in {"native_per_particle_mass_times_typed_fluid_count", "UNKNOWN_NATIVE_WEIGHT_BASIS"}:
            raise VerificationFailure(f"{label} fluid mass basis is not explicit")
        kinetic = fluid.get("kinetic_energy_j")
        kinetic_basis = fluid.get("kinetic_energy_basis")
        if kinetic is not None:
            _finite(kinetic, f"{label} total kinetic energy")
            if kinetic_basis != "NATIVE_PER_PARTICLE_VELOCITY_SUM":
                raise VerificationFailure(f"{label} total kinetic energy is not a per-particle velocity sum")
            if fluid.get("kinetic_energy_basis_source") != "ROOT279_F1_NATIVE_SELECTED_OBSERVER_V1_PER_PARTICLE_MASS_VELOCITY_SUM":
                raise VerificationFailure(f"{label} total kinetic energy lacks frozen producer basis provenance")
        elif kinetic_basis not in {None, "UNKNOWN_TOTAL_KE_BASIS"}:
            raise VerificationFailure(f"{label} missing kinetic energy has an unsupported basis")
        if fluid.get("com_translational_energy_basis") not in {None, "DERIVED_COM_SPEED_ONLY"}:
            raise VerificationFailure(f"{label} COM energy basis is not explicitly derived")
        for key in ("velocity_m_per_s", "com_m"):
            value = fluid.get(key)
            if not isinstance(value, list) or len(value) != 3:
                raise VerificationFailure(f"{label} fluid {key} is not a vector")
            for item in value:
                _finite(item, f"{label} fluid {key}")
    return rows


def _record_ref(value: Any, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise VerificationFailure(f"{label} has no exact path record")
    return _read(Path(value["path"]), label, value)


def verify(compact_manifest_path: Path, scalar_manifest_path: Path,
           scalar_output_path: Path, verification_output: Path | None = None) -> dict[str, Any]:
    compact_manifest, compact_manifest_record = _read(compact_manifest_path, "compact manifest")
    if compact_manifest.get("schema") != COMPACT_MANIFEST_SCHEMA:
        raise VerificationFailure("compact manifest schema mismatch")
    identity = compact_manifest.get("source_identity_digest")
    if not isinstance(identity, str) or identity in {UNKNOWN, "PARENT_AFTER_RESERVATION_REQUIRED"}:
        raise VerificationFailure("compact source identity is not bound")
    guard, guard_record = _record_ref(compact_manifest.get("guard_result"), "ROOT279 guard result")
    child, child_record = _record_ref(compact_manifest.get("child_report"), "ROOT279 child report")
    if not str(guard.get("status", "")).startswith("PASS"):
        raise VerificationFailure("ROOT279 producer guard is not PASS")
    if not str(child.get("status", "")).startswith("PASS"):
        raise VerificationFailure("ROOT279 child observer is not PASS")
    compact_outputs = compact_manifest.get("outputs")
    if not isinstance(compact_outputs, dict):
        raise VerificationFailure("compact manifest has no output records")
    compact_values: dict[str, dict[str, Any]] = {}
    compact_records: dict[str, dict[str, Any]] = {}
    for label in ("same_cfl", "half_cfl"):
        value, record = _record_ref(compact_outputs.get(label), f"{label} compact report")
        if value.get("source_identity_digest") != identity:
            raise VerificationFailure(f"{label} compact source identity differs")
        producer = value.get("producer")
        if not isinstance(producer, dict):
            raise VerificationFailure(f"{label} compact report lacks producer closure")
        for key, actual in (("guard_result", guard_record), ("child_report", child_record)):
            bound = producer.get(key)
            if not isinstance(bound, dict) or bound.get("path") != actual["path"] or bound.get("sha256") != actual["sha256"]:
                raise VerificationFailure(f"{label} compact {key} is not bound to actual producer")
        _rows(value, label)
        compact_values[label] = value; compact_records[label] = record
    scalar_manifest, scalar_manifest_record = _read(scalar_manifest_path, "scalar manifest")
    if scalar_manifest.get("schema") != SCALAR_MANIFEST_SCHEMA:
        raise VerificationFailure("scalar manifest schema mismatch")
    if scalar_manifest.get("source_identity", {}).get("source_identity_digest") != identity:
        raise VerificationFailure("scalar manifest source identity differs from compact producer")
    scalar_output, scalar_output_record = _read(scalar_output_path, "scalar result")
    if scalar_output.get("schema") != SCALAR_SCHEMA or scalar_output.get("status") != SCALAR_STATUS:
        raise VerificationFailure("scalar result schema/status mismatch")
    if scalar_output.get("source_identity", {}).get("source_identity_digest") != identity:
        raise VerificationFailure("scalar result source identity differs")
    if scalar_output.get("scientific_qualification", {}).get("scientific_credit", 1) != 0:
        raise VerificationFailure("scalar result grants scientific credit")
    axis = scalar_output.get("axis_scope")
    if not isinstance(axis, dict) or axis.get("producer_to_world_orientation") != UNKNOWN or axis.get("flux") != UNKNOWN:
        raise VerificationFailure("scalar result widens world/flux scope")
    # Ensure the consumer's two report records point to the exact compact files.
    attempt_rows = scalar_output.get("attempts")
    if not isinstance(attempt_rows, list) or {item.get("label") for item in attempt_rows if isinstance(item, dict)} != {"same-cfl", "half-cfl"}:
        raise VerificationFailure("scalar result attempt set is incomplete")
    expected_paths = {compact_records["same_cfl"]["path"], compact_records["half_cfl"]["path"]}
    actual_paths = {item.get("report", {}).get("path") for item in attempt_rows if isinstance(item, dict)}
    if actual_paths != expected_paths:
        raise VerificationFailure("scalar result reports are not the actual compact producer outputs")
    for query in scalar_output.get("matched_queries", []):
        metrics = query.get("metrics") if isinstance(query, dict) else None
        if isinstance(metrics, dict) and "mass_total_delta_kg" in metrics:
            raise VerificationFailure("scalar result contains deprecated header-sum mass metric")
    result = {
        "schema": "ds02.stage2.f1-s2.root279-native-scalar-verifier.v1",
        "status": STATUS,
        "compact_manifest": compact_manifest_record,
        "producer": {"guard_result": guard_record, "child_report": child_record,
                     "same_cfl_compact": compact_records["same_cfl"], "half_cfl_compact": compact_records["half_cfl"]},
        "scalar": {"manifest": scalar_manifest_record, "result": scalar_output_record},
        "native_mass_policy": "MassFluid/MassBound are per-particle weights; sample total requires typed role counts or per-ID native weights",
        "axis_scope": {"producer_component_basis": True, "world_orientation": UNKNOWN,
                       "world_directional_velocity": UNKNOWN, "flux": UNKNOWN, "owner_mass": UNKNOWN},
        "scientific_qualification": {"QI": UNKNOWN, "QN": UNKNOWN, "QE": UNKNOWN, "scientific_credit": 0},
        "read_scope": {"json_metadata_only": True, "native_payload_read": False, "solver_launch": False,
                        "gencase_launch": False, "interpolation": False},
    }
    if verification_output is not None:
        output = _abs(verification_output)
        if output.exists() or output.is_symlink():
            raise VerificationFailure(f"refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    # Build an actual compact report from the compact worker's manufactured
    # producer output, then run the real v2 scalar consumer and this verifier.
    import importlib.util
    worker_path = HERE / "stage2_f1_s2_root279_native_compact_worker_v1.py"
    scalar_path = HERE / "stage2_rotation_invariant_native_scalar_observer_v2.py"
    spec = importlib.util.spec_from_file_location("compact_fixture", worker_path)
    assert spec and spec.loader
    compact = importlib.util.module_from_spec(spec); spec.loader.exec_module(compact)
    scalar_spec = importlib.util.spec_from_file_location("scalar_fixture", scalar_path)
    assert scalar_spec and scalar_spec.loader
    scalar = importlib.util.module_from_spec(scalar_spec); scalar_spec.loader.exec_module(scalar)
    with tempfile.TemporaryDirectory(prefix="root279-scalar-verifier-") as value:
        root = Path(value); guard, child = compact._fixture_child(root)
        g = compact._record_json(guard, "fixture guard")[1]; c = compact._record_json(child, "fixture child")[1]
        identity = "fixture-root279-source-identity"
        manifest = {"schema": compact.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROOT279_NATIVE_COMPACT",
                    "source_identity_digest": identity, "guard_result": g, "child_report": c,
                    "outputs": {label: {"path": str(root / f"{label}.compact.json")} for label in ("same_cfl", "half_cfl")}}
        manifest_path = root / "compact-manifest.json"; manifest_path.write_text(json.dumps(manifest) + "\n")
        compact.run(manifest_path, root / "compact-out")
        reports = {label: root / f"{label}.compact.json" for label in ("same_cfl", "half_cfl")}
        scalar_manifest = {"schema": scalar.MANIFEST_SCHEMA, "status": "READY_FOR_PARENT_ROTATION_INVARIANT_NATIVE_SCALAR",
                           "source_identity": {"source_identity_digest": identity, "component_basis": "PRODUCER_COMPONENT_XYZ",
                                               "world_orientation": UNKNOWN, "world_directional_claims": False,
                                               "flux_claims": False, "owner_mass_claims": False},
                           "attempts": [{"label": "same-cfl", "attempt_id": "same", "rows_key": "observations",
                                         "source_identity_digest": identity, "report": {"path": str(reports["same_cfl"]), "sha256": _sha(reports["same_cfl"].read_bytes()), "stat": _stat(reports["same_cfl"])}},
                                        {"label": "half-cfl", "attempt_id": "half", "rows_key": "observations",
                                         "source_identity_digest": identity, "report": {"path": str(reports["half_cfl"]), "sha256": _sha(reports["half_cfl"].read_bytes()), "stat": _stat(reports["half_cfl"])} }],
                           "query_times_s": [0.0, 0.25, 0.5]}
        scalar_manifest_path = root / "scalar-manifest.json"; scalar_manifest_path.write_text(json.dumps(scalar_manifest) + "\n")
        scalar_output_path = root / "scalar.json"; scalar.run(scalar_manifest_path, scalar_output_path)
        result = verify(manifest_path, scalar_manifest_path, scalar_output_path)
        assert result["status"] == STATUS
        bad = json.loads(scalar_output_path.read_text()); bad["axis_scope"]["flux"] = "KNOWN"
        bad_path = root / "bad-scalar.json"; bad_path.write_text(json.dumps(bad) + "\n")
        try:
            verify(manifest_path, scalar_manifest_path, bad_path)
        except VerificationFailure:
            pass
        else:
            raise AssertionError("world/flux scope widening was accepted")
    print("PASS_ROOT279_NATIVE_SCALAR_INDEPENDENT_VERIFIER_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--verify", action="store_true")
    parser.add_argument("--compact-manifest", type=Path)
    parser.add_argument("--scalar-manifest", type=Path)
    parser.add_argument("--scalar-output", type=Path)
    parser.add_argument("--verification-output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if any(item is None for item in (args.compact_manifest, args.scalar_manifest, args.scalar_output)):
            parser.error("--verify requires --compact-manifest, --scalar-manifest and --scalar-output")
        result = verify(args.compact_manifest, args.scalar_manifest, args.scalar_output, args.verification_output)
        print(json.dumps({"status": result["status"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (VerificationFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_ROOT279_NATIVE_SCALAR_VERIFIER: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
