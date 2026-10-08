#!/usr/bin/env python3
"""Prepare one bounded, spacing-separated F1-S1 GenCase repair probe.

The candidate changes only the exact CURRENT F1-S1 definition ``dp`` from
0.010 m to 0.009 m (10% spacing separation).  Continuous drawboxes, fluid
region, controls, and all source geometry bytes are copied unchanged.  This is
a launch-disabled CPU request for parent review; it is not a CFD request and
does not rescale particle mass or widen the mass gate.  F1-S2's existing
0.017/0.0165/0.016 interval queue is referenced rather than duplicated.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.mass-geometry-repair-queue.v1"
REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
V6_RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v6.py"
V6_STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v6.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
GEOMETRY_AUDIT = REFERENCE / "stage2_continuum_geometry_mass_audit_v1.json"
CURRENT_DEF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE_Def.xml")
CURRENT_XML = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/prepared/F1_FALLBACK_ECC_COARSE.xml")
OUTPUT_ROOT = REFERENCE / "stage2_mass_geometry_repair_inputs_v1/F1_S1/dp0p009000"
CANDIDATE_DEF = OUTPUT_ROOT / "F1_S1_SPATIAL_REPAIR_DP0p009000_Def.xml"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-mass-geometry-repair-v1"
REQUEST_PATH = REQUEST_ROOT / "f1_s1_spatial_repair_dp0p009000.json"
QUEUE_PATH = REFERENCE / "stage2_mass_geometry_repair_queue_v1.json"
DP_RE = re.compile(r'dp="[^"]+"')


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    try:
        temporary.write_bytes(data)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def derive_definition() -> dict[str, Any]:
    source = CURRENT_DEF.resolve()
    target = CANDIDATE_DEF.resolve()
    source_text = source.read_text(encoding="utf-8")
    matches = list(re.finditer(r"<definition\b[^>]*>", source_text))
    if len(matches) != 1:
        raise ValueError(f"expected exactly one definition tag in {source}: {len(matches)}")
    tag = matches[0].group(0)
    dp_match = DP_RE.search(tag)
    if dp_match is None:
        raise ValueError(f"definition has no dp attribute: {source}")
    replacement_tag = tag[:dp_match.start()] + 'dp="0.009"' + tag[dp_match.end():]
    derived_text = source_text[:matches[0].start()] + replacement_tag + source_text[matches[0].end():]
    if derived_text == source_text:
        raise ValueError("candidate definition did not change")
    normalized_source = DP_RE.sub('dp="<DP>"', source_text)
    normalized_derived = DP_RE.sub('dp="<DP>"', derived_text)
    if normalized_source != normalized_derived:
        raise ValueError("candidate changes bytes outside definition dp")
    if target.exists():
        if target.read_text(encoding="utf-8") != derived_text:
            raise ValueError(f"existing candidate differs: {target}")
    else:
        atomic_bytes(target, derived_text.encode("utf-8"))
    return {
        "source_def": record(source),
        "candidate_def": record(target),
        "source_normalized_sha256": hashlib.sha256(normalized_source.encode()).hexdigest(),
        "candidate_normalized_sha256": hashlib.sha256(normalized_derived.encode()).hexdigest(),
        "continuous_geometry_and_control_bytes_equal_after_dp_normalization": True,
        "intentional_change": "definition dp only: 0.010 m -> 0.009 m",
    }


def build_request(definition_meta: dict[str, Any]) -> dict[str, Any]:
    if REQUEST_PATH.exists():
        raise FileExistsError(REQUEST_PATH)
    static = [Path(__file__).resolve(), CANDIDATE_DEF, CURRENT_DEF, CURRENT_XML,
              QUALITY, GEOMETRY_AUDIT, GENCASE, V6_RUNNER, V6_STRICT, V6_RUNTIME,
              V2_RUNTIME, PYTHON.resolve()]
    input_files: list[Path] = []
    seen: set[str] = set()
    for path in static:
        path = path.resolve()
        if not path.is_file():
            raise FileNotFoundError(path)
        if str(path) not in seen:
            seen.add(str(path)); input_files.append(path)
    case_id = "F1_S1_SPATIAL_REPAIR_DP0p009000"
    attempt_id = "f1-s1-spatial-repair-dp0p009000-v1-parent-001"
    output_root = DATA_ROOT / "families/F1" / case_id / attempt_id
    if output_root.exists():
        raise FileExistsError(output_root)
    request: dict[str, Any] = {
        "schema": "ds02.request.v1",
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": case_id,
        "attempt_id": attempt_id,
        "qualification_stage": "stage2_continuum_geometry_mass_repair_gencase_preflight_pending_parent_v6_dispatch",
        "command": [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "cwd": str(REPO),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in input_files],
        "input_hashes": {str(path): sha256(path) for path in input_files},
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(V6_RUNNER),
            "strict_guard": str(V6_STRICT),
            "runtime": str(V6_RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "launch_disabled": True,
            "parent_v6_review_required": True,
        },
        "output": {"path": "{attempt_root}/generated", "refuse_overwrite": True},
        "output_protection": {"attempt_root_must_not_exist_at_dispatch": True, "refuse_overwrite": True},
        "source_binding": {
            "schema": "ds02.stage2.mass-geometry-repair-binding.v1",
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "continuous_geometry_source_xml": record(CURRENT_XML),
            "current_definition": record(CURRENT_DEF),
            "candidate_definition": record(CANDIDATE_DEF),
            "definition_semantics": definition_meta,
            "baseline_spacing_dp_m": 0.010,
            "candidate_spacing_dp_m": 0.009,
            "spacing_separation_fraction": 0.10,
            "geometry_control_domain": "same source definition after dp-only normalization; no fill/domain/motion edits",
            "continuous_target_reference": {
                "declared_geometry_mass_kg": 36.036,
                "reference_particle_sample_mass_target_kg": 40.2,
                "mass_units": "kg",
                "target_role": "declared geometry mass is a source target candidate; sample mass is initialization diagnostic only",
                "semantic_status": "UNKNOWN_OVERLAP_VOID_CELL_CENTER_CROP",
            },
            "prior_grid_evidence": {
                "original_dp_m": 0.010,
                "original_sample_mass_error_pct": 0.0,
                "coarse_dp_m": 0.0125,
                "coarse_sample_mass_error_pct": 0.7463,
                "fine_dp_m": 0.008,
                "fine_sample_mass_error_pct": 1.6358,
                "reason_for_probe": "bounded phase/count information between an existing pass coarse grid and marginal fine grid; no mass rescale",
            },
            "mass_gate": {
                "whole_initial_sample_diagnostic_target_pct": 1.0,
                "explicit_exception_upper_pct": 2.0,
                "above_upper": "HARD_FAIL",
                "particle_mass_rescale": False,
                "threshold_widening": False,
                "status": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML",
            },
        },
        "deferred_scientific_followup": "none; any CFD requires separate source-bound review after terminal XML and material audit",
        "launch_disabled": True,
        "execution_allowed": False,
        "solver_started": False,
        "hdf5_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    return request


def build() -> dict[str, Any]:
    definition_meta = derive_definition()
    request = build_request(definition_meta)
    queue = {
        "schema": SCHEMA,
        "status": "PREPARED_LAUNCH_DISABLED",
        "candidate_count": 1,
        "candidate_requests": [str(REQUEST_PATH.resolve())],
        "candidates": [{
            "sentinel_id": "F1-S1", "case_id": request["case_id"], "dp_m": 0.009,
            "spacing_separation_fraction": 0.10, "status": "PREPARED_LAUNCH_DISABLED",
            "mass_status": "UNKNOWN_UNTIL_TERMINAL_GENERATED_XML",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }],
        "existing_f1_s2_interval_queue": str((REFERENCE / "stage2_infogain_gencase_queue_v2.json").resolve()),
        "scope": "one F1-S1 spacing-separated repair probe; F1-S2 existing interval queue is referenced, not duplicated",
        "guard": {"runner": str(V6_RUNNER), "strict_guard": str(V6_STRICT), "runtime": str(V6_RUNTIME), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden"},
        "mass_gate": {"whole_initial_target_pct": 1.0, "explicit_exception_upper_pct": 2.0, "particle_mass_rescale": False, "threshold_widening": False},
    }
    atomic_json(QUEUE_PATH, queue)
    return queue


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
