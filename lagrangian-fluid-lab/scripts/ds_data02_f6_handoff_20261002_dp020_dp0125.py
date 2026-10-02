#!/usr/bin/env python3
"""Register additive F6 .02/.0125 CPU GenCase and initial-audit inputs.

This scope reuses the frozen RIGID003 construction logic only as an imported
generator.  It writes a new directory and keeps the consumed DP025 outputs and
their spatial failure evidence immutable.  Both finer candidates retain the
same continuous tank/fluid/body/paddle geometry, 128 kg floating mass,
explicit center and analytic inertia, and mechanism controls; only the
particle spacing and its numerical cell-centre representation change.

The module prepares bounded shared-runner GenCase requests and, after those
receipts exist, official PartVTK initial-state audit requests.  It never
starts a solver or selects a GPU.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
RIGID003_SOURCE = SCRIPT.with_name("ds_data02_f6_handoff_20261002_v9.py")
DP_SCOPE_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_001"
DP025_FAILURE = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp025_postprocessing_002/prior_attempt_001_failure_sidecar.json"
DP025_SPATIAL = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp025_postprocessing_005/strict_spatial_comparison_001.json"


def _load_rigid003() -> Any:
    spec = importlib.util.spec_from_file_location("f6_rigid003_dp020_dp0125_base", RIGID003_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(RIGID003_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_rigid003()
MODULE = BASE.MODULE
BASE_DEFINITION_XML = BASE._definition_xml
BASE_NATIVE_JSON = MODULE._native_json
BASE_REQUEST_INPUTS = MODULE._request_input_files
BASE_GENCASE_REQUEST = MODULE._gencase_request

# This is a new numerical scope.  No old manifest, request, definition or
# receipt is rewritten in place.
MODULE.FAMILY_ROOT = DP_SCOPE_ROOT
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.dp020_dp0125.v1"
MODULE.DP_LADDER = (("dp020", 0.020), ("dp0125", 0.0125))


def _request_input_files_with_scope(*paths: Path) -> list[str]:
    values = BASE_REQUEST_INPUTS(*paths)
    extra = [RIGID003_SOURCE, DP025_FAILURE, DP025_SPATIAL, SCRIPT]
    for path in extra:
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_scope


def _gencase_request_with_cost_review(case: dict[str, Any]) -> dict[str, Any]:
    request = BASE_GENCASE_REQUEST(case)
    # GenCase is still bounded CPU work.  The .0125 case is larger than the
    # consumed DP025 reference and is explicitly costed from its expected
    # lattice count before any runner submission.
    expected_total = int(case["expected_fluid_particles"])
    expected_total += int(case["expected_fluid_particles"] * 0.22)
    request["max_wall_seconds"] = 900
    request["estimated_storage_bytes"] = 2 * 1024**3
    request["cost_review"] = {
        "basis": "expected type-3 lattice count plus 22% finite-bound/body allowance; no old 13.57M identity reuse",
        "expected_fluid_particles": int(case["expected_fluid_particles"]),
        "conservative_total_particle_estimate": expected_total,
        "estimated_storage_bytes": 2 * 1024**3,
        "max_wall_seconds": 900,
    }
    request["purpose"] = "additive F6 .02/.0125 strict-mother GenCase only; no solver/GPU; DP025 spatial failure remains negative evidence"
    request["qualification_claim"] = "none"
    request["q_n_status"] = "pending actual GenCase and PartVTK initial QA"
    return request


MODULE._gencase_request = _gencase_request_with_cost_review


def _write_scope_sidecars(manifest: dict[str, Any]) -> None:
    DP_SCOPE_ROOT.mkdir(parents=True, exist_ok=True)
    scope = {
        "schema": "ds-data-02.f6.dp020-dp0125.scope.v1",
        "family_id": "F6",
        "scope": "F6_HANDOFF_20261002_RIGID003_DP020_DP0125_CPU_PREFLIGHT_001",
        "status": "cpu_gencase_requests_registered; initial_partvtk_pending",
        "source_generator": str(SCRIPT.resolve()),
        "source_generator_sha256": MODULE.sha256(SCRIPT),
        "imported_rigid003_generator": str(RIGID003_SOURCE.resolve()),
        "imported_rigid003_generator_sha256": MODULE.sha256(RIGID003_SOURCE),
        "resolution_ladder": {"dp020": 0.020, "dp0125": 0.0125},
        "same_continuous_geometry": True,
        "continuous_fluid_box_m": {"low": [0.4, 0.4, 0.04], "size": [4.0, 1.6, 0.8], "volume_m3": 5.12},
        "continuous_fluid_mass_kg": 5120.0,
        "body_contract": {
            "floatingtype": 2,
            "aggregate_massbody_kg": 128.0,
            "center_m": [2.4, 1.2, 1.08],
            "inertia_diag_kg_m2": [8.533333333333335, 8.533333333333335, 13.653333333333336],
            "particle_type2_mass_is_separate": True,
        },
        "control_contract": {"window_s": [0.0, 12.0], "control_dt_s": 0.01, "same_control_family_as_rigid003": True},
        "preserved_dp025_negative_evidence": [
            {"path": str(DP025_FAILURE.resolve()), "sha256": MODULE.sha256(DP025_FAILURE), "role": "prior postprocessing failure sidecar"},
            {"path": str(DP025_SPATIAL.resolve()), "sha256": MODULE.sha256(DP025_SPATIAL), "role": "prior DP025 spatial comparison failure"},
        ],
        "manifest_status": manifest.get("status"),
        "gpu_launch": False,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    MODULE.write_json(DP_SCOPE_ROOT / "scope.json", scope)
    # Add the immutable scope and negative evidence to every new request, then
    # refresh only this new manifest's request bindings.
    manifest = dict(manifest)
    request_rows = []
    for row in manifest["cases"]:
        request_path = Path(row["request_binding"]["path"])
        request = MODULE.read_json(request_path)
        extra_paths = [DP_SCOPE_ROOT / "scope.json", DP025_FAILURE, DP025_SPATIAL]
        request["input_files"] = list(dict.fromkeys(request["input_files"] + [str(path.resolve()) for path in extra_paths]))
        request["source_scope"] = {
            "scope_path": str((DP_SCOPE_ROOT / "scope.json").resolve()),
            "scope_sha256": MODULE.sha256(DP_SCOPE_ROOT / "scope.json"),
            "preserved_dp025_failure": str(DP025_FAILURE.resolve()),
            "preserved_dp025_spatial_failure": str(DP025_SPATIAL.resolve()),
        }
        MODULE.write_json(request_path, request)
        row = dict(row)
        row["request"] = request
        row["request_binding"] = {
            "path": str(request_path.resolve()),
            "sha256": MODULE.sha256(request_path),
            "attempt_id": request["attempt_id"],
        }
        request_rows.append(row)
    manifest["cases"] = request_rows
    manifest["scope_path"] = str((DP_SCOPE_ROOT / "scope.json").resolve())
    manifest["scope_sha256"] = MODULE.sha256(DP_SCOPE_ROOT / "scope.json")
    manifest["preserved_dp025_spatial_failure"] = str(DP025_SPATIAL.resolve())
    MODULE.write_json(DP_SCOPE_ROOT / "manifest.json", manifest)


def prepare() -> dict[str, Any]:
    manifest = MODULE.prepare()
    _write_scope_sidecars(manifest)
    return MODULE.read_json(DP_SCOPE_ROOT / "manifest.json")


def make_partvtk_requests() -> dict[str, Any]:
    """Delegate the official initial-state audit request builder."""
    return MODULE.make_partvtk_requests()


def audit() -> dict[str, Any]:
    return MODULE.audit()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "make-partvtk-requests", "audit"])
    args = parser.parse_args()
    if args.action == "prepare":
        result = prepare()
    elif args.action == "make-partvtk-requests":
        result = make_partvtk_requests()
    else:
        result = audit()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
