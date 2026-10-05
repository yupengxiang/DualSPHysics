#!/usr/bin/env python3
"""Validate fresh109 metadata and disabled full801 requests only.

No H5/BI4/CSV/VTK/DAT payload is opened or hashed.  Producer-declared H5 and
motion-DAT SHA values are checked as metadata fields; JSON/XML/Python/text
source files are the only bytes hashed by this validator.
"""
from __future__ import annotations
import ast
import hashlib
import json
from pathlib import Path
from typing import Any

PKG = Path(__file__).resolve().parents[1]
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F5")
CASE = "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_C082S1"
COUNTS = {"total": 194427, "fixed": 158559, "moving": 4210, "floating": 0, "fluid": 31658}
ROOT230_POLICY_SHA = "c9103e306f87bb5af871c5de28d9939aa05f0c95c72e1630778f4bcf50e91ab5"
SCIENCE = {".bi4", ".csv", ".h5", ".hdf5", ".vtk", ".vtu", ".npy", ".npz", ".dat"}
SOURCE = {".json", ".py", ".xml", ".md", ".txt", ".log"}
HEX = set("0123456789abcdefABCDEF")
CANDIDATES = ("A080", "A120")


def require(ok: bool, message: str) -> None:
    if not ok:
        raise ValueError(message)


