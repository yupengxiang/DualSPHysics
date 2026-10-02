#!/usr/bin/env python3
"""Additive PartVTK requests for the phase-aligned F6 finer mother.

The v3 request generator listed ``__Actual.vtk`` as an input.  GenCase's
actual ``-save:all`` output has ``_Bound.vtk`` instead, so the shared runner
rejected that request during input validation before PartVTK started.  This
wrapper preserves the v3 request and emits a new ``_PARTVTK_002`` request
version using only the files that exist in each immutable GenCase attempt.
It does not regenerate GenCase data, alter the physical mother, or launch a
solver.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
V3 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125_v3.py")
SPEC = importlib.util.spec_from_file_location("f6_dp020_dp0125_v3_for_partvtk_v2", V3)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load phase-aligned v3 generator: {V3}")
BASE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BASE)

MODULE = BASE.MODULE
ORIGINAL_ROOT = MODULE.FAMILY_ROOT
MODULE.FAMILY_ROOT = ORIGINAL_ROOT / "partvtk_002"
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.dp020_dp0125.partvtk_002.v1"

_BASE_INPUT_FILES = MODULE._request_input_files
_BASE_PARTVTK_REQUESTS = MODULE.make_partvtk_requests


def _request_input_files_existing(*paths: Path) -> list[str]:
    values = [value for value in _BASE_INPUT_FILES(*paths) if Path(value).is_file()]
    for path in (V3, SCRIPT):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return list(dict.fromkeys(values))


MODULE._request_input_files = _request_input_files_existing


def _native_prefix(request: dict[str, Any]) -> Path:
    command = request.get("command", [])
    try:
        bi4 = Path(command[command.index("-filedata") + 1])
    except (ValueError, IndexError, TypeError) as exc:
        raise ValueError("PartVTK request lacks -filedata native input") from exc
    if bi4.suffix.lower() != ".bi4":
        raise ValueError(f"unexpected native input: {bi4}")
    return bi4.with_suffix("")


def make_partvtk_requests() -> dict[str, Any]:
    """Create version-002 requests while retaining the v3 failed request."""

    source_manifest_path = ORIGINAL_ROOT / "manifest.json"
    source_manifest = MODULE.read_json(source_manifest_path)
    MODULE.FAMILY_ROOT.mkdir(parents=True, exist_ok=True)
    MODULE.write_json(MODULE.FAMILY_ROOT / "manifest.json", source_manifest)

    # The imported builder writes an intermediate manifest and four _001
    # requests under this fresh additive directory.  Preserve those bytes as
    # an explicit lineage artifact before writing the corrected version.
    intermediate = _BASE_PARTVTK_REQUESTS()
    intermediate_manifest_path = MODULE.FAMILY_ROOT / "partvtk_request_manifest.json"
    intermediate_manifest_copy = MODULE.FAMILY_ROOT / "partvtk_request_manifest_base_001.json"
    if intermediate_manifest_path.is_file():
        intermediate_manifest_copy.write_bytes(intermediate_manifest_path.read_bytes())
        intermediate_manifest_copy_sha = MODULE.sha256(intermediate_manifest_copy)
    else:
        intermediate_manifest_copy_sha = None

    rows: list[dict[str, Any]] = []
    for row in intermediate["requests"]:
        old_path = Path(row["request"]["path"])
        request = MODULE.read_json(old_path)
        cid = str(request["case_id"])
        old_attempt = str(request["attempt_id"])
        new_attempt = old_attempt.replace("_PARTVTK_001", "_PARTVTK_002")
        if new_attempt == old_attempt:
            raise ValueError(f"unexpected PartVTK attempt identity: {old_attempt}")

        prefix = _native_prefix(request)
        actual_outputs = [
            prefix.with_name(prefix.name + suffix)
            for suffix in ("_All.vtk", "_Bound.vtk", "_Fluid.vtk", "_MkCells.vtk", "__Dp.vtk")
        ]
        missing = [str(path) for path in actual_outputs if not path.is_file()]
        if missing:
            raise FileNotFoundError(f"actual GenCase audit files missing for {cid}: {missing}")

        input_files = [value for value in request["input_files"] if Path(value).is_file()]
        for path in actual_outputs:
            value = str(path.resolve())
            if value not in input_files:
                input_files.append(value)
        for path in (V3, SCRIPT):
            value = str(path.resolve())
            if value not in input_files:
                input_files.append(value)

        request["attempt_id"] = new_attempt
        request["generator_version"] = MODULE.VERSION
        request["input_files"] = list(dict.fromkeys(input_files))
        request["max_wall_seconds"] = 900
        # A 2.62M-particle all-typed CSV plus the stats sidecar is materially
        # larger than the inherited 256 MiB estimate.  This is a bounded CPU
        # audit reservation, not a solver/storage approval.
        request["estimated_storage_bytes"] = 2 * 1024**3
        request["purpose"] = "official PartVTK phase-aligned initial typed-state audit; corrected native file binding; no solver/GPU"
        request["lineage"] = {
            "source_v3_manifest": str((ORIGINAL_ROOT / "partvtk_request_manifest.json").resolve()),
            "source_v3_manifest_sha256": MODULE.sha256(ORIGINAL_ROOT / "partvtk_request_manifest.json"),
            "supersedes_request": str(old_path.resolve()),
            "supersedes_request_sha256": MODULE.sha256(old_path),
            "input_correction": "GenCase -save:all emits _Bound.vtk; no __Actual.vtk was present",
            "actual_native_audit_files": [str(path.resolve()) for path in actual_outputs],
            "gencase_receipt_immutable": True,
        }
        new_path = MODULE.FAMILY_ROOT / "execution_requests" / f"{cid}_partvtk_002.json"
        MODULE.write_json(new_path, request)
        rows.append(
            {
                "case_id": cid,
                "request": {"path": str(new_path.resolve()), "sha256": MODULE.sha256(new_path), "attempt_id": new_attempt},
                "gencase_receipt": request["gencase_receipt"],
                "output_csv": str((MODULE._attempt_root(cid, new_attempt) / f"{cid}_initial_all.csv").resolve()),
                "output_stats": str((MODULE._attempt_root(cid, new_attempt) / f"{cid}_initial_stats_stats.csv").resolve()),
            }
        )

    result = {
        "schema": "ds-data-02.f6.rigid_contract_003.dp020-dp0125.partvtk_requests.v2",
        "created_at": MODULE.now(),
        "status": "ready_for_shared_runtime_partvtk",
        "requests": rows,
        "supersedes_manifest": str((ORIGINAL_ROOT / "partvtk_request_manifest.json").resolve()),
        "supersedes_manifest_sha256": MODULE.sha256(ORIGINAL_ROOT / "partvtk_request_manifest.json"),
        "preserved_intermediate_manifest": str(intermediate_manifest_copy.resolve()),
        "preserved_intermediate_manifest_sha256": intermediate_manifest_copy_sha,
        "failed_reason": "v3 _PARTVTK_001 was rejected before launch because __Actual.vtk was not emitted by GenCase",
        "qualification_claim": "none",
        "q_i_status": "pending_actual_partvtk_receipts_and_typed_audit",
        "q_n_status": "pending",
        "gpu_launch": False,
    }
    MODULE.write_json(MODULE.FAMILY_ROOT / "partvtk_request_manifest_002.json", result)
    # Keep the canonical name for the inherited audit implementation.  This
    # file is new within this additive root; the original v3 manifest remains
    # untouched under ORIGINAL_ROOT and is bound above.
    MODULE.write_json(MODULE.FAMILY_ROOT / "partvtk_request_manifest.json", result)
    return result


def _load_stats_partvtk_counter():
    v7 = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v7.py")
    spec = importlib.util.spec_from_file_location("f6_dp020_dp0125_partvtk_v2_counter", v7)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load stats-aware PartVTK parser: {v7}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._partvtk_counts


def audit() -> dict[str, Any]:
    """Run the inherited typed/mass audit against only the _002 requests."""

    MODULE._partvtk_counts = _load_stats_partvtk_counter()
    result = MODULE.audit()
    result["schema"] = "ds-data-02.f6.rigid_contract_003.dp020-dp0125.partvtk_audit.v2"
    result["request_manifest"] = str((MODULE.FAMILY_ROOT / "partvtk_request_manifest_002.json").resolve())
    result["request_manifest_sha256"] = MODULE.sha256(MODULE.FAMILY_ROOT / "partvtk_request_manifest_002.json")
    result["supersedes"] = str((ORIGINAL_ROOT / "partvtk_request_manifest.json").resolve())
    result["qualification_claim"] = "none"
    result["q_n_status"] = "pending_root_review_and_solver_three_resolution_reference"
    MODULE.write_json(MODULE.FAMILY_ROOT / "strict_partvtk_audit_002.json", result)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["make-partvtk-requests", "audit"])
    args = parser.parse_args()
    result = make_partvtk_requests() if args.action == "make-partvtk-requests" else audit()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
