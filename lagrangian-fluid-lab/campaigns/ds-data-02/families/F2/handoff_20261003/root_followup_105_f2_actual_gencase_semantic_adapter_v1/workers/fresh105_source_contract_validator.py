#!/usr/bin/env python3
"""Pure metadata validator for the fresh105 disabled package.

This validator intentionally does not import or call ``runtime_v2``.  The
runtime hashes every ``input_files`` entry during launch; fresh105 preflight
only checks request structure and hashes safe JSON/XML/Python metadata.  Raw
scientific paths are checked for a producer-recorded 64-hex digest and are
never opened here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

STATIC_SUFFIXES = {".json", ".xml", ".py", ".md", ".txt"}
RAW_SUFFIXES = {".dat", ".bi4", ".ibi4", ".h5", ".hdf5", ".csv", ".vtk", ".vtu", ".vtp", ".xmf", ".png", ".gif"}
LOGICAL_GUARD = "a84bee972a733eba4808587384144def75b28dff51f04e83bbf63d0dff0bed0a"
STRICT_DISPATCH_SHA = "81bdd60e5de4fec362807043ab632864405f1667a0658560fb9349025aab75ec"


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON object required: {path}")
    return value


def sha_static(path: Path) -> str:
    path = Path(path).resolve()
    if path.suffix.lower() not in STATIC_SUFFIXES or path.suffix.lower() in RAW_SUFFIXES:
        raise ValueError(f"scientific/non-static path refused: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def check_inputs(request: Mapping[str, Any]) -> None:
    files = request.get("input_files")
    hashes = request.get("input_sha256")
    require(isinstance(files, list) and isinstance(hashes, dict) and set(files) == set(hashes), "input closure mismatch")
    for raw_path, expected in hashes.items():
        path = Path(str(raw_path)).resolve()
        require(isinstance(expected, str) and len(expected) == 64, f"invalid input digest: {path}")
        if path.suffix.lower() in RAW_SUFFIXES or path.suffix.lower() not in STATIC_SUFFIXES:
            continue
        require(path.is_file() and sha_static(path) == expected, f"static metadata input hash mismatch: {path}")
    for value in (request.get("future_input_sha256") or {}).values():
        require(value is None, "future input hash is non-null")


def check_common(request: Mapping[str, Any], package: Path) -> None:
    for field in ("family_id", "case_id", "attempt_id", "kind", "command", "cwd", "max_wall_seconds", "cpu_threads", "estimated_storage_bytes", "input_files", "worktree_root"):
        require(field in request, f"missing runtime field: {field}")
    require(request.get("family_id") == "F2", "family drift")
    require(request.get("disabled") is True and request.get("execution_allowed") is False and request.get("launch_allowed") is False, "enabled request")
    require(request.get("source_only") is True and request.get("future_hashes_null") is True, "source/future guard drift")
    require(request.get("strict_guard_digest") == LOGICAL_GUARD and request.get("strict_dispatch_file_sha256") == STRICT_DISPATCH_SHA, "strict digest drift")
    require(Path(str(request.get("worktree_root"))).resolve() == Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics").resolve(), "worktree root drift")
    check_inputs(request)


def check_qa(request: Mapping[str, Any]) -> None:
    check_common(request, Path("."))
    require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "audit", "QA task kind drift")
    require(request.get("cpu_threads") == 4 and request.get("max_wall_seconds") == 1800 and request.get("estimated_storage_bytes") == 268435456, "Root396 QA resource contract drift")
    require(str(request.get("attempt_id", "")).endswith("-prepared-report-qa-csv-layout-repair-105"), "QA identity drift")
    command = [str(item) for item in request.get("command", [])]
    require(any(value.endswith("fresh105_initial_qa_csv_parser.py") for value in command), "fresh105 parser missing")
    require("--definition" in command and "--gencase-receipt" in command and "--prepared-input-report" in command and "--runtime-evidence" in command, "QA metadata inputs incomplete")
    require(request.get("registered_existing_csv") is None or request["registered_existing_csv"].get("read_or_hashed_here") is False, "source claimed CSV read")


def check_semantic(request: Mapping[str, Any]) -> None:
    check_common(request, Path("."))
    require(request.get("kind") == "cpu" and request.get("cpu_task_kind") == "audit", "semantic task kind drift")
    require(request.get("cpu_threads") == 4 and request.get("max_wall_seconds") == 1800 and request.get("estimated_storage_bytes") == 268435456, "semantic resource contract drift")
    require(any(str(value).endswith("fresh105_gencase_semantic_adapter.py") for value in request.get("command", [])), "semantic adapter missing")
    require(request.get("semantic_receipt", {}).get("sha256") is None, "semantic future hash fabricated")
    require(request.get("gencase_receipt_sha256") and len(request["gencase_receipt_sha256"]) == 64, "raw producer receipt hash missing")
    require(request.get("scientific_payloads_read_or_hashed") == [], "semantic adapter payload claim drift")


def check_native(request: Mapping[str, Any]) -> None:
    check_common(request, Path("."))
    require(request.get("kind") == "qualification" and request.get("cpu_task_kind") == "solver", "native kind drift")
    command = [str(value) for value in request.get("command", [])]
    require(command and command[0].endswith("DualSPHysics5.4_linux64"), "approved solver drift")
    require("-tmax:4.0" in command and "-tout:0.01" in command, "native recipe drift")
    require(not any("mdbc" in value.lower() or "noslip" in value.lower() for value in command), "native option drift")
    require(request.get("expected_native_frames") == 401 and request.get("expected_dimension") == 3 and request.get("expected_particles") == 418104, "native dimensions/counts drift")
    require(request.get("gencase_receipt_sha256") is None and "gencase-semantic-metadata-105" in str(request.get("gencase_receipt")), "native did not defer semantic receipt")
    require(request.get("initial_qa_gate", {}).get("enable_only_after_actual_report_pass") is True, "native QA gate missing")
    require(request.get("shared_gpu_lease_policy", {}).get("resolved_gpu_uuid") is None, "source resolved GPU UUID")
    require(request.get("future_input_sha256", {}).get(str(request.get("gencase_receipt"))) is None, "semantic future hash missing")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    package = args.package.resolve()
    manifest = load(package / "F2_STAGE1_FRESH105_GENCASE_SEMANTIC_CSV_LAYOUT_ADAPTER_MANIFEST.json")
    require(manifest.get("fresh_id") == "fresh105" and manifest.get("case_count") == 16, "manifest identity/count drift")
    require(manifest.get("all_requests_disabled") is True and manifest.get("future_hashes_null") is True, "manifest enabled future work")
    seen: set[str] = set()
    semantic = qa = native = 0
    observed = scientific_good = interface_bad = 0
    for row in manifest["cases"]:
        cid = str(row["case_id"])
        require(cid not in seen, f"duplicate case: {cid}")
        seen.add(cid)
        for field in ("semantic_request", "qa_request", "native_request"):
            path = Path(str(row[field]["path"])).resolve()
            require(sha_static(path) == row[field]["sha256"], f"request binding drift: {cid}/{field}")
            req = load(path)
            if field == "semantic_request":
                check_semantic(req); semantic += 1
            elif field == "qa_request":
                check_qa(req); qa += 1
            else:
                check_native(req); native += 1
        observation = row.get("root397_observation", {})
        if observation.get("report", {}).get("exists"):
            observed += 1
            require(observation.get("negative_evidence_preserved") is True, f"Root397 failure not preserved: {cid}")
            if observation.get("scientific_checks_all_true"):
                scientific_good += 1
            if observation.get("layout_checks_false"):
                interface_bad += 1
        require(row.get("raw_receipt_immutable") is True and row.get("semantic_output_sha256") is None and row.get("qa_report_sha256") is None and row.get("native_receipt_sha256") is None, f"future evidence drift: {cid}")
    result = {
        "schema": "ds02.f2.stage1.fresh105.source-validation.v1", "status": "pass", "case_count": len(seen),
        "semantic_requests": semantic, "qa_requests": qa, "native_requests": native,
        "root397_reports_seen": observed, "root397_scientific_checks_all_true": scientific_good,
        "root397_interface_layout_failures_preserved": interface_bad, "actual_qa_passes_claimed": 0,
        "scientific_payloads_read_or_hashed": [], "runtime_v2_validate_request_called": False,
        "all_requests_disabled": True, "future_hashes_null": True, "strict_dispatch_file_sha256": STRICT_DISPATCH_SHA,
    }
    output = args.output or package / "evidence/fresh105-source-validation.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
