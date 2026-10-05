#!/usr/bin/env python3
"""Static validator for the F2 fresh104 source-only package.

It hashes only JSON/XML/Python/text metadata and trusts producer-recorded
digests for raw scientific inputs.  It never opens a CSV, BI4, DAT, VTK, H5 or
solver output.  The validator is useful before Root registers a CPU/GPU job;
the requests themselves remain disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


LOGICAL_GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STRICT_DISPATCH_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"
STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}


def sha(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
        raise ValueError(f"refusing scientific/non-static path: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_request(path: Path, kind: str, package: Path, seen: set[str]) -> dict[str, Any]:
    request = load(path)
    cid = str(request.get("case_id", ""))
    require(cid and cid not in seen, f"duplicate/missing case in {path}")
    seen.add(cid)
    require(request.get("fresh_id") == "fresh104", f"fresh id drift: {path}")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False, f"enabled request: {path}")
    require(request.get("source_only") is True and request.get("future_hashes_null") is True, f"source/future guard drift: {path}")
    require(request.get("strict_guard_digest") == LOGICAL_GUARD and request.get("strict_dispatch_file_sha256") == STRICT_DISPATCH_SHA, f"strict digest drift: {path}")
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict) and set(files) == set(hashes), f"input closure mismatch: {path}")
    for raw_path, expected in hashes.items():
        source = Path(str(raw_path)).resolve()
        require(isinstance(expected, str) and len(expected) == 64, f"invalid input digest: {source}")
        if source.suffix.lower() in RAW_SUFFIXES or source.suffix.lower() not in STATIC_SUFFIXES:
            continue
        require(source.is_file(), f"missing metadata input: {source}")
        require(sha(source) == expected, f"metadata input hash drift: {source}")
    future_hashes = request.get("future_input_sha256") or {}
    require(all(value is None for value in future_hashes.values()), f"future input hash is non-null: {path}")
    for value in (request.get("future_outputs") or {}).values():
        if isinstance(value, dict):
            require(all(item is None for key, item in value.items() if key.endswith("sha256")), f"future output hash is non-null: {path}")
    if kind == "qa":
        require(request.get("cpu_task_kind") == "audit", f"QA task kind drift: {path}")
        require(str(request.get("attempt_id", "")).endswith("-prepared-report-qa-csv-parser-repair-104"), f"QA retry identity drift: {path}")
        observed = request.get("upstream_qa103_observation") or {}
        require(request.get("retry_of_attempt", "").endswith("-prepared-report-qa-semantic-adapter-103"), f"QA103 binding drift: {path}")
        if observed.get("report", {}).get("exists"):
            require(observed.get("report_status") == "fail", f"observed QA103 was not retained as fail: {path}")
            require(observed.get("passed") is False, f"observed QA103 was treated as pass: {path}")
        csv = request.get("registered_existing_csv")
        if csv is not None:
            require(csv.get("read_or_hashed_here") is False, f"source claimed CSV read: {path}")
    elif kind == "native":
        require(request.get("cpu_task_kind") == "solver", f"native task kind drift: {path}")
        command = [str(value) for value in request.get("command", [])]
        require("-tmax:4.0" in command and "-tout:0.01" in command, f"native recipe drift: {path}")
        require(not any("mdbc" in value.lower() or "noslip" in value.lower() for value in command), f"native options changed: {path}")
        require(request.get("expected_native_frames") == 401 and request.get("expected_dimension") == 3, f"native contract drift: {path}")
        require(request.get("initial_qa_gate", {}).get("enable_only_after_actual_report_pass") is True, f"native QA gate missing: {path}")
        require(request.get("shared_gpu_lease_policy", {}).get("resolved_gpu_uuid") is None, f"source resolved a GPU UUID: {path}")
    elif kind == "typed":
        require(request.get("cpu_task_kind") == "conversion", f"typed task kind drift: {path}")
        require(request.get("physical_condition_hash_scope", {}).get("canonical_grant") is False and request.get("canonical_grant") is False, f"canonical grant drift: {path}")
        require(request.get("physical_condition_hash_scope", {}).get("actual_converter_physical_condition_sha256") is None, f"actual converter scope fabricated: {path}")
        require(request.get("prospective_legacy_scope_sha256"), f"legacy scope missing: {path}")
        require(request.get("metadata_only_preflight_actual_conversion") is False, f"typed preflight claims actual conversion: {path}")
    return request


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    package = args.package.resolve()
    manifest_path = package / "F2_STAGE1_FRESH104_ACTUAL_QA_NATIVE_TYPED_ADAPTER_MANIFEST.json"
    manifest = load(manifest_path)
    require(manifest.get("case_count") == 16 and manifest.get("fresh_id") == "fresh104", "manifest identity/count drift")
    require(manifest.get("all_requests_disabled") is True and manifest.get("future_hashes_null") is True, "manifest enables future work")
    require(manifest.get("observed_qa_passes") == 0 and manifest.get("four_root379_failures_preserved") is True, "manifest overclaims QA")
    seen: set[str] = set()
    failures = 0
    pending = 0
    for row in manifest["cases"]:
        cid = str(row["case_id"])
        require(cid == str(row["root378_actual_qa"].get("case_id", cid)) or "case_id" not in row["root378_actual_qa"], f"case observation identity drift: {cid}")
        root_req = Path(str(row["root378_request"]["path"])).resolve()
        require(sha(root_req) == row["root378_request"]["sha256"], f"Root378 request hash drift: {cid}")
        require(str(row["root378_attempt_id"]).endswith("-prepared-report-qa-semantic-adapter-103"), f"Root378 attempt drift: {cid}")
        qa_path = Path(str(row["csv_parser_repair_request"]["path"])).resolve()
        native_path = Path(str(row["native_request"]["path"])).resolve()
        typed_path = Path(str(row["typed_request"]["path"])).resolve()
        require(sha(qa_path) == row["csv_parser_repair_request"]["sha256"], f"QA request hash drift: {cid}")
        require(sha(native_path) == row["native_request"]["sha256"], f"native request hash drift: {cid}")
        require(sha(typed_path) == row["typed_request"]["sha256"], f"typed request hash drift: {cid}")
        check_request(qa_path, "qa", package, seen)
        # The same case identity must be checked independently for downstream requests.
        native = load(native_path); typed = load(typed_path)
        require(native.get("case_id") == cid and typed.get("case_id") == cid, f"downstream identity drift: {cid}")
        check_request(native_path, "native", package, set())
        check_request(typed_path, "typed", package, set())
        report = row["root378_actual_qa"].get("report", {})
        if report.get("exists"):
            failures += 1
            require(row["root378_actual_qa"].get("report_status") == "fail", f"observed report not failed: {cid}")
        else:
            pending += 1
        require(native.get("initial_qa_attempt_id") == check_request(qa_path, "qa", package, set()).get("attempt_id"), f"native QA dependency drift: {cid}")
        require(typed.get("native_attempt_id") == native.get("attempt_id"), f"typed native dependency drift: {cid}")
        require(typed.get("initial_qa_attempt_id") == native.get("initial_qa_attempt_id"), f"typed QA dependency drift: {cid}")
    result = {"schema": "ds02.f2.stage1.fresh104.source-validation.v1", "status": "pass", "case_count": 16, "observed_root379_failures": failures, "pending_root379_reports": pending, "observed_qa_passes": 0, "scientific_payloads_read_or_hashed": [], "all_requests_disabled": True, "future_hashes_null": True, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA}
    output = args.output or package / "evidence/fresh104-source-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
