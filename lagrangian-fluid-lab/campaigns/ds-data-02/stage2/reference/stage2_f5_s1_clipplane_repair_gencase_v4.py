#!/usr/bin/env python3
"""Build source-bound F5 clip-plane GenCase-only requests (forward V4).

The old V2 manifests embed the reference worktree path in their records.  V3
does not consume or rewrite those manifests.  It binds the already committed
candidate Def/motion files by their current primary-tree paths, accepts the
immutable source Def/motion paths explicitly, and emits fresh parent-v8
GenCase requests.  V4 corrects the toolchain record: ``GenCase_linux64`` is
the 5,809,384-byte GenCase generator; the 159,206,984-byte binary belongs to
the solver and must not be used as the GenCase input size.  The candidate byte
comparison permits only ``dp`` and
``pointref`` changes; the fluid box, clip plane, bed, motion table and solver
controls remain source-bound.  No GenCase, solver, BI4, HDF5 or VTK payload is
read by this builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f5-s1.clipplane-repair-gencase.v4"
PRIMARY_REPO = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
LOCAL_REPO = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
REFERENCE_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference"
STAGE2_REL = "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
TEMPLATE = PRIMARY_REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
DISPATCH = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = PRIMARY_REPO / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
EVIDENCE_DEFAULT = PRIMARY_REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_official_evidence_audit_v2.json"
SOURCE_DEF_DEFAULT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/"
    "handoff_20261003/root_followup_118_stage1_f5_c082s1_first24_cpu_contract_disabled_v1/"
    "candidates/M095_T090/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1_M095_T090_Def.xml"
)
SOURCE_MOTION_DEFAULT = DATA_ROOT / (
    "families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1/"
    "root-stage1-f5-c082s1-m095_t090-motion-transform-117-root630/prepared/assets/"
    "f5_c082s1_motion_m095_t090.dat"
)
CANDIDATE_ROOT_DEFAULT = PRIMARY_REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_repair_v2_inputs/F5_S1"

PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T090"
CONTINUOUS_MASS_KG = 287.736
OLD_SAMPLE_MASS_KG = 254.4779834119572
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
GENCASE_BYTES = 5_809_384

GRIDS = {
    "dp010": {
        "dp_m": 0.010,
        "pointref_m": (0.015, 0.0, 0.015),
        "candidate_dir": "dp010",
        "candidate_prefix": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP010_Def",
        "case_id": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP010_V4_ROOT_REVIEW",
        "attempt_id": "f5-s1-clipplane-center-lattice-dp010-gencase-v4-root-review-001",
        "storage_bytes": 512 * 1024 * 1024,
        "wall_seconds": 900,
    },
    "dp005": {
        "dp_m": 0.005,
        "pointref_m": (0.0125, 0.0, 0.0125),
        "candidate_dir": "dp005",
        "candidate_prefix": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP005_Def",
        "case_id": "F5_S1_CLIPPLANE_CENTER_LATTICE_DP005_V4_ROOT_REVIEW",
        "attempt_id": "f5-s1-clipplane-center-lattice-dp005-gencase-v4-root-review-001",
        "storage_bytes": 4 * 1024**3,
        "wall_seconds": 1800,
    },
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def regular(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(f"{label} must be a regular file: {path}")
    return path


def record(path: Path, label: str, *, content_scope: str = "small_input_hashed_by_builder_and_parent") -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
        "sha256": sha256(path),
        "content_scope": content_scope,
    }


def official_binary_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    # Parent v8 hashes the 5.8 MB GenCase executable after reservation; this
    # known digest is source-bound from the official binary verification
    # already used by Stage2.  Do not substitute the separately sized solver
    # executable here.
    if path != GENCASE.resolve():
        raise ValueError("only the registered official GenCase binary may use the known digest")
    return {
        "path": str(path),
        "bytes": GENCASE_BYTES,
        "sha256": GENCASE_SHA256,
        "content_scope": "PARENT_V8_AFTER_RESERVATION_HASH",
        "hash_source": "official_binary_verification_earlier_stage2",
    }


def normalize_definition(data: bytes) -> bytes:
    data, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if count != 1:
        raise ValueError("source/candidate Def must contain exactly one definition@dp")
    data, count = re.subn(rb'<pointref\s+x="[^"]+"\s+y="[^"]+"\s+z="[^"]+"\s*/>', b'<pointref x="<X>" y="<Y>" z="<Z>" />', data, count=1)
    if count != 1:
        raise ValueError("source/candidate Def must contain exactly one pointref")
    return data


def definition_facts(data: bytes) -> tuple[float, tuple[float, float, float]]:
    match = re.search(rb'<definition\b[^>]*\bdp="([^"]+)"', data)
    point = re.search(rb'<pointref\s+x="([^"]+)"\s+y="([^"]+)"\s+z="([^"]+)"\s*/>', data)
    if not match or not point:
        raise ValueError("cannot extract candidate dp/pointref")
    return float(match.group(1)), tuple(float(point.group(index)) for index in range(1, 4))


def json_new(path: Path, value: dict[str, Any]) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            if fd >= 0:
                os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def build_request(grid: str, args: argparse.Namespace) -> dict[str, Any]:
    spec = GRIDS[grid]
    source_def = regular(Path(args.source_def), "F5 source Def")
    source_motion = regular(Path(args.source_motion), "F5 source motion")
    evidence = regular(Path(args.evidence), "F5 official clip evidence")
    candidate_dir = Path(args.candidate_root).expanduser().resolve() / spec["candidate_dir"]
    candidate_def = regular(candidate_dir / f"{spec['candidate_prefix']}.xml", "F5 candidate Def")
    candidate_motion = regular(candidate_dir / "assets" / source_motion.name, "F5 candidate motion")
    source_data = source_def.read_bytes()
    candidate_data = candidate_def.read_bytes()
    source_dp, _ = definition_facts(source_data)
    candidate_dp, candidate_point = definition_facts(candidate_data)
    if abs(candidate_dp - spec["dp_m"]) > 1e-12 or any(abs(candidate_point[index] - spec["pointref_m"][index]) > 1e-12 for index in range(3)):
        raise ValueError(f"{grid}: candidate dp/pointref differs from the registered V4 rung")
    if normalize_definition(source_data) != normalize_definition(candidate_data):
        raise ValueError(f"{grid}: candidate changes source Def outside dp/pointref")
    if candidate_motion.read_bytes() != source_motion.read_bytes():
        raise ValueError(f"{grid}: candidate motion is not byte-identical to source motion")

    static_paths = [
        (source_def, "F5 source Def"), (source_motion, "F5 source motion"),
        (candidate_def, "F5 candidate Def"), (candidate_motion, "F5 candidate motion"),
        (evidence, "F5 official clip evidence"), (Path(__file__).resolve(), "F5 V4 builder"),
        (DISPATCH, "parent v8 dispatch"), (STRICT, "parent v8 strict dispatch"),
        (RUNTIME, "parent v8 runtime"), (GENCASE_CONFIG, "official GenCase config"),
        (TEMPLATE, "GenCase template"), (PYTHON, "stage2 interpreter"),
    ]
    records = {str(path.resolve()): record(path, label) for path, label in static_paths}
    records[str(GENCASE.resolve())] = official_binary_record(GENCASE)
    input_files = sorted(records)
    output_root = DATA_ROOT / "families/F5" / spec["case_id"] / spec["attempt_id"]
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "family_id": "F5",
        "sentinel_id": "F5-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": spec["case_id"],
        "attempt_id": spec["attempt_id"],
        "launch_commit": args.launch_commit,
        "command": [str(GENCASE), str(candidate_def.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(candidate_def.parent),
        "worktree_root": str(PRIMARY_REPO),
        "input_files": input_files,
        "input_hashes": {path: records[path]["sha256"] for path in input_files},
        "input_records": records,
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": spec["wall_seconds"],
        "max_memory_bytes": 2 * 1024**3,
        "estimated_storage_bytes": spec["storage_bytes"],
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_input_read_bytes": sum(int(row["bytes"]) for row in records.values()),
        "estimated_native_read_bytes": 0,
        "estimated_bi4_read_bytes": 0,
        "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True,
        "launch_disabled": False,
        "solver_started": False,
        "gencase_launch": True,
        "solver_launch": False,
        "hdf5_read": False,
        "bi4_read": False,
        "output_root": str(output_root),
        "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {
            "schema": SCHEMA,
            "grid": grid,
            "dp_m": spec["dp_m"],
            "pointref_m": list(spec["pointref_m"]),
            "source_dp_m": source_dp,
            "source_def": records[str(source_def.resolve())],
            "candidate_def": records[str(candidate_def.resolve())],
            "source_motion": records[str(source_motion.resolve())],
            "candidate_motion": records[str(candidate_motion.resolve())],
            "candidate_normalized_def_sha256": hashlib.sha256(normalize_definition(candidate_data)).hexdigest(),
            "source_normalized_def_sha256": hashlib.sha256(normalize_definition(source_data)).hexdigest(),
            "official_clip_evidence": records[str(evidence.resolve())],
            "continuous_region_mass_kg": CONTINUOUS_MASS_KG,
            "old_sample_mass_kg": OLD_SAMPLE_MASS_KG,
            "continuous_box_and_clip_unchanged": True,
            "controls_and_motion_unchanged": True,
            "mass_rescale": False,
            "support_mass_qa_required_before_solver": True,
            "toolchain": {
                "generator": "GenCase_linux64",
                "generator_bytes": GENCASE_BYTES,
                "generator_sha256": GENCASE_SHA256,
                "generator_role": "GenCase input generator; not the solver binary",
                "config_path": str(GENCASE_CONFIG),
                "template_path": str(TEMPLATE),
            },
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "source_pre_post_hash_required": True,
        },
        "qualification_stage": "stage2_f5_s1_source_preserving_clipplane_gencase_only_v4_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "GenCase-only source representation; continuous mass/support must be measured from the terminal product"},
        "status": "READY_FOR_PARENT_V8_CPU_GENCASE_REVIEW",
    }
    request["sha256"] = canonical_sha(request)
    return request


def self_test() -> dict[str, Any]:
    local_candidate_root = LOCAL_REPO / REFERENCE_REL / "stage2_f5_s1_clipplane_repair_v2_inputs/F5_S1"
    for grid, spec in GRIDS.items():
        candidate = local_candidate_root / spec["candidate_dir"] / f"{spec['candidate_prefix']}.xml"
        candidate_motion = local_candidate_root / spec["candidate_dir"] / "assets" / SOURCE_MOTION_DEFAULT.name
        source = SOURCE_DEF_DEFAULT.read_bytes()
        candidate_data = candidate.read_bytes()
        assert normalize_definition(source) == normalize_definition(candidate_data)
        dp, point = definition_facts(candidate_data)
        assert abs(dp - spec["dp_m"]) < 1e-12
        assert all(abs(point[index] - spec["pointref_m"][index]) < 1e-12 for index in range(3))
        assert candidate_motion.read_bytes() == SOURCE_MOTION_DEFAULT.read_bytes()
    assert GENCASE_BYTES == 5_809_384
    assert GENCASE_SHA256 == "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
    assert GENCASE.is_file() and GENCASE_CONFIG.is_file() and TEMPLATE.is_file()
    return {"status": "PASS", "schema": SCHEMA, "grids": sorted(GRIDS), "source_changes": ["dp", "pointref"], "gencase_bytes": GENCASE_BYTES, "gencase_sha256": GENCASE_SHA256, "solver_started": False, "bi4_read": False, "hdf5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit")
    parser.add_argument("--source-def", type=Path, default=SOURCE_DEF_DEFAULT)
    parser.add_argument("--source-motion", type=Path, default=SOURCE_MOTION_DEFAULT)
    parser.add_argument("--evidence", type=Path, default=EVIDENCE_DEFAULT)
    parser.add_argument("--candidate-root", type=Path, default=CANDIDATE_ROOT_DEFAULT)
    parser.add_argument("--output-dir", type=Path, default=PRIMARY_REPO / STAGE2_REL / "requests/f5-s1-clipplane-repair-v4")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit:
        parser.error("--build-requests requires the parent integration launch commit")
    args.output_dir = args.output_dir.expanduser().resolve()
    results = []
    for grid in GRIDS:
        request = build_request(grid, args)
        output = args.output_dir / f"f5_s1_clipplane_repair_{grid}_gencase_v4.json"
        json_new(output, request)
        results.append({"grid": grid, "request": str(output), "request_sha256": sha256(output), "candidate": request["source_binding"]["candidate_def"]["path"]})
    print(json.dumps({"schema": SCHEMA, "status": "PREPARED_TWO_GENCASE_ONLY_REQUESTS", "results": results, "gencase_bytes": GENCASE_BYTES, "solver_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