def load(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value, hashlib.sha256(raw).hexdigest()


def sha_source(path: Path) -> str:
    require(path.suffix.lower() in SOURCE, f"source hash forbidden for payload: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def counts_placement(value: dict[str, Any]) -> dict[str, int]:
    return {"total": int(value.get("total_particles", -1)), "fixed": int(value.get("fixed_particles", -1)), "moving": int(value.get("moving_particles", -1)), "floating": int(value.get("floating_particles", -1)), "fluid": int(value.get("fluid_particles", -1)), "dimension": int(value.get("solver_dimension", -1))}


def check_manifest() -> int:
    manifest, _ = load(PKG / "manifest.json")
    require(manifest.get("schema") == "ds02.f5.c082s1.fresh109-source-manifest.v1", "manifest schema")
    require(manifest.get("validator_report_excluded_from_manifest") is True, "manifest report exclusion")
    require("metadata/fresh109-validator-report.json" not in manifest.get("files", {}), "validator report self-reference")
    require(manifest.get("full801_authorized") is False and manifest.get("q_n_granted") is False, "manifest acceptance")
    files = manifest.get("files", {})
    require(isinstance(files, dict), "manifest files")
    for rel, declared in files.items():
        path = PKG / rel
        require(path.is_file(), f"manifest file missing: {path}")
        require(path.suffix.lower() in SOURCE, f"science/unsupported package file: {path}")
        require(isinstance(declared, str) and len(declared) == 64 and sha_source(path) == declared, f"manifest hash mismatch: {rel}")
    return len(files)


def check_closure(request: dict[str, Any], label: str, h5_sha: str | None = None) -> dict[str, int]:
    files = request.get("input_files", [])
    hashes = request.get("input_sha256", {})
    provenance = request.get("input_sha256_provenance", {})
    require(isinstance(files, list) and isinstance(hashes, dict) and isinstance(provenance, dict), f"{label}: closure shape")
    static = payload = placeholders = 0
    for raw in files:
        text = str(raw)
        require(text in hashes and text in provenance, f"{label}: closure missing {text}")
        if text.startswith("<root-bind:"):
            require(hashes[text] is None, f"{label}: placeholder hash not null")
            placeholders += 1
            continue
        path = Path(text)
        require(path.exists(), f"{label}: input path missing {path}")
        suffix = path.suffix.lower()
        if suffix in SCIENCE:
            require(suffix in {".h5", ".dat"}, f"{label}: unsupported science path {path}")
            require(isinstance(hashes[text], str) and len(str(hashes[text])) == 64, f"{label}: producer payload SHA missing")
            require("producer-declared" in str(provenance[text]), f"{label}: producer payload provenance missing")
            if suffix == ".h5" and h5_sha is not None:
                require(hashes[text] == h5_sha, f"{label}: H5 producer SHA mismatch")
            payload += 1
            continue
        if suffix not in SOURCE:
            require(hashes[text] is None, f"{label}: executable must remain un-hashed")
            continue
        require(isinstance(hashes[text], str) and len(hashes[text]) == 64 and sha_source(path) == hashes[text], f"{label}: static hash mismatch {path}")
        static += 1
    return {"static": static, "producer_payload": payload, "placeholders": placeholders}


def check_short_actual(candidate: str) -> dict[str, Any]:
    root = DATA / CASE
    xmf_attempt = f"root-stage1-f5-c082s1-{candidate}-short-native-xmf-107-root506"
    bed_attempt = f"root-stage1-f5-c082s1-{candidate}-short-dynamic-bed-audit-107-root508"
    xmf_receipt_path = root / xmf_attempt / "execution-receipt.json"
    xmf_manifest_path = root / xmf_attempt / "xmf/manifest.json"
    bed_receipt_path = root / bed_attempt / "execution-receipt.json"
    bed_report_path = root / bed_attempt / "audit-output/c082s1-short-event-bed-footprint-audit.json"
    xmf_receipt, xmf_receipt_sha = load(xmf_receipt_path)
    xmf_manifest, xmf_manifest_sha = load(xmf_manifest_path)
    bed_receipt, bed_receipt_sha = load(bed_receipt_path)
    bed_report, bed_report_sha = load(bed_report_path)
    require(xmf_receipt.get("status") == "completed" and int(xmf_receipt.get("returncode", -1)) == 0, f"{candidate}: XMF receipt")
    require(bed_receipt.get("status") == "completed" and int(bed_receipt.get("returncode", -1)) == 0, f"{candidate}: bed receipt")
    require(xmf_manifest.get("frames") == 51 and xmf_manifest.get("particles") == COUNTS["total"] and xmf_manifest.get("full801_authorized") is False, f"{candidate}: XMF metadata")
    frames = bed_report.get("frame_reports", [])
    require(bed_report.get("scan", {}).get("frames_scanned") == 51 and len(frames) == 51, f"{candidate}: bed frame count")
    one = [int(row.get("penetration", {}).get("one_dp", {}).get("count", -1)) for row in frames]
    two = [int(row.get("penetration", {}).get("two_dp", {}).get("count", -1)) for row in frames]
    missing = [int(row.get("uid_tracking", {}).get("missing_initial_uid", {}).get("count", -1)) for row in frames]
    nonfinite = [int(row.get("nonfinite_initial_fluid_uid_count", -1)) for row in frames]
    outside_x = [int(row.get("bed_domain", {}).get("x_outside_exact_profile_domain_count", -1)) for row in frames]
    outside_y = [int(row.get("bed_domain", {}).get("y_outside_actual_bed_footprint_with_x_in_domain_count", -1)) for row in frames]
    require(max(one) == max(two) == max(missing) == max(nonfinite) == max(outside_x) == max(outside_y) == 0, f"{candidate}: short bed diagnostic summary")
    require(bed_report.get("diagnostic_only") is True and bed_report.get("full16_authorized") is False and bed_report.get("q_n_status") == "not_granted", f"{candidate}: bed acceptance boundary")
    binding, binding_sha = load(PKG / "bindings" / f"{candidate}-short-bed-audit-binding.json")
    require(binding.get("schema") == "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1", f"{candidate}: bed schema")
    worker_text = (PKG / "workers" / f"bed_audit_{candidate}.py").read_text(encoding="utf-8")
    require('BINDING_SCHEMA = "ds02.f5.c082s1.short-dynamic-bed-audit-binding.fresh109.v1"' in worker_text, f"{candidate}: worker/binding schema mismatch")
    require(binding.get("xmf_manifest") == str(xmf_manifest_path) and binding.get("xmf_manifest_sha256") == xmf_manifest_sha, f"{candidate}: actual XMF binding")
    actual_bed = binding.get("short_bed_audit", {})
    require(actual_bed.get("report") == str(bed_report_path) and actual_bed.get("report_sha256") == bed_report_sha and actual_bed.get("receipt_sha256") == bed_receipt_sha and actual_bed.get("completed0") is True, f"{candidate}: actual bed binding")
    require(binding.get("short_visual_review", {}).get("status") == "WAIT" and binding.get("full801_authorized") is False, f"{candidate}: visual gate")
    return {"xmf_receipt_sha256": xmf_receipt_sha, "xmf_manifest_sha256": xmf_manifest_sha, "bed_receipt_sha256": bed_receipt_sha, "bed_report_sha256": bed_report_sha, "frames": 51, "max_one_dp": max(one), "max_two_dp": max(two), "max_missing_uid": max(missing), "max_nonfinite_uid": max(nonfinite), "max_outside_x": max(outside_x), "max_outside_y": max(outside_y), "visual_review": "WAIT"}


def check_requests(candidate: str, actual: dict[str, Any]) -> dict[str, Any]:
    xmf_path = PKG / "requests" / f"{candidate}-xmf-request.json"
    bed_path = PKG / "requests" / f"{candidate}-bed-audit-request.json"
    xmf, xmf_sha = load(xmf_path)
    bed, bed_sha = load(bed_path)
    for label, request in (("xmf", xmf), ("bed", bed)):
        require(request.get("schema") == "ds02.runner-request.v2" and request.get("kind") == "cpu" and request.get("cpu_task_kind") == "audit", f"{candidate} {label}: allowlisted CPU kind")
        require(request.get("disabled") is True and request.get("launch") is False and request.get("execution_allowed") is False and request.get("solver_allowed") is False, f"{candidate} {label}: unexpectedly enabled")
        require(request.get("full801_authorized") is False and request.get("q_n_granted") is False and request.get("independent_case_count_increment") == 0, f"{candidate} {label}: acceptance")
        require(all(value is None for value in request.get("future_output_hashes", {}).values()), f"{candidate} {label}: future hash")
        check_closure(request, f"{candidate} {label}", actual.get("h5_sha256"))
    full_path = PKG / "requests" / f"{candidate}-full801-native-request.json"
    full, full_sha = load(full_path)
    require(full.get("schema") == "ds02.runner-request.v2" and full.get("kind") == "qualification" and full.get("cpu_task_kind") == "solver", f"{candidate}: full solver shape")
    require(full.get("disabled") is True and full.get("launch") is False and full.get("launch_allowed") is False and full.get("execution_allowed") is False and full.get("solver_allowed") is False, f"{candidate}: full solver enabled")
    require(full.get("expected_frames") == 801 and full.get("expected_dimension") == 3 and full.get("expected_particles") == COUNTS["total"] and full.get("tmax_s") == 16.0 and full.get("tout_s") == 0.02 and full.get("cpu_threads") == 2, f"{candidate}: full solver shape")
    require(full.get("root_inventory_policy_source_sha256") == ROOT230_POLICY_SHA and full.get("root_live_uuid_inventory") is None and full.get("root_shared_gpu_lease") is None and full.get("root_full_launch_approval") is None, f"{candidate}: Root230 lease/approval gate")
    require(full.get("short_visual_review", {}).get("status") == "WAIT" and full.get("full801_authorized") is False and full.get("q_n_granted") is False, f"{candidate}: full acceptance")
    require(all(value is None for value in full.get("future_output_hashes", {}).values()), f"{candidate}: full future hashes")
    check_closure(full, f"{candidate} full801")
    return {"xmf_request_sha256": xmf_sha, "bed_request_sha256": bed_sha, "full_request_sha256": full_sha}


def check_sources() -> dict[str, str]:
    result = {}
    for path in sorted((PKG / "scripts").glob("*.py")) + sorted((PKG / "workers").glob("*.py")):
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        result[str(path.relative_to(PKG))] = sha_source(path)
    return result


def main() -> int:
    manifest_count = check_manifest()
    sources = check_sources()
    results = {}
    for candidate in CANDIDATES:
        actual = check_short_actual(candidate)
        results[candidate] = {"actual_short": actual, "requests": check_requests(candidate, {"h5_sha256": json.loads((PKG / "bindings" / f"{candidate}-short-xmf-binding.json").read_text())["trajectory_h5_sha256"]})}
    report = {"schema": "ds02.f5.c082s1.fresh109-source-validator-report.v1", "status": "passed_actual_short_bed_bound_full801_disabled_contract", "manifest_source_files": manifest_count, "sources": sources, "candidates": results, "short_visual_review": "WAIT/null", "full801_authorized": False, "q_n_granted": False, "independent_case_count_increment": 0, "exact_dp_lattice_negative_retained": True, "science_payloads_read_or_hashed_by_validator": False, "jobs_started": False, "shared_state_modified": False, "source_only": True}
    (PKG / "metadata" / "fresh109-validator-report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "candidates": list(CANDIDATES), "science_payloads_read_or_hashed_by_validator": False}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
