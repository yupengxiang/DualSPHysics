#!/usr/bin/env python3
"""Prepare the F2-S1 source-centred three-spacing GenCase preflights.

The old ``dp=.00855`` product is retained as a discrete-current-sample
diagnostic.  It is not repackaged as the source-centred reference.  This
forward-only builder keeps the CURRENT drawboxes, motion table, controls and
continuous owner mass fixed, and changes only ``definition@dp`` plus an
explicit lattice phase (``pointref``).  It writes small Def/motion inputs and
parent-guarded GenCase requests; it never runs GenCase or reads a native
payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.source-centered-v3-gencase.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
SOURCE_DEF = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010/root-stage1-f2-f2_stage1_first48_expansion_"
    "rx056_ry014_fill080_rot090_dp010_spatial_reference_save010-actual-"
    "gencase-source801-root804/prepared/"
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010_Def.xml"
)
SOURCE_MOTION = SOURCE_DEF.parent / (
    "F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_DP010_"
    "SPATIAL_REFERENCE_SAVE010_motion.dat"
)
INPUT_ROOT = REFERENCE / "stage2_f2_s1_source_centered_v3_inputs/F2_S1"
MANIFEST_PATH = REFERENCE / "stage2_f2_s1_source_centered_v3_manifest_v1.json"
QA_WORKER = REFERENCE / "stage2_f2_s1_source_centered_v3_initial_native_qa_v1.py"
REQUEST_DIR = STAGE2 / "requests/stage2-f2-s1-source-centered-v3-gencase-v1"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
CONTINUUM_MASS_KG = 18.876
RHO0 = 1000.0

RUNG_TABLE: tuple[dict[str, Any], ...] = (
    {"token": "dp0p0088", "dp_m": 0.0088, "pointref": [0.0013, 0.0, 0.0004],
     "counts_per_layer": [37, 25, 10], "fluid_count": 27_750,
     "storage_bytes": 256 * 1024**2, "wall_seconds": 900, "memory_bytes": 2 * 1024**3},
    {"token": "dp0p0044", "dp_m": 0.0044, "pointref": [0.0035, 0.0022, 0.0026],
     "counts_per_layer": [74, 50, 20], "fluid_count": 222_000,
     "storage_bytes": 1024**3, "wall_seconds": 1800, "memory_bytes": 4 * 1024**3},
    {"token": "dp0p0022", "dp_m": 0.0022, "pointref": [0.0002, 0.0011, 0.0015],
     "counts_per_layer": [148, 100, 40], "fluid_count": 1_776_000,
     "storage_bytes": 8 * 1024**3, "wall_seconds": 3600, "memory_bytes": 8 * 1024**3},
)


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
    return {"path": str(path), "bytes": int(stat.st_size), "mtime_ns": int(stat.st_mtime_ns), "sha256": sha256(path)}


def atomic_bytes(path: Path, value: bytes) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        if path.read_bytes() == value:
            return
        raise FileExistsError(f"refuse to overwrite immutable artifact: {path}")
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
    atomic_bytes(path, (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode())


def source_motion_name() -> str:
    text = regular(SOURCE_DEF).read_text(encoding="utf-8")
    match = re.search(r'<file\s+name="([^"]+\.dat)"', text)
    if match is None:
        raise ValueError("F2 source Def has no motion file reference")
    if match.group(1) != SOURCE_MOTION.name:
        raise ValueError(f"source motion basename mismatch: XML={match.group(1)} path={SOURCE_MOTION.name}")
    return match.group(1)


def derive_def(rung: dict[str, Any]) -> Path:
    source_path = regular(SOURCE_DEF)
    source_text = source_path.read_text(encoding="utf-8")
    if "<pointref" in source_text:
        raise ValueError("frozen F2 source unexpectedly already contains pointref")
    tag_matches = list(re.finditer(r"<definition\b[^>]*>", source_text))
    if len(tag_matches) != 1:
        raise ValueError(f"expected one F2 definition tag, found {len(tag_matches)}")
    tag = tag_matches[0].group(0)
    if tag.count('dp="0.01"') != 1:
        raise ValueError(f"frozen F2 definition is not dp=0.01: {tag}")
    dp_text = format(float(rung["dp_m"]), ".4f").rstrip("0").rstrip(".")
    phase = rung["pointref"]
    pointref = f'<pointref x="{phase[0]:.4f}" y="{phase[1]:.4f}" z="{phase[2]:.4f}" />'
    start, end = tag_matches[0].span()
    new_tag = tag.replace('dp="0.01"', f'dp="{dp_text}"', 1)
    derived = source_text[:start] + new_tag + "\n        " + pointref + source_text[end:]
    if derived == source_text or derived.count("<pointref") != 1:
        raise ValueError("F2 source-centred candidate did not add exactly one pointref")
    normalized_source = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r"\1<DP>\2", source_text, count=1)
    normalized_candidate = re.sub(r'\s*<pointref\b[^>]*/>', "", derived, count=1)
    normalized_candidate = re.sub(r'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', r"\1<DP>\2", normalized_candidate, count=1)
    if normalized_source != normalized_candidate:
        raise ValueError("source-centred candidate changes text beyond dp/pointref")
    case_id = f"F2_S1_SOURCE_CENTERED_V3_{rung['token'].upper()}"
    output_dir = INPUT_ROOT / rung["token"]
    candidate = output_dir / f"{case_id}_Def.xml"
    motion = output_dir / source_motion_name()
    atomic_bytes(candidate, derived.encode("utf-8"))
    source_motion = regular(SOURCE_MOTION)
    motion_bytes = source_motion.read_bytes()
    atomic_bytes(motion, motion_bytes)
    return candidate


def lattice_expected(rung: dict[str, Any]) -> dict[str, Any]:
    dp = float(rung["dp_m"])
    count = int(rung["fluid_count"])
    particle_mass = RHO0 * dp**3
    predicted = count * particle_mass
    per_layer = int(rung["counts_per_layer"][0] * rung["counts_per_layer"][1] * rung["counts_per_layer"][2])
    fraction = (predicted - CONTINUUM_MASS_KG) / CONTINUUM_MASS_KG
    return {
        "basis": "registered inclusive lattice counts; GenCase XML/VTK/receipt remain authoritative",
        "counts_per_layer": list(rung["counts_per_layer"]),
        "layer_count": 3,
        "predicted_fluid_count": count,
        "predicted_per_layer_count": per_layer,
        "massfluid_kg_predicted": particle_mass,
        "predicted_continuum_sample_mass_kg": predicted,
        "whole_initial_continuum_owner_mass_kg": CONTINUUM_MASS_KG,
        "predicted_relative_to_continuum_fraction": fraction,
        "predicted_relative_to_continuum_percent": 100.0 * fraction,
        "preferred_mass_gate": "abs(relative whole-initial mass fraction) <= 0.01",
        "marginal_mass_gate": "0.01 < abs(relative fraction) <= 0.02",
        "hard_mass_gate": "abs(relative fraction) > 0.02",
        "not_actual_until_gencase": True,
    }


def prepare_inputs() -> dict[str, Any]:
    source_motion_name()
    for rung in RUNG_TABLE:
        derive_def(rung)
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_SOURCE_CENTERED_V3_GENCASE_INPUTS",
        "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": PHYSICAL_CASE_ID,
        "source_def": record(SOURCE_DEF), "source_motion": record(SOURCE_MOTION),
        "continuous_owner": {
            "shape": "three solid fluid drawboxes",
            "layer_low_m": [[0.05, -0.11, 0.70], [0.05, -0.11, 0.788], [0.05, -0.11, 0.876]],
            "layer_size_m": [0.325, 0.22, 0.088], "layer_count": 3,
            "volume_m3": 0.018876, "density_kg_m3": RHO0, "mass_kg": CONTINUUM_MASS_KG,
            "authority": "frozen CURRENT source drawboxes; representation phase is separate",
        },
        "historical_discrete_sample": {"mass_kg": 21.114, "role": "diagnostic only; not V3 continuum gate; no rescale"},
        "representation_rule": {
            "only_definition_edits": ["dp", "pointref"],
            "drawboxes_preserved": True, "motion_preserved": True, "execution_controls_preserved": True,
            "mass_rescale": False, "continuous_geometry_changed": False,
        },
        "rungs": [],
    }
    for rung in RUNG_TABLE:
        candidate = INPUT_ROOT / rung["token"] / f"F2_S1_SOURCE_CENTERED_V3_{rung['token'].upper()}_Def.xml"
        motion = INPUT_ROOT / rung["token"] / SOURCE_MOTION.name
        manifest["rungs"].append({**rung, "candidate_def": record(candidate), "motion": record(motion), "lattice": lattice_expected(rung)})
    atomic_json(MANIFEST_PATH, manifest)
    return manifest


def build_requests(launch_commit: str) -> dict[str, Any]:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8")) if MANIFEST_PATH.is_file() else prepare_inputs()
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    requests: list[dict[str, Any]] = []
    for rung in manifest["rungs"]:
        token = str(rung["token"])
        case_id = f"F2_S1_SOURCE_CENTERED_V3_{token.upper()}"
        attempt_id = f"f2-s1-source-centered-v3-{token}-gencase-root-forward-001"
        candidate = Path(rung["candidate_def"]["path"])
        motion = Path(rung["motion"]["path"])
        output_root = DATA_ROOT / "families/F2" / case_id / attempt_id
        paths = [Path(__file__), candidate, motion, SOURCE_DEF, SOURCE_MOTION, GENCASE, DISPATCH, STRICT, RUNTIME]
        paths = list(dict.fromkeys(regular(path) for path in paths))
        records = {str(path): record(path) for path in paths}
        request_path = REQUEST_DIR / f"{case_id.lower()}.json"
        if request_path.exists():
            raise FileExistsError(request_path)
        request = {
            "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase",
            "family_id": "F2", "sentinel_id": "F2-S1", "physical_case_id": PHYSICAL_CASE_ID,
            "case_id": case_id, "attempt_id": attempt_id, "launch_commit": launch_commit,
            "command": [str(GENCASE), str(candidate.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
            "cwd": str(candidate.parent), "worktree_root": str(REPO),
            "input_files": list(records), "input_hashes": {path: item["sha256"] for path, item in records.items()},
            "input_records": records, "deferred_input_files": [], "cpu_threads": 1, "omp_threads": 1,
            "max_wall_seconds": int(rung["wall_seconds"]), "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()),
            "estimated_storage_bytes": int(rung["storage_bytes"]), "estimated_peak_memory_bytes": int(rung["memory_bytes"]),
            "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
            "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True,
            "solver_launch": False, "hdf5_read": False, "bi4_read": False,
            "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
            "source_binding": {
                "schema": "ds02.stage2.f2-s1.source-centered-v3-binding.v1",
                "source_def": records[str(SOURCE_DEF)], "source_motion": records[str(SOURCE_MOTION)],
                "candidate_def": records[str(candidate)], "candidate_motion": records[str(motion)],
                "representation": {"dp_m": rung["dp_m"], "pointref_m": rung["pointref"], "only_intentional_edits": ["definition@dp", "definition/pointref"]},
                "continuous_owner": manifest["continuous_owner"], "controls_and_drawboxes_frozen": True,
                "mass_audit_preregistration": rung["lattice"],
                "post_gencase_required": ["generated.xml", "generated.bi4", "execution-receipt.json", "GenCase.out/VTK if present"],
                "old_dp00855_lineage": {"status": "NOT_THIS_REFERENCE_RECIPE", "role": "immutable discrete-current-sample diagnostic only"},
            },
            "qa_followup": {
                "worker": str(QA_WORKER.resolve()), "request_template": str((REQUEST_DIR / f"{case_id.lower()}_initial_native_qa.json").resolve()),
                "required_after_terminal": True, "native_frame": 0, "no_hdf5_or_full_tree_scan": True,
                "expected_fluid_count_predicted": rung["fluid_count"], "expected_mass_predicted_kg": rung["lattice"]["predicted_continuum_sample_mass_kg"],
                "qualification_until_qa": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
            },
            "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME),
                               "launch_commit": launch_commit, "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden",
                               "hdf5_read": "forbidden", "source_output_protection": "new attempt tree only; frozen source immutable"},
            "qualification_stage": "stage2_f2_s1_source_centered_v3_gencase_preflight_pending_initial_native_qa",
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        }
        atomic_json(request_path, request)
        qa_path = REQUEST_DIR / f"{case_id.lower()}_initial_native_qa.json"
        qa_attempt = f"f2-s1-source-centered-v3-{token}-initial-native-qa-root-forward-001"
        generated_root = output_root / "generated"
        qa_output_root = DATA_ROOT / "families/F2" / f"{case_id}_INITIAL_NATIVE_QA" / qa_attempt
        qa_static = [Path(__file__), QA_WORKER, candidate, motion, SOURCE_DEF, SOURCE_MOTION, PYTHON, GENCASE, DISPATCH, STRICT, RUNTIME]
        qa_static = list(dict.fromkeys(regular(path) for path in qa_static))
        qa_records = {str(path): record(path) for path in qa_static}
        qa = {
            "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "audit", "family_id": "F2", "sentinel_id": "F2-S1",
            "physical_case_id": PHYSICAL_CASE_ID, "case_id": f"{case_id}_INITIAL_NATIVE_QA", "attempt_id": qa_attempt,
            "launch_commit": launch_commit,
            "command": [str(PYTHON), str(QA_WORKER.resolve()), "--generated-xml", str(generated_root / "generated.xml"),
                        "--generated-bi4", str(generated_root / "generated.bi4"), "--gencase-receipt", str(output_root / "execution-receipt.json"),
                        "--candidate-def", str(candidate), "--source-def", str(SOURCE_DEF), "--source-motion", str(SOURCE_MOTION),
                        "--decoder", str(Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")),
                        "--decoder-source", str(REPO / "lagrangian-fluid-lab/scripts/native/bi4_dump.cpp"),
                        "--output", "{attempt_root}/f2_initial_native_qa.json", "--scratch-root", "{attempt_root}/scratch"],
            "cwd": str(REPO), "worktree_root": str(REPO), "input_files": list(qa_records),
            "input_hashes": {path: item["sha256"] for path, item in qa_records.items()},
            "deferred_input_files": [str(generated_root / "generated.xml"), str(generated_root / "generated.bi4"), str(output_root / "execution-receipt.json")],
            "deferred_input_stats": {str(generated_root / "generated.xml"): {"sha256": "PARENT_GUARD_COMPUTED"}, str(generated_root / "generated.bi4"): {"sha256": "PARENT_GUARD_COMPUTED"}, str(output_root / "execution-receipt.json"): {"sha256": "PARENT_GUARD_COMPUTED"}},
            "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 3600, "estimated_native_read_bytes": "PARENT_GUARD_MEASURE_GENERATED_BI4",
            "estimated_storage_bytes": 2 * 1024**3, "estimated_peak_memory_bytes": 2 * 1024**3,
            "execution_allowed": False, "launch_disabled": True, "solver_started": False, "gencase_launch": False, "solver_launch": False,
            "hdf5_read": False, "bi4_read": True, "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(DISPATCH), "strict_guard": str(STRICT), "runtime": str(RUNTIME), "parent_guard_required": True, "solver_launch": "forbidden", "hdf5_read": "forbidden"},
            "source_binding": {"candidate_def": records[str(candidate)], "source_def": records[str(SOURCE_DEF)], "source_motion": records[str(SOURCE_MOTION)], "generated_outputs": "deferred until corresponding GenCase receipt", "mass_gate": "whole initial fluid mass against 18.876kg; per-MK audit; no rescale", "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}},
            "output_root": str(qa_output_root), "output": {"atomic": True, "refuse_overwrite": True},
        }
        atomic_json(qa_path, qa)
        requests.append({"gencase_request": str(request_path), "qa_template": str(qa_path), "rung": token})
    report = {"schema": SCHEMA, "status": "PREPARED_SOURCE_CENTERED_V3_GENCАSE_AND_QA_TEMPLATES", "manifest": str(MANIFEST_PATH), "requests": requests, "launch_commit": launch_commit, "gencase_started": False, "native_qa_started": False}
    atomic_json(REFERENCE / "stage2_f2_s1_source_centered_v3_requests_v1.json", report)
    return report


def self_test() -> dict[str, Any]:
    assert len(RUNG_TABLE) == 3
    assert all(abs(lattice_expected(r)["predicted_relative_to_continuum_percent"]) <= 1 for r in RUNG_TABLE)
    assert all(r["fluid_count"] == 3 * r["counts_per_layer"][0] * r["counts_per_layer"][1] * r["counts_per_layer"][2] for r in RUNG_TABLE)
    source_motion_name()
    return {"status": "PASS", "rungs": [r["token"] for r in RUNG_TABLE], "predicted_continuum_mass_gate": "within_1pct", "gencase_started": False, "native_payload_read": False, "old_dp00855_reused_as_reference": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-inputs", action="store_true")
    parser.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    if sum((args.self_test, args.prepare_inputs, args.build_requests)) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    elif args.prepare_inputs:
        value = prepare_inputs()
    else:
        if not args.launch_commit:
            parser.error("--build-requests requires --launch-commit")
        value = build_requests(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": "PREPARED", "result": str(MANIFEST_PATH if args.prepare_inputs else REFERENCE / 'stage2_f2_s1_source_centered_v3_requests_v1.json')}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
