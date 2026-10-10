#!/usr/bin/env python3
"""Build an exact, source-bound 14-sentinel scope/reuse card.

The existing dimension catalog and next-request index contain useful evidence,
but their status words are not scientific outcomes.  This additive consumer
joins each fixed sentinel to the exact evidence paths/SHA, records which
fields and recognition prerequisites are present, separates reusable bounded
diagnostics from unresolved error dimensions, and carries one concrete next
parent action.  It never opens a referenced solver/native payload and never
grants QI/QN/QE or neighboring-grid truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
from typing import Any

HERE = Path(__file__).resolve().parent
CATALOG_DEFAULT = HERE / "stage2_fourteen_evidence_dimension_catalog_v3.json"
REQUESTS_DEFAULT = HERE / "stage2_fourteen_source_status_v3_next_requests.json"
SCHEMA = "ds02.stage2.fourteen-scientific-scope-reuse.v1"
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "scientific_credit": 0}
ROOT345_TARGETS = {"F2-S2", "F3-S1", "F5-S1"}


class ScopeFailure(RuntimeError):
    pass


def _record(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ScopeFailure(f"{label} is not a regular file: {path}")
    before = path.stat()
    if before.st_size > CAP:
        raise ScopeFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes(); after = path.stat()
    if before != after:
        raise ScopeFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScopeFailure(f"{label} is not bounded JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ScopeFailure(f"{label} root is not an object: {path}")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(),
                   "bytes": len(raw), "stat": {"device": int(after.st_dev), "inode": int(after.st_ino),
                                                 "bytes": int(after.st_size), "mtime_ns": int(after.st_mtime_ns),
                                                 "ctime_ns": int(after.st_ctime_ns)}}


def _evidence(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not isinstance(value.get("sha256"), str):
        raise ScopeFailure(f"{label} lacks exact evidence path/SHA")
    if len(value["sha256"]) != 64:
        raise ScopeFailure(f"{label} evidence SHA is not concrete")
    return {"path": value["path"], "sha256": value["sha256"],
            "claim_scope": value.get("claim_scope", "bounded_proof_field_inventory_only"),
            "source_v2_sha256": value.get("source_v2_sha256"), "stat": value.get("stat")}


def _build(catalog_path: Path, requests_path: Path) -> dict[str, Any]:
    catalog, catalog_record = _record(catalog_path, "fourteen dimension catalog")
    requests, requests_record = _record(requests_path, "fourteen next-request index")
    if catalog.get("schema") != "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v3":
        raise ScopeFailure("dimension catalog schema mismatch")
    if requests.get("schema") != "ds02.stage2.fourteen-source-status.v3-next-requests":
        raise ScopeFailure("next-request index schema mismatch")
    records = catalog.get("records")
    next_rows = requests.get("requests")
    if not isinstance(records, list) or not isinstance(next_rows, list):
        raise ScopeFailure("catalog/index lacks record arrays")
    by_sentinel: dict[str, list[dict[str, Any]]] = {}
    for row in records:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise ScopeFailure("catalog record lacks sentinel_id")
        by_sentinel.setdefault(row["sentinel_id"], []).append(row)
    by_request: dict[str, dict[str, Any]] = {}
    for row in next_rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise ScopeFailure("next request lacks sentinel_id")
        if row["sentinel_id"] in by_request:
            raise ScopeFailure(f"duplicate next request for {row['sentinel_id']}")
        by_request[row["sentinel_id"]] = row
    sentinel_ids = sorted(set(by_sentinel) | set(by_request))
    if len(sentinel_ids) != 14:
        raise ScopeFailure(f"expected exactly fourteen sentinels, got {len(sentinel_ids)}")
    entries: list[dict[str, Any]] = []
    for sentinel_id in sentinel_ids:
        evidence_rows = by_sentinel.get(sentinel_id, [])
        request = by_request.get(sentinel_id)
        if request is None:
            raise ScopeFailure(f"{sentinel_id} lacks a next action")
        dimensions: list[dict[str, Any]] = []
        for row in evidence_rows:
            evidence = _evidence(row.get("evidence"), f"{sentinel_id}/{row.get('evidence_id')}")
            dimensions.append({
                "evidence_id": row.get("evidence_id"), "dimension": row.get("dimension"),
                "dimension_observation": row.get("dimension_observation", "UNKNOWN"),
                "scope": row.get("scope", "bounded_proof_field_inventory_only"),
                "evidence": evidence,
                "field_presence": {"status": (row.get("field_presence") or {}).get("status"),
                                   "paths": [item.get("path") for item in (row.get("field_presence") or {}).get("paths", [])
                                             if isinstance(item, dict) and isinstance(item.get("path"), str)]},
                "observed_scales": [{"path": item.get("path"), "unit": item.get("unit")}
                                    for item in (row.get("observed_scales") or {}).get("fields", [])
                                    if isinstance(item, dict) and isinstance(item.get("path"), str)],
                "recognition_prerequisites": row.get("recognition_prerequisites", []),
                "source_index_flags": row.get("source_index_flags", {}),
                "scientific_qualification": row.get("scientific_qualification", dict(UNKNOWN)),
            })
        actual_reuse = [item["evidence"] for item in dimensions
                        if (item.get("source_index_flags") or {}).get("actual") is True]
        entries.append({
            "sentinel_id": sentinel_id,
            "family_id": request.get("family_id"), "physical_case_id": request.get("physical_case_id"),
            "actual_evidence_reuse": {"status": "BOUNDED_METADATA_REUSE_ONLY", "evidence": actual_reuse,
                                       "scientific_credit": 0, "neighbor_grid_truth": False},
            "error_separation": {"dimensions": dimensions,
                                  "spatial_vs_time_vs_output_must_remain_separate": True,
                                  "unknown_prerequisites_are_preserved": True},
            "next_action": {"task_kind": request.get("task_kind"), "state": request.get("state"),
                             "action": request.get("action"), "source_prerequisite": request.get("source_prerequisite"),
                             "parent_guard_requirements": request.get("parent_guard_requirements", []),
                             "success_condition": request.get("success_condition"),
                             "stop_condition": request.get("stop_condition"),
                             "evidence": [_evidence(item, f"{sentinel_id} next action")
                                          for item in request.get("evidence", [])]},
            "root345_chain": {"required": sentinel_id in ROOT345_TARGETS,
                              "status": "WAITING_FOR_ROOT345_PRODUCER_AND_NATIVE_HEADER_INITIAL_SUPPORT"
                              if sentinel_id in ROOT345_TARGETS else "NOT_APPLICABLE",
                              "chain_module": "stage2_three_sentinel_native_header_initial_support_calibration_chain_v1.py"
                              if sentinel_id in ROOT345_TARGETS else None},
            "qualification": dict(UNKNOWN),
        })
    return {"schema": SCHEMA, "status": "SOURCE_BOUND_SCOPE_REUSE_AND_ERROR_SEPARATION_ONLY",
            "source_index": {"catalog": catalog_record, "next_requests": requests_record},
            "record_count": len(entries), "entries": entries,
            "scope": {"reads_proof_json_only": True, "payload_read": False, "solver_launch": False,
                       "gencase_launch": False, "neighbor_grid_truth": False, "interpolation": False,
                       "status_words_do_not_imply_observed_dimension": True},
            "scientific_qualification": dict(UNKNOWN)}


def build(catalog_path: Path, requests_path: Path, output: Path) -> dict[str, Any]:
    result = _build(catalog_path, requests_path)
    output = output.expanduser().absolute()
    if output.exists() or output.is_symlink():
        raise ScopeFailure(f"refusing overwrite: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="fourteen-scope-reuse-") as td:
        root = Path(td)
        catalog = {"schema": "ds02.stage2.fourteen-reference-evidence-dimension-catalog.v3", "records": []}
        requests = {"schema": "ds02.stage2.fourteen-source-status.v3-next-requests", "requests": []}
        for index in range(14):
            sid = f"F{index // 2 + 1}-S{index % 2 + 1}"
            evidence = {"path": str(root / f"{sid}-evidence.json"), "sha256": f"{index + 1:064x}",
                        "claim_scope": "fixture-only", "stat": {"bytes": 2}}
            (root / f"{sid}-evidence.json").write_text("{}")
            catalog["records"].append({"sentinel_id": sid, "evidence_id": f"E{index}", "dimension": "time_step",
                                       "dimension_observation": "UNKNOWN", "evidence": evidence,
                                       "field_presence": {"status": "FIELDS_PRESENT", "paths": []},
                                       "source_index_flags": {"actual": index == 0}})
            requests["requests"].append({"sentinel_id": sid, "family_id": sid[:2], "physical_case_id": f"P-{sid}",
                                         "task_kind": "fixture", "state": "SOURCE_READY_PARENT_REVIEW",
                                         "action": "fixture bounded diagnostic", "evidence": [evidence]})
        c = root / "catalog.json"; q = root / "requests.json"; out = root / "out.json"
        c.write_text(json.dumps(catalog)); q.write_text(json.dumps(requests))
        result = build(c, q, out)
        assert result["record_count"] == 14 and result["scientific_qualification"]["scientific_credit"] == 0
    print("PASS_FOURTEEN_SCOPE_REUSE_ERROR_SEPARATION_TINY_NO_PRODUCTION_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true"); mode.add_argument("--build", action="store_true")
    parser.add_argument("--catalog", type=Path, default=CATALOG_DEFAULT)
    parser.add_argument("--next-requests", type=Path, default=REQUESTS_DEFAULT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test(); return 0
        if args.output is None:
            parser.error("--build requires --output")
        value = build(args.catalog, args.next_requests, args.output)
        print(json.dumps({"status": value["status"], "output": str(args.output.absolute()),
                          "record_count": value["record_count"], "scientific_credit": 0}, sort_keys=True)); return 0
    except (ScopeFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_SCOPE_REUSE_ERROR_SEPARATION_V1: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
