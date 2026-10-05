#!/usr/bin/env python3
"""Validate fresh111's full-window gate semantics using metadata only.

The validator deliberately treats the current A080/A120 full-window evidence
as WAIT/null.  It checks that Root511's short review cannot authorize the six
fresh110 24 s/1201 requests and that no science payload is part of this
sidecar.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
FRESH110 = PKG.parent / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def validate_static_manifest() -> dict[str, Any]:
    manifest = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh111-source-manifest.v1", "manifest schema")
    require(manifest.get("status") == "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass", "manifest status")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "validator report exclusion")
    require(manifest.get("fresh110_modified") is False, "fresh110 modification claim")
    require(manifest.get("full1201_authorized") is False, "full1201 authorization")
    require(manifest.get("science_payloads_read_or_hashed_by_source_builder") is False, "science provenance")
    require(manifest.get("jobs_started") is False and manifest.get("shared_state_modified") is False, "side effects")
    files = manifest.get("files")
    require(isinstance(files, dict) and files, "manifest files")
    report_rel = "metadata/fresh111-validator-report.json"
    require(report_rel not in files, "validator report must remain outside fixed manifest")
    for rel, expected_sha in files.items():
        path = PKG / rel
        require(path.is_file(), f"missing manifest file: {rel}")
        require(path.suffix.lower() in SOURCE_SUFFIXES, f"non-source manifest file: {rel}")
        require(path.suffix.lower() not in SCIENCE_SUFFIXES, f"science file in sidecar: {rel}")
        require(sha(path) == expected_sha, f"manifest hash mismatch: {rel}")
    return manifest


def validate_scripts() -> None:
    for path in sorted((PKG / "scripts").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def validate_fresh110() -> dict[str, Any]:
    manifest = load(FRESH110 / "manifest.json")
    plan_path = FRESH110 / "metadata/fresh110-source-plan.json"
    report_path = FRESH110 / "metadata/fresh110-validator-report.json"
    plan = load(plan_path)
    report = load(report_path)
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh110-source-manifest.v1", "fresh110 manifest schema")
    require(plan.get("candidate_count") == 6, "fresh110 candidate count")
    event_window = plan.get("full_event_window", {})
    require(
        event_window.get("tmax_s") == 24.0
        and event_window.get("tout_s") == 0.02
        and event_window.get("frames") == 1201,
        "fresh110 event window",
    )
    require(report.get("status") == "passed_six_unique_amplitude_time_disabled_contract", "fresh110 validation status")
    require(sha(FRESH110 / "manifest.json") == load(PKG / "metadata/fresh111-full1201-gate-sidecar.json").get("fresh110_manifest_sha256"), "fresh110 manifest hash binding")
    return {"manifest": manifest, "plan": plan, "report": report}


def validate_sidecar(fresh110: dict[str, Any]) -> dict[str, Any]:
    sidecar = load(PKG / "metadata/fresh111-full1201-gate-sidecar.json")
    require(sidecar.get("schema") == "ds02.f5.c082s1.fresh111-full1201-gate-sidecar.v1", "sidecar schema")
    require(sidecar.get("status") == "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass", "sidecar status")
    require(sidecar.get("fresh110_commit") == FRESH110_COMMIT, "sidecar fresh110 commit")
    require(sidecar.get("integration_head_at_sidecar_review") == "f0d698cd", "integration review head")
    require(sidecar.get("fresh110_candidate_count") == 6, "sidecar candidate count")
    require(sidecar.get("fresh110_full_window") == {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201}, "sidecar full window")
    require(sidecar.get("source_only") is True, "sidecar source-only marker")
    require(sidecar.get("science_payloads_read_or_hashed_by_source_agent") is False, "sidecar science marker")
    require(sidecar.get("jobs_started") is False and sidecar.get("shared_state_modified") is False, "sidecar side effects")

    short = sidecar.get("short_window_semantics", {})
    require(short.get("can_authorize_existing_A080_A120_full801") is True, "Root511 existing gate role")
    require(short.get("can_authorize_fresh110_full1201") is False, "Root511 overreach")
    require(short.get("status") == "WAIT/null", "short status")
    require(short.get("short_receipt") is None and short.get("short_render_receipt") is None, "short future receipts")

    gate = sidecar.get("existing_full801_gate", {})
    require(gate.get("current_status") == "WAIT/null", "existing full gate status")
    require(gate.get("full801_visual_pass") is False, "existing full visual pass")
    require(gate.get("all_future_hashes_null") is True, "existing full future hashes")
    required = gate.get("required_candidates", {})
    require(set(required) == {"A080", "A120"}, "upstream candidates")
    for candidate in ("A080", "A120"):
        record = required[candidate]
        require(record.get("required_full_window") == {"tmax_s": 16.0, "tout_s": 0.02, "frames": 801}, f"{candidate} full window")
        for stage in ("full801_native", "full801_typed", "full801_xmf", "full801_render"):
            value = record.get(stage, {})
            require(value.get("status") == "WAIT/null", f"{candidate} {stage} status")
            require(value.get("completed0") is None, f"{candidate} {stage} completed")
        for stage in ("full801_native", "full801_typed", "full801_xmf", "full801_render"):
            value = record[stage]
            for key, item in value.items():
                if key.endswith("sha256") or key in {"attempt_id", "receipt", "manifest", "render_manifest_sha256", "h5_sha256"}:
                    require(item is None, f"{candidate} {stage} future field {key}")
        decision = record.get("root_visual_decision", {})
        require(decision.get("status") == "WAIT/null" and decision.get("decision") is None, f"{candidate} root visual decision")

    prep = sidecar.get("fresh110_intermediate_preparation", {})
    require(prep.get("preparation_is_full1201_authorization") is False, "intermediate authorization")
    require(prep.get("full1201_enablement") == "blocked", "full1201 enablement")
    require(prep.get("full1201_authorization_receipt") is None and prep.get("full1201_authorization_sha256") is None, "authorization future fields")

    for tag in TAGS:
        path = FRESH110 / "requests" / f"{tag}-full-native-qualification-request.json"
        request = load(path)
        require(request.get("disabled") is True, f"{tag} disabled")
        require(request.get("full_native_authorized") is False and request.get("full801_authorized") is False, f"{tag} authorization")
        require(request.get("tmax_s") == 24.0 and request.get("expected_frames") == 1201, f"{tag} window")
        require(request.get("upstream_visual_gate") == "WAIT_existing_A080_A120_Root511_review", f"{tag} upstream gate")
        require(request.get("future_output_sha256") is None, f"{tag} future hash")
    return sidecar


def main() -> int:
    validate_static_manifest()
    validate_scripts()
    fresh110 = validate_fresh110()
    sidecar = validate_sidecar(fresh110)
    report = {
        "schema": "ds02.f5.c082s1.fresh111-validator-report.v1",
        "status": "passed_full1201_gate_semantics_wait_null",
        "fresh110_commit": FRESH110_COMMIT,
        "fresh110_candidate_count": fresh110["plan"]["candidate_count"],
        "fresh110_full_window": fresh110["plan"]["full_event_window"],
        "root511_can_authorize_fresh110_full1201": sidecar["short_window_semantics"]["can_authorize_fresh110_full1201"],
        "existing_A080_A120_full801_status": sidecar["existing_full801_gate"]["current_status"],
        "full1201_authorized": False,
        "future_hashes_null": True,
        "science_payloads_read_or_hashed_by_validator": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }
    (PKG / "metadata/fresh111-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "full1201_authorized": False, "future_hashes_null": True}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
