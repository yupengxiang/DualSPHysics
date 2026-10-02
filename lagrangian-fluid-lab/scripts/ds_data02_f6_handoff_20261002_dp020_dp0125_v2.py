#!/usr/bin/env python3
"""Prepare the additive epsilon-free F6 .02/.0125 initial QA scope.

The first additive scope is retained as negative evidence: its inherited
``+1e-6 m`` drawbox tie-break emitted an extra x/y fluid layer at .0125 m.
This version changes only that numerical fluid drawbox span to the exact
continuous-size-minus-dp value.  The finite tank, fluid low/high faces, body,
128 kg mass, explicit center/inertia, paddle and controls remain frozen.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
REPO_ROOT = SCRIPT.parents[1]
FAMILY_ROOT = REPO_ROOT / "campaigns/ds-data-02/families/F6"
V1_SOURCE = SCRIPT.with_name("ds_data02_f6_handoff_20261002_dp020_dp0125.py")
SCOPE_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_002"
V1_SCOPE_ROOT = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp020_dp0125_cpu_001"
V1_FAILURE = V1_SCOPE_ROOT / "initial_qa_failure_001.json"
DP025_FAILURE = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp025_postprocessing_002/prior_attempt_001_failure_sidecar.json"
DP025_SPATIAL = FAMILY_ROOT / "handoff_20261002/rigid_contract_003/dp025_postprocessing_005/strict_spatial_comparison_001.json"


def _load_v1() -> Any:
    spec = importlib.util.spec_from_file_location("f6_dp020_dp0125_v1", V1_SOURCE)
    if spec is None or spec.loader is None:
        raise ImportError(V1_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


BASE = _load_v1()
MODULE = BASE.MODULE
BASE_DEFINITION_XML = MODULE._definition_xml
BASE_REQUEST_INPUTS = MODULE._request_input_files

MODULE.FAMILY_ROOT = SCOPE_ROOT
MODULE.SCRIPT = SCRIPT
MODULE.VERSION = "ds_data02_f6_handoff_20261002.rigid_contract_003.dp020_dp0125.v2"
MODULE.DP_LADDER = (("dp020", 0.020), ("dp0125", 0.0125))


def _request_input_files_with_repair(*paths: Path) -> list[str]:
    values = BASE_REQUEST_INPUTS(*paths)
    for path in (V1_SOURCE, V1_FAILURE, SCRIPT):
        value = str(path.resolve())
        if value not in values:
            values.append(value)
    return values


MODULE._request_input_files = _request_input_files_with_repair


def _definition_xml_without_epsilon(mechanism: str, resolution: str, dp: float) -> str:
    xml = BASE_DEFINITION_XML(mechanism, resolution, dp)
    exact = (
        f'<size x="{MODULE.fmt(MODULE.FLUID["size"][0] - dp)}" '
        f'y="{MODULE.fmt(MODULE.FLUID["size"][1] - dp)}" '
        f'z="{MODULE.fmt(MODULE.FLUID["size"][2] - dp)}" />'
    )
    pattern = re.compile(
        r'(<drawbox cmt="Frozen continuous fluid cell-centre population">.*?<size )'
        r'x="[^"]+" y="[^"]+" z="[^"]+"(\s*/>)',
        re.DOTALL,
    )
    repaired, count = pattern.subn(rf"\g<1>{exact[6:-3]}\g<2>", xml, count=1)
    if count != 1:
        raise ValueError("epsilon-free fluid drawbox was not found")
    return repaired.replace(
        "RIGID003 direct solid drawbox: measured GenCase lattice span; continuous physical faces and native rigid center/inertia remain frozen.",
        "RIGID003 epsilon-free direct fluid drawbox: exact continuous-size-minus-dp span; physical faces and native rigid center/inertia remain frozen.",
    )


MODULE._definition_xml = _definition_xml_without_epsilon


def _write_scope(manifest: dict[str, Any]) -> None:
    SCOPE_ROOT.mkdir(parents=True, exist_ok=True)
    scope = {
        "schema": "ds-data-02.f6.dp020-dp0125.scope.v2",
        "family_id": "F6",
        "scope": "F6_HANDOFF_20261002_RIGID003_DP020_DP0125_CPU_PREFLIGHT_002",
        "status": "cpu_gencase_requests_registered; initial_partvtk_pending",
        "repair_class": "numerical_drawbox_endpoint_layer",
        "repair_number_within_new_scope": 2,
        "change": "remove inherited +1e-6 m fluid drawbox x/y tie-break; use exact continuous_size-dp",
        "source_generator": {"path": str(SCRIPT.resolve()), "sha256": MODULE.sha256(SCRIPT)},
        "prior_scope_failure": {"path": str(V1_FAILURE.resolve()), "sha256": MODULE.sha256(V1_FAILURE)},
        "preserved_dp025_negative_evidence": [
            {"path": str(DP025_FAILURE.resolve()), "sha256": MODULE.sha256(DP025_FAILURE)},
            {"path": str(DP025_SPATIAL.resolve()), "sha256": MODULE.sha256(DP025_SPATIAL)},
        ],
        "resolution_ladder": {"dp020": 0.020, "dp0125": 0.0125},
        "same_continuous_geometry": True,
        "strict_continuous_fluid_mass_kg": 5120.0,
        "rigid_body_contract": {"floatingtype": 2, "aggregate_massbody_kg": 128.0, "center_m": [2.4, 1.2, 1.08], "inertia_diag_kg_m2": [8.533333333333335, 8.533333333333335, 13.653333333333336]},
        "control_window_s": [0.0, 12.0],
        "gpu_launch": False,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    MODULE.write_json(SCOPE_ROOT / "scope.json", scope)
    updated_cases = []
    for original in manifest["cases"]:
        row = dict(original)
        request_path = Path(row["request_binding"]["path"])
        request = MODULE.read_json(request_path)
        request["input_files"] = list(dict.fromkeys(request["input_files"] + [str(path.resolve()) for path in (SCOPE_ROOT / "scope.json", V1_FAILURE, DP025_FAILURE, DP025_SPATIAL)]))
        request["repair_scope"] = {
            "scope_path": str((SCOPE_ROOT / "scope.json").resolve()),
            "scope_sha256": MODULE.sha256(SCOPE_ROOT / "scope.json"),
            "prior_scope_failure": str(V1_FAILURE.resolve()),
        }
        MODULE.write_json(request_path, request)
        row["request"] = request
        row["request_binding"] = {"path": str(request_path.resolve()), "sha256": MODULE.sha256(request_path), "attempt_id": request["attempt_id"]}
        updated_cases.append(row)
    manifest = dict(manifest)
    manifest["cases"] = updated_cases
    manifest["scope_path"] = str((SCOPE_ROOT / "scope.json").resolve())
    manifest["scope_sha256"] = MODULE.sha256(SCOPE_ROOT / "scope.json")
    manifest["prior_scope_failure"] = str(V1_FAILURE.resolve())
    MODULE.write_json(SCOPE_ROOT / "manifest.json", manifest)


def prepare() -> dict[str, Any]:
    manifest = MODULE.prepare()
    _write_scope(manifest)
    return MODULE.read_json(SCOPE_ROOT / "manifest.json")


def make_partvtk_requests() -> dict[str, Any]:
    return MODULE.make_partvtk_requests()


def audit() -> dict[str, Any]:
    return MODULE.audit()


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "make-partvtk-requests", "audit"])
    args = parser.parse_args()
    result = prepare() if args.action == "prepare" else make_partvtk_requests() if args.action == "make-partvtk-requests" else audit()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
