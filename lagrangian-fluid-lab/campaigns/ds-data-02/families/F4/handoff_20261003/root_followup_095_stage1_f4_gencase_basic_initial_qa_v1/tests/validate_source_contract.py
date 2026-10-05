#!/usr/bin/env python3
"""Static/source-only validator for F4 fresh095."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
from typing import Any

PACKAGE = Path(__file__).resolve().parents[1]
RAW_SUFFIXES = {".bi4", ".h5", ".vtk", ".vtu", ".vtp", ".csv"}
HEX = set("0123456789abcdef")


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected object: {path}")
    return value


def sha(path: Path) -> str:
    if path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"validator refuses scientific payload hash: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def valid_sha(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value.lower()) <= HEX


def main() -> int:
    manifest = load(PACKAGE / "F4_STAGE1_FRESH095_PRE_SOLVER_GENCASE_BASIC_INITIAL_QA_MANIFEST.json")
    plan = load(PACKAGE / "metadata" / "fresh095-gencase-plan.json")
    contract = load(PACKAGE / "metadata" / "fresh095-stage1-contract.json")
    evidence = load(PACKAGE / "metadata" / "fresh095-root44424-evidence.json")
    worker_path = PACKAGE / "workers" / "run_f4_fresh095_gencase_basic_initial_qa.py"
    builder_path = PACKAGE / "build_fresh095.py"
    worker_text = worker_path.read_text(encoding="utf-8")
    builder_text = builder_path.read_text(encoding="utf-8")
    if manifest.get("case_count") != 24 or manifest.get("all_requests_disabled") is not True:
        raise ValueError("manifest case/disabled contract drift")
    if manifest.get("pre_solver") is not True or manifest.get("native_solver_dependency") is not None:
        raise ValueError("manifest is not independent pre-solver")
    if contract.get("execution", {}).get("requires_native_receipt") is not False:
        raise ValueError("contract unexpectedly requires native receipt")
    if contract.get("execution", {}).get("requires_native_frame0") is not False:
        raise ValueError("contract unexpectedly requires native frame0")
    if evidence.get("case_count") != 24 or evidence.get("all_individual_receipts_completed0") is not True:
        raise ValueError("Root44424/Root445 evidence contract drift")
    if evidence.get("aggregate_receipt_promotion") != "none":
        raise ValueError("aggregate receipt was promoted")
    bindings = sorted((PACKAGE / "metadata" / "bindings").glob("*.json"))
    requests = sorted((PACKAGE / "requests").glob("*.json"))
    if len(bindings) != 24 or len(requests) != 24:
        raise ValueError(f"expected 24 bindings/requests, got {len(bindings)}/{len(requests)}")
    case_ids = []
    for path in bindings:
        binding = load(path)
        eid = binding.get("case_id")
        case_ids.append(eid)
        if binding.get("source_only") is not True or binding.get("execution_allowed") is not False:
            raise ValueError(f"{eid}: binding is enabled")
        if binding.get("future_hashes_null") is not True:
            raise ValueError(f"{eid}: future hashes are not null")
        receipt = binding.get("gencase_receipt", {})
        bi4 = binding.get("generated_bi4", {})
        if receipt.get("status") not in {"completed", "completed/0"} or receipt.get("returncode") != 0:
            raise ValueError(f"{eid}: GenCase receipt not completed/0")
        if not valid_sha(receipt.get("sha256")):
            raise ValueError(f"{eid}: missing receipt SHA")
        if not valid_sha(bi4.get("producer_sha256")) or bi4.get("content_rehashed_by_source") is not False:
            raise ValueError(f"{eid}: BI4 producer attestation/source boundary drift")
        if binding.get("initial_velocity_declaration", {}).get("claim") != "generated XML declaration only; no native frame-0 velocity observation":
            raise ValueError(f"{eid}: velocity claim drift")
        if binding.get("mass_policy", {}).get("stage1_gate") is not False:
            raise ValueError(f"{eid}: mass became a gate")
        if binding.get("downstream", {}).get("post_native_frame0_velocity_audit") != "fresh094":
            raise ValueError(f"{eid}: post-native boundary drift")
    if len(set(case_ids)) != 24 or set(case_ids) != {row["case_id"] for row in plan["cases"]}:
        raise ValueError("case identity set mismatch")
    request_case_ids = set()
    for path in requests:
        request = load(path)
        eid = request.get("case_id")
        request_case_ids.add(eid)
        for key in ("disabled", "launch", "launch_allowed", "execution_allowed", "source_only"):
            if request.get(key) is not (True if key == "disabled" or key == "source_only" else False):
                raise ValueError(f"{eid}: request {key} is unsafe")
        if request.get("kind") != "cpu" or request.get("cpu_task_kind") != "audit":
            raise ValueError(f"{eid}: request is not a CPU audit")
        if request.get("native_upstream_request") is not None or request.get("native_solver_dependency") is not None:
            raise ValueError(f"{eid}: native dependency was introduced")
        command = " ".join(str(item) for item in request.get("command", []))
        if any(token in command for token in ("native_attempt_root", "Part_0000", "full1201", "fresh094")):
            raise ValueError(f"{eid}: command has a native/post-native dependency")
        if request.get("expected_outputs", {}).get("native_receipt") is not None:
            raise ValueError(f"{eid}: native receipt output is not null")
        if request.get("expected_outputs", {}).get("native_frame0") is not None:
            raise ValueError(f"{eid}: native frame0 output is not null")
        deferred = request.get("deferred_input_files", [])
        deferred_sha = request.get("deferred_input_sha256", {})
        if len(deferred) != 1 or Path(deferred[0]).suffix.lower() != ".bi4":
            raise ValueError(f"{eid}: deferred input is not exactly GenCase BI4")
        if deferred_sha.get(deferred[0]) is not None:
            raise ValueError(f"{eid}: deferred BI4 hash was fabricated")
        if request.get("deferred_bi4_producer_sha256", {}).get(deferred[0]) is None:
            raise ValueError(f"{eid}: attested BI4 producer SHA missing")
        for raw in request.get("input_files", []):
            if Path(raw).suffix.lower() in RAW_SUFFIXES:
                raise ValueError(f"{eid}: scientific payload in static input files: {raw}")
        for raw_path, expected in request.get("input_sha256", {}).items():
            path_obj = Path(raw_path)
            if path_obj.suffix.lower() in RAW_SUFFIXES:
                raise ValueError(f"{eid}: scientific payload hash in input closure: {raw_path}")
            if not path_obj.is_file() or sha(path_obj) != expected:
                raise ValueError(f"{eid}: input SHA closure drift: {raw_path}")
        if request.get("no_jobs_started_by_source") is not True or request.get("no_shared_registry_write") is not True:
            raise ValueError(f"{eid}: source mutation boundary drift")
        if request.get("root_only") is not True or request.get("launch_owner") != "root":
            raise ValueError(f"{eid}: root ownership drift")
    if request_case_ids != set(case_ids):
        raise ValueError("request identity set mismatch")
    if "sha_static(bi4" in worker_text or 'sha_static(Path(binding["generated_bi4"]' in worker_text:
        raise ValueError("worker statically hashes BI4 through source metadata helper")
    if "read_bytes()" in builder_text and ".bi4" in builder_text:
        raise ValueError("builder appears to read raw payload bytes")
    if "root_followup_094" not in (PACKAGE / "README.md").read_text(encoding="utf-8"):
        raise ValueError("README does not preserve fresh094 downstream boundary")
    result = {
        "schema": "ds02.f4.fresh095.source-contract-validation.v1",
        "status": "pass",
        "case_count": 24,
        "all_disabled": True,
        "independent_pre_solver_gate": True,
        "native_receipt_dependency": False,
        "native_frame0_dependency": False,
        "root44424_individual_gencase_completed0_bound": True,
        "science_payloads_read_or_hashed_by_source_package": False,
        "fresh094_retained_post_native": True,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
