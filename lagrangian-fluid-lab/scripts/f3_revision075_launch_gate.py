"""Fail-closed authorization verifier for the prospective F3 revision.

This module deliberately does not launch a solver.  It validates the owner
authorization and the immutable preparation hashes so a future runner cannot
mistake ``prepared_only`` inputs for permission to spend qualification budget.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
MANIFEST = LAB / "diagnostics/f3-audit/F3-075-REVISION-MATRIX-MANIFEST.json"
SUMMARY = LAB / "campaigns/l1-resume/continuation/F3-075-REVISION-PREPARATION-SUMMARY.json"
LIMITS = LAB / "campaigns/l1-resume/continuation/RESOURCE-LIMITS.json"
DEFAULT_AUTHORIZATION = LAB / "campaigns/l1-resume/continuation/F3-075-REVISION-AUTHORIZATION.json"
RECIPE = "F3_CELL3_NS_visco1_native_nopen_revision075"
SCHEMA = "f3.revision075.owner_authorization.v1"
REQUIRED_EXISTING_EVIDENCE = {
    "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen",
    "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
    "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"missing required record: {path}")
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise ValueError(f"invalid JSON record: {path}") from error
    if not isinstance(value, dict):
        raise ValueError(f"record must be an object: {path}")
    return value


def verify_preparation() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest = _read(MANIFEST)
    summary = _read(SUMMARY)
    if manifest.get("schema") != "f3.revision075.matrix_manifest.v1":
        raise ValueError("unexpected revision manifest schema")
    if manifest.get("recipe_id") != RECIPE or manifest.get("launch_allowed") is not False:
        raise ValueError("revision manifest is not an unlaunched revision")
    if len(manifest.get("cells", [])) != 11:
        raise ValueError("revision manifest must contain exactly 11 cells")
    if (summary.get("schema") != "f3.revision075.preparation_summary.v1"
            or summary.get("status") != "prepared_only"
            or summary.get("launch_allowed") is not False
            or summary.get("manifest_sha256") != sha256(MANIFEST)
            or summary.get("solver_attempts") != 0
            or summary.get("qualification_attempts_charged") != 0):
        raise ValueError("revision preparation summary is stale or already launched")
    return manifest, summary


def verify_authorization(
    authorization_path: Path = DEFAULT_AUTHORIZATION,
    limits_path: Path = LIMITS,
) -> dict[str, Any]:
    """Verify a prospective owner authorization without mutating anything."""
    manifest, summary = verify_preparation()
    authorization = _read(authorization_path)
    if authorization.get("schema") != SCHEMA or authorization.get("status") != "approved":
        raise PermissionError("explicit approved revision authorization is required")
    if not isinstance(authorization.get("owner_reply"), str) or not authorization["owner_reply"].strip():
        raise PermissionError("authorization must retain the owner's reply")
    existing = authorization.get("existing_evidence")
    if (not isinstance(existing, list)
            or not REQUIRED_EXISTING_EVIDENCE.issubset(set(existing))):
        raise PermissionError("authorization must explicitly allow the three hash-bound existing reference cases")
    if authorization.get("recipe_id") != RECIPE:
        raise PermissionError("authorization recipe does not match the prepared revision")
    if authorization.get("manifest_sha256") != sha256(MANIFEST):
        raise PermissionError("authorization is bound to a different revision manifest")
    if authorization.get("preparation_summary_sha256") != sha256(SUMMARY):
        raise PermissionError("authorization is bound to a different preparation summary")
    requested = authorization.get("limits")
    if not isinstance(requested, dict):
        raise PermissionError("authorization must specify qualification/CPU/GPU limits")
    try:
        qualification = int(requested["qualification"])
        cpu_core_hours = float(requested["cpu_core_hours"])
        gpu_hours = float(requested["gpu_hours"])
    except (KeyError, TypeError, ValueError) as error:
        raise PermissionError("authorization limits are invalid") from error
    if qualification < 72 or cpu_core_hours < 768 or gpu_hours < 64:
        raise PermissionError("authorization limits cannot reduce the existing approved caps")
    current = _read(limits_path).get("limits")
    if not isinstance(current, dict):
        raise ValueError("resource limits record has no limits object")
    if (int(current.get("qualification", 0)) < qualification
            or float(current.get("cpu_core_hours", 0)) < cpu_core_hours
            or float(current.get("gpu_hours", 0)) < gpu_hours):
        raise PermissionError("resource limits record has not been updated to the authorized caps")
    policy = manifest.get("resource_policy")
    if (not isinstance(policy, dict)
            or policy.get("development_launch_allowed") is not False
            or policy.get("training_launch_allowed") is not False
            or policy.get("material_production_allowed") is not False):
        raise ValueError("revision manifest cannot authorize development or training")
    return {
        "authorization": authorization,
        "manifest": manifest,
        "preparation_summary": summary,
        "active_limits": current,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--authorization", type=Path, default=DEFAULT_AUTHORIZATION)
    parser.add_argument("--limits", type=Path, default=LIMITS)
    args = parser.parse_args(argv)
    try:
        result = verify_authorization(args.authorization, args.limits)
    except (PermissionError, ValueError) as error:
        print(json.dumps({"status": "blocked", "reason": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "authorized", "recipe_id": result["authorization"]["recipe_id"],
                      "limits": result["authorization"]["limits"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
