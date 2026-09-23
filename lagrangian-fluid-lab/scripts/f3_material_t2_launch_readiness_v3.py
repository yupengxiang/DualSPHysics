#!/usr/bin/env python3
"""F3 readiness v3 incorporating the terminal JSON-only row30 r003 audit."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts import f3_material_t2_launch_readiness_v2 as v2
from scripts import f3_row30_r003_terminal_audit_v1 as r003_audit


SCHEMA = "core.material.f3.t2.launch_readiness.v3"
DEFAULT_OUTPUT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-t2-launch-readiness-v3-20260923/receipt.json"
)
R003_TERMINAL_RECEIPT = Path(
    "campaigns/core-v1/material/evidence/"
    "f3-material-row30-r003-terminal-audit-v1/receipt.json"
)


def _sha256(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 << 20), b""):
            digest.update(block)
            size += len(block)
    return size, digest.hexdigest()


def _bind(root: Path, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else root / path
    if not resolved.is_file():
        raise FileNotFoundError(resolved)
    size, digest = _sha256(resolved)
    try:
        shown = str(resolved.resolve().relative_to(root.resolve()))
    except ValueError:
        shown = str(resolved.resolve())
    return {"path": shown, "bytes": size, "sha256": digest}


def _load_json(root: Path, path: Path) -> dict[str, Any]:
    resolved = path if path.is_absolute() else root / path
    value = json.loads(resolved.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {resolved}")
    return value


def _counter(rows: list[dict[str, Any]]) -> dict[str, int]:
    return dict(sorted(Counter(row["evidence_class"] for row in rows).items()))


def build_audit(lab_root: str | Path) -> dict[str, Any]:
    root = Path(lab_root).resolve()
    result = v2.build_audit(root)
    persisted = _load_json(root, R003_TERMINAL_RECEIPT)
    terminal = r003_audit.build_audit(root)
    if persisted != terminal:
        raise ValueError("persisted r003 terminal receipt does not match its JSON-only source evidence")
    if terminal.get("schema") != r003_audit.SCHEMA:
        raise ValueError("r003 terminal receipt schema mismatch")
    if terminal.get("status") != "completed_scientific_gate_failure":
        raise ValueError("r003 terminal receipt no longer records the expected scientific gate failure")

    result["schema"] = SCHEMA
    rows = result["plan_33_logical_configurations"]["rows"]
    row30 = rows[30]
    gates = terminal["fixed_scientific_gates"]
    row30.update(
        {
            "historical_status_precedes_r003": True,
            "evidence_class": "terminal_diagnostic_scientific_gate_failure",
            "terminal_attempt_id": terminal["attempt_id"],
            "terminal_execution_status": terminal["execution"]["status"],
            "terminal_full_window_complete": terminal["execution"]["full_native_window_complete"],
            "per_source_unknown_gate_pass": gates["per_source_unknown_gate_pass"],
            "row_acceptance": gates["row_acceptance"],
            "next_gap": (
                "the single authorized r003 attempt completed the full window but exceeded the frozen "
                "per-source unknown-mass gate; no independent matched 512-versus-4096 CDF comparison "
                "is bound, so retain this terminal failure and do not retry the same scope"
            ),
        }
    )
    result["plan_33_logical_configurations"]["availability_counts"] = _counter(rows)
    diagnostics = result["plan_15_diagnostics"]["rows"]
    result["plan_15_diagnostics"]["availability_counts"] = _counter(diagnostics)

    result["row30_r003_terminal_assessment"] = {
        "receipt_path": str(R003_TERMINAL_RECEIPT),
        "execution_succeeded": terminal["execution"]["status"] == "succeeded",
        "full_native_window_complete": terminal["execution"]["full_native_window_complete"],
        "source_unknown_gate_pass": gates["per_source_unknown_gate_pass"],
        "maximum_observed_unknown_fraction": gates["maximum_observed_unknown_fraction"],
        "maximum_allowed_unknown_fraction": gates["maximum_per_source_unknown_fraction"],
        "independent_cdf_comparison_available": gates["cdf_comparison_available"],
        "row_acceptance": gates["row_acceptance"],
        "single_attempt_consumed": terminal["authorization_boundary"]["single_authorized_attempt_consumed"],
        "automatic_retry_authorized": False,
        "T2_credit": 0,
        "input_bindings": terminal["input_bindings"],
    }
    result["next_executable_step"] = {
        "status": "row30_r003_closed_no_same_scope_retry",
        "candidate_matrix_row": 30,
        "required_action": (
            "retain the terminal scientific-gate failure; continue only with independent, separately "
            "authorized matrix/resource work; any future row30 attempt needs a frozen remedy and new authorization"
        ),
        "same_scope_retry_authorized": False,
        "T2_credit": "none",
    }
    result["audit_status"] = "matrix_v2_integrated_r003_terminal_failure_no_t2_credit"
    result["hard_boundaries"].update(
        {
            "r003_terminal_failure_bound": True,
            "same_scope_row30_retry_authorized": False,
            "T2_credit_from_r003": 0,
            "hdf5_or_npz_opened": False,
        }
    )

    bindings = dict(result["input_bindings"])
    bindings["r003_terminal_receipt"] = _bind(root, R003_TERMINAL_RECEIPT)
    bindings["readiness_adapter_v3"] = _bind(root, Path(__file__).resolve())
    for name, binding in terminal["input_bindings"].items():
        bindings[f"r003_{name}"] = binding
    result["input_bindings"] = bindings
    result["scope"].update(
        {
            "npz_opened": False,
            "trace_or_checkpoint_payload_opened": False,
            "runtime_process_state_observed": False,
        }
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-root", type=Path, default=REPOSITORY_ROOT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)
    root = args.lab_root.resolve()
    output = args.output if args.output.is_absolute() else root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(build_audit(root), indent=2, sort_keys=True, allow_nan=False) + "\n"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    print(json.dumps({"schema": SCHEMA, "audit_status": json.loads(encoded)["audit_status"], "output": str(output.resolve())}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
