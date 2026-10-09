#!/usr/bin/env python3
"""ROOT191 V3 callable typed-only, model-free evaluator.

V3 is the forward interface for the *successful* ROOT200 JSON-only proof.  It
keeps the generic ``ds02.execution-receipt.v1`` as the completed guard report;
ROOT200 did not emit a second parent report or a ``closedledger`` field.  The
small ROOT200 verification checkpoint supplies the independent same-ledger,
fee-closed and reservation-released evidence.

The builder and ``validate`` command read only bounded JSON/code metadata.  The
``run`` command is the first command in this chain that opens the bound V16
JSON, and it must be started by the already-reserved parent.  It invokes the
existing V12 semantic validator and the existing typed-only operator scorer;
HDF5, BI4, native frames, CFD, and models remain forbidden.  QI/QN/QE and all
raw-to-typed/cold-replay credit remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Mapping, Sequence

SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V2_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v2.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
V1_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"

REQUEST_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v3"
ROOT200_RECEIPT_SCHEMA = "ds02.execution-receipt.v1"
ROOT200_CHECKPOINT_SCHEMA = "ds02.stage2.root-actual-verification.v1"
ROOT200_PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
ROOT200_WRAPPER_SCHEMA = "ds02.request.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024
MAX_RESULT_BYTES = 100 * 1024 * 1024
WRAPPER_SUFFIX = "-root-forward-030-001"
SUPPORTED_SOURCE_ROOTS = ("ROOT197", "ROOT200")
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
TYPED_H5_SHA = "2a2ef5cf5c0e1f164018466fa4815a4465ab72dbf1071bf60e76c33657288664"
TYPED_H5_BYTES = 1191110528
PROFILE_SHA = "de4f7ed699149424506216b30a2784750d54d6cc359fbfe9b9da3d299d7e5507"
COHORT_COUNT = 21114
COHORT_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
DENOMINATOR_KG = 21.114001002861187
LATER_MISSING_KG = 0.003000000142492354


class Root191V3Error(RuntimeError):
    """A strict ROOT191 V3 binding, semantic, or execution error."""


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Root191V3Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_module(V2_SCRIPT, "ds02_bound_root191_v2_for_v3")
V8 = _load_module(V8_SCRIPT, "ds02_bound_root191_v8_for_v3")
V12 = _load_module(V12_SCRIPT, "ds02_bound_root191_v12_for_v3")
EVALUATOR = _load_module(V1_EVALUATOR_SCRIPT, "ds02_bound_root191_typed_evaluator_v1_for_v3")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V2.canonical_sha(value)


def sha256_file(path: Path | str, *, max_bytes: int = MAX_METADATA_BYTES) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if total > max_bytes:
                    raise Root191V3Error(f"file exceeds bounded hash limit: {target}")
                digest.update(block)
    except OSError as error:
        raise Root191V3Error(f"cannot hash {target}: {error}") from error
    return digest.hexdigest()


def _file(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root191V3Error(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Root191V3Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise Root191V3Error(f"{role} exceeds the bounded metadata limit: {target}")
    return target.resolve()


def _json(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    path = _file(value, role, max_bytes=max_bytes)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root191V3Error(f"cannot read {role}: {error}") from error
    if not isinstance(parsed, dict):
        raise Root191V3Error(f"{role} must be a JSON object")
    return path, parsed


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise Root191V3Error(f"{role} must be a lowercase SHA-256")
    return value


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise Root191V3Error(f"{role} must keep QI/QN/QE UNKNOWN")


def _new_id(value: Any, role: str, marker: str = "ROOT191") -> str:
    if not isinstance(value, str) or not value or marker.lower() not in value.lower():
        raise Root191V3Error(f"{role} must carry the {marker} forward identity")
    return value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise Root191V3Error(f"refusing to overwrite V3 output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return target


def _load_pair(inner_path: Path | str, wrapper_path: Path | str) -> dict[str, Any]:
    """Reuse V2's exact ROOT197/ROOT200 inner/outer identity join."""
    try:
        return V2._load_pair(inner_path, wrapper_path)
    except Exception as error:
        raise Root191V3Error(f"ROOT200 inner/outer join failed: {error}") from error


