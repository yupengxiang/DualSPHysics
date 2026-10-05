#!/usr/bin/env python3
"""Read-only compatibility probe for the proposed F3 native NVMe staging contract.

This probe reads only the current runtime source text.  It never opens campaign
outputs, ledgers, arrays, leases, or solver inputs, and it never starts a job.
A blocked result is deliberate until the shared runtime owns both storage roots
and separates native completion from the later CPU archive.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
CONTRACT_PATH = HERE / "native-staging-contract.json"
DEFAULT_RUNTIME = Path(
    "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/"
    """lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"""
)

# These are source-level facts that must change together before staging can be
# enabled.  The probe intentionally uses text anchors, never imports runtime
# code and never invokes a runtime entry point.
REQUIRED_ANCHORS = {
    "attempt_output_is_home_root": "output = data_root / 'families' / attempt",
    "attempt_root_substitution_exists": "arg.replace('{attempt_root}', str(output))",
    "home_tree_storage_guard_exists": "tree_bytes(output)",
    "home_free_floor_guard_exists": "live_limits.get('storage_policy')",
    "native_wait_exists": "proc.wait()",
    "native_status_from_child_exists": "status='completed' if proc.returncode == 0 and reason is None else 'failed'",
    "home_receipt_bytes_exists": "bytes=tree_bytes(output)",
    "conversion_kind_exists": "'conversion'",
}
FORBIDDEN_OR_MISSING = {
    "native_archive_kind_missing": "native_archive",
    "native_stage_root_missing": "native_stage_root",
    "archive_hook_missing": "native_archive_request_path",
    "separate_native_returncode_missing": "native_returncode",
}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--runtime",
        type=Path,
        default=DEFAULT_RUNTIME,
        help="runtime source path (read-only; defaults to the reviewed integration WT)",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    runtime_path = args.runtime.expanduser().resolve()
    result = {
        "schema": "ds02.f3.native-nvme-staging-diagnostic.v1",
        "status": "blocked",
        "source_only": True,
        "jobs_started": False,
        "arrays_read": False,
        "shared_state_modified": False,
        "runtime_path": str(runtime_path),
        "runtime_exists": runtime_path.is_file(),
        "runtime_sha256": None,
        "contract_path": str(CONTRACT_PATH),
        "observed": {},
        "missing_required_support": [],
        "preserved_blockers": [
            "runtime must own and account for a separate native_stage_root",
            "Home and NVMe floors must be reserved and monitored together",
            "official native exit must be recorded separately from CPU archive exit",
            "a completed native receipt must gate a later archive request",
        ],
        "decision": "keep native output on the existing Home attempt root until a reviewed shared-runtime extension lands",
    }

    if not runtime_path.is_file():
        result["missing_required_support"] = ["runtime source is unavailable for a read-only probe"]
    else:
        source = runtime_path.read_bytes()
        text = source.decode("utf-8")
        result["runtime_sha256"] = sha256_bytes(source)
        result["observed"] = {
            name: anchor in text for name, anchor in REQUIRED_ANCHORS.items()
        }
        result["missing_required_support"] = [
            name for name, anchor in FORBIDDEN_OR_MISSING.items() if anchor not in text
        ]
        # Current runtime source intentionally triggers every hard staging gap;
        # this check keeps the result blocked even if one textual anchor moves.
        if not result["missing_required_support"]:
            result["missing_required_support"] = [
                "no missing staging anchors detected; human review is still required before enablement"
            ]

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(f"status: {result['status']}")
        print(f"runtime: {result['runtime_path']}")
        print(f"runtime_sha256: {result['runtime_sha256']}")
        print("missing_required_support:")
        for item in result["missing_required_support"]:
            print(f"  - {item}")
        print(f"decision: {result['decision']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
