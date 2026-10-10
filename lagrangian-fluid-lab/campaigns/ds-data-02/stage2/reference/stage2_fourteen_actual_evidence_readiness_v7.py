#!/usr/bin/env python3
"""Materialize an exact, source-linked fourteen-sentinel readiness snapshot.

The v6 status file is retained byte-for-byte.  This additive index removes
the prose-only ambiguity by retaining the exact proof paths/SHA/stat metadata,
dimension states, next guarded parent, cost envelope, and failure recovery for
every sentinel.  It does not infer scientific qualification and does not read
any native/VTK/H5 payload.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any


HERE = Path(__file__).resolve().parent
V6 = HERE / "stage2_fourteen_actual_evidence_readiness_v6.json"
SCALE_REGISTRY = HERE / "stage2_three_sentinel_calibration_scales_v2.json"
JSON_CAP = 10 * 1024 * 1024
TARGETS = {"F2-S2", "F3-S1", "F5-S1"}
THREE_FILES = {
    "builder": "stage2_three_sentinel_calibration_request_v1.py",
    "worker": "stage2_three_sentinel_calibration_worker_v1.py",
    "verifier": "stage2_three_sentinel_calibration_verify_v1.py",
    "contract": "stage2_three_sentinel_calibration_worker_contract_v1.json",
}


class ReadinessFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _read(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ReadinessFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ReadinessFailure(f"{label} exceeds metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ReadinessFailure(f"{label} changed during read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessFailure(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ReadinessFailure(f"{label} must be an object")
    return value, {"path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "stat": after,
                   "read_scope": "small_metadata_only"}


def _proof_ref(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("file") or item.get("source") or item
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise ReadinessFailure("evidence row lacks an exact path")
    sha = value.get("sha256")
    if not isinstance(sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", sha):
        raise ReadinessFailure(f"evidence row lacks a concrete SHA: {value.get('path')}")
    result = {
        "path": value["path"], "sha256": sha, "bytes": value.get("bytes", value.get("stat", {}).get("bytes")),
        "kind": item.get("kind"), "claim_scope": item.get("claim_scope", item.get("note")),
        "source_metadata_only": True,
    }
    return result


def _row(value: dict[str, Any], scale_registry: dict[str, Any]) -> dict[str, Any]:
    sid = value.get("sentinel_id")
    evidence = [_proof_ref(item) for item in value.get("actual_evidence", [])]
    next_parent = value.get("next_parent")
    if not isinstance(next_parent, dict) or not next_parent.get("action"):
        raise ReadinessFailure(f"{sid} has no executable next parent action")
    result = {
        "sentinel_id": sid,
        "family_id": value.get("family_id"),
        "physical_case_id": value.get("physical_case_id"),
        "actual_evidence_count": value.get("actual_evidence_count"),
        "actual_evidence": evidence,
        "dimension_readiness": value.get("dimension_readiness", {}),
        "terminal_state": value.get("terminal_state", {}),
        "scientific_qualification": value.get("scientific_qualification", {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}),
        "minimum_new_evidence": value.get("minimum_new_evidence"),
        "next_parent": next_parent,
        "next_scientific_action": value.get("next_scientific_action"),
        "unknown_impact": value.get("unknown_impact"),
        "recovery_if_gate_fails": value.get("recovery_if_gate_fails"),
        "request_graph_reference": value.get("request_graph_reference"),
    }
    if sid in TARGETS:
        scale_row = next((item for item in scale_registry.get("sentinels", []) if item.get("sentinel_id") == sid), None)
        if scale_row is None:
            raise ReadinessFailure(f"scale registry has no {sid}")
        result["source_bound_scale_registry"] = {
            "path": str(SCALE_REGISTRY),
            "sha256": scale_registry["_sha256"],
            "reference_scales": scale_row.get("reference_scales"),
            "uncertainty_or_gate": scale_row.get("uncertainty_or_gate"),
            "valid_window": scale_row.get("valid_window"),
            "authority": scale_row.get("authority"),
            "blockers": scale_row.get("blockers"),
        }
        result["runnable_calibration_chain"] = {
            "status": "SOURCE_PREPARED_NO_PARENT_RUN",
            "files": {key: str(HERE / name) for key, name in THREE_FILES.items()},
            "scientific_credit": 0,
            "resources": {"cpu_threads": 1, "memory_max_bytes": 4 * 1024 ** 3,
                           "max_wall_seconds": 900, "gpu": "none"},
        }
    else:
        result["runnable_calibration_chain"] = {"status": "NOT_THIS_THREE_SENTINEL_CHAIN", "scientific_credit": 0}
    return result


def build() -> dict[str, Any]:
    source, source_record = _read(V6, "v6 readiness source")
    scales, scales_record = _read(SCALE_REGISTRY, "calibration scale registry")
    scales["_sha256"] = scales_record["sha256"]
    rows = source.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ReadinessFailure("v6 source must contain exactly fourteen sentinels")
    result_rows = [_row(item, scales) for item in rows]
    ids = [item["sentinel_id"] for item in result_rows]
    if len(set(ids)) != 14:
        raise ReadinessFailure("sentinel IDs are not unique")
    return {
        "schema": "ds02.stage2.fourteen-actual-evidence-readiness.v7",
        "status": "ACTUAL_EVIDENCE_INDEX_WITH_EXECUTABLE_NEXT_PARENTS_NO_SCIENTIFIC_QUALIFICATION",
        "sentinel_count": 14,
        "scientific_credit": 0,
        "global_policy": source.get("global_policy", {}),
        "source_inputs": {"v6": source_record, "calibration_scales_v2": scales_record},
        "three_sentinel_chain": {
            "status": "SOURCE_PREPARED_NO_PARENT_RUN",
            "builder": str(HERE / THREE_FILES["builder"]),
            "worker": str(HERE / THREE_FILES["worker"]),
            "verifier": str(HERE / THREE_FILES["verifier"]),
            "contract": str(HERE / THREE_FILES["contract"]),
            "scale_registry": scales_record,
            "sentinels": sorted(TARGETS),
        },
        "sentinels": result_rows,
        "actual_vs_plan": source.get("actual_vs_plan", {}),
    }


def self_test() -> None:
    result = build()
    assert result["sentinel_count"] == 14
    assert len(result["sentinels"]) == 14
    assert all(item["scientific_qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
               for item in result["sentinels"])
    assert all(item["next_parent"].get("action") for item in result["sentinels"])
    assert set(result["three_sentinel_chain"]["sentinels"]) == TARGETS
    print("PASS_FOURTEEN_ACTUAL_EVIDENCE_READINESS_V7_SELFTEST")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        value = build()
        if args.self_test:
            self_test()
            return 0
        if args.output is None:
            parser.error("--output is required unless --self-test is used")
        output = args.output.expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ReadinessFailure(f"refusing to overwrite {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({"status": value["status"], "sentinels": 14, "scientific_credit": 0,
                          "output": str(output)}, sort_keys=True))
        return 0
    except (ReadinessFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_ACTUAL_EVIDENCE_READINESS_V7: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
