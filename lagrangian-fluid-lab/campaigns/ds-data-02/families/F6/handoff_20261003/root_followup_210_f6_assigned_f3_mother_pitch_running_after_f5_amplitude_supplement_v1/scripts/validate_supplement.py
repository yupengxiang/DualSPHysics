#!/usr/bin/env python3
"""Standalone read-only validator for fresh210.

The validator consumes only the generated JSON metadata.  It never imports or
executes the builder, opens scientific payloads, or treats an absent running
receipt after-map as a completed run.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "metadata/f3-mother-running-after-f5-amplitude-supplement.json"

def fail(message: str) -> None:
    raise AssertionError(message)

def expect(condition: bool, message: str) -> None:
    if not condition:
        fail(message)

def validate(d: dict[str, Any]) -> None:
    expect(d.get("schema") == "ds02.f6.fresh210.f3-mother-running-after-f5-amplitude-supplement.v1", "schema")
    expect(d.get("source_boundaries", {}).get("scientific_payloads_read_or_hashed") is False, "payload boundary")
    expect(d.get("source_boundaries", {}).get("scientific_jobs_started") is False, "job boundary")
    expect(d.get("source_boundaries", {}).get("shared_state_modified") is False, "shared-state boundary")

    mother = d.get("f3_mother", {})
    expect(mother.get("status") == "PASS_DRIVE_AMPLITUDE_JOIN_PITCH_STILL_ABSENT", "mother status")
    expect(mother.get("actual_numeric_drive_amplitude_G") == 1.0, "mother drive amplitude")
    expect(mother.get("numeric_pitch") is None, "mother numeric pitch must remain absent")
    expect("ABSENT" in mother.get("pitch_status", ""), "mother pitch absence disclosure")
    fj = mother.get("field_join", {})
    for key in ("native_request_drive_amplitude_G", "continuum_binding_drive_amplitude_G", "source_report_physical_binding_drive_amplitude_G", "source_report_forcing_transform_amplitude_x"):
        expect(fj.get(key) == 1.0, f"mother field {key}")
    expect(fj.get("source_report_forcing_transform_amplitude_y") == 0.5, "mother transverse amplitude")
    mstate = mother.get("native_receipt_state", {})
    expect(mstate.get("status") == "completed", "mother native status")
    expect(mstate.get("returncode") == 0, "mother native returncode")
    for join in mstate.get("metadata_input_join", []):
        expect(join.get("launch_matches_metadata") is True, f"mother launch metadata join: {join.get('path')}")
        expect(join.get("after_matches_metadata") is True, f"mother after metadata join: {join.get('path')}")
        expect(join.get("launch_after_equal") is True, f"mother launch/after equality: {join.get('path')}")
    forcing = mstate.get("forcing_payload_join", {})
    expect(forcing.get("payload_opened_or_hashed_by_this_audit") is False, "mother forcing payload boundary")
    expect(forcing.get("producer_attested_sha256"), "mother producer forcing attestation")
    expect(forcing.get("launch_matches_producer_attestation") is True, "mother forcing launch attestation")
    expect(forcing.get("after_matches_producer_attestation") is True, "mother forcing after attestation")

    running = d.get("f3_original_059_running", [])
    expect(len(running) == 4, "four original 059 rows")
    expected = {0.32, 0.39, 0.46, 0.57}
    seen: set[float] = set()
    for row in running:
        expect(row.get("status") == "RUNNING_AFTER_UNKNOWN", f"running status {row.get('case_id')}")
        dec = row.get("request_launch_declaration", {})
        prod = row.get("producer_prepare_report", {})
        join = row.get("native_launch_join", {})
        amp = dec.get("request_transverse_amplitude_m_s2")
        seen.add(amp)
        expect(amp in expected, f"unexpected running amplitude {amp}")
        expect(dec.get("report_sha_launch_matches") is True, f"report launch join {row.get('case_id')}")
        expect(dec.get("request_transverse_amplitude_m_s2") == prod.get("report_transverse_amplitude_m_s2"), f"request/report amplitude {row.get('case_id')}")
        expect(prod.get("report_transverse_amplitude_m_s2") == prod.get("physical_binding_transverse_amplitude_m_s2"), f"report binding amplitude {row.get('case_id')}")
        expect(prod.get("report_transverse_amplitude_m_s2") == prod.get("forcing_transform_amplitude_y"), f"producer transform amplitude {row.get('case_id')}")
        expect(prod.get("forcing_transform_amplitude_x") == 1.0, f"producer drive factor {row.get('case_id')}")
        expect(row.get("amplitude_join", {}).get("request_equals_report") is True, f"amplitude join {row.get('case_id')}")
        expect(row.get("amplitude_join", {}).get("request_motion_matches_producer_attestation") is True, f"motion output join {row.get('case_id')}")
        expect(join.get("after_metadata_available") is False, f"running after map must be absent {row.get('case_id')}")
        expect(join.get("report_after_sha256") is None, f"running report after must remain null {row.get('case_id')}")
        expect(join.get("forcing_after_sha256") is None, f"running forcing after must remain null {row.get('case_id')}")
        expect(join.get("forcing_after_matches_producer_attestation") is None, f"running forcing after claim {row.get('case_id')}")
        expect(row.get("original_receipt", {}).get("path", "").endswith("execution-receipt.json"), f"running receipt path {row.get('case_id')}")
    expect(seen == expected, f"running amplitudes: {seen}")
    role = d.get("f3_original_059_role_closure", {})
    expect(role.get("recovery_and_typed_roles_are_separate") is True, "recovery/typed role separation")
    expect(role.get("original_status_rewritten") is False, "original 059 status rewrite")
    expect(role.get("original_receipt_policy", "").startswith("preserve each native-059"), "original 059 receipt policy")
    for key in ("downstream_recovery_product", "typed_artifact_scope"):
        ref = role.get(key, {})
        expect(ref.get("exists") is True, f"role evidence {key}")
        expect(ref.get("path", "").endswith(".json"), f"role evidence format {key}")

    f5 = d.get("f5_a080_a120_amplitude_audit", {})
    expect(f5.get("basis") == "amplitude_scale_only; time_scale is unknown/absent and does not participate", "F5 basis")
    selected = f5.get("selected", {})
    expect(selected.get("F5_COMPACT_RUNUP_RECOVERY_C082S1_A080", {}).get("amplitude_scale") == 0.8, "A080 amplitude")
    expect(selected.get("F5_COMPACT_RUNUP_RECOVERY_C082S1_A120", {}).get("amplitude_scale") == 1.2, "A120 amplitude")
    expect(selected["F5_COMPACT_RUNUP_RECOVERY_C082S1_A080"].get("time_scale") is None, "A080 time scale must remain unknown")
    expect(selected["F5_COMPACT_RUNUP_RECOVERY_C082S1_A120"].get("time_scale") is None, "A120 time scale must remain unknown")
    expect(f5.get("same_amplitude_other_cases") == {"0.8": [], "1.2": []}, "A080/A120 amplitude uniqueness")
    for amp in ("0.8", "1.2"):
        expect(len(f5.get("amplitude_membership", {}).get(amp, [])) == 1, f"F5 amplitude membership {amp}")

    # Meaningful negative contracts: these mutations are in-memory only.
    bad = copy.deepcopy(d)
    bad["f3_mother"]["field_join"]["source_report_forcing_transform_amplitude_x"] = 0.5
    try:
        validate_without_negative_contracts(bad)
    except AssertionError:
        pass
    else:
        fail("negative mother drive-factor mutation was accepted")
    bad = copy.deepcopy(d)
    bad["f3_original_059_running"][0]["status"] = "COMPLETED"
    try:
        validate_without_negative_contracts(bad)
    except AssertionError:
        pass
    else:
        fail("negative running-to-completed mutation was accepted")
    bad = copy.deepcopy(d)
    bad["f5_a080_a120_amplitude_audit"]["same_amplitude_other_cases"]["0.8"] = ["FAKE_DUPLICATE"]
    try:
        validate_without_negative_contracts(bad)
    except AssertionError:
        pass
    else:
        fail("negative F5 duplicate mutation was accepted")

def validate_without_negative_contracts(d: dict[str, Any]) -> None:
    """Core checks used by negative tests, avoiding recursive negative tests."""
    mother = d["f3_mother"]
    expect(mother["field_join"]["source_report_forcing_transform_amplitude_x"] == 1.0, "drive factor")
    for row in d["f3_original_059_running"]:
        expect(row["status"] == "RUNNING_AFTER_UNKNOWN", "running state")
    expect(d["f5_a080_a120_amplitude_audit"]["same_amplitude_other_cases"] == {"0.8": [], "1.2": []}, "F5 duplicates")

def main() -> None:
    data = json.loads(INPUT.read_text())
    validate(data)
    print(json.dumps({"schema": data["schema"], "status": "PASS", "negative_contracts": ["drive-factor mismatch", "running receipt promoted to completed", "F5 amplitude duplicate"]}, sort_keys=True))

if __name__ == "__main__":
    main()
