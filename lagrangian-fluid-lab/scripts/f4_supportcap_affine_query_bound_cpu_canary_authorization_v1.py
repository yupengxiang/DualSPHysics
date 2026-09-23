#!/usr/bin/env python3
"""Write a fail-closed authorization contract for one new F4 CPU canary.

This is an authorization and preflight contract only.  It deliberately has no
HDF5 reader, candidate runner, solver, GPU, queue, worker, registry, or ledger
entry point.  A later, separately authorized executor must perform every
runtime check recorded here before it can create the new output namespace.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


LAB = Path(__file__).resolve().parents[1]
CANDIDATE_DIR = LAB / "campaigns/core-v1/material/candidates/f4-supportcap-affine-query-bound-v3"
CANDIDATE_CARD = CANDIDATE_DIR / "candidate-card-v3.json"
ROOT_REVIEW = CANDIDATE_DIR / "terra-high-root-review-v4.json"
HISTORICAL_PREFLIGHT = LAB / (
    "campaigns/core-v1/material/evidence/"
    "f4-tallwall120-native-cell14-material-preflight-20260921.json"
)
FORMAL_QUALIFICATION = LAB / "campaigns/core-v1/evidence/f4-tallwall120-formal-qualification-20260920.json"
STATIC_IMPLEMENTATION = LAB / "scripts/f4_supportcap_affine_query_bound_candidate_v3.py"
CPU_MANAGER = LAB / "scripts/f4_tallwall120_material_preflight_v1.py"
OUTPUT = CANDIDATE_DIR / "cpu-native-canary-preflight-authorization-v1/authorization.json"

ATTEMPT_ID = "f4-supportcap-affine-query-bound-v3-cpu-native-canary-r001"
OUTPUT_NAMESPACE = LAB / "campaigns/core-v1/material/evidence" / ATTEMPT_ID
SOURCE_SHA256 = "91846866c177e4c3036b7ef92c33a4e0bde7d9e8993efb01dde300811b7c096e"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def reference(path: Path, role: str) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {
        "path": str(path.relative_to(LAB)),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "role": role,
    }


def _relative(path: Path) -> str:
    return str(Path(path).resolve().relative_to(LAB))


def _require_static_admission() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    card = load(CANDIDATE_CARD)
    review = load(ROOT_REVIEW)
    old_preflight = load(HISTORICAL_PREFLIGHT)
    qualification = load(FORMAL_QUALIFICATION)

    if not (
        card["candidate_id"] == "f4_supportcap_affine_query_bound_v3"
        and card["status"] == "proposal_only_root_review_required"
        and card["authorized_one_cpu_only"] is False
        and card["T2_macro"] is False
        and card["T2_path"] is False
    ):
        raise ValueError("candidate card does not describe the expected zero-credit v3 proposal")
    review_card = review["hash_bindings"]["candidate_card_v3"]
    if not (
        review["status"] == "static_review_completed_canary_denied"
        and review["decision"] == "STATIC_REVISION_ACCEPTED_FOR_FUTURE_ROOT_REVIEW__NO_CPU_AUTHORIZATION"
        and review["authorized_one_cpu_only"] is False
        and review_card["sha256"] == sha256(CANDIDATE_CARD)
    ):
        raise ValueError("Terra High v4 review is not the expected static-only predecessor")
    source_binding = old_preflight["source_t1_binding"]
    source = Path(source_binding["source"]["path"])
    if not (
        old_preflight["schema"] == "core.material.f4.tallwall120.cpu_preflight.v1"
        and old_preflight["qualification"]["T2_macro"] is False
        and old_preflight["qualification"]["T2_path"] is False
        and source_binding["scope"]["T1_numerical"] is True
        and source_binding["source"]["sha256"] == SOURCE_SHA256
        and source.is_file()
    ):
        raise ValueError("the selected F4 source is not the expected available T1-only native input")
    if not (
        qualification["scope_id"] == source_binding["scope"]["scope_id"]
        and qualification["T1_numerical"] is True
        and qualification["T2_macro"] is False
        and qualification["T2_path"] is False
    ):
        raise ValueError("F4 formal qualification is not T1-only for the selected source scope")
    return card, review, old_preflight


def _planned_artifacts() -> dict[str, dict[str, Any]]:
    names = {
        "attempt_manifest": "attempt-manifest.json",
        "environment_preflight": "environment-preflight.json",
        "input_preflight": "input-preflight.json",
        "trace": "trace.h5",
        "checkpoint_manifest": "trace.h5.checkpoint.json",
        "result": "result.json",
        "acceptance_receipt": "acceptance-receipt.json",
    }
    return {
        name: {"path": _relative(OUTPUT_NAMESPACE / filename), "exists": (OUTPUT_NAMESPACE / filename).exists()}
        for name, filename in names.items()
    }


def build_authorization() -> dict[str, Any]:
    card, review, old_preflight = _require_static_admission()
    source_binding = old_preflight["source_t1_binding"]
    source_path = Path(source_binding["source"]["path"]).resolve()
    artifacts = _planned_artifacts()
    if OUTPUT_NAMESPACE.exists() or any(item["exists"] for item in artifacts.values()):
        raise FileExistsError("new CPU canary output namespace must be absent; old output reuse is forbidden")

    return {
        "schema": "core.material.f4.supportcap_affine_query_bound.cpu_canary_authorization.v1",
        "record_id": "f4-supportcap-affine-query-bound-v3-cpu-native-canary-preflight-authorization-v1",
        "status": "authorized_preflight_contract_only_canary_not_started",
        "authorization": {
            "authority": "explicit user authorization: F4 supportcap CPU canary preflight",
            "candidate_id": card["candidate_id"],
            "attempt_id": ATTEMPT_ID,
            "authorization_grants_runtime_execution": False,
            "reason": "this artifact authorizes a versioned preflight contract only; a separately explicit execution authorization is required before a CPU canary may start",
        },
        "qualification_boundary": {
            "qualification_claim": "none",
            "credit": 0,
            "T1_numerical": False,
            "T2_macro": False,
            "T2_path": False,
            "material_qualification": False,
        },
        "one_attempt_contract": {
            "max_attempts": 1,
            "retry": False,
            "resume_only_within_same_attempt": True,
            "new_output_namespace": _relative(OUTPUT_NAMESPACE),
            "output_namespace_must_be_absent_before_start": True,
            "planned_artifacts_absent_at_authorization": artifacts,
            "old_output_reuse_forbidden": True,
            "old_failure_evidence_modification_forbidden": True,
        },
        "input_contract": {
            "source": {
                "path": _relative(source_path),
                "sha256": SOURCE_SHA256,
                "role": "T1-qualified terminal native trajectory; read-only input only",
                "frame_count": source_binding["frame_count"],
                "particle_count": source_binding["particle_count"],
                "time_start_s": source_binding["time_start_s"],
                "time_end_s": source_binding["time_end_s"],
                "exact_native_rows": True,
            },
            "bounded_canary": {
                "frame_start": 40,
                "frame_stop_inclusive": 41,
                "seed_denominator": 512,
                "q": 0.5,
                "dp_m": 0.0075,
                "substeps": 2,
                "purpose": "one-transition CPU integration and fixed-gate preflight only",
            },
            "runtime_input_checks_required": [
                "recompute and exactly match source SHA256 before any HDF5 open",
                "open only the hash-matched source read-only and require time/position/velocity/valid/particle_zone datasets",
                "require frames 40 and 41 with strictly increasing native time",
                "require the original 512-seed denominator and unchanged F4 gate/event/unknown semantics",
                "require candidate-card-v3 and terra-high-root-review-v4 hashes to match this authorization",
            ],
        },
        "environment_and_resource_preflight": {
            "runtime_checks_required": [
                "Python >= 3.10 with importable numpy, scipy, and h5py",
                "CUDA_VISIBLE_DEVICES is empty or unset and no GPU API is initialized",
                "one process, one CPU worker, OMP_NUM_THREADS=1, OPENBLAS_NUM_THREADS=1, MKL_NUM_THREADS=1",
                "fresh writable parent for the new output namespace while the namespace itself remains absent",
                "available RAM is at least 16 GiB and free filesystem capacity is at least 8 GiB before start",
                "no active queue, scheduler, worker, solver, registry, or ledger operation is used",
            ],
            "resource_limits": {"max_concurrent_processes": 1, "cpu_workers": 1, "gpu_allowed": False},
        },
        "execution_contract": {
            "future_executor_status": "not_implemented_or_authorized_by_this_record",
            "required_before_start": "a separate explicit execution authorization must bind a new executor hash and this exact authorization hash",
            "must_not_call": ["solver", "GPU", "queue", "worker scheduler", "registry", "ledger", "matrix writer"],
            "must_preserve": [
                "registered F4 fixed support/reconstruction/unknown/event gates",
                "full 512-seed denominator and right-censor semantics",
                "all historical negative receipts including the ESS32 zero-survivor review",
            ],
        },
        "acceptance_and_failure_semantics": {
            "success_status": "completed_cpu_canary_preflight_zero_credit",
            "success_requires": [
                "all input, environment, resource, and output-absence checks pass",
                "one immutable attempt manifest, preflight records, result, and acceptance receipt are written in the new namespace",
                "receipt records no solver/GPU/queue/worker/registry/ledger activity",
                "receipt retains T1/T2/material qualification false and credit 0",
            ],
            "failure_status": "failed_one_attempt_zero_credit",
            "failure_requires": [
                "write an immutable negative receipt if output creation has begun",
                "do not retry, rename into, or reuse any old or partial output namespace",
                "do not alter thresholds, source, denominator, event semantics, or historical evidence",
            ],
        },
        "execution_controls": {
            "canary_started": False,
            "source_hdf5_opened": False,
            "solver_started": False,
            "gpu_started": False,
            "queue_mutation": 0,
            "worker_started": False,
            "registry_mutation": 0,
            "ledger_mutation": 0,
            "historical_receipts_modified": False,
        },
        "hash_bindings": {
            "candidate_card_v3": reference(CANDIDATE_CARD, "authorized F4 supportcap candidate card"),
            "terra_high_root_review_v4": reference(ROOT_REVIEW, "static root review preceding this authorization"),
            "historical_negative_cpu_preflight": reference(HISTORICAL_PREFLIGHT, "preserved non-reusable F4 baseline preflight"),
            "formal_f4_t1_qualification": reference(FORMAL_QUALIFICATION, "T1-only formal F4 scope qualification"),
            "static_candidate_implementation": reference(STATIC_IMPLEMENTATION, "array-only candidate implementation"),
            "existing_cpu_manager": reference(CPU_MANAGER, "existing F4 CPU preflight manager consulted for safeguards"),
            "authorization_builder": reference(Path(__file__), "authorization contract builder"),
            "authorization_test": reference(LAB / "tests/test_f4_supportcap_affine_query_bound_cpu_canary_authorization_v1.py", "authorization regression test"),
        },
    }


def write_authorization(path: Path = OUTPUT) -> dict[str, Any]:
    path = Path(path).resolve()
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable CPU canary authorization: {path}")
    value = build_authorization()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return value


def verify(path: Path = OUTPUT) -> dict[str, Any]:
    value = load(path)
    assert value["schema"] == "core.material.f4.supportcap_affine_query_bound.cpu_canary_authorization.v1"
    assert value["status"] == "authorized_preflight_contract_only_canary_not_started"
    assert value["authorization"]["authorization_grants_runtime_execution"] is False
    assert value["execution_controls"]["canary_started"] is False
    assert value["qualification_boundary"]["credit"] == 0
    assert not (LAB / value["one_attempt_contract"]["new_output_namespace"]).exists()
    for item in value["hash_bindings"].values():
        bound = LAB / item["path"]
        assert bound.is_file(), bound
        assert bound.stat().st_size == item["bytes"], bound
        assert sha256(bound) == item["sha256"], bound
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    value = verify(args.output) if args.verify else write_authorization(args.output)
    print(json.dumps({key: value[key] for key in ("status", "record_id")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
