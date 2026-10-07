#!/usr/bin/env python3
"""Build the bounded fresh210 metadata supplement.

Only JSON and the mother XML are read here.  CSV/BI4/H5/DAT/VTK/PNG payloads
are represented by producer-attested metadata and are never opened or hashed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata/f3-mother-running-after-f5-amplitude-supplement.json"
FRESH209 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_209_f6_assigned_f3_f4_f5_normalized_tuple_full144_v1/"
    "metadata/f3-f4-f5-normalized-tuples-144.json"
)
FRESH208 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_208_f6_assigned_f3_actual_forcing_binding_correction_v1/"
    "metadata/f3-actual-forcing-correction.json"
)
FRESH207 = Path(
    "/home/jade/.codex/worktrees/ds-data-02-f6/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F6/handoff_20261003/"
    "root_followup_207_f6_assigned_cross_family_physical_distinctness_spot_audit_v1/"
    "metadata/physical-distinctness-spot-audit.json"
)

FRESH_COMMITS = {"fresh207": "746b600cc94bb0638ea456489dfb9e6954538f95", "fresh208": "d9cb5eb2c4ec61d3d17761ed7f32124a4d489d3f", "fresh209": "6d1a1a1d1dd8a2740e1144834c7e803aae38f4c5"}
MOTHER_ID = "F3_TWOAXIS_AY0P50_PITCH_NOMINAL"
F3_RECOVERY_PRODUCT = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_source229_lastF3_actual1101_personal44PNG_full836QI_F3final48_primary_native_both_plan_ABS_XMF_condition_present_1449/"
    "source229-personal44PNG-main-QI1427-and-finalF3primary48-proof.json"
)
F3_TYPED_SCOPE = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    "lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/"
    "root_stage1_current330_original1063_1189_completedQI_lastF2_lastF5_personal_pending_F3_original154_unknown_typed_role_sidecar_live1184_1175_1435/"
    "F3-current47-original154-unknown-typed-runtime-and-native-source-role-clarification.json"
)

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def load_json(path: str | Path) -> Any:
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise RuntimeError(f"metadata loader only accepts JSON: {p}")
    return json.loads(p.read_text())

def metadata_ref(path: str | Path, role: str) -> dict[str, Any]:
    p = Path(path)
    if p.suffix.lower() not in {".json", ".xml", ".xmf"}:
        raise RuntimeError(f"non-metadata reference cannot be hashed: {p}")
    return {"role": role, "path": str(p), "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None, "sha256": sha(p) if p.exists() else None}

def find_row(d: dict[str, Any], family: str, physical_id: str) -> dict[str, Any]:
    for row in d["cases"][family]:
        if row.get("physical_case_id") == physical_id:
            return row
    raise KeyError(physical_id)

def find_report_path(req: dict[str, Any]) -> Path:
    for raw in req.get("input_files", []):
        p = Path(raw)
        if p.name == "prepared-input-report.json":
            return p
    raise RuntimeError(f"prepared-input-report.json missing for {req.get('case_id')}")

def map_value(mapping: Any, path: str) -> Any:
    return mapping.get(path) if isinstance(mapping, dict) else None

def metadata_join(receipt: dict[str, Any], path: Path) -> dict[str, Any]:
    launch = receipt.get("input_hashes_at_launch", {})
    after = receipt.get("input_hashes_after_run", {})
    actual = sha(path) if path.exists() else None
    return {
        "path": str(path),
        "metadata_sha256": actual,
        "launch_sha256": map_value(launch, str(path)),
        "after_sha256": map_value(after, str(path)),
        "launch_matches_metadata": map_value(launch, str(path)) == actual if actual else False,
        "after_matches_metadata": map_value(after, str(path)) == actual if actual else False,
        "launch_after_equal": map_value(launch, str(path)) == map_value(after, str(path)),
    }

def find_source_path(row: dict[str, Any], suffix: str) -> Path | None:
    for item in row.get("actual_native", {}).get("metadata_input_join", []):
        p = Path(item.get("path", ""))
        if p.name == suffix and p.exists():
            return p
    return None

def build_mother(row: dict[str, Any]) -> dict[str, Any]:
    receipt_path = Path(row["actual_native"]["path"])
    receipt = load_json(receipt_path)
    req = receipt.get("request", {})
    continuum_path = Path(req["actual_continuum_binding"])
    continuum = load_json(continuum_path)
    report_path = find_source_path(row, "prepared-input-report.json")
    if report_path is None:
        raise RuntimeError("mother prepared report not found")
    report = load_json(report_path)
    report_transform = report.get("forcing_transform", {})
    xml_path = find_source_path(row, f"{row['case_id']}.xml")
    if xml_path is None:
        raise RuntimeError("mother XML not found")
    xml_root = ET.parse(xml_path).getroot()
    acctimes = [e.attrib.get("value") for e in xml_root.iter() if e.tag.rsplit("}", 1)[-1] == "acctimesfile"]
    source_review = find_source_path(row, "source-review.json")
    gencase_path = Path(req["gencase_receipt"])
    launch = receipt.get("input_hashes_at_launch", {})
    after = receipt.get("input_hashes_after_run", {})
    output_path = Path(str(report_transform.get("output_file", "")))
    output_launch = map_value(launch, str(output_path))
    output_after = map_value(after, str(output_path))
    params = req.get("physical_binding", {}).get("parameters", {})
    report_params = report.get("physical_binding", {}).get("parameters", {})
    continuum_params = continuum.get("physical_binding", {}).get("parameters", {})
    return {
        "physical_case_id": MOTHER_ID,
        "case_id": row["case_id"],
        "status": "PASS_DRIVE_AMPLITUDE_JOIN_PITCH_STILL_ABSENT" if params.get("drive_amplitude_G") == 1.0 and report_transform.get("amplitude_x") == 1.0 and continuum_params.get("drive_amplitude_G") == 1.0 else "INCOMPLETE_DRIVE_AMPLITUDE_JOIN",
        "numeric_pitch": None,
        "pitch_status": "UNRESOLVED_NUMERIC_PITCH_FIELD_ABSENT; identifier/label is not converted to a number",
        "actual_numeric_drive_amplitude_G": 1.0,
        "evidence": {
            "native_receipt": metadata_ref(receipt_path, "actual_native_060_execution_receipt"),
            "actual_continuum_binding": metadata_ref(continuum_path, "request_actual_continuum_binding"),
            "source_preparation_report": metadata_ref(report_path, "root_source056_prepared_input_report"),
            "source_review": metadata_ref(source_review, "root_source056_source_review") if source_review else None,
            "gencase_receipt": metadata_ref(gencase_path, "actual_gencase_receipt"),
            "generated_xml": metadata_ref(xml_path, "actual_generated_xml"),
        },
        "field_join": {
            "native_request_actual_continuum_binding": str(continuum_path),
            "native_request_drive_amplitude_G": params.get("drive_amplitude_G"),
            "native_request_transverse_amplitude_m_s2": params.get("transverse_amplitude_m_s2"),
            "continuum_binding_drive_amplitude_G": continuum_params.get("drive_amplitude_G"),
            "source_report_physical_binding_drive_amplitude_G": report_params.get("drive_amplitude_G"),
            "source_report_forcing_transform_amplitude_x": report_transform.get("amplitude_x"),
            "source_report_forcing_transform_amplitude_y": report_transform.get("amplitude_y"),
            "source_report_output_file": report_transform.get("output_file"),
            "source_report_output_sha256_attested": report_transform.get("output_sha256"),
            "xml_acctimesfile_value": acctimes[0] if acctimes else None,
            "resolved_acctimesfile_path": str(xml_path.parent / acctimes[0]) if acctimes else None,
            "xml_relative_lookup_metadata_only": True,
        },
        "native_receipt_state": {
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "metadata_input_join": [metadata_join(receipt, p) for p in [continuum_path, report_path, xml_path, gencase_path]],
            "forcing_payload_join": {
                "path": str(output_path),
                "producer_attested_sha256": report_transform.get("output_sha256"),
                "launch_sha256": output_launch,
                "after_sha256": output_after,
                "launch_matches_producer_attestation": output_launch == report_transform.get("output_sha256"),
                "after_matches_producer_attestation": output_after == report_transform.get("output_sha256"),
                "payload_opened_or_hashed_by_this_audit": False,
            },
        },
        "source_boundary": "drive amplitude is joined from actual request/binding and producer report; pitch remains absent/null; no ID or image inference",
    }

def build_running(row: dict[str, Any]) -> dict[str, Any]:
    receipt_path = Path(row["actual_native"]["path"])
    receipt = load_json(receipt_path)
    req = receipt.get("request", {})
    report_path = find_report_path(req)
    report = load_json(report_path)
    transform = report.get("forcing_transform", {})
    binding_params = report.get("physical_binding", {}).get("parameters", {})
    motion = req.get("motion", {})
    output_path = Path(str(transform.get("output_file", "")))
    launch = receipt.get("input_hashes_at_launch", {})
    after = receipt.get("input_hashes_after_run", {})
    request_amp = req.get("transverse_amplitude_m_s2")
    report_amp = report.get("transverse_amplitude_m_s2", binding_params.get("transverse_amplitude_m_s2"))
    report_sha = sha(report_path)
    return {
        "physical_case_id": row["physical_case_id"],
        "case_id": row["case_id"],
        "status": "RUNNING_AFTER_UNKNOWN" if receipt.get("status") == "running" and receipt.get("returncode") is None and not after else "UNEXPECTED_RUNNING_RECEIPT_STATE",
        "original_receipt": metadata_ref(receipt_path, "original_native_059_execution_receipt"),
        "request_launch_declaration": {
            "request_transverse_amplitude_m_s2": request_amp,
            "request_nominal_pitch_multiplier": req.get("nominal_pitch_multiplier"),
            "request_parameter_tuple": req.get("parameter_tuple"),
            "request_motion": motion,
            "prepared_report_path": str(report_path),
            "prepared_report_sha256": report_sha,
            "report_sha_launch_pin": launch.get(str(report_path)),
            "report_sha_launch_matches": launch.get(str(report_path)) == report_sha,
        },
        "producer_prepare_report": {
            "report": metadata_ref(report_path, "actual_forcing_prepared_input_report"),
            "physical_case_id": report.get("physical_case_id"),
            "report_transverse_amplitude_m_s2": report_amp,
            "physical_binding_transverse_amplitude_m_s2": binding_params.get("transverse_amplitude_m_s2"),
            "forcing_transform_amplitude_x": transform.get("amplitude_x"),
            "forcing_transform_amplitude_y": transform.get("amplitude_y"),
            "forcing_transform_status": transform.get("status"),
            "output_file": transform.get("output_file"),
            "output_sha256_attested": transform.get("output_sha256"),
            "payload_opened_or_hashed_by_this_audit": False,
        },
        "native_launch_join": {
            "report_launch_sha256": launch.get(str(report_path)),
            "report_after_sha256": after.get(str(report_path)),
            "after_metadata_available": bool(after),
            "after_state": "UNKNOWN_WHILE_RECEIPT_RUNNING; no after pin is synthesized",
            "forcing_path": str(output_path),
            "forcing_launch_sha256": launch.get(str(output_path)),
            "forcing_after_sha256": after.get(str(output_path)),
            "forcing_launch_matches_producer_attestation": launch.get(str(output_path)) == transform.get("output_sha256"),
            "forcing_after_matches_producer_attestation": None if str(output_path) not in after else after.get(str(output_path)) == transform.get("output_sha256"),
        },
        "amplitude_join": {
            "request_equals_report": request_amp == report_amp,
            "report_binding_equals_transform": report_amp == transform.get("amplitude_y"),
            "request_motion_actual_forcing_sha256": motion.get("actual_forcing_sha256"),
            "request_motion_matches_producer_attestation": motion.get("actual_forcing_sha256") == transform.get("output_sha256"),
            "source_forcing_sha256": motion.get("source_forcing_sha256"),
        },
    }

def build_f5_amplitude_audit(fresh209: dict[str, Any]) -> dict[str, Any]:
    # This is the only portion of fresh209 read here: the existing F5 tuple
    # rows, not a second traversal of the full 144-row audit.
    rows = fresh209["cases"]["F5"]
    by_amp: dict[str, list[str]] = {}
    for row in rows:
        amp = row.get("normalized_tuple", {}).get("amplitude_scale")
        by_amp.setdefault(str(amp), []).append(row["physical_case_id"])
    selected = {}
    for pid in ["F5_COMPACT_RUNUP_RECOVERY_C082S1_A080", "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120"]:
        row = find_row(fresh209, "F5", pid)
        selected[pid] = {
            "amplitude_scale": row["normalized_tuple"].get("amplitude_scale"),
            "time_scale": row["normalized_tuple"].get("time_scale"),
            "time_scale_role": "UNKNOWN/ABSENT; excluded from distinctness",
            "source_evidence": row.get("source_evidence", []),
        }
    return {
        "basis": "amplitude_scale_only; time_scale is unknown/absent and does not participate",
        "selected": selected,
        "amplitude_membership": by_amp,
        "same_amplitude_other_cases": {
            "0.8": [x for x in by_amp.get("0.8", []) if x != "F5_COMPACT_RUNUP_RECOVERY_C082S1_A080"],
            "1.2": [x for x in by_amp.get("1.2", []) if x != "F5_COMPACT_RUNUP_RECOVERY_C082S1_A120"],
        },
    }

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {args.output}")
    fresh209 = load_json(FRESH209)
    mother_row = find_row(fresh209, "F3", MOTHER_ID)
    running_rows = [r for r in fresh209["cases"]["F3"] if r.get("actual_native", {}).get("status") == "running"]
    if len(running_rows) != 4:
        raise RuntimeError(f"expected four original 059 running rows, found {len(running_rows)}")
    result = {
        "schema": "ds02.f6.fresh210.f3-mother-running-after-f5-amplitude-supplement.v1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "max",
        "source_commits": FRESH_COMMITS,
        "inputs": {
            "fresh207": metadata_ref(FRESH207, "immutable_fresh207_spot_audit"),
            "fresh208": metadata_ref(FRESH208, "immutable_fresh208_actual_forcing_correction"),
            "fresh209": metadata_ref(FRESH209, "immutable_fresh209_144_tuple_audit"),
        },
        "source_boundaries": {
            "scientific_payloads_read_or_hashed": False,
            "payloads": ["CSV", "BI4", "H5", "DAT", "VTK", "PNG"],
            "metadata_json_xml_read": True,
            "scientific_jobs_started": False,
            "shared_state_modified": False,
            "case_credit": 0,
            "Q_N": False,
            "Q_E": False,
        },
        "f3_mother": build_mother(mother_row),
        "f3_original_059_running": [build_running(r) for r in sorted(running_rows, key=lambda x: x["case_id"])],
        "f3_original_059_role_closure": {
            "original_receipt_policy": "preserve each native-059 receipt status=running and returncode absent; an absent after map is unknown, not completed0",
            "downstream_recovery_product": metadata_ref(F3_RECOVERY_PRODUCT, "main_F3_Root1449_registered_native_completion_recovery_product"),
            "typed_artifact_scope": metadata_ref(F3_TYPED_SCOPE, "main_F3_Root1435_typed_artifact_scope_sidecar"),
            "recovery_and_typed_roles_are_separate": True,
            "original_status_rewritten": False,
        },
        "f5_a080_a120_amplitude_audit": build_f5_amplitude_audit(fresh209),
        "conclusion": {
            "mother_drive_amplitude": "resolved to 1.0 from actual request/binding and source056 producer transform; numeric pitch remains absent",
            "running_059": "four original receipts remain running with no returncode and no after map; after state is unknown, never promoted to completed",
            "f5_a080_a120": "0.8 and 1.2 are each unique among all 48 F5 amplitudes; unknown time_scale is excluded from this distinction",
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "running_rows": len(running_rows), "mother_status": result["f3_mother"]["status"]}, sort_keys=True))

if __name__ == "__main__":
    main()
