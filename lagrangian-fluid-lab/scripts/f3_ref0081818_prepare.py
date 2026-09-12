"""Prepare a prospective exact-tiling F3 reference branch without CFD.

The failed revision075 gate is immutable.  This module creates a *proposal
only* branch whose new coarse reference is ``0.09/11`` metres.  That value
tiles the fixed 0.9 x 0.18 x 0.09 m fluid volume exactly (110 x 22 x 11
particles), unlike 0.008 m.  The module may invoke the vendored GenCase
binary for input preparation and structural checks, but it has no solver
runner and never spends a qualification attempt.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET

import numpy as np

try:
    from scripts import f3_nopen_qualification as native
    from scripts import l1r_q2_mdbc_bridge as q2
    from scripts.l1r_continuation_evidence import LAB, OUT, write
    from scripts.l1r_input_preflight import check_input
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import f3_nopen_qualification as native
    from scripts import l1r_q2_mdbc_bridge as q2
    from scripts.l1r_continuation_evidence import LAB, OUT, write
    from scripts.l1r_input_preflight import check_input


DP = 0.09 / 11.0
DP_LABEL = "0p008181818181818"
RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075_ref0081818"
MANIFEST = LAB / "diagnostics/f3-audit/F3-075-REF0081818-MANIFEST.json"
AUTHORIZATION = OUT / "F3-075-REF0081818-AUTHORIZATION.json"
TARGET_ROOT = LAB / "campaigns/l1-resume/artifacts/f3-ref0081818"
GENCASE = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
SOURCE_RECORD = OUT / "F3_REV075_R075-ENDPOINT-LOW-0075-PREPARED.json"
SOURCE_PREFIX = LAB / "campaigns/l1-resume/artifacts/f3-revision075/F3_REV075_R075-ENDPOINT-LOW-0075/F3_CELL3_plain_0p0075"
VENDOR_DRIVE = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"
FLUID_DIMS = (0.9, 0.18, 0.09)
LOW = (-0.45, -0.09, 0.0)

CELLS = (
    ("R0081818-NOMINAL", 1.0, "new_coarse_reference"),
    ("R0081818-ENDPOINT-LOW", 0.9, "new_low_endpoint_reference"),
    ("R0081818-ENDPOINT-HIGH", 1.1, "new_high_endpoint_reference"),
)

OLD_REPORT_SHA256 = "887035e274d17b56f3c0ab4b749ca6988069b42060ee047b116224a8b8f38af6"
EXPECTED_OLD_FAILURES = {
    ("endpoint_low", ("R075-ENDPOINT-LOW-010", "R075-ENDPOINT-LOW-006")),
    ("endpoint_high", ("R075-ENDPOINT-HIGH-010", "R075-ENDPOINT-HIGH-006")),
}

# These digests are the immutable HDF5 identities recorded by the completed
# revision075 audits.  The preparation step checks the audit claims against
# this allow-list; a later authorized scoring run rechecks the actual files.
EXPECTED_HDF5_SHA256 = {
    "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen": "fb304e0bc8e5d7f51eaab0af0d8dba8c928b8146e0bf5776002f83012e4480c4",
    "R075-ZERO": "8231d15f3cf69e667e7cf3e798388fb7433ff0a3df69b696a86a27a43b725df3",
    "R075-TIME": "2766fd135f378529508d0d97b019def374d9e62da4a6336f41ae7dfa70cb90af",
    "R075-OUTPUT": "571ddf4ba1878730ff80d20bca49361a7f3fff841f3ac618dd983894364c7e63",
    "R075-ENDPOINT-LOW-0075": "83b065cf15b9ef15fdfa71ac6e6d6239337e22a3794812a173eee1b2de3528c7",
    "R075-ENDPOINT-LOW-006": "1d0a640e1abb30a46cac351c77ea4c7e3dab32de7f422dad917d22f9192aac71",
    "R075-ENDPOINT-HIGH-0075": "fdc55cf1f802f3224af2d37032b0ea7b617cd4f1b3884e69edcb0b856e20076d",
    "R075-ENDPOINT-HIGH-006": "57e6ee9afe6407d07b451f3c7b07b1e12470d36ba52a181bce0716f772cb7815",
    "R075-INTERNAL-0075": "8be6cc1d0d41d9e2c5cd19905303c473820cd51af38efc309f2b28856a8c2662",
    "R075-INTERNAL-006": "828dbba90f8fcb9e471a5cc2616d1687820a87c96ced5df8623a9b9fd1381fd7",
}


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


REUSED_CASES = {
    "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen":
        "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
    "R075-ZERO": "F3_REV075_R075-ZERO",
    "R075-TIME": "F3_REV075_R075-TIME",
    "R075-OUTPUT": "F3_REV075_R075-OUTPUT",
    "R075-ENDPOINT-LOW-0075": "F3_REV075_R075-ENDPOINT-LOW-0075",
    "R075-ENDPOINT-LOW-006": "F3_REV075_R075-ENDPOINT-LOW-006",
    "R075-ENDPOINT-HIGH-0075": "F3_REV075_R075-ENDPOINT-HIGH-0075",
    "R075-ENDPOINT-HIGH-006": "F3_REV075_R075-ENDPOINT-HIGH-006",
    "R075-INTERNAL-0075": "F3_REV075_R075-INTERNAL-0075",
    "R075-INTERNAL-006": "F3_REV075_R075-INTERNAL-006",
}


def _evidence_binding(label: str) -> dict:
    """Bind reusable evidence without rehashing multi-gigabyte HDF5 files."""
    case_id = REUSED_CASES[label]
    record_path = OUT / f"{case_id}-PREPARED.json"
    audit_path = OUT / f"{case_id}-AUDIT.json"
    solver_path = OUT / f"{case_id}-SOLVER.json"
    preflight_path = OUT / f"{case_id}-INPUT-PREFLIGHT.json"
    for path in (record_path, audit_path, solver_path, preflight_path):
        if not path.is_file():
            raise ValueError(f"reusable evidence is missing: {path}")
    record = _read(record_path)
    audit = _read(audit_path)
    solver = _read(solver_path)
    if record.get("id") != case_id or record.get("case_id") != case_id:
        raise ValueError(f"reusable evidence record identity mismatch: {case_id}")
    if record.get("family") != "F3" or record.get("qualified") is not False:
        raise ValueError(f"reusable evidence record is not an unqualified F3 result: {case_id}")
    expected_recipe = (
        "F3_CELL3_NS_visco1_native_nopen"
        if label.startswith("F3_CELL3_LONG_")
        else "F3_CELL3_NS_visco1_native_nopen_revision075"
    )
    if record.get("recipe_id") != expected_recipe:
        raise ValueError(f"reusable evidence recipe mismatch: {case_id}")
    if audit.get("case_id") != case_id or audit.get("audit_status") != "pass_diagnostic":
        raise ValueError(f"reusable evidence audit is not a passing diagnostic: {case_id}")
    if solver.get("status") != "completed" or solver.get("resource_category") != "qualification":
        raise ValueError(f"reusable evidence solver is not a completed qualification: {case_id}")
    source_record = solver.get("source_record")
    if not isinstance(source_record, dict) or source_record.get("id") != case_id:
        raise ValueError(f"reusable evidence solver source mismatch: {case_id}")
    preflight = _read(preflight_path)
    if preflight.get("status") != "passed":
        raise ValueError(f"reusable evidence preflight is not passed: {case_id}")
    expected_hdf5_sha256 = EXPECTED_HDF5_SHA256.get(label)
    if audit.get("hdf5_sha256") != expected_hdf5_sha256:
        raise ValueError(f"reusable evidence HDF5 identity mismatch: {case_id}")
    hdf5_path = LAB / audit["hdf5"]
    if not hdf5_path.is_file() or not audit.get("hdf5_sha256"):
        raise ValueError(f"reusable evidence has no bound HDF5: {case_id}")
    paths = [record_path, audit_path, solver_path, preflight_path]
    normalization = OUT / f"{case_id}-NORMALIZATION.json"
    if normalization.is_file():
        paths.append(normalization)
    prefix = LAB / record["generated_prefix"]
    for name in record.get("input_assets", {}):
        paths.append(prefix.parent / name)
    attempt = Path(solver.get("attempt_directory", ""))
    for name in ("Run.out", "RunPARTs.csv"):
        if (attempt / name).is_file():
            paths.append(attempt / name)
    files = {
        _relative(path): q2.sha256(path)
        for path in paths if path.is_file()
    }
    files[_relative(hdf5_path)] = audit["hdf5_sha256"]
    return {
        "label": label,
        "case_id": case_id,
        "record_sha256": q2.sha256(record_path),
        "audit_sha256": q2.sha256(audit_path),
        "solver_sha256": q2.sha256(solver_path),
        "preflight_sha256": q2.sha256(preflight_path),
        "hdf5_path": _relative(hdf5_path),
        "hdf5_sha256": audit["hdf5_sha256"],
        "files": files,
    }


def _manifest() -> dict:
    report = OUT / "F3-075-REVISION-SCORES-887035e274d17b56f3c0ab4b749ca6988069b42060ee047b116224a8b8f38af6.json"
    if q2.sha256(report) != OLD_REPORT_SHA256:
        raise ValueError("immutable revision075 failure report digest changed")
    old_report = _read(report)
    if old_report.get("status") != "failed":
        raise ValueError("revision075 failure report no longer records failed status")
    observed_failures = {
        (panel.get("kind"), tuple(panel.get("case_ids", [])))
        for panel in old_report.get("panels", [])
        if panel.get("status") == "failed"
    }
    if observed_failures != EXPECTED_OLD_FAILURES:
        raise ValueError("revision075 direct endpoint failure set changed")
    manifest = {
        "schema": "f3.revision075.ref0081818.matrix_manifest.v1",
        "status": "proposed_preparation_only",
        "launch_allowed": False,
        "recipe_id": RECIPE,
        "production_resolution_m": 0.0075,
        "reference_resolutions_m": [DP, 0.006],
        "retained_historical_resolution_m": 0.01,
        "fixed_recipe": {
            "solver_mode": "-mdbc_noslip:1",
            "boundary": 2,
            "slip_mode": 2,
            "no_penetration": 1,
            "visco": 0.05,
            "visco_bound_factor": 1,
            "shifting": 0,
            "time_window_s": [0.0, 8.35],
            "output_interval_s": 0.01,
            "coordinate_frame": "fixed tank computational coordinates with prescribed acceleration; no inertial-world trajectory claim",
            "scoring": "frozen v2 full-window macro metrics plus unchanged hard particle audit; all endpoint pair combinations",
        },
        "exact_tiling": {
            "dp_m": DP,
            "fluid_shape": [110, 22, 11],
            "fluid_particles": 110 * 22 * 11,
            "target_mass_kg": 14.58,
            "reason": "dp=0.09/11 exactly tiles all three fixed fluid dimensions",
        },
        "old_v1_status": {
            "status": "failed_immutable",
            "report": "campaigns/l1-resume/continuation/F3-075-REVISION-SCORES-887035e274d17b56f3c0ab4b749ca6988069b42060ee047b116224a8b8f38af6.json",
            "report_sha256": q2.sha256(report),
            "direct_endpoint_failures": [".010↔.006 at amplitude 0.9", ".010↔.006 at amplitude 1.1"],
        },
        "new_v2_status": "not_scored_preparation_only",
        "cells": [
            {"cell_id": case_id, "dp_m": DP, "amplitude": amplitude, "role": role,
             "new_solver_attempt": True}
            for case_id, amplitude, role in CELLS
        ],
        "reused_hash_bound_evidence": [
            "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
            "R075-ZERO", "R075-TIME", "R075-OUTPUT",
            "R075-ENDPOINT-LOW-0075", "R075-ENDPOINT-LOW-006",
            "R075-ENDPOINT-HIGH-0075", "R075-ENDPOINT-HIGH-006",
            "R075-INTERNAL-0075", "R075-INTERNAL-006",
        ],
        "reused_evidence_bindings": {
            label: _evidence_binding(label)
            for label in REUSED_CASES
        },
        "resource_policy": {
            "qualification_attempts_required": 3,
            "launch_requires_new_authorization": True,
            "development_launch_allowed": False,
            "material_production_allowed": False,
            "training_launch_allowed": False,
            "allowed_gpu_indices": [4, 5, 6, 7],
            "protected_gpu_indices": [0, 1, 2, 3],
            "max_concurrent_cfd_solvers": 1,
            "cpu_analysis_slots": 2,
            "authorization_path": _relative(AUTHORIZATION),
            "approved_resource_caps": {
                "cpu_core_hours": 896,
                "gpu_hours": 64,
                "qualification_attempts": 80,
            },
        },
        "required_before_launch": [
            "owner approval of this prospective branch",
            "new authorization record bound to this manifest and preparation summary",
            "R0081818-NOMINAL hard-audit canary before endpoint launches",
        ],
    }
    return manifest


def _rewrite_definition(source: Path, target: Path) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    definition = root.find("./casedef/geometry/definition")
    if definition is None:
        raise ValueError("missing geometry definition")
    definition.set("dp", repr(DP))
    pointref = definition.find("./pointref")
    if pointref is None:
        raise ValueError("missing pointref")
    half = DP / 2.0
    for key in ("x", "y", "z"):
        pointref.set(key, repr(half))
    main = root.find("./casedef/geometry/commands/mainlist")
    if main is None:
        raise ValueError("missing mainlist")
    boxes = main.findall("./drawbox")
    if len(boxes) != 2:
        raise ValueError("expected fluid and boundary drawboxes")
    fluid_point = boxes[0].find("./point")
    fluid_size = boxes[0].find("./size")
    bound_point = boxes[1].find("./point")
    bound_size = boxes[1].find("./size")
    if any(item is None for item in (fluid_point, fluid_size, bound_point, bound_size)):
        raise ValueError("incomplete CELL3 drawbox")
    for key, value in zip(("x", "y", "z"), (LOW[0] + half, LOW[1] + half, LOW[2] + half)):
        fluid_point.set(key, repr(value))
    for key, value in zip(("x", "y", "z"), (FLUID_DIMS[0] - DP, FLUID_DIMS[1] - DP, FLUID_DIMS[2] - DP)):
        fluid_size.set(key, repr(value))
    for key, value in zip(("x", "y", "z"), (LOW[0] - half, LOW[1] - half, LOW[2] - half)):
        bound_point.set(key, repr(value))
    for key, value in zip(("x", "y", "z"), (0.9 + DP, 0.18 + DP, 0.51 + DP)):
        bound_size.set(key, repr(value))
    tree.write(target, encoding="utf-8", xml_declaration=True)


def _drive(target: Path, amplitude: float) -> None:
    nominal = np.loadtxt(VENDOR_DRIVE, delimiter=";", comments="#")
    actual = nominal.copy()
    gravity = np.array([0.0, 0.0, -9.81])
    actual[:, 1:4] = gravity + amplitude * (nominal[:, 1:4] - gravity)
    actual[:, 4:7] = amplitude * nominal[:, 4:7]
    np.savetxt(target, actual, delimiter=";", fmt="%.17g",
               header="Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ")


def _run_gencase(definition: Path, prefix: Path) -> str:
    process = subprocess.run(
        [str(GENCASE), str(definition.with_suffix("")), str(prefix), "-save:all"],
        cwd=prefix.parent, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False,
    )
    log = prefix.parent / (prefix.name + "-GENCASE.log")
    log.write_text(process.stdout)
    if process.returncode != 0:
        raise RuntimeError(f"GenCase failed for {prefix.name}; see {log}")
    required = [prefix.with_suffix(".xml"), prefix.with_suffix(".bi4"),
                prefix.with_name(prefix.name + "_hdp_Actual.vtk")]
    if not all(path.is_file() and path.stat().st_size > 0 for path in required):
        raise RuntimeError(f"GenCase did not produce complete assets for {prefix.name}")
    return _relative(log)


def _prepare_cell(manifest_sha: str, cell: tuple[str, float, str]) -> dict:
    case_id, amplitude, role = cell
    target = TARGET_ROOT / case_id
    prefix = target / f"F3_CELL3_plain_{DP_LABEL}"
    prepared_path = OUT / f"{case_id}-PREPARED.json"
    if prepared_path.is_file():
        return _verify_prepared_record(prepared_path, manifest_sha, cell)
    if target.exists():
        raise ValueError(f"incomplete preparation exists; inspect without overwrite: {target}")
    target.mkdir(parents=True)
    definition = target / f"{prefix.name}_Def.xml"
    _rewrite_definition(SOURCE_PREFIX.with_name(SOURCE_PREFIX.name + "_Def.xml"), definition)
    # GenCase may truncate same-directory auxiliary files; restore the source
    # control after generation before recording or preflighting the cell.
    shutil.copy2(VENDOR_DRIVE, target / "CaseSloshingAccData.csv")
    gencase_log = _run_gencase(definition, prefix)
    shutil.copy2(VENDOR_DRIVE, target / "CaseSloshingAccData.csv")
    _drive(target / "CaseSloshingAccData.csv", amplitude)
    counts = native._initial_state(prefix, DP)
    source = _read(SOURCE_RECORD)
    record = copy.deepcopy(source)
    record.update({
        "id": case_id,
        "case_id": case_id,
        "phase": "F3_ref0081818_preparation_only",
        "plan_case_id": case_id,
        "recipe_id": RECIPE,
        "role": role,
        "dp_m": DP,
        "resolution": str(DP),
        "drive_amplitude": amplitude,
        "generated_prefix": _relative(prefix),
        "candidate_definition": _relative(definition),
        "generated_xml_sha256": q2.sha256(prefix.with_suffix(".xml")),
        "drive_sha256": q2.sha256(target / "CaseSloshingAccData.csv"),
        "gencase": {**counts, "gencase_log": gencase_log, "exact_tiling": True},
        "actual_y_layers": 22,
        "initial_mass_kg": counts["initial_mass_kg"],
        "initial_com_m": counts["initial_com_m"],
        "initial_target_mass_kg": 14.58,
        "initial_mass_relative_error": abs(counts["initial_mass_kg"] / 14.58 - 1.0),
        "solver_timeout_seconds": 4200,
        "max_attempts": 1,
        "resource_category": "qualification",
        "launch_allowed": False,
        "qualified": False,
        "formal_release": False,
        "revision_manifest_sha256": manifest_sha,
        "preparer_sha256": q2.sha256(Path(__file__)),
        "comparison_scope": "Prospective exact-tiling coarse reference; preparation only, no qualification or production status",
        "input_repair": "none; prospective exact-tiling reference resolution only",
        "input_assets": {
            path.name: q2.sha256(path)
            for path in (target / "CaseSloshingAccData.csv", prefix.with_suffix(".xml"),
                         definition, prefix.with_suffix(".bi4"),
                         prefix.with_name(prefix.name + "_hdp_Actual.vtk"))
        },
    })
    _atomic(prepared_path, record)
    check_input(record)
    preflight_path = OUT / f"{case_id}-INPUT-PREFLIGHT.json"
    preflight = _read(preflight_path)
    preflight.update({
        "record_id": case_id,
        "record_sha256": q2.sha256(prepared_path),
        "recipe_id": RECIPE,
        "revision_manifest_sha256": manifest_sha,
    })
    _atomic(preflight_path, preflight)
    _verify_prepared_record(prepared_path, manifest_sha, cell)
    return record


def _verify_prepared_record(path: Path, manifest_sha: str,
                            cell: tuple[str, float, str]) -> dict:
    case_id, amplitude, role = cell
    record = _read(path)
    expected = {
        "id": case_id, "case_id": case_id, "plan_case_id": case_id,
        "recipe_id": RECIPE, "role": role, "dp_m": DP,
        "drive_amplitude": amplitude, "resource_category": "qualification",
        "revision_manifest_sha256": manifest_sha,
    }
    if any(record.get(key) != value for key, value in expected.items()):
        raise ValueError(f"prepared record is not bound to manifest cell: {path}")
    if (record.get("launch_allowed") is not False
            or record.get("qualified") is not False
            or record.get("formal_release") is not False):
        raise ValueError(f"prepared record is not fail-closed: {path}")
    prefix = LAB / record["generated_prefix"]
    for name, digest in record.get("input_assets", {}).items():
        asset = prefix.parent / name
        if not asset.is_file() or q2.sha256(asset) != digest:
            raise ValueError(f"prepared input asset changed: {asset}")
    if record.get("generated_xml_sha256") != q2.sha256(prefix.with_suffix(".xml")):
        raise ValueError(f"prepared XML binding changed: {path}")
    preflight_path = OUT / f"{case_id}-INPUT-PREFLIGHT.json"
    preflight = _read(preflight_path)
    if (preflight.get("status") != "passed"
            or preflight.get("record_id") != case_id
            or preflight.get("record_sha256") != q2.sha256(path)
            or preflight.get("recipe_id") != RECIPE
            or preflight.get("revision_manifest_sha256") != manifest_sha):
        raise ValueError(f"prepared input preflight is not bound: {preflight_path}")
    return record


def prepare_all() -> dict:
    if not GENCASE.is_file():
        raise FileNotFoundError(f"missing GenCase executable: {GENCASE}")
    manifest = _manifest()
    manifest_sha = q2.sha256(MANIFEST) if MANIFEST.exists() else None
    # The manifest is immutable for this preparation.  Write it once, then
    # compute its hash for all prepared records.
    if MANIFEST.exists():
        existing = _read(MANIFEST)
        if existing != manifest:
            raise ValueError("prospective manifest exists with different content")
    else:
        _atomic(MANIFEST, manifest)
    manifest_sha = q2.sha256(MANIFEST)
    records = [_prepare_cell(manifest_sha, cell) for cell in CELLS]
    summary = {
        "schema": "f3.revision075.ref0081818.preparation_summary.v1",
        "status": "prepared_only",
        "launch_allowed": False,
        "recipe_id": RECIPE,
        "manifest_sha256": manifest_sha,
        "preparer_sha256": q2.sha256(Path(__file__)),
        "cell_ids": [record["plan_case_id"] for record in records],
        "prepared_records": [str((OUT / f"{record['id']}-PREPARED.json").relative_to(LAB)) for record in records],
        "input_preflights": [str((OUT / f"{record['id']}-INPUT-PREFLIGHT.json").relative_to(LAB)) for record in records],
        "record_bindings": [
            {"path": str((OUT / f"{record['id']}-PREPARED.json").relative_to(LAB)),
             "sha256": q2.sha256(OUT / f"{record['id']}-PREPARED.json")}
            for record in records
        ],
        "preflight_bindings": [
            {"path": str((OUT / f"{record['id']}-INPUT-PREFLIGHT.json").relative_to(LAB)),
             "sha256": q2.sha256(OUT / f"{record['id']}-INPUT-PREFLIGHT.json")}
            for record in records
        ],
        "solver_attempts": 0,
        "qualification_attempts_charged": 0,
        "qualified": False,
        "formal_release": False,
        "new_authorization_required": True,
    }
    _atomic(OUT / "F3-075-REF0081818-PREPARATION-SUMMARY.json", summary)
    print(json.dumps(summary, indent=2, ensure_ascii=False), flush=True)
    return summary


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare-all",))
    args = parser.parse_args()
    prepare_all()
