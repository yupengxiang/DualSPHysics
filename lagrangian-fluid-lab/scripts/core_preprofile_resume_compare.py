#!/usr/bin/env python3
"""Read-only comparison of a Core 16->18 resume and an optional 18-step control.

The comparator consumes completed ``core.training.v1`` receipts and their
checkpoint references.  It never constructs or updates a model, opens future
state arrays, submits a job, or writes a ledger.  A resume can preserve the
construction digest while still loading a trained parameter state; these are
reported as separate identities deliberately.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import torch

try:  # The metadata-only sampling check uses HDF5 shape/time metadata.
    import h5py
except ImportError:  # pragma: no cover - the lab runtime includes h5py
    h5py = None


COMPARATOR_SCHEMA = "core.preprofile.resume_comparison.v1"
TRAINING_SCHEMA = "core.training.v1"
CHECKPOINT_SCHEMA = "core.checkpoint.v1"
EVIDENCE_SCHEMA = "core.training.evidence.v1"
INITIALIZATION_EVIDENCE_SCHEMA = "core.training.initialization_evidence.v1"
NORMALIZATION_EVIDENCE_SCHEMA = "core.training.normalization_evidence.v1"
PRIOR_EVIDENCE_SCHEMA = "core.training.prior_evidence.v1"
MODEL_KINDS = ("mlp", "graph_raw", "graph_residual")


def canonical(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), allow_nan=False)


def _jsonable(value: Any) -> Any:
    if torch.is_tensor(value):
        return value.detach().cpu().tolist()
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _failure(code: str, message: str, *, scope: str | None = None) -> dict[str, str]:
    result = {"code": str(code), "message": str(message)}
    if scope is not None:
        result["scope"] = str(scope)
    return result


def _valid_sha(value: Any) -> bool:
    if not isinstance(value, str) or len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def _resolve(value: str | Path, *, base: Path | None = None) -> Path:
    candidate = Path(value).expanduser()
    options = []
    if candidate.is_absolute():
        options.append(candidate.resolve())
    else:
        if base is not None:
            options.append((base / candidate).resolve())
        options.append((Path.cwd() / candidate).resolve())
        options.append((Path(__file__).resolve().parents[1] / candidate).resolve())
    for option in options:
        if option.is_file():
            return option
    return options[0] if options else candidate.resolve()


def _artifact_path(value: str | Path, *, receipt_path: Path) -> tuple[Path, Path | None]:
    """Resolve a receipt path and retain a missing declared path for audit."""
    declared = _resolve(value, base=receipt_path.parent)
    if declared.is_file():
        return declared, None
    sibling = receipt_path.parent / Path(value).name
    if sibling.is_file():
        return sibling, declared
    return declared, None


def _state_digest(state: Mapping[str, Any]) -> str:
    """Match ``core_learning.model_parameter_digest`` without model creation."""
    digest = hashlib.sha256()
    for name, value in sorted(state.items()):
        if not torch.is_tensor(value):
            raise TypeError(f"model state entry {name!r} is not a tensor")
        tensor = value.detach().cpu().contiguous()
        digest.update(str(name).encode())
        digest.update(b"\0")
        digest.update(str(tensor.dtype).encode())
        digest.update(b"\0")
        digest.update(json.dumps(list(tensor.shape), separators=(",", ":")).encode())
        digest.update(b"\0")
        digest.update(tensor.numpy().tobytes(order="C"))
    return digest.hexdigest()


def _load_member(source: str | Path, *, scope: str, failures: list[dict[str, str]]) -> dict[str, Any] | None:
    receipt_path = _resolve(source)
    member: dict[str, Any] = {
        "receipt_path": str(receipt_path),
        "receipt_sha256": sha256_file(receipt_path) if receipt_path.is_file() else None,
    }
    try:
        receipt = json.loads(receipt_path.read_text())
    except (OSError, ValueError) as error:
        failures.append(_failure("receipt_unreadable", str(error), scope=scope))
        return None
    if not isinstance(receipt, Mapping):
        failures.append(_failure("receipt_invalid", "receipt is not a JSON object", scope=scope))
        return None
    member["receipt"] = dict(receipt)
    checkpoint_ref = receipt.get("checkpoint")
    if not isinstance(checkpoint_ref, Mapping) or not isinstance(checkpoint_ref.get("path"), str):
        failures.append(_failure("checkpoint_reference_missing", "receipt has no checkpoint path", scope=scope))
        return member
    checkpoint_path, rebound = _artifact_path(checkpoint_ref["path"], receipt_path=receipt_path)
    checkpoint_info: dict[str, Any] = {
        "declared_path": str(checkpoint_ref["path"]),
        "path": str(checkpoint_path),
        "rebound_from_missing_path": str(rebound) if rebound else None,
        "declared_sha256": checkpoint_ref.get("sha256"),
        "declared_bytes": checkpoint_ref.get("bytes"),
    }
    if not checkpoint_path.is_file():
        failures.append(_failure("checkpoint_missing", f"checkpoint does not exist: {checkpoint_path}", scope=scope))
        member["checkpoint"] = checkpoint_info
        return member
    actual_sha = sha256_file(checkpoint_path)
    checkpoint_info["sha256"] = actual_sha
    checkpoint_info["bytes"] = checkpoint_path.stat().st_size
    if checkpoint_ref.get("sha256") != actual_sha:
        failures.append(_failure("checkpoint_hash_mismatch", "checkpoint hash differs from receipt", scope=scope))
    if checkpoint_ref.get("bytes") is not None and int(checkpoint_ref["bytes"]) != checkpoint_info["bytes"]:
        failures.append(_failure("checkpoint_size_mismatch", "checkpoint size differs from receipt", scope=scope))
    try:
        payload = torch.load(checkpoint_path, map_location="cpu", weights_only=False)
    except Exception as error:  # pragma: no cover - defensive artifact handling
        failures.append(_failure("checkpoint_unreadable", str(error), scope=scope))
        member["checkpoint"] = checkpoint_info
        return member
    if not isinstance(payload, Mapping):
        failures.append(_failure("checkpoint_invalid", "checkpoint payload is not a mapping", scope=scope))
        member["checkpoint"] = checkpoint_info
        return member
    if receipt.get("evidence") != payload.get("evidence"):
        failures.append(_failure("receipt_checkpoint_evidence_mismatch",
                                 "receipt evidence differs from checkpoint evidence", scope=scope))
    if receipt.get("evidence_status") != payload.get("evidence_status"):
        failures.append(_failure("receipt_checkpoint_evidence_status_mismatch",
                                 "receipt and checkpoint evidence_status differ", scope=scope))
    member["checkpoint"] = checkpoint_info
    member["payload"] = payload
    return member


def _check_identity(member: Mapping[str, Any], *, model_kind: str, expected_update: int,
                    scope: str, failures: list[dict[str, str]]) -> None:
    receipt = member.get("receipt", {})
    payload = member.get("payload", {})
    for key, expected in (("schema", TRAINING_SCHEMA), ("model_kind", model_kind),
                          ("seed", 17), ("run_id", f"{model_kind}-seed17"),
                          ("completed_updates", expected_update)):
        if receipt.get(key) != expected:
            failures.append(_failure("receipt_identity_mismatch",
                                     f"receipt {key}={receipt.get(key)!r}, expected {expected!r}", scope=scope))
    if receipt.get("checkpoint_verified") is not True:
        failures.append(_failure("checkpoint_not_verified", "receipt does not attest checkpoint_verified=true", scope=scope))
    if receipt.get("evidence_status") != "complete" or payload.get("evidence_status") != "complete":
        failures.append(_failure("evidence_incomplete", "receipt/checkpoint evidence is not complete", scope=scope))
    for key, expected in (("schema", CHECKPOINT_SCHEMA), ("model_kind", model_kind),
                          ("seed", 17), ("update", expected_update)):
        if payload.get(key) != expected:
            failures.append(_failure("checkpoint_identity_mismatch",
                                     f"checkpoint {key}={payload.get(key)!r}, expected {expected!r}", scope=scope))


def _history_rows(member: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    receipt = member.get("receipt", {})
    payload = member.get("payload", {})
    history = receipt.get("history", payload.get("history", []))
    return [row for row in history if isinstance(row, Mapping)] if isinstance(history, list) else []


def _manifest_asset(root: Path, value: Any) -> Path:
    if isinstance(value, Mapping):
        value = value.get("path")
    if not isinstance(value, str):
        raise ValueError("manifest asset has no path")
    candidate = Path(value)
    if candidate.is_absolute():
        return candidate
    return (root / candidate).resolve()


def _expected_following_samples(base_sampler: Mapping[str, Any], *, manifest: str | Path,
                                data_root: str | Path | None, base_update: int,
                                resumed_update: int) -> list[dict[str, Any]]:
    """Advance a copy of the base RNG using HDF5 shapes/times only."""
    if h5py is None:
        raise RuntimeError("h5py is unavailable")
    manifest_path = _resolve(manifest)
    payload = json.loads(manifest_path.read_text())
    root = Path(data_root).expanduser().resolve() if data_root is not None else manifest_path.parent
    train = [row for row in payload.get("cases", []) if row.get("split") == "train"]
    expected_case_ids = list(base_sampler.get("case_ids", []))
    rows_by_id = {str(row.get("case_id")): row for row in train}
    if list(rows_by_id) != expected_case_ids:
        raise ValueError("manifest train case order differs from checkpoint sampler")
    transitions: list[tuple[str, int]] = []
    counts: dict[str, int] = {}
    for case_id in expected_case_ids:
        row = rows_by_id[case_id]
        path = _manifest_asset(root, row.get("hdf5"))
        with h5py.File(path, "r") as handle:
            frame_count = int(len(handle["time"]))
            counts[case_id] = int(handle["particle_id"].shape[0])
        if frame_count < 2 or counts[case_id] < 1:
            raise ValueError(f"invalid train metadata for {case_id}")
        transitions.extend((case_id, frame) for frame in range(frame_count - 1))
    state = copy.deepcopy(base_sampler.get("rng_state"))
    if not isinstance(state, Mapping):
        raise ValueError("base sampler has no RNG state")
    rng = np.random.default_rng()
    rng.bit_generator.state = state
    centers_per_update = int(base_sampler.get("centers_per_update", 0))
    result = []
    for update in range(base_update + 1, resumed_update + 1):
        case_id, frame = transitions[int(rng.integers(len(transitions)))]
        center_count = min(centers_per_update, counts[case_id])
        rng.choice(counts[case_id], center_count, replace=False)
        result.append({"update": update, "case_id": case_id, "frame": int(frame)})
    return result, _jsonable(rng.bit_generator.state)


def _sampling_check(base: Mapping[str, Any], resumed: Mapping[str, Any], *, manifest: str | Path | None,
                    data_root: str | Path | None, base_update: int, resumed_update: int,
                    failures: list[dict[str, str]]) -> dict[str, Any]:
    base_payload = base.get("payload", {})
    resumed_payload = resumed.get("payload", {})
    base_sampler = base_payload.get("sampler_state")
    resumed_sampler = resumed_payload.get("sampler_state")
    result: dict[str, Any] = {
        "metadata_only": True,
        "base_draws": base_sampler.get("draws") if isinstance(base_sampler, Mapping) else None,
        "resumed_draws": resumed_sampler.get("draws") if isinstance(resumed_sampler, Mapping) else None,
        "continuation": "not_run",
    }
    if not isinstance(base_sampler, Mapping) or not isinstance(resumed_sampler, Mapping):
        failures.append(_failure("sampler_state_missing", "base or resumed checkpoint has no sampler state", scope="sampling"))
        return result
    if int(base_sampler.get("draws", -1)) != base_update:
        failures.append(_failure("base_sampler_draw_count_mismatch", "base sampler draws do not equal base update", scope="sampling"))
    if int(resumed_sampler.get("draws", -1)) != resumed_update:
        failures.append(_failure("resumed_sampler_draw_count_mismatch", "resumed sampler draws do not equal resumed update", scope="sampling"))
    for key in ("version", "seed", "case_ids", "centers_per_update"):
        if base_sampler.get(key) != resumed_sampler.get(key):
            failures.append(_failure("sampler_binding_changed", f"sampler {key} changed across resume", scope="sampling"))
    if base_sampler.get("seed") != 17 or resumed_sampler.get("seed") != 17:
        failures.append(_failure("sampler_seed_mismatch", "sampler seed is not the paired seed 17", scope="sampling"))
    base_history = _history_rows(base)
    resumed_history = _history_rows(resumed)
    base_prefix = [dict(row) for row in resumed_history if int(row.get("update", -1)) <= base_update]
    if base_history != base_prefix:
        failures.append(_failure("history_prefix_changed", "resumed history does not preserve the base history prefix", scope="sampling"))
    resumed_updates = {int(row.get("update", -1)): row for row in resumed_history}
    if any(update not in resumed_updates for update in range(base_update + 1, resumed_update + 1)):
        failures.append(_failure("resumed_history_missing", "resumed history lacks every post-checkpoint update", scope="sampling"))
    if manifest is None:
        failures.append(_failure("sampling_continuation_unverified",
                                 "a manifest is required to replay post-checkpoint sampler draws", scope="sampling"))
        return result
    try:
        expected, expected_final_rng_state = _expected_following_samples(
            base_sampler, manifest=manifest, data_root=data_root,
            base_update=base_update, resumed_update=resumed_update,
        )
    except (OSError, KeyError, TypeError, ValueError, RuntimeError) as error:
        failures.append(_failure("sampling_replay_error", str(error), scope="sampling"))
        result["error"] = str(error)
        return result
    result["expected_post_checkpoint_samples"] = expected
    result["observed_post_checkpoint_samples"] = [
        {"update": update, "case_id": resumed_updates[update].get("case_id"),
         "frame": resumed_updates[update].get("frame")}
        for update in range(base_update + 1, resumed_update + 1)
        if update in resumed_updates
    ]
    if result["expected_post_checkpoint_samples"] != result["observed_post_checkpoint_samples"]:
        failures.append(_failure("sampler_continuation_mismatch",
                                 "post-checkpoint case/frame draws do not follow the base sampler RNG state",
                                 scope="sampling"))
    elif expected_final_rng_state != _jsonable(resumed_sampler.get("rng_state")):
        failures.append(_failure("sampler_rng_state_mismatch",
                                 "resumed sampler RNG state is not the deterministic continuation of base state",
                                 scope="sampling"))
    else:
        result["continuation"] = "passed"
    return result


def _compare_continuous(resumed: Mapping[str, Any], continuous: Mapping[str, Any], *,
                        model_kind: str, expected_update: int, failures: list[dict[str, str]]) -> dict[str, Any]:
    """Compare a separately executed 18-step same-seed control when supplied."""
    _check_identity(continuous, model_kind=model_kind, expected_update=expected_update,
                    scope="continuous", failures=failures)
    result: dict[str, Any] = {
        "status": "not_assessed",
        "claim": "not_claimed",
        "reason": "no continuous 18-step receipt supplied",
    }
    if continuous.get("payload") is None:
        return result
    resumed_payload = resumed.get("payload", {})
    control_payload = continuous.get("payload", {})
    checks = {
        "optimizer_state": (
            isinstance(resumed_payload.get("optimizer_state"), Mapping)
            and isinstance(control_payload.get("optimizer_state"), Mapping)
            and _jsonable(resumed_payload["optimizer_state"])
            == _jsonable(control_payload["optimizer_state"])
        ),
        "normalization": resumed_payload.get("normalization") == control_payload.get("normalization"),
        "sampler_state": _jsonable(resumed_payload.get("sampler_state")) == _jsonable(control_payload.get("sampler_state")),
        "rng_state": _jsonable(resumed_payload.get("rng_state")) == _jsonable(control_payload.get("rng_state")),
        "history": _history_rows(resumed) == _history_rows(continuous),
    }
    try:
        resumed_digest = _state_digest(resumed_payload.get("model_state", resumed_payload.get("state_dict", {})))
        control_digest = _state_digest(control_payload.get("model_state", control_payload.get("state_dict", {})))
    except (TypeError, AttributeError, ValueError) as error:
        failures.append(_failure("continuous_state_digest_error", str(error), scope="continuous"))
        checks["model_state"] = False
    else:
        checks["model_state"] = resumed_digest == control_digest
        result["resumed_state_digest"] = resumed_digest
        result["continuous_state_digest"] = control_digest
    resumed_evidence = resumed.get("receipt", {}).get("evidence", {})
    control_evidence = continuous.get("receipt", {}).get("evidence", {})
    checks["initialization_digest"] = (
        isinstance(resumed_evidence, Mapping) and isinstance(control_evidence, Mapping)
        and resumed_evidence.get("initialization", {}).get("parameter_digest")
        == control_evidence.get("initialization", {}).get("parameter_digest")
    )
    result["checks"] = checks
    if all(checks.values()):
        result["status"] = "pass"
        result["claim"] = "resume_matches_same_seed_continuous_18_step_control"
        result.pop("reason", None)
    else:
        result["status"] = "fail"
        result["claim"] = "no_equivalence_claim"
        failures.append(_failure("continuous_equivalence_mismatch",
                                 "resumed 18-step output differs from the same-seed continuous control",
                                 scope="continuous"))
    return result


def compare_resume(base: str | Path, resumed: str | Path, *, model_kind: str | None = None,
                   manifest: str | Path | None = None, data_root: str | Path | None = None,
                   continuous: str | Path | None = None, base_update: int = 16,
                   resumed_update: int = 18, output: str | Path | None = None) -> dict[str, Any]:
    failures: list[dict[str, str]] = []
    base_member = _load_member(base, scope="base", failures=failures)
    resumed_member = _load_member(resumed, scope="resumed", failures=failures)
    inferred_kind = model_kind
    for member in (base_member, resumed_member):
        if inferred_kind is None and member is not None:
            inferred_kind = member.get("receipt", {}).get("model_kind")
    if inferred_kind not in MODEL_KINDS:
        failures.append(_failure("model_kind_missing", "model kind must be one of the three Core baselines", scope="identity"))
        inferred_kind = str(inferred_kind or "unknown")
    if base_member is not None:
        _check_identity(base_member, model_kind=inferred_kind, expected_update=base_update,
                        scope="base", failures=failures)
    if resumed_member is not None:
        _check_identity(resumed_member, model_kind=inferred_kind, expected_update=resumed_update,
                        scope="resumed", failures=failures)
    result: dict[str, Any] = {
        "schema": COMPARATOR_SCHEMA,
        "status": "fail",
        "model_kind": inferred_kind,
        "seed": 17,
        "base_update": int(base_update),
        "resumed_update": int(resumed_update),
        "read_only": True,
        "writes_ledger": False,
        "gpu_started": False,
        "base": {"receipt_path": base_member.get("receipt_path") if base_member else None,
                 "checkpoint": base_member.get("checkpoint") if base_member else None},
        "resumed": {"receipt_path": resumed_member.get("receipt_path") if resumed_member else None,
                     "checkpoint": resumed_member.get("checkpoint") if resumed_member else None},
        "failures": failures,
    }
    if base_member is not None and resumed_member is not None:
        base_payload = base_member.get("payload", {})
        resumed_payload = resumed_member.get("payload", {})
        base_receipt = base_member.get("receipt", {})
        resumed_receipt = resumed_member.get("receipt", {})
        try:
            base_state_digest = _state_digest(base_payload.get("model_state", base_payload.get("state_dict", {})))
            resumed_state_digest = _state_digest(resumed_payload.get("model_state", resumed_payload.get("state_dict", {})))
        except (TypeError, AttributeError, ValueError) as error:
            failures.append(_failure("state_digest_error", str(error), scope="identity"))
            base_state_digest = resumed_state_digest = None
        base_evidence = base_receipt.get("evidence")
        resumed_evidence = resumed_receipt.get("evidence")
        base_init = base_evidence.get("initialization", {}) if isinstance(base_evidence, Mapping) else {}
        resumed_init = resumed_evidence.get("initialization", {}) if isinstance(resumed_evidence, Mapping) else {}
        base_norm = base_payload.get("normalization")
        resumed_norm = resumed_payload.get("normalization")
        norm_checks = {
            "checkpoint_equal": base_norm == resumed_norm,
            "receipt_equal": base_receipt.get("normalization") == resumed_receipt.get("normalization"),
            "evidence_equal": (
                isinstance(base_evidence, Mapping) and isinstance(resumed_evidence, Mapping)
                and base_evidence.get("normalization") == resumed_evidence.get("normalization")
            ),
            "evidence_schema": (
                isinstance(base_evidence, Mapping) and isinstance(resumed_evidence, Mapping)
                and base_evidence.get("normalization", {}).get("schema") == NORMALIZATION_EVIDENCE_SCHEMA
                and resumed_evidence.get("normalization", {}).get("schema") == NORMALIZATION_EVIDENCE_SCHEMA
            ),
            "train_only": (
                isinstance(resumed_evidence, Mapping)
                and resumed_evidence.get("normalization", {}).get("source_split") == "train"
            ),
        }
        if not all(norm_checks.values()):
            failures.append(_failure("normalization_not_continuous", "normalization arrays/audit changed across resume", scope="normalization"))
        init_checks = {
            "base_captured": base_init.get("status") == "captured",
            "resumed_captured": resumed_init.get("status") == "captured",
            "initialization_schema": (
                base_init.get("schema") == INITIALIZATION_EVIDENCE_SCHEMA
                and resumed_init.get("schema") == INITIALIZATION_EVIDENCE_SCHEMA
            ),
            "initial_digest_equal": base_init.get("parameter_digest") == resumed_init.get("parameter_digest"),
            "loaded_digest_is_base16": resumed_init.get("resume", {}).get("loaded_parameter_digest") == base_state_digest,
            "loaded_digest_is_initial_false": resumed_init.get("resume", {}).get("loaded_digest_is_initial") is False,
            "initial_digest_reused": resumed_init.get("resume", {}).get("initial_digest_reused") is True,
            "resume_start_update": resumed_init.get("resume", {}).get("start_update") == base_update,
        }
        if not all(init_checks.values()):
            failures.append(_failure("resume_initialization_evidence_mismatch",
                                     "construction and loaded-trained-state digests do not satisfy the resume contract",
                                     scope="initialization"))
        if resumed_state_digest == base_state_digest:
            failures.append(_failure("resume_state_unchanged", "resumed checkpoint has no parameter-state change after extra updates", scope="resumed"))
        prior_base = base_evidence.get("residual_prior", {}) if isinstance(base_evidence, Mapping) else {}
        prior_resumed = resumed_evidence.get("residual_prior", {}) if isinstance(resumed_evidence, Mapping) else {}
        prior_checks = {
            "prior_schema": (
                prior_base.get("schema") == PRIOR_EVIDENCE_SCHEMA
                and prior_resumed.get("schema") == PRIOR_EVIDENCE_SCHEMA
            ),
            "enabled_matches_model": bool(prior_resumed.get("enabled")) == (inferred_kind == "graph_residual"),
            "base_calls": prior_base.get("execution_calls") == base_update if inferred_kind == "graph_residual" else prior_base.get("execution_calls", 0) == 0,
            "resumed_calls": prior_resumed.get("execution_calls") == resumed_update if inferred_kind == "graph_residual" else prior_resumed.get("execution_calls", 0) == 0,
            "history_complete": prior_resumed.get("history_complete") is True,
            "finite": prior_resumed.get("finite") is True,
        }
        if inferred_kind == "graph_residual":
            prior_checks.update({
                "rows_accumulate": int(prior_resumed.get("rows", -1)) > int(prior_base.get("rows", -1)),
                "dx_sum_non_decreasing": float(prior_resumed.get("dx_abs_sum_m", -1.0)) >= float(prior_base.get("dx_abs_sum_m", -1.0)),
                "dv_sum_non_decreasing": float(prior_resumed.get("dv_abs_sum_mps", -1.0)) >= float(prior_base.get("dv_abs_sum_mps", -1.0)),
            })
        if not all(prior_checks.values()):
            failures.append(_failure("prior_evidence_not_accumulated",
                                     "residual-prior execution evidence does not cover the resumed update frontier",
                                     scope="residual_prior"))
        result["initialization"] = {"checks": init_checks, "base_state_digest": base_state_digest,
                                     "resumed_state_digest": resumed_state_digest}
        result["normalization"] = norm_checks
        result["residual_prior"] = prior_checks
        result["sampling"] = _sampling_check(
            base_member, resumed_member, manifest=manifest, data_root=data_root,
            base_update=base_update, resumed_update=resumed_update, failures=failures,
        )
        if continuous is None:
            result["continuous_equivalence"] = {
                "status": "not_assessed", "claim": "not_claimed",
                "reason": "no same-seed continuous 18-step receipt supplied",
            }
        else:
            continuous_member = _load_member(continuous, scope="continuous", failures=failures)
            if continuous_member is None:
                result["continuous_equivalence"] = {
                    "status": "fail", "claim": "no_equivalence_claim",
                    "reason": "continuous receipt could not be loaded",
                }
            else:
                result["continuous_equivalence"] = _compare_continuous(
                    resumed_member, continuous_member, model_kind=inferred_kind,
                    expected_update=resumed_update, failures=failures,
                )
    else:
        result["continuous_equivalence"] = {
            "status": "not_assessed", "claim": "not_claimed",
            "reason": "base/resumed artifacts unavailable",
        }
    result["failure_count"] = len(failures)
    result["status"] = "pass" if not failures else "fail"
    if output is not None:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return result


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True, help="base 16-update training receipt JSON")
    parser.add_argument("--resumed", required=True, help="resumed 18-update training receipt JSON")
    parser.add_argument("--model", choices=MODEL_KINDS)
    parser.add_argument("--manifest", help="portable manifest for deterministic post-checkpoint sampler replay")
    parser.add_argument("--data-root")
    parser.add_argument("--continuous", help="optional same-seed continuous 18-update receipt JSON")
    parser.add_argument("--base-update", type=int, default=16)
    parser.add_argument("--resumed-update", type=int, default=18)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    report = compare_resume(
        args.base, args.resumed, model_kind=args.model, manifest=args.manifest,
        data_root=args.data_root, continuous=args.continuous,
        base_update=args.base_update, resumed_update=args.resumed_update,
        output=args.output,
    )
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(_cli())
