#!/usr/bin/env python3
"""Build the additive Stage2 consumer evidence/catalog forward index.

The index joins the already-written small root verification checkpoints.  It
does not read H5, BI4, raw frames, or result arrays, and it does not replace
V29/V30 or promote any QI/QN/QE status.  The three ordinary CPU receipts
whose systemd terminal deltas are still pending remain explicitly pending;
the closed ROOT078 fee is represented as a closed accounting observation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.stage2.consumer-evidence-catalog.v31"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
PENDING_CPU = {
    "F3_S2_SOURCE_MATCHED_V2_ACTUAL_SUPPORT_ROOT_VERIFICATION_093.json",
    "F2_COARSE_GENERATED_BI4_ACTUAL_WORKER_SNAPSHOT_ROOT_VERIFICATION_094.json",
    "F3_S2_CONTINUOUS_OWNER_ACTUAL_MASS_RECONCILIATION_ROOT_VERIFICATION_096.json",
}
ENTRY_SCOPES = {
    "F2_TYPED_PARENT_V6_ACTUAL_TERMINAL_FEE_CLOSED_ROOT_VERIFICATION_078.json":
        "typed-only evaluator terminal fee closure; no scientific qualification",
    "F2_MIDDLE_CELL_SELECTOR_ACTUAL_GENCASE_MASS_ROOT_VERIFICATION_083.json":
        "middle-grid GenCase XML and initial mass support prerequisite",
    "F2_FINE_CELL_SELECTOR_ACTUAL_GENCASE_MASS_ROOT_VERIFICATION_084.json":
        "fine-grid GenCase XML and initial mass support prerequisite",
    "F3_S2_SOURCE_CLONE_ACTUAL_GENCASE_ROOT_VERIFICATION_086.json":
        "F3-S2 source/control clone and initial mass support prerequisite",
    "F2_MIDDLE_V9_ACTUAL_SUPPORT_MASS_CONTROL_ROOT_VERIFICATION_088.json":
        "middle-grid source/support/mass/control prerequisite",
    "F2_FINE_V9_ACTUAL_SUPPORT_MASS_CONTROL_ROOT_VERIFICATION_089.json":
        "fine-grid source/support/mass/control prerequisite",
    "F5_SOURCE_CLIP_CONTINUOUS_MASS_ACTUAL_HARDFAIL_ROOT_VERIFICATION_091.json":
        "F5 source clip with continuous-mass hard-fail boundary",
    "F6_TWO_SENTINEL_THREE_GRID_ACTUAL_SOURCE_BODY_CONTROL_ROOT_VERIFICATION_092.json":
        "F6 two-sentinel source/body/control metadata prerequisite",
    "F3_S2_SOURCE_MATCHED_V2_ACTUAL_SUPPORT_ROOT_VERIFICATION_093.json":
        "F3-S2 source-matched VTK/support observation; CPU delta pending",
    "F2_COARSE_GENERATED_BI4_ACTUAL_WORKER_SNAPSHOT_ROOT_VERIFICATION_094.json":
        "F2 generated BI4 worker snapshot; CPU delta pending",
    "F3_S2_CONTINUOUS_OWNER_ACTUAL_MASS_RECONCILIATION_ROOT_VERIFICATION_096.json":
        "F3-S2 owner/mass reconciliation; CPU delta pending",
}
ENTRY_FILES = tuple(ENTRY_SCOPES)


class CatalogError(RuntimeError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = dict(value)
    body.pop("sha256", None)
    encoded = json.dumps(body, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_json(path: Path | str, role: str, *, max_bytes: int = 8 * 1024 * 1024) -> dict[str, Any]:
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise CatalogError(f"{role} is not a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise CatalogError(f"{role} exceeds metadata size bound: {target}")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise CatalogError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise CatalogError(f"{role} must be a JSON object")
    return value


def _parent_ref(path: Path, role: str) -> dict[str, Any]:
    value = _load_json(path, role)
    return {"role": role, "path": str(path), "sha256": sha256_file(path),
            "schema": value.get("schema"), "status": value.get("status"),
            "scientific_qualification": value.get("scientific_qualification")
            or value.get("qualification") or dict(UNKNOWN),
            "source_read_scope": "small JSON catalog metadata only"}


def _cpu_observation(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    if name in PENDING_CPU:
        actual = value.get("actual_cpu_core_seconds")
        full = value.get("full_systemd_cpu_seconds")
        if not isinstance(actual, (int, float)) or not isinstance(full, (int, float)):
            raise CatalogError(f"{name} is missing actual/full CPU evidence")
        delta = float(full) - float(actual)
        if delta <= 0:
            raise CatalogError(f"{name} does not contain a positive pending CPU delta")
        return {"status": "PENDING_TERMINAL_CPU_DELTA_RECONCILIATION",
                "receipt_cpu_core_seconds": float(actual),
                "systemd_cpu_core_seconds": float(full),
                "pending_delta_cpu_core_seconds": delta,
                "charge_append_performed_by_catalog": False}
    if name.endswith("_078.json") and "TERMINAL_FEE_CLOSED" in name:
        charge = value.get("charge")
        if not isinstance(charge, Mapping) or value.get("reservation_rows_remaining") != 0:
            raise CatalogError("ROOT078 fee checkpoint is not a closed terminal fee")
        return {"status": "CLOSED_TERMINAL_FEE_OBSERVATION",
                "cpu_core_seconds": charge.get("cpu_core_seconds"),
                "full_fee_not_delta": bool(value.get("full_fee_not_delta")),
                "reservation_rows_remaining": 0,
                "charge_id": charge.get("id")}
    return {"status": "NO_CPU_DELTA_RECONCILIATION_DECLARED",
            "charge_append_performed_by_catalog": False}


def build_catalog(*, checkpoint_root: Path | str, parent_catalog_v29: Path | str,
                  parent_catalog_v30: Path | str, output: Path | str) -> dict[str, Any]:
    root = Path(checkpoint_root).expanduser()
    if not root.is_dir():
        raise CatalogError(f"checkpoint root is missing: {root}")
    target = Path(output).expanduser()
    if target.exists():
        raise CatalogError(f"refusing existing catalog output: {target}")
    entries: list[dict[str, Any]] = []
    for name in ENTRY_FILES:
        path = root / name
        value = _load_json(path, f"checkpoint {name}")
        qualification = value.get("scientific_qualification") or value.get("qualification") or dict(UNKNOWN)
        if qualification != UNKNOWN:
            raise CatalogError(f"{name} carries a non-UNKNOWN qualification")
        entry = {
            "id": name.removesuffix(".json"),
            "checkpoint": {"path": str(path), "sha256": sha256_file(path),
                           "status": value.get("status")},
            "scope": ENTRY_SCOPES[name],
            "request_sha256": value.get("request_sha256"),
            "receipt_sha256": value.get("receipt_sha256"),
            "report_sha256": value.get("report_sha256"),
            "cpu": _cpu_observation(name, value),
            "scientific_qualification": dict(UNKNOWN),
            "payload_read_by_catalog_builder": False,
            "source_bytes_rewritten": False,
        }
        entries.append(entry)
    pending = [entry for entry in entries
               if entry["cpu"]["status"] == "PENDING_TERMINAL_CPU_DELTA_RECONCILIATION"]
    pending_total = sum(float(entry["cpu"]["pending_delta_cpu_core_seconds"]) for entry in pending)
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "DEVELOPMENT_FORWARD_INDEX_ONLY",
        "parent_catalogs": [
            _parent_ref(Path(parent_catalog_v29).expanduser(), "V29 qualification catalog"),
            _parent_ref(Path(parent_catalog_v30).expanduser(), "V30 task scope catalog"),
        ],
        "entries": entries,
        "summary": {
            "checkpoint_entry_count": len(entries),
            "pending_terminal_cpu_delta_count": len(pending),
            "pending_terminal_cpu_delta_total_core_seconds": pending_total,
            "current336_audit_cases": 336,
            "native_impact_cases": 118,
            "qualification_catalog_status": "UNKNOWN",
            "task_scope_status": "DEVELOPMENT_ONLY",
        },
        "scientific_boundary": {
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "hidden_test_claim": False,
            "catalog_is_source_index_only": True,
            "old_catalog_bytes_immutable": True,
            "pending_recovery_and_window_closure": True,
        },
        "read_scope": {
            "checkpoint_and_parent_catalog_json_only": True,
            "h5_bi4_raw_result_payload_read": False,
            "rewrites_existing_sidecars": False,
        },
    }
    value["sha256"] = canonical_sha(value)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True,
                  allow_nan=False)
        stream.write("\n")
    return value


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--parent-catalog-v29", type=Path, required=True)
    parser.add_argument("--parent-catalog-v30", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = build_catalog(checkpoint_root=args.checkpoint_root,
                              parent_catalog_v29=args.parent_catalog_v29,
                              parent_catalog_v30=args.parent_catalog_v30,
                              output=args.output)
    except (CatalogError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"status": value["status"], "catalog": str(args.output),
                      "sha256": value["sha256"], "entries": len(value["entries"])},
                     sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
