#!/usr/bin/env python3
"""Prepare one F2-S1 inner-box GenCase candidate.

The F2-S1 source boxes remain unchanged.  The current ``dp | bound`` recipe
uses the full cell envelope when a solid box is rasterised; at ``dp=.0088``
the registered phase therefore produces 37 x 27 x (10, 10, 11) particles.
This forward candidate makes the box-limit choice explicit only while the
three fluid boxes are drawn, then restores ``full`` for the bound geometry.
It is a GenCase preflight request only.  It does not run GenCase or read a
native payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
from typing import Any


SCHEMA = "ds02.stage2.f2-s1.source-centered-v4-inner-box.v1"
REQUEST_SCHEMA = "ds02.request.v1"
REPO = Path(__file__).resolve().parents[5]
STAGE2 = REPO / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
REFERENCE = STAGE2 / "reference"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
MAIN = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
GENCASE = Path(
    "/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/"
    "DualSPHysics_v5.4/bin/linux/GenCase_linux64"
)
GENCASE_CONFIG = GENCASE.parent / "DsphConfig.xml"
DISPATCH = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_stage2_dispatch_v8.py"
STRICT = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v8.py"
RUNTIME = MAIN / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v8.py"
TEMPLATE = REPO / "doc/xml_format/GenCase_CaseTemplate.xml"
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
INPUT_ROOT = REFERENCE / "stage2_f2_s1_source_centered_v4_inner_inputs/F2_S1/dp0p0088"
CASE_ID = "F2_S1_SOURCE_CENTERED_V4_INNER_DP0P0088"
PHYSICAL_CASE_ID = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
POINTREF = (0.0013, 0.0, 0.0004)
DP_M = 0.0088
RHO0 = 1000.0
OWNER_MASS_KG = 18.876
FORECAST_COUNT = 27_750
FORECAST_MASS_KG = FORECAST_COUNT * RHO0 * DP_M**3


def regular(path: Path) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError(path)
    return path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with regular(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    path = regular(path)
    stat = path.stat()
    return {
        "path": str(path),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "sha256": sha256(path),
    }


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


def make_candidate() -> Path:
    source = regular(SOURCE_DEF).read_text(encoding="utf-8")
    if "<pointref" in source:
        raise ValueError("frozen source unexpectedly already contains pointref")
    if source.count('<definition dp="0.01">') != 1:
        raise ValueError("expected one frozen dp=0.01 definition")
    if source.count("<setmkfluid mk=") != 3:
        raise ValueError("expected exactly three fluid draw boxes")
    if "<setboxlimitmode" in source:
        raise ValueError("frozen source unexpectedly already contains box-limit mode")

    definition = '<definition dp="0.0088">'
    pointref = '<pointref x="0.0013" y="0.0000" z="0.0004" />'
    derived = source.replace('<definition dp="0.01">', definition + "\n        " + pointref, 1)
    marker = '          <setmkfluid mk="0" />'
    if derived.count(marker) != 1:
        raise ValueError("cannot locate first fluid draw operation")
    derived = derived.replace(marker, '          <setboxlimitmode mode="inner" />\n' + marker, 1)
    # Fluid boxes are the final operations in this source.  Restore the full
    # limit before the main list closes so future edits cannot inherit inner.
    close = "        </mainlist>"
    if derived.count(close) != 1:
        raise ValueError("expected one mainlist close")
    derived = derived.replace(close, '          <setboxlimitmode mode="full" />\n' + close, 1)

    # The only intentional source changes are definition@dp, pointref, and
    # the local box-limit pair.  This is a source audit, not a scientific QA.
    normalized_source = source.replace('dp="0.01"', 'dp="<DP>"', 1)
    normalized_candidate = derived.replace('dp="0.0088"', 'dp="<DP>"', 1)
    normalized_candidate = normalized_candidate.replace("\n        " + pointref, "", 1)
    normalized_candidate = normalized_candidate.replace(
        '          <setboxlimitmode mode="inner" />\n', "", 1
    ).replace('          <setboxlimitmode mode="full" />\n', "", 1)
    if normalized_candidate != normalized_source:
        raise ValueError("candidate changed frozen source beyond dp/pointref/box-limit pair")

    candidate = INPUT_ROOT / f"{CASE_ID}_Def.xml"
    motion = INPUT_ROOT / SOURCE_MOTION.name
    atomic_bytes(candidate, derived.encode("utf-8"))
    atomic_bytes(motion, regular(SOURCE_MOTION).read_bytes())
    return candidate


def prepare_inputs() -> dict[str, Any]:
    candidate = make_candidate()
    motion = INPUT_ROOT / SOURCE_MOTION.name
    manifest = {
        "schema": SCHEMA,
        "status": "PREPARED_F2_S1_INNER_BOX_GENCASE_CANDIDATE",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_def": record(SOURCE_DEF),
        "source_motion": record(SOURCE_MOTION),
        "candidate_def": record(candidate),
        "candidate_motion": record(motion),
        "official_gencase": {
            "binary": record(GENCASE),
            "config": record(GENCASE_CONFIG),
            "xml_template": record(TEMPLATE),
            "template_contract": {
                "setboxlimitmode_values": ["inner", "full"],
                "setshapemode_values": ["actual", "dp", "all", "bound", "fluid", "void", "null"],
                "implementation_source": "GenCase implementation source is not present in this checkout; binary and template are bound.",
            },
        },
        "continuous_owner": {
            "layer_low_m": [[0.05, -0.11, 0.70], [0.05, -0.11, 0.788], [0.05, -0.11, 0.876]],
            "layer_size_m": [0.325, 0.22, 0.088],
            "layer_count": 3,
            "volume_m3": 0.018876,
            "mass_kg": OWNER_MASS_KG,
            "authority": "frozen CURRENT source drawboxes; unchanged by candidate",
        },
        "representation": {
            "dp_m": DP_M,
            "pointref_m": list(POINTREF),
            "fluid_box_limit_mode": "inner",
            "bound_box_limit_mode_before_and_after_fluid": "full",
            "drawboxes_unchanged": True,
            "motion_unchanged": True,
            "execution_controls_unchanged": True,
            "mass_rescale": False,
        },
        "forecast_only": {
            "axis_counts": [37, 25, 10],
            "per_layer_count": 9250,
            "fluid_count": FORECAST_COUNT,
            "massfluid_kg": RHO0 * DP_M**3,
            "sample_mass_kg": FORECAST_MASS_KG,
            "relative_to_continuous_owner_percent": 100.0 * (FORECAST_MASS_KG / OWNER_MASS_KG - 1.0),
            "basis": "full-mode VTK lattice rule plus inner-box arithmetic; GenCase XML/receipt authoritative",
            "status": "PREDICTED_NOT_ACTUAL",
        },
        "quality_gates": {
            "preferred_whole_initial_mass_fraction": 0.01,
            "marginal_whole_initial_mass_fraction": 0.02,
            "no_mass_rescale": True,
            "no_geometry_or_control_widening": True,
            "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        },
    }
    atomic_json(REFERENCE / "stage2_f2_s1_source_centered_v4_inner_manifest_v1.json", manifest)
    return manifest


def build_request(launch_commit: str) -> dict[str, Any]:
    manifest_path = REFERENCE / "stage2_f2_s1_source_centered_v4_inner_manifest_v1.json"
    if not manifest_path.is_file():
        prepare_inputs()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    candidate = Path(manifest["candidate_def"]["path"])
    motion = Path(manifest["candidate_motion"]["path"])
    request_dir = STAGE2 / "requests/stage2-f2-s1-source-centered-v4-inner-v1"
    request_dir.mkdir(parents=True, exist_ok=True)
    attempt_id = "f2-s1-source-centered-v4-inner-dp0088-gencase-root-forward-001"
    output_root = DATA_ROOT / "families/F2" / CASE_ID / attempt_id
    static_paths = [
        Path(__file__), manifest_path, candidate, motion, SOURCE_DEF, SOURCE_MOTION,
        GENCASE, GENCASE_CONFIG, TEMPLATE, DISPATCH, STRICT, RUNTIME,
    ]
    static_paths = list(dict.fromkeys(regular(path) for path in static_paths))
    records = {str(path): record(path) for path in static_paths}
    request = {
        "schema": REQUEST_SCHEMA,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "family_id": "F2",
        "sentinel_id": "F2-S1",
        "physical_case_id": PHYSICAL_CASE_ID,
        "case_id": CASE_ID,
        "attempt_id": attempt_id,
        "launch_commit": launch_commit,
        "command": [str(GENCASE), str(candidate.with_suffix("")), "{attempt_root}/generated", "-save:all", "-threads:1"],
        "cwd": str(candidate.parent),
        "worktree_root": str(REPO),
        "input_files": list(records),
        "input_hashes": {path: item["sha256"] for path, item in records.items()},
        "input_records": records,
        "deferred_input_files": [],
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_input_read_bytes": sum(int(item["bytes"]) for item in records.values()),
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
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
            "schema": "ds02.stage2.f2-s1.source-centered-v4-inner-binding.v1",
            "source_def": records[str(SOURCE_DEF)],
            "source_motion": records[str(SOURCE_MOTION)],
            "candidate_def": records[str(candidate)],
            "candidate_motion": records[str(motion)],
            "continuous_owner": manifest["continuous_owner"],
            "representation": manifest["representation"],
            "forecast_mass_audit": manifest["forecast_only"],
            "controls_and_drawboxes_frozen": True,
            "post_gencase_required": ["generated.xml", "generated.bi4", "execution-receipt.json", "generated_Fluid.vtk if present"],
            "source_relative_mass_diagnostic": {"status": "NOT_USED_AS_CONTINUUM_TRUTH", "old_dp00855": "immutable diagnostic only"},
        },
        "resource_guard": {
            "owner": "stage2-reference-preparation",
            "runner": str(DISPATCH),
            "strict_guard": str(STRICT),
            "runtime": str(RUNTIME),
            "cpu_parent_binding": "required",
            "gpu": "none",
            "solver_launch": "forbidden",
            "hdf5_read": "forbidden",
            "source_output_protection": "new attempt tree only; frozen source immutable",
        },
        "qualification_stage": "stage2_f2_s1_v4_inner_gencase_preflight_pending_actual_xml_and_initial_native_qa",
        "scientific_qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    path = request_dir / "f2_s1_source_centered_v4_inner_dp0088_gencase.json"
    atomic_json(path, request)
    report = {"schema": SCHEMA, "status": "PREPARED_NO_GENCАSE_STARTED", "request": str(path), "launch_commit": launch_commit}
    atomic_json(REFERENCE / "stage2_f2_s1_source_centered_v4_inner_request_v1.json", report)
    return report


def self_test() -> dict[str, Any]:
    assert abs(FORECAST_MASS_KG / OWNER_MASS_KG - 1.0) < 0.01
    assert FORECAST_COUNT == 3 * 37 * 25 * 10
    assert SOURCE_DEF.is_file() and SOURCE_MOTION.is_file()
    assert TEMPLATE.is_file()
    return {
        "status": "PASS",
        "gencase_started": False,
        "native_payload_read": False,
        "forecast_count": FORECAST_COUNT,
        "forecast_relative_mass_percent": 100.0 * (FORECAST_MASS_KG / OWNER_MASS_KG - 1.0),
        "qualification": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--prepare-inputs", action="store_true")
    parser.add_argument("--build-request", action="store_true")
    parser.add_argument("--launch-commit")
    args = parser.parse_args()
    selected = [args.self_test, args.prepare_inputs, args.build_request]
    if sum(selected) != 1:
        parser.error("choose exactly one mode")
    if args.self_test:
        value = self_test()
    elif args.prepare_inputs:
        value = prepare_inputs()
    else:
        if not args.launch_commit:
            parser.error("--build-request requires --launch-commit")
        value = build_request(args.launch_commit)
    print(json.dumps(value if args.self_test else {"status": "PREPARED", "result": value.get("request", value.get("candidate_def"))}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
