#!/usr/bin/env python3
"""Generate immutable, metadata-only structural receipts for the F3 cases.

The legacy F3 audit already scanned each native trajectory and retained the
structural observations, but ``core_f3_legacy_audit.py`` exposed only its hard
integrity result.  This generator revalidates the retained audit and prepared
records, binds every source hash to the current reader manifest, and emits one
receipt per case plus a content-addressed receipt-set index.

It does not open an HDF5 trajectory, rewrite a source manifest, change
``formal_release``, or claim numerical/material qualification.  An existing
receipt is immutable: rerunning this command with the same output path checks
the caller's workflow rather than silently replacing evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence


RECEIPT_SCHEMA = "core.f3.structural_audit_receipt.v1"
ADAPTER_SCHEMA = "core.f3.structural_audit_adapter.v1"
GENERATOR_VERSION = "f3-structural-receipts-v1"
EXPECTED_FAMILY = "F3"
EXPECTED_CASE_COUNT = 32
EXPECTED_CLOSED_FACES = ("bottom", "left", "right", "front", "back")
EXPECTED_OPEN_FACES = ("top",)
EXPECTED_WALL = {
    "xmin": -0.45,
    "xmax": 0.45,
    "ymin": -0.09,
    "ymax": 0.09,
    "zmin": 0.0,
    "zmax": 0.51,
}
UNIT_CONTRACT = {
    "position": "m",
    "velocity": "m/s",
    "time": "s",
    "mass": "kg",
    "density": "kg/m^3",
    "pressure": "Pa",
    "gravity": "m/s^2",
    "resolution": "m",
}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(path: str | Path) -> str:
    hasher = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            hasher.update(block)
    return hasher.hexdigest()


def _relative(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise ValueError(f"evidence path must remain under data root: {path}") from error


def _resolve(value: str | Path, *, root: Path, base: Path | None = None) -> Path:
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    options = []
    if base is not None:
        options.append((base / candidate).resolve())
    options.append((root / candidate).resolve())
    for option in options:
        if option.exists():
            return option
    return options[0]


def _load_json(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return payload


def _bound_json(reference: Mapping[str, Any], *, root: Path, base: Path,
                role: str) -> tuple[Mapping[str, Any], dict[str, Any]]:
    path_value = reference.get("path")
    declared = reference.get("sha256")
    if not isinstance(path_value, str) or not isinstance(declared, str):
        raise ValueError(f"{role} must declare path and sha256")
    path = _resolve(path_value, root=root, base=base)
    if not path.is_file():
        raise ValueError(f"{role} is missing: {path}")
    observed = digest(path)
    if observed.lower() != declared.lower():
        raise ValueError(f"{role} hash mismatch: {path}")
    return _load_json(path), {
        "role": role,
        "path": _relative(path, root),
        "sha256": observed,
        "bytes": path.stat().st_size,
    }


def _finite(value: Any) -> bool:
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return math.isfinite(float(value))
    if isinstance(value, (list, tuple)):
        return all(_finite(item) for item in value)
    if isinstance(value, Mapping):
        return all(_finite(item) for item in value.values())
    return value is None or isinstance(value, str)


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _wall_pass(audit: Mapping[str, Any], prepared: Mapping[str, Any]) -> tuple[bool, dict[str, Any]]:
    wall = audit.get("wall_spec")
    if not isinstance(wall, Mapping):
        wall = prepared.get("wall_spec")
    _require(isinstance(wall, Mapping), "F3 structural wall spec is missing")
    bounds = wall.get("container_interior")
    _require(isinstance(bounds, Mapping), "F3 structural wall bounds are missing")
    observed = {key: bounds.get(key) for key in EXPECTED_WALL}
    bounds_pass = all(
        isinstance(observed[key], (int, float))
        and math.isclose(float(observed[key]), expected, rel_tol=0.0, abs_tol=1e-12)
        for key, expected in EXPECTED_WALL.items()
    )
    closed = tuple(wall.get("closed_faces", ()))
    opened = tuple(wall.get("open_faces", ()))
    penetration = audit.get("penetration")
    _require(isinstance(penetration, Mapping), "F3 penetration observation is missing")
    zero_fields = (
        "frames_with_penetration", "frames_with_runtime_domain_outside",
        "frames_with_swept_crossing", "swept_crossing_count",
    )
    endpoint_pass = all(penetration.get(key) == 0 for key in zero_fields)
    runtime_checked = penetration.get("runtime_domain_status") == "checked"
    obstacles = wall.get("obstacles", [])
    pass_gate = bool(
        bounds_pass and closed == EXPECTED_CLOSED_FACES
        and opened == EXPECTED_OPEN_FACES and obstacles == []
        and endpoint_pass and runtime_checked
    )
    return pass_gate, {
        "structural_pass": pass_gate,
        "geometry_binding": {
            "container_interior": observed,
            "closed_faces": list(closed),
            "open_faces": list(opened),
            "obstacles": obstacles,
            "registered_bounds_pass": bounds_pass,
            "opening_semantics": "top_open; bottom and four side faces closed",
        },
        "penetration": {
            key: penetration.get(key) for key in zero_fields
        } | {"runtime_domain_status": penetration.get("runtime_domain_status")},
        "source_wall_spec": "legacy_audit.wall_spec",
    }


def build_receipt(row: Mapping[str, Any], *, root: Path,
                  manifest_path: Path, manifest_sha256: str,
                  generator_sha256: str) -> dict[str, Any]:
    """Validate one row and return its deterministic structural receipt."""
    case_id = row.get("case_id")
    _require(isinstance(case_id, str) and case_id, "F3 case has no case_id")
    _require(row.get("family") == EXPECTED_FAMILY, f"unexpected family for {case_id}")
    provenance = row.get("provenance")
    _require(isinstance(provenance, Mapping), f"{case_id} has no provenance")
    manifest_base = manifest_path.parent
    audit, audit_ref = _bound_json(
        provenance.get("audit", {}), root=root, base=manifest_base,
        role=f"{case_id} legacy audit")
    prepared, prepared_ref = _bound_json(
        provenance.get("prepared", {}), root=root, base=manifest_base,
        role=f"{case_id} prepared record")

    _require(audit.get("case_id") == case_id, f"{case_id} audit identity mismatch")
    _require(prepared.get("id") == case_id, f"{case_id} prepared identity mismatch")
    _require(prepared.get("family") == EXPECTED_FAMILY, f"{case_id} prepared family mismatch")
    _require(row.get("sha256") == audit.get("hdf5_sha256"), f"{case_id} trajectory hash mismatch")
    _require(row.get("hdf5") == audit.get("hdf5"), f"{case_id} trajectory path mismatch")
    _require(row.get("scope_id") == prepared.get("recipe_id"),
             f"{case_id} scope/recipe identity mismatch")
    _require(prepared.get("recipe_id") == row.get("known_inputs_ref", {})
             .get("numerics", {}).get("recipe_id"), f"{case_id} recipe mismatch")

    expected_particles = prepared.get("gencase", {}).get("fluid_particles")
    _require(isinstance(expected_particles, int) and expected_particles > 0,
             f"{case_id} prepared particle count is missing")
    _require(audit.get("audit_status") == "pass_diagnostic",
             f"{case_id} legacy audit is not pass_diagnostic")
    _require(audit.get("issues") == [] and audit.get("unknowns") == [],
             f"{case_id} legacy audit has issues or unknowns")

    particle_axis_pass = (
        audit.get("particle_axis_count") == expected_particles
        and audit.get("initial_valid_particles") == expected_particles
        and audit.get("final_valid_particles") == expected_particles
        and audit.get("frames", 0) >= 2
    )
    _require(particle_axis_pass, f"{case_id} particle-axis gate failed")
    particle_axis = {
        "structural_pass": True,
        "axis": "particle_id",
        "particle_axis_count": audit.get("particle_axis_count"),
        "expected_fluid_particles": expected_particles,
        "initial_valid_particles": audit.get("initial_valid_particles"),
        "final_valid_particles": audit.get("final_valid_particles"),
        "frame_count": audit.get("frames"),
    }

    finite_fields = (
        "initial_fluid_mass_kg", "final_valid_mass_kg", "minimum_frame_mass_kg",
        "maximum_frame_mass_kg", "final_valid_mass_fraction_of_initial",
        "density_min_kg_m3", "density_max_kg_m3", "max_speed_m_s",
        "mean_displacement_m", "max_displacement_m",
    )
    finite_pass = (
        audit.get("finite_bad_value_rows") == 0
        and audit.get("finite_bad_first_frame") is None
        and all(_finite(audit.get(key)) for key in finite_fields)
    )
    _require(finite_pass, f"{case_id} finite-value gate failed")
    finite_values = {
        "structural_pass": True,
        "finite_bad_value_rows": audit.get("finite_bad_value_rows"),
        "finite_bad_first_frame": audit.get("finite_bad_first_frame"),
        "checked_fields": list(finite_fields),
        "observed": {key: audit.get(key) for key in finite_fields},
    }

    lifecycle_fields = (
        "identities_introduced_after_initial", "initial_identities_missing_at_final",
        "identities_reappeared_after_gap", "excluded_particles_from_solver_log",
    )
    lifecycle_pass = (
        all(audit.get(key) == 0 for key in lifecycle_fields)
        and audit.get("identity_retention_first_to_last") == 1.0
    )
    _require(lifecycle_pass, f"{case_id} lifecycle gate failed")
    lifecycle = {
        "structural_pass": True,
        "identity_retention_first_to_last": audit.get("identity_retention_first_to_last"),
        "zero_violation_fields": list(lifecycle_fields),
        "observed": {key: audit.get(key) for key in lifecycle_fields},
    }

    semantics = row.get("semantics")
    _require(isinstance(semantics, Mapping), f"{case_id} manifest semantics are missing")
    coordinate_frame = prepared.get("coordinate_frame")
    units_pass = semantics.get("units") == "SI" and isinstance(coordinate_frame, str) and bool(coordinate_frame)
    _require(units_pass, f"{case_id} unit/coordinate contract failed")
    units = {
        "structural_pass": True,
        "declared_system": semantics.get("units"),
        "coordinate_frame": coordinate_frame,
        "contract": UNIT_CONTRACT,
        "evidence": "manifest semantics.units=SI plus prepared coordinate_frame and SI-named source fields",
    }

    wall_pass, wall_opening = _wall_pass(audit, prepared)
    _require(wall_pass, f"{case_id} wall/opening gate failed")

    return {
        "schema": RECEIPT_SCHEMA,
        "receipt_version": GENERATOR_VERSION,
        "receipt_id": f"{GENERATOR_VERSION}:{case_id}",
        "case_id": case_id,
        "family": EXPECTED_FAMILY,
        "scope_id": row.get("scope_id"),
        "recipe_id": prepared.get("recipe_id"),
        "physical_case_id": row.get("physical_case_id"),
        "lineage_group_id": row.get("lineage_group_id"),
        "manifest_binding": {
            "path": _relative(manifest_path, root),
            "sha256": manifest_sha256,
        },
        "generator_binding": {
            "path": "scripts/core_f3_structural_audit_receipts.py",
            "sha256": generator_sha256,
        },
        "source_evidence": {
            "audit": audit_ref,
            "prepared": prepared_ref,
            "trajectory": {
                "path": row.get("hdf5"),
                "sha256": row.get("sha256"),
                "bytes": row.get("bytes"),
                "opened_by_generator": False,
            },
        },
        "checks": {
            "particle_axis": particle_axis,
            "finite_values": finite_values,
            "lifecycle": lifecycle,
            "units": units,
            "wall_opening": wall_opening,
        },
        "structural_pass": True,
        "qualification_claim": "none; structural serialization/integrity receipt only",
        "formal_release": False,
    }


def write_immutable(path: Path, payload: Mapping[str, Any]) -> None:
    path = path.resolve()
    if path.exists():
        raise FileExistsError(f"immutable evidence output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(payload, indent=2, sort_keys=True,
                                  ensure_ascii=False, allow_nan=False) + "\n",
                       encoding="utf-8")
    partial.replace(path)


def generate(manifest: str | Path, *, data_root: str | Path,
             output_dir: str | Path, adapter_output: str | Path) -> dict[str, Any]:
    root = Path(data_root).expanduser().resolve()
    manifest_path = _resolve(manifest, root=root)
    if not manifest_path.is_file():
        raise FileNotFoundError(manifest_path)
    payload = _load_json(manifest_path)
    rows = payload.get("cases")
    if payload.get("schema") != "core.dataset.v2" or not isinstance(rows, list):
        raise ValueError("F3 structural receipt generation requires core.dataset.v2 cases")
    if payload.get("formal_release") is not False:
        raise ValueError("structural receipt generator only accepts an unreleased source manifest")
    if len(rows) != EXPECTED_CASE_COUNT:
        raise ValueError(f"expected {EXPECTED_CASE_COUNT} F3 cases, observed {len(rows)}")
    manifest_sha256 = digest(manifest_path)
    generator_path = Path(__file__).resolve()
    generator_sha256 = digest(generator_path)
    output_root = _resolve(output_dir, root=root)
    output_root.relative_to(root)
    adapter_path = _resolve(adapter_output, root=root)
    adapter_path.relative_to(root)
    if adapter_path.parent not in {output_root, output_root.parent}:
        raise ValueError("adapter output must be beside or in the receipt output directory")
    output_root.mkdir(parents=True, exist_ok=True)

    receipt_refs: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: str(item.get("case_id", ""))):
        receipt = build_receipt(
            row, root=root, manifest_path=manifest_path,
            manifest_sha256=manifest_sha256, generator_sha256=generator_sha256)
        path = output_root / f"{receipt['case_id']}.json"
        write_immutable(path, receipt)
        receipt_refs.append({
            "case_id": receipt["case_id"],
            "path": _relative(path, root),
            "sha256": digest(path),
            "structural_pass": receipt["structural_pass"],
        })

    adapter = {
        "schema": ADAPTER_SCHEMA,
        "receipt_version": GENERATOR_VERSION,
        "manifest_path": _relative(manifest_path, root),
        "manifest_sha256": manifest_sha256,
        "generator_path": _relative(generator_path, root),
        "generator_sha256": generator_sha256,
        "case_count": len(receipt_refs),
        "structural_pass": all(item["structural_pass"] for item in receipt_refs),
        "cases": receipt_refs,
        "formal_release": False,
        "qualification_claim": "none; structural serialization/integrity receipts only",
    }
    write_immutable(adapter_path, adapter)
    return {
        "schema": ADAPTER_SCHEMA,
        "manifest_sha256": manifest_sha256,
        "case_count": len(receipt_refs),
        "structural_pass": adapter["structural_pass"],
        "output_dir": _relative(output_root, root),
        "adapter": _relative(adapter_path, root),
        "adapter_sha256": digest(adapter_path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--adapter-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    result = generate(args.manifest, data_root=args.data_root,
                      output_dir=args.output_dir, adapter_output=args.adapter_output)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
