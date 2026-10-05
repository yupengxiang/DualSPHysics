#!/usr/bin/env python3
"""Metadata-only fresh103 contract preflight; never opens science payloads."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
REQUESTS = PACKAGE / "requests"
BASE_MOTION = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050/root-compact-equilibrium-runup_coarse-clip-direction-fix-gencase-050/prepared/assets/f5_compact_packet_motion.dat")
BASE_MOTION_SHA = "51e197f0831915a73534c619704658b06812c9d52c38c470ab4cbb8d59f5614a"
SCIENCE_SUFFIXES = {".dat", ".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".xmf", ".xdmf"}
STATIC_SUFFIXES = {".json", ".xml", ".py", ".txt", ".md", ".yaml", ".yml"}
CONVERSION_KEYS = {
    "all_51_saved_states_required",
    "all_actual_counts_from_gencase_and_report",
    "canonical_condition_separate_from_legacy_h5_scope",
    "mass_report_without_rescale",
    "native_mk50_bed_mapping_preserved",
    "solver_dimension_required",
    "source_h5_read_only",
    "source_native_identity_preserved",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha(path: Path) -> str:
    require(path.suffix.lower() not in SCIENCE_SUFFIXES,
            f"science payload hashing is forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def check_input_closure(request: dict[str, Any], label: str, unresolved: list[str]) -> None:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    require(isinstance(files, list) and isinstance(hashes, dict), f"{label}: input closure is not object/list")
    require(set(files) == set(hashes), f"{label}: input_files/input_sha256 key mismatch")
    for raw in files:
        value = hashes[raw]
        if isinstance(raw, str) and raw.startswith("<root-bind:"):
            require(value is None, f"{label}: unresolved binding has non-null hash: {raw}")
            continue
        path = Path(raw)
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            if path == BASE_MOTION:
                require(value == BASE_MOTION_SHA, f"{label}: registered base motion digest changed")
            else:
                raise AssertionError(f"{label}: unbound science payload in new request: {raw}")
            continue
        if path.exists():
            require(value == sha(path), f"{label}: static input SHA drift: {raw}")
        elif value is not None:
            # Root/integration-owned static inputs may be absent in this WT;
            # their declared digest is retained for Root's strict preflight.
            require(isinstance(value, str) and len(value) == 64,
                    f"{label}: missing static input has malformed declared hash: {raw}")
            unresolved.append(raw)


def all_future_null(value: Any, label: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            all_future_null(child, f"{label}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            all_future_null(child, f"{label}[{index}]")
    elif isinstance(value, str) and value.startswith("<root-bind:"):
        return
    else:
        require(value is None, f"{label} is not null: {value!r}")


def common_disabled(request: dict[str, Any], label: str) -> None:
    require(request.get("schema") == "ds02.runner-request.v2", f"{label}: runner schema")
    for key in ("disabled", "source_only"):
        require(request.get(key) is True, f"{label}: {key} must be true")
    for key in ("launch", "launch_allowed", "execution_allowed", "solver_allowed",
                "conversion_allowed", "arrays_allowed", "array_edit_allowed",
                "shared_registry_write_allowed"):
        require(request.get(key) is False, f"{label}: {key} must be false")
    require(request.get("full16_authorized") is False and
            request.get("full801_authorized") is False, f"{label}: full authorization changed")
    require(request.get("independent_case_count_increment") == 0, f"{label}: case count changed")
    all_future_null(request.get("future_output_hashes"), f"{label}.future_output_hashes")
    check_input_closure(request, label, UNRESOLVED)


def check_candidate(cid: str) -> dict[str, str]:
    prefix = f"{cid}-"
    paths = {p.name: p for p in REQUESTS.glob(f"{cid}-*.json")}
    expected = {
        f"{cid}-motion-transform-request.json",
        f"{cid}-gencase-request.json",
        f"{cid}-initial-qa-mk50-request.json",
        f"{cid}-short-native-qualification-request.json",
        f"{cid}-typed-conversion-request.json",
        f"{cid}-xmf-request.json",
        f"{cid}-short-dynamic-bed-audit-request.json",
    }
    require(expected <= set(paths), f"{cid}: missing stage requests")
    loaded = {name: load(path) for name, path in paths.items() if name in expected}
    attempts: dict[str, str] = {}
    for name, request in loaded.items():
        common_disabled(request, f"{cid}/{name}")
        require(request.get("candidate_id") == loaded[f"{cid}-motion-transform-request.json"].get("candidate_id"),
                f"{cid}/{name}: candidate identity mismatch")
        require(request.get("physical_condition_sha256") ==
                loaded[f"{cid}-motion-transform-request.json"].get("physical_condition_sha256"),
                f"{cid}/{name}: physical scope changed")
        attempts[name] = str(request.get("attempt_id"))
        for key in ("expected_particles", "expected_fixed_particles",
                    "expected_moving_particles", "expected_fluid_particles",
                    "expected_floating_particles", "expected_particle_axis"):
            if key in request:
                require(request[key] is None, f"{cid}/{name}: future count {key} was guessed")
    motion = loaded[f"{cid}-motion-transform-request.json"]
    gencase = loaded[f"{cid}-gencase-request.json"]
    initial = loaded[f"{cid}-initial-qa-mk50-request.json"]
    native = loaded[f"{cid}-short-native-qualification-request.json"]
    typed = loaded[f"{cid}-typed-conversion-request.json"]
    xmf = loaded[f"{cid}-xmf-request.json"]
    bed = loaded[f"{cid}-short-dynamic-bed-audit-request.json"]
    if "depends_on_attempt" in gencase:
        require(gencase["depends_on_attempt"] == motion["attempt_id"], f"{cid}: GenCase dependency")
    else:
        require(gencase.get("motion_transform_attempt") == motion["attempt_id"], f"{cid}: GenCase motion dependency")
    require(initial["depends_on_attempt"] == gencase["attempt_id"], f"{cid}: initial QA dependency")
    require(native["depends_on_attempt"] == initial["attempt_id"], f"{cid}: native dependency")
    require(typed["depends_on_attempt"] == native["attempt_id"], f"{cid}: typed dependency")
    require(xmf["depends_on_attempt"] == typed["attempt_id"], f"{cid}: XMF dependency")
    require(bed["depends_on_attempt"] == xmf["attempt_id"], f"{cid}: bed dependency")
    require(initial["kind"] == "cpu" and initial["cpu_task_kind"] == "audit",
            f"{cid}: initial QA task kind")
    require(initial["placement_gate"] ==
            "basic placement/Mk50 only; numerical precision remains diagnostic",
            f"{cid}: initial QA placement gate changed")
    initial_binding = load(Path(initial["binding"]))
    require(initial_binding["schema"] ==
            "ds02.f5.c082s1.stage1-placement-mk50-binding.fresh103.v1",
            f"{cid}: initial QA binding schema")
    precision = initial_binding["numerical_precision"]
    require(precision["diagnostic_only"] is True and
            precision["accepted_as_stage1_placement_gate"] is False and
            float(precision["exact_dp_lattice_threshold"]) == 1e-6,
            f"{cid}: exact DP residual became a stage1 gate")
    require(initial_binding["actual_counts"] is None,
            f"{cid}: initial QA source template guessed counts")
    require(typed["kind"] == "cpu" and typed["cpu_task_kind"] == "conversion", f"{cid}: typed task kind")
    require(typed["estimated_peak_gpu_mib"] == 0, f"{cid}: typed GPU estimate")
    require(typed["expected_frames"] == 51 and typed["expected_dimension"] == 3, f"{cid}: typed dimensions")
    require(set(typed["conversion_contract"]) == CONVERSION_KEYS, f"{cid}: converter contract fields")
    require(typed["conversion_contract"]["solver_dimension_required"] == 3, f"{cid}: solver dimension contract")
    require(typed["conversion_contract"]["all_actual_counts_from_gencase_and_report"] is True,
            f"{cid}: typed counts are not producer-bound")
    require(typed["actual_bindings"]["actual_counts"] is None, f"{cid}: typed count guess")
    all_future_null(typed["actual_bindings"], f"{cid}.typed.actual_bindings")
    all_future_null(typed["future_bindings"], f"{cid}.typed.future_bindings")
    require(typed["producer_report_contract"]["solver_dimension_field_shape"] == "evidence_object",
            f"{cid}: typed solver_dimension shape")
    require(typed["producer_report_contract"]["report_schema"] == "ds-data-02.bi4-direct-conversion.v1",
            f"{cid}: typed report schema")
    require(xmf["kind"] == "cpu" and xmf["cpu_task_kind"] == "xmf_export", f"{cid}: XMF task kind")
    require(xmf["derived_view_only"] is True and xmf["native_fields_preserved"] is True,
            f"{cid}: XMF view semantics")
    require(xmf["expected_frames"] == 51 and xmf["expected_dimension"] == 3 and
            xmf["expected_particles"] is None, f"{cid}: XMF future dimensions")
    all_future_null(xmf["future_bindings"], f"{cid}.xmf.future_bindings")
    semantics = xmf["binding_semantics"]
    require(semantics["source_h5_scope_schema"] == "legacy-owner-scope.v0" and
            semantics["source_h5_scope_sha256"].startswith("<root-bind:"),
            f"{cid}: XMF legacy scope semantics")
    require(bed["kind"] == "cpu" and bed["cpu_task_kind"] == "audit", f"{cid}: bed task kind")
    require(bed["depends_on_attempt"] == xmf["attempt_id"], f"{cid}: bed must follow XMF")
    require(bed["expected_frames"] == 51 and bed["expected_dimension"] == 3 and
            bed["expected_particle_axis"] is None, f"{cid}: bed dimensions")
    require(bed["native_bed_marker_mk"] == 50 and bed["source_bed_marker_mkbound"] == 40,
            f"{cid}: marker mapping")
    contract = bed["output_contract"]
    for key in ("scan_all_51_frames", "all_initial_fluid_uids_full_denominator",
                "report_one_dp_two_dp_count_fraction_depth",
                "report_nonfinite_and_lost_uid_unexplained",
                "thresholds_diagnostic_only", "visual_review_required"):
        require(contract[key] is True, f"{cid}: bed contract {key}")
    require(bed["dynamic_acceptance"] is False, f"{cid}: bed acceptance enabled")
    binding = load(Path(bed["binding"]))
    require(binding["schema"] == "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh103.v1",
            f"{cid}: bed binding schema")
    require(binding["actual_counts"] is None and binding["expected_particle_axis"] is None,
            f"{cid}: bed binding guessed count")
    all_future_null(binding["future_inputs"], f"{cid}.bed.future_inputs")
    return {
        "motion": motion["attempt_id"],
        "gencase": gencase["attempt_id"],
        "initial_qa": initial["attempt_id"],
        "short_native": native["attempt_id"],
        "typed": typed["attempt_id"],
        "xmf": xmf["attempt_id"],
        "bed_audit": bed["attempt_id"],
    }


def main() -> int:
    global UNRESOLVED
    UNRESOLVED = []
    require((PACKAGE / "workers/bed_audit_candidate.py").is_file(), "candidate bed worker missing")
    ast.parse((PACKAGE / "workers/bed_audit_candidate.py").read_text(encoding="utf-8"))
    chains = {cid: check_candidate(cid) for cid in ("A080", "A120")}
    result = {
        "schema": "ds02.f5.c082s1.fresh103-preflight-report.v1",
        "status": "passed_metadata_only",
        "source_only": True,
        "science_arrays_read": False,
        "science_arrays_hashed": False,
        "jobs_started": False,
        "shared_state_modified": False,
        "full801_enabled": False,
        "independent_case_count_increment": 0,
        "future_candidate_counts_and_hashes_null": True,
        "typed_conversion_contract_verified": True,
        "xmf_derived_view_contract_verified": True,
        "bed_audit_contract_verified": True,
        "upstream_motion_rebind_required_if_root425_rebases": True,
        "unresolved_root_owned_static_inputs": sorted(set(UNRESOLVED)),
        "chains": chains,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    report = PACKAGE / "metadata/fresh103-preflight-report.json"
    report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
