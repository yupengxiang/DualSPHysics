#!/usr/bin/env python3
"""Bind F2 commensurate cases to separate physical and numerical hashes.

This is a read-only handoff utility.  It intentionally lives beside the
fallback generator so the already-consumed GenCase requests keep the exact
generator bytes they were launched with.  It reads immutable XML, metadata,
and motion files and writes only a semantic-hash sidecar.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
import xml.etree.ElementTree as ET


SCRIPT_PATH = Path(__file__).resolve()
FALLBACK_PATH = SCRIPT_PATH.with_name("f2_commensurate_fallback.py")


def _load_fallback() -> Any:
    spec = importlib.util.spec_from_file_location("f2_commensurate_fallback_for_hashes", FALLBACK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import fallback constants from {FALLBACK_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FALLBACK = _load_fallback()
FAMILY_ID = "F2"
RHO0 = float(FALLBACK.RHO0)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _sorted_attributes(node: ET.Element | None) -> dict[str, str]:
    return {} if node is None else {key: node.attrib[key] for key in sorted(node.attrib)}


def _source_physical_payload(source_text: str) -> dict[str, Any]:
    """Keep physical geometry/control and exclude execution numerics."""
    root = ET.fromstring(source_text)
    constants = root.find(".//constantsdef")
    physical_constant_tags = {"gravity", "rhop0", "gamma"}
    physical_constants = {
        node.tag: _sorted_attributes(node)
        for node in (list(constants) if constants is not None else [])
        if node.tag in physical_constant_tags
    }
    mainlist = root.find(".//geometry/commands/mainlist")
    boundary_boxes: list[dict[str, Any]] = []
    active_mk: str | None = None
    if mainlist is not None:
        for node in mainlist:
            if node.tag == "setmkbound":
                active_mk = node.attrib.get("mk")
                continue
            if node.tag == "setmkfluid":
                active_mk = None
                continue
            if node.tag != "drawbox" or active_mk is None:
                continue
            point = node.find("./point")
            size = node.find("./size")
            if point is None or size is None:
                continue
            boundary_boxes.append(
                {
                    "mk": active_mk,
                    "boxfill": node.findtext("./boxfill", default="").strip(),
                    "point": _sorted_attributes(point),
                    "size": _sorted_attributes(size),
                    "layers": _sorted_attributes(node.find("./layers")),
                }
            )
    motion = root.find(".//motion")
    motion_payload: dict[str, Any] = {}
    if motion is not None:
        motion_payload["objreal"] = _sorted_attributes(motion.find("./objreal"))
        motion_payload["begin"] = _sorted_attributes(motion.find("./objreal/begin"))
        rotation = motion.find("./objreal/mvrotfile")
        if rotation is not None:
            motion_payload["rotation"] = {
                "attributes": _sorted_attributes(rotation),
                "file": "{MOTION_FILE}",
                "axis_p1": _sorted_attributes(rotation.find("./axisp1")),
                "axis_p2": _sorted_attributes(rotation.find("./axisp2")),
            }
    return {
        "physical_constants": physical_constants,
        "finite_boundary_boxes": boundary_boxes,
        "motion_definition": motion_payload,
    }


def _solver_recipe_payload(definition_text: str) -> dict[str, Any]:
    root = ET.fromstring(definition_text)
    definition = root.find(".//geometry/definition")
    parameters = root.find(".//execution/parameters")
    values: dict[str, Any] = {}
    if parameters is not None:
        for node in parameters:
            if node.tag == "parameter":
                values[node.attrib.get("key", "")] = _sorted_attributes(node)
            elif node.tag == "simulationdomain":
                values["simulationdomain"] = {
                    "posmin": _sorted_attributes(node.find("./posmin")),
                    "posmax": _sorted_attributes(node.find("./posmax")),
                }
    return {"definition_dp": _sorted_attributes(definition), "execution_parameters": values}


def _payload_hash(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def semantic_hashes(metadata: Mapping[str, Any]) -> dict[str, Any]:
    source_xml = Path(str(metadata["source_definition"]["path"])).resolve()
    definition_xml = Path(str(metadata["definition"]["path"])).resolve()
    source_text = source_xml.read_text(encoding="utf-8")
    definition_text = definition_xml.read_text(encoding="utf-8")
    geometry = metadata["geometry"]
    physical_payload = {
        "schema": "ds-data-02.f2.physical-condition.v1",
        "background": metadata["background"],
        "source_geometry_and_motion": _source_physical_payload(source_text),
        "source_motion_sha256": metadata["source_motion"]["sha256"],
        "continuous_fluid": {
            "low_m": geometry["continuous_fluid_low_m"],
            "size_m": geometry["continuous_fluid_size_m"],
            "volume_m3": geometry["continuous_fluid_volume_m3"],
            "source_axis": geometry["fluid_source_axis"],
            "source_band_count": geometry["source_band_count"],
            "source_band_width_m": geometry["source_band_width_m"],
            "source_band_bounds_y_m": geometry["source_band_bounds_y_m"],
            "rho0_kg_m3": RHO0,
        },
        "prescribed_control": metadata["motion_and_solver"],
    }
    numerical_payload = {
        "schema": "ds-data-02.f2.numerical-recipe.v1",
        "background": metadata["background"],
        "resolution": metadata["resolution"],
        "dp_m": metadata["dp_m"],
        "population_mode": metadata["population_construction"]["mode"],
        "numerical_grid_origin_m": geometry["numerical_grid_origin_m"],
        "solver_recipe": _solver_recipe_payload(definition_text),
        "expected_population": metadata["expected_population"],
    }
    return {
        "physical_condition_hash_scope": "background; finite boundary geometry; prescribed motion definition and motion bytes; continuous fluid domain, source bands, density, gravity/material constants, and event/control metadata; excludes dp, pointmin/grid phase, population mode, execution parameters, and save cadence",
        "physical_condition_payload": physical_payload,
        "physical_condition_hash": _payload_hash(physical_payload),
        "numerical_recipe_hash_scope": "resolution/dp; numerical pointmin grid phase; population construction mode; GenCase/solver execution parameters; expected lattice population",
        "numerical_recipe_payload": numerical_payload,
        "numerical_recipe_hash": _payload_hash(numerical_payload),
    }


def semantic_hash_manifest(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    cases: list[dict[str, Any]] = []
    for entry in manifest["cases"]:
        metadata_path = Path(entry["metadata"]["path"]).resolve()
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        hashes = semantic_hashes(metadata)
        cases.append(
            {
                "case_id": entry["case_id"],
                "physical_case_id": entry["physical_case_id"],
                "background": entry["background"],
                "resolution": entry["resolution"],
                "definition": {"path": entry["definition"]["path"], "sha256": entry["definition"]["sha256"]},
                "metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
                "motion": metadata["motion"],
                "source_definition": metadata["source_definition"],
                "source_motion": metadata["source_motion"],
                "physical_condition_hash": hashes["physical_condition_hash"],
                "physical_condition_hash_scope": hashes["physical_condition_hash_scope"],
                "numerical_recipe_hash": hashes["numerical_recipe_hash"],
                "numerical_recipe_hash_scope": hashes["numerical_recipe_hash_scope"],
                "physical_condition_payload": hashes["physical_condition_payload"],
                "numerical_recipe_payload": hashes["numerical_recipe_payload"],
            }
        )
    result = {
        "schema": "ds-data-02.f2.commensurate-semantic-hashes.v1",
        "family_id": FAMILY_ID,
        "scope_id": manifest["scope_id"],
        "status": "evidence_binding_sidecar_only",
        "qualification_claim": "none",
        "production_claim": "none",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "semantic_script": {"path": str(SCRIPT_PATH), "sha256": sha256(SCRIPT_PATH)},
        "physical_hash_semantics": "same physical condition requires identical physical_condition_hash; dp/grid phase/population mode/solver execution parameters belong only to numerical_recipe_hash",
        "cases": cases,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    write_json(output_path.resolve(), result)
    result["output"] = {"path": str(output_path.resolve()), "sha256": sha256(output_path.resolve())}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = semantic_hash_manifest(args.manifest, args.output)
    print(json.dumps({"status": "written", **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
