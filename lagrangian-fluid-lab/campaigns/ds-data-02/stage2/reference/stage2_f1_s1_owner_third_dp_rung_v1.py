#!/usr/bin/env python3
"""Prepare one source-bound F1-S1 third-spacing GenCase preflight.

The frozen F1-S1 owner/control source is the completed dp=.010 Def.  The
candidate changes only its definition ``dp`` to .008 m, preserving the
owner drawboxes, pointref, setshapemode command, obstacle, and all source
control text byte-for-byte.  This gives a real third spacing rung relative
to the completed dp=.010 and dp=.009 products while leaving the continuous
owner mass (40.2 kg) and the no-rescale gates explicit.  This module only
creates an immutable Def and a bounded GenCase request; it never invokes
GenCase, a solver, or a native/H5 reader.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


SCHEMA = "ds02.stage2.f1-s1-owner-third-dp-rung.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
RUNNER = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
CURRENT_ROOT = DATA_ROOT / "families/F1/F1_FALLBACK_ECC_COARSE/root-fallback-ecc-coarse-actual-gencase-027"
CURRENT_DEF = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE_Def.xml"
CURRENT_XML = CURRENT_ROOT / "prepared/F1_FALLBACK_ECC_COARSE.xml"
CURRENT_RECEIPT = CURRENT_ROOT / "execution-receipt.json"
OWNER = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F1/"
    "handoff_20261003/root_actual_fallback_canonical_bindings_and_typed_034/"
    "ecc_coarse/owner.json"
)
OWNER_BINDING = OWNER.parent.parent / "ecc-physical-binding.json"
GEOMETRY_EVIDENCE = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_geometry_semantics_source_evidence_v1.json"
EFFECTIVE_AUDIT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_effective_point_support_geometry_audit_v2.json"
INPUT_ROOT = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_f1_s1_owner_third_dp_rung_inputs_v1"
REQUEST_DIR = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/stage2-f1-s1-owner-third-dp-rung-v1"
CASE_ID = "F1_S1_OWNER_THIRD_DP0p008000"
ATTEMPT_ID = "f1-s1-owner-third-dp0p008000-v1-root-001"
CANDIDATE_DEF = INPUT_ROOT / f"{CASE_ID}_Def.xml"
REQUEST_PATH = REQUEST_DIR / f"{CASE_ID.lower()}.json"
OWNER_MASS_KG = 40.2
DP_SOURCE_M = 0.010
DP_CANDIDATE_M = 0.008


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {"path": str(path), "bytes": stat.st_size, "mtime_ns": stat.st_mtime_ns, "sha256": sha256(path)}


def atomic_bytes(path: Path, value: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise FileExistsError(f"refuse overwrite immutable artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)


def atomic_json(path: Path, value: Any) -> None:
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8"))


def derive_def() -> dict[str, Any]:
    source = regular(CURRENT_DEF)
    text = source.read_text(encoding="utf-8")
    definitions = list(re.finditer(r"<definition\b[^>]*>", text))
    if len(definitions) != 1:
        raise ValueError(f"expected one definition tag, found {len(definitions)}")
    tag = definitions[0].group(0)
    dp_matches = list(re.finditer(r'dp="([^"]+)"', tag))
    if len(dp_matches) != 1 or dp_matches[0].group(1) != "0.01":
        raise ValueError("source F1-S1 Def must have exactly dp=0.01")
    start, end = dp_matches[0].span(1)
    derived = text[:definitions[0].start()] + tag[:start] + "0.008" + tag[end:] + text[definitions[0].end():]
    mode = re.findall(r"<setshapemode>\s*(.*?)\s*</setshapemode>", derived, flags=re.S)
    if mode != ["dp | actual | bound"]:
        raise ValueError(f"unexpected source setshapemode: {mode!r}")
    if derived == text:
        raise ValueError("candidate Def did not change")
    normalized_source = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r"\1<DP>\2", text, count=1)
    normalized_candidate = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r"\1<DP>\2", derived, count=1)
    if normalized_source != normalized_candidate:
        raise ValueError("candidate differs outside the intentional dp edit")
    atomic_bytes(CANDIDATE_DEF, derived.encode("utf-8"))
    return {
        "source": record(source),
        "candidate": record(CANDIDATE_DEF),
        "source_dp_m": DP_SOURCE_M,
        "candidate_dp_m": DP_CANDIDATE_M,
        "spacing_separation_from_source_fraction": (DP_SOURCE_M - DP_CANDIDATE_M) / DP_SOURCE_M,
        "spacing_separation_from_completed_dp009_fraction": (0.009 - DP_CANDIDATE_M) / 0.009,
        "normalized_source_sha256": hashlib.sha256(normalized_source.encode()).hexdigest(),
        "normalized_candidate_sha256": hashlib.sha256(normalized_candidate.encode()).hexdigest(),
        "only_intentional_edit": "definition@dp 0.01 -> 0.008",
    }


def self_test() -> dict[str, Any]:
    source = regular(CURRENT_DEF).read_text(encoding="utf-8")
    definitions = list(re.finditer(r"<definition\b[^>]*>", source))
    if len(definitions) != 1:
        raise AssertionError("source definition count is not one")
    tag = definitions[0].group(0)
    if 'dp="0.01"' not in tag:
        raise AssertionError("source dp is not 0.01")
    if re.findall(r"<setshapemode>\s*(.*?)\s*</setshapemode>", source, flags=re.S) != ["dp | actual | bound"]:
        raise AssertionError("source shape mode changed")
    if not (DP_CANDIDATE_M < DP_SOURCE_M and (DP_SOURCE_M - DP_CANDIDATE_M) / DP_SOURCE_M >= 0.10):
        raise AssertionError("third rung is not spacing-separated")
    return {
        "status": "PASS",
        "source_dp_m": DP_SOURCE_M,
        "candidate_dp_m": DP_CANDIDATE_M,
        "source_control_and_geometry_text_preserved": True,
        "spacing_separation_from_source_fraction": 0.2,
        "spacing_separation_from_completed_dp009_fraction": 1.0 / 9.0,
        "owner_mass_target_kg": OWNER_MASS_KG,
        "mass_rescale": False,
        "solver_started": False,
        "gencase_started": False,
        "bi4_read": False,
        "hdf5_read": False,
    }



def build_request_with_commit(launch_commit: str) -> dict[str, Any]:
    info = derive_def() if not CANDIDATE_DEF.exists() else {
        "source": record(CURRENT_DEF),
        "candidate": record(CANDIDATE_DEF),
        "source_dp_m": DP_SOURCE_M,
        "candidate_dp_m": DP_CANDIDATE_M,
        "spacing_separation_from_source_fraction": 0.2,
        "spacing_separation_from_completed_dp009_fraction": 1.0 / 9.0,
        "only_intentional_edit": "definition@dp 0.01 -> 0.008",
    }
    if REQUEST_PATH.exists():
        raise FileExistsError(f"refuse overwrite immutable request: {REQUEST_PATH}")
    # The effective-point audit report is intentionally not an input here: it
    # is the downstream bounded audit for this new product and does not exist
    # before the guarded GenCase attempt.  Bind its source/evidence instead.
    source_paths = [Path(__file__).resolve(), GENCASE, RUNNER, STRICT, RUNTIME, CURRENT_DEF, CURRENT_XML, CURRENT_RECEIPT, OWNER, OWNER_BINDING, GEOMETRY_EVIDENCE, CANDIDATE_DEF]
    paths: list[Path] = []
    seen: set[str] = set()
    for path in source_paths:
        path = regular(path)
        if str(path) not in seen:
            paths.append(path); seen.add(str(path))
    records = {str(path): record(path) for path in paths}
    output_root = DATA_ROOT / "families/F1" / CASE_ID / ATTEMPT_ID
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F1", "sentinel_id": "F1-S1",
        "physical_case_id": "F1_ECC_THICK_DBC_LOWER_HEAD_V1", "case_id": CASE_ID, "attempt_id": ATTEMPT_ID,
        "command": [str(GENCASE), str(CANDIDATE_DEF.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(CANDIDATE_DEF.parent), "worktree_root": str(REPO), "input_files": [str(path) for path in paths],
        "input_hashes": {path: value["sha256"] for path, value in records.items()}, "cpu_threads": 1, "omp_threads": 1,
        "max_wall_seconds": 600, "estimated_input_read_bytes": sum(value["bytes"] for value in records.values()),
        "estimated_storage_bytes": 64 * 1024 * 1024, "estimated_peak_memory_bytes": 512 * 1024 * 1024,
        "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True,
        "hdf5_read": False, "bi4_read": False, "deferred_input_files": [],
        "source_binding": {
            "schema": "ds02.stage2.f1-s1-owner-third-dp-rung-binding.v1",
            "continuous_owner": {"low_m": [0.0, 0.0, 0.0], "size_m": [0.4, 0.67, 0.15], "density_kg_m3": 1000.0, "mass_kg": OWNER_MASS_KG, "authority": "CURRENT336 owner/physical-binding; candidate must not change drawboxes or rescale particle mass"},
            "source_control": {"source_def_sha256": info["source"]["sha256"], "candidate_def_sha256": info["candidate"]["sha256"], "only_intentional_edit": "definition@dp 0.01 -> 0.008", "setshapemode": "dp | actual | bound", "all_other_geometry_and_control_text_unchanged": True},
            "spacing": {"source_dp_m": DP_SOURCE_M, "candidate_dp_m": DP_CANDIDATE_M, "completed_middle_dp_m": 0.009, "separation_from_source_fraction": 0.2, "separation_from_middle_fraction": 1.0 / 9.0},
            "acceptance_after_actual_gencase": {"whole_initial_mass_target_kg": OWNER_MASS_KG, "preferred_absolute_fraction": 0.01, "marginal_absolute_fraction": 0.02, "hard_fail_above_absolute_fraction": 0.02, "owner_geometry_envelope_and_point_support_must_be_audited": True, "no_particle_mass_rescale": True, "no_drawbox_or_control_posthoc_change": True, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            "parent_guard_prepost_hash_required": True,
        },
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(RUNNER), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "launch_commit": launch_commit, "cpu_parent_binding": "required", "gpu": "none", "gpu_uuid_lease": "none", "solver_launch": "forbidden", "hdf5_read": "forbidden", "bi4_read": "forbidden", "source_output_protection": "new attempt output only; immutable CURRENT and completed products"},
        "output_root": str(output_root), "qualification_stage": "stage2_f1_s1_owner_third_dp_rung_gencase_only_pending_parent_audit", "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    atomic_json(REQUEST_PATH, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-input", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    selected = [args.self_test, args.prepare_input, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one of --self-test, --prepare-input, or --build-request")
    if args.self_test:
        print(json.dumps(self_test(), indent=2))
    elif args.prepare_input:
        print(json.dumps(derive_def(), ensure_ascii=False, indent=2))
    else:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit after source commit")
        request = build_request_with_commit(args.launch_commit)
        print(json.dumps({"status": "PREPARED", "path": str(REQUEST_PATH), "input_count": len(request["input_files"]), "estimated_input_read_bytes": request["estimated_input_read_bytes"], "candidate_dp_m": DP_CANDIDATE_M}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
