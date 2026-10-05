#!/usr/bin/env python3
"""Verify the fresh080 source package without touching scientific arrays."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "workers/bed_audit_axis_repaired.py"
BINDER = ROOT / "scripts/bind_bed_audit_fresh080.py"
CONTRACT = ROOT / "pipeline-contract.json"
BINDING = ROOT / "short-bed-audit-binding-template.json"
REQUEST = ROOT / "short-bed-audit-request.json"
EXPECTED = {
    "EXPECTED_FRAMES": 51,
    "EXPECTED_PARTICLE_AXIS": 174896,
    "EXPECTED_FIXED_PARTICLES": 130392,
    "EXPECTED_MOVING_PARTICLES": 3794,
    "EXPECTED_FLUID_PARTICLES": 40710,
    "FLUID_TYPE": 3,
    "DP_M": 0.02,
}
CANONICAL = "d791355fcb5d8562a45ecdbee1772b1039f2fe8e6534760734509b51511c5d3f"
SOURCE_PLAN = "e912c12cc6cf9d3e754cba69a307f47588e717a8a4717f1ed190c63443cc3e72"
LEGACY = "efa8c9822ee12f6400e36e09e6b1edaebb760882f3354adabb6113a72f380047"
PROFILE = [[-0.2, 0.0], [2.0, 0.0], [3.0, 0.28], [3.6, 0.448],
           [3.9, 0.448], [4.4, 0.05], [4.8, 0.05]]


def fail(message: str) -> None:
    raise SystemExit(f"fresh080 verification failed: {message}")


def require(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256(path: Path) -> str:
    require(path.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".csv"},
            f"scientific array digest requested: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def constants(path: Path) -> dict[str, Any]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, Any] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            for target in targets:
                if isinstance(target, ast.Name) and target.id in EXPECTED:
                    try:
                        values[target.id] = ast.literal_eval(value)
                    except (ValueError, TypeError):
                        pass
    return values


def check_request(value: dict[str, Any], label: str) -> None:
    require(value.get("case_id") == "F5_REF_RUNUP_DP020_EQUILIBRIUM_ROOT050_B071",
            f"{label} case id")
    require(value.get("expected_dimension") == 3, f"{label} dimension")
    require(value.get("expected_frames") == 51, f"{label} frames")
    require(value.get("expected_particle_axis") == 174896, f"{label} particle axis")
    require(value.get("expected_fixed_particles") == 130392, f"{label} fixed count")
    require(value.get("expected_moving_particles") == 3794, f"{label} moving count")
    require(value.get("expected_fluid_particles") == 40710, f"{label} fluid count")
    require(value.get("native_bed_marker_mk") == 50, f"{label} native bed marker")
    require(value.get("source_bed_marker_mkbound") == 40, f"{label} source bed marker")
    require(value.get("physical_condition_sha256") == CANONICAL, f"{label} canonical hash")
    require(value.get("source_plan_physical_condition_sha256") == SOURCE_PLAN, f"{label} source plan hash")
    require(value.get("source_h5_physical_condition_sha256") == LEGACY, f"{label} legacy H5 hash")
    require(value.get("physical_condition_sha256") != value.get("source_h5_physical_condition_sha256"),
            f"{label} collapsed hash layers")
    require(value.get("execution_allowed") is False, f"{label} execution gate")
    require(value.get("launch_allowed") is False, f"{label} launch gate")
    require(value.get("solver_allowed") is False, f"{label} solver gate")
    require(value.get("full801_authorized") is False, f"{label} full801 gate")
    require(value.get("independent_case_count_increment") == 0, f"{label} case count")
    profile = value.get("profile_nodes_xz_m") or value.get("output_contract", {}).get("profile_nodes_xz_m")
    if profile is not None:
        require(profile == PROFILE, f"{label} profile")
    bins = value.get("penetration_bins_m") or value.get("output_contract", {}).get("depth_tolerances_m")
    if bins is not None:
        require(bins == [0.02, 0.04], f"{label} penetration bins")


def main() -> int:
    require(WORKER.is_file() and BINDER.is_file(), "worker or binder missing")
    require(CONTRACT.is_file() and BINDING.is_file() and REQUEST.is_file(), "contract/template missing")
    worker_source = WORKER.read_text(encoding="utf-8")
    binder_source = BINDER.read_text(encoding="utf-8")
    require("import h5py" not in binder_source and "import numpy" not in binder_source,
            "source binder imports scientific-array reader")
    require("subprocess" not in binder_source and "os.system" not in binder_source,
            "source binder can launch a process")
    for token in ("verify_typed_conversion", "verify_xmf_receipt", "verify_registered_request",
                  "resolve_native_receipt"):
        require(token in binder_source, f"binder lacks actual metadata guard: {token}")
    found = constants(WORKER)
    for key, expected in EXPECTED.items():
        require(found.get(key) == expected, f"worker constant {key}={found.get(key)!r}")

    contract = load(CONTRACT)
    require(contract.get("source_only") is True, "contract source_only")
    require(contract.get("arrays_opened_by_source_prep") is False, "contract array policy")
    require(contract.get("jobs_started_by_source_prep") is False, "contract job policy")
    require(contract.get("full801_authorized") is False, "contract full801 policy")
    require(contract.get("native_identity_contract", {}).get("total_particles") == 174896,
            "contract native total")
    require(contract.get("native_identity_contract", {}).get("native_bed_marker_mk") == 50,
            "contract Mk50")
    require(contract.get("source_identity_contract", {}).get("source_bed_marker_mkbound") == 40,
            "contract mkbound40")
    require(contract.get("physical_condition_hash_layers", {}).get("canonical_owner_sha256") == CANONICAL,
            "contract canonical layer")
    require(contract.get("physical_condition_hash_layers", {}).get("source_h5_sha256") == LEGACY,
            "contract H5 layer")
    require(CANONICAL != LEGACY, "contract hash layers are equal")
    require(sha256(WORKER) == contract.get("worker_source_sha256"), "worker digest")
    require(sha256(BINDER) == contract.get("binder_source_sha256"), "binder digest")
    require(sha256(Path(__file__).resolve()) == contract.get("source_verifier_sha256"),
            "source verifier digest")

    binding = load(BINDING)
    request = load(REQUEST)
    check_request(binding, "binding template")
    check_request(request, "request template")
    require(request.get("input_files") == [] and request.get("input_sha256") == {},
            "future template contains unbound inputs")
    require(binding.get("worker_source_sha256") == contract.get("worker_source_sha256"),
            "binding worker digest")
    require(request.get("worker_source_sha256") == contract.get("worker_source_sha256"),
            "request worker digest")
    print(json.dumps({
        "schema": "ds02.f5.b071.fresh080.source-verification.v1",
        "source_only": True,
        "arrays_opened": False,
        "jobs_started": False,
        "worker_source_sha256": contract["worker_source_sha256"],
        "binder_source_sha256": contract["binder_source_sha256"],
        "particle_axis": 174896,
        "frames": 51,
        "native_mk": 50,
        "source_mkbound": 40,
        "status": "pass",
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
