#!/usr/bin/env python3
"""Build the fresh111 semantic gate sidecar without changing fresh110.

This package records that Root511's short 0..1 s/51-state visual review can
only participate in the existing A080/A120 full16/801 decision.  It cannot
authorize fresh110's new 24 s/1201 conditions.  Current A080/A120 full-window
solver, typed/XMF/render, and Root visual receipts are deliberately null.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
FRESH110 = PKG.parent / "root_followup_110_stage1_f5_c082s1_six_forcing_conditions_disabled_v1"
FRESH110_COMMIT = "57ccfc730bdaf2eae462591ff9f3b737e5272dd3"
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
TAGS = ("M080_T090", "M080_T110", "M100_T090", "M100_T110", "M120_T090", "M120_T110")
SOURCE_SUFFIXES = {".json", ".py", ".md", ".txt", ".xml", ".log"}
SCIENCE_SUFFIXES = {".dat", ".bi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".npy", ".npz"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def build_sidecar() -> dict[str, Any]:
    manifest = FRESH110 / "manifest.json"
    plan = load(FRESH110 / "metadata/fresh110-source-plan.json")
    validation = load(FRESH110 / "metadata/fresh110-validator-report.json")
    if plan.get("candidate_count") != 6 or validation.get("status") != "passed_six_unique_amplitude_time_disabled_contract":
        raise ValueError("fresh110 source evidence is not the expected validated package")
    if plan.get("full_event_window", {}).get("frames") != 1201:
        raise ValueError("fresh110 full event window changed")
    full_requests = []
    for tag in TAGS:
        request_path = FRESH110 / "requests" / f"{tag}-full-native-qualification-request.json"
        request = load(request_path)
        if request.get("disabled") is not True or request.get("full_native_authorized") is not False or request.get("full801_authorized") is not False:
            raise ValueError(f"fresh110 full request gate changed: {tag}")
        full_requests.append({
            "tag": tag,
            "request": str(request_path),
            "request_sha256": sha(request_path),
            "tmax_s": request.get("tmax_s"),
            "expected_frames": request.get("expected_frames"),
            "disabled": request.get("disabled"),
            "full_native_authorized": request.get("full_native_authorized"),
            "full801_authorized": request.get("full801_authorized"),
        })
    upstream = {}
    for candidate in ("A080", "A120"):
        upstream[candidate] = {
            "case_id": f"C082S1_MOTION_{candidate}",
            "required_full_window": {"tmax_s": 16.0, "tout_s": 0.02, "frames": 801},
            "short_root511_role": "short 0..1 s/51-state visual evidence only; cannot satisfy this full-window gate",
            "full801_native": {"status": "WAIT/null", "attempt_id": None, "receipt": None, "receipt_sha256": None, "completed0": None},
            "full801_typed": {"status": "WAIT/null", "attempt_id": None, "receipt": None, "receipt_sha256": None, "h5_sha256": None, "completed0": None},
            "full801_xmf": {"status": "WAIT/null", "attempt_id": None, "receipt": None, "receipt_sha256": None, "manifest": None, "manifest_sha256": None, "completed0": None},
            "full801_render": {"status": "WAIT/null", "attempt_id": None, "receipt": None, "receipt_sha256": None, "render_manifest_sha256": None, "completed0": None},
            "root_visual_decision": {"status": "WAIT/null", "path": None, "receipt_sha256": None, "decision": None},
            "all_future_hashes_null": True,
        }
    return {
        "schema": "ds02.f5.c082s1.fresh111-full1201-gate-sidecar.v1",
        "status": "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass",
        "case_id": CASE,
        "fresh110_package": str(FRESH110),
        "fresh110_commit": FRESH110_COMMIT,
        "integration_head_at_sidecar_review": "f0d698cd",
        "fresh110_manifest_sha256": sha(manifest),
        "fresh110_plan_sha256": sha(FRESH110 / "metadata/fresh110-source-plan.json"),
        "fresh110_validator_report_sha256": sha(FRESH110 / "metadata/fresh110-validator-report.json"),
        "fresh110_candidate_count": 6,
        "fresh110_full_window": {"tmax_s": 24.0, "tout_s": 0.02, "frames": 1201},
        "short_window_semantics": {
            "root511": "short 0..1 s/51-state visual review for current A080/A120 only",
            "can_authorize_existing_A080_A120_full801": True,
            "can_authorize_fresh110_full1201": False,
            "short_receipt": None,
            "short_render_receipt": None,
            "status": "WAIT/null",
        },
        "existing_full801_gate": {
            "purpose": "must close before any fresh110 full24/1201 native enablement",
            "required_candidates": upstream,
            "rule": "Both A080 and A120 require their own actual completed/0 full16/801 native receipt, typed receipt/H5 metadata, XMF manifest/receipt, full-window render receipt, and explicit Root visual pass. Any WAIT/null blocks all fresh110 full1201 requests.",
            "current_status": "WAIT/null",
            "full801_visual_pass": False,
            "all_future_hashes_null": True,
        },
        "fresh110_intermediate_preparation": {
            "motion_transform_gencase_initial_qa_short_stages_may_be_prepared": True,
            "preparation_is_full1201_authorization": False,
            "full1201_enablement": "blocked",
            "full1201_authorization_receipt": None,
            "full1201_authorization_sha256": None,
        },
        "historical_boundaries": {
            "exact_dp_lattice_negative_retained": True,
            "historical_A_B_penetration_failures_retained": True,
            "fresh110_counts_remain_producer_bound": True,
            "fresh110_bytes_unchanged": True,
        },
        "source_only": True,
        "science_payloads_read_or_hashed_by_source_agent": False,
        "jobs_started": False,
        "shared_state_modified": False,
    }


def write_readme(sidecar: dict[str, Any]) -> None:
    (PKG / "README.md").write_text(
        "# F5 fresh111: full1201 gate semantics\n\n"
        "This independent sidecar leaves fresh110 unchanged. Root511 short 0..1 s/51-state rendering is evidence for the existing A080/A120 short-window review and can only participate in deciding whether those existing two full16/801 runs may be considered. It does not authorize fresh110's six new 24 s/1201 conditions.\n\n"
        "Before any fresh110 full native request is enabled, both A080 and A120 must have their own actual completed/0 full16/801 solver receipt, typed conversion receipt/H5 metadata, XMF manifest/receipt, full-window render receipt, and explicit Root visual pass. These fields are currently WAIT/null. Preparing fresh110 motion, GenCase, initial QA, or short qualification stages does not satisfy this full-window gate.\n\n"
        "The sidecar review records integration HEAD f0d698cd as provenance; it does not imply that any future receipt exists.\n\n"
        "The sidecar reads only fresh110 JSON/source metadata. It does not read or hash DAT, BI4, H5, CSV, VTK, or solver payloads, launch a task, modify fresh110, or modify shared state.\n",
        encoding="utf-8",
    )


def write_manifest() -> None:
    report = PKG / "metadata/fresh111-validator-report.json"
    files = {}
    for path in sorted(PKG.rglob("*")):
        if not path.is_file() or path.name == "manifest.json" or path == report:
            continue
        if path.suffix.lower() in SCIENCE_SUFFIXES or path.suffix.lower() not in SOURCE_SUFFIXES:
            raise ValueError(f"unsupported sidecar file: {path}")
        files[str(path.relative_to(PKG))] = sha(path)
    dump(PKG / "manifest.json", {
        "schema": "ds02.f5.c082s1.fresh111-source-manifest.v1",
        "status": "fresh110_full1201_blocked_on_existing_A080_A120_full801_visual_pass",
        "files": files,
        "validator_report_excluded_from_manifest": True,
        "fresh110_modified": False,
        "full1201_authorized": False,
        "science_payloads_read_or_hashed_by_source_builder": False,
        "jobs_started": False,
        "shared_state_modified": False,
    })


def main() -> int:
    sidecar = build_sidecar()
    dump(PKG / "metadata/fresh111-full1201-gate-sidecar.json", sidecar)
    write_readme(sidecar)
    write_manifest()
    print(json.dumps({"status": sidecar["status"], "full1201_authorized": False, "fresh110_modified": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
