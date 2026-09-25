"""Tests for the read-only real 32000-update capacity adapter."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import torch

from scripts.core_formal_capacity_evidence import (
    CHECKPOINT_SCHEMA,
    EXECUTION_SCHEMA,
    MODEL_ADAPTER_SCHEMA,
    MODEL_VERSION,
    REQUIRED_CODE_FILES,
    SOURCE_CLOSURE_SCHEMA,
    canonical_sha256,
    inspect_capacity_evidence,
    sha256_file,
)
from scripts.core_formal_admission_audit import _resource_observation, audit_admission


ROOT = Path(__file__).resolve().parents[1]


def _manifest(tmp_path: Path) -> Path:
    payload = {
        "schema": "core.dataset.v2",
        "dataset_id": "capacity-fixture",
        "formal_release": True,
        "cases": [{
            "case_id": "F4_CAPACITY_00",
            "physical_case_id": "F4_CAPACITY_00",
            "lineage_group_id": "F4_CAPACITY_00",
            "family": "F4",
            "split": "train",
            "hdf5": "trajectory.h5",
            "sha256": "0" * 64,
            "known_inputs_sha256": "1" * 64,
            "known_inputs_ref": {
                "geometry": {"path": "geometry.npz", "sha256": "2" * 64},
                "control": {"path": "control.npz", "sha256": "3" * 64},
                "numerics": {"recipe_id": "fixture"},
                "physics": {"scope_id": "fixture"},
                "coordinate_frame": "fixture",
            },
        }],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _closure() -> dict:
    rows = []
    for relative in REQUIRED_CODE_FILES:
        path = ROOT / relative
        rows.append({"relative_path": relative, "sha256": sha256_file(path), "bytes": path.stat().st_size})
    return {
        "schema": SOURCE_CLOSURE_SCHEMA,
        "complete": True,
        "required_files": list(REQUIRED_CODE_FILES),
        "files": rows,
        "closure_sha256": canonical_sha256([
            {"relative_path": row["relative_path"], "sha256": row["sha256"]}
            for row in rows
        ]),
    }


def _checkpoint(path: Path, *, update: int, model_kind: str = "graph_raw",
                 seed: int = 17, run_id: str = "capacity-fixture") -> dict:
    payload = {
        "schema": CHECKPOINT_SCHEMA,
        "model_kind": model_kind,
        "hidden": 64,
        "seed": seed,
        "update": update,
        "config": {"run_id": run_id},
        "model_state": {},
        "state_dict": {},
        "optimizer_state": {"state": {}, "param_groups": []},
        "sampler_state": {"draws": update},
        "rng_state": {"python": b"fixture"},
        "evidence_status": "complete",
    }
    torch.save(payload, path)
    return {"path": str(path), "sha256": sha256_file(path),
            "bytes": path.stat().st_size, "update": update,
            "schema": CHECKPOINT_SCHEMA}


def _fixture(tmp_path: Path) -> tuple[dict, dict, Path, Path, Path]:
    manifest = _manifest(tmp_path)
    closure_path = tmp_path / "source-closure.json"
    closure = _closure()
    closure_path.write_text(json.dumps(closure), encoding="utf-8")
    checkpoints = {
        update: _checkpoint(tmp_path / f"checkpoint-{update}.pt", update=update)
        for update in (8000, 16000, 24000, 32000)
    }
    final_path = tmp_path / "final.pt"
    final = _checkpoint(final_path, update=32000)
    receipt = {
        "schema": "core.training.v1",
        "run_id": "capacity-fixture",
        "model_kind": "graph_raw",
        "seed": 17,
        "device": "cuda:0",
        "completed_updates": 32000,
        "checkpoint_verified": True,
        "checkpoint": final,
        "milestone_updates": [8000, 16000, 24000, 32000],
        "milestone_checkpoints": list(checkpoints.values()),
        "config": {
            "model_kind": "graph_raw", "seed": 17, "updates": 32000,
            "run_id": "capacity-fixture",
            "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        },
        "evidence_status": "complete",
        "evidence": {"schema": "core.training.evidence.v1", "status": "complete"},
        "sampler": {"case_count": 16, "draws": 32000},
    }
    execution = {
        "schema": EXECUTION_SCHEMA,
        "model_kind": "graph_raw",
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
        "source_closure_sha256": closure["closure_sha256"],
        "model_adapter": {
            "schema": MODEL_ADAPTER_SCHEMA,
            "model_version": MODEL_VERSION,
            "model_kind": "graph_raw",
            "entrypoint": "scripts.core_models.DualIncrementModel",
        },
        "execution_constraints": {
            "synthetic_input": False,
            "formal_training": False,
            "formal_job_count": 0,
            "formal_runs_started": 0,
            "solver_started": False,
            "submitted": False,
            "central_registry_mutation": 0,
            "central_ledger_mutation": 0,
            "full_particle_axis": True,
            "trajectory_files_opened": True,
            "checkpoint_written": True,
            "updates_completed": 32000,
        },
        "resource": {
            "wall_seconds": 3600.0,
            "peak_gpu_memory_bytes": 8 * 1024 * 1024 * 1024,
        },
    }
    return receipt, execution, manifest, closure_path, final_path


def test_real_capacity_fixture_is_valid_but_never_formal_training(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    report = inspect_capacity_evidence(
        receipt, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["status"] == "ready"
    assert report["formal_capacity_evidence"] is True
    assert report["formal_training"] is False
    assert report["formal_job_count"] == 0
    assert report["formal_runs_counted"] == 0
    assert report["observed_update_frontier"] == 32000
    assert report["execution_constraints"]["central_registry_mutation"] == 0
    assert report["execution_constraints"]["central_ledger_mutation"] == 0


def test_existing_1000_update_pilot_cannot_be_adapted_as_capacity_evidence(tmp_path: Path) -> None:
    pilot = ROOT / "campaigns/core-v1/evidence/h200-f3-fullfield-integration-pilot-graph_raw-1000-training.json"
    payload = json.loads(pilot.read_text(encoding="utf-8"))
    report = inspect_capacity_evidence(
        payload, execution=None, manifest=None, source_closure=None,
        data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_UPDATE_FRONTIER" in report["blocker_codes"]
    assert "CAPACITY_EXECUTION_EVIDENCE" in report["blocker_codes"]
    assert "CAPACITY_SOURCE_CLOSURE" in report["blocker_codes"]


def test_checkpoint_hash_or_milestone_tamper_fails_closed(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, final_path = _fixture(tmp_path)
    broken = copy.deepcopy(receipt)
    broken["milestone_checkpoints"][2]["update"] = 16000
    broken["checkpoint"]["sha256"] = "0" * 64
    report = inspect_capacity_evidence(
        broken, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_CHECKPOINT_SEMANTICS" in report["blocker_codes"]
    assert "CAPACITY_HASH_BINDING" in report["blocker_codes"]
    assert final_path.is_file()


def test_admission_consumes_only_a_hash_bound_capacity_record(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    receipt_path = tmp_path / "training.json"
    execution_path = tmp_path / "execution.json"
    closure.write_text(json.dumps(_closure()), encoding="utf-8")
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    execution_path.write_text(json.dumps(execution), encoding="utf-8")
    adapted = inspect_capacity_evidence(
        receipt_path, execution=execution_path, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert adapted["valid"] is True
    assert adapted["receipt"] == {
        "path": "training.json",
        "sha256": hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
        "bytes": receipt_path.stat().st_size,
    }
    assert adapted["execution"] == {
        "path": "execution.json",
        "sha256": hashlib.sha256(execution_path.read_bytes()).hexdigest(),
        "bytes": execution_path.stat().st_size,
    }
    adapter_path = tmp_path / "capacity.json"
    adapter_path.write_text(json.dumps(adapted), encoding="utf-8")
    audit = audit_admission(
        [manifest], data_root=tmp_path, code_root=ROOT,
        capacity_evidence=adapter_path,
    )
    assert audit["capacity_evidence"]["valid"] is True
    assert audit["resource_profile"]["formal_capacity_evidence"] is True
    assert "RESOURCE_FRONTIER_UNPROVEN" not in {item["code"] for item in audit["blockers"]}
    assert audit["formal_job_count"] == 0


def test_32000_synthetic_profile_stays_diagnostic(tmp_path: Path) -> None:
    profile = tmp_path / "synthetic-profile.json"
    profile.write_text(json.dumps({
        "configurations": [{"optimizer_updates": 32000}],
        "limits": "synthetic only",
    }))
    observation = _resource_observation(profile, root=tmp_path)
    assert observation["observed_update_frontier"] == 32000
    assert observation["diagnostic_only"] is True
    assert observation["formal_capacity_evidence"] is False


def test_capacity_binding_requires_explicit_manifest_hashes(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    del receipt["config"]["manifest_sha256"]
    execution.pop("manifest_sha256")
    report = inspect_capacity_evidence(
        receipt, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_MANIFEST_BINDING" in report["blocker_codes"]


def test_capacity_binding_requires_checkpoint_and_closure_byte_receipts(
    tmp_path: Path,
) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    del receipt["milestone_checkpoints"][0]["bytes"]
    closure_payload = json.loads(closure.read_text(encoding="utf-8"))
    del closure_payload["files"][0]["bytes"]
    closure.write_text(json.dumps(closure_payload), encoding="utf-8")
    report = inspect_capacity_evidence(
        receipt, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_CHECKPOINT_SEMANTICS" in report["blocker_codes"]
    assert "CAPACITY_SOURCE_CLOSURE" in report["blocker_codes"]


def test_capacity_binding_requires_execution_source_closure_hash(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    execution.pop("source_closure_sha256")
    report = inspect_capacity_evidence(
        receipt, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_SOURCE_CLOSURE" in report["blocker_codes"]


def test_capacity_binding_rejects_noncanonical_source_closure_rows(tmp_path: Path) -> None:
    receipt, execution, manifest, closure, _ = _fixture(tmp_path)
    payload = json.loads(closure.read_text(encoding="utf-8"))
    payload["files"] = payload["files"][1:] + payload["files"][:1]
    closure.write_text(json.dumps(payload), encoding="utf-8")
    report = inspect_capacity_evidence(
        receipt, execution=execution, manifest=manifest,
        source_closure=closure, data_root=tmp_path, code_root=ROOT,
    )
    assert report["formal_capacity_evidence"] is False
    assert "CAPACITY_SOURCE_CLOSURE" in report["blocker_codes"]