def _request_hashes(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            name = str(key).lower()
            if isinstance(child, str) and len(child) == 64 and all(ch in HEX64 for ch in child):
                if "request" in name and ("sha" in name or name in {"sha256", "file_sha256", "canonical_sha256"}):
                    found.add(child)
            if isinstance(child, Mapping):
                for child_key in ("sha256", "file_sha256", "canonical_sha256", "request_sha256"):
                    candidate = child.get(child_key)
                    if isinstance(candidate, str) and len(candidate) == 64 and all(ch in HEX64 for ch in candidate):
                        if "request" in name or name in {"parent", "binding", "receipt", "executor", "charge"}:
                            found.add(candidate)
                found.update(_request_hashes(child))
            elif isinstance(child, list):
                found.update(_request_hashes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_request_hashes(child))
    return found


def _producer_artifact(path: Path | str, role: str, request_file_sha: str, *, require_closed: bool) -> dict[str, Any]:
    target, value = _json(path, role)
    if value.get("status") is not None:
        status = str(value["status"]).upper()
        if any(word in status for word in ("FAIL", "ERROR", "CANCEL", "ABORT", "TIMEOUT")):
            raise Root191V3Error(f"{role} has a failed terminal status")
        if not any(word in status for word in ("COMPLETE", "COMPLETED", "PASS", "SUCCESS", "VERIFIED", "CLOSED")):
            raise Root191V3Error(f"{role} has no completed terminal status")
    candidates = _request_hashes(value)
    direct = value.get("request_sha256")
    if isinstance(direct, str):
        candidates.add(direct)
    request = value.get("request")
    if isinstance(request, Mapping):
        for key in ("sha256", "file_sha256", "request_sha256"):
            if isinstance(request.get(key), str):
                candidates.add(request[key])
    if request_file_sha not in candidates:
        raise Root191V3Error(f"{role} is not joined to the producer request file SHA")
    if require_closed:
        charge = value.get("charge")
        closed = bool(value.get("ledger_mutated") is True)
        if isinstance(charge, Mapping):
            closed = closed or str(charge.get("status", "")).upper() in {"COMPLETED", "CLOSED", "APPLIED", "SUCCESS"}
        closed = closed or str(value.get("terminal_status", "")).lower() in {"completed", "closed", "success"}
        if not closed:
            # A checkpoint may express the closed charge as parent_charge.
            parent_charge = value.get("parent_charge") or value.get("parent_charge_original")
            closed = isinstance(parent_charge, Mapping) and str(parent_charge.get("status", "")).lower() in {"completed", "closed", "success"}
        if not closed and value.get("parent_reservation_released") is True and value.get("repeat_fee_idempotent") is True:
            closed = True
        if not closed:
            raise Root191V3Error(f"{role} lacks explicit completed charge evidence")
    return {"path": str(target), "file_sha256": sha256_file(target), "schema": value.get("schema"),
            "status": value.get("status"), "request_sha256": request_file_sha}


def _validate_root200_receipt(path: Path | str, pair: Mapping[str, Any]) -> dict[str, Any]:
    receipt_path, receipt = _json(path, "ROOT200 generic execution receipt")
    if receipt.get("schema") != ROOT200_RECEIPT_SCHEMA:
        raise Root191V3Error("ROOT200 guard report is not ds02.execution-receipt.v1")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0 or receipt.get("termination_reason") is not None:
        raise Root191V3Error("ROOT200 generic receipt is not a successful terminal execution")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not False:
        raise Root191V3Error("ROOT200 generic receipt model/CFD flags are not closed")
    _unknown(receipt.get("qualification"), "ROOT200 receipt qualification")
    request = receipt.get("request")
    if not isinstance(request, Mapping) or request.get("schema") != ROOT200_WRAPPER_SCHEMA:
        raise Root191V3Error("ROOT200 generic receipt request is missing")
    if request.get("case_id") != pair["case_id"] or request.get("attempt_id") != pair["outer_attempt"]:
        raise Root191V3Error("ROOT200 receipt request identity differs from wrapper")
    wrapper_file_sha = pair["wrapper_file_sha"]
    if receipt.get("request_sha256") != wrapper_file_sha:
        raise Root191V3Error("ROOT200 receipt request_sha256 is not the wrapper file SHA")
    terminal = receipt.get("terminal_storage_guard")
    if not isinstance(terminal, Mapping) or terminal.get("status") != "passed":
        raise Root191V3Error("ROOT200 receipt lacks a passed terminal storage guard")
    if terminal.get("actual_bytes") != receipt.get("bytes") or terminal.get("excess_bytes") != 0:
        raise Root191V3Error("ROOT200 receipt terminal bytes do not close the storage guard")
    return {
        "path": str(receipt_path), "file_sha256": sha256_file(receipt_path),
        "schema": receipt["schema"], "status": receipt["status"],
        "request_file_sha256": wrapper_file_sha,
        "cpu_core_seconds": receipt.get("cpu_core_seconds"),
        "bytes": receipt.get("bytes"),
        "terminal_storage_guard": dict(terminal),
    }


def _validate_root200_checkpoint(path: Path | str, pair: Mapping[str, Any], receipt: Mapping[str, Any],
                                 proof_path: Path) -> dict[str, Any]:
    checkpoint_path, checkpoint = _json(path, "ROOT200 actual verification checkpoint")
    if checkpoint.get("schema") != ROOT200_CHECKPOINT_SCHEMA:
        raise Root191V3Error("ROOT200 checkpoint schema differs")
    if not str(checkpoint.get("status", "")).startswith("VERIFIED_ACTUAL_F2_FRESH_V16_JSON_PROOF_V12"):
        raise Root191V3Error("ROOT200 checkpoint is not the successful V12 proof verification")
    if checkpoint.get("request") != str(pair["wrapper_path"]):
        raise Root191V3Error("ROOT200 checkpoint request path differs from wrapper")
    if checkpoint.get("request_sha256") != pair["wrapper_file_sha"]:
        raise Root191V3Error("ROOT200 checkpoint request SHA is not the wrapper file SHA")
    if checkpoint.get("receipt") != receipt["path"] or checkpoint.get("receipt_sha256") != receipt["file_sha256"]:
        raise Root191V3Error("ROOT200 checkpoint receipt binding differs")
    proof_sha = sha256_file(proof_path)
    if checkpoint.get("fresh_proof") != str(proof_path) or checkpoint.get("fresh_proof_file_sha256") != proof_sha:
        raise Root191V3Error("ROOT200 checkpoint fresh-proof binding differs")
    binding = checkpoint.get("consumer_request_binding")
    if not isinstance(binding, Mapping):
        raise Root191V3Error("ROOT200 checkpoint consumer binding is missing")
    if (binding.get("path") != str(pair["inner_path"]) or binding.get("sha256") != pair["inner_file_sha"] or
            binding.get("canonical_sha256") != pair["inner_canonical_sha"]):
        raise Root191V3Error("ROOT200 checkpoint inner request file/canonical join differs")
    charge = checkpoint.get("parent_charge")
    if not isinstance(charge, Mapping) or charge.get("status") != "completed":
        raise Root191V3Error("ROOT200 checkpoint has no completed parent charge")
    if checkpoint.get("guarded_receipt_status") != "completed" or checkpoint.get("parent_reservation_released") is not True:
        raise Root191V3Error("ROOT200 checkpoint terminal lifecycle is not closed")
    if checkpoint.get("repeat_fee_idempotent") is not True:
        raise Root191V3Error("ROOT200 checkpoint lacks repeat-fee idempotence evidence")
    if checkpoint.get("fresh_cold_credit") is not False or checkpoint.get("H5_BI4_read_by_root") is not False:
        raise Root191V3Error("ROOT200 checkpoint grants forbidden cold/content credit")
    _unknown(checkpoint.get("scientific_qualification"), "ROOT200 checkpoint qualification")
    cpu = checkpoint.get("full_systemd_cpu_seconds")
    receipt_cpu = receipt.get("cpu_core_seconds")
    if not isinstance(cpu, (int, float)) or not isinstance(receipt_cpu, (int, float)) or float(cpu) < float(receipt_cpu):
        raise Root191V3Error("ROOT200 checkpoint CPU evidence is not a conservative terminal bound")
    return {"path": str(checkpoint_path), "file_sha256": sha256_file(checkpoint_path),
            "schema": checkpoint["schema"], "status": checkpoint["status"],
            "parent_charge": dict(charge), "full_systemd_cpu_seconds": float(cpu),
            "repeat_fee_idempotent": True}


def _validate_v12_proof_v3(path: Path | str, pair: Mapping[str, Any]) -> dict[str, Any]:
    proof_path, proof = _json(path, "ROOT200 fresh V12 proof")
    if proof.get("schema") != ROOT200_PROOF_SCHEMA or proof.get("sha256") != canonical_sha(proof):
        raise Root191V3Error("ROOT200 fresh V12 proof is not canonical V8")
    if proof.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise Root191V3Error("ROOT200 fresh V12 proof is not complete")
    _unknown(proof.get("quality"), "ROOT200 proof quality")
    _unknown(proof.get("qualification"), "ROOT200 proof qualification")
    execution = proof.get("execution")
    if not isinstance(execution, Mapping) or execution.get("hdf5_or_bi4_content_read") is not False or execution.get("raw_opened") is not False:
        raise Root191V3Error("ROOT200 proof is not JSON-only")
    adapter = proof.get("v12_semantic_scope_adapter")
    if not isinstance(adapter, Mapping) or adapter.get("normalized_for_v8_only") is not True:
        raise Root191V3Error("ROOT200 proof V12 adapter is missing")
    sidecar = pair["sidecar_path"]
    if adapter.get("sidecar_sha256") != sha256_file(sidecar):
        raise Root191V3Error("ROOT200 proof sidecar SHA differs")
    request = proof.get("request")
    if not isinstance(request, Mapping) or Path(str(request.get("path"))).expanduser().resolve() != pair["inner_path"].resolve():
        raise Root191V3Error("ROOT200 proof points at a different inner request")
    # The V12 producer writes the inner *file* SHA here.  The canonical SHA is
    # a separate inner request field and is checked independently below.
    if request.get("sha256") != pair["inner_file_sha"]:
        raise Root191V3Error("ROOT200 proof request.sha256 must be the inner file SHA")
    if request.get("canonical_sha256", pair["inner_canonical_sha"]) != pair["inner_canonical_sha"]:
        raise Root191V3Error("ROOT200 proof request canonical SHA differs")
    result = pair["inner"].get("result")
    source_result = proof.get("source_result")
    if not isinstance(result, Mapping) or not isinstance(source_result, Mapping):
        raise Root191V3Error("ROOT200 proof result binding is missing")
    if (source_result.get("sha256") != result.get("sha256") or source_result.get("bytes") != result.get("bytes") or
            source_result.get("content_sha_verified") is not True):
        raise Root191V3Error("ROOT200 proof result binding differs")
    source = proof.get("source_binding")
    if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != CURRENT_SHA:
        raise Root191V3Error("ROOT200 proof CURRENT binding differs")
    return {"path": str(proof_path), "file_sha256": sha256_file(proof_path),
            "canonical_sha256": proof["sha256"], "schema": proof["schema"],
            "status": proof["status"], "result_sha256": result.get("sha256"),
            "result_bytes": result.get("bytes"), "request_file_sha256": pair["inner_file_sha"]}


def _validate_frozen(path: Path | str) -> dict[str, Any]:
    frozen_path, frozen = _json(path, "source-frozen V15 request")
    if frozen.get("schema") != "ds02.stage2.f2-s1-replay-request.v15":
        raise Root191V3Error("source-frozen request is not V15")
    if frozen.get("model_invoked") is not False or frozen.get("qualification") != UNKNOWN:
        raise Root191V3Error("source-frozen V15 request is not model-free UNKNOWN")
    try:
        # This validates the actual V15 observer/source contract and H5 stat
        # without reading H5 content.  The full V16 payload is never opened by
        # the metadata builder.
        frozen_validation = EVALUATOR.V3.v2.validate_frozen_request(frozen)
    except Exception as error:
        raise Root191V3Error(f"source-frozen V15 request failed strict validation: {error}") from error
    return {"path": str(frozen_path), "file_sha256": sha256_file(frozen_path),
            "schema": frozen["schema"], "request_id": frozen.get("request_id"),
            "observer_profile_sha256": frozen.get("observer_profile", {}).get("sha256"),
            "validation": frozen_validation}


def _build_request(*, root200_inner: Path, root200_wrapper: Path, root200_receipt: Path,
                   root200_checkpoint: Path, root200_v12_proof: Path,
                   producer_request: Path, producer_parent_report: Path,
                   producer_receipt: Path, producer_root_proof: Path,
                   frozen_request: Path, output: Path, case_id: str,
                   attempt_id: str, fresh_output_root: Path) -> dict[str, Any]:
    pair = _load_pair(root200_inner, root200_wrapper)
    case = _new_id(case_id, "ROOT191 V3 case_id")
    attempt = _new_id(attempt_id, "ROOT191 V3 attempt_id")
    fresh_root = fresh_output_root.expanduser().resolve()
    if fresh_root.exists() or "root191" not in str(fresh_root).lower() or "v3" not in str(fresh_root).lower():
        raise Root191V3Error("V3 fresh output namespace must be new and explicitly ROOT191/V3")
    proof_path = _file(root200_v12_proof, "ROOT200 V12 proof")
    receipt = _validate_root200_receipt(root200_receipt, pair)
    checkpoint = _validate_root200_checkpoint(root200_checkpoint, pair, receipt, proof_path)
    proof = _validate_v12_proof_v3(proof_path, pair)
    producer_path, producer = _json(producer_request, "179C producer request")
    producer_file_sha = sha256_file(producer_path)
    if producer.get("status") not in {"READY_FOR_PARENT_GUARD", "COMPLETED", "COMPLETED_PARENT_EXECUTOR_RAW_TYPED_LABEL_UNKNOWN"}:
        raise Root191V3Error("179C producer request is not a recognized source-bound request")
    producer_parent = _producer_artifact(producer_parent_report, "179C producer parent report", producer_file_sha, require_closed=False)
    # The producer's execution receipt is written before its same-parent
    # supplemental fee reconciliation.  The immutable producer root proof
    # below closes that fee; requiring a fictional ``charge`` field in this
    # receipt would reject the real successful 179C interface.
    producer_receipt_info = _producer_artifact(producer_receipt, "179C producer receipt", producer_file_sha, require_closed=False)
    producer_root = _producer_artifact(producer_root_proof, "179C producer root proof", producer_file_sha, require_closed=True)
    frozen = _validate_frozen(frozen_request)
    result = pair["inner"].get("result")
    typed = result.get("typed_output") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or not isinstance(typed, Mapping):
        raise Root191V3Error("ROOT200 typed result binding is missing")
    if typed.get("sha256") != TYPED_H5_SHA or typed.get("bytes") != TYPED_H5_BYTES:
        raise Root191V3Error("ROOT200 typed H5 metadata differs from source-bound product")
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "family_id": "F2",
        "case_id": case,
        "attempt_id": attempt,
        "model_invoked": False,
        "cfd_invoked": False,
        "ledger_mutated": False,
        "quality": dict(UNKNOWN),
        "qualification": dict(UNKNOWN),
        "product_mode": "TYPED_ONLY_LABELS",
        "root200_binding": {
            "inner_request": {"path": str(pair["inner_path"]), "file_sha256": pair["inner_file_sha"],
                               "canonical_sha256": pair["inner_canonical_sha"], "case_id": pair["case_id"],
                               "attempt_id": pair["inner_attempt"]},
            "outer_wrapper": {"path": str(pair["wrapper_path"]), "file_sha256": pair["wrapper_file_sha"],
                              "canonical_sha256": canonical_sha(pair["wrapper"]), "case_id": pair["case_id"],
                              "attempt_id": pair["outer_attempt"], "suffix": WRAPPER_SUFFIX},
            "completed_execution_receipt": receipt,
            "actual_verification_checkpoint": checkpoint,
            "fresh_v12_proof": proof,
            "typed_h5": {"path": typed.get("path"), "sha256": typed.get("sha256"), "bytes": typed.get("bytes"),
                         "content_verification": "PARENT_AFTER_RESERVATION"},
            "result": {"path": result.get("path"), "sha256": result.get("sha256"), "bytes": result.get("bytes"),
                       "content_verification": "PARENT_AFTER_RESERVATION"},
        },
        "producer_179c_binding": {
            "request": {"path": str(producer_path), "file_sha256": producer_file_sha,
                        "canonical_sha256": producer.get("sha256"), "case_id": producer.get("case_id"),
                        "attempt_id": producer.get("attempt_id")},
            "parent_report": producer_parent, "completed_receipt": producer_receipt_info,
            "root_proof": producer_root,
            "same_source_case": "F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE",
        },
        "source_frozen_request": frozen,
        "source_binding": {
            "current_catalog_sha256": CURRENT_SHA,
            "observer_profile_sha256": PROFILE_SHA,
            "cohort_selected_count": COHORT_COUNT,
            "cohort_identity_sha256": COHORT_IDENTITY_SHA,
            "initial_denominator_kg": DENOMINATOR_KG,
            "later_missing_mass_kg": LATER_MISSING_KG,
            "typed_h5_sha256": TYPED_H5_SHA,
            "typed_h5_bytes": TYPED_H5_BYTES,
            "content_read_by_builder": False,
            "cold_credit": "NOT_CLAIMED",
        },
        "evaluator_binding": {
            "entrypoint": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "schema": REQUEST_SCHEMA},
            "fresh_v12_proof_consumer": {"path": str(V12_SCRIPT), "sha256": sha256_file(V12_SCRIPT)},
            "existing_typed_evaluator_v1": {"path": str(V1_EVALUATOR_SCRIPT), "sha256": sha256_file(V1_EVALUATOR_SCRIPT)},
        },
        "execution": {
            "command_template": [sys.executable, str(SCRIPT), "run", "--request", "{request}",
                                  "--output", "{output}", "--parent-pid", "{parent_pid}"],
            "max_wall_seconds": 900.0,
            "max_result_bytes": MAX_RESULT_BYTES,
            "read_hdf5_or_bi4": False,
            "raw_opened": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
            "result_content_verification": "PARENT_AFTER_RESERVATION",
        },
        "fresh_output_namespace": {"root": str(fresh_root), "is_new": True},
        "old_proof_reuse": False,
        "fresh_cold_credit": False,
        "limitations": [
            "The generic ROOT200 execution receipt is the guard report; no closedledger field is required.",
            "The ROOT200 verification checkpoint independently proves completed fee, released reservation, and repeat idempotence.",
            "The V12 proof request.sha256 is the inner request file SHA; the inner canonical SHA is bound separately.",
            "The run command reads the V16 JSON only after the parent reservation and runs the existing typed-only scorer.",
            "No HDF5/BI4/native frame/model/CFD is opened and no raw-to-typed or cold-replay credit is granted.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(target),
            "file_sha256": sha256_file(target), "canonical_sha256": request["sha256"],
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def _validate_result_binding(request: Mapping[str, Any], pair: Mapping[str, Any]) -> tuple[Path, str, int]:
    result = pair["inner"].get("result")
    binding = request.get("root200_binding", {}).get("result")
    if not isinstance(result, Mapping) or not isinstance(binding, Mapping):
        raise Root191V3Error("ROOT200 result binding is missing")
    if binding.get("path") != result.get("path") or binding.get("sha256") != result.get("sha256") or binding.get("bytes") != result.get("bytes"):
        raise Root191V3Error("V3 result binding differs from the ROOT200 inner result")
    result_path = _file(binding.get("path"), "V16 JSON result", max_bytes=MAX_RESULT_BYTES)
    expected_sha = _sha(binding.get("sha256"), "V16 result SHA")
    declared_bytes = binding.get("bytes")
    if isinstance(declared_bytes, bool) or not isinstance(declared_bytes, int) or declared_bytes <= 0:
        raise Root191V3Error("V16 result bytes must be a positive integer")
    return result_path, expected_sha, declared_bytes


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path, request = _json(path, "ROOT191 V3 evaluator request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Root191V3Error("ROOT191 V3 request schema/canonical SHA differs")
    _new_id(request.get("case_id"), "ROOT191 V3 case_id")
    _new_id(request.get("attempt_id"), "ROOT191 V3 attempt_id")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("model_invoked") is not False or request.get("cfd_invoked") is not False:
        raise Root191V3Error("ROOT191 V3 request is not model-free parent-ready")
    _unknown(request.get("quality"), "ROOT191 V3 quality")
    _unknown(request.get("qualification"), "ROOT191 V3 qualification")
    root = request.get("root200_binding")
    producer = request.get("producer_179c_binding")
    if not isinstance(root, Mapping) or not isinstance(producer, Mapping):
        raise Root191V3Error("ROOT191 V3 ROOT200/179C bindings are missing")
    inner = root.get("inner_request")
    outer = root.get("outer_wrapper")
    if not isinstance(inner, Mapping) or not isinstance(outer, Mapping):
        raise Root191V3Error("ROOT191 V3 inner/outer request bindings are missing")
    pair = _load_pair(_file(inner.get("path"), "V3 ROOT200 inner request"), _file(outer.get("path"), "V3 ROOT200 wrapper"))
    if inner.get("file_sha256") != pair["inner_file_sha"] or outer.get("file_sha256") != pair["wrapper_file_sha"]:
        raise Root191V3Error("V3 ROOT200 inner/outer file SHA differs")
    receipt_binding = root.get("completed_execution_receipt")
    checkpoint_binding = root.get("actual_verification_checkpoint")
    proof_binding = root.get("fresh_v12_proof")
    if not all(isinstance(item, Mapping) for item in (receipt_binding, checkpoint_binding, proof_binding)):
        raise Root191V3Error("V3 ROOT200 terminal bindings are incomplete")
    receipt = _validate_root200_receipt(receipt_binding.get("path"), pair)
    checkpoint = _validate_root200_checkpoint(checkpoint_binding.get("path"), pair, receipt, _file(proof_binding.get("path"), "V3 V12 proof"))
    proof = _validate_v12_proof_v3(proof_binding.get("path"), pair)
    if receipt_binding.get("file_sha256") != receipt["file_sha256"] or checkpoint_binding.get("file_sha256") != checkpoint["file_sha256"] or proof_binding.get("file_sha256") != proof["file_sha256"]:
        raise Root191V3Error("V3 ROOT200 terminal file SHA differs")
    frozen = producer.get("request")
    if not isinstance(frozen, Mapping):
        raise Root191V3Error("V3 producer request binding is missing")
    producer_path = _file(frozen.get("path"), "V3 179C producer request")
    producer_sha = sha256_file(producer_path)
    if frozen.get("file_sha256") != producer_sha:
        raise Root191V3Error("V3 producer request file SHA differs")
    for key, closed in (("parent_report", False), ("completed_receipt", False), ("root_proof", True)):
        binding = producer.get(key)
        if not isinstance(binding, Mapping):
            raise Root191V3Error(f"V3 producer artifact missing: {key}")
        _producer_artifact(binding.get("path"), f"V3 producer {key}", producer_sha, require_closed=closed)
    frozen_info = _validate_frozen(request.get("source_frozen_request", {}).get("path"))
    if request.get("source_frozen_request", {}).get("file_sha256") != frozen_info["file_sha256"]:
        raise Root191V3Error("V3 source-frozen V15 SHA differs")
    source = request.get("source_binding")
    if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != CURRENT_SHA or source.get("observer_profile_sha256") != PROFILE_SHA:
        raise Root191V3Error("V3 source binding differs")
    if source.get("cohort_selected_count") != COHORT_COUNT or source.get("cohort_identity_sha256") != COHORT_IDENTITY_SHA:
        raise Root191V3Error("V3 source cohort binding differs")
    evaluator = request.get("evaluator_binding")
    for role in ("entrypoint", "fresh_v12_proof_consumer", "existing_typed_evaluator_v1"):
        binding = evaluator.get(role) if isinstance(evaluator, Mapping) else None
        if not isinstance(binding, Mapping):
            raise Root191V3Error(f"V3 evaluator role missing: {role}")
        source_file = _file(binding.get("path"), f"V3 evaluator source {role}")
        if binding.get("sha256") != sha256_file(source_file):
            raise Root191V3Error(f"V3 evaluator source SHA differs: {role}")
    execution = request.get("execution")
    if not isinstance(execution, Mapping) or execution.get("read_hdf5_or_bi4") is not False or execution.get("raw_opened") is not False or execution.get("original_path_fallback") != "FORBIDDEN":
        raise Root191V3Error("V3 execution content/fallback contract is open")
    fresh = request.get("fresh_output_namespace")
    if not isinstance(fresh, Mapping) or fresh.get("is_new") is not True:
        raise Root191V3Error("V3 fresh output namespace is not marked new")
    fresh_root = Path(str(fresh.get("root"))).expanduser().resolve()
    if "root191" not in str(fresh_root).lower() or "v3" not in str(fresh_root).lower():
        raise Root191V3Error("V3 output namespace identity differs")
    if request.get("old_proof_reuse") is not False or request.get("fresh_cold_credit") is not False:
        raise Root191V3Error("V3 old-proof/cold-credit boundary is open")
    result_path, expected_sha, declared_bytes = _validate_result_binding(request, pair)
    return {"schema": "ds02.stage2.f2-root191-metadata-preflight.v3",
            "status": "ROOT191_V3_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": sha256_file(request_path), "canonical_sha256": request["sha256"]},
            "root200_receipt": receipt, "root200_checkpoint": checkpoint, "root200_v12_proof": proof,
            "source_frozen_request": frozen_info, "result": {"path": str(result_path), "sha256": expected_sha, "bytes": declared_bytes},
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def _check_deadline(started: float, max_wall: float) -> None:
    if time.monotonic() - started > max_wall:
        raise Root191V3Error("ROOT191 V3 typed-only run exceeded max_wall_seconds")


def _result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    denominator = result.get("initial_mass_denominator")
    cohort = result.get("cohort")
    frames = result.get("frame_observations")
    event = result.get("event_summary")
    return {
        "schema": result.get("schema"),
        "case_identity": result.get("case_identity"),
        "cohort": {"selected_count": cohort.get("selected_count") if isinstance(cohort, Mapping) else None,
                   "selected_identity_sha256": cohort.get("selected_identity_sha256") if isinstance(cohort, Mapping) else None},
        "initial_mass_denominator": dict(denominator) if isinstance(denominator, Mapping) else None,
        "time": {"frame_count": len(frames) if isinstance(frames, list) else None,
                 "first_s": frames[0].get("time_s") if frames and isinstance(frames[0], Mapping) else None,
                 "last_s": frames[-1].get("time_s") if frames and isinstance(frames[-1], Mapping) else None,
                 "observer_profile": result.get("observer_profile")},
        "event_censor": dict(event) if isinstance(event, Mapping) else None,
        "quality": result.get("quality"),
    }


def run_trial(request_path: Path | str, *, output: Path | str, parent_pid: int,
              max_wall_seconds: float | None = None) -> dict[str, Any]:
    started = time.monotonic()
    request_file, request = _json(request_path, "ROOT191 V3 evaluator request")
    # validate_request is intentionally before payload reading.  It hashes only
    # bounded JSON/code metadata; the parent owns the reservation that precedes
    # this command and must account for this metadata phase.
    validate_request(request_file)
    if os.getppid() != int(parent_pid):
        raise Root191V3Error("ROOT191 V3 run requires the direct parent guard")
    execution = request["execution"]
    limit = float(max_wall_seconds if max_wall_seconds is not None else execution.get("max_wall_seconds", 900.0))
    if not math.isfinite(limit) or limit <= 0:
        raise Root191V3Error("max_wall_seconds must be finite and positive")
    root = request["root200_binding"]
    pair = _load_pair(root["inner_request"]["path"], root["outer_wrapper"]["path"])
    result_path, expected_sha, declared_bytes = _validate_result_binding(request, pair)
    _check_deadline(started, limit)
    # V8 checks stat and request semantics; V12 then applies the exact source
    # bound denominator adapter before the existing V1 no-model scorer.
    try:
        proof_request = V8._load_object(pair["inner_path"])
        bound = V12._load_marker(pair["inner_path"])[1]
        bound_info = V8._validate_request(proof_request, verify_result_stat=True)
        result, observed_sha, observed_bytes = V8._read_result(result_path, int(bound_info["max_result_bytes"]))
        if observed_sha != expected_sha or observed_bytes != declared_bytes:
            raise Root191V3Error("V16 JSON result SHA/stat differs from ROOT200 source binding")
        contract = V12._load_marker(pair["inner_path"])[2]
        old_scope = V12._ACTIVE_SCOPE
        V12._ACTIVE_SCOPE = contract
        try:
            v12_summary = V12._validate_result_v12(result, bound_info, observed_sha, observed_bytes)
        finally:
            V12._ACTIVE_SCOPE = old_scope
    except Root191V3Error:
        raise
    except Exception as error:
        raise Root191V3Error(f"V12/V8 typed JSON validation failed: {error}") from error
    _check_deadline(started, limit)
    frozen_path = _file(request["source_frozen_request"]["path"], "V3 source-frozen V15 request")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    if not isinstance(frozen, Mapping) or sha256_file(frozen_path) != request["source_frozen_request"]["file_sha256"]:
        raise Root191V3Error("source-frozen V15 request changed before scorer")
    try:
        operator_score = EVALUATOR._score_typed_result(result, frozen)
    except Exception as error:
        raise Root191V3Error(f"existing typed-only no-model scorer rejected the source-frozen result: {error}") from error
    _check_deadline(started, limit)
    output_path = Path(output).expanduser().resolve()
    fresh_root = Path(request["fresh_output_namespace"]["root"]).expanduser().resolve()
    if output_path == fresh_root or not (output_path == fresh_root or str(output_path).startswith(str(fresh_root) + os.sep)):
        raise Root191V3Error("V3 output is outside the fresh ROOT191 namespace")
    report: dict[str, Any] = {
        "schema": "ds02.stage2.f2-root191-typed-only-no-model-evaluator-report.v3",
        "status": "PASS_DEVELOPMENT_TYPED_ONLY_NO_MODEL_OPERATOR_TRIAL_ROOT191_V3",
        "request": {"path": str(request_file), "file_sha256": sha256_file(request_file), "canonical_sha256": request["sha256"]},
        "root200_guard": {"receipt": root["completed_execution_receipt"],
                          "checkpoint": root["actual_verification_checkpoint"],
                          "fresh_v12_proof": root["fresh_v12_proof"]},
        "typed_only_product": {"result_path": str(result_path), "result_sha256": observed_sha,
                                "result_bytes": observed_bytes, "hdf5_or_bi4_content_read": False,
                                "raw_opened": False},
        "result_summary": _result_summary(result),
        "v12_result_validation": v12_summary,
        "operator_score": operator_score,
        "source_frozen_request": request["source_frozen_request"],
        "producer_179c_binding": request["producer_179c_binding"],
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                             "portable_cold_replay_credit": "NOT_CLAIMED", "scientific_qualification": "UNKNOWN"},
        "timing": {"wall_seconds_from_entry": time.monotonic() - started,
                   "max_wall_seconds": limit,
                   "content_read_after_parent_guard": True},
    }
    report["sha256"] = canonical_sha(report)
    _write_new(output_path, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("root200-inner", "root200-wrapper", "root200-receipt", "root200-checkpoint", "root200-v12-proof",
                 "producer-request", "producer-parent-report", "producer-receipt", "producer-root-proof",
                 "frozen-request", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    run.add_argument("--max-wall-seconds", type=float)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = _build_request(
                root200_inner=args.root200_inner.absolute(), root200_wrapper=args.root200_wrapper.absolute(),
                root200_receipt=args.root200_receipt.absolute(), root200_checkpoint=args.root200_checkpoint.absolute(),
                root200_v12_proof=args.root200_v12_proof.absolute(), producer_request=args.producer_request.absolute(),
                producer_parent_report=args.producer_parent_report.absolute(), producer_receipt=args.producer_receipt.absolute(),
                producer_root_proof=args.producer_root_proof.absolute(), frozen_request=args.frozen_request.absolute(),
                output=args.output.absolute(), case_id=args.case_id, attempt_id=args.attempt_id,
                fresh_output_root=args.fresh_output_root.absolute())
        elif args.command == "validate":
            value = validate_request(args.request.absolute())
        else:
            value = run_trial(args.request.absolute(), output=args.output.absolute(), parent_pid=args.parent_pid,
                              max_wall_seconds=args.max_wall_seconds)
    except (Root191V3Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT191 V3 typed-only no-model evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value.get("status"), "sha256": value.get("sha256", value.get("file_sha256")),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
