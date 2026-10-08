#!/usr/bin/env python3
"""Prepare F2-S2 exact-source three-grid GenCase and control contracts.

F2-S2 is the second offset/open-rim sentinel, with CURRENT336 physical
identity ``F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080``.  This forward
builder resolves that exact CURRENT row and its sibling Def/motion source,
then binds the already prepared dp=.0125/.010/.008 Def files.  It verifies
that each candidate changes only ``definition@dp`` and that the source
motion/control bytes remain identical.  Requests are GenCase-only CPU
preflights; actual particle count, support, mass and later solver eligibility
remain UNKNOWN until a parent guard executes each request.

No BI4, H5, VTK or solver payload is read.  Existing v1 preflight files and
requests are preserved; V3 emits fresh request identities and a source-bound
ladder plan under a caller-selected output directory.

V3 corrects the toolchain record: ``GenCase_linux64`` is the 5,809,384-byte
GenCase generator.  The 159,206,984-byte executable is a solver binary and is
not the GenCase input.  Both the official ``DsphConfig.xml`` and
``GenCase_CaseTemplate.xml`` are bound as small inputs.  No BI4, H5, VTK or
solver payload is read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


REQUEST_SCHEMA = "ds02.request.v1"
SCHEMA = "ds02.stage2.f2-s2.source-control-ladder.v3"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PYTHON = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
GENCASE_CONFIG_NAME = "DsphConfig.xml"
PHYSICAL_CASE_ID = "F2_STAGE1_OFFSET_P03_OPEN_RIM_RX065_RY014_FILL080"
SENTINEL_ID = "F2-S2"
SOURCE_DP_M = 0.01
GRIDS = {
    "coarse": {"label": "coarse", "dp_m": 0.0125, "storage_bytes": 128 * 1024**2, "wall_seconds": 600, "case_id": "F2_S2_OWNER_SOURCE_CONTROL_DP0125_V3", "attempt_id": "f2-s2-owner-source-control-dp0125-gencase-v3-parent-review-001"},
    "original": {"label": "original", "dp_m": 0.01, "storage_bytes": 256 * 1024**2, "wall_seconds": 600, "case_id": "F2_S2_OWNER_SOURCE_CONTROL_DP010_V3", "attempt_id": "f2-s2-owner-source-control-dp010-gencase-v3-parent-review-001"},
    "fine": {"label": "fine", "dp_m": 0.008, "storage_bytes": 512 * 1024**2, "wall_seconds": 600, "case_id": "F2_S2_OWNER_SOURCE_CONTROL_DP008_V3", "attempt_id": "f2-s2-owner-source-control-dp008-gencase-v3-parent-review-001"},
}
GENCASE_SHA256 = "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
GENCASE_BYTES = 5_809_384


def repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


def stage2_root() -> Path:
    return repo_root() / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"


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


def record(path: Path, label: str) -> dict[str, Any]:
    path = regular(path, label)
    value = path.stat()
    return {"path": str(path), "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns), "st_dev": int(value.st_dev), "st_ino": int(value.st_ino), "sha256": sha256(path), "content_scope": "small_input_hashed_by_builder_and_parent_v8"}


def official_binary_record(path: Path) -> dict[str, Any]:
    path = path.expanduser().resolve()
    if not path.is_file() or path != GENCASE.resolve():
        raise FileNotFoundError(f"official GenCase binary unavailable: {path}")
    return {"path": str(path), "bytes": GENCASE_BYTES, "sha256": GENCASE_SHA256, "content_scope": "PARENT_V8_AFTER_RESERVATION_HASH", "hash_source": "official_binary_verification_earlier_stage2"}


def json_new(path: Path, value: Any) -> None:
    path = path.expanduser().absolute()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
        try:
            with os.fdopen(fd, "wb") as handle:
                fd = -1; handle.write(payload); handle.flush(); os.fsync(handle.fileno())
        finally:
            if fd >= 0: os.close(fd)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def canonical_sha(value: dict[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def parse_xml_facts(path: Path) -> dict[str, Any]:
    root = ET.fromstring(path.read_bytes())
    definition = next((item for item in root.iter() if local_name(item) == "definition" and "dp" in item.attrib), None)
    if definition is None:
        raise ValueError(f"source XML has no definition@dp: {path}")
    parameters = {item.attrib["key"]: item.attrib.get("value") for item in root.iter() if local_name(item) == "parameter" and "key" in item.attrib}
    constants = {}
    for key in ("cflnumber", "h", "massfluid", "rhop0", "gamma"):
        item = next((node for node in root.iter() if local_name(node) == key), None)
        if item is not None:
            constants[key] = dict(item.attrib)
    rotations = []
    for item in root.iter():
        if local_name(item) == "mvrotfile":
            file_node = next((node for node in item if local_name(node) == "file"), None)
            rotations.append({"attributes": dict(item.attrib), "file": dict(file_node.attrib) if file_node is not None else None, "axis_p1": next((dict(node.attrib) for node in item if local_name(node) == "axisp1"), None), "axis_p2": next((dict(node.attrib) for node in item if local_name(node) == "axisp2"), None)})
    drawboxes = []
    for item in root.iter():
        if local_name(item) == "drawbox":
            point = next((node for node in item if local_name(node) == "point"), None)
            size = next((node for node in item if local_name(node) == "size"), None)
            drawboxes.append({"point": dict(point.attrib) if point is not None else None, "size": dict(size.attrib) if size is not None else None, "boxfill": next((node.text.strip() for node in item if local_name(node) == "boxfill" and node.text), None)})
    return {"definition_dp_m": float(definition.attrib["dp"]), "parameters": parameters, "constants": constants, "rotations": rotations, "drawboxes": drawboxes, "xml_sha256": sha256(path)}


def normalize_definition(data: bytes) -> bytes:
    data, count = re.subn(rb'(<definition\b[^>]*\bdp=")[^"]+("[^>]*>)', rb"\1<DP>\2", data, count=1)
    if count != 1:
        raise ValueError("Def must contain exactly one definition@dp")
    return data


def load_exact_source() -> dict[str, Any]:
    current_path = DATA_ROOT / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
    review_path = stage2_root() / "review-source/SENTINEL_MATRIX.json"
    current = json.loads(regular(current_path, "CURRENT336").read_text(encoding="utf-8"))
    review = json.loads(regular(review_path, "SENTINEL_MATRIX").read_text(encoding="utf-8"))
    review_row = next((row for row in review.get("sentinels", []) if row.get("sentinel_id") == SENTINEL_ID), None)
    if review_row is None or review_row.get("source_physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("F2-S2 review identity mismatch")
    matches = [row for row in current.get("cases", []) if row.get("physical_case_id") == PHYSICAL_CASE_ID]
    if len(matches) != 1:
        raise ValueError(f"expected one exact CURRENT row, found {len(matches)}")
    row = matches[0]
    source_xml = regular(Path(row["source_bindings"]["generated_xml"]["path"]), "F2-S2 generated XML")
    source_receipt = regular(Path(row["source_bindings"]["gencase_receipt"]["path"]), "F2-S2 GenCase receipt")
    source_def = regular(source_xml.with_name(source_xml.stem + "_Def.xml"), "F2-S2 source Def")
    source_motion = regular(source_xml.with_name(source_xml.stem + "_motion.dat"), "F2-S2 source motion")
    receipt = json.loads(source_receipt.read_text(encoding="utf-8"))
    request = receipt.get("request") or {}
    if request.get("physical_case_id") != PHYSICAL_CASE_ID or receipt.get("returncode") != 0:
        raise ValueError("F2-S2 source GenCase receipt identity/status mismatch")
    source_facts = parse_xml_facts(source_xml)
    if abs(source_facts["definition_dp_m"] - SOURCE_DP_M) > 1e-12:
        raise ValueError("F2-S2 source dp differs from CURRENT")
    return {"current_path": current_path, "review_path": review_path, "current": row, "review": review_row, "source_xml": source_xml, "source_receipt": source_receipt, "source_def": source_def, "source_motion": source_motion, "receipt": receipt, "request": request, "source_facts": source_facts}


def candidate_paths(grid: str, root: Path) -> tuple[Path, Path]:
    # ``root`` is the repository root when this builder is invoked by the
    # parent guard.  The prepared candidates live below the campaign's
    # reference directory, rather than directly below the repository root.
    directory = root / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/F2_S2" / grid
    if not directory.is_dir():
        # Keep the builder portable when it is run from a checkout whose
        # repository root has been relocated.
        directory = Path(__file__).resolve().parent / "stage2_sentinel_spatial_preflight_inputs_v1/F2_S2" / grid
    candidate = next(directory.glob("*_Def.xml"))
    motion = next(directory.glob("*_motion.dat"))
    return candidate, motion


def build_one(grid: str, args: argparse.Namespace, source: dict[str, Any]) -> dict[str, Any]:
    spec = GRIDS[grid]
    candidate_def, candidate_motion = candidate_paths(grid, repo_root())
    source_def = source["source_def"]
    source_motion = source["source_motion"]
    if abs(parse_xml_facts(candidate_def)["definition_dp_m"] - spec["dp_m"]) > 1e-12:
        raise ValueError(f"{grid}: candidate XML dp differs from registered spacing")
    if normalize_definition(source_def.read_bytes()) != normalize_definition(candidate_def.read_bytes()):
        raise ValueError(f"{grid}: candidate Def changes source beyond definition@dp")
    if source_motion.read_bytes() != candidate_motion.read_bytes():
        raise ValueError(f"{grid}: candidate motion is not byte-identical to source motion")
    dispatch = repo_root() / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
    strict = repo_root() / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
    runtime = repo_root() / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
    runtime_v6 = repo_root() / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v6.py"
    runtime_v2 = repo_root() / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
    builder = Path(__file__).resolve()
    config = GENCASE.parent / GENCASE_CONFIG_NAME
    template = repo_root() / "doc/xml_format/GenCase_CaseTemplate.xml"
    static = [
        (source["current_path"], "CURRENT336"), (source["review_path"], "SENTINEL_MATRIX"),
        (source["source_xml"], "F2-S2 generated XML"), (source["source_receipt"], "F2-S2 GenCase receipt"),
        (source["source_def"], "F2-S2 source Def"), (source["source_motion"], "F2-S2 source motion"),
        (candidate_def, f"F2-S2 {grid} candidate Def"), (candidate_motion, f"F2-S2 {grid} candidate motion"),
        (builder, "F2-S2 ladder builder"), (dispatch, "parent v8 dispatch"), (strict, "parent v8 strict dispatch"),
        (runtime, "parent v8 runtime"), (runtime_v6, "parent v6 runtime"), (runtime_v2, "parent v2 runtime"),
        (config, "official GenCase config"), (template, "GenCase case template"), (PYTHON, "stage2 interpreter"),
    ]
    records = {str(path.resolve()): record(path, label) for path, label in static}
    records[str(GENCASE.resolve())] = official_binary_record(GENCASE)
    input_files = sorted(records)
    output_root = DATA_ROOT / "families/F2" / spec["case_id"] / spec["attempt_id"]
    command = [str(GENCASE), str(candidate_def.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"]
    request = {
        "schema": REQUEST_SCHEMA, "kind": "cpu", "cpu_task_kind": "gencase", "family_id": "F2", "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": spec["case_id"], "attempt_id": spec["attempt_id"], "launch_commit": args.launch_commit, "command": command,
        "cwd": str(candidate_def.parent), "worktree_root": str(repo_root()), "input_files": input_files,
        "input_hashes": {path: records[path]["sha256"] for path in input_files}, "input_records": records,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": spec["wall_seconds"], "max_memory_bytes": 2 * 1024**3,
        "estimated_storage_bytes": spec["storage_bytes"], "estimated_peak_memory_bytes": 1 * 1024**3,
        "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()), "estimated_native_read_bytes": 0, "estimated_bi4_read_bytes": 0, "estimated_hdf5_read_bytes": 0,
        "execution_allowed": True, "launch_disabled": False, "solver_started": False, "gencase_launch": True, "solver_launch": False, "hdf5_read": False, "bi4_read": False,
        "output_root": str(output_root), "output": {"atomic": True, "refuse_overwrite": True, "path": "{attempt_root}/generated"},
        "source_binding": {
            "schema": SCHEMA, "grid": grid, "source_physical_case_id": PHYSICAL_CASE_ID, "source_runtime_case_alias": source["current"].get("runtime_case_alias"),
            "source_generated_xml": records[str(source["source_xml"].resolve())], "source_gencase_receipt": records[str(source["source_receipt"].resolve())],
            "source_def": records[str(source_def.resolve())], "source_motion": records[str(source_motion.resolve())],
            "candidate_def": records[str(candidate_def.resolve())], "candidate_motion": records[str(candidate_motion.resolve())],
            "source_dp_m": SOURCE_DP_M, "candidate_dp_m": spec["dp_m"], "normalized_def_equal_except_dp": True, "motion_byte_identical": True,
            "control_facts": source["source_facts"], "actual_time_window_s": source["current"].get("actual_time_window_s"),
            "known_physical_parameters": source["current"].get("known_numeric_physical_parameters"), "baseline_cfl": source["review"].get("baseline_cfl"), "half_cfl": source["review"].get("proposed_half_cfl"),
            "mass_support_qa_required": True,
            "toolchain": {
                "generator": "GenCase_linux64",
                "generator_bytes": GENCASE_BYTES,
                "generator_sha256": GENCASE_SHA256,
                "generator_role": "GenCase input generator; not the solver binary",
                "config_path": str(config),
                "template_path": str(template),
            },
        },
        "spatial_plan": {"three_grid_set": [GRIDS[name]["dp_m"] for name in GRIDS], "intentional_resolution_parameter": "dp only; h/mass/count are measured from each terminal GenCase", "continuous_geometry_control_frozen": True, "no_mass_rescale": True},
        "resource_guard": {"owner": "stage2-reference-preparation", "runner": str(dispatch), "strict_guard": str(strict), "runtime": str(runtime), "cpu_parent_binding": "required", "gpu": "none", "solver_launch": "forbidden"},
        "qualification_stage": "stage2_f2_s2_source_control_spatial_gencase_only_v3_pending_parent_guard",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "reason": "source/control closure and GenCase preflight only; actual support/mass and observer calibration remain pending"},
        "status": "READY_FOR_PARENT_V8_CPU_GENCASE_REVIEW",
    }
    request["sha256"] = canonical_sha(request)
    return request


def self_test() -> dict[str, Any]:
    source = load_exact_source()
    candidate_root = repo_root() / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/reference/stage2_sentinel_spatial_preflight_inputs_v1/F2_S2"
    for grid, spec in GRIDS.items():
        candidate, motion = candidate_paths(grid, repo_root())
        assert abs(parse_xml_facts(candidate)["definition_dp_m"] - spec["dp_m"]) < 1e-12
        assert normalize_definition(source["source_def"].read_bytes()) == normalize_definition(candidate.read_bytes())
        assert source["source_motion"].read_bytes() == motion.read_bytes()
    assert GENCASE_BYTES == 5_809_384
    assert GENCASE_SHA256 == "a1b6414e0f716669363d1a80a05e133085c04995e15716e3c1f0406e0d023226"
    assert GENCASE.is_file() and (GENCASE.parent / GENCASE_CONFIG_NAME).is_file()
    assert (repo_root() / "doc/xml_format/GenCase_CaseTemplate.xml").is_file()
    return {"status": "PASS", "schema": SCHEMA, "sentinel": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "grids": [GRIDS[name]["dp_m"] for name in GRIDS], "gencase_bytes": GENCASE_BYTES, "source_control_closed": True, "solver_started": False, "bi4_or_h5_read": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True); mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build-requests", action="store_true")
    parser.add_argument("--launch-commit"); parser.add_argument("--output-dir", type=Path, default=stage2_root() / "requests/f2-s2-source-control-ladder-v3")
    parser.add_argument("--plan-output", type=Path, default=stage2_root() / "reference/stage2_f2_s2_source_control_ladder_v3.json")
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    if not args.launch_commit: parser.error("--build-requests requires the parent integration launch commit")
    source = load_exact_source(); args.output_dir = args.output_dir.expanduser().resolve(); args.plan_output = args.plan_output.expanduser().resolve()
    results = []
    for grid in GRIDS:
        request = build_one(grid, args, source)
        output = args.output_dir / f"f2_s2_{grid}_source_control_gencase_v3.json"
        json_new(output, request); results.append({"grid": grid, "dp_m": GRIDS[grid]["dp_m"], "request": str(output), "request_sha256": sha256(output), "launch": "PARENT_ONLY_NOT_STARTED"})
    plan = {"schema": SCHEMA, "status": "PREPARED_SOURCE_BOUND_THREE_GRID_GENCASE_REQUESTS", "sentinel_id": SENTINEL_ID, "physical_case_id": PHYSICAL_CASE_ID, "toolchain": {"generator": "GenCase_linux64", "generator_bytes": GENCASE_BYTES, "generator_sha256": GENCASE_SHA256, "config_path": str(GENCASE.parent / GENCASE_CONFIG_NAME), "template_path": str(repo_root() / "doc/xml_format/GenCase_CaseTemplate.xml")}, "source": {"current_row": source["current"], "review_row": source["review"], "generated_xml": record(source["source_xml"], "source XML"), "gencase_receipt": record(source["source_receipt"], "source receipt"), "source_def": record(source["source_def"], "source Def"), "source_motion": record(source["source_motion"], "source motion"), "control_facts": source["source_facts"]}, "grids": results, "same_cfl_half_cfl_dense": {"baseline_cfl": source["review"].get("baseline_cfl"), "half_cfl": source["review"].get("proposed_half_cfl"), "dense_cadence_s": source["review"].get("proposed_dense_cadence_s"), "status": "PLANNED_NO_SOLVER_OBSERVER_CALIBRATION_REQUIRED"}, "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, "solver_started": False, "bi4_or_h5_read": False}
    json_new(args.plan_output, plan)
    print(json.dumps({"status": plan["status"], "plan": str(args.plan_output), "requests": results, "solver_started": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
