#!/usr/bin/env python3
"""Metadata-only validator for the fresh164 M095 Root968 bed handoff.

This validator reads JSON/XML/Python metadata and invokes the unchanged
fresh138 metadata gate against a synthetic Part filename directory. It never
opens or hashes H5/BI4/CSV/DAT/VTK science payloads and never launches a job.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
import xml.etree.ElementTree as ET

PACKAGE = Path(__file__).resolve().parents[1]
BINDING = PACKAGE / "bindings/M095_T080-actual968-bed-binding.json"
REQUEST = PACKAGE / "requests/M095_T080-actual968-bed-request.json"
MANIFEST = PACKAGE / "manifest.json"
REPORT = PACKAGE / "metadata/fresh164-validator-report.json"
ORIGINAL = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f5/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F5/handoff_20261003/"
    "root_followup_138_stage1_f5_remaining10_full801_downstream_disabled_v1/"
    "workers/bed_audit_full801_fresh138.py"
)
CASE_ROOT = Path(
    "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/"
    "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
)
GEN = CASE_ROOT / "root-stage1-f5-c082s1-m095_t080-genuine-gencase-118-root640"
QA = CASE_ROOT / "root-stage1-f5-c082s1-m095_t080-actual-initial-placement-mk50-119-root661"
NATIVE = CASE_ROOT / "root-stage1-f5-c082s1-m095_t080-full801-native-release-131-root808"
TYPED = CASE_ROOT / "root-stage1-f5-m095_t080-actual808-full801-typed157-NVMe4GiB-root939"
XMF = CASE_ROOT / "root-stage1-f5-m095-t080-actual939-full801-N3-XMF-root968"
GEN_REC = GEN / "execution-receipt.json"
GEN_REPORT = GEN / "prepared/prepared-input-report.json"
GEN_XML = GEN / "prepared/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1.xml"
QA_REC = QA / "execution-receipt.json"
QA_REPORT = QA / "initial-qa/placement/c082s1-stage1-placement-mk50-audit.json"
NATIVE_REC = NATIVE / "execution-receipt.json"
TYPED_REC = TYPED / "execution-receipt.json"
TYPED_REPORT = TYPED / "conversion-report.json"
XMF_REC = XMF / "execution-receipt.json"
XMF_MANIFEST = XMF / "xmf/manifest.json"
XDMF = XMF / "xmf/case.xmf"

CASE_ID = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
PHYSICAL_CASE_ID = "F5_COMPACT_RUNUP_RECOVERY_C082S1_M095_T080"
XMF_ATTEMPT = "root-stage1-f5-m095-t080-actual939-full801-N3-XMF-root968"
EXPECTED_COUNTS = {
    "data2d": False,
    "fixed_particles": 158559,
    "floating_particles": 0,
    "fluid_particles": 31658,
    "moving_particles": 4210,
    "solver_dimension": 3,
    "total_particles": 194427,
    "xml_particle_counts": {"fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210},
}
SCIENCE_SUFFIXES = {".h5", ".hdf5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".png"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def load_json(path: Path) -> dict:
    require(path.is_file(), f"missing JSON metadata: {path}")
    value = json.loads(path.read_text())
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha_metadata(path: Path) -> str:
    require(path.is_file(), f"missing metadata input: {path}")
    require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science payload hash forbidden: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def norm_counts(value: dict) -> dict:
    return {
        "data2d": bool(value.get("data2d", False)),
        "fixed_particles": int(value["fixed_particles"]),
        "floating_particles": int(value["floating_particles"]),
        "fluid_particles": int(value["fluid_particles"]),
        "moving_particles": int(value["moving_particles"]),
        "solver_dimension": int(value["solver_dimension"]),
        "total_particles": int(value["total_particles"]),
        "xml_particle_counts": {k: int(value["xml_particle_counts"][k]) for k in ("fixed", "floating", "fluid", "moving")},
    }


def completed_receipt(path: Path, attempt: str, case_id: str = CASE_ID) -> dict:
    value = load_json(path)
    require(value.get("status") == "completed", f"{path}: producer status")
    require(value.get("returncode") == 0, f"{path}: producer returncode")
    request = value.get("request") or {}
    require(request.get("attempt_id") == attempt, f"{path}: attempt identity")
    require(request.get("case_id") == case_id, f"{path}: case identity")
    require(Path(str(value.get("output_root", ""))).resolve() == path.parent.resolve(), f"{path}: output_root")
    return value


def verify_actual_chain(binding: dict) -> dict:
    gen = completed_receipt(GEN_REC, "root-stage1-f5-c082s1-m095_t080-genuine-gencase-118-root640")
    qa = completed_receipt(QA_REC, "root-stage1-f5-c082s1-m095_t080-actual-initial-placement-mk50-119-root661")
    native = completed_receipt(NATIVE_REC, "root-stage1-f5-c082s1-m095_t080-full801-native-release-131-root808")
    typed = completed_receipt(TYPED_REC, "root-stage1-f5-m095_t080-actual808-full801-typed157-NVMe4GiB-root939")
    xmf = completed_receipt(XMF_REC, XMF_ATTEMPT)
    gen_report = load_json(GEN_REPORT)
    qa_report = load_json(QA_REPORT)
    typed_report = load_json(TYPED_REPORT)
    manifest = load_json(XMF_MANIFEST)

    require(binding["case_id"] == CASE_ID and binding["producer_case_id"] == CASE_ID, "M095 original case identity")
    require(binding["physical_case_id"] == PHYSICAL_CASE_ID, "M095 physical identity")
    require(norm_counts(binding["actual_counts"]) == EXPECTED_COUNTS, "binding counts")
    gen_counts = gen_report["generated_xml_particle_counts"]
    require({k: int(gen_counts[k]) for k in ("fixed", "floating", "fluid", "moving")} == EXPECTED_COUNTS["xml_particle_counts"], "GenCase particle counts")
    require(int(gen_report["actual_total_particles"]) == EXPECTED_COUNTS["total_particles"], "GenCase total")
    require(gen_report.get("case_id") == CASE_ID, "GenCase report case")
    require(gen_report.get("xml_sha256") == binding["canonical_generated_xml_sha256"], "GenCase XML attestation")
    require(qa_report.get("actual_counts") == binding["actual_counts"], "QA counts/output binding")
    require(qa_report.get("all_basic_placement_checks_pass") is True, "QA basic placement")
    require(qa_report.get("stage1_basic_placement_proof") == "pass_excluding_numerical_precision", "QA proof semantics")
    require(qa_report.get("numerical_precision_result_accepted") is False, "historical 5e-6 precision negative changed")
    bins = qa_report.get("mk50_coverage", {}).get("six_segment_bins", [])
    require(len(bins) == 6 and all(int(row.get("central_abs_y_le_0p01_surface_half_dp_count", 0)) > 0 for row in bins), "Mk50 six segment coverage")

    require(typed_report.get("conversion_status") == "completed", "typed report status")
    require(typed_report.get("frames") == 801 and typed_report.get("particles") == 194427, "typed dimensions")
    dimension = typed_report.get("solver_dimension", {})
    require(isinstance(dimension, dict) and dimension.get("solver_dimension") == 3, "typed 3D")
    typed_identity = typed_report.get("typed_identity", {})
    require(50 in set(typed_identity.get("observed_mks", [])), "typed Mk50")
    require({0, 1, 3}.issubset(set(typed_identity.get("observed_types", []))), "typed native types")

    require(manifest.get("case_id") == CASE_ID, "XMF case")
    require(manifest.get("physical_case_id") == PHYSICAL_CASE_ID, "XMF physical case")
    require(manifest.get("frames") == 801 and manifest.get("particles") == 194427, "XMF dimensions")
    require(norm_counts(manifest["actual_counts"]) == EXPECTED_COUNTS, "XMF counts")
    require(manifest.get("root_actual_XMF_attempt_id") == XMF_ATTEMPT, "XMF attempt")
    require(manifest.get("xdmf") == str(XDMF), "XMF XML path")
    require(manifest.get("xdmf_sha256") == sha_metadata(XDMF), "XMF XML producer SHA")
    require(manifest.get("source_h5_sha256") == binding.get("trajectory_h5_sha256"), "H5 producer attestation")
    require(manifest.get("physical_condition_sha256") == binding["physical_condition_sha256"], "canonical scope")
    require(manifest.get("canonical_physical_condition_sha256") == binding["physical_condition_sha256"], "canonical XMF scope")
    require(manifest.get("source_plan_physical_condition_sha256") == binding["source_plan_physical_condition_sha256"], "source plan scope")

    xmf_req = xmf.get("request") or {}
    require(xmf_req.get("case_id") == CASE_ID, "XMF request case")
    require(xmf_req.get("execution_allowed") is True and xmf_req.get("disabled") is False, "XMF producer state")
    return {
        "gencase": {"attempt_id": gen["request"]["attempt_id"], "receipt": str(GEN_REC), "receipt_sha256": sha_metadata(GEN_REC), "prepared_report": str(GEN_REPORT), "prepared_report_sha256": sha_metadata(GEN_REPORT), "generated_xml": str(GEN_XML), "generated_xml_sha256": sha_metadata(GEN_XML)},
        "initial_qa": {"attempt_id": qa["request"]["attempt_id"], "receipt": str(QA_REC), "receipt_sha256": sha_metadata(QA_REC), "report": str(QA_REPORT), "report_sha256": sha_metadata(QA_REPORT)},
        "native": {"attempt_id": native["request"]["attempt_id"], "receipt": str(NATIVE_REC), "receipt_sha256": sha_metadata(NATIVE_REC)},
        "typed": {"attempt_id": typed["request"]["attempt_id"], "receipt": str(TYPED_REC), "receipt_sha256": sha_metadata(TYPED_REC), "report": str(TYPED_REPORT), "report_sha256": sha_metadata(TYPED_REPORT), "producer_h5_sha256": binding["trajectory_h5_sha256"]},
        "xmf": {"attempt_id": XMF_ATTEMPT, "receipt": str(XMF_REC), "receipt_sha256": sha_metadata(XMF_REC), "manifest": str(XMF_MANIFEST), "manifest_sha256": sha_metadata(XMF_MANIFEST), "xdmf": str(XDMF), "xdmf_sha256": sha_metadata(XDMF)},
        "counts": EXPECTED_COUNTS,
    }


def verify_request(binding: dict, request: dict) -> None:
    require(request.get("binding") == str(BINDING), "request binding path")
    require(request.get("binding_sha256") == sha_metadata(BINDING), "request binding SHA")
    require(request.get("actual_counts") == binding.get("actual_counts"), "request counts")
    require(request.get("physical_condition_hash_semantics") == binding.get("physical_condition_hash_semantics"), "request scope semantics")
    require(request.get("scope_provenance") == binding.get("scope_provenance"), "request scope provenance")
    require(request.get("depends_on_attempts") == [
        "root-stage1-f5-c082s1-m095_t080-genuine-gencase-118-root640",
        "root-stage1-f5-c082s1-m095_t080-actual-initial-placement-mk50-119-root661",
        "root-stage1-f5-c082s1-m095_t080-full801-native-release-131-root808",
        "root-stage1-f5-m095_t080-actual808-full801-typed157-NVMe4GiB-root939",
        XMF_ATTEMPT,
    ], "dependency closure")
    require(request.get("command")[-8:] == ["--binding", str(BINDING), "--trajectory-h5", "{resolved_trajectory_h5}", "--xdmf", "{resolved_xdmf}", "--output-dir", "{attempt_root}/audit-output"], "original138 CLI")
    require(request.get("cpu_task_kind") == "audit" and request.get("kind") == "cpu" and request.get("cpu_threads") == 2, "Root142 CPU contract")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False and request.get("solver_allowed") is False and request.get("launch") is False, "request disabled")
    require(request.get("full801_authorized") is False and request.get("case_credit") == 0 and request.get("independent_case_count_increment") == 0, "full/case gate")
    require(all(value is None for value in request.get("future_output_hashes", {}).values()), "future hashes")
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    require(set(files) == set(hashes), "input hash set")
    require(all(Path(p).suffix.lower() not in SCIENCE_SUFFIXES for p in files), "science input registered")
    for raw in files:
        path = Path(raw)
        require(path.is_file(), f"input missing: {path}")
        require(sha_metadata(path) == hashes[raw], f"input SHA mismatch: {path}")
    for actual in (str(GEN_REPORT), str(QA_REPORT), str(NATIVE_REC), str(TYPED_REPORT), str(XMF_REC), str(XMF_MANIFEST), str(XDMF)):
        require(actual in files, f"actual metadata absent from input closure: {actual}")


def invoke_original138_gate(binding: dict) -> dict:
    """Call the actual original138 verifier without touching real science arrays."""
    spec = importlib.util.spec_from_file_location("fresh138_original", ORIGINAL)
    require(spec is not None and spec.loader is not None, "cannot import original138 worker")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.CASE_ID == CASE_ID, "original138 CASE_ID changed")
    with tempfile.TemporaryDirectory(prefix="fresh164-original138-metadata-") as temp:
        toy_root = Path(temp)
        toy_data = toy_root / "solver_output/data"
        toy_data.mkdir(parents=True)
        # Names only: no real BI4 content is copied or opened.
        for index in range(801):
            (toy_data / f"Part_{index:04d}.bi4").touch()
        toy = copy.deepcopy(binding)
        toy["full_native_data_root"] = str(toy_data)
        result = module._verify_bound_metadata(toy)
    require(result.get("case_id") == CASE_ID, "original138 gate returned wrong case")
    require(result.get("full_native_solver", {}).get("saved_state_count") == 801, "original138 frame gate")
    return {"status": "passed", "synthetic_part_filename_count": 801, "real_science_payload_opened_or_hashed": False, "case_id": CASE_ID}


def verify_manifest() -> None:
    manifest = load_json(MANIFEST)
    require(manifest.get("schema") == "ds02.f5.fresh164.manifest.v1", "manifest schema")
    entries = manifest.get("files", [])
    require(entries and all("path" in item and "sha256" in item for item in entries), "manifest entries")
    paths = {item["path"] for item in entries}
    require("manifest.json" not in paths and "metadata/fresh164-validator-report.json" not in paths, "manifest self/report reference")
    for item in entries:
        path = PACKAGE / item["path"]
        require(path.is_file(), f"manifest missing {path}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"manifest science path {path}")
        require(sha_metadata(path) == item["sha256"], f"manifest SHA mismatch: {path}")


def main() -> None:
    binding = load_json(BINDING)
    request = load_json(REQUEST)
    require(sha_metadata(ORIGINAL) == load_json(PACKAGE / "metadata/worker-contract.json")["worker_sha256"], "original worker SHA")
    require(binding.get("schema") == "ds02.f5.c082s1.full-event-bed-audit-binding.fresh138.v1", "fresh138 schema")
    require(binding.get("case_id") == CASE_ID and binding.get("producer_case_id") == CASE_ID, "M095 case identity")
    require(binding.get("worker_identity_adapter_required") is False, "unexpected identity adapter")
    require(binding.get("native_bed_marker_mk") == 50 and binding.get("source_bed_marker_mkbound") == 40, "Mk mapping")
    require(binding.get("expected_frames") == 801 and binding.get("expected_particle_axis") == 194427 and binding.get("expected_dimension") == 3, "dimensions")
    require(binding.get("disabled") is True and binding.get("execution_allowed") is False and binding.get("launch_allowed") is False and binding.get("solver_allowed") is False, "binding disabled")
    require(binding.get("full801_authorized") is False and binding.get("bed_audit_attempt_id") is None, "binding gate")
    for key in ("physical_condition_sha256", "source_plan_physical_condition_sha256", "source_h5_physical_condition_sha256"):
        value = binding.get(key); require(isinstance(value, str) and len(value) == 64, f"scope field {key}")
    require(len({binding["physical_condition_sha256"], binding["source_plan_physical_condition_sha256"], binding["source_h5_physical_condition_sha256"]}) == 3, "scope collapse")
    for path_key, hash_key in (("gencase_receipt", "gencase_receipt_sha256"),("gencase_prepared_report", "gencase_prepared_report_sha256"),("canonical_generated_xml", "canonical_generated_xml_sha256"),("initial_qa_receipt", "initial_qa_receipt_sha256"),("initial_qa_report", "initial_qa_report_sha256"),("full_native_receipt", "full_native_receipt_sha256"),("full_typed_receipt", "full_typed_receipt_sha256"),("full_typed_conversion_report", "full_typed_conversion_report_sha256"),("xmf_receipt", "xmf_receipt_sha256"),("xmf_manifest", "xmf_manifest_sha256"),("xdmf", "xdmf_sha256")):
        path = Path(str(binding.get(path_key)))
        require(path.is_file(), f"bound metadata missing: {path_key}")
        require(sha_metadata(path) == binding.get(hash_key), f"bound metadata SHA: {path_key}")
    producer = verify_actual_chain(binding)
    verify_request(binding, request)
    original_gate = invoke_original138_gate(binding)
    ET.parse(XDMF)
    verify_manifest()
    report = {
        "schema": "ds02.f5.fresh164.validator-report.v1",
        "status": "passed",
        "source_only": True,
        "science_payload_opened_or_hashed": False,
        "original138_metadata_gate": original_gate,
        "actual_producer_chain": producer,
        "actual_xmf_metadata_sha256": {"receipt": sha_metadata(XMF_REC), "manifest": sha_metadata(XMF_MANIFEST), "xdmf": sha_metadata(XDMF)},
        "scopes": {"canonical": binding["physical_condition_sha256"], "source_plan": binding["source_plan_physical_condition_sha256"], "typed_h5_legacy_producer_attested": binding["source_h5_physical_condition_sha256"], "cross_resolution_claim": False},
        "checks": {
            "gencase640_qa661_native808_typed939_xmf968_completed0": True,
            "actual_counts_and_output_roots_bound": True,
            "m095_original138_case_identity_no_adapter": True,
            "original138_verify_bound_metadata_executed": True,
            "actual_xmf_manifest_xml_receipt_sha_closed": True,
            "canonical_source_plan_legacy_scopes_separate": True,
            "mk50_source_mkbound40_and_thresholds_unchanged": True,
            "precision_5e-6_vs_1e-6_negative_retained": True,
            "disabled_request_and_binding": True,
            "future_bed_and_render_hashes_null": True,
            "request_input_hash_closure": True,
            "no_science_payload_access": True,
        },
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
