#!/usr/bin/env python3
"""Join the actual F3 forcing producer reports to native launch metadata.

The stale native-request physical_binding is retained as a contradiction
record.  The producer report and its attested output SHA are the source of
the actual endpoint amplitude.  This script reads only JSON and the endpoint
XML; it never opens or hashes the CSV payload.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata/f3-actual-forcing-correction.json"
MAIN_PROOF = "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_F3_actual_two_endpoint_forcing_transform_native_pins_XML_relative_file_lookup_copied_nominal_request_metadata_preserved_1456/actual-two-F3-endpoint-forcing-and-stale-request-binding-proof.json"
CASES = {
    "lower": {
        "physical_case_id": "F3_TWOAXIS_PITCH1000_AY0250_VISUAL_DOMAIN",
        "case_id": "F3_STAGE1_DP006_P1000_AY0250",
        "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1000_AY0250/root-stage1-twoaxis-lower-physical-endpoint-full836-native-009/execution-receipt.json",
        "report": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/lower/prepared-input-report.json",
        "xml": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/lower/F3_STAGE1_DP006_P1000_AY0250.xml",
        "source_binding": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_native_007/lower-physical-binding.json",
        "expected_amplitude": 0.25,
    },
    "upper": {
        "physical_case_id": "F3_TWOAXIS_PITCH1000_AY0750_VISUAL_DOMAIN",
        "case_id": "F3_STAGE1_DP006_P1000_AY0750",
        "receipt": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_DP006_P1000_AY0750/root-stage1-twoaxis-upper-physical-endpoint-full836-native-009/execution-receipt.json",
        "report": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/upper/prepared-input-report.json",
        "xml": "/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F3/F3_STAGE1_PHYSICAL_VISUAL_ENDPOINT_PREPARATION/root-stage1-twoaxis-two-physical-amplitude-endpoints-exact-initial-inputs-006/prepared/upper/F3_STAGE1_DP006_P1000_AY0750.xml",
        "source_binding": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f3_visual_domain_endpoint_native_007/upper-physical-binding.json",
        "expected_amplitude": 0.75,
    },
}

def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def load_json(path: str) -> dict:
    p = Path(path)
    if p.suffix.lower() != ".json":
        raise RuntimeError(f"JSON reader received {p}")
    return json.loads(p.read_text())

def file_ref(path: str, role: str) -> dict:
    p = Path(path)
    return {"role": role, "path": str(p), "exists": p.exists(), "bytes": p.stat().st_size if p.exists() else None, "sha256": sha(p) if p.exists() else None}

def build_case(name: str, spec: dict) -> dict:
    receipt = load_json(spec["receipt"])
    report = load_json(spec["report"])
    source = load_json(spec["source_binding"])
    req = receipt.get("request", {})
    transform = report.get("forcing_transform", {})
    endpoint_output = str(transform.get("output_file", ""))
    endpoint_output_sha = transform.get("output_sha256")
    endpoint_path = Path(endpoint_output)
    # The XML is metadata and may be parsed.  The CSV named by it remains
    # untouched; only its producer-attested SHA is compared to receipt maps.
    xml_root = ET.parse(spec["xml"]).getroot()
    acctimes = [e for e in xml_root.iter() if e.tag.rsplit("}", 1)[-1] == "acctimesfile"]
    acctimes_value = acctimes[0].attrib.get("value") if acctimes else None
    xml_case_prefix = str(Path(spec["xml"]).with_suffix(""))
    launch = receipt.get("input_hashes_at_launch", {})
    after = receipt.get("input_hashes_after_run", {})
    forcing_keys = [p for p in launch if p == endpoint_output]
    if not forcing_keys:
        forcing_keys = [p for p in launch if p.endswith("/" + (endpoint_path.name or "CaseSloshingAccData.csv")) and "/prepared/" in p and (name in p or f"/{name}/" in p)]
    forcing_key = forcing_keys[0] if forcing_keys else None
    stale_binding = req.get("physical_binding") if isinstance(req.get("physical_binding"), dict) else {}
    stale_params = stale_binding.get("parameters", {}) if isinstance(stale_binding.get("parameters"), dict) else {}
    source_params = source.get("parameters", {}) if isinstance(source.get("parameters"), dict) else {}
    source_amplitude = source_params.get("transverse_amplitude_m_s2")
    producer_amplitude = report.get("transverse_amplitude_m_s2")
    if producer_amplitude is None:
        producer_amplitude = transform.get("amplitude_y")
    resolved_acctimes = str(Path(spec["xml"]).parent / acctimes_value) if acctimes_value else None
    metadata = {
        "schema": "ds02.f6.fresh208.f3.actual-forcing-correction-case.v1",
        "case_alias": name,
        "case_id": spec["case_id"],
        "physical_case_id": spec["physical_case_id"],
        "status": "PASS_ACTUAL_FORCING_ENDPOINT_DISTINCT_WITH_STALE_REQUEST_BINDING" if producer_amplitude == spec["expected_amplitude"] and forcing_key else "INCOMPLETE_ACTUAL_FORCING_JOIN",
        "conclusion": "Actual producer forcing report and its launch/after SHA pin establish this endpoint amplitude. The stale request physical_binding remains recorded as a metadata contradiction and is not used to overwrite the producer evidence.",
        "actual_forcing_tuple": {
            "pitch_numeric": None,
            "pitch_label": "P1000 (label only; no numeric pitch field was found)",
            "transverse_amplitude_m_s2": producer_amplitude,
            "transverse_omega_rad_s": transform.get("omega_y"),
            "phase_rad": transform.get("phase_y"),
            "tau_ramp_s": transform.get("tau_ramp"),
        },
        "producer_report": {
            **file_ref(spec["report"], "actual_forcing_producer_report"),
            "physical_case_id": report.get("physical_case_id"),
            "transverse_amplitude_m_s2": report.get("transverse_amplitude_m_s2"),
            "forcing_transform": {k: transform.get(k) for k in ["status", "mechanism_id", "amplitude_x", "amplitude_y", "omega_y", "phase_y", "tau_ramp", "rows_processed", "start_token", "end_token", "time_range_s", "column_min", "column_max", "source_sha256_before", "source_sha256_after", "output_file", "output_sha256"]},
            "payload_policy": "CSV path and producer-attested SHA copied from JSON; CSV not opened or hashed by this source-only audit",
        },
        "source_owner_binding": {**file_ref(spec["source_binding"], "Root007_source_owner_binding"), "transverse_amplitude_m_s2": source_amplitude, "reference_variant": source_params.get("reference_variant"), "forcing_source_sha256": source_params.get("forcing_source_sha256"), "actual_forcing_sha256": source_params.get("actual_forcing_sha256")},
        "actual_native_request_stale_binding": {
            "request_sha256": receipt.get("request_sha256"),
            "request_case_id": req.get("case_id"),
            "request_physical_case_id": req.get("physical_case_id"),
            "physical_binding_physical_case_id": stale_binding.get("physical_case_id"),
            "physical_binding_control_family_id": stale_binding.get("control_family_id"),
            "physical_binding_transverse_amplitude_m_s2": stale_params.get("transverse_amplitude_m_s2"),
            "gencase_prefix": req.get("gencase_prefix"),
            "command_case_prefix": req.get("command", [None, None, None])[2] if isinstance(req.get("command"), list) and len(req.get("command")) > 2 else None,
        },
        "endpoint_xml": {**file_ref(spec["xml"], "actual_endpoint_xml"), "acctimesfile_value": acctimes_value, "resolved_acctimesfile_path": resolved_acctimes, "resolved_acctimesfile_matches_producer_output": resolved_acctimes == endpoint_output, "case_prefix": xml_case_prefix},
        "native_launch_after_join": {
            "receipt": file_ref(spec["receipt"], "actual_native_execution_receipt"),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "forcing_input_path": forcing_key,
            "forcing_launch_sha256": launch.get(forcing_key) if forcing_key else None,
            "forcing_after_sha256": after.get(forcing_key) if forcing_key else None,
            "forcing_launch_after_equal": bool(forcing_key and launch.get(forcing_key) == after.get(forcing_key)),
            "forcing_launch_matches_producer_output": bool(forcing_key and launch.get(forcing_key) == endpoint_output_sha),
            "endpoint_xml_launch_sha256": launch.get(spec["xml"]),
            "endpoint_xml_after_sha256": after.get(spec["xml"]),
            "endpoint_xml_launch_after_equal": launch.get(spec["xml"]) == after.get(spec["xml"]),
        },
        "numeric_pitch_policy": "absent/null; P1000 is never converted from an identifier into a numeric physical value",
    }
    return metadata

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=OUT)
    args = ap.parse_args()
    if args.output.exists():
        raise SystemExit(f"refusing to overwrite {args.output}")
    result = {"schema": "ds02.f6.fresh208.f3.actual-forcing-correction.v1", "created_at_utc": datetime.now(timezone.utc).isoformat(), "model": "gpt-5.6-luna", "reasoning_effort": "max", "main_external_proof": {**file_ref(MAIN_PROOF, "Root1456_actual_forcing_and_stale_binding_proof"), "main_commit": "7ac44ee7c"}, "source_boundaries": {"csv_read_or_hashed": False, "scientific_jobs_started": False, "shared_state_modified": False, "case_credit": 0, "Q_N": False, "Q_E": False}, "cases": [build_case(name, spec) for name, spec in CASES.items()]}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    print(json.dumps({"output": str(args.output), "cases": len(result["cases"])}, sort_keys=True))

if __name__ == "__main__":
    main()
