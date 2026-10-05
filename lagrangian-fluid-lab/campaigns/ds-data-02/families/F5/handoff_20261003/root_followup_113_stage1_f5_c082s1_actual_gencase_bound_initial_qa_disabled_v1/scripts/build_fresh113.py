#!/usr/bin/env python3
"""Bind Root544 GenCase metadata to disabled native initial QA requests.

Only JSON receipts/reports and XML path metadata are inspected.  BI4, CSV,
DAT, H5, and VTK payloads stay external to this source package.  BI4/XML
hashes are copied from the producer report as attestations; this builder does
not read or rehash those payloads.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
FRESH110 = PKG.parent / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH111 = PKG.parent / "root_followup_111_stage1_f5_c082s1_full1201_gate_sidecar_v1"
FRESH112 = PKG.parent / "root_followup_112_stage1_f5_c082s1_motion535_bound_gencase_disabled_v1"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
FRESH111_COMMIT = "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0"
FRESH112_COMMIT = "586555fe048c628c24ef363a301208302cef1ae9"


def sha_json(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden in fresh113: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def attempt_dir(tag: str) -> Path:
    return DATA_CASE / f"root-stage1-f5-c082s1-{tag.lower()}-genuine-gencase-112-root544"


def gencase_paths(tag: str) -> tuple[Path, Path, Path, Path]:
    root = attempt_dir(tag)
    receipt = root / "execution-receipt.json"
    report = root / "prepared/prepared-input-report.json"
    prefix = load(report).get("prefix") if report.is_file() else None
    if not isinstance(prefix, str):
        prefix = str(root / "prepared" / CASE)
    return receipt, report, Path(prefix + ".xml"), Path(prefix + ".bi4")


def fresh111_gate() -> dict[str, Any]:
    sidecar_file = FRESH111 / "metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(sidecar_file)
    if sidecar.get("status") != "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass":
        raise ValueError("fresh111 gate status changed")
    if sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is not False:
        raise ValueError("Root511 short review cannot authorize fresh110 full1201")
    if sidecar.get("existing_full801_gate", {}).get("current_status") != "WAIT/null":
        raise ValueError("existing A080/A120 full801 gate is no longer WAIT/null")
    return {
        "sidecar_path": str(sidecar_file),
        "sidecar_sha256": sha_json(sidecar_file),
        "sidecar_commit": FRESH111_COMMIT,
        "status": "WAIT/null",
        "root511_short_render_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_pass": False,
        "required_before_any_full24s_1201": True,
        "future_authorization_receipt": None,
        "future_authorization_sha256": None,
    }


def producer_record(tag: str) -> dict[str, Any]:
    receipt_path, report_path, xml_path, bi4_path = gencase_paths(tag)
    receipt = load(receipt_path)
    report = load(report_path)
    nested_request = receipt.get("request", {})
    counts = report.get("generated_xml_particle_counts", {})
    total = report.get("actual_total_particles")
    receipt_total = receipt.get("total_particles")
    receipt_fluid = receipt.get("fluid_particles")
    solver_dimension = receipt.get("solver_dimension_from_gencase")
    constants = report.get("actual_generated_constants", {})
    data2d_raw = constants.get("data2d", {}).get("value") if isinstance(constants, dict) else None
    if isinstance(data2d_raw, str):
        data2d_value = data2d_raw.strip().lower() in {"true", "1", "yes"}
    else:
        data2d_value = data2d_raw
    ready = (
        receipt.get("status") == "completed"
        and receipt.get("returncode") == 0
        and receipt.get("termination_reason") is None
        and isinstance(nested_request, dict)
        and nested_request.get("case_id") == CASE
        and isinstance(counts, dict)
        and all(isinstance(counts.get(k), int) for k in ("fixed", "moving", "floating", "fluid"))
        and isinstance(total, int)
        and total == sum(counts[k] for k in ("fixed", "moving", "floating", "fluid"))
        and receipt_total == total
        and receipt_fluid == counts["fluid"]
        and solver_dimension == 3
        and isinstance(report.get("xml_sha256"), str)
        and len(report["xml_sha256"]) == 64
        and isinstance(report.get("bi4_sha256"), str)
        and len(report["bi4_sha256"]) == 64
        and xml_path.exists()
        and bi4_path.exists()
    )
    if not isinstance(nested_request, dict):
        nested_request = {}
    assets = report.get("assets", [])
    motion = assets[0] if isinstance(assets, list) and assets and isinstance(assets[0], dict) else {}
    actual_counts = {
        "total_particles": total if ready else None,
        "fixed_particles": counts.get("fixed") if ready else None,
        "moving_particles": counts.get("moving") if ready else None,
        "floating_particles": counts.get("floating") if ready else None,
        "fluid_particles": counts.get("fluid") if ready else None,
        "solver_dimension": solver_dimension if ready else None,
        "data2d": data2d_value if ready else None,
    }
    return {
        "tag": tag,
        "status": "completed/0" if ready else "WAIT/null",
        "attempt_id": nested_request.get("attempt_id"),
        "case_id": nested_request.get("case_id"),
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha_json(receipt_path),
        "report_path": str(report_path),
        "report_sha256": sha_json(report_path),
        "receipt_output_root": receipt.get("output_root"),
        "returncode": receipt.get("returncode"),
        "generated_xml": str(xml_path) if ready else None,
        "generated_xml_sha256": report.get("xml_sha256") if ready else None,
        "generated_bi4": str(bi4_path) if ready else None,
        "generated_bi4_sha256": report.get("bi4_sha256") if ready else None,
        "generated_xml_sha256_provenance": "Root544 prepared-input-report.json producer field; source agent did not read or rehash XML",
        "generated_bi4_sha256_provenance": "Root544 prepared-input-report.json producer field; source agent did not read or rehash BI4",
        "actual_counts": actual_counts,
        "data2d_producer_raw": data2d_raw,
        "counts_provenance": "Root544 prepared-input-report.json generated_xml_particle_counts and actual_total_particles",
        "motion_asset": motion,
        "native_initial_typed_QA": report.get("native_initial_typed_QA"),
        "production_approval": report.get("production_approval"),
        "independent_case_count_increment": report.get("independent_case_count_increment"),
        "source_definition": report.get("source_definition"),
        "source_definition_sha256": report.get("definition_sha256"),
    }


def replace_input_files(values: list[Any], producer: dict[str, Any]) -> list[Any]:
    mapping = {
        "<root-bind:gencase_receipt>": producer["receipt_path"],
        "<root-bind:prepared_input_report>": producer["report_path"],
        "<root-bind:generated_xml>": producer["generated_xml"],
        "<root-bind:generated_bi4>": producer["generated_bi4"],
    }
    result: list[Any] = []
    for value in values:
        if value in mapping and mapping[value] is not None:
            result.append(mapping[value])
        elif value in mapping:
            result.append(value)
        else:
            result.append(value)
    if producer["report_path"] not in result:
        result.append(producer["report_path"])
    if producer["receipt_path"] not in result:
        result.append(producer["receipt_path"])
    return result


def replace_input_hashes(values: dict[str, Any], producer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    path_map = {
        "<root-bind:gencase_receipt>": (producer["receipt_path"], producer["receipt_sha256"], "Root544 execution-receipt.json JSON metadata hash"),
        "<root-bind:prepared_input_report>": (producer["report_path"], producer["report_sha256"], "Root544 prepared-input-report.json JSON metadata hash"),
        "<root-bind:generated_xml>": (producer["generated_xml"], producer["generated_xml_sha256"], producer["generated_xml_sha256_provenance"]),
        "<root-bind:generated_bi4>": (producer["generated_bi4"], producer["generated_bi4_sha256"], producer["generated_bi4_sha256_provenance"]),
    }
    hashes: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for key, value in values.items():
        if key in path_map and path_map[key][0] is not None:
            path, digest, note = path_map[key]
            hashes[path] = digest
            provenance[path] = note
        else:
            hashes[key] = value
            provenance[key] = "future Root binding or inherited fresh110 source provenance"
    for key, digest, note in (
        (producer["report_path"], producer["report_sha256"], "Root544 prepared-input-report.json JSON metadata hash"),
        (producer["receipt_path"], producer["receipt_sha256"], "Root544 execution-receipt.json JSON metadata hash"),
    ):
        hashes[key] = digest
        provenance[key] = note
    return hashes, provenance


def initial_checks() -> dict[str, Any]:
    return {
        "source_of_truth": "registered Root-owned native BI4/official PartVTK worker; no GenCase CSV substitution",
        "required_total_uid_rows": True,
        "required_unique_finite_uid": True,
        "required_type_and_mk_fields": True,
        "required_native_3d": True,
        "required_initial_fluid_velocity_zero": True,
        "native_bed_mk": 50,
        "source_mkbound": 40,
        "central_mk50_support_required": True,
        "required_transverse_y_levels": 15,
        "fluid_below_analytic_profile_must_be_zero": True,
        "no_initial_spatial_overlap": True,
        "bed_penetration_profile": {
            "footprint": "exact C082S1 analytic bed profile and source x/y domain",
            "one_dp_depth_m": 0.02,
            "two_dp_depth_m": 0.04,
            "all_fluid_denominator": True,
            "frame_scope": "native initial state only",
        },
        "exact_dp_lattice_precision": "independent diagnostic retained; does not gate this basic placement request",
    }


def build_candidate(tag: str, producer: dict[str, Any], gate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_request = load(FRESH110 / "requests" / f"{tag}-initial-placement-mk50-request.json")
    source_binding = load(FRESH110 / "bindings" / f"{tag}-initial-qa-mk50-binding.json")
    source_gencase_binding = load(FRESH112 / "bindings" / f"{tag}-gencase-binding.json")
    lower = tag.lower()
    attempt_id = f"root-stage1-f5-c082s1-{lower}-actual-initial-qa-113"
    binding_path = PKG / "bindings" / f"{tag}-initial-qa-mk50-binding.json"
    request_path = PKG / "requests" / f"{tag}-initial-placement-mk50-request.json"
    checks = initial_checks()

    binding = copy.deepcopy(source_binding)
    binding["schema"] = "ds02.f5.c082s1.actual-gencase-bound-initial-mk50-binding.fresh113.v1"
    binding["attempt_id"] = attempt_id
    binding["gencase_attempt_id"] = producer["attempt_id"]
    binding["gencase_binding"] = str(FRESH112 / "bindings" / f"{tag}-gencase-binding.json")
    binding["gencase_binding_sha256"] = sha_json(FRESH112 / "bindings" / f"{tag}-gencase-binding.json")
    binding["gencase_receipt"] = producer["receipt_path"]
    binding["prepared_input_report"] = producer["report_path"]
    binding["generated_xml"] = producer["generated_xml"]
    binding["generated_xml_sha256"] = producer["generated_xml_sha256"]
    binding["generated_bi4"] = producer["generated_bi4"]
    binding["generated_bi4_sha256"] = producer["generated_bi4_sha256"]
    binding["gencase_receipt_sha256"] = producer["receipt_sha256"]
    binding["prepared_input_report_sha256"] = producer["report_sha256"]
    binding["actual_counts"] = producer["actual_counts"]
    binding["expected_counts"] = producer["actual_counts"]
    binding["actual_counts_provenance"] = producer["counts_provenance"]
    binding["official_particle_csv"] = None
    binding["official_particle_csv_sha256"] = None
    binding["native_initial_checks"] = checks
    binding["gencase_producer"] = {
        "status": producer["status"],
        "attempt_id": producer["attempt_id"],
        "receipt": producer["receipt_path"],
        "receipt_sha256": producer["receipt_sha256"],
        "prepared_input_report": producer["report_path"],
        "prepared_input_report_sha256": producer["report_sha256"],
        "generated_xml": producer["generated_xml"],
        "generated_xml_sha256": producer["generated_xml_sha256"],
        "generated_bi4": producer["generated_bi4"],
        "generated_bi4_sha256": producer["generated_bi4_sha256"],
        "completed0": producer["status"] == "completed/0",
    }
    binding["upstream_full801_visual_gate"] = gate
    dump(binding_path, binding)
    binding_sha = sha_json(binding_path)

    request = copy.deepcopy(source_request)
    request["attempt_id"] = attempt_id
    request["binding"] = str(binding_path)
    request["binding_sha256"] = binding_sha
    request["disabled"] = True
    request["execution_allowed"] = False
    request["launch"] = False
    request["launch_allowed"] = False
    request["solver_allowed"] = False
    request["status"] = "disabled_until_root_review_and_native_initial_worker_registration"
    request["purpose"] = "native initial UID/type/Mk50/finite/3D and analytic-bed 1DP/2DP audit; exact-DP precision remains independent"
    request["depends_on_attempt"] = producer["attempt_id"]
    request["gencase_attempt_id"] = producer["attempt_id"]
    request["gencase_receipt"] = producer["receipt_path"]
    request["prepared_input_report"] = producer["report_path"]
    request["generated_xml"] = producer["generated_xml"]
    request["generated_xml_sha256"] = producer["generated_xml_sha256"]
    request["generated_bi4"] = producer["generated_bi4"]
    request["generated_bi4_sha256"] = producer["generated_bi4_sha256"]
    request["gencase_receipt_sha256"] = producer["receipt_sha256"]
    request["prepared_input_report_sha256"] = producer["report_sha256"]
    request["actual_counts"] = producer["actual_counts"]
    request["actual_counts_provenance"] = producer["counts_provenance"]
    request["expected_counts"] = producer["actual_counts"]
    request["expected_particles"] = producer["actual_counts"]["total_particles"]
    request["expected_fixed_particles"] = producer["actual_counts"]["fixed_particles"]
    request["expected_moving_particles"] = producer["actual_counts"]["moving_particles"]
    request["expected_floating_particles"] = producer["actual_counts"]["floating_particles"]
    request["expected_fluid_particles"] = producer["actual_counts"]["fluid_particles"]
    request["official_particle_csv"] = None
    request["official_particle_csv_sha256"] = None
    request["native_initial_checks"] = checks
    request["gencase_producer"] = binding["gencase_producer"]
    request["upstream_full801_visual_gate"] = gate
    command = list(request["command"])
    for index, value in enumerate(command):
        if value == str(source_binding_path := FRESH110 / "bindings" / f"{tag}-initial-qa-mk50-binding.json"):
            command[index] = str(binding_path)
    request["command"] = command
    request["input_files"] = replace_input_files(request["input_files"], producer)
    request["input_sha256"], request["input_sha256_provenance"] = replace_input_hashes(request["input_sha256"], producer)
    request["future_output_hashes"] = {key: None for key in request["future_output_hashes"]}
    dump(request_path, request)
    return request, binding


def write_manifest() -> None:
    report = PKG / "metadata/fresh113-validator-report.json"
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path == report:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES or path.suffix.lower() not in SOURCE_SUFFIXES:
            raise ValueError(f"unsupported fresh113 file: {path}")
        files[str(path.relative_to(PKG))] = sha_json(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh113-source-manifest.v1",
        "status": "six_root544_gencase_metadata_bound_native_initial_qa_disabled_full1201_gate_wait",
        "files": files,
        "validator_report_excluded_from_manifest": True,
        "fresh110_modified": False,
        "fresh111_modified": False,
        "fresh112_modified": False,
        "full1201_authorized": False,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })


def main() -> int:
    gate = fresh111_gate()
    producers = [producer_record(tag) for tag in TAGS]
    requests = []
    for tag, producer in zip(TAGS, producers):
        request, _binding = build_candidate(tag, producer, gate)
        requests.append(request)
    dump(PKG / "metadata/fresh113-gencase-producer-provenance.json", {
        "schema": "ds02.f5.c082s1.fresh113-gencase-producer-provenance.v1",
        "status": "six_root544_gencase_metadata_bound_native_initial_qa_disabled",
        "fresh110_commit": FRESH110_COMMIT,
        "fresh111_commit": FRESH111_COMMIT,
        "fresh112_commit": FRESH112_COMMIT,
        "fresh111_gate": gate,
        "candidates": producers,
        "candidate_count": 6,
        "full_event_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "native_initial_qa_outputs_future": True,
        "future_initial_qa_report_sha256": None,
        "future_official_particle_csv_sha256": None,
        "future_typed_h5_sha256": None,
        "future_bed_audit_receipt_sha256": None,
        "independent_case_count_increment": 0,
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    dump(PKG / "metadata/fresh113-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh113-source-plan.v1",
        "status": "six_root544_gencase_metadata_bound_native_initial_qa_disabled_full1201_gate_wait",
        "candidate_count": 6,
        "candidate_tags": list(TAGS),
        "root544_producer": "actual completed/0 execution-receipt.json and prepared-input-report.json metadata",
        "counts_source": "Root544 generated_xml_particle_counts and actual_total_particles; no historical count substitution",
        "full_event_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "native_initial_qa_requests_disabled": True,
        "execution_allowed": False,
        "actual_native_checks": ["UID", "type", "Mk", "finite", "positive weights/density", "3D", "fluid initial zero velocity", "no overlap", "native bed Mk50", "analytic profile 1DP/2DP"],
        "source_mkbound": 40,
        "native_bed_mk": 50,
        "future_initial_qa_reports_null": True,
        "fresh111_gate_status": gate["status"],
        "root511_short_window_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_pass": False,
        "exact_dp_lattice_precision_negative_retained": True,
        "historical_A_B_penetration_failures_retained": True,
        "independent_case_count_increment": 0,
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "bi4_csv_dat_h5_vtk_payloads_read_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    (PKG / "README.md").write_text(
        "# F5 fresh113: Root544-bound native initial QA requests\n\n"
        "Root544 completed all six fresh112 GenCase attempts with returncode 0. This package binds each producer receipt, prepared-input-report, generated XML path/hash, BI4 path/hash, and actual particle counts to a disabled native initial placement/Mk50 audit request. Counts come from the producer report and are not copied from historical C082S1 expectations.\n\n"
        "The future worker must independently inspect native initial data for UID/type/Mk/finite/positive weights and density/3D/no-overlap, fluid initial zero velocity, native bed Mk50 support, exact analytic bed profile, and 1DP/2DP penetration diagnostics. Official CSV, initial QA report, typed H5, and bed audit receipts remain future/null. The exact-DP lattice precision negative remains a separate diagnostic and is not relaxed.\n\n"
        "Generated BI4 and motion DAT are external producer assets. Their SHA values are copied from Root544/Root535 producer metadata; this source agent did not read, copy, or hash those payloads. Fresh111's existing A080/A120 full801 visual gate remains WAIT/null, so no new full24/1201 authorization is created.\n",
        encoding="utf-8",
    )
    write_manifest()
    print(json.dumps({
        "status": "six_root544_gencase_metadata_bound_native_initial_qa_disabled_full1201_gate_wait",
        "candidate_count": len(requests),
        "producer_statuses": {record["tag"]: record["status"] for record in producers},
        "full1201_authorized": False,
        "payloads_read_or_hashed_by_source_builder": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
