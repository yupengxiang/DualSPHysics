#!/usr/bin/env python3
"""Prepare F2 owner-centered, phase-registered GenCase preflights.

The current F2 source samples 21.114 kg from three owner boxes of
0.325 x 0.22 x 0.088 m (18.876 kg at rho0=1000).  This forward builder keeps
each continuous owner box and all controls fixed, registers the proposed
count-commensurate ladder (0.0088, 0.0044, 0.0022 m), and emits an
owner-centred parity phase for ``pointref``.  The drawbox size is deliberately left unchanged:
the generated receipt, not the arithmetic registration, determines the actual
particle count and sample mass.  No mass is rescaled and no solver or native
payload is started here.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
LAB_ROOT = SCRIPT_DIR.parent
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-02"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_DEF = DATA_ROOT / (
    "families/F2/F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801/"
    "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_"
    "DP010_SPATIAL_REFERENCE_SAVE010_Def.xml"
)
SOURCE_MOTION = DATA_ROOT / (
    "families/F2/F2_FIRST48_REMAINING24_SOURCE_ROOT801/"
    "root-stage1-f2-first48-remaining24-registered-source-generation-root801/"
    "source/source/F2_STAGE1_FIRST48_EXPANSION_RX056_RY014_FILL080_ROT090_"
    "DP010_SPATIAL_REFERENCE_SAVE010_motion.dat"
)
OFFICIAL_ROOT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux")
GENCASE = OFFICIAL_ROOT / "GenCase_linux64"
DISPATCH_V8 = SCRIPT_DIR / "ds_data02_stage2_dispatch_v8.py"
STRICT_V8 = SCRIPT_DIR / "ds_data02_strict_dispatch_v8.py"
RUNTIME_V8 = SCRIPT_DIR / "ds_data02_runtime_v8.py"
RUNTIME_V6 = SCRIPT_DIR / "ds_data02_runtime_v6.py"
LEDGER = DATA_ROOT / "runtime/resource-ledger.json"
OUTPUT_ROOT = CAMPAIGN_ROOT / "stage2/reference/stage2_f2_owner_centered_gencase_v3"
REQUEST_ROOT = CAMPAIGN_ROOT / "stage2/requests/stage2-f2-owner-centered-gencase-v3"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
OWNER_LOW = (0.05, -0.11, 0.70)
OWNER_SIZE = (0.325, 0.22, 0.264)
OWNER_LAYER_SIZE = (0.325, 0.22, 0.088)
LAYER_SIZE_Z = 0.088
RHO0 = 1000.0
DP_LADDER = (0.0088, 0.0044, 0.0022)


class BuildError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def canonical_sha(value: dict[str, Any]) -> str:
    body = {k: v for k, v in value.items() if k != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                      ensure_ascii=True, default=str).encode()).hexdigest()


def git_commit() -> str:
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=SCRIPT_DIR.parent.parent,
                          check=True, capture_output=True, text=True).stdout.strip()


def fmt(value: float) -> str:
    return format(float(value), ".12g")


def registered_count(size: float, dp: float) -> int:
    """Arithmetic registration only; the parent GenCase receipt is authoritative."""
    # Exact decimal ratios such as .22/.0088 can be one ulp above their
    # integer in binary floating point.  The small subtraction stabilizes that
    # case without changing a genuinely noninteger ratio.
    return int(math.ceil(size / dp - 1e-10))


def _find_child(parent: ET.Element, tag: str) -> ET.Element:
    for child in parent:
        if child.tag == tag:
            return child
    raise BuildError(f"missing XML element: {tag}")


def phase_pointref(low: tuple[float, float, float], size: tuple[float, float, float], dp: float) -> tuple[float, float, float]:
    """Choose the phase that centers the registered lattice in the owner box.

    For an axis with an even number of cells the center lies halfway between
    cell centers; for an odd count it lies on a cell center.  The returned
    phase is the pointref coordinate modulo dp, normalized to [0, dp).  This
    is an arithmetic preregistration only; GenCase output remains authoritative.
    """
    values: list[float] = []
    for axis_low, axis_size in zip(low, size):
        count = registered_count(axis_size, dp)
        center = axis_low + axis_size / 2.0
        phase = (center - (dp / 2.0 if count % 2 == 0 else 0.0)) % dp
        values.append(phase)
    return tuple(values)


def make_def(dp: float, out: Path) -> dict[str, Any]:
    if not SOURCE_DEF.is_file() or not SOURCE_MOTION.is_file():
        raise BuildError("F2 exact source Def/motion is unavailable")
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(SOURCE_DEF.read_bytes(), parser=parser)
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise BuildError("F2 source lacks geometry definition")
    definition.set("dp", fmt(dp))
    pointref = definition.find("pointref")
    if pointref is None:
        pointref = ET.Element("pointref")
        definition.insert(0, pointref)
    phase = phase_pointref(OWNER_LOW, OWNER_LAYER_SIZE, dp)
    for axis, value in zip("xyz", phase):
        pointref.set(axis, fmt(value))
    mainlist = root.find("./casedef/geometry/commands/mainlist")
    if mainlist is None:
        raise BuildError("F2 source lacks geometry command list")
    mode_nodes = [node for node in mainlist if node.tag == "setshapemode"]
    if len(mode_nodes) != 1:
        raise BuildError(f"expected one setshapemode, found {len(mode_nodes)}")
    mode_nodes[0].text = "dp | actual | bound"
    active_fluid = False
    fluid_blocks = []
    for node in mainlist:
        if node.tag == "setmkfluid":
            active_fluid = True
            continue
        if not active_fluid or node.tag != "drawbox":
            continue
        point = node.find("point")
        size = node.find("size")
        if point is None or size is None:
            raise BuildError("fluid drawbox lacks point/size")
        old_size = tuple(float(size.get(axis)) for axis in "xyz")
        if any(v < dp for v in old_size):
            raise BuildError(f"dp={dp} is not smaller than every fluid layer extent")
        old_point = tuple(float(point.get(axis)) for axis in "xyz")
        # Keep the owner drawbox coordinates exact. ``pointref`` controls the
        # particle-centre phase; moving the drawbox itself would change the
        # continuous region and would make the candidate a different case.
        new_point = old_point
        # Keep the continuous owner box exact.  Shrinking by dp would alter
        # the source support and would not implement the registered
        # ceil(size/dp) count ladder (37/25/10, 74/50/20, 148/100/40).
        new_size = old_size
        for axis, value in zip("xyz", new_point):
            point.set(axis, fmt(value))
        for axis, value in zip("xyz", new_size):
            size.set(axis, fmt(value))
        fluid_blocks.append({"mk": int(mainlist[list(mainlist).index(node)-1].get("mk", -1)),
                             "point_before_m": list(old_point), "point_after_m": list(new_point),
                             "size_before_m": list(old_size), "size_after_m": list(new_size),
                             "registered_counts_xyz": [registered_count(v, dp) for v in old_size],
                             "registered_coverage_m": [registered_count(v, dp) * dp for v in old_size]})
        active_fluid = False
    if len(fluid_blocks) != 3:
        raise BuildError(f"expected exactly three fluid blocks, found {len(fluid_blocks)}")
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        raise BuildError(f"refusing existing Def: {out}")
    ET.indent(root, space="  ")
    tree = ET.ElementTree(root)
    tree.write(out, encoding="utf-8", xml_declaration=True)
    return {
        "dp_m": dp, "pointref_m": list(phase), "fluid_blocks": fluid_blocks,
        "registered_count_basis": "ceil(owner_box_size/dp - 1e-10) with owner-centred parity phase; actual GenCase receipt authoritative",
        "phase_basis": "owner box centre; even count uses centre-dp/2, odd count uses centre; phase modulo dp",
        "source_def": str(SOURCE_DEF), "source_def_sha256": sha256_file(SOURCE_DEF),
        "output_def": str(out), "output_def_sha256": sha256_file(out),
    }


def _parent_limits() -> dict[str, Any]:
    value = json.loads(LEDGER.read_text(encoding="utf-8"))
    limits = value.get("limits", {})
    required = ("cpu_core_seconds", "gpu_seconds", "new_storage_bytes", "qualification_attempts",
                "production_attempts", "home_min_free_bytes", "home_path", "storage_policy")
    if any(k not in limits for k in required):
        raise BuildError("parent ledger lacks required limits")
    return {"ledger_path": str(LEDGER), "data_root": str(DATA_ROOT),
            "campaign_id": value.get("campaign_id"), "deadline_utc": value.get("deadline_utc"),
            "ledger_reset": False, "no_new_data_root": True,
            "limits": {k: limits[k] for k in required}}


def make_request(dp: float, def_path: Path, motion_path: Path, manifest: dict[str, Any],
                 launch_commit: str, out: Path) -> dict[str, Any]:
    token = f"DP{dp:.4f}".replace(".", "p")
    case = f"F2_S1_OWNER_CENTERED_{token}_GENCASE"
    attempt = f"f2-s1-owner-centered-phase-{token.lower()}-gencase-v3-root-001"
    # The manifest is provenance only.  It is finalized after all requests are
    # written, so placing it in the executable input hash would create a
    # self-invalidating request.  Candidate Def/motion and exact source/control
    # files are the complete GenCase input closure.
    inputs = [def_path, motion_path, SOURCE_DEF, SOURCE_MOTION, DISPATCH_V8, STRICT_V8,
              RUNTIME_V8, RUNTIME_V6]
    hashes = {str(p.resolve()): sha256_file(p) for p in inputs}
    return {
        "schema": "ds02.request.v1", "kind": "cpu", "cpu_task_kind": "gencase",
        "family_id": "F2", "sentinel_id": "F2-S1",
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "case_id": case, "attempt_id": attempt, "launch_commit": launch_commit,
        "command": [str(GENCASE), str(def_path), "{attempt_root}/generated", "-save:all"],
        "cwd": str(def_path.parent), "worktree_root": str(SCRIPT_DIR.parent.parent),
        "input_files": [str(p.resolve()) for p in inputs], "input_hashes": hashes,
        "cpu_threads": 1, "omp_threads": 1, "max_wall_seconds": 600,
        "estimated_input_read_bytes": sum(p.stat().st_size for p in inputs),
        "estimated_storage_bytes": 512 * 1024**2,
        "estimated_peak_memory_bytes": 2 * 1024**3,
        "estimated_cpu_core_hours": 0.2,
        "execution_allowed": True, "launch_disabled": False,
        "solver_started": False, "solver_launch": False, "gencase_launch": True,
        "hdf5_read": False, "bi4_read": False,
        "resource_guard": {
            "owner": "stage2-reference-preparation", "runner": str(DISPATCH_V8),
            "strict_guard": str(STRICT_V8), "runtime": str(RUNTIME_V8),
            "runtime_v6_dependency": str(RUNTIME_V6), "launch_commit": launch_commit,
            "gpu": "none", "gpu_uuid_lease": "none", "solver_launch": "forbidden",
            "hdf5_read": "forbidden", "source_output_protection": "new GenCase attempt only",
        },
        "parent_resource_binding": _parent_limits(),
        "source_geometry_contract": {
            "owner_continuous_low_m": list(OWNER_LOW),
            "owner_continuous_size_m": list(OWNER_SIZE),
            "owner_layer_size_m": list(OWNER_LAYER_SIZE),
            "owner_continuous_volume_m3": 0.018876,
            "owner_continuous_mass_kg_at_rho0": 18.876,
            "source_discrete_sample_mass_kg": 21.114,
            "source_discrete_mass_role": "diagnostic only; never a rescale target",
            "representation": "owner-centred parity phase pointref; setshapemode=dp | actual | bound; each fluid box keeps exact owner point/size and only particle-centre phase changes",
            "registered_lattice": {
                "layer_size_m": list(OWNER_LAYER_SIZE),
                "phase_rule": "owner box centre; even count centre-dp/2, odd count centre; phase modulo dp",
                "layers": 3,
                "count_rule": "ceil(layer_size/dp - 1e-10) per axis; arithmetic registration only",
                "coverage_rule": "registered_count*dp; actual GenCase receipt is authoritative",
                "expected_counts_per_layer": [registered_count(v, dp) for v in OWNER_LAYER_SIZE],
                "expected_coverage_m_per_layer": [registered_count(v, dp) * dp for v in OWNER_LAYER_SIZE],
                "actual_counts": "UNKNOWN_UNTIL_PARENT_GENCASE_RECEIPT",
            },
            "fixed_geometry_control": True,
            "mass_gate": {"preferred_absolute_fraction": 0.01, "hard_upper_fraction": 0.02,
                          "denominator": "continuous owner 18.876 kg",
                          "actual_counts_and_sample_mass": "UNKNOWN until GenCase receipt"},
        },
        "source_binding": {
            "source_def": str(SOURCE_DEF), "source_def_sha256": sha256_file(SOURCE_DEF),
            "source_motion": str(SOURCE_MOTION), "source_motion_sha256": sha256_file(SOURCE_MOTION),
            "candidate_def": str(def_path), "candidate_def_sha256": sha256_file(def_path),
            "candidate_motion": str(motion_path), "candidate_motion_sha256": sha256_file(motion_path),
            "only_representation_changes": ["definition.dp", "definition.pointref", "setshapemode"],
            "fluid_drawbox_point_size_unchanged": True,
            "boundary_motion_materials_unchanged": True,
        },
        "qualification": dict(UNKNOWN),
        "mass_result": "UNKNOWN_UNTIL_PARENT_GENCASE_RECEIPT",
        "manifest_path": str(Path(manifest["manifest_path"]).resolve()),
    }


def build(output_dir: Path, request_dir: Path, *, launch_commit: str | None = None,
          dps: tuple[float, ...] = DP_LADDER) -> dict[str, Any]:
    output_dir = output_dir.expanduser().resolve()
    request_dir = request_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    request_dir.mkdir(parents=True, exist_ok=True)
    launch_commit = launch_commit or git_commit()
    if not SOURCE_DEF.is_file() or not SOURCE_MOTION.is_file():
        raise BuildError("exact F2 source inputs unavailable")
    manifest: dict[str, Any] = {
        "schema": "ds02.stage2.f2.owner-centered-gencase-manifest.v3",
        "status": "READY_PARENT_CPU_V8_Gencase_ONLY", "launch_commit": launch_commit,
        "physical_case_id": "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090",
        "source_def": str(SOURCE_DEF), "source_def_sha256": sha256_file(SOURCE_DEF),
        "source_motion": str(SOURCE_MOTION), "source_motion_sha256": sha256_file(SOURCE_MOTION),
        "owner_continuous_size_m": list(OWNER_SIZE), "owner_continuous_mass_kg": 18.876,
        "owner_layer_size_m": list(OWNER_LAYER_SIZE),
        "registered_ladder_m": list(DP_LADDER),
        "registered_count_rule": "ceil(layer_size/dp - 1e-10) per axis; arithmetic only until actual receipt",
        "registered_phase_expectations_m": {
            fmt(dp): list(phase_pointref(OWNER_LOW, OWNER_LAYER_SIZE, dp)) for dp in DP_LADDER
        },
        "registered_count_expectations": {
            fmt(dp): [registered_count(v, dp) for v in OWNER_LAYER_SIZE] for dp in DP_LADDER
        },
        "registered_coverage_expectations_m": {
            fmt(dp): [registered_count(v, dp) * dp for v in OWNER_LAYER_SIZE] for dp in DP_LADDER
        },
        "source_discrete_sample_mass_kg": 21.114,
        "no_mass_rescale": True, "no_geometry_control_change": True,
        "rungs": [],
    }
    manifest_path = output_dir / "f2_s1_owner_centered_gencase_manifest_v3.json"
    manifest["manifest_path"] = str(manifest_path)
    for dp in dps:
        token = f"DP{dp:.4f}".replace(".", "p")
        stem = f"F2_S1_OWNER_CENTERED_{token}_Def.xml"
        def_path = output_dir / token / stem
        info = make_def(float(dp), def_path)
        motion_path = def_path.parent / SOURCE_MOTION.name
        if motion_path.exists():
            raise BuildError(f"refusing existing motion copy: {motion_path}")
        shutil.copyfile(SOURCE_MOTION, motion_path)
        info["candidate_motion"] = str(motion_path)
        info["candidate_motion_sha256"] = sha256_file(motion_path)
        info["expected_owner_mass_kg"] = 18.876
        info["preferred_gate"] = "abs(sample_mass-owner_mass)/owner_mass <= 0.01"
        info["hard_upper_gate"] = "abs(sample_mass-owner_mass)/owner_mass <= 0.02"
        manifest["rungs"].append(info)
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    requests = []
    for info in manifest["rungs"]:
        def_path = Path(info["output_def"])
        motion_path = Path(info["candidate_motion"])
        req = make_request(float(info["dp_m"]), def_path, motion_path, manifest, launch_commit,
                           request_dir / f"{def_path.stem}.json")
        out = request_dir / f"{def_path.stem}.json"
        out.write_text(json.dumps(req, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        requests.append(str(out))
    manifest["requests"] = requests
    manifest["request_count"] = len(requests)
    manifest["sha256"] = canonical_sha(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def self_test() -> None:
    # A small manufactured copy checks the finite, owner-centered XML rewrite
    # without touching the real source or invoking GenCase.
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ds02-f2-owner-selftest-") as td:
        root = Path(td)
        old_def, old_motion = SOURCE_DEF, SOURCE_MOTION
        try:
            globals()["SOURCE_DEF"] = root / "source.xml"
            globals()["SOURCE_MOTION"] = root / "motion.dat"
            shutil.copyfile(old_def, SOURCE_DEF)
            SOURCE_MOTION.write_bytes(b"0 0 0\n")
            result = make_def(0.0044, root / "candidate.xml")
            assert result["dp_m"] == 0.0044 and len(result["fluid_blocks"]) == 3
            assert result["pointref_m"] != [0.0022, 0.0022, 0.0022]
            assert "dp | actual | bound" in (root / "candidate.xml").read_text()
            print("PASS F2 owner-centered XML self-test")
        finally:
            globals()["SOURCE_DEF"] = old_def
            globals()["SOURCE_MOTION"] = old_motion


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--output-dir", type=Path, default=OUTPUT_ROOT)
    ap.add_argument("--request-dir", type=Path, default=REQUEST_ROOT)
    ap.add_argument("--launch-commit")
    ap.add_argument("--self-test", action="store_true")
    args = ap.parse_args(argv)
    try:
        if args.self_test:
            self_test()
            return 0
        result = build(args.output_dir, args.request_dir, launch_commit=args.launch_commit)
        print(json.dumps({"status": result["status"], "request_count": result["request_count"],
                          "manifest": result["manifest_path"]}, indent=2))
        return 0
    except (BuildError, OSError, subprocess.CalledProcessError, ET.ParseError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
