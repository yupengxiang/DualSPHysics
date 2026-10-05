#!/usr/bin/env python3
"""Build fresh112 from Root535 motion metadata without touching motion DATs.

Root535 is the only producer of the six scaled motion assets.  This builder
reads its JSON request/report/receipt metadata, records the producer-attested
motion SHA, and emits disabled GenCase requests.  It never opens, copies, or
rehashes a DAT file.
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
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
HANDOFF535 = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_fresh110_six_actual_motion_preparation_535"
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}
ROOT535_COMMIT = "root_stage1_f5_fresh110_six_actual_motion_preparation_535"
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
FRESH111_COMMIT = "d5d888cfa35f94ae5ebaf315c10e1eaddd8f16f0"


def sha(path: Path) -> str:
    """Hash a source/JSON metadata file; never call this on a science suffix."""
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden in fresh112: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def report_path(tag: str) -> Path:
    attempt = f"root-stage1-f5-c082s1-{tag.lower()}-motion-transform-110-root535"
    return DATA_CASE / attempt / "motion-transform-report.json"


def receipt_path(tag: str) -> Path:
    return report_path(tag).with_name("execution-receipt.json")


def request_path(tag: str) -> Path:
    return HANDOFF535 / f"C082S1_MOTION_{tag}-motion-request.json"


def producer_record(tag: str) -> dict[str, Any]:
    report_file = report_path(tag)
    receipt_file = receipt_path(tag)
    root_request_file = request_path(tag)
    report = load(report_file)
    receipt = load(receipt_file)
    root_request = load(root_request_file)
    nested_request = receipt.get("request", {})
    if not isinstance(nested_request, dict):
        raise ValueError(f"Root535 receipt request object missing: {receipt_file}")
    report_status = report.get("status")
    receipt_status = receipt.get("status")
    ready = (
        report_status == "completed"
        and receipt_status == "completed"
        and isinstance(report.get("output_motion"), str)
        and isinstance(report.get("output_motion_sha256"), str)
        and len(report["output_motion_sha256"]) == 64
        and report.get("rows") == 641
    )
    if root_request.get("attempt_id") != nested_request.get("attempt_id"):
        raise ValueError(f"Root535 attempt identity mismatch: {tag}")
    if nested_request.get("case_id") != CASE or report.get("schema") != "ds02.f5.c082s1.motion-transform-receipt.fresh110.v1":
        raise ValueError(f"Root535 producer schema/case mismatch: {tag}")
    return {
        "tag": tag,
        "status": "completed" if ready else "WAIT/null",
        "report_path": str(report_file),
        "report_sha256": sha(report_file),
        "receipt_path": str(receipt_file),
        "receipt_sha256": sha(receipt_file),
        "root_request_path": str(root_request_file),
        "root_request_sha256": sha(root_request_file),
        "attempt_id": nested_request.get("attempt_id"),
        "case_id": nested_request.get("case_id"),
        "report_schema": report.get("schema"),
        "report_status": report_status,
        "receipt_status": receipt_status,
        "output_motion": report.get("output_motion") if ready else None,
        "output_motion_sha256": report.get("output_motion_sha256") if ready else None,
        "output_motion_sha256_provenance": (
            "Root535 motion-transform-report.json producer field; source agent did not read, copy, or rehash DAT"
            if ready else None
        ),
        "rows": report.get("rows") if ready else None,
        "output_time_start_s": report.get("output_time_start_s") if ready else None,
        "output_time_end_s": report.get("output_time_end_s") if ready else None,
        "amplitude_scale": report.get("amplitude_scale"),
        "time_scale": report.get("time_scale"),
        "source_time_start_s": report.get("source_time_start_s"),
        "source_time_end_s": report.get("source_time_end_s"),
        "solver_started": report.get("solver_started"),
        "source_agent_did_not_run_worker": report.get("source_agent_did_not_run_worker"),
        "root_source_interpreter_digest": nested_request.get("root_source_interpreter_digest"),
        "root_actual_interpreter_digest": nested_request.get("root_actual_interpreter_digest"),
        "root_source_interpreter_digest_provenance": "Root535 request field; null means no source forecast digest was used",
        "root_actual_interpreter_digest_provenance": "Root535 execution request actual interpreter field",
    }


def replace_motion_bindings(values: list[Any], producer: dict[str, Any]) -> list[Any]:
    result: list[Any] = []
    for value in values:
        if value == "<root-bind:motion_transform_receipt>":
            result.append(producer["receipt_path"])
        elif value == "<root-bind:scaled_motion_output>":
            result.append(producer["output_motion"])
        else:
            result.append(value)
    if producer["report_path"] not in result:
        result.append(producer["report_path"])
    if producer["receipt_path"] not in result:
        result.append(producer["receipt_path"])
    return result


def replace_hash_bindings(values: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key == "<root-bind:motion_transform_receipt>":
            result[producer["receipt_path"]] = producer["receipt_sha256"]
        elif key == "<root-bind:scaled_motion_output>":
            if producer["output_motion"] is not None:
                # This is producer-attested output_motion_sha256, never a source-agent DAT hash.
                result[producer["output_motion"]] = producer["output_motion_sha256"]
        else:
            result[key] = value
    result[producer["report_path"]] = producer["report_sha256"]
    return result


def replace_hash_provenance(values: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in values.items():
        if key == "<root-bind:motion_transform_receipt>":
            result[producer["receipt_path"]] = "Root535 execution-receipt.json JSON metadata hash"
        elif key == "<root-bind:scaled_motion_output>":
            if producer["output_motion"] is not None:
                result[producer["output_motion"]] = producer["output_motion_sha256_provenance"]
        else:
            result[key] = value
    result[producer["report_path"]] = "Root535 motion-transform-report.json JSON metadata hash"
    return result


def fresh111_gate() -> dict[str, Any]:
    sidecar_file = FRESH111 / "metadata/fresh111-full1201-gate-sidecar.json"
    sidecar = load(sidecar_file)
    if sidecar.get("status") != "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass":
        raise ValueError("fresh111 gate status changed")
    if sidecar.get("short_window_semantics", {}).get("can_authorize_fresh110_full1201") is not False:
        raise ValueError("fresh111 incorrectly authorizes fresh110 full1201")
    if sidecar.get("existing_full801_gate", {}).get("current_status") != "WAIT/null":
        raise ValueError("fresh111 existing full801 gate is not WAIT/null")
    return {
        "sidecar_path": str(sidecar_file),
        "sidecar_sha256": sha(sidecar_file),
        "sidecar_commit": FRESH111_COMMIT,
        "status": "WAIT/null",
        "root511_short_render_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_pass": False,
        "required_before_fresh110_full1201": True,
        "future_authorization_receipt": None,
        "future_authorization_sha256": None,
    }


def build_candidate(tag: str, producer: dict[str, Any], gate: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    source_request = load(FRESH110 / "requests" / f"{tag}-gencase-request.json")
    source_binding = load(FRESH110 / "bindings" / f"{tag}-gencase-binding.json")
    lower = tag.lower()
    attempt_id = f"root-stage1-f5-c082s1-{lower}-genuine-gencase-112"
    binding_path = PKG / "bindings" / f"{tag}-gencase-binding.json"
    request_file = PKG / "requests" / f"{tag}-gencase-request.json"

    binding = copy.deepcopy(source_binding)
    binding["schema"] = "ds02.f5.c082s1.motion535-gencase-binding.fresh112.v1"
    binding["attempt_id"] = attempt_id
    binding["source_only"] = True
    binding["actual_counts"] = None
    binding["expected_fluid"] = None
    binding["motion_transform_attempt"] = producer["attempt_id"]
    binding["motion_transform_receipt"] = producer["receipt_path"]
    binding["motion_transform_report"] = producer["report_path"]
    binding["motion_transform_receipt_sha256"] = producer["receipt_sha256"]
    binding["motion_transform_report_sha256"] = producer["report_sha256"]
    binding["motion_asset"] = {
        "path": producer["output_motion"],
        "producer_attempt_id": producer["attempt_id"],
        "producer_receipt": producer["receipt_path"],
        "producer_report": producer["report_path"],
        "sha256": producer["output_motion_sha256"],
        "sha256_provenance": producer["output_motion_sha256_provenance"],
        "rows": producer["rows"],
        "output_time_window_s": [producer["output_time_start_s"], producer["output_time_end_s"]],
    }
    binding["motion_output_time_end_s"] = producer["output_time_end_s"]
    binding["motion_output_sha256"] = producer["output_motion_sha256"]
    binding["motion_output_rows"] = producer["rows"]
    binding["root_source_interpreter_digest"] = producer["root_source_interpreter_digest"]
    binding["root_actual_interpreter_digest"] = producer["root_actual_interpreter_digest"]
    binding["root_source_interpreter_digest_provenance"] = producer["root_source_interpreter_digest_provenance"]
    binding["root_actual_interpreter_digest_provenance"] = producer["root_actual_interpreter_digest_provenance"]
    binding["upstream_full801_visual_gate"] = gate
    assets = binding.get("assets", [{"relative_name": f"assets/f5_c082s1_motion_{lower}.dat"}])
    if not isinstance(assets, list) or len(assets) != 1:
        raise ValueError(f"unexpected asset binding shape: {tag}")
    assets[0]["source"] = producer["output_motion"]
    assets[0]["sha256"] = producer["output_motion_sha256"]
    assets[0]["sha256_provenance"] = producer["output_motion_sha256_provenance"]
    binding["assets"] = assets
    dump(binding_path, binding)
    binding_sha = sha(binding_path)

    request = copy.deepcopy(source_request)
    request["attempt_id"] = attempt_id
    request["binding"] = str(binding_path)
    request["binding_sha256"] = binding_sha
    request["disabled"] = True
    request["execution_allowed"] = False
    request["launch"] = False
    request["launch_allowed"] = False
    request["solver_allowed"] = False
    request["status"] = "disabled_until_root_review_and_actual_motion_metadata_bound"
    request["purpose"] = "genuine GenCase input only after Root review; Root535 motion producer is metadata-bound; GenCase counts and generated hashes remain null"
    request["motion_transform_attempt"] = producer["attempt_id"]
    request["motion_transform_receipt"] = producer["receipt_path"]
    request["motion_transform_report"] = producer["report_path"]
    request["motion_transform_receipt_sha256"] = producer["receipt_sha256"]
    request["motion_transform_report_sha256"] = producer["report_sha256"]
    request["motion_asset_path"] = producer["output_motion"]
    request["motion_asset_sha256"] = producer["output_motion_sha256"]
    request["motion_asset_sha256_provenance"] = producer["output_motion_sha256_provenance"]
    request["motion_rows"] = producer["rows"]
    request["motion_output_time_end_s"] = producer["output_time_end_s"]
    request["root_source_interpreter_digest"] = producer["root_source_interpreter_digest"]
    request["root_actual_interpreter_digest"] = producer["root_actual_interpreter_digest"]
    request["root_source_interpreter_digest_provenance"] = producer["root_source_interpreter_digest_provenance"]
    request["root_actual_interpreter_digest_provenance"] = producer["root_actual_interpreter_digest_provenance"]
    request["upstream_full801_visual_gate"] = gate
    request["input_files"] = replace_motion_bindings(request["input_files"], producer)
    request["input_sha256"] = replace_hash_bindings(request["input_sha256"], producer)
    request["input_sha256_provenance"] = replace_hash_provenance(request["input_sha256_provenance"], producer)
    request["future_output_hashes"] = {key: None for key in request["future_output_hashes"]}
    request["generated_bi4"] = None
    request["generated_xml"] = None
    request["expected_counts"] = None
    request["source_only"] = True
    request["full801_authorized"] = False
    request["q_n_granted"] = False
    dump(request_file, request)
    return request, binding


def write_manifest() -> None:
    report = PKG / "metadata/fresh112-validator-report.json"
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path == report:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES or path.suffix.lower() not in SOURCE_SUFFIXES:
            raise ValueError(f"unsupported fresh112 file: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh112-source-manifest.v1",
        "status": "six_motion535_bound_gencase_requests_disabled_full1201_gate_wait",
        "files": files,
        "validator_report_excluded_from_manifest": True,
        "fresh110_modified": False,
        "fresh111_modified": False,
        "full1201_authorized": False,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "motion_dat_read_copied_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })


def main() -> int:
    gate = fresh111_gate()
    producers = [producer_record(tag) for tag in TAGS]
    if {record["tag"] for record in producers} != set(TAGS):
        raise ValueError("motion producer tag set changed")
    requests = []
    for tag, producer in zip(TAGS, producers):
        request, _binding = build_candidate(tag, producer, gate)
        requests.append(request)
    dump(PKG / "metadata/fresh112-motion535-binding-provenance.json", {
        "schema": "ds02.f5.c082s1.fresh112-motion535-binding-provenance.v1",
        "status": "six_root535_motion_outputs_bound_or_wait_null_gencase_disabled",
        "root535_handoff": str(HANDOFF535),
        "root535_identity": ROOT535_COMMIT,
        "fresh110_commit": FRESH110_COMMIT,
        "fresh111_commit": FRESH111_COMMIT,
        "fresh111_gate": gate,
        "candidates": producers,
        "full_event_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "future_gencase_counts": None,
        "future_generated_bi4_sha256": None,
        "future_generated_xml_sha256": None,
        "future_prepared_input_report_sha256": None,
        "future_gencase_receipt_sha256": None,
        "independent_case_count_increment": 0,
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "motion_dat_read_copied_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    dump(PKG / "metadata/fresh112-source-plan.json", {
        "schema": "ds02.f5.c082s1.fresh112-source-plan.v1",
        "status": "six_motion535_bound_gencase_requests_disabled_full1201_gate_wait",
        "candidate_count": 6,
        "candidate_tags": list(TAGS),
        "motion_producer": "Root535 completed motion-transform-report.json and execution-receipt.json metadata; source DAT remains external",
        "full_event_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "gencase_requests_disabled": True,
        "execution_allowed": False,
        "future_counts_and_hashes_null": True,
        "fresh111_gate_status": gate["status"],
        "root511_short_window_can_authorize_new_full1201": False,
        "existing_A080_A120_full801_visual_pass": False,
        "source110_forecast_interpreter_digest_used": False,
        "root535_actual_interpreter_digest_bound": True,
        "independent_case_count_increment": 0,
        "historical_exact_dp_negative_retained": True,
        "historical_A_B_penetration_failures_retained": True,
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "motion_dat_read_copied_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })
    (PKG / "README.md").write_text(
        "# F5 fresh112: Root535 motion-bound GenCase inputs\n\n"
        "Root535 produced one independent scaled motion asset for each of the six fresh110 tags. This package binds each completed producer report and execution receipt to a disabled genuine GenCase request. The output motion path and SHA are producer-attested metadata; the source agent does not open, copy, or rehash any DAT.\n\n"
        "Every request remains disabled with execution, launch, solver, and full801 authorization false. The target remains 24 s at tout 0.02 s with 1201 frames; GenCase counts, prepared-input report, BI4/XML, and GenCase receipt hashes remain null until Root explicitly runs and reviews the request.\n\n"
        "Fresh111's gate is carried forward: Root511's short 0..1 s/51-state review cannot authorize these new full24/1201 cases. Both existing A080 and A120 still require their own completed full16/801 native, typed/H5, XMF, full-window render, and explicit Root visual pass.\n\n"
        "Root535 source forecast interpreter digest is recorded as null where the producer request reports null; only Root535's actual interpreter digest is bound. This package reads JSON/source metadata only and does not start jobs or modify fresh110, fresh111, or shared state.\n",
        encoding="utf-8",
    )
    write_manifest()
    print(json.dumps({
        "status": "six_motion535_bound_gencase_requests_disabled_full1201_gate_wait",
        "candidate_count": len(requests),
        "full1201_authorized": False,
        "motion_dat_read_copied_or_hashed_by_source_builder": False,
        "fresh110_modified": False,
        "fresh111_modified": False,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
