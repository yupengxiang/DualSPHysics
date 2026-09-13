"""Freeze the six-run ref0081818 training plan after the actual-source contract."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import sys

if __package__ in (None, ""):  # pragma: no cover
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts import f3_ref0081818_development as development
from scripts import f3_ref0081818_training_data as training_data
from scripts import f3_training_core as core
from scripts import f3_train_worker as worker
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_q2_mdbc_bridge import atomic_json, sha256


PLAN_NAME = "F3-REF0081818-TRAINING-PLAN-R9.json"
ROUTES = ("particle_mlp", "local_interaction")
SEEDS = (17, 29, 43)
MAX_STEPS = 16_384
CHECKPOINT_STEPS = (4096, 8192, MAX_STEPS)
FULL_CONTRACT = OUT / training_data.CONTRACTS["full"]
GATE = OUT / development.REVISION_GATE
PARALLEL_AUTHORIZATION = OUT / "F3-075-REF0081818-TRAINING-PARALLEL-AUTHORIZATION.json"


def _bound(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve().relative_to(LAB.resolve())), "sha256": sha256(path)}


def _read(path: Path) -> dict:
    return json.loads(path.read_text())


def build() -> dict:
    gate = development.verify_revision_gate()
    if gate.get("training_launch_allowed") is not True:
        raise PermissionError("ref0081818 training launch is not enabled")
    if not FULL_CONTRACT.is_file():
        raise FileNotFoundError("full ref0081818 development contract is required")
    contract = training_data.validate_development_contract(FULL_CONTRACT)
    if contract.get("scope") != "full" or len(contract.get("cases", [])) != 32:
        raise ValueError("full actual-source contract must contain 32 cases")
    authorization = _read(PARALLEL_AUTHORIZATION)
    if (authorization.get("status") != "approved"
            or authorization.get("allowed_gpu_indices") != list(range(8))):
        raise PermissionError("approved eight-GPU training authorization is required")
    validation_test = [row["case_id"] for row in contract["cases"]
                       if row["split"] in ("validation", "test")]
    train = [row["case_id"] for row in contract["cases"] if row["split"] == "train"]
    if len(train) != 16 or len(validation_test) != 16:
        raise ValueError("unexpected full contract split counts")
    config_template = core.TrainConfig(
        route="particle_mlp", seed=SEEDS[0], max_steps=MAX_STEPS,
        hidden=128, learning_rate=1e-3, weight_decay=1e-2, max_targets=256,
        shuffle=True, dtype="float32", adam_betas=(.9, .999), adam_eps=1e-8,
        validation_patience=None, validation_min_delta=0.0,
    )
    entries = []
    for route in ROUTES:
        for seed in SEEDS:
            config = asdict(core.TrainConfig(**{**asdict(config_template),
                                                "route": route, "seed": seed}))
            # JSON turns the TrainConfig tuple into a list on disk.  Normalize
            # the in-memory frozen value as well so an existing immutable plan
            # can be revalidated byte-for-byte on later launches.
            config["adam_betas"] = list(config["adam_betas"])
            entries.append({
                "logical_run_id": f"REF0081818-{route}-seed{seed}",
                "config": config,
                "checkpoint_steps": list(CHECKPOINT_STEPS),
                "qualification_contract": _bound(GATE),
                "development_contract": _bound(FULL_CONTRACT),
                "evaluation": {
                    "selection": "fixed_final_step_no_selection",
                    "case_ids": validation_test,
                    "validation_case_ids": [row["case_id"] for row in contract["cases"]
                                            if row["split"] == "validation"],
                    "public_test_case_ids": [row["case_id"] for row in contract["cases"]
                                              if row["split"] == "test"],
                },
            })
    bindings = {}
    for relative in worker.PROGRAMS:
        path = LAB / relative
        bindings[relative] = sha256(path)
    for path in (GATE, FULL_CONTRACT,
                 OUT / "F3-075-REF0081818-DOWNSTREAM-AUTHORIZATION.json",
                 PARALLEL_AUTHORIZATION,
                 OUT / "F3-075-REF0081818-DEVELOPMENT-REGISTRY-RECONCILIATION.json",
                 LAB / "scripts/f3_ref0081818_training_plan.py"):
        bindings[str(path.resolve().relative_to(LAB.resolve()))] = sha256(path)
    return {
        "schema": worker.PLAN_SCHEMA,
        "status": "frozen",
        "recipe_id": development.REVISION_RECIPE,
        "scope": "ref0081818 actual-source training closure",
        "qualification_contract": _bound(GATE),
        "development_contract": _bound(FULL_CONTRACT),
        "development_contract_sha256": sha256(FULL_CONTRACT),
        "routes": list(ROUTES), "seeds": list(SEEDS),
        "max_steps": MAX_STEPS,
        "checkpoint_steps": list(CHECKPOINT_STEPS),
        "train_case_count": len(train),
        "evaluation_case_count": len(validation_test),
        "evaluation_semantics": "all validation and public development test cases; fixed final step; no test-based selection",
        "resource_policy": {
            "allowed_gpu_indices": list(range(8)),
            "max_concurrent_training_runs": 8,
            "same_gpu_concurrency_limit": 2,
            "gpu_memory_reservation_mib": 18000,
            "parallel_authorization": _bound(PARALLEL_AUTHORIZATION),
            "training_attempt_budget": 12,
            "planned_primary_runs": len(entries),
            "reserved_recovery_attempts": 6,
        },
        "storage_policy": {
            "scope": "external_immutable_archive",
            "archive_root": str(worker.TRAINING_ROOT.resolve()),
            "campaign_storage_exempt": True,
            "artifact_manifest": "per-attempt SHA-256 manifest excludes only attempt.json and itself",
            "unique_outputs_retained": True,
        },
        "evidence_sha256": dict(sorted(bindings.items())),
        "entries": entries,
    }


def write(path: Path | None = None) -> dict:
    value = build()
    target = path or (OUT / PLAN_NAME)
    if target.exists():
        if _read(target) != value:
            raise ValueError("frozen ref0081818 training plan differs; refusing replacement")
    else:
        atomic_json(target, value)
    return value


if __name__ == "__main__":
    value = write()
    print(json.dumps({"status": value["status"], "entries": len(value["entries"]),
                      "path": str((OUT / PLAN_NAME).resolve()),
                      "sha256": sha256(OUT / PLAN_NAME)}, ensure_ascii=False))
