"""Read-only preflight for the ref0081818 material and learning closure.

This module deliberately does not mutate the revision gate, publish a training
contract, charge a material configuration, or probe a GPU.  It freezes the
post-development proposal against the actual 32-case development manifest so
that a later owner opt-in can launch an exact, hash-bound batch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any
import sys

if __package__ in (None, ""):  # pragma: no cover - direct CLI invocation
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_ref0081818_development as development
from scripts import f3_ref0081818_material_reference as material
from scripts.l1r_continuation_evidence import LAB, OUT


PREFLIGHT_NAME = "F3-REF0081818-DOWNSTREAM-PREFLIGHT.json"
RECIPE = development.REVISION_RECIPE
TRAINING_ROUTES = ("particle_mlp", "local_interaction")
TRAINING_SEEDS = (17, 29, 43)
TRAINING_MAX_STEPS = 16_384
TRAINING_CHECKPOINT_STEPS = (4096, 8192, TRAINING_MAX_STEPS)
MATERIAL_TIMEOUT_S = 900
TRAINING_TIMEOUT_S = 1800
MATERIAL_POSTPROCESS_RESERVE_S = 600
CPU_ACTIVITY_CORES = 17.6
TRAINING_CPU_MULTIPLIER = 2.2


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


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _bound(path: Path) -> dict[str, str]:
    return {"path": _relative(path), "sha256": _sha256(path)}


def _reserve_material_cpu() -> float:
    seconds = MATERIAL_TIMEOUT_S + 5.0 + MATERIAL_POSTPROCESS_RESERVE_S
    return seconds * CPU_ACTIVITY_CORES / 3600.0


def _reserve_training_cpu() -> float:
    seconds = TRAINING_TIMEOUT_S + 5.0
    worker = seconds * TRAINING_CPU_MULTIPLIER / 3600.0
    activity_growth = seconds * CPU_ACTIVITY_CORES / 3600.0
    return worker + activity_growth


def build() -> dict[str, Any]:
    gate_path = OUT / "F3-075-REF0081818-GATE.json"
    manifest_path = OUT / development.DEVELOPMENT_MANIFEST
    ledger_path = OUT / "RESOURCE-LEDGER.json"
    gate = _read(gate_path)
    manifest = _read(manifest_path)
    ledger = _read(ledger_path)
    if (gate.get("schema") != "f3.revision075.ref0081818.gate.v1"
            or gate.get("recipe_id") != RECIPE
            or gate.get("status") != "passed"
            or gate.get("development_launch_allowed") is not True):
        raise ValueError("passed ref0081818 development gate is required")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != 32:
        raise ValueError("the downstream proposal requires all 32 development cases")
    split_counts = {split: sum(row.get("split") == split for row in cases)
                    for split in ("train", "validation", "test")}
    if split_counts != {"train": 16, "validation": 4, "test": 12}:
        raise ValueError("registered ref008 split counts changed")
    case_checks = []
    for row in cases:
        case_id = row.get("case_id")
        audit = OUT / f"{case_id}-AUDIT.json"
        solver = OUT / f"{case_id}-SOLVER.json"
        if not case_id or not audit.is_file() or not solver.is_file():
            raise ValueError(f"missing actual development evidence: {case_id}")
        audit_value, solver_value = _read(audit), _read(solver)
        if (audit_value.get("audit_status") != "pass_diagnostic"
                or audit_value.get("frames") != 836
                or audit_value.get("issues") != []
                or audit_value.get("unknowns") != []
                or solver_value.get("status") != "completed"):
            raise ValueError(f"development evidence is not complete: {case_id}")
        case_checks.append({"case_id": case_id, "split": row["split"],
                            "audit": _bound(audit), "solver": _bound(solver)})

    material_rows = material.configurations()
    training_entries = []
    for route in TRAINING_ROUTES:
        for seed in TRAINING_SEEDS:
            training_entries.append({
                "logical_run_id": f"REF0081818-{route}-seed{seed}",
                "route": route, "seed": seed, "max_steps": TRAINING_MAX_STEPS,
                "checkpoint_steps": list(TRAINING_CHECKPOINT_STEPS),
                "evaluation": {"selection": "fixed_final_step_no_selection",
                               "case_ids": [row["case_id"] for row in cases
                                             if row["split"] in ("validation", "test")]},
            })

    material_cpu = len(material_rows) * _reserve_material_cpu()
    training_cpu = len(training_entries) * _reserve_training_cpu()
    current_cpu = float(ledger["cpu_core_hours_upper_bound"])
    current_gpu = float(ledger["gpu_budget_charge_hours"])
    limits = ledger["limits"]
    return {
        "schema": "f3.ref0081818.downstream_preflight.v1",
        "status": "blocked_pending_material_and_training_opt_in",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "recipe_id": RECIPE,
        "gate": _bound(gate_path),
        "gate_state": {
            "status": gate["status"],
            "development_launch_allowed": gate["development_launch_allowed"],
            "material_production_allowed": gate.get("material_production_allowed"),
            "training_launch_allowed": gate.get("training_launch_allowed"),
        },
        "development": {"manifest": _bound(manifest_path),
                         "case_count": len(cases), "split_counts": split_counts,
                         "cases": case_checks},
        "material": {"configurations": material_rows, "configuration_count": len(material_rows),
                      "timeout_seconds": MATERIAL_TIMEOUT_S,
                      "postprocess_reserve_seconds": MATERIAL_POSTPROCESS_RESERVE_S,
                      "cpu_reserve_core_hours": material_cpu},
        "training": {"routes": list(TRAINING_ROUTES), "seeds": list(TRAINING_SEEDS),
                      "logical_run_count": len(training_entries),
                      "max_steps": TRAINING_MAX_STEPS,
                      "checkpoint_steps": list(TRAINING_CHECKPOINT_STEPS),
                      "entries": training_entries,
                      "timeout_seconds": TRAINING_TIMEOUT_S,
                      "cpu_reserve_core_hours": training_cpu,
                      "evaluation_case_count": len(training_entries[0]["evaluation"]["case_ids"])},
        "resources": {
            "current_cpu_core_hours": current_cpu,
            "current_gpu_budget_charge_hours": current_gpu,
            "limits": limits,
            "proposed_cpu_reserve_core_hours": material_cpu + training_cpu,
            "proposed_cpu_upper_bound": current_cpu + material_cpu + training_cpu,
            "cpu_headroom_after_proposal": limits["cpu_core_hours"] - current_cpu - material_cpu - training_cpu,
            "material_configurations_used": ledger["material_configurations_used"],
            "material_configurations_after_proposal": ledger["material_configurations_used"] + len(material_rows),
            "training_attempts_after_proposal": ledger["training_attempts_used"] + len(training_entries),
            "execution_policy": "single solver/training lock; GPU 4-7; analysis may be parallel but CFD/training launches are serialized",
        },
        "authorization_required": {
            "material_production_allowed": True,
            "training_launch_allowed": True,
            "note": "This artifact is a read-only proposal; it does not authorize or enable either gate.",
        },
    }


def write(path: Path | None = None) -> dict[str, Any]:
    value = build()
    target = path or (OUT / PREFLIGHT_NAME)
    if target.exists() and _read(target) != value:
        raise ValueError("existing downstream preflight differs; refusing replacement")
    if not target.exists():
        target.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    return value


if __name__ == "__main__":
    print(json.dumps(write(), indent=2, ensure_ascii=False))
