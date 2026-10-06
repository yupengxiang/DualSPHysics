#!/usr/bin/env python3
"""Static fresh112 contract validation; never starts Root023 or opens payloads."""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
from pathlib import Path


HERE = Path(__file__).resolve().parents[1]
BAD_SUFFIXES = {".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".dat", ".vtk", ".vtu", ".npy", ".npz", ".raw", ".bin"}
GI = 1024 ** 3


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def import_worker():
    path = HERE / "workers/nvme_render_successor.py"
    spec = importlib.util.spec_from_file_location("fresh112_nvme_render_successor", path)
    check(spec is not None and spec.loader is not None, "worker import spec missing")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> None:
    manifest_path = HERE / "manifest.json"
    manifest = load(manifest_path)
    check(manifest["schema"] == "ds02.f3.fresh112.package-manifest.v1", "manifest schema")
    check(manifest["package_id"] == "F3_fresh112_fresh110_publication_lifecycle_hardening", "manifest package identity")
    check(manifest["source_only"] is True and manifest["no_jobs_started"] is True, "manifest source boundary")
    check(manifest["no_science_payload_read_or_hashed"] is True, "manifest payload boundary")

    listed = set()
    for row in manifest["files"]:
        rel = row["path"]
        check(rel not in listed, f"duplicate manifest entry: {rel}")
        listed.add(rel)
        path = HERE / rel
        check(path.is_file(), f"missing package file: {rel}")
        check(path.suffix.lower() not in BAD_SUFFIXES, f"scientific payload shipped: {rel}")
        check(path.stat().st_size == int(row["bytes"]), f"size mismatch: {rel}")
        check(digest(path) == row["sha256"], f"digest mismatch: {rel}")

    for path in HERE.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        check(path.suffix.lower() not in BAD_SUFFIXES, f"scientific payload in package tree: {path}")
        if path.suffix.lower() == ".json":
            load(path)
        elif path.suffix.lower() == ".py":
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    worker_text = (HERE / "workers/nvme_render_successor.py").read_text(encoding="utf-8")
    for literal in (
        "resource-ledger.lock", "resource-ledger.json", "--force-offscreen-rendering",
        "_terminate_owned_process", "_rewrite_pvsm", "_remove_stage",
        "except BaseException", "published_bytes_total", "post_publish_home_floor_rechecked",
        "_reject_private_paths", "_require_final_output_path",
    ):
        check(literal in worker_text, f"worker missing safety contract: {literal}")
    check('request["family_id"] != "F6"' not in worker_text, "worker retained an unnecessary F6-only family gate")
    check("resource-ledger.json" not in load(HERE / "metadata/successor-policy.json").get("resource_ledger_lock", ""), "request lock must be the lock file")

    worker = import_worker()
    audit = load(HERE / "metadata/root860-audit.json")
    check(audit["controller_result_present"] is False, "Root860 result unexpectedly present in audit")
    check(audit["execution_receipt_count"] == 0 and audit["render_output_directory_count"] == 0, "Root860 had output at audit")
    check(audit["render_request_file_count"] == 0 and audit["renderer_worker_observed_at_audit"] is False, "Root860 had a worker at audit")
    check(audit["terminal_completion_claim"] is False and audit["root860_f4_gate_preserved_as_historical_only"] is True, "Root860 historical boundary")

    catalog = load(HERE / "metadata/f6-root722-case-catalog.json")
    check(catalog["case_count"] == 24 and len(catalog["cases"]) == 24, "Root722 case count")
    check(catalog["all_root722_completed0_N3"] is True, "Root722 status aggregate")
    check(catalog["all_expected_frames"] == [241] and catalog["all_expected_particles"] == [417505], "Root722 dimensions")
    check(catalog["cross_family_gate_removed"] is True and catalog["f4_root856_dependency_used_by_root860"] is False, "Root860 lineage disclosure")
    by_case = {row["case_id"]: row for row in catalog["cases"]}
    check(len(by_case) == 24, "Root722 unique case IDs")

    requests = sorted((HERE / "requests").glob("*.json"))
    check(len(requests) == 24, "disabled request count")
    seen = set()
    for path in requests:
        request = load(path)
        case = request["case_id"]
        check(case not in seen, f"duplicate request case: {case}")
        seen.add(case)
        check(case == request["physical_case_id"] and case in by_case, f"request case binding: {case}")
        check(request["schema"] == worker.SCHEMA, f"request schema: {case}")
        check(request["fresh_id"] == "fresh112", f"fresh id: {case}")
        check(request["disabled"] is True and request["launch"] is False and request["launch_allowed"] is False and request["execution_allowed"] is False, f"request must be disabled: {case}")
        check(request["source_only"] is True and request["future_input_hashes_null"] is True, f"source boundary: {case}")
        check(request["reservation_id"] is None and request["current_attempt_id"] is None, f"unbound reservation: {case}")
        check(request["launch_owner"] == "root" and request["root_only"] is True, f"owner: {case}")
        check(request["resource_ledger_lock"].endswith("/runtime/resource-ledger.lock"), f"real lock: {case}")
        check("resource-ledger.json" not in request["resource_ledger_lock"], f"lock path confused with ledger: {case}")
        check(request["cross_family_gate_removed"] is True and request["root860_historical_wait_gate_not_in_successor"] is True, f"Root860 gate: {case}")
        check(request["expected_frames"] == 241 and request["expected_particles"] == 417505 and request["expected_contact_sheets"] == 11, f"dimensions: {case}")
        check(request["keyframe_indices"] == [0, 40, 80, 120, 160, 200, 240], f"keyframes: {case}")
        check(request["home_free_floor_bytes"] >= 500 * GI and request["nvme_free_floor_bytes"] >= 100 * GI, f"floors: {case}")
        check(request["nvme_stage_cap_bytes"] <= 24 * GI and request["home_publish_cap_bytes"] <= 3 * GI, f"caps: {case}")
        check(request["renderer_argv_template"] == [request["pvpython"], "--force-offscreen-rendering", request["renderer"], "--manifest", "{manifest}", "--output-dir", "{stage_render}"], f"Root732 argv: {case}")
        check(request["root023_contract"]["force_offscreen_rendering"] is True and request["root023_contract"]["diagnostic_frames_omitted"] is True, f"full-frame contract: {case}")
        check(request["future_scientific_input_hashes"] is None, f"scientific future hash boundary: {case}")
        check(request["no_science_payload_read_or_hash_by_source_package"] is True, f"payload boundary: {case}")
        for value in request["future_input_files"]:
            check(Path(value).suffix.lower() not in BAD_SUFFIXES, f"future closure contains payload: {case}: {value}")
        result = worker.preflight_request(request)
        check(result["valid"] is True and result["science_payloads_opened"] is False, f"worker preflight: {case}")
        row = by_case[case]
        check(row["root722_status"] == "actual_completed0_N3_pass" and row["expected_frames"] == 241 and row["expected_particles"] == 417505, f"Root722 source row: {case}")

    check(seen == set(by_case), "request/catalog case sets differ")
    print(json.dumps({
        "status": "pass",
        "fresh_id": "fresh112",
        "requests": len(requests),
        "root722_actual_completed0_N3": 24,
        "root860_render_requests_at_audit": 0,
        "source_only": True,
        "jobs_started": False,
        "science_payloads_opened_or_hashed": False,
        "renderer_argv_contract": "Root732 --force-offscreen-rendering full saved frames",
        "live_ledger_lock": "/home/jade/Projects/DualSPHysics-data/ds-data-02/runtime/resource-ledger.lock",
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
