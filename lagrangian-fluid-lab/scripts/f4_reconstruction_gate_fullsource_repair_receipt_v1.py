#!/usr/bin/env python3
"""Bind a completed F4 full-source repair trace without granting credit.

The receipt is deliberately fail-closed: it accepts only a completed native
source trace with the fixed 512-seed denominator, records the observed
right-censoring/unknown result, and never mutates the Core registry, ledger, or
denominator.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any


SCHEMA = "core.material.f4.reconstruction_gate_fullsource_repair_receipt.v1"
EXPECTED_SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"
EXPECTED_FRAMES = 1086
EXPECTED_FINAL_FRAME = EXPECTED_FRAMES - 1
EXPECTED_SEEDS = 512


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def file_ref(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "role": role, "sha256": sha256(path), "bytes": path.stat().st_size}


def build_receipt(result_path: Path, output_path: Path) -> dict[str, Any]:
    result_path = Path(result_path).resolve()
    output_path = Path(output_path).resolve()
    result = read_json(result_path)
    binding = result["binding"]
    source = result["by_source"]
    if len(source) != 1:
        raise ValueError("receipt requires exactly one F4 source row")
    row = source[0]
    checks = {
        "completed_trace": result["status"] == "completed",
        "native_frame_count": result["native_frame_count"] == EXPECTED_FRAMES,
        "terminal_frame_committed": result["committed_frame"] == EXPECTED_FINAL_FRAME,
        "fixed_seed_denominator": bool(binding["initial_sha256"] and binding["tracer_id_sha256"]),
        "source_hash_bound": binding["source_sha256"] == EXPECTED_SOURCE_SHA256,
        "mass_closed": bool(result["mass_closed"]),
        "unknown_gate_rejected": result["unknown_gate_pass"] is False,
        "event_window_rejected": result["event_window_complete"] is False,
        "zero_qualification_claim": result["qualification_claim"] == "none",
        "right_censored_status": result["event_window_status"] == "right_censored_or_unresolved",
    }
    if not all(checks.values()):
        failed = [name for name, passed in checks.items() if not passed]
        raise ValueError(f"receipt precondition failed: {failed}")
    artifact_dir = result_path.parent
    trace_path = artifact_dir / "candidate-full.h5"
    checkpoint_path = artifact_dir / "candidate-full.h5.checkpoint.json"
    receipt = {
        "schema": SCHEMA,
        "record_id": "f4-tallwall120-zoh-fullsource-repair-20260922",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": "completed_full_source_zero_credit_right_censored",
        "qualification_claim": "none",
        "T2_macro": False,
        "T2_path": False,
        "scope_id": result["scope_id"],
        "candidate": {
            "candidate_id": binding["repair_candidate_id"],
            "revision_id": binding["revision_id"],
            "temporal_interpolation": binding["temporal_interpolation"],
            "neighbour_variant": binding["neighbour_variant"],
            "neighbours": binding["neighbours"],
            "seeds": EXPECTED_SEEDS,
            "substeps": binding["substeps"],
        },
        "source_window": {
            "source_sha256": binding["source_sha256"],
            "native_frame_count": result["native_frame_count"],
            "committed_frame": result["committed_frame"],
            "committed_time_s": result["committed_time_s"],
            "event_window_semantics_unchanged": True,
        },
        "observed": {
            "contact_fraction": row["contact_fraction"],
            "unknown_fraction": row["unknown_fraction"],
            "unknown_fraction_max": row["unknown_fraction_max"],
            "reliable_path_coverage": row["reliable_path_coverage"],
            "mass_closed": result["mass_closed"],
            "event_window_complete": result["event_window_complete"],
            "event_window_status": result["event_window_status"],
            "qualification_blockers": [
                "unknown_fraction_exceeds_fixed_limit",
                "event_window_right_censored_or_unresolved",
                "no_contact_events_observed",
            ],
        },
        "acceptance_checks": checks,
        "artifacts": {
            "result": file_ref(result_path, "completed trace result"),
            "trace": file_ref(trace_path, "completed trace H5"),
            "checkpoint_manifest": file_ref(checkpoint_path, "append-only checkpoint manifest"),
        },
        "execution_constraints": {
            "source_read_only": True,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "denominator_mutation": 0,
        },
        "resource_accounting": {
            "elapsed_seconds": result["elapsed_seconds"],
            "max_rss_kib": result["max_rss_kib"],
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    receipt = build_receipt(args.result, args.output)
    print(json.dumps({"status": receipt["status"], "qualification_claim": receipt["qualification_claim"], "output": str(args.output.resolve())}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
