"""Record the explicit post-development ref0081818 owner opt-in.

The command is the only supported transition from a passed development gate
to the material/training downstream gates.  It binds the read-only preflight,
all 32 completed development cases, the approved resource caps, and the exact
material/training proposal before atomically updating the gate.  It never
launches a solver or a training worker.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ""):  # pragma: no cover - direct CLI invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_ref0081818_downstream_preflight as preflight
from scripts import f3_ref0081818_development as development
from scripts.l1r_continuation_evidence import LAB, OUT


GATE_NAME = "F3-075-REF0081818-GATE.json"
AUTH_NAME = "F3-075-REF0081818-DOWNSTREAM-AUTHORIZATION.json"
REPLY = "我批准"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _bound(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve().relative_to(LAB.resolve())), "sha256": _sha256(path)}


def _atomic(path: Path, value: dict[str, Any]) -> None:
    partial = path.with_name(path.name + ".partial")
    partial.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    partial.replace(path)


def authorize(*, owner_reply: str = REPLY) -> dict[str, Any]:
    if owner_reply.strip() != REPLY:
        raise PermissionError("the explicit owner reply must be retained verbatim")
    gate_path = OUT / GATE_NAME
    preflight_path = OUT / preflight.PREFLIGHT_NAME
    manifest_path = OUT / development.DEVELOPMENT_MANIFEST
    registry_path = OUT / development.REGISTRY
    gate = _read(gate_path)
    proposal = _read(preflight_path)
    limits = _read(OUT / "RESOURCE-LIMITS.json").get("limits", {})
    if gate.get("status") != "passed" or gate.get("development_launch_allowed") is not True:
        raise PermissionError("passed ref0081818 development gate is required")
    if gate.get("material_production_allowed") is True or gate.get("training_launch_allowed") is True:
        raise ValueError("downstream gates are already enabled; refusing a second authorization")
    if proposal.get("status") != "blocked_pending_material_and_training_opt_in":
        raise ValueError("the frozen downstream preflight is missing or has an unexpected status")
    if proposal.get("gate", {}).get("sha256") != _sha256(gate_path):
        raise ValueError("downstream preflight was made against a different gate")
    if proposal.get("development", {}).get("case_count") != 32:
        raise ValueError("all 32 completed development cases must be bound")
    if proposal.get("material", {}).get("configuration_count") != 3:
        raise ValueError("the approved material scope must contain exactly 3 configurations")
    if proposal.get("training", {}).get("logical_run_count") != 6:
        raise ValueError("the approved training scope must contain exactly 6 logical runs")
    resource_limits = {
        "cpu_core_hours": limits["cpu_core_hours"],
        "gpu_hours": limits["gpu_hours"],
        "qualification_attempts": limits["qualification"],
        "development_attempts": limits["development"],
        "material_configurations": limits["materials"],
        "training_attempts": limits["training"],
    }
    authorization = {
        "schema": "f3.revision075.ref0081818.downstream_owner_authorization.v1",
        "status": "owner_authorized",
        "approved_at_utc": datetime.now(timezone.utc).isoformat(),
        "owner_reply": owner_reply,
        "recipe_id": development.REVISION_RECIPE,
        "scope": "post-development material production and training closure",
        "preflight": _bound(preflight_path),
        "development_manifest": _bound(manifest_path),
        "development_registry": _bound(registry_path),
        "resource_limits": resource_limits,
        "material": {
            "allowed": True,
            "configuration_ids": [row["config_id"] for row in proposal["material"]["configurations"]],
            "configuration_count": proposal["material"]["configuration_count"],
        },
        "training": {
            "allowed": True,
            "routes": proposal["training"]["routes"],
            "seeds": proposal["training"]["seeds"],
            "logical_run_count": proposal["training"]["logical_run_count"],
            "max_steps": proposal["training"]["max_steps"],
        },
        "launch_policy": {
            "allowed_gpu_indices": [4, 5, 6, 7],
            "max_concurrent_cfd_solvers": 1,
            "max_concurrent_training_runs": 1,
            "analysis_slots": 2,
        },
        "note": "This record enables the two downstream gate flags only; formal material/model qualification remains false until measured results pass their own gates.",
    }
    if (OUT / AUTH_NAME).exists():
        raise FileExistsError("downstream authorization already exists; refusing replacement")
    auth_path = OUT / AUTH_NAME
    _atomic(auth_path, authorization)
    updated = dict(gate)
    updated.update({
        "material_production_allowed": True,
        "training_launch_allowed": True,
        "downstream_authorization_path": str(auth_path.resolve().relative_to(LAB.resolve())),
        "downstream_authorization_sha256": _sha256(auth_path),
        "downstream_preflight_path": str(preflight_path.resolve().relative_to(LAB.resolve())),
        "downstream_preflight_sha256": _sha256(preflight_path),
        "material_configuration_scope": authorization["material"],
        "training_scope": authorization["training"],
    })
    _atomic(gate_path, updated)
    return {"authorization": authorization, "gate": updated}


if __name__ == "__main__":
    result = authorize()
    print(json.dumps(result, indent=2, ensure_ascii=False))
