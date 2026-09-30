#!/usr/bin/env python3
"""Create explicit F4 physical/numerical binding sidecars.

The frozen F4 owner metadata mixes continuum semantics with lattice counts and
save controls.  This module separates those scopes before direct BI4
conversion.  It only reads the owner metadata, generated XML, and completed
receipts; it never regenerates a case or edits an external source.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any, Mapping

from scripts.ds_data02_direct_convert import (
    PHYSICAL_BINDING_SCHEMA,
    _validate_physical_binding,
    canonical_hash,
    parse_particle_blocks,
    sha256_file,
)


SCHEMA = "ds02.f4.direct-binding.v1"
_PHYSICAL_CONTROLS = (
    "step_algorithm",
    "kernel",
    "viscosity",
    "density_dt",
    "density_dt_value",
    "boundary",
)
_PHYSICAL_EVENT = (
    "time_start_s",
    "time_end_s",
    "sequence",
    "expected_first_contact_range_s",
    "right_censor_policy",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _copy_region(region: Mapping[str, Any], *, label: str | None = None) -> dict[str, Any]:
    if "low_m" in region:
        low = list(region["low_m"])
        size = list(region["size_m"])
    elif "low" in region:
        low = list(region["low"])
        size = list(region["size"])
    else:
        raise ValueError(f"continuous region lacks low/size: {region}")
    result: dict[str, Any] = {"low_m": low, "size_m": size}
    if "mkfluid" in region:
        result["mkfluid"] = int(region["mkfluid"])
    if label is not None:
        result["label"] = label
    return result


def physical_binding(owner: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only explicit continuous physics from a frozen F4 owner file."""
    controls = owner.get("controls")
    if not isinstance(controls, Mapping):
        raise ValueError("F4 owner controls are required")
    event_window = owner.get("event_window")
    if not isinstance(event_window, Mapping):
        raise ValueError("F4 owner event_window is required")
    geometry = owner.get("geometry")
    if not isinstance(geometry, Mapping):
        raise ValueError("F4 owner geometry is required")
    source_labels = owner.get("initial_state", {}).get("source_labels", {})
    continuous_geometry: dict[str, Any] = {}
    for name, region in geometry.items():
        if name == "native_boxes":
            # These fields encode dp, lattice counts, and first-particle
            # offsets.  They are numeric evidence, never physical semantics.
            continue
        if not isinstance(region, Mapping):
            raise ValueError(f"F4 geometry region is not an object: {name}")
        label = None
        if "mkfluid" in region:
            label = source_labels.get(f"mkfluid:{int(region['mkfluid'])}")
        continuous_geometry[name] = _copy_region(region, label=label)
    continuum = owner.get("continuum_geometry")
    if isinstance(continuum, Mapping) and isinstance(continuum.get("tank"), Mapping):
        continuous_geometry["tank"] = _copy_region(continuum["tank"])

    initial = owner.get("initial_state")
    if not isinstance(initial, Mapping):
        raise ValueError("F4 owner initial_state is required")
    source_regions = {
        name: copy.deepcopy(region)
        for name, region in continuous_geometry.items()
        if "mkfluid" in region
    }
    binding: dict[str, Any] = {
        "schema": PHYSICAL_BINDING_SCHEMA,
        "family_id": owner["family_id"],
        "physical_case_id": owner["physical_case_id"],
        "lineage_group_id": owner.get("lineage_group_id"),
        "paired_background_id": owner.get("paired_background_id"),
        "mechanism_id": owner["mechanism_id"],
        "geometry_family_id": owner["geometry_family_id"],
        "control_family_id": owner["control_family_id"],
        "geometry": continuous_geometry,
        "initial_state": {
            "source_regions": source_regions,
            "velocities_m_per_s": copy.deepcopy(initial["velocities_m_per_s"]),
            "source_labels": copy.deepcopy(initial["source_labels"]),
            # The physical contract uses continuum mass.  Any native lattice
            # count error is retained by the sidecar as initialization
            # evidence and never hidden in this cross-resolution hash.
            "initial_mass_by_source_kg": copy.deepcopy(initial["continuum_mass_by_source_kg"]),
            "continuum_mass_by_source_kg": copy.deepcopy(initial["continuum_mass_by_source_kg"]),
            "initial_mass_total_kg": sum(initial["continuum_mass_by_source_kg"].values()),
            "mass_policy": owner["initialization_rule"]["mass_policy"],
        },
        "controls": {key: copy.deepcopy(controls[key]) for key in _PHYSICAL_CONTROLS},
        "gravity_m_s2": copy.deepcopy(owner["gravity_m_s2"]),
        "density_kg_m3": owner["density_kg_m3"],
        "parameters": copy.deepcopy(owner["parameters"]),
        "event_window": {key: copy.deepcopy(event_window[key]) for key in _PHYSICAL_EVENT},
        "open_inlet": bool(owner["open_inlet"]),
        "periodic_boundary": bool(owner["periodic_boundary"]),
        "mass_policy": owner["initialization_rule"]["mass_policy"],
    }
    _validate_physical_binding(binding)
    return binding


