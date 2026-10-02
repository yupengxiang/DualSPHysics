#!/usr/bin/env python3
"""Register deferred full-state conversion requests for RV4EQ DP005.

The two RV4-equivalent DP005 solver jobs are owned by the primary process.
This module only reads their immutable handoff inputs and writes additive
owner metadata plus deferred CPU conversion requests.  It never runs a
solver, converter, PartVTK, or label job.  The request deliberately keeps
the terminal solver receipt, RunPARTs.csv, and sampled Part files deferred;
the root process must bind their actual hashes after a terminal receipt.

The conversion command uses the official full-frame ``PartVTK_linux64``
binary for validation.  ``PartVTKOut_linux64`` is excluded because it is the
native exclusion accounting tool, not a full-frame decoder.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable, Mapping
import xml.etree.ElementTree as ET


F2_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = F2_ROOT.parents[4]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_DATA_ROOT = DATA_ROOT / "families/F2"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB_ROOT = INTEGRATION_ROOT / "lagrangian-fluid-lab"
RUNTIME_V2 = LAB_ROOT / "scripts/ds_data02_runtime_v2.py"
DIRECT_CONVERTER = LAB_ROOT / "scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
HANDOFF_MANIFEST = F2_ROOT / "rv4_equivalent_dp005/solver_handoff/solver_handoff_manifest.json"
OUTPUT_ROOT = F2_ROOT / "rv4_equivalent_dp005/postprocess_handoff_v2"
SCOPE_ID = "F2_SCOPE_RV4_EQUIVALENT_DP005_PRECHECK_20261002"
SCHEMA = "ds-data-02.f2.rv4eq-dp005.postprocess-handoff.v2"
FRAMES_EXPECTED = 401
MACRO_SAVE_S = 0.01
BYTES_PER_PARTICLE_FRAME = 64
STORAGE_MARGIN = 1.40
REFERENCE_TOTAL_PARTICLES = 28_647
REFERENCE_FRAMES = 4_001
REFERENCE_SECONDS = 191.78278693789616
REFERENCE_TRAJECTORY = F2_DATA_ROOT / "F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001" / "conversion-f2h10v2_center_v1_coarse_rv4d1_baseline_save001-fullstate-v5-002/trajectory.h5"
MACRO_BUDGET = 0.01
EVENT_SAVE_HALF_WIDTH_BUDGET_S = 0.0007336390799938275


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def require(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def require_dir(path: Path, label: str) -> Path:
    path = Path(path).resolve()
    if not path.is_dir():
        raise FileNotFoundError(f"{label} missing: {path}")
    return path


def load_json(path: Path, label: str) -> dict[str, Any]:
    path = require(path, label)
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def file_bindings(paths: Iterable[Path]) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in paths:
        path = require(path, "static conversion input")
        result[str(path)] = sha256(path)
    return dict(sorted(result.items()))


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        str(node.attrib["key"]): str(node.attrib["value"])
        for node in root.findall(".//execution/parameters/parameter")
        if node.attrib.get("key") is not None
    }


def manifest_entry(manifest: Mapping[str, Any], case_id: str) -> Mapping[str, Any]:
    for entry in manifest.get("requests", []):
        if str(entry.get("case_id")) == case_id:
            return entry
    raise KeyError(f"solver handoff manifest has no request for {case_id}")


def source_request(case_id: str) -> tuple[Path, dict[str, Any], Mapping[str, Any]]:
    request_path = F2_ROOT / "rv4_equivalent_dp005/solver_handoff/requests" / f"{case_id}_request.json"
    request = load_json(request_path, f"solver handoff request {case_id}")
    manifest = load_json(HANDOFF_MANIFEST, "solver handoff manifest")
    return request_path, request, manifest_entry(manifest, case_id)


def static_inputs(case_id: str, request_path: Path, request: Mapping[str, Any], entry: Mapping[str, Any], owner: Path, prefix: Path, metadata: Path, source_report: Path, rv4_xml: Path, rv4_motion: Path) -> list[Path]:
    native_dir = require_dir(Path(str(entry["native_inputs"]["directory"])), "DP005 native input directory")
    provenance = require(native_dir / "solver-input-provenance.json", "DP005 solver provenance")
    gencase_receipt = require(Path(str(request["gencase_receipt"])), "DP005 GenCase receipt")
    input_files = [
        F2_ROOT / "f2_rv4eq_dp005_postprocess_handoff_v2.py",
        RUNTIME_V2,
        DIRECT_CONVERTER,
        DECODER,
        PARTVTK,
        F2_ROOT / "quality_contract.json",
        F2_ROOT / "event_definitions.json",
        F2_ROOT / "integration_save_plan.json",
        F2_ROOT / "case_registry.jsonl",
        F2_ROOT / "definitions/reference_matrix.json",
        F2_ROOT.parents[1] / "GOAL_ZH.md",
        HANDOFF_MANIFEST,
        request_path,
        metadata,
        Path(str(entry["domain_audit"]["path"])),
        gencase_receipt,
        prefix.with_suffix(".xml"),
        prefix.with_suffix(".bi4"),
        prefix.parent / f"{prefix.name}_motion.dat",
        provenance,
        source_report,
        rv4_xml,
        rv4_motion,
        owner,
    ]
    # Keep the original DP005 definition and motion tied to the owner record
    # even though the solver prefix is the immutable .01-solver copy.
    definition = next(
        Path(path) for path in request["input_files"]
        if "/rv4_equivalent_dp005/definitions/" in str(path) and str(path).endswith("_Def.xml")
    )
    definition_motion = next(
        Path(path) for path in request["input_files"]
        if "/rv4_equivalent_dp005/definitions/" in str(path) and str(path).endswith("_motion.dat")
    )
    input_files.extend([definition, definition_motion])
    return list(dict.fromkeys(input_files))


def owner_metadata(case_id: str, request: Mapping[str, Any], metadata_path: Path, macro_xml: Path, macro_motion: Path, source_report_path: Path, output: Path) -> Path:
    metadata = load_json(metadata_path, f"DP005 metadata {case_id}")
    source_report = load_json(source_report_path, f"RV4 source conversion report {case_id}")
    physical = source_report["hash_scopes"]["physical_condition"]
    physical_hash = str(source_report["hash_scopes"]["physical_condition_sha256"])
    expected_hash = str(metadata["rv4_binding"]["physical_condition_hash"])
    if physical_hash != expected_hash:
        raise ValueError(f"RV4 physical binding mismatch for {case_id}: report={physical_hash} metadata={expected_hash}")
    if canonical_hash(physical) != physical_hash:
        raise ValueError(f"RV4 physical condition is not canonical for {case_id}")
    owner = {
        "schema": "ds-data-02.f2.rv4eq-dp005-owner.v2",
        "case_id": case_id,
        "source_case_id": str(metadata["case_id"]),
        "family_id": "F2",
        "background": str(metadata["background"]),
        "mechanism_id": str(metadata["mechanism_id"]),
        "physical_case_id": str(metadata["physical_case_id"]),
        "scope_id": SCOPE_ID,
        "resolution": "dp005",
        "definition": {"path": str(macro_xml), "sha256": sha256(macro_xml)},
        "motion": {"path": str(macro_motion), "sha256": sha256(macro_motion)},
        "solver_parameters": xml_parameters(macro_xml),
        "physical_binding": physical,
        "physical_condition_hash_declared": physical_hash,
        "physical_binding_sha256": physical_hash,
        "numerical_recipe_hash_declared": str(request["numerical_recipe_hash"]),
        "numerical_view": {
            "variant_case_id": case_id,
            "variant": "RV4EQ_DP005_BASELINE_SAVE001",
            "physical_condition_hash": physical_hash,
            "source_metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
            "source_conversion_report": {"path": str(source_report_path), "sha256": sha256(source_report_path)},
            "scope": "same RV4 physical mother; dp=.005 solver; .01 macro save; numerical recipe is separate",
        },
        "source_provenance": {
            "dp005_metadata": {"path": str(metadata_path), "sha256": sha256(metadata_path)},
            "rv4_physical_conversion_report": {"path": str(source_report_path), "sha256": sha256(source_report_path)},
            "physical_binding_origin": "RV4 conversion report hash_scopes.physical_condition; stale label-owner declaration is not used",
        },
        "mass_reference": {
            "continuous_mass_kg": 24.575999999999997,
            "native_header_is_authority": True,
            "strict_relative_budget_fraction": 1e-12,
            "adapter_float32_error_is_separate": True,
        },
        "qualification_claim": "none; conversion evidence only",
        "production_claim": "none",
    }
    path = output / "owner_metadata" / f"{case_id}.owner.v2.json"
    write_json(path, owner)
    return path


def estimate_resources(total_particles: int) -> dict[str, Any]:
    lower_bound = FRAMES_EXPECTED * total_particles * BYTES_PER_PARTICLE_FRAME
    storage = math.ceil(lower_bound * STORAGE_MARGIN)
    predicted = REFERENCE_SECONDS * total_particles * FRAMES_EXPECTED / (REFERENCE_TOTAL_PARTICLES * REFERENCE_FRAMES)
    return {
        "actual_total_particles_from_gencase": total_particles,
        "frames_expected": FRAMES_EXPECTED,
        "bytes_per_particle_frame_lower_bound": BYTES_PER_PARTICLE_FRAME,
        "lower_bound_bytes": lower_bound,
        "storage_margin_fraction": STORAGE_MARGIN - 1.0,
        "estimated_storage_bytes": storage,
        "formula": "ceil(actual_total_particles * 401 * 64 * 1.40)",
        "wall_reference": {
            "case_id": "F2H10V2_CENTER_V1_COARSE_RV4D1_BASELINE_SAVE001",
            "total_particles": REFERENCE_TOTAL_PARTICLES,
            "frames": REFERENCE_FRAMES,
            "elapsed_seconds": REFERENCE_SECONDS,
            "trajectory_path": str(REFERENCE_TRAJECTORY),
        },
        "predicted_wall_seconds": predicted,
        "requested_wall_seconds": 1800,
        "wall_margin_multiplier": 1800.0 / predicted,
    }


def deferred_request(case_id: str, request_path: Path, request: Mapping[str, Any], entry: Mapping[str, Any], owner: Path, static: list[Path], macro_prefix: Path, metadata_path: Path, source_report: Path, rv4_xml: Path, rv4_motion: Path, output_root: Path) -> Path:
    gencase_receipt = require(Path(str(request["gencase_receipt"])), "DP005 GenCase receipt")
    gencase = load_json(gencase_receipt, "DP005 GenCase receipt")
    # The request's expected population is fluid-only.  Conversion storage
    # must use the completed GenCase total (fluid plus all finite boundary and
    # moving nodes), which is the top-level receipt value used by the solver
    # handoff manifest.
    total_particles = int(gencase["total_particles"])
    if total_particles != int(entry["actual_total_particles"]):
        raise ValueError(f"manifest/GenCase particle count mismatch for {case_id}")
    native_dir = require_dir(Path(str(entry["native_inputs"]["directory"])), "DP005 native input directory")
    macro_xml = require(macro_prefix.with_suffix(".xml"), "DP005 macro XML")
    macro_bi4 = require(macro_prefix.with_suffix(".bi4"), "DP005 macro BI4")
    macro_motion = require(macro_prefix.parent / f"{macro_prefix.name}_motion.dat", "DP005 macro motion")
    attempt_id = f"conversion-{case_id.lower()}-fullstate-v2-001"
    case_root = F2_DATA_ROOT / case_id
    solver_attempt = case_root / str(request["attempt_id"])
    solver_output = solver_attempt / "solver_output"
    data_root = solver_output / "data"
    conversion_root = case_root / attempt_id
    output_h5 = conversion_root / "trajectory.h5"
    report = conversion_root / "conversion-report.json"
    receipt = conversion_root / "execution-receipt.json"
    deferred = [
        solver_attempt / "execution-receipt.json",
        solver_output / "Run.out",
        solver_output / "Run.csv",
        solver_output / "RunPARTs.csv",
        data_root / "Part_0000.bi4",
        data_root / "Part_0200.bi4",
        data_root / "Part_0400.bi4",
    ]
    resources = estimate_resources(total_particles)
    physical_hash = str(request["physical_condition_hash"])
    static_hashes = file_bindings(static)
    command = [
        str(WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"),
        str(DIRECT_CONVERTER),
        "--data-root", str(data_root),
        "--generated-xml", str(macro_xml),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", str(solver_output / "Run.out"),
        "--solver-receipt", str(solver_attempt / "execution-receipt.json"),
        "--gencase-receipt", str(gencase_receipt),
        "--owner-metadata", str(owner),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
    ]
    request_value: dict[str, Any] = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": command,
        "cwd": str(LAB_ROOT),
        "worktree_root": str(WORKTREE_ROOT),
        "raw_output_root": str(F2_DATA_ROOT),
        "max_wall_seconds": 1800,
        "cpu_threads": 4,
        "estimated_storage_bytes": resources["estimated_storage_bytes"],
        "resource_estimate": resources,
        "input_files": [str(path) for path in static],
        "input_sha256": static_hashes,
        "deferred_input_files": [str(path) for path in deferred],
        "deferred_binding_policy": "wait for root-owned solver receipt status completed/code0; then hash the receipt, Run.out, Run.csv, full-window RunPARTs.csv, and first/middle/last Part_*.bi4 before scheduling; do not bind partial output",
        "source_bindings": {
            "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256(gencase_receipt)},
            "generated_xml": {"path": str(macro_xml), "sha256": sha256(macro_xml)},
            "copied_bi4": {"path": str(macro_bi4), "sha256": sha256(macro_bi4)},
            "copied_motion": {"path": str(macro_motion), "sha256": sha256(macro_motion)},
            "rv4_source_xml": {"path": str(rv4_xml), "sha256": sha256(rv4_xml)},
            "rv4_source_motion": {"path": str(rv4_motion), "sha256": sha256(rv4_motion)},
            "owner_metadata": {"path": str(owner), "sha256": sha256(owner)},
            "physical_condition_hash": physical_hash,
            "numerical_recipe_hash": str(request["numerical_recipe_hash"]),
        },
        "gencase_receipt": str(gencase_receipt),
        "gencase_receipt_sha256": sha256(gencase_receipt),
        "generated_xml": {"path": str(macro_xml), "sha256": sha256(macro_xml)},
        "owner_metadata": {"path": str(owner), "sha256": sha256(owner)},
        "actual_source": {
            "solver_receipt": str(solver_attempt / "execution-receipt.json"),
            "data_root": str(data_root),
            "expected_native_frame_count": FRAMES_EXPECTED,
            "expected_total_particles": total_particles,
            "event_window_s": [0.0, 4.0],
            "native_exclusion_accounting": "RunPARTs full-window sum; unknown native fate is separate and cannot be called physical spill",
        },
        "physical_case_id": str(request["physical_condition_hash"]),
        "physical_condition_hash": physical_hash,
        "physical_geometry_control_hash": physical_hash,
        "numerical_recipe_hash": str(request["numerical_recipe_hash"]),
        "scope_id": SCOPE_ID,
        "registry_role": "new_RV4_equivalent_finer_reference_outside_original_48_registry",
        "new_independent_physical_case_count": 0,
        "event_timing_status": "not_qualified; .01 s macro save is spatial evidence only and cannot meet the frozen .0007336390799938275 s save half-width by itself",
        "quality_thresholds": {
            "continuous_initial_mass_kg": 24.576,
            "strict_native_vs_continuous_relative_budget_fraction": 1e-12,
            "macro_relative_error_threshold": MACRO_BUDGET,
            "event_time_absolute_budget_s": 0.0036681953999691376,
            "save_half_width_budget_s": EVENT_SAVE_HALF_WIDTH_BUDGET_S,
            "timing_qualification_requires_independent_finer_save": True,
            "unknown_mass_remains_in_initial_denominator": True,
        },
        "native_exclusion_gate": {
            "status": "not_observed_until_solver_terminal",
            "semantics": "sum all RunPARTs NpOut/NPOutPos/etc over the complete timeline; preserve typed IDs, first-missing frame/time, Motive, and location; no physical-spill inference",
        },
        "expected_outputs": {"receipt": str(receipt), "trajectory": str(output_h5), "conversion_report": str(report)},
        "conversion_launch": {"allowed": False, "reason": "F4 conversion slots are occupied; root schedules after terminal solver receipt and review"},
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "status": "deferred_until_root_solver_terminal_and_conversion_slot",
        "qualification_claim": "none",
        "production_claim": "none",
        "request_note": "Additive owner/fullstate request only. Official PartVTK_linux64 is full-frame validation; PartVTKOut is not used. Root must bind terminal native hashes before scheduling.",
    }
    path = Path(output_root).resolve() / "conversion_requests" / f"{case_id}_conversion_request_v2.json"
    write_json(path, request_value)
    return path


def build(output_root: Path = OUTPUT_ROOT) -> dict[str, Any]:
    output_root = Path(output_root).resolve()
    manifest = load_json(HANDOFF_MANIFEST, "solver handoff manifest")
    result_requests: list[Path] = []
    owner_paths: list[Path] = []
    for background in ("CENTER", "OFFSET"):
        case_id = f"F2_RV4EQ_DP005_{background}_V1_BASELINE_SAVE001"
        request_path, request, entry = source_request(case_id)
        native_prefix = Path(str(entry["native_inputs"]["prefix"])).resolve()
        macro_xml = require(native_prefix.with_suffix(".xml"), f"{case_id} macro XML")
        macro_motion = require(native_prefix.parent / f"{native_prefix.name}_motion.dat", f"{case_id} macro motion")
        metadata_path = next(
            Path(path) for path in request["input_files"]
            if "/rv4_equivalent_dp005/definitions/" in str(path) and str(path).endswith(".metadata.json")
        )
        metadata = load_json(metadata_path, f"{case_id} metadata")
        source_report = require(Path(str(metadata["rv4_binding"]["conversion_report"]["path"])), f"{case_id} RV4 conversion report")
        rv4_xml = require(Path(str(metadata["rv4_binding"]["staged_xml"]["path"])), f"{case_id} RV4 XML")
        rv4_motion = require(Path(str(metadata["rv4_binding"]["staged_motion"]["path"])), f"{case_id} RV4 motion")
        owner = owner_metadata(case_id, request, metadata_path, macro_xml, macro_motion, source_report, output_root)
        static = static_inputs(case_id, request_path, request, entry, owner, native_prefix, metadata_path, source_report, rv4_xml, rv4_motion)
        # static_inputs is evaluated after owner creation and therefore binds
        # the exact owner bytes that the conversion will consume.
        result_requests.append(deferred_request(case_id, request_path, request, entry, owner, static, native_prefix, metadata_path, source_report, rv4_xml, rv4_motion, output_root))
        owner_paths.append(owner)
    handoff = {
        "schema": SCHEMA,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scope_id": SCOPE_ID,
        "source_solver_handoff_manifest": {"path": str(HANDOFF_MANIFEST), "sha256": sha256(HANDOFF_MANIFEST)},
        "requests": [{"path": str(path), "sha256": sha256(path)} for path in result_requests],
        "owner_metadata": [{"path": str(path), "sha256": sha256(path)} for path in owner_paths],
        "official_partvtk": {"path": str(PARTVTK), "sha256": sha256(PARTVTK), "role": "full-frame validation"},
        "solver_launch": False,
        "conversion_launch": False,
        "deferred_until": "root terminal solver receipt and shared conversion slot",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    manifest_path = output_root / "postprocess_handoff_manifest_v2.json"
    write_json(manifest_path, handoff)
    handoff["manifest"] = {"path": str(manifest_path), "sha256": sha256(manifest_path)}
    return handoff


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=OUTPUT_ROOT)
    args = parser.parse_args()
    print(json.dumps(build(args.output_root), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
