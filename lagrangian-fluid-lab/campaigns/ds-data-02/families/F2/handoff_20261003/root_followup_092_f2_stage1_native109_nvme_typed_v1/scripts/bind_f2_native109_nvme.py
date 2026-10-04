#!/usr/bin/env python3
"""Bind F2 native109 provenance without decoding BI4, CSV, or H5 arrays."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HANDOFF = Path(__file__).resolve().parents[1]
CASES = {
    "P01": "F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010",
    "P03": "F2_STAGE1_OFFSET_P03_DP010_SPATIAL_REFERENCE_SAVE010",
}
PHYSICAL_REQUIRED = {
    "family_id", "physical_case_id", "mechanism_id", "geometry_family_id",
    "control_family_id", "geometry", "initial_state", "controls",
    "gravity_m_s2", "density_kg_m3", "parameters", "event_window",
}
PHYSICAL_ALLOWED = PHYSICAL_REQUIRED | {
    "schema", "lineage_group_id", "paired_background_id", "open_inlet",
    "periodic_boundary", "mass_policy",
}
CONTROL_ALLOWED = {
    "step_algorithm", "kernel", "viscosity", "density_dt",
    "density_dt_value", "boundary",
}
GEOMETRY_ALLOWED = {"low_m", "size_m", "mkfluid", "label"}
INITIAL_ALLOWED = {
    "source_regions", "velocities_m_per_s", "source_labels",
    "initial_mass_by_source_kg", "continuum_mass_by_source_kg",
    "initial_mass_total_kg", "mass_policy",
}
EVENT_ALLOWED = {
    "time_start_s", "time_end_s", "sequence",
    "expected_first_contact_range_s", "right_censor_policy",
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value

def canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)

def validate_physical_binding(binding: dict[str, Any]) -> None:
    require(binding.get("schema") == "ds-data-02.physical-binding.v1",
            "physical_binding schema mismatch")
    require(PHYSICAL_REQUIRED <= set(binding),
            f"physical_binding missing {sorted(PHYSICAL_REQUIRED - set(binding))}")
    require(not (set(binding) - PHYSICAL_ALLOWED),
            f"physical_binding unknown fields {sorted(set(binding) - PHYSICAL_ALLOWED)}")
    controls = binding["controls"]
    require(isinstance(controls, dict) and not (set(controls) - CONTROL_ALLOWED),
            "physical_binding.controls is outside the direct-converter allowlist")
    for name, region in binding["geometry"].items():
        require(isinstance(region, dict), f"geometry region {name} is not an object")
        require(not (set(region) - GEOMETRY_ALLOWED),
                f"geometry region {name} has unknown fields")
        require("low_m" in region and "size_m" in region,
                f"geometry region {name} lacks low_m/size_m")
    initial = binding["initial_state"]
    require(isinstance(initial, dict) and not (set(initial) - INITIAL_ALLOWED),
            "physical_binding.initial_state is outside the allowlist")
    require("particle_counts" not in initial and "native_boxes" not in initial,
            "native resolution fields entered physical binding")
    event = binding["event_window"]
    require(isinstance(event, dict) and not (set(event) - EVENT_ALLOWED),
            "physical_binding.event_window is outside the allowlist")

def evidence_paths(owner: dict[str, Any]) -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    def add(section: dict[str, Any], key: str) -> None:
        item = section.get(key)
        if isinstance(item, dict) and item.get("path") and item.get("sha256"):
            out.append((Path(item["path"]), item["sha256"]))
    for key in ("receipt", "generated_xml", "generated_bi4",
                "generated_motion", "prepared_input_report"):
        add(owner["gencase_provenance"], key)
    for key in ("receipt", "report"):
        add(owner["initial_qa_provenance"], key)
        add(owner["initial_qa_provenance"]["qa106_failed_predecessor"], key)
    for key in ("receipt", "solver_log", "partinfo"):
        add(owner["native_solver_provenance"], key)
    return out

def validate_case(label: str) -> dict[str, Any]:
    case = CASES[label]
    owner_path = HANDOFF / "owners" / f"{case}.owner.json"
    request_path = HANDOFF / "requests" / f"{case}.nvme-conversion-disabled.json"
    owner = load(owner_path)
    request = load(request_path)
    require(owner.get("source_only") is True and owner.get("launch_allowed") is False,
            f"{label}: owner is enabled")
    require(request.get("source_only") is True and request.get("launch_allowed") is False,
            f"{label}: request is enabled")
    require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "conversion",
            f"{label}: request is not typed CPU conversion")
    validate_physical_binding(owner["physical_binding"])
    physical_hash = canonical_hash(owner["physical_binding"])
    require(physical_hash == owner["canonical_physical_binding_sha256"],
            f"{label}: owner canonical physical hash mismatch")
    require(request["canonical_physical_binding_sha256"] == physical_hash
            and request["physical_binding_sha256"] == physical_hash,
            f"{label}: request canonical hash mismatch")
    require(owner["physical_condition_sha256"] != physical_hash,
            f"{label}: source and canonical hashes unexpectedly equal")
    gen = load(Path(owner["gencase_provenance"]["receipt"]["path"]))
    require(gen.get("status") == "completed" and gen.get("returncode") == 0,
            f"{label}: GenCase receipt not completed")
    require((gen.get("total_particles"), gen.get("fluid_particles"),
             gen.get("solver_dimension_from_gencase")) == (418104, 21114, 3),
            f"{label}: GenCase counts/dimension changed")
    qa = load(Path(owner["initial_qa_provenance"]["report"]["path"]))
    require(qa.get("status") == "pass", f"{label}: QA107 is not pass")
    checks = qa.get("checks", {})
    require(checks and all(value is True for value in checks.values()),
            f"{label}: QA107 named check failed")
    csv = qa["csv_summary"]
    require(csv["row_count"] == 418104 and csv["fluid_type3_count"] == 21114,
            f"{label}: QA counts changed")
    require(21.113 < csv["unscaled_fluid_mass_sum_kg"] < 21.115,
            f"{label}: native fluid mass changed")
    integrity = qa["additional_actual_native_integrity"]
    require(integrity["fluid_particles"] == 21114
            and integrity["representation_precision"]["native_geometry_or_mass_changed"] is False,
            f"{label}: native integrity/mass policy changed")
    solver = load(Path(owner["native_solver_provenance"]["receipt"]["path"]))
    require(solver.get("status") == "completed" and solver.get("returncode") == 0,
            f"{label}: solver109 receipt not completed")
    sr = solver["request"]
    command = sr["command"]
    require("-tmax:4.0" in command and "-tout:0.01" in command,
            f"{label}: solver window changed")
    require(not any("mdbc" in value.lower() for value in command),
            f"{label}: mdbc was added")
    require(sr["expected_output"]["frame_count"] == 401,
            f"{label}: solver frame count changed")
    require(owner["native_solver_provenance"]["motion_cwd_is_prepared_input_dir"] is True,
            f"{label}: solver cwd is not prepared directory")
    require(request["expected_native"]["partvtk_validation_frames"] == [0, 200, 400],
            f"{label}: PartVTK validation frame contract changed")
    require("/tmp/ds02-nvme-conversion" in request["command"]
            and str(24 * 1024**3) in request["command"],
            f"{label}: NVME staging/peak command changed")
    require(request["conversion_contract"]["free_space_floor_bytes"] == 100 * 1024**3
            and request["conversion_contract"]["concurrency"] == 2,
            f"{label}: NVME floor/concurrency changed")
    require(str(Path(__file__).resolve()) in request["input_files"],
            f"{label}: helper is not digest-bound")
    for raw in request["input_files"]:
        path = Path(raw)
        require(path.is_file(), f"{label}: request input missing: {path}")
        require(request["input_sha256"].get(str(path)) == sha(path),
                f"{label}: stale request hash: {path}")
    for path, expected in evidence_paths(owner):
        require(path.is_file(), f"{label}: owner evidence missing: {path}")
        require(sha(path) == expected, f"{label}: owner evidence hash mismatch: {path}")
    return {
        "case_id": case,
        "owner": str(owner_path),
        "request": str(request_path),
        "canonical_physical_binding_sha256": physical_hash,
        "source_physical_condition_sha256": owner["physical_condition_sha256"],
        "actual_counts": {"total": 418104, "fluid": 21114, "fixed": 372840,
                          "moving": 24150, "dimension": 3},
        "actual_initial_qa": {
            "status": "pass", "named_check_count": len(checks),
            "native_fluid_mass_kg": integrity["fluid_native_mass_kg"],
            "mass_rescaled": False,
        },
        "actual_solver": {
            "status": solver["status"], "frames": 401, "time_max_s": 4.0,
            "save_interval_s": 0.01, "mdbc_added": False,
        },
        "partvtk_validation_frames": [0, 200, 400],
        "source_vs_canonical_hash_equal": False,
        "nvme_request_disabled": True,
        "array_decode_performed": False,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["P01", "P03", "all"], default="all")
    parser.add_argument("--mode", choices=["static", "bind"], default="static")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    labels = ["P01", "P03"] if args.case == "all" else [args.case]
    results = [validate_case(label) for label in labels]
    value = {
        "schema": "ds02.f2.stage1.native109-nvme-helper-result.v1",
        "mode": args.mode, "source_only": True, "launch_allowed": False,
        "array_policy": "JSON/XML metadata and byte hashes only; no BI4/CSV/H5 arrays opened",
        "cases": results,
    }
    if args.mode == "bind":
        out_dir = args.output_dir or HANDOFF / "metadata" / "bound"
        out_dir.mkdir(parents=True, exist_ok=True)
        for result in results:
            out = out_dir / f"{result['case_id']}.actual-native-binding.json"
            out.write_text(json.dumps({
                "schema": "ds02.f2.stage1.native109-actual-binding.v1",
                "bound_status": "actual_native_provenance_bound; nvme_conversion_pending",
                "source_only": True, "launch_allowed": False,
                "conversion_output_status": "pending; no H5 conversion evidence bound",
                "conversion_report": None, "trajectory_h5": None,
                "array_policy": value["array_policy"], **result,
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
