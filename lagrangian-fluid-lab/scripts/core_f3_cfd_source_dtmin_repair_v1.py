#!/usr/bin/env python3
"""Prepare and run the isolated F3 dense cadence repair source.

This module is a Core-owned source path.  It deliberately does not use the
old ``l1-resume`` runner, its authorization records, or its ledger.  The old
revision075 preparation logic is reproduced as a hash-bound input transform:
the existing particle assets and XML recipe are copied into a fresh immutable
Core preparation directory, and only the forcing CSV, case identity, and the
registered output cadence are materialized there.

This version is a fresh qualification-only lineage.  It preserves the dense
.002 s source recipe and uses one explicit double-valued ``DtMin`` to avoid the
float32 downward rounding diagnosed in the static proposal.  ``prepare`` and
``make-job`` are CPU/metadata operations.  ``run`` is the runtime worker
entrypoint used by ``core_runtime``.  The coordinator assigns one CUDA device
through ``CUDA_VISIBLE_DEVICES``; the solver therefore always receives
``-gpu:0`` inside that remapped device namespace.  No GPU is selected by this
module and no campaign ledger is touched.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from typing import Any

import numpy as np

try:
    from scripts import core_cfd
    from scripts import core_f3_cfd_source_audit_v2
except ModuleNotFoundError:  # pragma: no cover - direct script entrypoint
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts import core_cfd
    from scripts import core_f3_cfd_source_audit_v2


LAB = Path(__file__).resolve().parents[1]
SCHEMA = "core.f3.cfd.native_volume_mls.source.v1"
JOB_SCHEMA = "core.f3.cfd.native_volume_mls.source_job.v1"
RECIPE_ID = "F3_CELL3_NS_visco1_native_nopen_revision075"
QUALIFICATION_ONLY = "none; qualification_only source generation"
TIME_MAX_S = 8.35
OUTPUT_NATIVE010_S = 0.01
OUTPUT_NATIVE002_S = 0.002
CFL = 0.05
COEF_DT_MIN = 0.05
EXPLICIT_DT_MIN_S = 2.1978023141855374e-05
REPAIR_ID = "F3_DENSE002_EXPLICIT_DTMIN_FLOAT64_UP_V1"
STATIC_REPORT_REL = (
    "campaigns/core-v1/material/evidence/f3-dense-cadence-diagnosis-v1/"
    "dense002-timestep-repair-v4/static-report.json"
)
STATIC_PROPOSAL_REL = (
    "campaigns/core-v1/material/evidence/f3-dense-cadence-diagnosis-v1/"
    "dense002-timestep-repair-v4/proposal.json"
)
SOURCE_AUDIT_V2_REL = "scripts/core_f3_cfd_source_audit_v2.py"
FINITE_WALL_AUDIT_REL = "scripts/finite_wall_audit.py"
GRAVITY = np.array([0.0, 0.0, -9.81], dtype=np.float64)
PROPOSAL_REL = "campaigns/core-v1/material/evidence/f3-native-mls-missing-cfd-source-proposals-v2-20260920.json"
PROPOSAL_SHA256 = "9dc3ccba356a82e6feaa271ad0c81554a630793210d1b08fda3fe9f099831c99"
LEGACY_PREPARE_REL = "scripts/f3_revision075_prepare.py"
REVISION_MANIFEST_REL = "diagnostics/f3-audit/F3-075-REVISION-MATRIX-MANIFEST.json"
SOLVER_REL = "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
GENCASE_REL = "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
DECODER_REL = "campaigns/l1-resume/artifacts/bi4_dump"
VENDOR_CONTROL_REL = "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(path: Path) -> str:
    """Hash one immutable file in bounded memory."""
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def atomic_json(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".partial")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _lab_path(lab: Path, relative: str) -> Path:
    return (Path(lab).resolve() / relative).resolve()


def _relative_or_absolute(path: Path, lab: Path) -> str:
    try:
        return str(path.resolve().relative_to(Path(lab).resolve()))
    except ValueError:
        return str(path.resolve())


def _proposal_hash(lab: Path) -> str:
    path = _lab_path(lab, PROPOSAL_REL)
    if not path.is_file():
        raise FileNotFoundError(path)
    return digest(path)


def _case(
    *,
    source_asset_id: str,
    case_id: str,
    legacy_alias: str,
    rows: list[int],
    q: float,
    amplitude: float,
    dp_m: float,
    role: str,
    template_prefix: str,
    output_interval_s: float,
    cadence: str,
    fluid_particles: int,
    timeout_seconds: int,
    ram_mib: int,
    gpu_peak_mib: int,
    expected_h5_size_bytes: int,
    explicit_dt_min_s: float = 0.0,
) -> dict[str, Any]:
    return {
        "source_asset_id": source_asset_id,
        "case_id": case_id,
        "legacy_proposal_case_id": legacy_alias,
        "matrix_rows": rows,
        "q": q,
        "drive_amplitude": amplitude,
        "dp_m": dp_m,
        "resolution_role": role,
        "template_prefix": template_prefix,
        "output_interval_s": output_interval_s,
        "cadence": cadence,
        "time_max_s": TIME_MAX_S,
        "cfl_number": CFL,
        "coef_dt_min": COEF_DT_MIN,
        "explicit_dt_min_s": explicit_dt_min_s,
        "fluid_particles": fluid_particles,
        "expected_native_frames": 836 if math.isclose(output_interval_s, .01) else 4176,
        "expected_native_intervals": 835 if math.isclose(output_interval_s, .01) else 4175,
        "timeout_seconds": timeout_seconds,
        "ram_mib": ram_mib,
        "gpu_peak_mib": gpu_peak_mib,
        "expected_h5_size_bytes": expected_h5_size_bytes,
        "qualification_claim": QUALIFICATION_ONLY,
    }


def source_cases() -> dict[str, dict[str, Any]]:
    """Return the five exact, deduplicated CFD sources in canonical order."""
    return {
        "f3_production_amp0p95_native010": _case(
            source_asset_id="f3_production_amp0p95_native010",
            case_id="F3_REV075_MATERIAL-AMP0P95-0075",
            legacy_alias="F3_REV075_INTERNAL-LOW-0075",
            rows=[16, 17], q=.25, amplitude=.95, dp_m=.0075,
            role="production", template_prefix="campaigns/l1-resume/artifacts/cell3-nopen-qualification/"
            "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen/F3_CELL3_plain_0p0075",
            output_interval_s=.01, cadence="native", fluid_particles=34560,
            timeout_seconds=3600, ram_mib=4096, gpu_peak_mib=4096,
            expected_h5_size_bytes=900096638),
        "f3_fine_amp0p95_native010": _case(
            source_asset_id="f3_fine_amp0p95_native010",
            case_id="F3_REV075_MATERIAL-AMP0P95-006",
            legacy_alias="F3_REV075_INTERNAL-LOW-006",
            rows=[18, 19], q=.25, amplitude=.95, dp_m=.006,
            role="fine", template_prefix="campaigns/l1-resume/artifacts/cell3-nopen-qualification/"
            "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen/F3_CELL3_plain_0p006",
            output_interval_s=.01, cadence="native", fluid_particles=67500,
            timeout_seconds=5400, ram_mib=4096, gpu_peak_mib=6144,
            expected_h5_size_bytes=1789385044),
        "f3_production_amp1p05_native010": _case(
            source_asset_id="f3_production_amp1p05_native010",
            case_id="F3_REV075_MATERIAL-AMP1P05-0075",
            legacy_alias="F3_REV075_INTERNAL-HIGH-0075",
            rows=[20, 21], q=.75, amplitude=1.05, dp_m=.0075,
            role="production", template_prefix="campaigns/l1-resume/artifacts/cell3-nopen-qualification/"
            "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen/F3_CELL3_plain_0p0075",
            output_interval_s=.01, cadence="native", fluid_particles=34560,
            timeout_seconds=3600, ram_mib=4096, gpu_peak_mib=4096,
            expected_h5_size_bytes=900096638),
        "f3_fine_amp1p05_native010": _case(
            source_asset_id="f3_fine_amp1p05_native010",
            case_id="F3_REV075_MATERIAL-AMP1P05-006",
            legacy_alias="F3_REV075_INTERNAL-HIGH-006",
            rows=[22, 23], q=.75, amplitude=1.05, dp_m=.006,
            role="fine", template_prefix="campaigns/l1-resume/artifacts/cell3-nopen-qualification/"
            "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen/F3_CELL3_plain_0p006",
            output_interval_s=.01, cadence="native", fluid_particles=67500,
            timeout_seconds=5400, ram_mib=4096, gpu_peak_mib=6144,
            expected_h5_size_bytes=1789385044),
        "f3_production_amp1p1_native002": _case(
            source_asset_id="f3_production_amp1p1_native002",
            case_id="F3_REV075_MATERIAL-AMP1P1-0075-DENSE002",
            legacy_alias="F3_REV075_ENDPOINT-HIGH-0075-DENSE002",
            rows=[26, 27], q=1., amplitude=1.1, dp_m=.0075,
            role="production", template_prefix="campaigns/l1-resume/artifacts/f3-revision075/"
            "F3_REV075_R075-OUTPUT/F3_CELL3_plain_0p0075",
            output_interval_s=.002, cadence="native_dense", fluid_particles=34560,
            timeout_seconds=21600, ram_mib=4096, gpu_peak_mib=4096,
            expected_h5_size_bytes=4498243234),
    }


def source_cases() -> dict[str, dict[str, Any]]:
    """Expose only the fresh dense repair case from this runner version."""
    return {
        "f3_production_amp1p1_native002_dtminrepair_auditv2r2": _case(
            source_asset_id="f3_production_amp1p1_native002_dtminrepair_auditv2r2",
            case_id="F3_REV075_MATERIAL-AMP1P1-0075-DENSE002-DTMINREPAIR-AUDITV2R2",
            legacy_alias="F3_REV075_ENDPOINT-HIGH-0075-DENSE002-DTMINREPAIR-AUDITV2R2",
            rows=[26, 27], q=1.0, amplitude=1.1, dp_m=0.0075,
            role="production", template_prefix="campaigns/l1-resume/artifacts/f3-revision075/"
            "F3_REV075_R075-OUTPUT/F3_CELL3_plain_0p0075",
            output_interval_s=0.002, cadence="native_dense", fluid_particles=34560,
            timeout_seconds=21600, ram_mib=8192, gpu_peak_mib=8192,
            expected_h5_size_bytes=4498243234,
            explicit_dt_min_s=EXPLICIT_DT_MIN_S,
        ),
    }


def _validate_case(case: dict[str, Any]) -> None:
    if not math.isclose((float(case["drive_amplitude"]) - .9) / .2, float(case["q"]), abs_tol=1e-12):
        raise ValueError("q/amplitude binding mismatch")
    if case["cadence"] == "native_dense" and not math.isclose(case["output_interval_s"], .002):
        raise ValueError("dense source must use native .002 s output")
    if case["cadence"] == "native" and not math.isclose(case["output_interval_s"], .01):
        raise ValueError("native source must use .01 s output")
    if case["time_max_s"] != TIME_MAX_S:
        raise ValueError("all source cases require the complete 8.35 s window")
    if case["dp_m"] not in (.0075, .006):
        raise ValueError("unregistered source resolution")
    if case["output_interval_s"] == .002 and case["dp_m"] != .0075:
        raise ValueError("dense source is registered only at production dp")
    explicit_dt_min_s = float(case.get("explicit_dt_min_s", 0.0))
    if case["cadence"] == "native_dense":
        if not math.isclose(explicit_dt_min_s, EXPLICIT_DT_MIN_S, rel_tol=0.0, abs_tol=1e-18):
            raise ValueError("dense repair source must use the registered explicit DtMin")
    elif explicit_dt_min_s != 0.0:
        raise ValueError("explicit DtMin is only registered for the dense repair source")


def _copy_input_asset(source: Path, target: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(source)
    if target.exists():
        raise FileExistsError(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def _rewrite_xml(path: Path, *, dp_m: float, output_interval_s: float,
                 explicit_dt_min_s: float = 0.0) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    parameters = root.findall("./execution/parameters/parameter")
    by_key = {node.get("key"): node for node in parameters}
    if len(by_key) != len(parameters):
        raise ValueError(f"duplicate execution parameter in {path}")
    for key, value in (("TimeMax", TIME_MAX_S), ("TimeOut", output_interval_s),
                       ("CoefDtMin", COEF_DT_MIN), ("DtMin", explicit_dt_min_s)):
        if key not in by_key:
            raise ValueError(f"missing parameter {key} in {path}")
        by_key[key].set("value", str(value))
    for node in root.findall(".//cflnumber"):
        node.set("value", str(CFL))
    if not root.findall(".//cflnumber"):
        raise ValueError(f"missing cflnumber in {path}")
    definition = root.find("./casedef/geometry/definition")
    if definition is None or not math.isclose(float(definition.get("dp")), dp_m, abs_tol=1e-12):
        raise ValueError(f"source dp differs from registered case in {path}")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _write_control(path: Path, amplitude: float, vendor_path: Path) -> None:
    nominal = np.loadtxt(vendor_path, delimiter=";", comments="#")
    actual = nominal.copy()
    actual[:, 1:4] = GRAVITY + amplitude * (nominal[:, 1:4] - GRAVITY)
    actual[:, 4:7] = amplitude * nominal[:, 4:7]
    np.savetxt(path, actual, delimiter=";", fmt="%.17g",
               header="Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ")


def _sampling(dp_m: float, fluid_particles: int) -> dict[str, Any]:
    # This is the unchanged F3 fluid volume: x[-.45,.45), y[-.09,.09),
    # z[0,.09).  It yields 34560 particles at dp=.0075 and 67500 at .006.
    counts = np.floor(np.asarray([.9, .18, .09]) / dp_m + 1e-9).astype(int)
    expected = int(np.prod(counts))
    if expected != fluid_particles:
        raise ValueError(f"fluid lattice mismatch: {expected} != {fluid_particles}")
    box = {
        "continuous_low_m": [-.45, -.09, 0.0],
        "continuous_size_m": [.9, .18, .09],
        "first_center_m": ((np.array([-.45, -.09, 0.0]) + dp_m / 2)).tolist(),
        "draw_size_m": ((counts - 1) * dp_m).tolist(),
        "counts": counts.tolist(),
        "particle_count": expected,
        "continuous_mass_kg": .9 * .18 * .09 * 1000.,
        "discrete_mass_kg": expected * dp_m ** 3 * 1000.,
        "mkfluid": 0,
    }
    return {
        "fluid_boxes": [box],
        "expected_fluid_particles": expected,
        "continuous_mass_kg": box["continuous_mass_kg"],
        "sampled_mass_kg": box["discrete_mass_kg"],
        "mass_policy": "native rho*dp^3; no mass rescaling; continuous-volume representation is recorded",
    }


def _mass_preflight(sampling: dict[str, Any]) -> dict[str, Any]:
    continuous = float(sampling["continuous_mass_kg"])
    discrete = float(sampling["sampled_mass_kg"])
    relative = discrete / continuous - 1.0
    return {
        "continuous_mass_kg": continuous,
        "discrete_mass_kg": discrete,
        "relative_error": relative,
        "mass_rescaling": False,
        "pass": bool(math.isfinite(relative) and abs(relative) <= 1e-12),
    }


def _source_file_names(prefix: Path) -> list[str]:
    return [
        prefix.name + ".xml",
        prefix.name + "_Def.xml",
        prefix.name + ".bi4",
        prefix.name + "_hdp_Actual.vtk",
    ]


def prepare_case(case_key: str, output: Path, *, lab: Path = LAB) -> dict[str, Any]:
    """Create one fresh immutable Core prepared case without launching CFD."""
    lab = Path(lab).resolve()
    cases = source_cases()
    if case_key not in cases:
        raise ValueError(f"unknown source case: {case_key}")
    case = dict(cases[case_key])
    _validate_case(case)
    if digest(_lab_path(lab, PROPOSAL_REL)) != PROPOSAL_SHA256:
        raise ValueError("source proposal changed; regenerate a new Core source snapshot")
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"immutable preparation target is not fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)

    template_prefix = _lab_path(lab, case["template_prefix"])
    template_dir = template_prefix.parent
    copied_prefix = output / template_prefix.name
    for name in _source_file_names(template_prefix):
        _copy_input_asset(template_dir / name, output / name)
    control_path = output / "CaseSloshingAccData.csv"
    _write_control(control_path, float(case["drive_amplitude"]), _lab_path(lab, VENDOR_CONTROL_REL))
    _rewrite_xml(output / (template_prefix.name + ".xml"),
                 dp_m=float(case["dp_m"]), output_interval_s=float(case["output_interval_s"]),
                 explicit_dt_min_s=float(case.get("explicit_dt_min_s", 0.0)))
    _rewrite_xml(output / (template_prefix.name + "_Def.xml"),
                 dp_m=float(case["dp_m"]), output_interval_s=float(case["output_interval_s"]),
                 explicit_dt_min_s=float(case.get("explicit_dt_min_s", 0.0)))

    # The decoder validates the copied initial state on CPU.  It does not run
    # a CFD solver and it never mutates the source template.
    with tempfile.TemporaryDirectory(prefix="core-f3-source-prepare-") as temp:
        ids, position, velocity, density, meta, info, _ = core_cfd.native_frame(
            copied_prefix.with_suffix(".bi4"), Path(temp) / "initial", _lab_path(lab, DECODER_REL))
    sampling = _sampling(float(case["dp_m"]), int(case["fluid_particles"]))
    mass = _mass_preflight(sampling)
    if int(meta["CaseNfluid"]) != int(case["fluid_particles"]):
        raise ValueError("native initial fluid count differs from registered source case")
    if not (np.isfinite(position).all() and np.isfinite(velocity).all() and np.isfinite(density).all()):
        raise ValueError("native initial state contains nonfinite values")
    if not mass["pass"]:
        raise ValueError("F3 native mass representation failed exact preparation gate")

    config = {
        "schema": "core.f3.cfd.source.config.v1",
        "family": "F3",
        "scope": "F3_native_volume_mls_source",
        "case_id": case["case_id"],
        "source_asset_id": case["source_asset_id"],
        "recipe_id": RECIPE_ID,
        "q": case["q"],
        "drive_amplitude": case["drive_amplitude"],
        "dp_m": case["dp_m"],
        "output_interval_s": case["output_interval_s"],
        "time_max_s": TIME_MAX_S,
        "cfl": CFL,
        "coef_dt_min": COEF_DT_MIN,
        "explicit_dt_min_s": float(case.get("explicit_dt_min_s", 0.0)),
        "timestep_repair_id": REPAIR_ID,
        "solver_mode": "-mdbc_noslip:1",
        "boundary": 2,
        "slip_mode": 2,
        "no_penetration": 1,
        "visco": 0.05,
        "visco_bound_factor": 1,
        "shifting": 0,
        "coordinate_frame": "fixed tank computational coordinates with prescribed acceleration; no inertial-world trajectory claim",
        "source_label_semantics": "material source is continuous x<0/x>=0 seed geometry; CFD fluid is one native fluid block",
        "physical_case_id": f"F3_material_source_q{case['q']:.8f}_dp{case['dp_m']:.12f}_amp{case['drive_amplitude']:.8f}".replace('.', 'p'),
        "lineage_group_id": f"F3_material_source_amp{case['drive_amplitude']:.8f}_dp{case['dp_m']:.12f}".replace('.', 'p'),
        "qualification_claim": QUALIFICATION_ONLY,
        "qualified": False,
        "formal_release": False,
        "matrix_rows": case["matrix_rows"],
        "cadence": case["cadence"],
        "expected_native_frames": case["expected_native_frames"],
        "interpolation_forbidden": True,
    }
    inputs = {}
    for path in [control_path] + [output / name for name in _source_file_names(template_prefix)]:
        inputs[str(path.resolve())] = digest(path)
    prepared = {
        "schema": SCHEMA,
        "created_at_utc": utc_now(),
        "status": "prepared_only",
        "launch_allowed": False,
        "execution_status": "prepared_only",
        "qualification_claim": QUALIFICATION_ONLY,
        "case": case,
        "config": config,
        "sampling": sampling,
        "mass_preflight": mass,
        "native_initial": {
            "total_particles": int(len(ids)),
            "fluid_particles": int(meta["CaseNfluid"]),
            "boundary_particles": int(meta["CaseNfixed"]),
            "initial_time_s": float(info["TimeStep"]),
            "initial_state_pass": True,
        },
        "preflight_pass": True,
        "generated_prefix": str(copied_prefix.resolve()),
        "template_prefix": str(template_prefix.resolve()),
        "template_prefix_sha256": digest(template_prefix.with_suffix('.xml')),
        "inputs": inputs,
        "solver_binary": str(_lab_path(lab, SOLVER_REL)),
        "solver_sha256": digest(_lab_path(lab, SOLVER_REL)),
        "decoder": str(_lab_path(lab, DECODER_REL)),
        "decoder_sha256": digest(_lab_path(lab, DECODER_REL)),
        "solver_arguments": ["-mdbc_noslip:1"],
        "control_generation": {
            "algorithm": "gravity_preserving_amplitude_v1",
            "formula": "LinearAcc[1:4]=gravity + amp*(vendor[1:4]-gravity); AngularAcc[4:7]=amp*vendor[4:7]; Time unchanged",
            "gravity_mps2": [0.0, 0.0, -9.81],
            "vendor_path": str(_lab_path(lab, VENDOR_CONTROL_REL)),
            "vendor_sha256": digest(_lab_path(lab, VENDOR_CONTROL_REL)),
            "generated_sha256": digest(control_path),
        },
        "source_provenance": {
            "timestep_repair_id": REPAIR_ID,
            "explicit_dt_min_s": float(case.get("explicit_dt_min_s", 0.0)),
            "static_report_path": str(_lab_path(lab, STATIC_REPORT_REL)),
            "static_report_sha256": digest(_lab_path(lab, STATIC_REPORT_REL)),
            "static_proposal_path": str(_lab_path(lab, STATIC_PROPOSAL_REL)),
            "static_proposal_sha256": digest(_lab_path(lab, STATIC_PROPOSAL_REL)),
            "proposal_path": str(_lab_path(lab, PROPOSAL_REL)),
            "proposal_sha256": PROPOSAL_SHA256,
            "legacy_preparation_logic_path": str(_lab_path(lab, LEGACY_PREPARE_REL)),
            "legacy_preparation_logic_sha256": digest(_lab_path(lab, LEGACY_PREPARE_REL)),
            "revision_manifest_path": str(_lab_path(lab, REVISION_MANIFEST_REL)),
            "revision_manifest_sha256": digest(_lab_path(lab, REVISION_MANIFEST_REL)),
            "core_preparation_runner": str(Path(__file__).resolve()),
            "core_preparation_runner_sha256": digest(Path(__file__)),
            "core_conversion_helper": str(Path(core_cfd.__file__).resolve()),
            "core_conversion_helper_sha256": digest(Path(core_cfd.__file__)),
            "source_audit_v2": str(_lab_path(lab, SOURCE_AUDIT_V2_REL)),
            "source_audit_v2_sha256": digest(_lab_path(lab, SOURCE_AUDIT_V2_REL)),
            "finite_wall_audit": str(_lab_path(lab, FINITE_WALL_AUDIT_REL)),
            "finite_wall_audit_sha256": digest(_lab_path(lab, FINITE_WALL_AUDIT_REL)),
        },
        "immutable_policy": {
            "prepared_directory_must_be_fresh": True,
            "old_l1_resume_files_mutated": False,
            "central_ledger_mutation": 0,
            "gpu_started": False,
            "native_h5_sha256": None,
            "native_h5_created_only_by_runtime_worker": True,
        },
    }
    atomic_json(output / "prepared.json", prepared)
    prepared["prepared_json_sha256"] = digest(output / "prepared.json")
    # Re-write with the self-hash omitted from the file itself.  The returned
    # record carries the externally computed hash for the job-spec builder.
    prepared.pop("prepared_json_sha256")
    atomic_json(output / "prepared.json", prepared)
    prepared["prepared_json_sha256"] = digest(output / "prepared.json")
    return prepared


def _validate_prepared(prepared_path: Path, *, lab: Path = LAB) -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    prepared = json.loads(prepared_path.read_text(encoding="utf-8"))
    if prepared.get("schema") != SCHEMA or prepared.get("status") != "prepared_only":
        raise ValueError("unexpected F3 Core prepared schema/status")
    if prepared.get("launch_allowed") is not False or prepared.get("qualification_claim") != QUALIFICATION_ONLY:
        raise ValueError("prepared source is not fail-closed qualification_only")
    if prepared.get("preflight_pass") is not True:
        raise ValueError("prepared source preflight failed")
    case = prepared.get("case") or {}
    _validate_case(case)
    if digest(_lab_path(lab, PROPOSAL_REL)) != PROPOSAL_SHA256:
        raise ValueError("proposal provenance changed")
    if prepared.get("source_provenance", {}).get("core_preparation_runner_sha256") != digest(Path(__file__)):
        raise ValueError("prepared source runner hash is stale; regenerate an immutable Core prepared record")
    if prepared.get("source_provenance", {}).get("core_conversion_helper_sha256") != digest(Path(core_cfd.__file__)):
        raise ValueError("prepared conversion helper hash is stale; regenerate an immutable Core prepared record")
    provenance = prepared.get("source_provenance", {})
    audit_path = _lab_path(lab, SOURCE_AUDIT_V2_REL)
    if provenance.get("source_audit_v2_sha256") != digest(audit_path):
        raise ValueError("prepared source audit-v2 hash is stale; regenerate an immutable Core prepared record")
    wall_audit_path = _lab_path(lab, FINITE_WALL_AUDIT_REL)
    if provenance.get("finite_wall_audit_sha256") != digest(wall_audit_path):
        raise ValueError("prepared finite-wall audit hash is stale; regenerate an immutable Core prepared record")
    if provenance.get("timestep_repair_id") != REPAIR_ID:
        raise ValueError("prepared source is missing the explicit-DtMin repair identity")
    if not math.isclose(float(provenance.get("explicit_dt_min_s", 0.0)), EXPLICIT_DT_MIN_S,
                        rel_tol=0.0, abs_tol=1e-18):
        raise ValueError("prepared source has the wrong explicit DtMin")
    for relative, key in ((STATIC_REPORT_REL, "static_report_sha256"),
                          (STATIC_PROPOSAL_REL, "static_proposal_sha256")):
        evidence = _lab_path(lab, relative)
        if provenance.get(key) != digest(evidence):
            raise ValueError(f"timestep repair evidence hash is stale: {relative}")
    for path, expected in prepared.get("inputs", {}).items():
        if digest(Path(path)) != expected:
            raise ValueError("prepared input hash mismatch: " + path)
    if digest(Path(prepared["solver_binary"])) != prepared["solver_sha256"]:
        raise ValueError("solver binary hash mismatch")
    if digest(Path(prepared["decoder"])) != prepared["decoder_sha256"]:
        raise ValueError("decoder hash mismatch")
    if prepared["config"]["time_max_s"] != TIME_MAX_S:
        raise ValueError("source is not the complete 8.35 s window")
    if prepared["config"]["expected_native_frames"] not in (836, 4176):
        raise ValueError("unexpected native frame contract")
    if prepared["config"]["cadence"] == "native_dense" and prepared["config"]["output_interval_s"] != .002:
        raise ValueError("native_dense source must be .002 s")
    if not math.isclose(float(prepared["config"].get("explicit_dt_min_s", 0.0)), EXPLICIT_DT_MIN_S,
                        rel_tol=0.0, abs_tol=1e-18):
        raise ValueError("prepared config has the wrong explicit DtMin")
    return prepared


def _audit_hdf5(
    prepared: dict[str, Any], prepared_path: Path, hdf5: Path, output: Path,
) -> dict[str, Any]:
    """Delegate to the immutable streaming source-audit-v2 implementation.

    The source runner intentionally has no second, weaker integrity audit.
    Cadence, finite-wall/open-top binding, and per-particle mass checks are
    supplied by the independently reviewable v2 auditor used for post-run
    re-audits as well.
    """
    report = core_f3_cfd_source_audit_v2.audit_hdf5(
        prepared, Path(hdf5), prepared_path=Path(prepared_path),
    )
    report["runner_audit_binding"] = {
        "audit_module": str(Path(core_f3_cfd_source_audit_v2.__file__).resolve()),
        "audit_module_sha256": digest(Path(core_f3_cfd_source_audit_v2.__file__)),
        "audit_schema_required": core_f3_cfd_source_audit_v2.SCHEMA,
        "delegated_without_copy": True,
    }
    atomic_json(output / "audit.json", report)
    return report

def run_case(prepared_path: Path, output: Path, *, lab: Path = LAB) -> dict[str, Any]:
    """Run one source case under a Core runtime worker."""
    lab = Path(lab).resolve()
    prepared = _validate_prepared(prepared_path, lab=lab)
    output = Path(output).resolve()
    if output.exists() and any(output.iterdir()):
        raise FileExistsError(f"runtime product directory must be fresh: {output}")
    visible = os.environ.get("CUDA_VISIBLE_DEVICES", "")
    if not visible or "," in visible:
        raise ValueError("core_runtime must assign exactly one CUDA_VISIBLE_DEVICES value")
    output.mkdir(parents=True, exist_ok=True)
    atomic_json(output / "prepared.json", prepared)
    solver_dir = output / "solver"
    argv = [prepared["solver_binary"], "-gpu:0", *prepared["solver_arguments"], prepared["generated_prefix"], str(solver_dir)]
    atomic_json(output / "worker-status.json", {"status": "running", "argv": argv, "cuda_visible_devices": visible, "started_at_utc": utc_now()})
    start = time.monotonic()
    with (output / "solver.stdout.log").open("w", encoding="utf-8") as log:
        proc = subprocess.run(argv, cwd=output, env=core_cfd.environment(lab), stdout=log, stderr=subprocess.STDOUT)
    elapsed = time.monotonic() - start
    stdout = (output / "solver.stdout.log").read_text(encoding="utf-8", errors="replace")
    if proc.returncode != 0 or "Finished execution (code=0)" not in stdout:
        atomic_json(output / "worker-status.json", {"status": "solver_failed", "returncode": proc.returncode, "elapsed_seconds": elapsed, "finished_at_utc": utc_now()})
        raise RuntimeError("DualSPHysics source solver failed; raw product retained")
    data = solver_dir / "data"
    conversion = core_cfd.convert_native(prepared, data, output / "trajectory.h5")
    atomic_json(output / "conversion.json", {"schema": "core.f3.cfd.native_volume_mls.conversion.v1", **conversion, "native_output_cadence_s": prepared["case"]["output_interval_s"], "interpolation_used": False})
    audit = _audit_hdf5(
        prepared, Path(prepared_path), output / "trajectory.h5", output,
    )
    result = {
        "schema": "core.f3.cfd.native_volume_mls.source_result.v1",
        "case_id": prepared["case"]["case_id"],
        "source_asset_id": prepared["case"]["source_asset_id"],
        "qualification_claim": QUALIFICATION_ONLY,
        "execution_status": "completed",
        "solver_elapsed_seconds": elapsed,
        "native_output_cadence_s": prepared["case"]["output_interval_s"],
        "full_window_s": [0.0, TIME_MAX_S],
        "conversion": conversion,
        "audit": audit,
        "source_h5_sha256": digest(output / "trajectory.h5"),
        "source_h5_bytes": (output / "trajectory.h5").stat().st_size,
        "code_provenance": prepared["source_provenance"],
        "worker_contract": "core_runtime worker; assigned CUDA_VISIBLE_DEVICES is remapped to solver -gpu:0",
        "central_ledger_mutation": 0,
        "gpu_selection_by_module": False,
    }
    atomic_json(output / "source-result.json", result)
    atomic_json(output / "worker-status.json", {"status": "complete_with_evidence", "hard_integrity_pass": audit["hard_integrity_pass"], "finished_at_utc": utc_now()})
    return result


def _job_spec(prepared_path: Path, *, lab: Path, job_id: str, host: str = "ada") -> dict[str, Any]:
    prepared_path = Path(prepared_path).resolve()
    prepared = _validate_prepared(prepared_path, lab=lab)
    python = Path(lab).resolve() / ".venv/bin/python"
    runner = Path(__file__).resolve()
    core_cfd_path = Path(core_cfd.__file__).resolve()
    input_files = [{"path": str(prepared_path), "sha256": digest(prepared_path)}]
    for path, value in prepared["inputs"].items():
        input_files.append({"path": path, "sha256": value})
    input_files.extend([
        {"path": prepared["solver_binary"], "sha256": prepared["solver_sha256"]},
        {"path": prepared["decoder"], "sha256": prepared["decoder_sha256"]},
        {"path": str(runner), "sha256": digest(runner)},
        {"path": str(core_cfd_path), "sha256": digest(core_cfd_path)},
        {"path": str(_lab_path(lab, SOURCE_AUDIT_V2_REL)),
         "sha256": digest(_lab_path(lab, SOURCE_AUDIT_V2_REL))},
        {"path": str(_lab_path(lab, FINITE_WALL_AUDIT_REL)),
         "sha256": digest(_lab_path(lab, FINITE_WALL_AUDIT_REL))},
        {"path": str(_lab_path(lab, STATIC_REPORT_REL)),
         "sha256": digest(_lab_path(lab, STATIC_REPORT_REL))},
        {"path": str(_lab_path(lab, STATIC_PROPOSAL_REL)),
         "sha256": digest(_lab_path(lab, STATIC_PROPOSAL_REL))},
    ])
    # Preserve order while preventing duplicate hash checks for an asset that
    # also appears in the prepared record.
    unique = {}
    for item in input_files:
        unique[item["path"]] = item["sha256"]
    case = prepared["case"]
    return {
        "schema": JOB_SCHEMA,
        "job_id": job_id,
        "logical_id": job_id,
        "attempt_role": "initial",
        "category": "qualification_canary",
        "host": host,
        "source_lab": str(Path(lab).resolve()),
        "cwd": str(Path(lab).resolve()),
        "argv": [str(python), str(runner), "--lab-root", str(Path(lab).resolve()), "run",
                 "--prepared", str(prepared_path), "--output", "{attempt_dir}/product"],
        "required_outputs": [
            "product/trajectory.h5", "product/conversion.json", "product/audit.json",
            "product/source-result.json", "product/prepared.json", "product/worker-status.json",
        ],
        "resources": {
            "cpu_cores": 2,
            "ram_mib": int(case["ram_mib"]),
            "gpu_peak_mib": int(case["gpu_peak_mib"]),
            "io_weight": 1,
        },
        "timeout_seconds": int(case["timeout_seconds"]),
        "depends_on": [],
        "qualification_claim": QUALIFICATION_ONLY,
        "timestep_repair_id": REPAIR_ID,
        "explicit_dt_min_s": EXPLICIT_DT_MIN_S,
        "input_files": [{"path": path, "sha256": value} for path, value in unique.items()],
        "prepared_case_id": case["case_id"],
        "source_asset_id": case["source_asset_id"],
        "matrix_rows": case["matrix_rows"],
        "q": case["q"],
        "drive_amplitude": case["drive_amplitude"],
        "dp_m": case["dp_m"],
        "output_interval_s": case["output_interval_s"],
        "registered_window_s": TIME_MAX_S,
        "expected_native_frames": case["expected_native_frames"],
        "worker_contract": "core_runtime worker; scheduler assigns one CUDA_VISIBLE_DEVICES value and runner invokes -gpu:0",
        "execution_status": "prepared_only",
        "central_ledger_mutation": 0,
        "gpu_started": False,
        "source_provenance": prepared["source_provenance"],
        "output_contract": {
            "attempt_product_dir": "{attempt_dir}/product",
            "native_h5": "product/trajectory.h5",
            "native_output_only": True,
            "interpolation_used": False,
            "source_h5_hash_written_by_runner": True,
        },
    }


def make_job(prepared_path: Path, output: Path, *, job_id: str, host: str = "ada", lab: Path = LAB) -> dict[str, Any]:
    """Write one Core runtime-compatible job spec without submitting it."""
    spec = _job_spec(Path(prepared_path), lab=Path(lab).resolve(), job_id=job_id, host=host)
    # Importing the validator here keeps preparation CPU-only and avoids a
    # queue/ledger side effect.  It catches reserved paths and malformed argv.
    from scripts.core_runtime import validate_spec
    validate_spec(json.loads(json.dumps(spec, allow_nan=False)))
    atomic_json(Path(output), spec)
    return spec


def prepare_all(output_root: Path, *, lab: Path = LAB) -> list[dict[str, Any]]:
    output_root = Path(output_root).resolve()
    records = []
    for case_key, case in source_cases().items():
        record = prepare_case(case_key, output_root / case["source_asset_id"], lab=lab)
        records.append(record)
    return records


def make_jobs(prepared_root: Path, jobs_root: Path, *, host: str = "ada", lab: Path = LAB) -> list[dict[str, Any]]:
    jobs_root = Path(jobs_root).resolve()
    jobs_root.mkdir(parents=True, exist_ok=True)
    specs = []
    for case_key, case in source_cases().items():
        prepared = Path(prepared_root).resolve() / case["source_asset_id"] / "prepared.json"
        spec = make_job(prepared, jobs_root / (case["source_asset_id"] + ".json"),
                        job_id="cfd-" + case["source_asset_id"] + "-v1", host=host, lab=lab)
        specs.append(spec)
    runner = Path(__file__).resolve()
    core_cfd_path = Path(core_cfd.__file__).resolve()
    manifest_jobs = []
    for spec in specs:
        spec_path = jobs_root / (spec["source_asset_id"] + ".json")
        prepared_path = Path(next(item["path"] for item in spec["input_files"]
                                  if item["path"].endswith("/prepared.json")))
        manifest_jobs.append({
            "job_id": spec["job_id"],
            "path": str(spec_path.resolve()),
            "sha256": digest(spec_path),
            "prepared": str(prepared_path),
            "prepared_sha256": digest(prepared_path),
            "prepared_case_id": spec["prepared_case_id"],
            "source_asset_id": spec["source_asset_id"],
            "matrix_rows": spec["matrix_rows"],
            "resources": spec["resources"],
            "timeout_seconds": spec["timeout_seconds"],
        })
    atomic_json(jobs_root / "manifest.json", {
        "schema": "core.f3.cfd.native_volume_mls.source_job_manifest.v1",
        "status": "prepared_only",
        "qualification_claim": QUALIFICATION_ONLY,
        "full_window_s": [0.0, TIME_MAX_S],
        "source_runner": {"path": str(runner), "sha256": digest(runner)},
        "conversion_helper": {"path": str(core_cfd_path), "sha256": digest(core_cfd_path)},
        "proposal_path": str(_lab_path(lab, PROPOSAL_REL)),
        "proposal_sha256": PROPOSAL_SHA256,
        "solver_binary": {"path": str(_lab_path(lab, SOLVER_REL)), "sha256": digest(_lab_path(lab, SOLVER_REL))},
        "decoder": {"path": str(_lab_path(lab, DECODER_REL)), "sha256": digest(_lab_path(lab, DECODER_REL))},
        "host_options": ["ada", "h200"],
        "concurrency_policy": "Core scheduler resource admission may run these jobs concurrently; this source runner has no fixed GPU index or legacy global solver lock.",
        "jobs": manifest_jobs,
        "job_count": len(manifest_jobs),
        "central_ledger_mutation": 0,
        "gpu_started": False,
    })
    return specs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=LAB)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--case", required=True, choices=sorted(source_cases()))
    p.add_argument("--output", type=Path, required=True)
    p = sub.add_parser("prepare-all")
    p.add_argument("--output-root", type=Path, required=True)
    p = sub.add_parser("make-job")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--job-id", required=True)
    p.add_argument("--host", default="ada")
    p = sub.add_parser("make-jobs")
    p.add_argument("--prepared-root", type=Path, required=True)
    p.add_argument("--output-root", type=Path, required=True)
    p.add_argument("--host", default="ada")
    p = sub.add_parser("run")
    p.add_argument("--prepared", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    lab = args.lab_root.resolve()
    if args.command == "prepare":
        result = prepare_case(args.case, args.output, lab=lab)
        print(json.dumps({"status": result["status"], "case_id": result["case"]["case_id"],
                          "prepared_json_sha256": result["prepared_json_sha256"]}, indent=2))
    elif args.command == "prepare-all":
        records = prepare_all(args.output_root, lab=lab)
        print(json.dumps({"status": "prepared_only", "cases": len(records),
                          "case_ids": [x["case"]["case_id"] for x in records]}, indent=2))
    elif args.command == "make-job":
        spec = make_job(args.prepared, args.output, job_id=args.job_id, host=args.host, lab=lab)
        print(json.dumps({"status": spec["execution_status"], "job_id": spec["job_id"],
                          "prepared_case_id": spec["prepared_case_id"]}, indent=2))
    elif args.command == "make-jobs":
        specs = make_jobs(args.prepared_root, args.output_root, host=args.host, lab=lab)
        print(json.dumps({"status": "prepared_only", "jobs": [x["job_id"] for x in specs]}, indent=2))
    else:
        result = run_case(args.prepared, args.output, lab=lab)
        print(json.dumps({"status": result["execution_status"], "case_id": result["case_id"],
                          "source_h5_sha256": result["source_h5_sha256"],
                          "hard_integrity_pass": result["audit"]["hard_integrity_pass"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
