"""Build a read-only 33-row F3 material matrix gap audit.

The audit reads canonical matrix metadata, immutable job specifications,
terminal runtime receipts, summaries, and heartbeat files only.  It never
opens an active HDF5 trace and does not assign qualification credit.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

try:
    from scripts.core_material import matrix
except ModuleNotFoundError:  # direct ``python scripts/...`` invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from scripts.core_material import matrix


LAB = Path(__file__).resolve().parents[1]
EVIDENCE = LAB / "campaigns/core-v1/material/evidence"
ATTEMPTS = LAB / "campaigns/core-v1/runtime/attempts"
ASSET_AUDIT = EVIDENCE / "f3-native-volume-mls-f3-matrix-asset-audit-v3-20260919.json"


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def attempt_dir(job_id: str) -> Path | None:
    candidates = sorted((ATTEMPTS / job_id).glob("*/"))
    return candidates[-1] if candidates else None


def runtime_observation(job_id: str) -> dict[str, Any]:
    directory = attempt_dir(job_id)
    if directory is None:
        return {"job_id": job_id, "status": "not_submitted"}
    result = directory / "result.json"
    if result.exists():
        receipt = read_json(result)
        summary_path = directory / "trace.summary.json"
        summary = read_json(summary_path) if summary_path.exists() else None
        trace_output = next((item for item in receipt.get("outputs", []) if item.get("path") == "trace.h5"), None)
        return {
            "job_id": job_id,
            "status": "terminal_" + str(receipt.get("execution_status", "unknown")),
            "attempt_dir": str(directory),
            "attempt_spec_sha256": sha256_file(directory / "spec.json") if (directory / "spec.json").exists() else None,
            "receipt_sha256": sha256_file(result),
            "trace_sha256": trace_output.get("sha256") if trace_output else None,
            "summary": {
                "status": summary.get("status") if summary else None,
                "backend": summary.get("binding", {}).get("backend") if summary else None,
                "frames": summary.get("source_window", {}).get("frame_count_committed") if summary else None,
                "unknown_fraction_max": summary.get("unknown_fraction_max") if summary else None,
                "mass_closed": summary.get("mass_closed") if summary else None,
            },
        }
    heartbeat = directory / "heartbeat.json"
    if heartbeat.exists():
        value = read_json(heartbeat)
        return {
            "job_id": job_id,
            "status": "running_no_terminal_receipt",
            "attempt_dir": str(directory),
            "heartbeat": {
                "time": value.get("time"),
                "pid": value.get("child_identity", {}).get("pid"),
                "peak_rss_mib": value.get("peak_rss_mib"),
            },
            "h5_opened": False,
        }
    return {"job_id": job_id, "status": "attempt_without_terminal_receipt"}


# These are the immutable job ids already used by root's diagnostic queue.
# They are observation bindings, not new submissions.
JOB_BY_ROW = {
    0: "ada-f3-native-mls-nominal-coarse-s2-full835-v1",
    1: "ada-f3-native-mls-nominal-coarse-s4-full835-v1",
    2: "ada-f3-native-volume-mls-full835-s2-512-v1",
    3: "ada-f3-native-volume-mls-full835-s4-512-v1",
    4: "ada-f3-native-mls-nominal-fine-s2-full835-v1",
    5: "ada-f3-native-mls-nominal-fine-s4-full835-v1",
    6: "ada-f3-native-mls-high-coarse-s2-full835-v1",
    7: "ada-f3-native-mls-high-coarse-s4-full835-v1",
    8: "ada-f3-native-mls-high-production-s2-full835-v1",
    9: "ada-f3-native-mls-high-production-s4-full835-v1",
    10: "ada-f3-native-mls-high-fine-s2-full835-v1",
    11: "ada-f3-native-mls-high-fine-s4-full835-v1",
    12: "ada-f3-native-mls-low-production-s2-full835-v1",
    13: "ada-f3-native-mls-low-production-s4-full835-v1",
    14: "ada-f3-native-mls-low-fine-s2-full835-v1",
    15: "ada-f3-native-mls-low-fine-s4-full835-v1",
    24: "ada-f3-native-mls-dense-native002-production-s4-full835-v2",
    25: "ada-f3-native-mls-dense-matched010-production-s4-full835-v2",
    # Row 30 has a related v3 quadrature run, but the canonical row remains
    # an s4/native current-frame seed-density cell.
    30: "ada-f3-native-mls-temporal-v3-nominal-production-seeds4096-full835-s2-v1",
}


def build_report() -> dict[str, Any]:
    asset_audit = read_json(ASSET_AUDIT)
    rows = matrix("F3")
    old_rows = {int(row["matrix_index"]): row for row in asset_audit["matrix_rows"]}
    output_rows = []
    for row in rows:
        index = int(row["matrix_index"])
        old = old_rows.get(index, {})
        job_id = JOB_BY_ROW.get(index)
        observation = runtime_observation(job_id) if job_id else None
        source_status = old.get("status")
        if source_status in {"missing_exact_control_asset", "missing_native_dense_control_asset"}:
            status = "blocked_missing_registered_source"
        elif observation is None:
            status = "source_available_not_submitted"
        elif observation["status"] == "running_no_terminal_receipt":
            status = "running_no_terminal_receipt"
        elif observation["status"] == "terminal_succeeded":
            status = "terminal_diagnostic_observed"
        else:
            status = observation["status"]
        formal_row_complete = bool(
            status == "terminal_diagnostic_observed"
            and index not in {25, 30}
            and row["matrix_stage"] != "cadence"
        )
        if index == 25 and status == "terminal_diagnostic_observed":
            status = "terminal_matched_decimation_diagnostic_only"
            formal_row_complete = False
        if index == 30:
            status = "related_v3_s2_diagnostic_running_not_canonical_s4_row"
            formal_row_complete = False
        if index == 24 and status == "running_no_terminal_receipt":
            status = "native_dense_material_postprocess_running"
        output_rows.append({
            **row,
            "status": status,
            "source_asset_status_from_registered_audit": source_status,
            "blocking_assets": old.get("blocking_assets", []),
            "observed_job": observation,
            "formal_row_complete": formal_row_complete,
            "qualification_credit": "none; all rows remain diagnostic until an independent acceptance record",
        })

    return {
        "schema": "core.material.f3.native_volume_mls.matrix_gap_audit.v1",
        "status": "diagnostic_asset_and_execution_gap_audit",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "qualification_claim": "none; this report does not promote any row to T2",
        "side_effects": {"gpu_started": False, "ledger_written": False, "active_h5_opened": False},
        "matrix_binding": {
            "definition": "scripts/core_material.py matrix(\"F3\")",
            "definition_sha256": sha256_file(LAB / "scripts/core_material.py"),
            "row_count": len(rows),
            "canonical_row_order": "0-23 resolution_substep; 24-27 cadence; 28-32 seed_density",
            "asset_audit_path": str(ASSET_AUDIT.resolve()),
            "asset_audit_sha256": sha256_file(ASSET_AUDIT),
        },
        "implementation_boundary": {
            "v1_runner_snapshot": "81ba36735f05ddf7b5a1f1568ed91ec3c861e84b1617b35f26da74648f99efe1",
            "v1_runner_sha256": "e1c5fc39e73781d386c7da2874c1749b5223c8209eaf8f25bb4453346df51ff9",
            "v3_4096_jobs": [
                "ada-f3-native-mls-temporal-v3-nominal-production-seeds4096-full835-s2-v1",
                "ada-f3-native-mls-temporal-v3-nominal-fine-seeds4096-full835-s2-v1",
            ],
            "v3_policy": "related quadrature/spatial diagnostics only; they do not silently fill canonical s4 seed-density rows or grant qualification",
        },
        "rows": output_rows,
        "gap_groups": [
            {
                "kind": "exact_control_source_missing",
                "rows": [16, 17, 18, 19, 20, 21, 22, 23, 29, 31],
                "dependency": "root-owned exact amp=.95/.1.05 prepared/H5/XML/control assets and hashes",
                "qualification_claim": "none",
            },
            {
                "kind": "native_dense_hard_endpoint_source_missing",
                "rows": [26, 27],
                "dependency": "root-owned production dp=.0075 amp=1.1 native .002 CFD source and its frame map",
                "qualification_claim": "none",
            },
            {
                "kind": "native_dense_center_postprocess_pending",
                "rows": [24],
                "dependency": "currently running native .002 material trace; collect terminal receipt before reading its H5",
                "qualification_claim": "none",
            },
            {
                "kind": "seed_density_formal_rows_not_run",
                "rows": [28, 30, 32],
                "dependency": "production amp=.9/1.0/1.1 native .01, current-frame MLS, s4, 4096 seeds; row30's v3 s2 run is not equivalent",
                "qualification_claim": "none",
            },
            {
                "kind": "matched_decimation_observed_but_not_native_dense_pair_complete",
                "rows": [25],
                "dependency": "row25 has a terminal v2 matched-decimation diagnostic; retain paired native-dense result and source map before any matrix interpretation",
                "qualification_claim": "none",
            },
        ],
        "completed_or_observed_rows": {
            "terminal_v1_512_diagnostics": list(range(16)),
            "terminal_matched_decimation_diagnostic": [25],
            "active_or_unresolved": [24, 30],
            "blocked_source": [16, 17, 18, 19, 20, 21, 22, 23, 26, 27, 29, 31],
            "source_available_not_submitted": [28, 32],
        },
        "next_minimal_cpu_batch_after_source_resolution": {
            "jobs": [
                {"rows": [28, 30, 32], "seeds": 4096, "substeps": 4, "cadence": "native .01", "backend": "f3_native_volume_mls_current_frame_rk4_v1", "qualification_claim": "none"},
            ],
            "do_not_duplicate": ["v3 4096 s2 jobs currently active", "completed v1 512 rows 0-15", "matched-decimation row25"],
            "resource_basis": "use measured v1 4096 s2 profile only as a bound; obtain one s4 profile before launching all three if scheduler requires",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_report()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(args.output.resolve()), "rows": len(report["rows"]), "status": report["status"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