def _provenance(path: Path) -> dict[str, Any]:
    return {"path": str(path), "sha256": sha256_file(path)}


def make_sidecar(entry: Mapping[str, Any]) -> dict[str, Any]:
    owner_path = Path(entry["owner_metadata_source"])
    owner = _load(owner_path)
    binding = physical_binding(owner)
    source_paths = {
        key: Path(entry[key])
        for key in (
            "generated_xml",
            "definition_xml",
            "gencase_receipt",
            "solver_receipt",
            "solver_log",
        )
    }
    for key, path in source_paths.items():
        if not path.is_file():
            raise FileNotFoundError(f"F4 source binding {key} does not exist: {path}")
    blocks = parse_particle_blocks(source_paths["generated_xml"])
    fluid_mk_map = {
        str(int(block["mkfluid"])): int(block["mk"])
        for block in blocks["blocks"]
        if block["type"] == 3 and block["mkfluid"] is not None
    }
    if not fluid_mk_map:
        raise ValueError(f"generated XML has no typed multiple-fluid mapping: {source_paths['generated_xml']}")
    sidecar = {
        "schema": SCHEMA,
        "family_id": owner["family_id"],
        "physical_case_id": owner["physical_case_id"],
        "mechanism_id": owner["mechanism_id"],
        "resolution": entry["resolution"],
        "dp_m": float(entry["dp_m"]),
        "time_variant": entry["time_variant"],
        "physical_binding": binding,
        "source_binding": {
            "owner_metadata_source": _provenance(owner_path),
            **{key: _provenance(path) for key, path in source_paths.items()},
            "binding_statement": (
                "physical_binding is copied from explicit continuum geometry, initial state, "
                "physical controls, and event-time semantics; generated XML and native lattice "
                "fields remain numerical provenance"
            ),
        },
        "initialization_evidence": {
            "native_initial_mass_by_source_kg": copy.deepcopy(owner["initial_state"]["initial_mass_by_source_kg"]),
            "continuum_mass_by_source_kg": copy.deepcopy(owner["initial_state"]["continuum_mass_by_source_kg"]),
            "native_initial_mass_total_kg": owner["initial_state"]["initial_mass_total_kg"],
            "continuum_initial_mass_total_kg": sum(owner["initial_state"]["continuum_mass_by_source_kg"].values()),
            "semantics": "native lattice initialization error is reported separately; no mass normalization",
        },
        "physical_binding_sha256": canonical_hash(binding),
        "typed_identity_binding": {
            "fluid_mkfluid_to_native_mk": fluid_mk_map,
            "source": "generated XML typed fluid ranges; converter preserves native mk and (Zone,Idp)",
        },
        "qualification_status": "conversion_and_observation_evidence_only",
        "q_i_status": "not_granted",
        "q_n_status": "not_assessed",
    }
    return sidecar


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    entries = json.loads(args.manifest.read_text(encoding="utf-8"))
    if not isinstance(entries, list):
        raise SystemExit("manifest must be a JSON array")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for entry in entries:
        sidecar = make_sidecar(entry)
        output = args.output_dir / str(entry["binding_id"])
        output.write_text(json.dumps(sidecar, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"binding_id": entry["binding_id"], "output": str(output), "physical_binding_sha256": sidecar["physical_binding_sha256"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
