#!/usr/bin/env python3
"""Register and audit the existing F3 weak-dual three-resolution references.

This is an additive, read-only producer.  It consumes the already completed
small JSON/CSV reports and the registered SHA256 of each large trajectory H5;
it deliberately does not rehash or rewrite an H5, start a solver, start a
converter, or start a labels job.  The generated requests are registration
records for a later root-owned bounded audit.  They are not Q-N or production
gates.

The source reports contain two distinct transport products.  The finite-plane
surface replay records x/y crossings, while the older typed-label JSON records
only the top-open aperture aggregate.  This producer keeps both values and
flags their reconciliation as an evidence gap instead of silently combining
them.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


HANDOFF_ROOT = Path(__file__).resolve().parent
F3_ROOT = HANDOFF_ROOT.parents[1]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
DATA_F3 = DATA_ROOT / "families" / "F3"
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
INFRA_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-infra/DualSPHysics")
OFFICIAL_LAB = Path("/home/jade/Projects/DualSPHysics") / "lagrangian-fluid-lab"
PARTVTK = OFFICIAL_LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
DECODER = OFFICIAL_LAB / "campaigns/l1-resume/artifacts/bi4_dump"

PHYSICAL_CASE_ID = "F3_DUAL_AXIS_WEAK_006G_004G"
PHYSICAL_BINDING_SHA = "fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"
CONTROL_SHA = "98cb5a00395301e4e5561d57b8d56189686f468a16f0b4420c6f96c3e4995e6b"
HDF5_CONTROL_REFERENCE_SHA = "0d3202227346dcc1357299f6838741b5d2e91e4da506a75284fb9586a781a635"
OPERATORS_SHA = "21a54faaab3a1f1a56138e2d73f62c90505e506e47e0bf6889fcb843f6e9a7b2"
EVENT_DEFINITIONS = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/event_definitions.json"
OPERATORS = INFRA_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/f3_weak_operators.v1.json"
TRANSPORT_CONFIG = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/f3_weak_full_transport_config.v1.json"
TEMPORAL_ASSESSMENT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/f3_weak_dual_temporal_budget_assessment_001.json"
SCRIPT_PATH = HANDOFF_ROOT / "f3_three_dp_qi_registration_v1.py"

MACRO_AUDIT = DATA_F3 / "F3_DUAL_AXIS_WEAK_006G_004G_MACRO_INPUT_AUDIT/root-nvme-macro-input-audit-001/macro-input-audit.json"
MACRO_SOURCE_BINDINGS = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/handoff_20261002/root_nvme_macro_input_audit_001/source_bindings.json"

CASES: dict[str, dict[str, Any]] = {
    "coarse": {
        "case_id": "F3_WEAK_DUAL_REFERENCE_COARSE",
        "attempt_id": "f3-weak-dual-coarse-direct-v1",
        "resolution": "coarse",
        "dp_m": 0.008181818,
        "data_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE",
        "direct_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-direct-v1",
        "solver_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE/qualification-weak-dual-coarse-reference-001",
        "gencase_root": DATA_F3 / "F3_WEAK_GENC_CASE_DP0P008181818/f3-weak-gencase-dp0p008181818-v1",
        "owner_metadata": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_reference_002/f3_weak_owner_metadata_coarse.json",
        "particle_count": 88528,
        "fluid_particles": 26620,
        "boundary_particles": 61908,
        "hdf5_sha256": "61d14a1a67ab040dfb6728a6b11a1721eb71f83da99468e31cbd8d987aeda2db",
        "hdf5_bytes": 5250144678,
        "audit_h5_rows": 106506620,
        "geometry_reference_sha256": "d9bb2841bdec6a53c1671bd1163d28e0ce8b3ed3ec107894eaa2a84107c15629",
        "numerical_parameters_sha256": "928908e4b7bc892117caaa12d7e600bccdf01cde874af8176c620aab45932a34",
        "solver_receipt_sha256": "1c330ef3c44de834f8f37ff1acd334a49ffdc0d340de00599ce24ce2f09ac213",
        "run_out_sha256": "30b57126df0dac02d682171c896290c797efa8a56db3fb2df7beb9e3021c0be9",
        "runparts_sha256": "d8038291d5eef9a72686c1fda6c016707eb5ec64c8eaf97f1afbbdc31965fbbd",
        "surface_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-surface-audit-v1",
        "labels_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-direct-v1",
        "labels_h5_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_COARSE/f3-weak-dual-coarse-labels-v1",
    },
    "medium": {
        "case_id": PHYSICAL_CASE_ID,
        "attempt_id": "f3-weak-dual-direct-full-v2",
        "resolution": "medium",
        "dp_m": 0.0075,
        "data_root": DATA_F3 / PHYSICAL_CASE_ID,
        "direct_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/f3-weak-dual-direct-full-v2",
        "solver_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/qualification-weak-dual-scope-001",
        "gencase_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/gencase-weak-dual-scope-001",
        "owner_metadata": INFRA_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_scope_001/f3_weak_owner_metadata.json",
        "particle_count": 108000,
        "fluid_particles": 34560,
        "boundary_particles": 73440,
        "hdf5_sha256": "c2cb2f701ef81a1a490764aa9057874c0d61f0d2447416cb4e1f7693daa76fd2",
        "hdf5_bytes": 6577918733,
        "audit_h5_rows": 138274560,
        "geometry_reference_sha256": "790937df79e914055aa00be09540fd4205cbde8bab3130284895c36515172cc4",
        "numerical_parameters_sha256": "50dd8e3fa78f793b74eabb0644e977d1b03e4e8a78869de4a329abe193a30ed1",
        "solver_receipt_sha256": "7d1831657d7dcc228b6b7d91e38ee10b980c34a0fb75cf669b4dc489a6e5e377",
        "run_out_sha256": "6c50c8a17ff8f5a8cd2ac9cfd8397268551be1e5543bb3297cc11e0afc7c375f",
        "runparts_sha256": "4b072d862a0cd21466145d24f904ec6123b305d2da427b58a553d56d968ed173",
        "surface_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/f3-weak-finite-surface-audit-v2",
        "labels_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/f3-weak-dual-direct-full-v2",
        "labels_h5_root": DATA_F3 / f"{PHYSICAL_CASE_ID}/f3-weak-full-transport-labels-v1",
    },
    "fine": {
        "case_id": "F3_WEAK_DUAL_REFERENCE_FINE",
        "attempt_id": "f3-weak-dual-fine-direct-v1",
        "resolution": "fine",
        "dp_m": 0.006,
        "data_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE",
        "direct_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-direct-v1",
        "solver_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE/qualification-weak-dual-fine-reference-001",
        "gencase_root": DATA_F3 / "F3_WEAK_GENC_CASE_DP0P006/f3-weak-gencase-dp0p006-v1",
        "owner_metadata": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F3/weak_dual_reference_002/f3_weak_owner_metadata_fine.json",
        "particle_count": 179208,
        "fluid_particles": 67500,
        "boundary_particles": 111708,
        "hdf5_sha256": "8cf11a279aa4849939982c1b11a1a4260dff0224051795a38880d55dfc74e8be",
        "hdf5_bytes": 11794266383,
        "audit_h5_rows": 270067500,
        "geometry_reference_sha256": "c63aedc04e53f119b5c06b70f9e5aea764b568761b48c5ae796608cc0730db05",
        "numerical_parameters_sha256": "871d6f192e8c5a96be87ac42efbf4b02ca5d9b8a7bf49980758c881492f59732",
        "solver_receipt_sha256": "bf7db863647ef00afde2484f58dc304705abc340615af7c2e8782f82e11f6e3a",
        "run_out_sha256": "becb6169c1ef58fc27fbe90cbaebfd2563ad5000eb5ae1ee5265f3441600ae28",
        "runparts_sha256": "e00e793ce823b877473cf0894528ec462a84282d26284ab347ca9a4206b41366",
        "surface_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-surface-audit-v1",
        "labels_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-direct-v1",
        "labels_h5_root": DATA_F3 / "F3_WEAK_DUAL_REFERENCE_FINE/f3-weak-dual-fine-labels-v1",
    },
}


def require(path: Path, role: str) -> Path:
    path = Path(path).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role} missing: {path}")
    return path


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with require(path, "digest input").open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def binding(path: Path, role: str, *, registered_sha256: str | None = None, registered_bytes: int | None = None) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if registered_sha256 is not None:
        # Large H5 is intentionally bound to the independently completed
        # macro-input audit.  Do not read it again merely to recreate a hash.
        return {
            "path": str(path),
            "sha256": registered_sha256,
            "bytes": registered_bytes,
            "role": role,
            "hash_scope": "registered_external_source_sha256",
            "rehash_performed": False,
        }
    path = require(path, role)
    return {
        "path": str(path),
        "sha256": digest(path),
        "bytes": path.stat().st_size,
        "role": role,
        "hash_scope": "actual_file_sha256",
        "rehash_performed": True,
    }


def load_json(path: Path, role: str) -> dict[str, Any]:
    value = json.loads(require(path, role).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{role} must be a JSON object: {path}")
    return value


def direct_paths(c: dict[str, Any]) -> dict[str, Path]:
    direct = c["direct_root"]
    solver = c["solver_root"]
    gencase = c["gencase_root"]
    surface = c["surface_root"]
    labels = c["labels_root"]
    case = c["case_id"]
    if c["resolution"] == "coarse":
        generated_xml = gencase / "F3_DUAL_AXIS_WEAK_006G_004G_dp0p008181818_Def.xml"
        generated_bi4 = gencase / "F3_DUAL_AXIS_WEAK_006G_004G_dp0p008181818_Def.bi4"
        control = gencase / "F3_DualAxisPhase_WeakControl.csv"
    elif c["resolution"] == "fine":
        generated_xml = gencase / "F3_DUAL_AXIS_WEAK_006G_004G_dp0p006_Def.xml"
        generated_bi4 = gencase / "F3_DUAL_AXIS_WEAK_006G_004G_dp0p006_Def.bi4"
        control = gencase / "F3_DualAxisPhase_WeakControl.csv"
    else:
        generated_xml = gencase / "F3_DUAL_AXIS_WEAK_006G_004G.xml"
        generated_bi4 = gencase / "F3_DUAL_AXIS_WEAK_006G_004G.bi4"
        control = gencase / "F3_DualAxisPhase_WeakControl.csv"
    return {
        "macro_entry": MACRO_AUDIT,
        "direct_report": direct / "direct-conversion-report.json",
        "audit_report": direct / "f3-weak-audit-report.json",
        "trajectory_h5": direct / "trajectory.h5",
        "transport_labels_json": labels / "typed-transport-labels.json",
        "transport_timeseries_csv": labels / "typed-transport-timeseries.csv",
        "surface_report": surface / "f3-weak-finite-surface-audit.json",
        "direct_receipt": direct / "execution-receipt.json",
        "solver_receipt": solver / "execution-receipt.json",
        "run_out": solver / "solver_output/Run.out",
        "runparts": solver / "solver_output/RunPARTs.csv",
        "partinfo": solver / "solver_output/data/PartInfo.ibi4",
        "part_first": solver / "solver_output/data/Part_0000.bi4",
        "part_last": solver / "solver_output/data/Part_4000.bi4",
        "generated_xml": generated_xml,
        "generated_bi4": generated_bi4,
        "control": control,
        "gencase_receipt": gencase / "execution-receipt.json",
        "owner_metadata": c["owner_metadata"],
        "labels_h5": c["labels_h5_root"] / "typed-transport-labels.h5",
        "labels_receipt": c["labels_h5_root"] / "execution-receipt.json",
        "preview_gif": direct / "previews/actual_trajectory.gif",
    }


def macro_entries() -> dict[str, dict[str, Any]]:
    audit = load_json(MACRO_AUDIT, "F3 macro audit")
    result: dict[str, dict[str, Any]] = {}
    for entry in audit.get("inputs", []):
        role = entry.get("role")
        if role in CASES:
            result[role] = entry
    if set(result) != set(CASES):
        raise ValueError(f"macro audit roles are incomplete: {sorted(result)}")
    return result


def number(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    if value is None or value == "":
        raise ValueError(f"missing RunPARTs field {key}")
    return float(value.replace(",", ""))


def runparts_summary(path: Path, c: dict[str, Any]) -> dict[str, Any]:
    rows: list[dict[str, str]] = []
    with require(path, "RunPARTs").open(newline="") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            try:
                int(row.get("Part", ""))
            except (TypeError, ValueError):
                continue
            rows.append(row)
    if len(rows) != 4001:
        raise ValueError(f"{c['resolution']} RunPARTs numeric rows={len(rows)}, expected 4001")
    times = [number(row, "TimeStep [s]") for row in rows]
    np_sim = [int(round(number(row, "NpSim"))) for row in rows]
    npf_sim = [int(round(number(row, "NpfSim"))) for row in rows]
    npb_sim = [int(round(number(row, "NpbSim"))) for row in rows]
    out_fields = {key: [int(round(number(row, key))) for row in rows] for key in ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")}
    dt_min = [number(row, "DtMin [s]") for row in rows]
    dt_max = [number(row, "DtMax [s]") for row in rows]
    expected_total = c["particle_count"]
    expected_fluid = c["fluid_particles"]
    expected_boundary = c["boundary_particles"]
    return {
        "runparts_sha256": digest(path),
        "numeric_rows": len(rows),
        "first_time_s": times[0],
        "last_time_s": times[-1],
        "strict_time_increase_after_frame_zero": all(a < b for a, b in zip(times, times[1:])),
        "NpSim_min": min(np_sim),
        "NpSim_max": max(np_sim),
        "NpfSim_min": min(npf_sim),
        "NpfSim_max": max(npf_sim),
        "NpbSim_min": min(npb_sim),
        "NpbSim_max": max(npb_sim),
        "expected_population_match": (
            min(np_sim) == max(np_sim) == expected_total
            and min(npf_sim) == max(npf_sim) == expected_fluid
            and min(npb_sim) == max(npb_sim) == expected_boundary
        ),
        "excluded_interval_sums": {key: sum(values) for key, values in out_fields.items()},
        "excluded_interval_max": {key: max(values) for key, values in out_fields.items()},
        "excluded_all_zero": all(sum(values) == 0 for values in out_fields.values()),
        "dt_min_first_s": dt_min[0],
        "dt_min_post_initial_min_s": min(dt_min[1:]),
        "dt_min_post_initial_max_s": max(dt_min[1:]),
        "dt_max_post_initial_min_s": min(dt_max[1:]),
        "dt_max_post_initial_max_s": max(dt_max[1:]),
        "full_window_completed": times[-1] >= 10.0,
    }


def first_passage_summary(surface: dict[str, Any], c: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    particles = surface.get("per_particle", [])
    for event_id in ("left_right_exchange", "front_back_exchange", "top_open_exit"):
        first = [p[event_id].get("first_passage_s") for p in particles if p.get(event_id, {}).get("first_passage_s") is not None]
        crossings = [int(p.get(event_id, {}).get("crossing_count", 0)) for p in particles]
        result[event_id] = {
            "identity_rows": len(particles),
            "identities_with_first_passage": len(first),
            "first_passage_min_s": min(first) if first else None,
            "first_passage_max_s": max(first) if first else None,
            "first_passage_present": bool(first),
            "crossing_count_sum": sum(crossings),
            "crossing_count_max": max(crossings) if crossings else 0,
            "source": "finite-surface-audit per_particle; linear chord crossing time",
        }
    return result


def surface_summary(surface: dict[str, Any]) -> dict[str, Any]:
    fields = (
        "candidate_crossings", "accepted_crossings", "aperture_rejected_crossings",
        "positive_crossings", "negative_crossings", "repeat_crossings",
        "positive_crossing_mass_kg", "negative_crossing_mass_kg", "net_crossing_mass_kg",
        "particle_count_with_crossing", "classification",
    )
    return {event_id: {key: record.get(key) for key in fields} for event_id, record in surface.get("surfaces", {}).items()}


def get_h5_entry(role: str, entries: dict[str, dict[str, Any]]) -> dict[str, Any]:
    entry = entries[role]
    return {
        "path": entry["path"],
        "sha256": entry["registered_source_sha256"],
        "bytes": entry["bytes"],
        "frames": entry["frames"],
        "particles": entry["particles"],
        "initial_fluid_particles": entry["initial_fluid_particles"],
        "initial_fluid_rows_checked": entry["counts"]["fluid_rows_checked"],
        "hash_scope": "macro_input_audit_registered_source_sha256",
        "rehash_performed": False,
    }


def source_bindings(c: dict[str, Any], p: dict[str, Path], h5: dict[str, Any]) -> dict[str, Any]:
    return {
        "trajectory_h5": h5,
        "direct_conversion_report": binding(p["direct_report"], "completed direct conversion report"),
        "direct_conversion_receipt": binding(p["direct_receipt"], "completed direct conversion receipt"),
        "audit_report": binding(p["audit_report"], "completed bounded Q-I audit report"),
        "surface_report": binding(p["surface_report"], "completed finite-surface replay report"),
        "transport_labels_json": binding(p["transport_labels_json"], "existing typed transport JSON"),
        "transport_timeseries_csv": binding(p["transport_timeseries_csv"], "existing typed transport timeseries"),
        "solver_receipt": binding(p["solver_receipt"], "terminal solver receipt"),
        "run_out": binding(p["run_out"], "terminal Run.out"),
        "runparts": binding(p["runparts"], "terminal RunPARTs ledger"),
        "partinfo": binding(p["partinfo"], "native PartInfo BI4"),
        "part_first": binding(p["part_first"], "native first Part BI4"),
        "part_last": binding(p["part_last"], "native last Part BI4"),
        "generated_xml": binding(p["generated_xml"], "actual generated XML"),
        "generated_bi4": binding(p["generated_bi4"], "actual GenCase BI4"),
        "control_csv": binding(p["control"], "actual copied control CSV"),
        "gencase_receipt": binding(p["gencase_receipt"], "completed GenCase receipt"),
        "owner_metadata_source": binding(p["owner_metadata"], "historical owner metadata source"),
        "operators": binding(OPERATORS, "frozen F3 operator schema"),
        "transport_config": binding(TRANSPORT_CONFIG, "frozen F3 transport config"),
        "event_definitions": binding(EVENT_DEFINITIONS, "frozen F3 event definitions"),
        "partvtk": binding(PARTVTK, "official PartVTK binary"),
        "bi4_decoder": binding(DECODER, "official BI4 decoder"),
    }


def make_contract(c: dict[str, Any], p: dict[str, Path], h5: dict[str, Any], audit: dict[str, Any], direct: dict[str, Any], surface: dict[str, Any], labels: dict[str, Any], runparts: dict[str, Any], bindings: dict[str, Any]) -> dict[str, Any]:
    native = audit.get("native_accounting", {})
    native_case_id = native.get("case_id")
    native_receipt = native.get("receipt", {}).get("path")
    expected_receipt = str(p["solver_receipt"].resolve())
    native_binding_gap = native_case_id != c["case_id"] or native_receipt != expected_receipt
    direct_qi = direct.get("q_i_status")
    audit_qi = audit.get("q_i_status")
    h5_qi = audit.get("hdf5_qi", {})
    direct_lifecycle = direct.get("lifecycle", {})
    labels_aggregate = labels.get("aggregate", {})
    surface_events = surface_summary(surface)
    label_surface_mismatch = any(
        (surface_events.get(event_id, {}).get("accepted_crossings") or 0) != 0
        and (labels_aggregate.get("positive_crossings", 0) == 0 and labels_aggregate.get("negative_crossings", 0) == 0)
        for event_id in ("left_right_exchange", "front_back_exchange")
    )
    report_h5_sha = direct.get("output_sha256")
    if report_h5_sha != h5["sha256"]:
        raise ValueError(f"{c['resolution']} direct report H5 SHA does not match macro binding")
    expected_control = direct.get("source_provenance", {}).get("control_sha256")
    return {
        "schema": "ds02.f3.three-dp-qi-source-contract.v1",
        "status": "registered_reference_evidence_pending_root_qi_review",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "family_id": "F3",
        "case_id": c["case_id"],
        "physical_case_id": PHYSICAL_CASE_ID,
        "physical_binding": {
            "physical_binding_sha256": PHYSICAL_BINDING_SHA,
            "lineage_group_id": "F3_WEAK_DUAL_CONTINUOUS_TANK",
            "paired_background_id": "F3_WEAK_DUAL_SINGLE_BACKGROUND",
            "mechanism_id": "dual_axis_phase",
            "geometry_family_id": "continuous_tank_0p9x0p18x0p51_open_top",
            "control_family_id": "weak_dual_axis_0p06g_0p04g",
            "geometry": {
                "tank_low_m": [-0.45, -0.09, 0.0],
                "tank_size_m": [0.9, 0.18, 0.51],
                "initial_fluid_low_m": [-0.45, -0.09, 0.0],
                "initial_fluid_size_m": [0.9, 0.18, 0.09],
                "top_open": True,
                "physical_open_faces": ["top"],
                "periodic_boundary": False,
            },
            "initial_state": {
                "density_kg_m3": 1000.0,
                "continuum_volume_m3": 0.01458,
                "continuum_mass_kg": 14.58,
                "mass_policy": "native MassFluid; no normalization or rescaling",
                "initial_velocity_m_per_s": [0.0, 0.0, 0.0],
                "source_label": "fluid",
            },
            "control": {
                "control_file_sha256": CONTROL_SHA,
                "hdf5_control_reference_sha256": HDF5_CONTROL_REFERENCE_SHA,
                "generated_control_reference_sha256": expected_control,
                "weak_peak_x_g": 0.06,
                "weak_peak_y_g": 0.04,
                "gravity_m_s2": [0.0, 0.0, -9.81],
                "boundary_parameter": 2,
                "no_penetration": 1,
                "slip_mode": 2,
                "kernel": "Wendland (Kernel=2)",
                "density_dt": "Fourtakas full (DensityDT=3)",
                "step_algorithm": "Symplectic (StepAlgorithm=2)",
                "viscosity_value": 0.05,
            },
        },
        "numerical_recipe": {
            "resolution_role": c["resolution"],
            "dp_m": c["dp_m"],
            "numerical_parameters_sha256": c["numerical_parameters_sha256"],
            "save_interval_nominal_s": 0.0025,
            "window_s": [0.0, 10.0],
            "frames": 4001,
            "solver_dimension": 3,
            "data2d": False,
            "native_internal_dt_source": "RunPARTs / native accounting; exact value retained per resolution",
            "same_physical_condition_as_other_resolutions": True,
            "numeric_parameters_excluded_from_physical_binding": True,
        },
        "state_schema": {
            "coordinate_frame": "DualSPHysics case Cartesian coordinates (x,y,z)",
            "units": {"time": "s", "position": "m", "velocity": "m/s", "mass": "kg", "density": "kg/m^3", "pressure": "Pa"},
            "identity_key": "(Zone,Idp)",
            "fluid_type": 3,
            "fixed_type": 0,
            "required_fields": ["time_s", "Zone", "Idp", "position", "velocity", "mass", "density", "pressure", "type", "mk", "valid"],
        },
        "source_bindings": bindings,
        "actual_terminal_evidence": {
            "trajectory_h5": h5,
            "direct_conversion_report_q_i_text": direct_qi,
            "audit_report_q_i_text": audit_qi,
            "frames": direct.get("frames"),
            "particles": direct.get("particles"),
            "time_evidence": direct.get("time_evidence"),
            "solver_dimension": direct.get("solver_dimension"),
            "partvtk_validation": {"all_passed": direct.get("partvtk_validation", {}).get("all_passed"), "validated_frames": [f.get("frame") for f in direct.get("partvtk_validation", {}).get("frames", [])]},
            "lifecycle": {
                "contract": direct_lifecycle.get("contract"),
                "first_missing_frame_by_type": direct_lifecycle.get("first_missing_frame_by_type"),
                "first_missing_frame_by_mk": direct_lifecycle.get("first_missing_frame_by_mk"),
                "initial_exclusion_ledger": direct.get("typed_identity", {}).get("initial_exclusion_ledger"),
            },
            "runparts": runparts,
            "initial_mass": {
                "continuum_mass_kg": h5_qi.get("expected_continuum_mass_kg"),
                "native_initial_fluid_mass_kg": h5_qi.get("initial_fluid_mass_kg"),
                "relative_error": h5_qi.get("initial_mass_relative_error"),
                "within_existing_1pct_initialization_budget": bool(h5_qi.get("initial_mass_within_budget", abs(h5_qi.get("initial_mass_relative_error", 1.0)) <= 0.01)),
            },
            "finite_surface_replay": surface_events,
            "first_passage": first_passage_summary(surface, c),
            "typed_label_aggregate": labels_aggregate,
        },
        "audit_findings": {
            "native_accounting_binding": {
                "status": "gap" if native_binding_gap else "pass",
                "report_case_id": native_case_id,
                "expected_case_id": c["case_id"],
                "report_solver_receipt": native_receipt,
                "expected_solver_receipt": expected_receipt,
                "reason": "Existing audit native_accounting must be rebound to this resolution; original report is immutable." if native_binding_gap else "Native accounting case and solver receipt match this resolution.",
            },
            "surface_vs_typed_label_flux": {
                "status": "reconciliation_required" if label_surface_mismatch else "consistent_zero_flux",
                "surface_x_y_crossings_present": label_surface_mismatch,
                "typed_label_aggregate_x_y_crossings": {
                    "positive": labels_aggregate.get("positive_crossings", 0),
                    "negative": labels_aggregate.get("negative_crossings", 0),
                },
                "meaning": "Surface replay and typed-label JSON are distinct products; retain both until an operator-specific binding is produced.",
            },
            "hdf5_raw_hash": {
                "status": "bound_without_rehash",
                "source": "macro_input_audit",
                "reason": "Avoid repeated multi-GB H5 read; existing registered SHA and direct report output SHA agree.",
            },
        },
        "missing_or_deferred": [
            "Q-N numerical reference comparison is not assessed.",
            "A complete x/y exchange transport label artifact with source/destination/residence semantics is not bound to the finite-surface replay.",
            "Top-open exit has no observed crossing; all identities are right-censored for this event and must not be called zero physical spill.",
            "Save/integration temporal budget is not proven per resolution; only the existing medium baseline versus HALF_DT diagnostic exists and its share-cap status is exceeded.",
            "Residence-time budget is not registered; reported residence is accounting only.",
        ] + (["Fine historical native_accounting report is cross-bound to coarse; a fresh fine-specific accounting sidecar is required."] if native_binding_gap else []),
    }


def make_request(c: dict[str, Any], contract: dict[str, Any], p: dict[str, Path], contract_path: Path) -> dict[str, Any]:
    case = c["case_id"].lower().replace("_", "-")
    attempt_id = f"f3-weak-dual-{c['resolution']}-qi-bounded-audit-20261003-001"
    input_paths = [
        SCRIPT_PATH, MACRO_AUDIT, MACRO_SOURCE_BINDINGS,
        p["audit_report"], p["direct_report"], p["surface_report"],
        p["transport_labels_json"], p["transport_timeseries_csv"],
        p["solver_receipt"], p["run_out"], p["runparts"],
        p["generated_xml"], p["generated_bi4"], p["control"],
        p["gencase_receipt"], p["owner_metadata"], OPERATORS,
        TRANSPORT_CONFIG, EVENT_DEFINITIONS, TEMPORAL_ASSESSMENT,
    ]
    input_paths = [require(path, "request input") for path in input_paths]
    input_hashes = {str(path): digest(path) for path in input_paths}
    return {
        "schema": "ds02.runner-request.v2",
        "status": "registered_only_root_review_required",
        "runnable": False,
        "launch_allowed": False,
        "root_only": True,
        "cpu_task_kind": "bounded_json_csv_qi_audit",
        "attempt_id": attempt_id,
        "case_id": c["case_id"],
        "physical_case_id": PHYSICAL_CASE_ID,
        "family_id": "F3",
        "resolution": c["resolution"],
        "command": [sys.executable, str(SCRIPT_PATH), "--case", c["resolution"], "--output", "{attempt_root}/bounded-audit.json"],
        "cwd": str(F3_ROOT.parents[3]),
        "cpu_threads": 2,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 536870912,
        "input_files": [str(path) for path in input_paths],
        "input_hashes": input_hashes,
        "source_contract": {
            "path": str(contract_path.resolve()),
            "hash_scope": "expected_contract_sha256",
            "included_in_input_hashes": False,
        },
        "source_bindings": {
            "terminal_solver_receipt": contract["source_bindings"]["solver_receipt"],
            "terminal_runparts": contract["source_bindings"]["runparts"],
            "trajectory_h5": contract["source_bindings"]["trajectory_h5"],
            "direct_conversion_report": contract["source_bindings"]["direct_conversion_report"],
        },
        "large_h5_policy": {
            "read_h5": False,
            "rehash_h5": False,
            "registered_sha_must_match_direct_report": True,
            "source_hash_authority": "macro_input_audit plus direct-conversion-report output_sha256",
        },
        "audit_scope": {
            "checks": [
                "3D and data2d=false from actual conversion/Run.out evidence",
                "4001 numeric RunPARTs rows and full 0-10 s timeline",
                "all native NpOut fields summed over the full timeline",
                "constant NpSim/NpfSim/NpbSim population identity",
                "native initial mass and frozen continuum mass",
                "physical/control/geometry source binding",
                "finite-plane replay versus typed-label aggregate reconciliation",
                "first-passage presence and residence budget state",
            ],
            "no_qn_grant": True,
        },
        "expected_contract_sha256": hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":")).encode()).hexdigest(),
        "postprocess_followup": "Do not bind quarter labels until root observes the terminal quarter conversion receipt; no solver/conversion launch is authorized by this request.",
    }


def build_case(role: str, entries: dict[str, dict[str, Any]], output_root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    c = CASES[role]
    p = direct_paths(c)
    macro = entries[role]
    h5 = get_h5_entry(role, entries)
    audit = load_json(p["audit_report"], f"{role} audit report")
    direct = load_json(p["direct_report"], f"{role} direct conversion report")
    surface = load_json(p["surface_report"], f"{role} finite surface report")
    labels = load_json(p["transport_labels_json"], f"{role} typed labels JSON")
    runparts = runparts_summary(p["runparts"], c)
    if runparts["runparts_sha256"] != c["runparts_sha256"]:
        raise ValueError(f"{role} RunPARTs SHA changed from registered terminal endpoint")
    if runparts["numeric_rows"] != macro["frames"]:
        raise ValueError(f"{role} RunPARTs rows disagree with macro audit frames")
    bindings = source_bindings(c, p, h5)
    contract = make_contract(c, p, h5, audit, direct, surface, labels, runparts, bindings)
    contract_path = output_root / "source_contracts" / f"{role}.source-contract.v1.json"
    contract_path.parent.mkdir(parents=True, exist_ok=True)
    contract_path.write_text(json.dumps(contract, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    request = make_request(c, contract, p, contract_path)
    request_path = output_root / "requests" / f"{role}.bounded-audit-request.v1.json"
    request_path.parent.mkdir(parents=True, exist_ok=True)
    request_path.write_text(json.dumps(request, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return contract, request


def build_all(output_root: Path) -> dict[str, Any]:
    entries = macro_entries()
    output_root.mkdir(parents=True, exist_ok=True)
    contracts: dict[str, dict[str, Any]] = {}
    requests: dict[str, dict[str, Any]] = {}
    for role in ("coarse", "medium", "fine"):
        contract, request = build_case(role, entries, output_root)
        contracts[role] = contract
        requests[role] = request
    assessment = load_json(TEMPORAL_ASSESSMENT, "frozen temporal budget assessment")
    report = {
        "schema": "ds02.f3.three-dp-qi-bounded-audit.v1",
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "family_id": "F3",
        "physical_case_id": PHYSICAL_CASE_ID,
        "status": "reference_qi_evidence_registered_qn_pending",
        "qualification_claim": "none",
        "q_n_status": "not_assessed",
        "production_eligibility": "not_evaluated",
        "macro_input_audit": binding(MACRO_AUDIT, "completed four-input finite-positive macro audit"),
        "macro_source_bindings": binding(MACRO_SOURCE_BINDINGS, "macro audit source-binding config"),
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "common_physical_contract": {
            "geometry": {"tank_low_m": [-0.45, -0.09, 0.0], "tank_size_m": [0.9, 0.18, 0.51], "fluid_size_m": [0.9, 0.18, 0.09], "top_open": True},
            "control_file_sha256": CONTROL_SHA,
            "gravity_m_s2": [0.0, 0.0, -9.81],
            "window_s": [0.0, 10.0],
            "nominal_save_interval_s": 0.0025,
            "density_kg_m3": 1000.0,
            "continuum_mass_kg": 14.58,
        },
        "resolutions": {
            role: {
                "case_id": contracts[role]["case_id"],
                "source_contract": str((output_root / "source_contracts" / f"{role}.source-contract.v1.json").resolve()),
                "bounded_audit_request": str((output_root / "requests" / f"{role}.bounded-audit-request.v1.json").resolve()),
                "q_i_evidence_status": contracts[role]["status"],
                "runparts": contracts[role]["actual_terminal_evidence"]["runparts"],
                "finite_surface_replay": contracts[role]["actual_terminal_evidence"]["finite_surface_replay"],
                "first_passage": contracts[role]["actual_terminal_evidence"]["first_passage"],
                "findings": contracts[role]["audit_findings"],
                "missing_or_deferred": contracts[role]["missing_or_deferred"],
            }
            for role in ("coarse", "medium", "fine")
        },
        "frozen_budget_contract": {
            # The campaign freezes macro observable tolerance at 5%; the
            # event-time tolerance is a separate 2% contract.  Do not derive
            # one from the other when materialising the handoff metadata.
            "macro_relative_starting_budget": 0.05,
            "event_time_relative_starting_budget": assessment["registration"]["event_time_relative_starting_budget"] if "registration" in assessment else 0.02,
            "save_or_integration_share_cap": assessment["registration"]["save_or_integration_share_cap"] if "registration" in assessment else 0.2,
            "derived_save_or_integration_fraction_of_event_time": assessment["registration"]["derived_save_or_integration_fraction_of_event_time"] if "registration" in assessment else 0.004,
            "residence_time_budget_registered": assessment["registration"]["residence_time_budget_registered"] if "registration" in assessment else False,
            "source_assessment": binding(TEMPORAL_ASSESSMENT, "frozen temporal budget assessment"),
            "status": assessment.get("assessment_status", "not_assessed"),
            "observed_medium_temporal_diagnostic": {
                "left_right_chord_relative_delta": -0.010788394747056574,
                "front_back_chord_relative_delta": -0.014666348001670111,
                "share_cap_status": "exceeded_on_two_observed_events",
                "scope": "medium baseline versus HALF_DT only; does not qualify coarse/fine",
            },
        },
        "temporal_quarter_followup": {
            "status": "deferred_until_terminal_quarter_conversion_and_labels",
            "root_owned": True,
            "quarter_solver_receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_DUAL_AXIS_WEAK_006G_004G_QUARTER_DT/qualification-weak-dual-quarter_dt-root-reviewed-20261002-002/execution-receipt.json",
            "label_sha256": None,
            "bind_label_hash_before_dispatch": True,
            "no_label_binding_performed": True,
        },
        "source_hash_semantics": {
            "physical_binding": "geometry/initial state/control/window only; same across DP",
            "numerical_recipe": "dp/internal dt/save/integrator; resolution-specific",
            "trajectory_h5": "macro audit registered SHA plus direct conversion output SHA, no new H5 read",
            "control_file": CONTROL_SHA,
            "hdf5_control_reference": HDF5_CONTROL_REFERENCE_SHA,
        },
        "requests_are_registration_only": True,
    }
    report_path = output_root / "three-dp-qi-bounded-audit-001.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "schema": "ds02.f3.three-dp-qi-registration-manifest.v1",
        "audit_report": str(report_path.resolve()),
        "audit_report_sha256": digest(report_path),
        "source_contracts": {role: str((output_root / "source_contracts" / f"{role}.source-contract.v1.json").resolve()) for role in contracts},
        "requests": {role: str((output_root / "requests" / f"{role}.bounded-audit-request.v1.json").resolve()) for role in requests},
        "status": "root_review_required_qn_pending",
    }
    (output_root / "three-dp-qi-registration-manifest.v1.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return {"report": report, "manifest": manifest, "contracts": contracts, "requests": requests}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["coarse", "medium", "fine", "all"], default="all")
    parser.add_argument("--output", type=Path, default=HANDOFF_ROOT / "generated")
    args = parser.parse_args()
    if args.case != "all":
        # A single-case audit still writes a self-contained contract/request;
        # the registration manifest is produced only by the all-case path.
        entries = macro_entries()
        c = CASES[args.case]
        p = direct_paths(c)
        h5 = get_h5_entry(args.case, entries)
        audit = load_json(p["audit_report"], f"{args.case} audit report")
        direct = load_json(p["direct_report"], f"{args.case} direct report")
        surface = load_json(p["surface_report"], f"{args.case} surface report")
        labels = load_json(p["transport_labels_json"], f"{args.case} labels JSON")
        runparts = runparts_summary(p["runparts"], c)
        contract = make_contract(c, p, h5, audit, direct, surface, labels, runparts, source_bindings(c, p, h5))
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "bounded-audit.json").write_text(json.dumps({"schema": "ds02.f3.single-dp-bounded-audit.v1", "contract": contract}, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    else:
        build_all(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
