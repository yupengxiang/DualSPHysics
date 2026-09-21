#!/usr/bin/env python3
"""Prepare the preregistered F4 native-cadence material canary.

The pair uses the same terminal cell-14 CFD trajectory twice:

* the native 0.004 s source with material RK2 substeps=2;
* an exact every-fifth-frame H5 view with substeps=10.

Both material paths therefore use the same maximum tracer integration step
while only the saved reference-frame cadence changes.  The older cell-04
0.02 s run is retained as historical context and is not used as the causal
pair.  This script only audits terminal inputs and writes immutable proposal
JSON; it never launches a worker or writes the central ledger.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

import h5py
import numpy as np

LAB_ROOT = Path(__file__).resolve().parents[1]
if str(LAB_ROOT) not in sys.path:
    sys.path.insert(0, str(LAB_ROOT))

from scripts import f4_tallwall120_frame_stride_view as stride_view
from scripts import f4_tallwall120_material as material


CELL04_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/f4-tallwall120-qualification-cell-04"
CELL14_DIR = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-archives-v2/f4-tallwall120-qualification-cell-14"
CELL04_H5 = CELL04_DIR / "product/trajectory.h5"
CELL14_H5 = CELL14_DIR / "product/trajectory.h5"
CELL04_PREPARED_DIR = LAB_ROOT / "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/cell-04"
CELL14_PREPARED_DIR = LAB_ROOT / "campaigns/core-v1/cfd/prepared/F4_tallwall120_qualification_v2/cell-14"
VIEW_H5 = LAB_ROOT / "campaigns/core-v1/material/derived/f4-tallwall120-native004-stride5/trajectory.h5"
VIEW_MANIFEST = VIEW_H5.with_suffix(VIEW_H5.suffix + ".manifest.json")
T1_COMPLETE = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-qualification-independent-root-complete-v1.json"
CELL04_VERIFICATION = LAB_ROOT / "campaigns/core-v1/cfd/f4-tallwall120-cell04-root-verification-v1.json"
TRACER = LAB_ROOT / "scripts/f4_tallwall120_material.py"
CORE_MATERIAL = LAB_ROOT / "scripts/core_material.py"
NEIGHBOURS = LAB_ROOT / "scripts/f3_material_neighbors.py"
PASSIVE = LAB_ROOT / "scripts/passive_tracers.py"
STRIDE_BUILDER = LAB_ROOT / "scripts/f4_tallwall120_frame_stride_view.py"
PROPOSAL_BUILDER = LAB_ROOT / "scripts/f4_tallwall120_cadence_proposal.py"
SOLVER_BINARY = LAB_ROOT / "vendor/official/DualSPHysics_v5.4/bin/linux/DualSPHysics5.4_linux64"
DECODER = LAB_ROOT / "campaigns/l1-resume/artifacts/bi4_dump"
SOURCE_TEMPLATE = LAB_ROOT / "campaigns/l1-resume/artifacts/f3-revision075/F3_REV075_R075-ENDPOINT-LOW-0075/F3_CELL3_plain_0p0075_Def.xml"

SOURCE14_H5_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
SOURCE04_H5_SHA256 = "78631cec15acdd5abcd5c43f326c2dd7c215b3248fd99ec544718bca72a74cad"
VIEW_STRIDE = 5
Q = 0.5
DP_M = 0.0075
SEEDS = 512
DENSE_SUBSTEPS = 2
VIEW_SUBSTEPS = 10
DENSE_STOP_AFTER = 100
VIEW_STOP_AFTER = 20
SOURCE_WINDOW_S = 4.34
EXPECTED_NATIVE_INTERVAL_S = 0.004
EXPECTED_STRIDE_INTERVAL_S = 0.02


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ref(path: Path, role: str) -> dict:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{role}: {path}")
    return {"path": str(path), "sha256": sha256(path), "role": role}


def load(path: Path) -> dict:
    return json.loads(Path(path).read_text())


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _normalise_config(config: dict) -> dict:
    value = deepcopy(config)
    for key in ("case_id", "design_cell", "output_interval_s", "time_control_variant", "time_control_contract"):
        value.pop(key, None)
    registered = value.get("registered_window")
    if isinstance(registered, dict):
        registered.pop("output_interval_s", None)
    return value


def _normalise_xml(text: str) -> str:
    value = re.sub(r'date="[^"]+"', 'date="<generated-date>"', text)
    value = re.sub(r'(<parameter key="TimeOut" value=")[^"]+("[^>]*>)', r'\1<CADENCE>\2', value)
    value = re.sub(r'(<vtkfile name=")[^"]+("[^>]*>)', r'\1<VTK_NAME>\2', value)
    return value


def _assert_case(prepared_dir: Path, *, expected_interval: float, expected_case_id: str):
    prepared_path = prepared_dir / "prepared.json"
    prepared = load(prepared_path)
    cfg = prepared["config"]
    if cfg.get("case_id") != expected_case_id:
        raise ValueError(f"unexpected prepared case: {cfg.get('case_id')!r}")
    if float(cfg["parameter"]["q"]) != Q or float(cfg["dp_m"]) != DP_M:
        raise ValueError("q/dp binding mismatch")
    if float(cfg["output_interval_s"]) != expected_interval:
        raise ValueError("prepared config output cadence mismatch")
    for key in ("gravity_m_s2", "initial_drop_velocity_m_s", "pool", "drop", "wall_bounds", "closed_faces", "open_faces", "container_height_m", "time_max_s", "cfl", "physical_case_id", "lineage_group_id", "physical_kinematic_viscosity_m2_s", "viscosity_formulation", "observation_version"):
        if key not in cfg:
            raise ValueError(f"missing physical control {key}")
    return prepared


def _verify_archive(directory: Path, source_h5: Path, expected_sha: str) -> dict:
    archive_path = directory / "archive.json"
    archive = load(archive_path)
    if archive.get("schema") != "core.verified_archive.v1" or archive.get("execution_status") != "succeeded":
        raise ValueError(f"archive is not a succeeded verified archive: {archive_path}")
    actual = sha256(source_h5)
    if actual != expected_sha:
        raise ValueError(f"source hash mismatch: {source_h5}")
    outputs = {row.get("path"): row for row in archive.get("outputs", []) if isinstance(row, dict)}
    if outputs.get("product/trajectory.h5", {}).get("sha256") != expected_sha:
        raise ValueError("archive does not bind trajectory source hash")
    audit = load(directory / "product/audit.json")
    if not audit.get("hard_integrity_pass") or not audit.get("source_mass_gate_pass"):
        raise ValueError(f"source audit failed: {source_h5}")
    return {
        "archive": ref(archive_path, "terminal_verified_archive"),
        "result": ref(directory / "product/result.json", "native_source_result"),
        "audit": ref(directory / "product/audit.json", "native_source_audit"),
        "observations": ref(directory / "product/observations.json", "native_source_observations"),
        "source_h5": ref(source_h5, "terminal_root_verified_native_trajectory"),
        "archive_record": archive,
        "audit_record": audit,
    }


def _dataset_names(h5: h5py.File) -> list[str]:
    return [name for name in ("position", "velocity", "density", "mass", "pressure", "valid", "mk", "type") if name in h5]


def _equal_nan(a: np.ndarray, b: np.ndarray) -> bool:
    if a.shape != b.shape or a.dtype != b.dtype:
        return False
    if np.issubdtype(a.dtype, np.floating):
        return bool(np.array_equal(a, b, equal_nan=True))
    return bool(np.array_equal(a, b))


def audit_pair(cell04_prepared: dict, cell14_prepared: dict, cell04: dict, cell14: dict) -> dict:
    with h5py.File(CELL04_H5, "r") as old, h5py.File(CELL14_H5, "r") as dense, h5py.File(VIEW_H5, "r") as view:
        old_times = np.asarray(old["time"][:], dtype=np.float64)
        dense_times = np.asarray(dense["time"][:], dtype=np.float64)
        view_times = np.asarray(view["time"][:], dtype=np.float64)
        if old_times.shape != (218,) or dense_times.shape != (1086,) or view_times.shape != (218,):
            raise ValueError("unexpected source/view frame count")
        if not np.array_equal(dense_times[::VIEW_STRIDE], old_times):
            raise ValueError("cell-14 every-fifth times do not exactly match cell-04 times")
        if not np.array_equal(view_times, dense_times[::VIEW_STRIDE]):
            raise ValueError("derived view time axis is not exact source row selection")
        if abs(float(dense_times[100]) - 0.4) > 0.002 or abs(float(view_times[20]) - float(dense_times[100])) > 1e-12:
            raise ValueError("canary endpoint is not the registered 100/20 interval endpoint")
        dataset_mismatches = []
        for frame04, frame14 in enumerate(range(0, len(dense_times), VIEW_STRIDE)):
            for name in _dataset_names(old):
                a = old[name][frame04]
                b = dense[name][frame14]
                if not _equal_nan(a, b):
                    dataset_mismatches.append({"frame04": frame04, "frame14": frame14, "dataset": name})
                c = view[name][frame04]
                if not _equal_nan(b, c):
                    dataset_mismatches.append({"frame14": frame14, "view_frame": frame04, "dataset": name, "reason": "view_copy"})
        dense_dt = np.diff(dense_times)
        view_dt = np.diff(view_times)
        dense_control = _normalise_config(cell14_prepared["config"])
        old_control = _normalise_config(cell04_prepared["config"])
        xml_old_path = CELL04_PREPARED_DIR / "generated/F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL.xml"
        xml_dense_path = CELL14_PREPARED_DIR / "generated/F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_NATIVE_OUTPUT.xml"
        xml_old = xml_old_path.read_text()
        xml_dense = xml_dense_path.read_text()
        normalized_xml_equal = _normalise_xml(xml_old) == _normalise_xml(xml_dense)
        view_attrs = {key: view.attrs[key] for key in ("view_schema", "view_source_sha256", "view_stride", "view_selection_rule", "view_exact_rows_no_interpolation", "view_source_frame_count", "view_frame_count")}

    metadata_warning = {
        "cell14_prepared_config_output_interval_s": float(cell14_prepared["config"]["output_interval_s"]),
        "cell14_prepared_registered_window_output_interval_s": float(cell14_prepared["config"]["registered_window"]["output_interval_s"]),
        "actual_cell14_xml_timeout_s": EXPECTED_NATIVE_INTERVAL_S,
        "actual_cell14_h5_median_interval_s": float(np.median(dense_dt)),
        "interpretation": "The stale registered_window metadata is not used for this proposal; generated XML and trajectory time axis bind the actual 0.004 s source cadence.",
    }
    return {
        "schema": "core.material.f4.tallwall120.cadence_source_audit.v1",
        "created_at_utc": stamp(),
        "pair": {
            "same_terminal_lineage": True,
            "cell04_role": "historical_context_only; not the causal pair",
            "cell14_role": "native_dense_reference_source",
            "derived_view_role": "exact_every_fifth_saved_row; no interpolation",
            "cell04_h5": cell04["source_h5"],
            "cell14_h5": cell14["source_h5"],
            "view_h5": ref(VIEW_H5, "exact_stride5_reference_view"),
            "view_manifest": ref(VIEW_MANIFEST, "exact_stride5_view_manifest"),
        },
        "physical_control_comparison": {
            "normalised_prepared_config_equal": dense_control == old_control,
            "normalisation_removed_only": ["case_id", "design_cell", "output_interval_s", "registered_window.output_interval_s", "time_control_variant", "time_control_contract"],
            "same_q": Q,
            "same_dp_m": DP_M,
            "same_solver_binary_sha256": cell04_prepared["solver_sha256"] == cell14_prepared["solver_sha256"],
            "same_decoder_sha256": cell04_prepared["decoder_sha256"] == cell14_prepared["decoder_sha256"],
            "same_solver_arguments": cell04_prepared["solver_arguments"] == cell14_prepared["solver_arguments"],
            "generated_xml_equal_after_cadence_date_and_vtk_normalisation": normalized_xml_equal,
            "xml_expected_difference": "TimeOut value and generated VTK filename; GenCase timestamp",
        },
        "time_axis": {
            "cell04_frame_count": int(len(old_times)),
            "cell14_native_frame_count": int(len(dense_times)),
            "stride5_view_frame_count": int(len(view_times)),
            "cell04_window_s": float(old_times[-1]),
            "cell14_window_s": float(dense_times[-1]),
            "canary_endpoint_s": float(dense_times[DENSE_STOP_AFTER]),
            "cell14_every_fifth_equals_cell04": True,
            "view_time_equals_cell14_every_fifth": True,
            "cell04_max_cadence_error_s": float(np.max(np.abs(np.diff(old_times) - 0.02))),
            "cell14_max_cadence_error_s": float(np.max(np.abs(dense_dt - EXPECTED_NATIVE_INTERVAL_S))),
            "view_max_cadence_error_s": float(np.max(np.abs(np.diff(view_times) - EXPECTED_STRIDE_INTERVAL_S))),
            "cell14_native_max_material_step_s": float(np.max(dense_dt) / DENSE_SUBSTEPS),
            "stride5_view_max_material_step_s": float(np.max(view_dt) / VIEW_SUBSTEPS),
            "matched_saved_frame_dataset_mismatch_count": len(dataset_mismatches),
            "matched_saved_frame_dataset_mismatches": dataset_mismatches[:20],
            "view_attributes": {key: (value.item() if isinstance(value, np.generic) else value) for key, value in view_attrs.items()},
        },
        "metadata_warning": metadata_warning,
        "qualification_boundary": {
            "qualification_only": True,
            "qualification_claim": "none",
            "material_reliability_status": "uncalibrated",
            "t2_status": "not_assessed",
            "source_view_is_not_independent_cfd": True,
        },
    }


def hypothesis(audit: dict) -> dict:
    dense_step = audit["time_axis"]["cell14_native_max_material_step_s"]
    view_step = audit["time_axis"]["stride5_view_max_material_step_s"]
    return {
        "schema": "core.material.f4.tallwall120.cadence_hypothesis.v1",
        "hypothesis_id": "F4_HC1_native004_vs_exact_stride5_v1",
        "created_at_utc": stamp(),
        "status": "preregistered_proposal_only",
        "question": "Does the saved reference-frame cadence alter the first frozen reconstruction-error failure when the maximum tracer integration step is held at the same approximately 0.002 s scale?",
        "alternative": "Using native 0.004 s support frames may change first-failure timing and unknown mass because the provider has shorter current-frame brackets.",
        "null": "The native 0.004 s source and exact every-fifth-frame 0.02 s view produce the same first-failure interval, unknown curve, and support-gate component accounting within numerical equality at common saved times.",
        "single_variable": "reference saved-frame cadence; the exact stride view is copied from the same cell-14 H5 rows without interpolation, while both runs use fixed substep counts chosen for the recorded approximately 0.002 s maximum step",
        "controlled": {
            "q": Q,
            "dp_m": DP_M,
            "seeds": SEEDS,
            "seed_generator": "scripts.core_material.seeds_f4",
            "neighbour_variant": "baseline24",
            "neighbours": material.NEIGHBOURS,
            "weighting": "1/(distance_squared+regularization_squared)",
            "regularization_m": material.REGULARIZATION_M,
            "support_gate": material.GATE,
            "unknown_gate_fraction_max": 0.01,
            "walls": "same tallwall120 finite wall definition",
            "dense_substeps": DENSE_SUBSTEPS,
            "stride_view_substeps": VIEW_SUBSTEPS,
            "dense_max_material_step_s": dense_step,
            "stride_view_max_material_step_s": view_step,
            "maximum_step_difference_s": abs(dense_step - view_step),
            "maximum_step_match_tolerance_s": 5e-6,
        },
        "excluded_comparisons": [
            "The old cell-04 .02 s s2 canary remains historical context and is not used to attribute this paired effect.",
            "No threshold relaxation, neighbour sweep, wall change, seed change, or q change is allowed.",
            "The derived stride view is not a new CFD run and cannot receive T1/T2 qualification.",
        ],
        "fixed_metrics": [
            "first failure saved-frame bracket and physical time",
            "unknown fraction per source at every common physical time",
            "common reliable path coverage and cumulative reliability",
            "reconstruction, distance, wall, ESS, rank, anisotropy and nonfinite gate contributions",
            "mass closure",
            "contact/upward/return CDFs, residence with right-censoring, and event-window status",
        ],
        "audit_bindings": {
            "source_audit_schema": audit["schema"],
            "cell14_source_sha256": audit["pair"]["cell14_h5"]["sha256"],
            "stride_view_sha256": audit["pair"]["view_h5"]["sha256"],
        },
    }


def input_refs(cell04: dict, cell14: dict, audit: dict) -> list[dict]:
    refs = [
        cell14["source_h5"], cell14["archive"], cell14["result"], cell14["audit"], cell14["observations"],
        cell04["source_h5"], cell04["archive"], cell04["result"], cell04["audit"], cell04["observations"],
        ref(CELL14_PREPARED_DIR / "prepared.json", "cell14_prepared_source_definition"),
        ref(CELL14_PREPARED_DIR / "gencase.log", "cell14_preparation_log"),
        ref(CELL14_PREPARED_DIR / "F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_NATIVE_OUTPUT_Def.xml", "cell14_finite_wall_definition"),
        ref(CELL14_PREPARED_DIR / "generated/F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_NATIVE_OUTPUT.xml", "cell14_generated_solver_definition"),
        ref(CELL04_PREPARED_DIR / "prepared.json", "cell04_historical_prepared_definition"),
        ref(CELL04_PREPARED_DIR / "generated/F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL.xml", "cell04_historical_generated_solver_definition"),
        ref(SOLVER_BINARY, "frozen_dualsphysics_solver_binary"),
        ref(DECODER, "frozen_bi4_decoder"),
        ref(SOURCE_TEMPLATE, "frozen_preparation_source_template"),
        audit["pair"]["view_h5"], audit["pair"]["view_manifest"],
        ref(T1_COMPLETE, "root_t1_complete_tallwall_matrix"),
        ref(CELL04_VERIFICATION, "historical_cell04_root_verification"),
        ref(TRACER, "versioned_tallwall120_material_tracer"),
        ref(CORE_MATERIAL, "shared_provider_and_event_primitives"),
        ref(NEIGHBOURS, "visible_support_shepard_backend"),
        ref(PASSIVE, "finite_wall_and_support_helpers"),
        ref(STRIDE_BUILDER, "exact_stride_view_builder"),
        ref(PROPOSAL_BUILDER, "cadence_proposal_builder"),
    ]
    # Keep the list deterministic and reject accidental duplicate paths.
    seen = set()
    unique = []
    for item in refs:
        if item["path"] not in seen:
            unique.append(item)
            seen.add(item["path"])
    return unique


def _job(*, source: dict, view: bool, audit: dict, hypothesis_record: dict, refs: list[dict]) -> dict:
    if view:
        job_id = "core-f4-tallwall120-material-cadence-stride5-s10-canary-v1"
        source_path = VIEW_H5
        output_name = "tallwall120_stride5_material.h5"
        stop_after = VIEW_STOP_AFTER
        substeps = VIEW_SUBSTEPS
        source_role = "cell14_exact_stride5_reference_view"
        intervals = VIEW_STOP_AFTER
        read_budget = int(VIEW_H5.stat().st_size * 1.20)
    else:
        job_id = "core-f4-tallwall120-material-cadence-native004-s2-canary-v1"
        source_path = CELL14_H5
        output_name = "tallwall120_native004_material.h5"
        stop_after = DENSE_STOP_AFTER
        substeps = DENSE_SUBSTEPS
        source_role = "cell14_terminal_root_verified_native004_trajectory"
        intervals = DENSE_STOP_AFTER
        read_budget = int(CELL14_H5.stat().st_size * 0.20)
    source_ref = ref(source_path, source_role)
    source_ref["frame_stride_view"] = bool(view)
    source_ref["parent_source_sha256"] = SOURCE14_H5_SHA256 if view else None
    source_record = {
        "role": source_role,
        "reference": source_ref,
        "cell14_native_parent": ref(CELL14_H5, "cell14_native_parent_binding"),
        "audit_schema": audit["schema"],
        "audit_sha256": None,
    }
    if view:
        source_record["stride_view_manifest"] = ref(VIEW_MANIFEST, "stride_view_manifest")
    return {
        "schema": "core.material.job.v2",
        "job_id": job_id,
        "logical_id": job_id.upper().replace("-", "_"),
        "attempt_role": "initial",
        "category": "material_f4_tallwall120_cadence_canary",
        "family": "F4",
        "scope_id": material.SCOPE_ID,
        "revision_id": material.REVISION_ID,
        "study_id": hypothesis_record["hypothesis_id"],
        "comparison_mode": "native004_vs_exact_stride5_same_lineage",
        "stage": "qualification_only",
        "qualification_only": True,
        "qualification_claim": "none",
        "material_reliability_status": "uncalibrated",
        "host": "ada",
        "cwd": str(LAB_ROOT),
        "argv": [
            str(LAB_ROOT / ".venv/bin/python"), str(TRACER),
            "--source", str(source_path),
            "--output", "{attempt_dir}/product/" + output_name,
            "--q", str(Q), "--dp-m", str(DP_M), "--seeds", str(SEEDS),
            "--substeps", str(substeps), "--stop-after", str(stop_after),
        ],
        "env": {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "NUMEXPR_NUM_THREADS": "1"},
        "input_files": refs,
        "source": source_record,
        "backend": {
            "name": material.NEIGHBOUR_BACKEND,
            "version": material.REVISION_ID,
            "neighbours": material.NEIGHBOURS,
            "weighting": "1/(distance_squared+regularization_squared)",
            "regularization_m": material.REGULARIZATION_M,
            "maximum_support_distance_m": material.MAXIMUM_SUPPORT_DISTANCE_M,
            "support_gate": material.GATE,
            "unknown_gate_fraction_max": 0.01,
            "material_reliability_calibrated": False,
        },
        "source_contract": {
            "source_frame_policy": "dense native saved rows" if not view else "exact source rows selected at indices 0,5,...,1085; no interpolation",
            "reference_provider_can_read": "only current interval's two registered frames",
            "model_future_cfd_access": False,
        },
        "event_window": {
            "requested_native_intervals": intervals,
            "requested_window_s": float(audit["time_axis"]["canary_endpoint_s"]),
            "source_native_window_s": SOURCE_WINDOW_S,
            "short_canary_is_event_right_censored": True,
            "unobserved_event_policy": "NaN/right-censored; retain full source mass denominator",
            "comparison_common_time_policy": "compare native dense frame 5*k and exact stride-view frame k at identical physical times",
        },
        "acceptance": {
            "must_preserve_mass_closure": True,
            "must_report_unknown_fraction_per_source": True,
            "must_report_common_reliable_path_coverage": True,
            "must_report_contact_upward_return_cdf": True,
            "must_report_residence_with_right_censoring": True,
            "must_report_support_gate_component_counts": True,
            "must_not_report_T2_qualification": True,
            "unknown_gate_remains_0p01": True,
            "thresholds_unchanged": True,
        },
        "required_outputs": [
            "product/" + output_name,
            "product/" + output_name.replace(".h5", ".json"),
            "product/" + output_name + ".checkpoint.json",
        ],
        "checkpoint_contract": {
            "schema": material.CHECKPOINT_SCHEMA,
            "policy": "content-addressed generation files; manifest pointer atomic; no generation overwrite",
            "generation_directory": "product/" + output_name + ".checkpoints/",
            "resume_equivalence_required": True,
        },
        "depends_on": [],
        "resources": {"cpu_cores": 2, "ram_mib": 8192, "gpu_peak_mib": 0, "io_weight": 0.5},
        "resource_estimate": {
            "basis": "root-verified cell04 20-interval material canary: 18.218 wall s / 12.552 child CPU s / 746.3 MiB RSS; pair holds approximately 200 material substeps, with 30% margin",
            "material_substeps": int(intervals * substeps),
            "input_bytes": int(source_path.stat().st_size),
            "read_bytes_budget": read_budget,
            "wall_seconds_budget": 180,
            "cpu_user_seconds_budget": 120,
            "peak_rss_mib_budget": 8192,
            "timeout_seconds": 900,
            "estimate_status": "planning estimate; no run started",
        },
        "central_ledger_mutation": 0,
        "gpu_started": False,
        "launch_status": "proposal_only_root_review_required",
    }


def build(output_root: Path) -> dict:
    cell04_prepared = _assert_case(CELL04_PREPARED_DIR, expected_interval=0.02, expected_case_id="F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_SPATIAL")
    cell14_prepared = _assert_case(CELL14_PREPARED_DIR, expected_interval=0.004, expected_case_id="F4_TALLWALL120_MDBC_NATIVE_NU1E6_Q0P50000000_DP0P007500000000_NATIVE_OUTPUT")
    cell04 = _verify_archive(CELL04_DIR, CELL04_H5, SOURCE04_H5_SHA256)
    cell14 = _verify_archive(CELL14_DIR, CELL14_H5, SOURCE14_H5_SHA256)
    if not VIEW_H5.is_file() or not VIEW_MANIFEST.is_file():
        raise FileNotFoundError("exact stride5 view is missing; run the versioned view builder first")
    audit = audit_pair(cell04_prepared, cell14_prepared, cell04, cell14)
    if not audit["physical_control_comparison"]["normalised_prepared_config_equal"]:
        raise ValueError("cell04/cell14 physical prepared controls are not equal after cadence normalisation")
    if not audit["physical_control_comparison"]["generated_xml_equal_after_cadence_date_and_vtk_normalisation"]:
        raise ValueError("cell04/cell14 generated XML differs beyond cadence/date/VTK name")
    if audit["time_axis"]["matched_saved_frame_dataset_mismatch_count"]:
        raise ValueError("cell14 dense rows and exact stride view/cell04 rows are not identical")
    audit_path = output_root / "evidence/f4-tallwall120-native004-cadence-source-audit-v1.json"
    hypothesis_path = output_root / "evidence/f4-tallwall120-native004-cadence-hypothesis-v1.json"
    jobs_dir = output_root / "jobs"
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    jobs_dir.mkdir(parents=True, exist_ok=True)
    audit["proposal_code"] = ref(PROPOSAL_BUILDER, "cadence_proposal_builder")
    audit_path.write_text(json.dumps(audit, indent=2, sort_keys=True, allow_nan=False) + "\n")
    hypothesis_record = hypothesis(audit)
    hypothesis_record["source_audit"] = {"path": str(audit_path), "sha256": sha256(audit_path)}
    hypothesis_path.write_text(json.dumps(hypothesis_record, indent=2, sort_keys=True, allow_nan=False) + "\n")
    refs = input_refs(cell04, cell14, audit)
    refs.extend([
        ref(audit_path, "cadence_source_audit"),
        ref(hypothesis_path, "preregistered_cadence_hypothesis"),
    ])
    dense_job = _job(source=cell14, view=False, audit=audit, hypothesis_record=hypothesis_record, refs=refs)
    view_job = _job(source=cell14, view=True, audit=audit, hypothesis_record=hypothesis_record, refs=refs)
    # Bind the final audit and hypothesis hashes into both runnable job specs.
    for job in (dense_job, view_job):
        job["source"]["audit_sha256"] = sha256(audit_path)
        job["hypothesis_sha256"] = sha256(hypothesis_path)
    dense_path = jobs_dir / f"{dense_job['job_id']}.json"
    view_path = jobs_dir / f"{view_job['job_id']}.json"
    dense_path.write_text(json.dumps(dense_job, indent=2, sort_keys=True, allow_nan=False) + "\n")
    view_path.write_text(json.dumps(view_job, indent=2, sort_keys=True, allow_nan=False) + "\n")
    manifest = {
        "schema": "core.material.f4.tallwall120.cadence_proposal_bundle.v1",
        "created_at_utc": stamp(),
        "study_id": hypothesis_record["hypothesis_id"],
        "audit": {"path": str(audit_path), "sha256": sha256(audit_path)},
        "hypothesis": {"path": str(hypothesis_path), "sha256": sha256(hypothesis_path)},
        "jobs": [
            {"path": str(dense_path), "sha256": sha256(dense_path), "job_id": dense_job["job_id"]},
            {"path": str(view_path), "sha256": sha256(view_path), "job_id": view_job["job_id"]},
        ],
        "qualification_only": True,
        "qualification_claim": "none",
        "submitted": False,
        "central_ledger_mutation": 0,
        "gpu_started": False,
        "scientific_boundary": "This is one preregistered cadence canary. The stride5 H5 is a derived exact-row view, not an independent CFD source; neither result can be promoted to T2.",
    }
    manifest_path = output_root / "evidence/f4-tallwall120-native004-cadence-proposal-bundle-v1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return {
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path)},
        "audit": {"path": str(audit_path), "sha256": sha256(audit_path)},
        "hypothesis": {"path": str(hypothesis_path), "sha256": sha256(hypothesis_path)},
        "jobs": manifest["jobs"],
        "stride_view": {"path": str(VIEW_H5), "sha256": sha256(VIEW_H5), "manifest_sha256": sha256(VIEW_MANIFEST)},
        "submitted": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=LAB_ROOT / "campaigns/core-v1/material")
    args = parser.parse_args()
    print(json.dumps(build(args.output_root.resolve()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
