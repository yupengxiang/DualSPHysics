#!/usr/bin/env python3
"""Bind the fourteen-sentinel terminal evidence range to actual small proofs.

The prior readiness card contains 41 actual proof references, but a status card
alone is not evidence.  This additive index reopens only those declared JSON
proofs under a 10 MiB stable-read cap, verifies each declared SHA, and records
what can be reused, what additional parent work is required, and what remains
scientifically unidentified.  It never reads native/VTK/BI4/H5 payloads and
never turns an actual diagnostic into QI/QN/QE credit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
READINESS_V7 = HERE / "stage2_fourteen_actual_evidence_readiness_v7.json"
SCHEMA = "ds02.stage2.fourteen-scientific-terminal-readiness.v2"
CAP = 10 * 1024 * 1024
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}

# ROOT362 is a completed metadata-recovery parent.  It reopened no native
# payload, but it is still a distinct F1-S2 integration/output-scope result
# and must be joined as actual evidence rather than represented by the
# source-only ROOT279 package.
ADDITIONAL_EVIDENCE: dict[str, list[dict[str, Any]]] = {
    "F1-S2": [{
        "kind": "proof_json",
        "claim_scope": "ROOT362 actual ROOT279 compact/scalar recovery; native reread zero; world orientation and scientific Q remain unknown",
        "path": "/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints/ROOT279_NATIVE_SCALAR_RECOVERY_ACTUAL_ROOT_VERIFICATION_362.json",
        "sha256": "e14568ed364fcee9540665db05387d315804e0cb84f06e0ac702e9ac6c5f4a0f",
        "bytes": 24838,
        "source_metadata_only": True,
    }]
}


class ReadinessFailure(RuntimeError):
    pass


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino), "bytes": int(value.st_size),
            "mtime_ns": int(value.st_mtime_ns), "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _small_json(path: Path | str, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().absolute()
    if path.is_symlink() or not path.is_file():
        raise ReadinessFailure(f"{label} is not a regular file: {path}")
    before = _stat(path)
    if before["bytes"] > CAP:
        raise ReadinessFailure(f"{label} exceeds 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after or len(raw) != before["bytes"]:
        raise ReadinessFailure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ReadinessFailure(f"{label} is not bounded JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ReadinessFailure(f"{label} is not a JSON object: {path}")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": before["bytes"],
                    "stat_before": before, "stat_after": after, "read_scope": "bounded_small_proof_json"}


def _evidence(item: Any, label: str) -> dict[str, Any]:
    if not isinstance(item, dict) or not isinstance(item.get("path"), str):
        return {"status": "UNBOUND", "reason": "evidence has no explicit path", "declared": item}
    path = Path(item["path"]).expanduser().absolute()
    declared = item.get("sha256")
    base = {"kind": item.get("kind"), "claim_scope": item.get("claim_scope"),
            "path": str(path), "declared_sha256": declared, "declared_bytes": item.get("bytes"),
            "source_metadata_only": item.get("source_metadata_only") is True}
    if not path.is_file() or path.is_symlink():
        base.update({"status": "MISSING", "reason": "declared proof path is unavailable"})
        return base
    try:
        proof, record = _small_json(path, label)
    except ReadinessFailure as exc:
        base.update({"status": "UNREADABLE", "reason": str(exc)})
        return base
    base.update({"actual_sha256": record["sha256"], "actual_bytes": record["bytes"], "stat": record["stat_after"],
                 "proof_schema": proof.get("schema"), "proof_status": proof.get("status")})
    if not isinstance(declared, str) or declared.lower() != record["sha256"].lower():
        base.update({"status": "HASH_MISMATCH", "reason": "declared SHA differs from stable proof bytes"})
    elif isinstance(item.get("bytes"), int) and int(item["bytes"]) != record["bytes"]:
        base.update({"status": "BYTE_MISMATCH", "reason": "declared byte count differs from stable proof bytes"})
    else:
        base["status"] = "SOURCE_BOUND_ACTUAL_SMALL_PROOF"
    # Keep only scalar top-level proof metadata. Never copy a nested payload,
    # per-particle array, or large report into this index.
    base["proof_scalar_metadata"] = {key: proof[key] for key in (
        "sentinel_id", "family_id", "grid_label", "row_key", "case_id", "attempt_id",
        "scientific_credit", "returncode", "frame_count", "final_time_s", "native_mass_fluid",
        "native_mass_bound", "initial_fluid_count", "final_fluid_count", "actual_selected_native_count",
        "actual_native_selected_read_after_reservation", "native_payload_reopened_by_recovery",
        "world_orientation", "scientific_Q_credit", "status")
        if key in proof and isinstance(proof[key], (str, int, float, bool, type(None)))}
    return base


def build(output: Path | None = None) -> dict[str, Any]:
    readiness, source_record = _small_json(READINESS_V7, "fourteen readiness v7")
    rows = readiness.get("sentinels")
    if not isinstance(rows, list) or len(rows) != 14:
        raise ReadinessFailure("readiness v7 does not contain exactly fourteen sentinels")
    sentinels: list[dict[str, Any]] = []
    total = bound = missing = mismatch = 0
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("sentinel_id"), str):
            raise ReadinessFailure("readiness v7 has malformed sentinel row")
        evidence = row.get("actual_evidence")
        if not isinstance(evidence, list):
            raise ReadinessFailure(f"{row.get('sentinel_id')} lacks actual_evidence list")
        checked = [_evidence(item, f"{row['sentinel_id']} proof") for item in evidence]
        addenda = [_evidence(item, f"{row['sentinel_id']} additive actual proof")
                   for item in ADDITIONAL_EVIDENCE.get(row["sentinel_id"], [])]
        checked.extend(addenda)
        total += len(checked)
        bound_here = sum(item.get("status") == "SOURCE_BOUND_ACTUAL_SMALL_PROOF" for item in checked)
        missing_here = sum(item.get("status") in {"MISSING", "UNREADABLE", "UNBOUND"} for item in checked)
        mismatch_here = sum(item.get("status") in {"HASH_MISMATCH", "BYTE_MISMATCH"} for item in checked)
        bound += bound_here; missing += missing_here; mismatch += mismatch_here
        reuse = ("REUSE_BOUND_ACTUAL_DIAGNOSTIC_PROOFS" if not missing_here and not mismatch_here
                 else "PARTIAL_ACTUAL_EVIDENCE_WITH_UNBOUND_OR_CHANGED_PROOFS")
        terminal = row.get("terminal_state") if isinstance(row.get("terminal_state"), dict) else {}
        next_parent = row.get("next_parent") if isinstance(row.get("next_parent"), dict) else {}
        sentinels.append({
            "sentinel_id": row["sentinel_id"], "family_id": row.get("family_id"),
            "physical_case_id": row.get("physical_case_id"), "terminal_state": terminal,
            "actual_evidence_count": len(checked), "bound_actual_small_proof_count": bound_here,
            "evidence": checked, "reuse_scope": reuse,
            "actual_scope_updates": ([{
                "status": "ACTUAL_METADATA_RECOVERY_SCOPE_BOUND",
                "source_evidence": [item["path"] for item in addenda],
                "claim": "ROOT362 compact/scalar recovery is usable for the recorded F1-S2 integration/output diagnostic scope; native reread, world orientation, integration error and scientific Q remain unknown.",
                "scientific_credit": 0,
            }] if addenda else []),
            "next_scientific_action": row.get("next_scientific_action"),
            "minimum_new_evidence": row.get("minimum_new_evidence"),
            "next_parent": next_parent, "unknown_impact": row.get("unknown_impact"),
            "recovery_if_gate_fails": row.get("recovery_if_gate_fails"),
            "scientific_qualification": dict(UNKNOWN), "production_credit": 0,
            "solver_launch_by_builder": False,
        })
    result = {
        "schema": SCHEMA,
        "status": "ACTUAL_SMALL_PROOF_BOUND_TERMINAL_SCOPE_NO_SCIENTIFIC_QUALIFICATION",
        "scientific_credit": 0, "scientific_qualification": dict(UNKNOWN), "sentinel_count": 14,
        "evidence_totals": {"declared_proofs": total, "source_bound_actual_small_proofs": bound,
                             "missing_or_unreadable": missing, "sha_or_byte_mismatch": mismatch},
        "sentinels": sentinels, "source_inputs": {
            "readiness_v7": source_record,
            "additional_actual_evidence": [path for row in sentinels
                                            for update in row.get("actual_scope_updates", [])
                                            for path in update.get("source_evidence", [])],
        },
        "frozen_policy": {
            "position_fraction_of_registered_L": 0.02,
            "velocity_and_ke_fraction_of_registered_nonzero_scale": 0.05,
            "event_time_fraction_of_registered_T": 0.01,
            "time_and_output_each_fraction_of_task_budget": 0.25,
            "whole_initial_fluid_mass_target_pct": 1.0,
            "whole_initial_fluid_mass_hard_upper_pct": 2.0,
            "tolerances_are_registration_gates_not_measured_errors": True,
        },
        "read_scope": {"proof_json_cap_bytes": CAP, "production_native_payload": False,
                       "production_vtk_bi4_h5": False, "large_report_read": False,
                       "solver_gencase_gpu_launch": False, "neighbor_grid_truth": False,
                       "interpolation": False},
        "interpretation": {
            "reusable_results": "Only the exact small proof claims under evidence[].claim_scope; actual diagnostics retain their original scope.",
            "additional_computation": "Each row's next_parent/minimum_new_evidence is still required before its registered study can be admitted.",
            "terminal_gap": "A row with a hard_fail_or_blocker is a scoped diagnostic/blocked branch, not a scientific pass; a missing proof is an evidence gap, not permission to copy a neighboring sentinel.",
            "quality_axes": "QI/QN/QE remain UNKNOWN for all fourteen rows.",
        },
    }
    if output is not None:
        output = Path(output).expanduser().absolute()
        if output.exists() or output.is_symlink():
            raise ReadinessFailure(f"refusing overwrite: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def _self_test() -> None:
    result = build()
    assert result["sentinel_count"] == 14
    assert result["evidence_totals"]["declared_proofs"] == 42
    assert result["evidence_totals"]["source_bound_actual_small_proofs"] == 42
    f1s2 = next(row for row in result["sentinels"] if row["sentinel_id"] == "F1-S2")
    assert f1s2["actual_scope_updates"]
    assert "ROOT279_NATIVE_SCALAR_RECOVERY_ACTUAL_ROOT_VERIFICATION_362.json" in f1s2["actual_scope_updates"][0]["source_evidence"][0]
    assert all(row["scientific_qualification"] == UNKNOWN for row in result["sentinels"])
    assert all(row["solver_launch_by_builder"] is False for row in result["sentinels"])
    print("PASS_FOURTEEN_ACTUAL_SMALL_PROOF_TERMINAL_SCOPE_V2_NO_Q_CREDIT")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        result = build(args.output)
        if args.self_test:
            assert result["sentinel_count"] == 14
            print("PASS_FOURTEEN_ACTUAL_SMALL_PROOF_TERMINAL_SCOPE_V2_NO_Q_CREDIT")
        else:
            print(json.dumps({"status": result["status"], "output": str(args.output.absolute()) if args.output else None,
                              "sentinel_count": result["sentinel_count"], "declared_proofs": result["evidence_totals"]["declared_proofs"],
                              "bound_proofs": result["evidence_totals"]["source_bound_actual_small_proofs"], "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ReadinessFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"FAILED_FOURTEEN_TERMINAL_READINESS_V2: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
