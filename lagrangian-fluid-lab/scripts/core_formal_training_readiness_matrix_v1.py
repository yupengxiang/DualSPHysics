#!/usr/bin/env python3
"""Build and validate the read-only Core nine-run formal readiness matrix.

This is a matrix projection, not a run-specific auditor.  It reads the
current source-closure receipt, training contract, current-manifest evidence,
and the read-only result of ``core_campaign.py status``.  It never imports a
trainer, opens HDF5/checkpoints, starts a process, touches a GPU/queue/worker,
or writes registry/ledger/denominator/gate/completion/PLAN state.

The matrix deliberately treats diagnostic evidence as non-formal.  A current
manifest evidence receipt can be present while every formal readiness flag is
false; that distinction prevents a diagnostic receipt from becoming a formal
training run by aggregation.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import sys
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
CORE_ROOT = LAB_ROOT / "campaigns/core-v1"
REPORT_REL = Path("reports/CORE-FORMAL-TRAINING-READINESS-MATRIX-2026-09-29.json")
SCHEMA = "core.formal_training_readiness_matrix.v1"
REPORT_ID = "core-formal-training-readiness-matrix-v1"
MODELS = ("graph_raw", "graph_residual", "mlp")
SEEDS = (17, 29, 43)
RUN_IDS = tuple(f"{model}-seed{seed}" for model in MODELS for seed in SEEDS)
MAX_JSON_BYTES = 8 * 1024 * 1024

CURRENT_MANIFEST_EVIDENCE = {
    "graph_raw": "reports/F3-GRAPH-RAW-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN2.json",
    "graph_residual": "reports/F3-GRAPH-RESIDUAL-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN5.json",
    "mlp": "reports/F3-MLP-HIDDEN16-CURRENT-MANIFEST-TRAINING-EVIDENCE-2026-09-29-RERUN1.json",
}

INPUT_PATHS = {
    "source_closure": "campaigns/core-v1/learning/formal-source-closure-v7-20260929/source-closure.json",
    "source_closure_receipt": "campaigns/core-v1/learning/formal-source-closure-v7-20260929/receipt.json",
    "training_contract": "campaigns/core-v1/learning/training-contract-v1/contract.json",
    "current_manifest": "campaigns/core-v1/f3-dataset-v2.json",
    "registry": "campaigns/core-v1/registry.json",
}


class MatrixError(ValueError):
    """Malformed or inconsistent bounded input."""


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _reject_constant(token: str) -> None:
    raise MatrixError(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise MatrixError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _walk(value: Any, *, depth: int = 0) -> None:
    if depth > 64:
        raise MatrixError("JSON nesting exceeds the bounded depth")
    if value is None or isinstance(value, (bool, int, str)):
        if isinstance(value, str) and len(value.encode("utf-8")) > 2 * 1024 * 1024:
            raise MatrixError("JSON string exceeds the bounded size")
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise MatrixError("JSON contains a non-finite number")
        return
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise MatrixError("JSON object key is not a string")
            _walk(item, depth=depth + 1)
        return
    if isinstance(value, list):
        if len(value) > 8192:
            raise MatrixError("JSON array exceeds the bounded item count")
        for item in value:
            _walk(item, depth=depth + 1)
        return
    raise MatrixError(f"unsupported JSON value: {type(value).__name__}")


def _read_bytes(path: Path) -> bytes:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if not os.path.isfile(path) or before.st_nlink != 1:
            raise MatrixError(f"input must be a single-link regular file: {path}")
        if before.st_size > MAX_JSON_BYTES:
            raise MatrixError(f"input exceeds bounded size: {path}")
        raw = os.read(descriptor, MAX_JSON_BYTES + 1)
        after = os.fstat(descriptor)
        identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
        identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
        if identity_before != identity_after or len(raw) != before.st_size:
            raise MatrixError(f"input changed during bounded read: {path}")
        if len(raw) > MAX_JSON_BYTES:
            raise MatrixError(f"input exceeds bounded size: {path}")
        return raw
    finally:
        os.close(descriptor)


def _relative(path: Path, root: Path = LAB_ROOT) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _ref(path: Path) -> dict[str, Any]:
    raw = _read_bytes(path)
    return {"path": _relative(path), "bytes": len(raw), "sha256": _sha256(raw)}


def _read_json(path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    raw = _read_bytes(path)
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, MatrixError) as exc:
        raise MatrixError(f"invalid JSON input {path}: {exc}") from exc
    _walk(value)
    if not isinstance(value, dict):
        raise MatrixError(f"JSON root is not an object: {path}")
    return value, {"path": _relative(path), "bytes": len(raw), "sha256": _sha256(raw)}


def _load_input(root: Path, relative: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = root / relative
    return _read_json(path)


def _status_snapshot(lab_root: Path, registry: Mapping[str, Any]) -> dict[str, Any]:
    """Use the same read-only computation as ``core_campaign.py status``."""
    if str(lab_root) not in sys.path:
        sys.path.insert(0, str(lab_root))
    from scripts.core_campaign import completion  # local, read-only status implementation

    status = completion(dict(registry), lab_root)
    return {
        "schema": status.get("schema"),
        "can_finalize": status.get("can_finalize"),
        "checks": status.get("checks"),
        "training_runs": status.get("training_runs"),
        "expected_training_runs": status.get("expected_training_runs"),
        "missing_training_runs": status.get("missing_training_runs"),
        "missing_target_t1_case_runs": status.get("missing_target_t1_case_runs"),
        "missing_target_material_case_runs": status.get("missing_target_material_case_runs"),
        "issues": status.get("issues"),
    }


def _manifest_evidence_observation(payload: Mapping[str, Any], reference: Mapping[str, Any], model: str) -> dict[str, Any]:
    expected_contract = payload.get("expected_contract")
    expected_contract = expected_contract if isinstance(expected_contract, Mapping) else {}
    observed_model = payload.get("model") or expected_contract.get("model_kind")
    seeds = payload.get("seeds") or expected_contract.get("seeds")
    if not isinstance(seeds, list):
        seeds = sorted({row.get("seed") for row in payload.get("runs", []) if isinstance(row, Mapping)})
    return {
        "model": observed_model,
        "seeds": list(seeds),
        "schema": payload.get("schema"),
        "status": payload.get("status"),
        "source_bound": payload.get("source_bound"),
        "diagnostic_only": payload.get("diagnostic_only"),
        "formal": payload.get("formal"),
        "formal_eligible": payload.get("formal_eligible"),
        "credit": payload.get("credit"),
        "qualification_credit": payload.get("qualification_credit"),
        "formal_training_runs_counted": payload.get("formal_training_runs_counted"),
        "reference": dict(reference),
        "expected_model": model,
    }


def _scan_formal_specs(core_root: Path) -> dict[str, Any]:
    directory = core_root / "runtime/specs"
    candidate_counts = {run_id: 0 for run_id in RUN_IDS}
    formal_counts = {run_id: 0 for run_id in RUN_IDS}
    formal_paths: list[str] = []
    scan_errors: list[str] = []
    if not directory.is_dir():
        return {
            "directory": _relative(directory),
            "candidate_counts": candidate_counts,
            "formal_counts": formal_counts,
            "formal_spec_paths": formal_paths,
            "scan_errors": [f"missing directory: {_relative(directory)}"],
        }
    for path in sorted(directory.glob("*.json")):
        try:
            payload, _ = _read_json(path)
        except (OSError, MatrixError) as exc:
            scan_errors.append(f"{_relative(path)}: {exc}")
            continue
        protocol = payload.get("training_protocol")
        protocol = protocol if isinstance(protocol, Mapping) else {}
        model = protocol.get("model_kind", payload.get("model_kind"))
        seed = protocol.get("seed", payload.get("seed"))
        run_id = protocol.get("run_id", payload.get("run_id"))
        if not isinstance(run_id, str) or run_id not in RUN_IDS:
            continue
        expected_model, expected_seed_text = run_id.rsplit("-seed", 1)
        if model != expected_model:
            continue
        if seed != int(expected_seed_text):
            continue
        candidate_counts[run_id] += 1
        is_formal = (
            payload.get("formal_training") is True
            and payload.get("formal_admission") is True
            and payload.get("formal_job_count") == 1
            and payload.get("launch_allowed") is True
            and payload.get("manifest_formal_release") is True
        )
        if is_formal:
            formal_counts[run_id] += 1
            formal_paths.append(_relative(path))
    return {
        "directory": _relative(directory),
        "candidate_counts": candidate_counts,
        "formal_counts": formal_counts,
        "formal_spec_paths": sorted(formal_paths),
        "scan_errors": scan_errors,
    }


def _build_report(root: Path = LAB_ROOT, *, observed_at_utc: str | None = None) -> dict[str, Any]:
    root = root.resolve()
    core_root = root / "campaigns/core-v1"
    inputs: dict[str, Any] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for name, relative in INPUT_PATHS.items():
        payload, reference = _load_input(root, relative)
        payloads[name] = payload
        inputs[name] = reference

    evidence_payloads: dict[str, dict[str, Any]] = {}
    evidence_observations: dict[str, Any] = {}
    for model, relative in CURRENT_MANIFEST_EVIDENCE.items():
        payload, reference = _load_input(root, relative)
        evidence_payloads[model] = payload
        evidence_observations[model] = _manifest_evidence_observation(payload, reference, model)
    inputs["current_manifest_evidence"] = {
        model: evidence_observations[model]["reference"] for model in MODELS
    }

    status = _status_snapshot(root, payloads["registry"])
    closure = payloads["source_closure"]
    closure_receipt = payloads["source_closure_receipt"]
    contract = payloads["training_contract"]
    manifest = payloads["current_manifest"]
    spec_scan = _scan_formal_specs(core_root)

    root_admission = closure_receipt.get("root_admission")
    root_admission = root_admission if isinstance(root_admission, Mapping) else {}
    source_closure_observation = {
        "schema": closure.get("schema"),
        "closure_version": closure.get("closure_version"),
        "complete": closure.get("complete"),
        "formal_release": closure.get("formal_release"),
        "formal_training_allowed": closure.get("formal_training_allowed"),
        "formal_training_ready": closure.get("formal_training_ready"),
        "launch_allowed": closure.get("launch_allowed"),
        "root_admission_granted": closure.get("root_admission_granted"),
        "closure_sha256": closure.get("closure_sha256"),
        "receipt_status": closure_receipt.get("status"),
        "receipt_formal_release": closure_receipt.get("formal_release"),
        "receipt_formal_training_ready": closure_receipt.get("formal_training_ready"),
        "receipt_launch_allowed": closure_receipt.get("launch_allowed"),
        "root_admission": {
            "granted": root_admission.get("granted"),
            "status": root_admission.get("status"),
            "decision": root_admission.get("decision"),
        },
    }
    contract_matrix = contract.get("matrix")
    contract_matrix = contract_matrix if isinstance(contract_matrix, Mapping) else {}
    contract_training = contract.get("training")
    contract_training = contract_training if isinstance(contract_training, Mapping) else {}
    training_contract_observation = {
        "schema": contract.get("schema"),
        "status": contract.get("status"),
        "planning_only": (contract.get("execution_policy") or {}).get("planning_only")
        if isinstance(contract.get("execution_policy"), Mapping) else None,
        "formal_training_allowed": (contract.get("execution_policy") or {}).get("formal_training_allowed")
        if isinstance(contract.get("execution_policy"), Mapping) else None,
        "models": contract_matrix.get("models"),
        "seeds": contract_matrix.get("seeds"),
        "expected_run_count": contract_matrix.get("expected_run_count"),
        "expected_run_ids": contract_matrix.get("expected_run_ids"),
        "training": {
            key: contract_training.get(key)
            for key in ("hidden", "updates", "milestones", "optimizer", "learning_rate", "loss_centers")
        },
    }

    registered_runs = set(status.get("training_runs") or [])
    formal_release = manifest.get("formal_release") is True and closure.get("formal_release") is True
    root_trust = (
        closure.get("root_admission_granted") is True
        and root_admission.get("granted") is True
    )
    rows: list[dict[str, Any]] = []
    for run_id in RUN_IDS:
        model, seed_text = run_id.rsplit("-seed", 1)
        seed = int(seed_text)
        evidence = evidence_observations[model]
        formal_spec = spec_scan["formal_counts"].get(run_id, 0) > 0
        terminal_evidence = run_id in registered_runs
        credit = formal_spec and formal_release and root_trust and terminal_evidence
        blockers = []
        if not formal_spec:
            blockers.append("formal_spec_missing")
        if not formal_release:
            blockers.append("formal_release_missing")
        if not root_trust:
            blockers.append("root_trust_missing")
        if not terminal_evidence:
            blockers.append("formal_terminal_evidence_missing")
        if not credit:
            blockers.append("formal_credit_missing")
        rows.append({
            "run_id": run_id,
            "model": model,
            "seed": seed,
            "formal_spec": formal_spec,
            "formal_release": formal_release,
            "root_trust": root_trust,
            "terminal_evidence": terminal_evidence,
            "credit": credit,
            "credit_value": 1 if credit else 0,
            "current_manifest_evidence": {
                "path": evidence["reference"]["path"],
                "status": evidence["status"],
                "diagnostic_only": evidence["diagnostic_only"],
                "formal": evidence["formal"],
                "formal_eligible": evidence["formal_eligible"],
                "credit": evidence["credit"],
            },
            "status": "ready" if not blockers else "blocked_fail_closed",
            "blocking_reasons": blockers,
        })

    all_blocked = all(row["status"] == "blocked_fail_closed" for row in rows)
    no_spec_created = not any(row["formal_spec"] for row in rows)
    no_launch = not any(row["terminal_evidence"] for row in rows)
    return {
        "schema": SCHEMA,
        "report_id": REPORT_ID,
        "observed_at_utc": observed_at_utc or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "purpose": "shared read-only readiness matrix for Core's fixed nine formal model-seed runs",
        "scope": {"models": list(MODELS), "seeds": list(SEEDS), "run_count": len(RUN_IDS), "run_ids": list(RUN_IDS)},
        "inputs": inputs,
        "source_closure": source_closure_observation,
        "training_contract": training_contract_observation,
        "current_manifest": {
            "schema": manifest.get("schema"),
            "dataset_id": manifest.get("dataset_id"),
            "case_count": manifest.get("case_count"),
            "formal_release": manifest.get("formal_release"),
            "source_manifest_sha256": manifest.get("source_manifest_sha256"),
        },
        "current_manifest_evidence": evidence_observations,
        "core_campaign_status": status,
        "formal_spec_scan": spec_scan,
        "runs": rows,
        "decision": {
            "status": "blocked_fail_closed" if all_blocked else "partially_ready",
            "all_runs_blocked": all_blocked,
            "spec_created": False,
            "launch_allowed": False,
            "no_spec_created": no_spec_created,
            "no_launch": no_launch,
            "reason": "all nine formal runs remain blocked by missing formal release/root trust/terminal evidence/credit and no formal scheduler spec exists"
            if all_blocked else "formal launch remains disabled by the current admission evidence",
        },
        "side_effects": {
            "read_only": True,
            "trainer_imported": False,
            "training_started": False,
            "optimizer_started": False,
            "gpu_started": False,
            "queue_submitted": False,
            "worker_started": False,
            "registry_written": False,
            "ledger_written": False,
            "denominator_written": False,
            "gate_written": False,
            "completion_written": False,
            "plan_written": False,
            "update_411_written": False,
        },
        "implementation_boundary": {
            "generic_matrix_projection": True,
            "run_specific_auditor_replayed": False,
            "seed17_auditor_logic_reused": False,
            "diagnostic_evidence_promoted": False,
        },
    }


def _check_reference(reference: Any, root: Path, label: str, errors: list[str]) -> None:
    if not isinstance(reference, Mapping):
        errors.append(f"{label} reference is not an object")
        return
    path_value = reference.get("path")
    if not isinstance(path_value, str) or Path(path_value).is_absolute() or ".." in Path(path_value).parts:
        errors.append(f"{label} reference path is not portable")
        return
    path = root / path_value
    if not path.is_file():
        errors.append(f"{label} reference is missing: {path_value}")
        return
    try:
        actual = _ref(path)
    except (OSError, MatrixError) as exc:
        errors.append(f"{label} cannot be read: {exc}")
        return
    for key in ("bytes", "sha256"):
        if reference.get(key) != actual[key]:
            errors.append(f"{label} {key} mismatch")


def validate_report(report: Mapping[str, Any], root: Path = LAB_ROOT) -> list[str]:
    errors: list[str] = []
    if not isinstance(report, Mapping):
        return ["report root is not an object"]
    if report.get("schema") != SCHEMA:
        errors.append("schema mismatch")
    if report.get("report_id") != REPORT_ID:
        errors.append("report_id mismatch")
    scope = report.get("scope")
    if not isinstance(scope, Mapping):
        errors.append("scope is missing")
    else:
        if scope.get("models") != list(MODELS) or scope.get("seeds") != list(SEEDS):
            errors.append("scope model/seed matrix mismatch")
        if scope.get("run_ids") != list(RUN_IDS) or scope.get("run_count") != len(RUN_IDS):
            errors.append("scope run denominator mismatch")

    inputs = report.get("inputs")
    if not isinstance(inputs, Mapping):
        errors.append("inputs are missing")
    else:
        for name in INPUT_PATHS:
            _check_reference(inputs.get(name), root, f"input {name}", errors)
        evidence_refs = inputs.get("current_manifest_evidence")
        if not isinstance(evidence_refs, Mapping):
            errors.append("current-manifest evidence references are missing")
        else:
            for model in MODELS:
                _check_reference(evidence_refs.get(model), root, f"input evidence {model}", errors)

    def load_current_input(name: str) -> dict[str, Any] | None:
        relative = INPUT_PATHS[name]
        try:
            payload, _ = _load_input(root, relative)
            return payload
        except (OSError, MatrixError):
            return None

    closure = report.get("source_closure")
    if not isinstance(closure, Mapping):
        errors.append("source_closure observation is missing")
    else:
        for key in ("formal_release", "formal_training_allowed", "formal_training_ready", "launch_allowed", "root_admission_granted"):
            if closure.get(key) is not False:
                errors.append(f"source closure must remain closed: {key}")
        if closure.get("complete") is not True:
            errors.append("source closure completeness is not observed")
        root_admission = closure.get("root_admission")
        if not isinstance(root_admission, Mapping) or root_admission.get("granted") is not False:
            errors.append("root admission is not fail-closed")
        actual_closure = load_current_input("source_closure")
        actual_receipt = load_current_input("source_closure_receipt")
        actual_root_admission = actual_receipt.get("root_admission") if isinstance(actual_receipt, Mapping) else None
        actual_root_admission = actual_root_admission if isinstance(actual_root_admission, Mapping) else {}
        for key in ("schema", "closure_version", "complete", "formal_release", "formal_training_allowed", "formal_training_ready", "launch_allowed", "root_admission_granted", "closure_sha256"):
            if isinstance(actual_closure, Mapping) and closure.get(key) != actual_closure.get(key):
                errors.append(f"source closure observation drift: {key}")
        if isinstance(actual_receipt, Mapping):
            if closure.get("receipt_status") != actual_receipt.get("status"):
                errors.append("source closure receipt status drift")
            if closure.get("receipt_formal_release") != actual_receipt.get("formal_release"):
                errors.append("source closure receipt formal-release drift")
            if root_admission.get("granted") != actual_root_admission.get("granted"):
                errors.append("source closure root-admission drift")

    contract = report.get("training_contract")
    if not isinstance(contract, Mapping):
        errors.append("training_contract observation is missing")
    else:
        if contract.get("status") != "planning_only" or contract.get("planning_only") is not True:
            errors.append("training contract is not planning-only")
        if contract.get("formal_training_allowed") is not False:
            errors.append("training contract unexpectedly allows formal training")
        if set(contract.get("models", [])) != set(MODELS) or contract.get("seeds") != list(SEEDS):
            errors.append("training contract model/seed matrix mismatch")
        expected_contract_runs = {f"{m}-seed{s}" for m in MODELS for s in SEEDS}
        if contract.get("expected_run_count") != len(RUN_IDS) or set(contract.get("expected_run_ids", [])) != expected_contract_runs:
            errors.append("training contract expected run denominator mismatch")
        actual_contract = load_current_input("training_contract")
        if isinstance(actual_contract, Mapping):
            actual_matrix = actual_contract.get("matrix") if isinstance(actual_contract.get("matrix"), Mapping) else {}
            actual_policy = actual_contract.get("execution_policy") if isinstance(actual_contract.get("execution_policy"), Mapping) else {}
            if contract.get("status") != actual_contract.get("status") or contract.get("planning_only") != actual_policy.get("planning_only") or contract.get("formal_training_allowed") != actual_policy.get("formal_training_allowed"):
                errors.append("training contract status observation drift")
            if contract.get("models") != actual_matrix.get("models") or contract.get("seeds") != actual_matrix.get("seeds") or contract.get("expected_run_count") != actual_matrix.get("expected_run_count") or contract.get("expected_run_ids") != actual_matrix.get("expected_run_ids"):
                errors.append("training contract matrix observation drift")

    manifest = report.get("current_manifest")
    if not isinstance(manifest, Mapping) or manifest.get("formal_release") is not False:
        errors.append("current manifest is not explicitly non-formal")
    actual_manifest = load_current_input("current_manifest")
    if isinstance(actual_manifest, Mapping) and isinstance(manifest, Mapping):
        for key in ("schema", "dataset_id", "case_count", "formal_release", "source_manifest_sha256"):
            if manifest.get(key) != actual_manifest.get(key):
                errors.append(f"current manifest observation drift: {key}")

    evidence = report.get("current_manifest_evidence")
    if not isinstance(evidence, Mapping):
        errors.append("current-manifest evidence observation is missing")
    else:
        for model in MODELS:
            row = evidence.get(model)
            if not isinstance(row, Mapping):
                errors.append(f"current-manifest evidence missing for {model}")
                continue
            if row.get("expected_model") != model or row.get("model") != model:
                errors.append(f"current-manifest evidence model mismatch for {model}")
            if row.get("seeds") != list(SEEDS):
                errors.append(f"current-manifest evidence seed mismatch for {model}")
            if row.get("diagnostic_only") is not True or row.get("formal") is not False or row.get("formal_eligible") is not False:
                errors.append(f"current-manifest evidence is not diagnostic-only for {model}")
            if row.get("credit") != 0 or row.get("qualification_credit") != 0 or row.get("formal_training_runs_counted") != 0:
                errors.append(f"current-manifest evidence credit drift for {model}")
            _check_reference(row.get("reference"), root, f"current-manifest evidence {model}", errors)
            try:
                actual_payload, actual_reference = _load_input(root, row["reference"]["path"])
                actual_row = _manifest_evidence_observation(actual_payload, actual_reference, model)
                for key in ("model", "seeds", "schema", "status", "source_bound", "diagnostic_only", "formal", "formal_eligible", "credit", "qualification_credit", "formal_training_runs_counted"):
                    if row.get(key) != actual_row.get(key):
                        errors.append(f"current-manifest evidence observation drift for {model}: {key}")
            except (KeyError, OSError, MatrixError):
                pass

    status = report.get("core_campaign_status")
    if not isinstance(status, Mapping):
        errors.append("core_campaign status snapshot is missing")
    else:
        if status.get("schema") != "core.completion.v1" or status.get("can_finalize") is not False:
            errors.append("core_campaign status is not blocked")
        if status.get("training_runs") != [] or status.get("missing_training_runs") != list(RUN_IDS):
            errors.append("core_campaign formal run status drift")
        checks = status.get("checks")
        if not isinstance(checks, Mapping) or checks.get("nine_formal_training_runs") is not False:
            errors.append("core_campaign nine-run gate drift")
        actual_registry = load_current_input("registry")
        if isinstance(actual_registry, Mapping):
            try:
                actual_status = _status_snapshot(root, actual_registry)
                for key in ("schema", "can_finalize", "checks", "training_runs", "expected_training_runs", "missing_training_runs", "missing_target_t1_case_runs", "missing_target_material_case_runs", "issues"):
                    if status.get(key) != actual_status.get(key):
                        errors.append(f"core_campaign status observation drift: {key}")
            except (ImportError, OSError, TypeError, ValueError) as exc:
                errors.append(f"cannot recompute core_campaign status: {exc}")

    spec_scan = report.get("formal_spec_scan")
    if not isinstance(spec_scan, Mapping):
        errors.append("formal spec scan is missing")
    else:
        formal_counts = spec_scan.get("formal_counts")
        if formal_counts != {run_id: 0 for run_id in RUN_IDS}:
            errors.append("formal spec scan found an unexpected formal spec")
        if spec_scan.get("formal_spec_paths") != []:
            errors.append("formal spec paths must remain empty")
        actual_scan = _scan_formal_specs(root / "campaigns/core-v1")
        if spec_scan.get("formal_counts") != actual_scan.get("formal_counts") or spec_scan.get("formal_spec_paths") != actual_scan.get("formal_spec_paths"):
            errors.append("formal spec scan observation drift")

    rows = report.get("runs")
    if not isinstance(rows, list) or [row.get("run_id") for row in rows if isinstance(row, Mapping)] != list(RUN_IDS):
        errors.append("run rows do not match the fixed nine-run denominator")
    else:
        for row in rows:
            if not isinstance(row, Mapping):
                errors.append("run row is not an object")
                continue
            run_id = row.get("run_id")
            flags = ("formal_spec", "formal_release", "root_trust", "terminal_evidence", "credit")
            if any(row.get(flag) is not False for flag in flags):
                errors.append(f"{run_id} contains a non-false readiness flag")
            if row.get("credit_value") != 0 or row.get("status") != "blocked_fail_closed":
                errors.append(f"{run_id} is not zero-credit blocked")
            reasons = row.get("blocking_reasons")
            if not isinstance(reasons, list) or not set(("formal_spec_missing", "formal_release_missing", "root_trust_missing", "formal_terminal_evidence_missing", "formal_credit_missing")) <= set(reasons):
                errors.append(f"{run_id} does not carry all blocking reasons")

    decision = report.get("decision")
    if not isinstance(decision, Mapping):
        errors.append("decision is missing")
    else:
        for key in ("all_runs_blocked", "no_spec_created", "no_launch"):
            if decision.get(key) is not True:
                errors.append(f"decision {key} must be true")
        for key in ("spec_created", "launch_allowed"):
            if decision.get(key) is not False:
                errors.append(f"decision {key} must be false")

    side_effects = report.get("side_effects")
    if not isinstance(side_effects, Mapping) or any(side_effects.get(key) is not False for key in (
        "trainer_imported", "training_started", "optimizer_started", "gpu_started", "queue_submitted",
        "worker_started", "registry_written", "ledger_written", "denominator_written", "gate_written",
        "completion_written", "plan_written", "update_411_written")):
        errors.append("side-effect boundary is not fail-closed")
    boundary = report.get("implementation_boundary")
    if not isinstance(boundary, Mapping) or boundary.get("seed17_auditor_logic_reused") is not False or boundary.get("run_specific_auditor_replayed") is not False:
        errors.append("matrix must not replay the seed17 auditor")
    return errors


def _load_report(path: Path) -> dict[str, Any]:
    value, _ = _read_json(path)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=LAB_ROOT)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--write", type=Path, help="write the single matrix report")
    group.add_argument("--verify", type=Path, help="validate an existing matrix report")
    args = parser.parse_args(argv)
    root = args.root.resolve()
    if args.write is not None:
        report = _build_report(root)
        output = args.write if args.write.is_absolute() else root / args.write
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        errors = validate_report(report, root)
        if errors:
            print(json.dumps({"valid": False, "errors": errors}, ensure_ascii=False))
            return 1
        print(json.dumps({"valid": True, "output": _relative(output, root), "runs": len(report["runs"])}, ensure_ascii=False))
        return 0
    report = _load_report(args.verify if args.verify.is_absolute() else root / args.verify)
    errors = validate_report(report, root)
    print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
