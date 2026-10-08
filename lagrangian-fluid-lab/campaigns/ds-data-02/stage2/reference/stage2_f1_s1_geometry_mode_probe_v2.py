#!/usr/bin/env python3
"""Prepare source-bound F1-S1 dp=.009 geometry-mode GenCase probes.

The existing F1-S1 dp=.009 preflight has a useful particle-sample mass
(40.351608 kg, +0.377% against the frozen 40.2 kg owner), but its observed
cell envelope does not yet close the owner geometry contract.  This forward
worker creates two *separate* bounded GenCase requests.  Each keeps the
CURRENT drawboxes, controls, source XML, and dp=.009 spacing, while replacing
the source ``setshapemode`` list with one official token: ``actual`` or
``bound``.  The token semantics are deliberately a runtime question; neither
candidate is called a matched grid until its generated XML/VTK is audited.

``--build`` only creates immutable Def/request/queue files.  It never invokes
GenCase.  A parent may submit either request through the shared Stage2 v8 CPU
guard.  The request is GenCase-only, has no solver or H5 read, and carries no
scientific qualification.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any


SCHEMA = "ds02.stage2.f1-s1-geometry-mode-probe.v2"
REQUEST_SCHEMA = "ds02.request.v1"
BINDING_SCHEMA = "ds02.stage2.f1-s1-geometry-mode-probe-binding.v2"

REPO = Path(__file__).resolve().parents[5]
REFERENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")

GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python").resolve()
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
V6_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
V2_RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"

CURRENT_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/"
    "F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027/"
    "prepared/F1_FALLBACK_ECC_COARSE_Def.xml"
)
CURRENT_XML = CURRENT_DEF.with_name("F1_FALLBACK_ECC_COARSE.xml")
CURRENT_GENCASE_RECEIPT = CURRENT_DEF.parents[1] / "execution-receipt.json"
OWNER_FILE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
OWNER_BINDING = OWNER_FILE.with_name("ecc-physical-binding.json")
GEOMETRY_AUDIT = REFERENCE / "stage2_f1_s1_geometry_semantics_audit_v2.json"
QUALITY = REFERENCE / "stage2_reference_quality_cost_v2.json"
DOC_TEMPLATE = REPO / "doc/xml_format/GenCase_CaseTemplate.xml"

INPUT_ROOT = REFERENCE / "stage2_f1_s1_geometry_mode_probe_inputs_v2/F1_S1/dp0p009000"
REQUEST_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-geometry-mode-probe-v2"
QUEUE_PATH = REFERENCE / "stage2_f1_s1_geometry_mode_probe_v2.json"

MODE_SPECS: dict[str, dict[str, str]] = {
    "actual": {
        "case_id": "F1_S1_SPATIAL_MODE_ACTUAL_DP0p009000",
        "attempt_id": "f1-s1-spatial-mode-actual-dp0p009000-v2-root-001",
        "purpose": "probe official actual-shape lattice/cell-envelope semantics at a meaningful dp=.009 rung",
    },
    "bound": {
        "case_id": "F1_S1_SPATIAL_MODE_BOUND_DP0p009000",
        "attempt_id": "f1-s1-spatial-mode-bound-dp0p009000-v2-root-001",
        "purpose": "probe official bound-shape lattice/cell-envelope semantics at a meaningful dp=.009 rung",
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular_file(path, label)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(path),
    }


def atomic_bytes(path: Path, data: bytes) -> None:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def normalized_definition(text: str) -> str:
    """Normalize only the two intentional probe edits."""
    text = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r'\1<DP>\2', text, count=1)
    text = re.sub(r"(<setshapemode>).*?(</setshapemode>)", r"\1<MODE>\2", text, count=1, flags=re.S)
    return text


def derive_definition(mode: str) -> dict[str, Any]:
    if mode not in MODE_SPECS:
        raise ValueError(f"unsupported mode: {mode}")
    source = regular_file(CURRENT_DEF, "CURRENT F1-S1 Def")
    source_text = source.read_text(encoding="utf-8")
    definitions = list(re.finditer(r"<definition\b[^>]*>", source_text))
    if len(definitions) != 1:
        raise ValueError(f"expected one definition tag, found {len(definitions)}")
    definition_tag = definitions[0].group(0)
    dp_matches = list(re.finditer(r'dp="([^"]+)"', definition_tag))
    if len(dp_matches) != 1 or dp_matches[0].group(1) != "0.01":
        raise ValueError("CURRENT F1-S1 definition dp is not exactly 0.01")
    dp_start, dp_end = dp_matches[0].span(1)
    new_definition_tag = definition_tag[:dp_start] + "0.009" + definition_tag[dp_end:]
    derived = source_text[:definitions[0].start()] + new_definition_tag + source_text[definitions[0].end():]
    mode_matches = list(re.finditer(r"<setshapemode>.*?</setshapemode>", derived, flags=re.S))
    if len(mode_matches) != 1:
        raise ValueError(f"expected one setshapemode command, found {len(mode_matches)}")
    old_mode = mode_matches[0].group(0)
    if not re.fullmatch(r"<setshapemode>\s*dp\s*\|\s*actual\s*\|\s*bound\s*</setshapemode>", old_mode):
        raise ValueError(f"unexpected CURRENT setshapemode command: {old_mode!r}")
    replacement = f"<setshapemode>{mode}</setshapemode>"
    derived = derived[:mode_matches[0].start()] + replacement + derived[mode_matches[0].end():]
    if derived == source_text:
        raise ValueError("candidate Def did not change")
    if normalized_definition(source_text) != normalized_definition(derived):
        raise ValueError("candidate differs outside dp and setshapemode normalization")

    target = INPUT_ROOT / f"setshapemode_{mode}" / f"F1_S1_DP009_MODE_{mode.upper()}_Def.xml"
    if target.exists():
        if target.read_text(encoding="utf-8") != derived:
            raise ValueError(f"existing candidate differs: {target}")
    else:
        atomic_bytes(target, derived.encode("utf-8"))
    return {
        "mode": mode,
        "source_def": record(source, "CURRENT F1-S1 Def"),
        "candidate_def": record(target, f"F1-S1 {mode} candidate Def"),
        "source_definition_normalized_sha256": hashlib.sha256(normalized_definition(source_text).encode("utf-8")).hexdigest(),
        "candidate_definition_normalized_sha256": hashlib.sha256(normalized_definition(derived).encode("utf-8")).hexdigest(),
        "dp_m": {"source": 0.01, "candidate": 0.009, "separation_fraction": 0.10},
        "setshapemode": {"source": "dp | actual | bound", "candidate": mode},
        "intentional_changes_only": ["definition dp: 0.010 m -> 0.009 m", f"setshapemode token list -> {mode}"],
        "continuous_drawboxes_and_controls_normalized_equal": True,
        "mode_semantics": "UNKNOWN_UNTIL_PARENT_GUARDED_GENC CASE_OUTPUT_AUDIT",
        "official_token_evidence": str(DOC_TEMPLATE.resolve()),
    }


def unique_files(paths: list[Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if str(path) not in seen:
            regular_file(path, "request input")
            seen.add(str(path))
            result.append(path)
    return result


def request_for(mode: str, definition_meta: dict[str, Any]) -> tuple[dict[str, Any], Path]:
    spec = MODE_SPECS[mode]
    candidate_def = Path(definition_meta["candidate_def"]["path"])
    output_root = DATA_ROOT / "families/F1" / spec["case_id"] / spec["attempt_id"]
    request_path = REQUEST_ROOT / f"f1_s1_dp009_setshapemode_{mode}_v2.json"
    if output_root.exists():
        raise FileExistsError(f"attempt output already exists: {output_root}")
    if request_path.exists():
        raise FileExistsError(f"request already exists: {request_path}")

    owner_file = regular_file(OWNER_FILE, "F1-S1 owner")
    owner_binding = regular_file(OWNER_BINDING, "F1-S1 canonical owner binding")
    input_paths = unique_files([
        Path(__file__), candidate_def, CURRENT_DEF, CURRENT_XML, CURRENT_GENCASE_RECEIPT,
        owner_file, owner_binding, GEOMETRY_AUDIT, QUALITY, DOC_TEMPLATE,
        GENCASE, PYTHON, RUNNER, STRICT, RUNTIME, V6_RUNTIME, V2_RUNTIME,
    ])
    input_hashes = {str(path): sha256(path) for path in input_paths}

    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "family_id": "F1",
        "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "case_id": spec["case_id"],
        "attempt_id": spec["attempt_id"],
        "qualification_stage": "stage2_f1_s1_geometry_mode_probe_gencase_pending_parent_v8_dispatch",
        "command": [str(GENCASE), str(candidate_def.with_suffix("")), "{attempt_root}/generated", "-save:all"],
        "cwd": str(candidate_def.parent),
        "worktree_root": str(REPO),
        "input_files": [str(path) for path in input_paths],
        "input_hashes": input_hashes,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_native_read_bytes": 0,
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "v6_runtime": str(V6_RUNTIME),
            "v2_runtime": str(V2_RUNTIME),
            "parent_cpu_guard_required": True,
            "gpu": "none",
            "gpu_uuid": "none",
            "solver_launch": "forbidden",
            "new_solver": False,
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "launch_disabled": False,
            "parent_v8_review_required": True,
        },
        "output": {
            "path": "{attempt_root}/generated",
            "refuse_overwrite": True,
            "expected_outputs": ["generated.xml", "generated.out", "generated_Fluid.vtk", "execution-receipt.json"],
        },
        "output_protection": {
            "attempt_root_must_not_exist_at_dispatch": True,
            "refuse_overwrite": True,
        },
        "source_binding": {
            "schema": BINDING_SCHEMA,
            "sentinel_id": "F1-S1",
            "family_id": "F1",
            "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
            "owner_authority": {
                "owner_file": record(owner_file, "F1-S1 owner"),
                "canonical_binding_file": record(owner_binding, "F1-S1 canonical owner binding"),
                "continuous_geometry": {
                    "low_m": [0.0, 0.0, 0.0],
                    "size_m": [0.4, 0.67, 0.15],
                    "upper_m": [0.4, 0.67, 0.15],
                    "volume_m3": 0.0402,
                    "density_kg_m3": 1000.0,
                    "mass_kg": 40.2,
                    "mkfluid_relative": 0,
                    "authority": "CURRENT336 owner/physical-binding metadata; not inferred from particle count",
                },
            },
            "current_source": {
                "definition": record(CURRENT_DEF, "CURRENT F1-S1 Def"),
                "generated_xml": record(CURRENT_XML, "CURRENT F1-S1 generated XML"),
                "gencase_receipt": record(CURRENT_GENCASE_RECEIPT, "CURRENT F1-S1 GenCase receipt"),
                "drawbox_and_control_semantics": "unchanged source bytes after dp/setshapemode normalization",
            },
            "candidate": {
                "definition": definition_meta,
                "dp_m": 0.009,
                "spacing_separation_fraction_from_original": 0.10,
                "mode_probe": mode,
                "purpose": spec["purpose"],
                "no_drawbox_change": True,
                "no_posthoc_box_adjustment": True,
                "no_particle_mass_rescale": True,
            },
            "frozen_mass_gate": {
                "owner_continuum_mass_kg": 40.2,
                "sample_mass_target_kg": 40.2,
                "target_role": "owner continuous mass is authoritative; particle sum is a discrete initialization diagnostic",
                "target_pct": 1.0,
                "hard_upper_pct": 2.0,
                "threshold_widening": False,
                "mass_rescale": False,
                "status": "UNKNOWN_UNTIL_TERMINAL_XML_AND_GEOMETRY_AUDIT",
            },
            "prior_dp009_evidence": {
                "existing_preflight_path": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F1/F1_S1_SPATIAL_REPAIR_DP0p009000/f1-s1-spatial-repair-dp0p009000-v1-root-001",
                "sample_mass_kg": 40.351608,
                "sample_mass_error_pct": 0.377134328,
                "cell_envelope_owner_match": False,
                "status": "HISTORICAL_DIAGNOSTIC_ONLY; NOT_REUSED_OR_OVERWRITTEN",
            },
        },
        "deferred_scientific_followup": {
            "cfd": "NOT_CREATED; requires parent audit of generated XML/VTK, owner envelope, sample mass, controls, and source receipt",
            "qualification": "No QI/QN/QE credit is granted by this GenCase probe",
        },
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "cfd_invoked": False,
        "hdf5_read": False,
        "bi4_read": False,
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(request_path, request)
    return request, request_path


def build() -> dict[str, Any]:
    definitions = {mode: derive_definition(mode) for mode in MODE_SPECS}
    requests: list[dict[str, Any]] = []
    request_paths: list[str] = []
    entries: list[dict[str, Any]] = []
    for mode, definition_meta in definitions.items():
        request, request_path = request_for(mode, definition_meta)
        requests.append(request)
        request_paths.append(str(request_path.resolve()))
        entries.append({
            "mode": mode,
            "case_id": request["case_id"],
            "attempt_id": request["attempt_id"],
            "request": str(request_path.resolve()),
            "candidate_def": definition_meta["candidate_def"],
            "dp_m": 0.009,
            "status": "READY_PARENT_V8_DISPATCH",
            "mass_status": "UNKNOWN_UNTIL_TERMINAL_XML_AND_GEOMETRY_AUDIT",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        })
    queue = {
        "schema": SCHEMA,
        "status": "READY_PARENT_V8_DISPATCH",
        "sentinel_id": "F1-S1",
        "family_id": "F1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1",
        "purpose": "two bounded dp=.009 setshapemode probes to resolve owner-envelope semantics before any CFD",
        "owner_contract": {
            "low_m": [0.0, 0.0, 0.0],
            "size_m": [0.4, 0.67, 0.15],
            "mass_kg": 40.2,
            "density_kg_m3": 1000.0,
            "mass_target_pct": 1.0,
            "hard_upper_pct": 2.0,
            "no_mass_rescale": True,
        },
        "historical_dp009": {
            "sample_mass_kg": 40.351608,
            "sample_mass_error_pct": 0.377134328,
            "cell_envelope_matches_owner": False,
            "credit": "diagnostic only; existing input/output untouched",
        },
        "candidate_count": len(entries),
        "candidates": entries,
        "requests": request_paths,
        "guard": {
            "runner": str(RUNNER),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "parent_cpu_guard_required": True,
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "max_wall_seconds_each": 600,
            "estimated_storage_bytes_each": 64 * 1024 * 1024,
        },
        "followup": "After terminal output audit only, parent may prepare a separate source-bound CFD request; this queue grants no CFD or scientific qualification.",
    }
    atomic_json(QUEUE_PATH, queue)
    return queue


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="write immutable candidates, requests, and queue")
    args = parser.parse_args()
    if not args.build:
        parser.error("use --build; this module never launches GenCase")
    print(json.dumps(build(), ensure_ascii=False, indent=2))
