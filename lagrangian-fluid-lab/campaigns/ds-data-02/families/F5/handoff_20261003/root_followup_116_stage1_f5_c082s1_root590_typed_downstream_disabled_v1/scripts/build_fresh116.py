#!/usr/bin/env python3
"""Build the disabled Root590 typed -> XMF -> bed -> Root023 source pack.

This builder reads only source files and JSON metadata.  It records the actual
Root588 short-window approval, Root575 native receipts, and the current Root590
typed receipt snapshot.  BI4/CSV/DAT/H5/VTK and solver products are never
opened or hashed.  A completed producer's H5 path and digest may be copied
from its conversion-report attestation without opening the H5; unfinished
producer fields remain null/placeholders.
"""
from __future__ import annotations

import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
HANDOFF_F5 = PKG.parent
FRESH115 = HANDOFF_F5 / "root_followup_115_stage1_f5_c082s1_root575_full801_downstream_disabled_v1"
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_CASE = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5/F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1")
NATIVE_HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_currenttwo_actual_short51_review_full801_native_575"
TYPED_HANDOFF = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_fullnative575_fresh115_full801_typed_590"
SHORT_APPROVAL = INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f5_actual_short51_allviews_visual_full801_approval_574/actual-root-short51-visual-full801-native-approval.json"
TAGS = ("A080", "A120")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
COUNTS = {"dimension": 3, "fixed": 158559, "floating": 0, "fluid": 31658, "moving": 4210, "total": 194427}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def sha_source(path: Path) -> str:
    if path.suffix.lower() in SCIENCE_SUFFIXES:
        raise ValueError(f"science payload hash forbidden: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prev(rel: str) -> Path:
    return FRESH115 / rel


def source_json(rel: str) -> dict[str, Any]:
    return load(prev(rel))


def local(rel: str) -> str:
    return str((PKG / rel).resolve())


def native_request(tag: str) -> dict[str, Any]:
    return source_json(f"requests/{tag}-full801-native-request.json")


def physical_binding(tag: str) -> dict[str, Any]:
    return source_json(f"bindings/{tag}-full801-physical-binding.json")


def xmf_binding(tag: str) -> dict[str, Any]:
    return source_json(f"bindings/{tag}-full801-xmf-binding.json")


def bed_binding(tag: str) -> dict[str, Any]:
    return source_json(f"bindings/{tag}-full801-bed-audit-binding.json")


def native_attempt(tag: str) -> str:
    return native_request(tag)["attempt_id"]


def typed_attempt(tag: str) -> str:
    return f"root-stage1-f5-c082s1-{tag}-full801-native-typed-575-root590"


def downstream_attempt(tag: str, kind: str) -> str:
    return f"root-stage1-f5-c082s1-{tag}-full801-native-{kind}-590"


def producer_paths(tag: str) -> dict[str, Any]:
    native = native_request(tag)
    typed_req_path = TYPED_HANDOFF / f"{tag}-full801-typed-request.json"
    typed_receipt = DATA_CASE / typed_attempt(tag) / "execution-receipt.json"
    conversion_report = DATA_CASE / typed_attempt(tag) / "typed/conversion-report.json"
    result: dict[str, Any] = {
        "native_attempt_id": native_attempt(tag),
        "native_receipt": str(DATA_CASE / native_attempt(tag) / "execution-receipt.json"),
        "native_receipt_sha256": None,
        "typed_attempt_id": typed_attempt(tag),
        "typed_request": str(typed_req_path),
        "typed_request_sha256": sha_source(typed_req_path),
        "typed_request_status": "registered_root590_enabled_producer_request",
        "typed_receipt": str(typed_receipt) if typed_receipt.exists() else None,
        "typed_receipt_sha256": sha_source(typed_receipt) if typed_receipt.exists() else None,
        "typed_status": None,
        "typed_output_root": None,
        "conversion_report": str(conversion_report) if conversion_report.exists() else None,
        "conversion_report_sha256": sha_source(conversion_report) if conversion_report.exists() else None,
        "trajectory_h5": None,
        "trajectory_h5_sha256": None,
        "science_payloads_read_or_hashed_by_source_builder": False,
    }
    native_receipt = Path(result["native_receipt"])
    if native_receipt.exists():
        result["native_receipt_sha256"] = sha_source(native_receipt)
    if typed_receipt.exists():
        receipt = load(typed_receipt)
        result["typed_status"] = receipt.get("status")
        result["typed_output_root"] = receipt.get("output_root")
    else:
        result["typed_status"] = "not_started_or_receipt_not_yet_published"
    if conversion_report.exists():
        report = load(conversion_report)
        h5_path = report.get("output_hdf5")
        h5_sha = report.get("output_sha256")
        if not isinstance(h5_path, str) or Path(h5_path).suffix.lower() not in {".h5", ".hdf5"}:
            raise ValueError(f"{tag} conversion report has no H5 producer path")
        if not isinstance(h5_sha, str) or len(h5_sha) != 64:
            raise ValueError(f"{tag} conversion report has no H5 producer digest")
        result.update({
            "trajectory_h5": h5_path,
            "trajectory_h5_sha256": h5_sha,
            "conversion_report_status": report.get("conversion_status"),
            "conversion_report_frames": report.get("frames"),
            "conversion_report_particles": report.get("particles"),
            "conversion_report_solver_dimension": report.get("solver_dimension"),
            "conversion_report_coordinate_frame": report.get("coordinate_frame"),
            "h5_producer_attestation": {
                "output_hdf5": h5_path,
                "output_sha256": h5_sha,
                "storage_protocol_verified_published_output_sha256": (report.get("storage_protocol") or {}).get("verified_published_output_sha256"),
                "legacy_report_physical_scope_sha256": (report.get("hash_scopes") or {}).get("physical_condition_sha256"),
                "source_agent_did_not_open_or_rehash_h5": True,
            },
        })
    return result


def root_gate() -> dict[str, Any]:
    approval = load(SHORT_APPROVAL)
    if approval.get("status") != "actual_short51_all_saved_states_root_visual_pass_currenttwo_full801_native_only_approved":
        raise ValueError("Root574 short-window approval status changed")
    rows = {row.get("tag"): row for row in approval.get("rows", [])}
    if set(rows) != set(TAGS):
        raise ValueError("Root574 approval does not cover A080/A120")
    for tag in TAGS:
        row = rows[tag]
        if row.get("full16s801_native_qualification_only_approved") is not True or row.get("complete_case_visual_approval") is not False:
            raise ValueError(f"Root574 approval scope changed for {tag}")
    return {
        "schema": "ds02.f5.c082s1.root574-to-root590-downstream-gate.fresh116.v1",
        "status": "PASS/root588_root574_short_window_native_approval_actual",
        "root574_approval_path": str(SHORT_APPROVAL),
        "root574_approval_sha256": sha_source(SHORT_APPROVAL),
        "root574_short_window_visual_pass": True,
        "root574_scope": "native full16s/801 qualification only; short preview and native approval do not certify full bed/render or complete runup event",
        "root575_native_actual_completed0_required": True,
        "root575_native_launch_allowed": True,
        "root590_typed_producer_must_be_actual_per_case": True,
        "full801_xmf_bed_render_authorized": False,
        "complete_case_visual_approval": False,
        "new_six_full24s1201_gate": approval.get("new_six_full24s1201_gate"),
        "new_six_full24s1201_authorized": False,
        "future_downstream_receipts_and_hashes": None,
    }


def copy_source_inputs() -> None:
    for name in ("A080-Definition.xml", "A080-owner.json", "A120-Definition.xml", "A120-owner.json"):
        shutil.copy2(prev(f"inputs/{name}"), PKG / "inputs" / name)
    shutil.copy2(prev("workers/export_xmf_legacy_aware.py"), PKG / "workers/export_xmf_legacy_aware.py")
    for tag in TAGS:
        source = prev(f"workers/bed_audit_{tag}_full801.py").read_text(encoding="utf-8")
        source = source.replace("full-event-bed-audit-binding.fresh115.v1", "full-event-bed-audit-binding.fresh116.v1")
        source = source.replace("full-event-bed-footprint-audit.fresh115.v1", "full-event-bed-footprint-audit.fresh116.v1")
        (PKG / "workers" / f"bed_audit_{tag}_full801.py").write_text(source, encoding="utf-8")


def attested_metadata_hashes(paths: list[str], attested: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    hashes: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    for raw in paths:
        if raw.startswith("<root-bind:"):
            hashes[raw] = None
            provenance[raw] = "future Root590 producer binding; null until Root binds actual receipt/report"
            continue
        path = Path(raw)
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            if raw not in attested or not isinstance(attested[raw], str) or len(attested[raw]) != 64:
                raise ValueError(f"science input lacks producer attestation: {raw}")
            hashes[raw] = attested[raw]
            provenance[raw] = "producer-attested science payload digest; source116 did not open or rehash payload"
            continue
        if raw in attested:
            hashes[raw] = attested[raw]
            provenance[raw] = "producer-attested metadata or generated XML; source116 did not read science payload"
        elif path.exists():
            hashes[raw] = sha_source(path)
            provenance[raw] = "source/JSON/XML/Python metadata hash"
        else:
            hashes[raw] = None
            provenance[raw] = "future or external metadata input; remains null"
    return hashes, provenance


def static_inputs(tag: str, gate: dict[str, Any], producer: dict[str, Any], extra: list[str]) -> tuple[list[str], dict[str, Any]]:
    phys = physical_binding(tag)
    native = native_request(tag)
    values = [
        local(f"bindings/{tag}-full801-native-binding.json"),
        local(f"bindings/{tag}-full801-physical-binding.json"),
        local(f"bindings/{tag}-full801-xmf-binding.json"),
        local(f"bindings/{tag}-full801-bed-audit-binding.json"),
        local(f"bindings/{tag}-full801-render-binding.json"),
        local(f"inputs/{tag}-Definition.xml"), local(f"inputs/{tag}-owner.json"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_strict_dispatch_v1.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/launch.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_home_floor_eight_solver_dispatch_230/root_native_home_floor_inventory_policy.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_user_resource_window_512gpu_3840cpu_064/resource-window-approval.json"),
        str(INTEGRATION / "lagrangian-fluid-lab/scripts/ds_data02_nvme_convert_v1.py"),
        str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"),
        str(NATIVE_HANDOFF / f"{tag}-full801-native-request.json"),
        str(TYPED_HANDOFF / f"{tag}-full801-typed-request.json"),
        str(SHORT_APPROVAL),
        str(TYPED_HANDOFF / "actual-root-two-full801typed-enable-review.json"),
        str(DATA_CASE / native_attempt(tag) / "execution-receipt.json"),
        native.get("generated_xml"), "<root-bind:generated_bi4>",
        "<root-bind:full_native_receipt>", "<root-bind:full_typed_receipt>", "<root-bind:full_typed_report>",
        "<root-bind:full_trajectory_h5>", "<root-bind:full_xmf_manifest>", "<root-bind:full_xdmf>",
        "<root-bind:root590_typed_receipt>", "<root-bind:root590_conversion_report>",
        str(SHORT_APPROVAL),
    ]
    if producer.get("typed_receipt"):
        values.append(producer["typed_receipt"])
    if producer.get("conversion_report"):
        values.append(producer["conversion_report"])
    if producer.get("trajectory_h5"):
        values.append(producer["trajectory_h5"])
    replacements = {
        "<root-bind:full_native_receipt>": producer.get("native_receipt"),
        "<root-bind:full_typed_receipt>": producer.get("typed_receipt"),
        "<root-bind:full_typed_report>": producer.get("conversion_report"),
        "<root-bind:full_trajectory_h5>": producer.get("trajectory_h5"),
    }
    values = [replacements.get(value, value) or value for value in values]
    values.extend(extra)
    unique: list[str] = []
    for value in values:
        if value and value not in unique:
            unique.append(value)
    attested = {native.get("generated_xml"): native.get("generated_xml_sha256"), str(SHORT_APPROVAL): sha_source(SHORT_APPROVAL)}
    native_receipt = str(DATA_CASE / native_attempt(tag) / "execution-receipt.json")
    if Path(native_receipt).exists():
        attested[native_receipt] = sha_source(Path(native_receipt))
    attested[producer["typed_request"]] = producer["typed_request_sha256"]
    if producer.get("typed_receipt"):
        attested[producer["typed_receipt"]] = producer["typed_receipt_sha256"]
    if producer.get("conversion_report"):
        attested[producer["conversion_report"]] = producer["conversion_report_sha256"]
    if producer.get("trajectory_h5"):
        attested[producer["trajectory_h5"]] = producer["trajectory_h5_sha256"]
    hashes, provenance = attested_metadata_hashes(unique, attested)
    return unique, {"sha256": hashes, "provenance": provenance}


def physical(tag: str, gate: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(physical_binding(tag))
    value["schema"] = "ds02.f5.c082s1.full801-physical-binding.fresh116.v1"
    value["physical_binding_path"] = local(f"bindings/{tag}-full801-physical-binding.json")
    value["source_preparation"] = {**(value.get("source_preparation") or {}), "source_only_package": "fresh116", "root574_actual_native_approval": True, "science_payloads_read_or_hashed_by_source_builder": False}
    value["root574_gate"] = gate
    return value


def native_binding(tag: str, gate: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    old = source_json(f"bindings/{tag}-full801-native-binding.json")
    value = copy.deepcopy(old)
    value.update({"schema": "ds02.f5.c082s1.root575-full801-native-binding.fresh116.v1", "root574_gate": gate, "root575_gate": gate, "native_actual_status": "completed/0", "native_actual_receipt": producer["native_receipt"], "native_actual_receipt_sha256": producer["native_receipt_sha256"], "full801_authorized": True, "typed_downstream_authorized": False, "source_agent_did_not_read_science_payloads": True})
    value["future_output_hashes"] = None
    return value


def typed_snapshot(tag: str, gate: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "ds02.f5.c082s1.root590-typed-producer-snapshot.fresh116.v1",
        "candidate_id": f"C082S1_MOTION_{tag}", "case_id": CASE, "condition_id": native_request(tag)["condition_id"],
        "attempt_id": producer["typed_attempt_id"], "producer_request": producer["typed_request"], "producer_request_sha256": producer["typed_request_sha256"],
        "producer_request_status": producer["typed_request_status"], "receipt": producer["typed_receipt"], "receipt_sha256": producer["typed_receipt_sha256"], "status": producer["typed_status"], "output_root": producer["typed_output_root"],
        "conversion_report": producer["conversion_report"], "conversion_report_sha256": producer["conversion_report_sha256"], "trajectory_h5": producer["trajectory_h5"], "trajectory_h5_sha256": producer["trajectory_h5_sha256"], "h5_producer_attestation": producer.get("h5_producer_attestation"),
        "expected_frames": 801, "expected_particles": 194427, "expected_dimension": 3, "expected_fluid_particles": 31658,
        "root574_gate": gate, "typed_completed0_required_before_xmf": True, "source_agent_did_not_read_or_hash_science_payload": True,
    }


def xmf_bind(tag: str, gate: dict[str, Any], producer: dict[str, Any], path: Path) -> dict[str, Any]:
    old = xmf_binding(tag)
    value = copy.deepcopy(old)
    typed_receipt = producer["typed_receipt"] or "<root-bind:root590_typed_receipt>"
    typed_report = producer["conversion_report"] or "<root-bind:root590_conversion_report>"
    value.update({"schema": "ds02.f5.c082s1.legacy-aware-xmf-binding.fresh116.v1", "binding_path": str(path), "root574_gate": gate, "native_actual_receipt": producer["native_receipt"], "native_actual_receipt_sha256": producer["native_receipt_sha256"], "typed_attempt_id": producer["typed_attempt_id"], "typed_receipt": typed_receipt, "typed_receipt_sha256": producer["typed_receipt_sha256"], "conversion_report": typed_report, "conversion_report_sha256": producer["conversion_report_sha256"], "trajectory_h5": producer["trajectory_h5"] or "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": producer["trajectory_h5_sha256"], "h5_producer_attestation": producer.get("h5_producer_attestation"), "full801_authorized": False, "xmf_actual": None, "future_output_hashes": {"xmf_manifest_sha256": None, "xmf_receipt_sha256": None, "xmf_sha256": None, "xdmf_sha256": None}})
    return value


def bed_bind(tag: str, gate: dict[str, Any], producer: dict[str, Any], path: Path) -> dict[str, Any]:
    value = copy.deepcopy(bed_binding(tag))
    value.update({"schema": "ds02.f5.c082s1.full-event-bed-audit-binding.fresh116.v1", "binding_path": str(path), "root574_gate": gate, "native_actual_receipt": producer["native_receipt"], "native_actual_receipt_sha256": producer["native_receipt_sha256"], "full_native_attempt_id": native_attempt(tag), "full_typed_attempt_id": producer["typed_attempt_id"], "full_typed_receipt": producer["typed_receipt"] or "<root-bind:root590_typed_receipt>", "full_typed_receipt_sha256": producer["typed_receipt_sha256"], "full_typed_conversion_report": producer["conversion_report"] or "<root-bind:root590_conversion_report>", "full_typed_conversion_report_sha256": producer["conversion_report_sha256"], "trajectory_h5": producer["trajectory_h5"] or "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": producer["trajectory_h5_sha256"], "h5_producer_attestation": producer.get("h5_producer_attestation"), "full_xmf_attempt_id": downstream_attempt(tag, "xmf"), "xmf_manifest": "<root-bind:full_xmf_manifest>", "xmf_manifest_sha256": None, "full801_authorized": False, "repair_success": "unknown_until_actual_root590_typed_xmf_full801_bed_and_root_review", "future_output_hashes": {"bed_audit_report_sha256": None, "typed_h5_sha256": None, "typed_receipt_sha256": None, "xmf_manifest_sha256": None}})
    return value


def render_bind(tag: str, gate: dict[str, Any], bed_path: Path) -> dict[str, Any]:
    value = copy.deepcopy(source_json(f"bindings/{tag}-full801-render-binding.json"))
    value.update({"schema": "ds02.f5.c082s1.root023-full801-render-binding.fresh116.v1", "root574_gate": gate, "full801_authorized": False, "bed_binding": str(bed_path), "bed_binding_sha256": None, "future_output_hashes": {"render_report_sha256": None, "frame_hashes": None}, "camera_bounds": None, "domain_bounds": None, "camera_bounds_policy": "auto_scan_all_actual_valid_native_points"})
    return value


def common_request_fields(tag: str, gate: dict[str, Any], producer: dict[str, Any], kind: str) -> dict[str, Any]:
    physical_value = physical_binding(tag)
    request_name = {"xmf": f"{tag}-full801-xmf-request.json", "bed_audit": f"{tag}-full801-bed-audit-request.json", "render": f"{tag}-full801-render-root023-request.json"}[kind]
    runtime = source_json(f"requests/{request_name}")
    return {"schema": "ds02.runner-request.v2", "candidate_id": f"C082S1_MOTION_{tag}", "case_id": CASE, "condition_id": native_request(tag)["condition_id"], "family_id": "F5", "kind": "cpu", "cpu_task_kind": "audit", "cpu_threads": 2, "launch_owner": "root", "cwd": str(INTEGRATION / "lagrangian-fluid-lab"), "worktree_root": str(PKG.parents[6]), "disabled": True, "execution_allowed": False, "launch": False, "launch_allowed": False, "solver_allowed": False, "conversion_allowed": False, "arrays_allowed": False, "array_edit_allowed": False, "source_only": True, "shared_registry_write_allowed": False, "physical_case_id": physical_value["physical_case_id"], "physical_condition_sha256": physical_value["physical_condition_sha256"], "source_plan_physical_condition_sha256": physical_value["source_plan_physical_condition_sha256"], "native_bed_marker_mk": 50, "source_bed_marker_mkbound": 40, "expected_frames": 801, "expected_particles": 194427, "expected_particle_axis": 194427, "expected_dimension": 3, "expected_fixed_particles": 158559, "expected_floating_particles": 0, "expected_fluid_particles": 31658, "expected_moving_particles": 4210, "root574_gate": gate, "full801_authorized": False, "full16_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0, "no_new_case_credit": True, "root_review_required": True, "production_approval": "none", "source_agent_did_not_read_science_payloads": True, "status": f"disabled_until_root590_actual_{kind}_and_root_review", "future_output_hashes": {"typed_receipt_sha256": None, "conversion_report_sha256": None, "trajectory_h5_sha256": None, "xmf_manifest_sha256": None, "bed_audit_report_sha256": None, "render_report_sha256": None}, "resource_window": runtime.get("resource_window"), "strict_dispatch_source": runtime.get("strict_dispatch_source"), "root_inventory_policy_source": runtime.get("root_inventory_policy_source"), "root_inventory_policy_source_sha256": runtime.get("root_inventory_policy_source_sha256"), "root_inventory_profile": runtime.get("root_inventory_profile"), "estimated_peak_gpu_mib": runtime.get("estimated_peak_gpu_mib", 0), "estimated_storage_bytes": runtime.get("estimated_storage_bytes"), "max_wall_seconds": runtime.get("max_wall_seconds"), "shared_state_modified": False}


def write_downstream(tag: str, gate: dict[str, Any], producer: dict[str, Any]) -> dict[str, Any]:
    native_path = PKG / "bindings" / f"{tag}-full801-native-binding.json"
    phys_path = PKG / "bindings" / f"{tag}-full801-physical-binding.json"
    xmf_path = PKG / "bindings" / f"{tag}-full801-xmf-binding.json"
    bed_path = PKG / "bindings" / f"{tag}-full801-bed-audit-binding.json"
    render_path = PKG / "bindings" / f"{tag}-full801-render-binding.json"
    dump(native_path, native_binding(tag, gate, producer)); native_sha = sha_source(native_path)
    dump(phys_path, physical(tag, gate)); phys_sha = sha_source(phys_path)
    dump(PKG / "metadata" / f"{tag}-root590-typed-producer-snapshot.json", typed_snapshot(tag, gate, producer))
    dump(xmf_path, xmf_bind(tag, gate, producer, xmf_path)); xmf_sha = sha_source(xmf_path)
    dump(bed_path, bed_bind(tag, gate, producer, bed_path)); bed_sha = sha_source(bed_path)
    dump(render_path, render_bind(tag, gate, bed_path)); render_sha = sha_source(render_path)
    worker = local(f"workers/bed_audit_{tag}_full801.py")
    xmf_worker = local("workers/export_xmf_legacy_aware.py")
    inputs, input_meta = static_inputs(tag, gate, producer, [worker, xmf_worker])
    def hashes(extra: list[str]) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
        all_inputs = list(inputs)
        for value in extra:
            if value not in all_inputs: all_inputs.append(value)
        native_meta = native_request(tag)
        attested = {native_meta.get("generated_xml"): native_meta.get("generated_xml_sha256"), str(SHORT_APPROVAL): sha_source(SHORT_APPROVAL), producer["typed_request"]: producer["typed_request_sha256"], producer["native_receipt"]: producer["native_receipt_sha256"], **({producer["typed_receipt"]: producer["typed_receipt_sha256"]} if producer.get("typed_receipt") else {}), **({producer["conversion_report"]: producer["conversion_report_sha256"]} if producer.get("conversion_report") else {}), **({producer["trajectory_h5"]: producer["trajectory_h5_sha256"]} if producer.get("trajectory_h5") else {})}
        hash_map, provenance_map = attested_metadata_hashes(all_inputs, attested)
        return all_inputs, hash_map, provenance_map
    # XMF request.
    xmf_req = common_request_fields(tag, gate, producer, "xmf")
    xmf_req.update({"attempt_id": downstream_attempt(tag, "xmf"), "depends_on_attempt": producer["typed_attempt_id"], "depends_on_attempts": [producer["typed_attempt_id"]], "binding": str(xmf_path), "binding_sha256": xmf_sha, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "native_attempt_id": native_attempt(tag), "native_receipt": producer["native_receipt"], "native_receipt_sha256": producer["native_receipt_sha256"], "typed_receipt": producer["typed_receipt"] or "<root-bind:root590_typed_receipt>", "typed_receipt_sha256": producer["typed_receipt_sha256"], "conversion_report": producer["conversion_report"] or "<root-bind:root590_conversion_report>", "conversion_report_sha256": producer["conversion_report_sha256"], "trajectory_h5": producer["trajectory_h5"] or "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": producer["trajectory_h5_sha256"], "derived_view_only": True, "command": [str(INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"), xmf_worker, "--binding", "<root-bind:full_xmf_binding>", "--output-dir", "{attempt_root}/xmf"], "output_contract": {"all_801_frames": True, "all_native_fields_preserved": True, "native_uid_axis": 194427, "dimension": 3, "no_reader_filter_or_particle_clipping": True}})
    trajectory_input = producer["trajectory_h5"] or "<root-bind:full_trajectory_h5>"
    typed_receipt_input = producer["typed_receipt"] or "<root-bind:full_typed_receipt>"
    typed_report_input = producer["conversion_report"] or "<root-bind:full_typed_report>"
    xmf_req["input_files"], xmf_req["input_sha256"], xmf_req["input_sha256_provenance"] = hashes([str(xmf_path), str(phys_path), trajectory_input, typed_receipt_input, typed_report_input])
    xmf_req["input_sha256"][str(xmf_path)] = xmf_sha; xmf_req["input_sha256_provenance"][str(xmf_path)] = "fresh116 XMF binding JSON hash"
    dump(PKG / "requests" / f"{tag}-full801-xmf-request.json", xmf_req)
    # Bed request.
    bed_req = common_request_fields(tag, gate, producer, "bed_audit")
    bed_req.update({"attempt_id": downstream_attempt(tag, "bed-audit"), "depends_on_attempt": downstream_attempt(tag, "xmf"), "depends_on_attempts": [downstream_attempt(tag, "xmf")], "binding": str(bed_path), "binding_sha256": bed_sha, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "native_attempt_id": native_attempt(tag), "typed_attempt_id": producer["typed_attempt_id"], "xmf_attempt_id": downstream_attempt(tag, "xmf"), "native_receipt": producer["native_receipt"], "native_receipt_sha256": producer["native_receipt_sha256"], "trajectory_h5": producer["trajectory_h5"] or "<root-bind:full_trajectory_h5>", "trajectory_h5_sha256": producer["trajectory_h5_sha256"], "xmf_manifest": "<root-bind:full_xmf_manifest>", "xmf_manifest_sha256": None, "bed_x_bounds_m": [-0.2, 4.8], "bed_y_bounds_m": [-0.22, 0.22], "penetration_bins_m": [0.02, 0.04], "time_window_s": [0.0, 16.0], "save_interval_s": 0.02, "diagnostic_only": True, "thresholds_diagnostic_only": True, "repair_success": "unknown_until_actual_full801_bed_report_and_root_visual_review", "command": [str(INTEGRATION / "lagrangian-fluid-lab/.venv/bin/python"), worker, "--binding", str(bed_path), "--output", "{attempt_root}/audit-output"], "output_contract": {"scan_all_801_frames": True, "full_initial_fluid_uid_denominator": True, "one_dp_two_dp_counts_fractions_max_depth": True, "missing_uid_nonfinite_and_outside_counts": True, "short_window_not_reused_as_full_pass": True}})
    bed_req["input_files"], bed_req["input_sha256"], bed_req["input_sha256_provenance"] = hashes([str(bed_path), str(phys_path), str(xmf_path), "<root-bind:full_xmf_manifest>", trajectory_input])
    bed_req["input_sha256"][str(bed_path)] = bed_sha; bed_req["input_sha256_provenance"][str(bed_path)] = "fresh116 bed binding JSON hash"
    bed_req["input_sha256"][str(xmf_path)] = xmf_sha; bed_req["input_sha256_provenance"][str(xmf_path)] = "fresh116 XMF binding JSON hash"
    dump(PKG / "requests" / f"{tag}-full801-bed-audit-request.json", bed_req)
    # Root023 render request.
    render_req = common_request_fields(tag, gate, producer, "render")
    render_req.update({"attempt_id": downstream_attempt(tag, "render"), "depends_on_attempt": downstream_attempt(tag, "xmf"), "depends_on_attempts": [downstream_attempt(tag, "xmf")], "binding": str(render_path), "binding_sha256": render_sha, "physical_binding_path": str(phys_path), "physical_binding_sha256": phys_sha, "xmf_manifest": "<root-bind:full_xmf_manifest>", "xmf_manifest_sha256": None, "camera_bounds": None, "domain_bounds": None, "camera_bounds_policy": "auto_scan_all_actual_valid_native_points", "renderer_sha256": "5e78f7b92ad7c6f1d15902e3ccacc9099affb04b1b992a42f540eb88241bde66", "derived_view_only": True, "command": ["/home/jade/ParaView-6.1.1-MPI-Linux-Python3.12-x86_64/bin/pvpython", "--force-offscreen-rendering", str(INTEGRATION / "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_native_renderer_proxy_lifetime_diagnostic_023/render.py"), "--manifest", "<root-bind:full_xmf_manifest>", "--output-dir", "{attempt_root}/render"], "output_contract": {"all_801_frames": True, "native_fields_preserved": True, "auto_scan_valid_native_bounds": True, "no_camera_crop_as_scientific_filter": True}})
    render_req["input_files"], render_req["input_sha256"], render_req["input_sha256_provenance"] = hashes([str(render_path), str(xmf_path), str(bed_path), "<root-bind:full_xmf_manifest>"])
    render_req["input_sha256"][str(render_path)] = render_sha; render_req["input_sha256_provenance"][str(render_path)] = "fresh116 render binding JSON hash"
    dump(PKG / "requests" / f"{tag}-full801-render-root023-request.json", render_req)
    return {"tag": tag, "typed": producer, "native_attempt": native_attempt(tag), "xmf_attempt": downstream_attempt(tag, "xmf"), "bed_attempt": downstream_attempt(tag, "bed-audit"), "render_attempt": downstream_attempt(tag, "render"), "future_downstream_hashes": None}


def write_manifest() -> None:
    files: dict[str, str] = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name in {"manifest.json", "fresh116-validator-report.json"}:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES:
            raise ValueError(f"science payload in fresh116: {path}")
        files[str(path.relative_to(PKG))] = sha_source(path)
    dump(PKG / "manifest.json", {"schema": "ds02.f5.c082s1.fresh116-source-manifest.v1", "status": "root588_native_approval_root590_typed_downstream_disabled", "files": files, "validator_report_excluded_from_manifest": True, "fresh115_modified": False, "new_six_full24s1201_gate": "WAIT", "full801_xmf_bed_render_authorized": False, "science_payloads_read_or_hashed_by_source_builder": False, "jobs_started": False, "shared_state_modified": False, "future_receipts_and_hashes_null": True})


def main() -> int:
    if not FRESH115.is_dir() or not SHORT_APPROVAL.is_file():
        raise FileNotFoundError("fresh115 or Root574 approval metadata is missing")
    gate = root_gate()
    copy_source_inputs()
    provenance: dict[str, Any] = {"schema": "ds02.f5.c082s1.fresh116-root590-provenance.v1", "status": "root588_native_approved_root590_typed_snapshot_downstream_disabled", "root574_gate": gate, "root574_review_sidecar": {"path": str(NATIVE_HANDOFF / "actual-root-currenttwo-full801-preflight-review.json"), "sha256": sha_source(NATIVE_HANDOFF / "actual-root-currenttwo-full801-preflight-review.json")}, "root590_review": {"path": str(TYPED_HANDOFF / "actual-root-two-full801typed-enable-review.json"), "sha256": sha_source(TYPED_HANDOFF / "actual-root-two-full801typed-enable-review.json")}, "counts": COUNTS, "native_axis": 194427, "fluid_uid_denominator": 31658, "native_bed_mk": 50, "source_mkbound": 40, "exact_dp_lattice_negative": {"max_residual_cells": 5.000000015797923e-06, "threshold_cells": 1e-06, "accepted": False}, "new_six_full24s1201_gate": gate["new_six_full24s1201_gate"], "science_payloads_read_or_hashed_by_source_builder": False}
    records = []
    for tag in TAGS:
        producer = producer_paths(tag)
        phys_path = PKG / "bindings" / f"{tag}-full801-physical-binding.json"
        # The downstream writer creates the physical binding first.
        result = write_downstream(tag, gate, producer)
        dump(PKG / "metadata" / f"{tag}-root590-native-and-typed-provenance.json", {"schema": "ds02.f5.c082s1.root590-native-typed-provenance.fresh116.v1", "tag": tag, "native": {"attempt_id": producer["native_attempt_id"], "receipt": producer["native_receipt"], "receipt_sha256": producer["native_receipt_sha256"], "status": "completed/0"}, "typed": producer, "root574_gate": gate, "typed_downstream_disabled_until_root_review": True, "producer_h5_attestation_copied_without_open_or_rehash": True, "future_downstream_receipts_and_hashes_null": True, "science_payloads_read_or_hashed_by_source_builder": False})
        provenance.setdefault("candidates", []).append(result)
    dump(PKG / "metadata/fresh116-root590-provenance.json", provenance)
    dump(PKG / "metadata/root574-gate.json", gate)
    plan = {"schema": "ds02.f5.c082s1.fresh116-source-plan.v1", "status": "root588_native_approval_root590_typed_to_xmf_bed_render_disabled", "candidates": list(TAGS), "actual_native575_completed0": True, "root574_short_window_native_approval": True, "root590_typed_snapshot_bound_per_case": True, "typed_h5_read_or_hashed_by_source_builder": False, "full801_xmf_bed_render_authorized": False, "new_six_full24s1201_gate": "WAIT", "exact_dp_lattice_negative_preserved": True, "no_qn_or_case_credit": True, "future_receipts_and_hashes_null": True}
    dump(PKG / "metadata/fresh116-source-plan.json", plan)
    (PKG / "README.md").write_text("# F5 fresh116: Root590 typed downstream source pack\n\nRoot588/574 metadata now records the actual short-window native approval for A080/A120. It approves the current full16 s/801 native qualification scope only; it does not approve complete-event bed/render acceptance. Root575 native receipts are completed/0. Root590 typed producer snapshots are bound per case, including the actual completed receipt/conversion-report metadata. The conversion reports publish the H5 path and digest; fresh116 copies that producer attestation without opening or rehashing H5.\n\nEach candidate has disabled Root590 typed-to-full-N3 XMF, 801-frame Mk50 bed audit, and Root023 render requests. The actual typed H5/report is an input attestation, while XMF, full bed audit, and render outputs remain future nulls until Root enables and reviews them. H5/BI4/CSV/DAT/VTK/scientific arrays are never read or hashed by this source package. The exact 5e-6 versus 1e-6 lattice precision negative remains preserved.\n\nThe six fresh110 24 s/1201 conditions remain WAIT and cannot be authorized by the short-window preview or the native approval.\n", encoding="utf-8")
    write_manifest()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
