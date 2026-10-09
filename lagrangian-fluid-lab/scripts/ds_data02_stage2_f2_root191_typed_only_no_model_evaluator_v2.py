#!/usr/bin/env python3
"""ROOT191 V2 typed-only bridge for a completed ROOT197 proof.

V1 binds one ROOT194 request whose wrapper and inner attempt IDs were equal.
The real generic ROOT197 dispatch has two deliberate identities: the V8
inner request keeps the producer attempt and the outer ``ds02.request.v1``
wrapper appends exactly ``-root-forward-030-001``.  This bridge accepts that
one documented relationship and rejects arbitrary wrappers or prefix-only
matches.

The builder is metadata-only.  It reads bounded request, receipt, proof, and
sidecar JSON; it never opens V16 result content, typed HDF5, BI4, native
frames, or models.  A later parent guard owns content verification and the
resource ledger.  ROOT194/ROOT060 are retained only as failed provenance and
cannot satisfy this request.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V1_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_typed_only_no_model_evaluator_v1.py"
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
V66_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py"
V1_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"
V3_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v3.py"

REQUEST_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v2"
ROOT197_V8_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
ROOT197_WRAPPER_SCHEMA = "ds02.request.v1"
V8_PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
V12_FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
V12_SIDECAR_SCHEMA = "ds02.stage2.f2-fresh-v16-missing-scope-sidecar.v1"
WRAPPER_SUFFIX = "-root-forward-030-001"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 16 * 1024 * 1024
CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
TYPED_H5_SHA = "2a2ef5cf5c0e1f164018466fa4815a4465ab72dbf1071bf60e76c33657288664"
TYPED_H5_BYTES = 1191110528
COHORT_COUNT = 21114
COHORT_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
DENOMINATOR_KG = 21.114001002861187
LATER_MISSING_KG = 0.003000000142492354
PROFILE_SHA = "de4f7ed699149424506216b30a2784750d54d6cc359fbfe9b9da3d299d7e5507"


class Root191V2Error(RuntimeError):
    """Raised for an incomplete or mis-bound ROOT197 V2 request."""


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Root191V2Error(f"cannot load bound module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_module(V1_SCRIPT, "ds02_bound_root191_v1_for_v2")
V8 = _load_module(V8_SCRIPT, "ds02_bound_root191_v8_for_v2")

SUPPORTED_SOURCE_ROOTS = ("ROOT197", "ROOT200")


def canonical_sha(value: Mapping[str, Any]) -> str:
    return V1.canonical_sha(value)


def sha256_file(path: Path | str, *, max_bytes: int = MAX_JSON_BYTES) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if total > max_bytes:
                    raise Root191V2Error(f"metadata file exceeds bound: {target}")
                digest.update(block)
    except OSError as error:
        raise Root191V2Error(f"cannot hash metadata file {target}: {error}") from error
    return digest.hexdigest()


def _file(value: Any, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root191V2Error(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise Root191V2Error(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise Root191V2Error(f"{role} exceeds bounded metadata size: {target}")
    return target.resolve()


def _json(value: Any, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    path = _file(value, role, max_bytes=max_bytes)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root191V2Error(f"cannot read {role}: {error}") from error
    if not isinstance(parsed, dict):
        raise Root191V2Error(f"{role} must be a JSON object")
    return path, parsed


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise Root191V2Error(f"{role} must be a lowercase SHA-256")
    return value


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise Root191V2Error(f"{role} must remain QI/QN/QE UNKNOWN")


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise Root191V2Error(f"refusing existing ROOT191 V2 output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def _status_strings(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if isinstance(child, str) and (str(key).lower() in {"status", "state", "terminal_status", "charge_status",
                                                               "ledger_status", "verification_status", "result_status"}
                                           or str(key).lower().endswith("_status")):
                found.append(child)
            found.extend(_status_strings(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_status_strings(child))
    return found


def _require_success(value: Mapping[str, Any], role: str, *, require_closed: bool = False) -> None:
    statuses = _status_strings(value)
    if any(any(word in status.upper() for word in ("FAIL", "ERROR", "CANCEL", "ABORT", "TIMEOUT"))
           for status in statuses):
        raise Root191V2Error(f"{role} has a failed terminal status")
    if not any(any(word in status.upper() for word in ("COMPLETE", "COMPLETED", "PASS", "SUCCESS", "VERIFIED", "CLOSED"))
               for status in statuses):
        raise Root191V2Error(f"{role} has no completed terminal status")
    if require_closed:
        closed = any(any(word in status.upper() for word in ("CLOSED", "APPLIED", "COMPLETE", "COMPLETED", "SUCCESS"))
                     for key, status in _status_pairs(value)
                     if any(token in key.lower() for token in ("charge", "ledger", "account", "terminal")))
        if isinstance(value.get("ledger_mutated"), bool) and value.get("ledger_mutated"):
            closed = True
        charge = value.get("charge")
        if isinstance(charge, Mapping) and any(word in str(charge.get("status", "")).upper()
                                               for word in ("CLOSED", "APPLIED", "COMPLETE", "SUCCESS")):
            closed = True
        if not closed:
            raise Root191V2Error(f"{role} lacks closed accounting evidence")


def _status_pairs(value: Any, prefix: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            key_text = f"{prefix}.{key}" if prefix else str(key)
            if isinstance(child, str) and (str(key).lower() in {"status", "state", "terminal_status", "charge_status",
                                                               "ledger_status", "verification_status", "result_status"}
                                           or str(key).lower().endswith("_status")):
                found.append((key_text, child))
            found.extend(_status_pairs(child, key_text))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_status_pairs(child, f"{prefix}[{index}]"))
    return found


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
                        if "request" in name or name in {"parent", "binding", "receipt", "executor"}:
                            found.add(candidate)
                found.update(_request_hashes(child))
            elif isinstance(child, list):
                found.update(_request_hashes(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_request_hashes(child))
    return found


def _artifact(path: Path | str, role: str, accepted: set[str], *, require_closed: bool = False) -> dict[str, Any]:
    target, value = _json(path, role)
    _require_success(value, role, require_closed=require_closed)
    candidates = _request_hashes(value)
    if not candidates.intersection(accepted):
        raise Root191V2Error(f"{role} is not bound to the exact request identity")
    return {"path": str(target), "file_sha256": sha256_file(target), "status": value.get("status"),
            "request_sha256": sorted(candidates.intersection(accepted))}


def _load_pair(inner_path: Path | str, wrapper_path: Path | str) -> dict[str, Any]:
    inner_file, inner = _json(inner_path, "ROOT197 inner V8 request")
    wrapper_file, wrapper = _json(wrapper_path, "ROOT197 generic wrapper")
    if inner.get("schema") != ROOT197_V8_SCHEMA or inner.get("sha256") != canonical_sha(inner):
        raise Root191V2Error("ROOT197 inner request is not canonical V8")
    if wrapper.get("schema") != ROOT197_WRAPPER_SCHEMA:
        raise Root191V2Error("ROOT197 outer request is not ds02.request.v1")
    case_id = str(inner.get("case_id", ""))
    inner_attempt = str(inner.get("attempt_id", ""))
    source_marker = next((item for item in SUPPORTED_SOURCE_ROOTS if item in case_id.upper()), None)
    if source_marker is None or not case_id.startswith(f"STAGE2_F2_{source_marker}_") or source_marker not in inner_attempt.upper():
        raise Root191V2Error("fresh ROOT197/ROOT200 inner case/attempt identity is not exact")
    binding = wrapper.get("consumer_request_binding")
    if not isinstance(binding, Mapping):
        raise Root191V2Error("ROOT197 wrapper consumer_request_binding is missing")
    if Path(str(binding.get("path"))).expanduser().resolve() != inner_file.resolve():
        raise Root191V2Error("ROOT197 wrapper does not point at the supplied inner request")
    inner_file_sha = sha256_file(inner_file)
    if binding.get("sha256") != inner_file_sha or binding.get("canonical_sha256") != inner["sha256"]:
        raise Root191V2Error("ROOT197 wrapper inner file/canonical SHA differs")
    if wrapper.get("case_id") != case_id:
        raise Root191V2Error("ROOT197 wrapper case differs from inner request")
    outer_attempt = wrapper.get("attempt_id")
    if outer_attempt != inner_attempt + WRAPPER_SUFFIX:
        raise Root191V2Error("ROOT197 wrapper attempt does not use the exact forward suffix")
    if wrapper.get("fresh_cold_credit") is not False or wrapper.get("no_old_ROOT060_reuse") is not True:
        raise Root191V2Error("ROOT197 wrapper old-proof boundary is not closed")
    _unknown(wrapper.get("qualification"), "ROOT197 wrapper qualification")
    profile = inner.get("observer_profile_source_binding")
    expected = inner.get("expected")
    time = expected.get("time") if isinstance(expected, Mapping) else None
    if not isinstance(profile, Mapping) or profile.get("profile_sha256") != PROFILE_SHA or profile.get("current_catalog_sha256") != CURRENT_SHA:
        raise Root191V2Error("ROOT197 observer profile is not the actual source-bound profile")
    if not isinstance(time, Mapping) or time.get("observer_profile_sha256") != PROFILE_SHA:
        raise Root191V2Error("ROOT197 expected time profile SHA differs")
    marker = inner.get("v12_forward")
    if not isinstance(marker, Mapping) or marker.get("schema") != V12_FORWARD_SCHEMA:
        raise Root191V2Error("ROOT197 V12 marker is missing")
    sidecar = marker.get("semantic_sidecar")
    if not isinstance(sidecar, Mapping):
        raise Root191V2Error("ROOT197 semantic sidecar binding is missing")
    sidecar_path = _file(sidecar.get("path"), "ROOT197 semantic sidecar")
    if sidecar.get("schema") != V12_SIDECAR_SCHEMA or sidecar.get("sha256") != sha256_file(sidecar_path):
        raise Root191V2Error("ROOT197 semantic sidecar SHA/schema differs")
    return {
        "inner_path": inner_file, "inner": inner, "inner_file_sha": inner_file_sha,
        "inner_canonical_sha": inner["sha256"], "wrapper_path": wrapper_file, "wrapper": wrapper,
        "wrapper_file_sha": sha256_file(wrapper_file), "sidecar_path": sidecar_path,
        "profile": dict(profile), "case_id": case_id, "inner_attempt": inner_attempt,
        "outer_attempt": outer_attempt, "source_root_marker": source_marker,
    }


def _validate_v12_proof(path: Path | str, pair: Mapping[str, Any]) -> dict[str, Any]:
    proof_path, proof = _json(path, "ROOT197 fresh V12 proof")
    if proof.get("schema") != V8_PROOF_SCHEMA or proof.get("sha256") != canonical_sha(proof):
        raise Root191V2Error("ROOT197 fresh V12 proof is not canonical V8")
    if proof.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise Root191V2Error("ROOT197 fresh V12 proof is not completed")
    _unknown(proof.get("quality"), "ROOT197 proof quality")
    _unknown(proof.get("qualification"), "ROOT197 proof qualification")
    execution = proof.get("execution")
    if not isinstance(execution, Mapping) or execution.get("hdf5_or_bi4_content_read") is not False or execution.get("raw_opened") is not False:
        raise Root191V2Error("ROOT197 proof is not JSON-only")
    adapter = proof.get("v12_semantic_scope_adapter")
    if not isinstance(adapter, Mapping) or adapter.get("schema") != V12_FORWARD_SCHEMA:
        raise Root191V2Error("ROOT197 proof V12 adapter is missing")
    if adapter.get("normalized_for_v8_only") is not True or adapter.get("original_result_bytes_unchanged") is not True:
        raise Root191V2Error("ROOT197 proof does not preserve result bytes")
    if adapter.get("sidecar_sha256") != sha256_file(pair["sidecar_path"]):
        raise Root191V2Error("ROOT197 proof sidecar SHA differs")
    request = proof.get("request")
    if not isinstance(request, Mapping) or Path(str(request.get("path"))).expanduser().resolve() != pair["inner_path"].resolve():
        raise Root191V2Error("ROOT197 V12 proof points at a different inner request")
    if request.get("sha256") != pair["inner"]["sha256"]:
        raise Root191V2Error("ROOT197 V12 proof request canonical SHA differs")
    result = pair["inner"].get("result")
    source_result = proof.get("source_result")
    if not isinstance(result, Mapping) or not isinstance(source_result, Mapping):
        raise Root191V2Error("ROOT197 result/proof result binding is missing")
    if source_result.get("sha256") != result.get("sha256") or source_result.get("bytes") != result.get("bytes") or source_result.get("content_sha_verified") is not True:
        raise Root191V2Error("ROOT197 proof result binding differs")
    source = proof.get("source_binding")
    if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != CURRENT_SHA:
        raise Root191V2Error("ROOT197 proof CURRENT binding differs")
    return {"path": str(proof_path), "file_sha256": sha256_file(proof_path),
            "canonical_sha256": proof["sha256"], "status": proof["status"],
            "request_file_sha256": pair["inner_file_sha"], "result_sha256": result.get("sha256"),
            "result_bytes": result.get("bytes")}


def _validate_frozen_original(path: Path | str) -> dict[str, Any]:
    frozen_path, frozen = _json(path, "frozen original producer request")
    if any(token in str(frozen_path).lower() for token in ("root060", "root190", "oldproof")):
        # The path is allowed as historical provenance only when the request
        # itself is explicitly marked as a source request; old proof products
        # never become an actionable input.
        if frozen.get("no_old_ROOT060_reuse") is not True:
            raise Root191V2Error("frozen original request is an old proof fallback")
    return {"path": str(frozen_path), "file_sha256": sha256_file(frozen_path),
            "canonical_sha256": frozen.get("sha256", canonical_sha(frozen)),
            "schema": frozen.get("schema"), "case_id": frozen.get("case_id"),
            "attempt_id": frozen.get("attempt_id")}


def _terminal_group(path: Path | str, role: str, accepted: set[str], *, closed: bool) -> dict[str, Any]:
    return _artifact(path, role, accepted, require_closed=closed)


def _build_request(*, root197_inner: Path, root197_wrapper: Path,
                   root197_parent_report: Path, root197_receipt: Path,
                   root197_root_proof: Path, root197_v12_proof: Path,
                   producer_parent_report: Path, producer_receipt: Path,
                   producer_root_proof: Path, frozen_original_request: Path,
                   output: Path, case_id: str, attempt_id: str,
                   fresh_output_root: Path) -> dict[str, Any]:
    pair = _load_pair(root197_inner, root197_wrapper)
    case = V1._new_id(case_id, "ROOT191 V2 case_id", "ROOT191")
    attempt = V1._new_id(attempt_id, "ROOT191 V2 attempt_id", "ROOT191")
    fresh_root = fresh_output_root.expanduser().resolve()
    if fresh_root.exists() or "root191" not in str(fresh_root).lower() or "v2" not in str(fresh_root).lower():
        raise Root191V2Error("ROOT191 V2 output namespace must be new and explicitly V2")
    root197_accepted = {pair["inner_file_sha"], pair["inner_canonical_sha"], pair["wrapper_file_sha"]}
    root197_parent = _terminal_group(root197_parent_report, "ROOT197 parent report", root197_accepted, closed=False)
    root197_receipt = _terminal_group(root197_receipt, "ROOT197 completed receipt", root197_accepted, closed=True)
    root197_root = _terminal_group(root197_root_proof, "ROOT197 root proof", root197_accepted, closed=True)
    root197_v12 = _validate_v12_proof(root197_v12_proof, pair)
    frozen = _validate_frozen_original(frozen_original_request)
    producer_accepted = {frozen["file_sha256"], frozen["canonical_sha256"]}
    producer_parent = _terminal_group(producer_parent_report, "179C producer parent report", producer_accepted, closed=False)
    producer_receipt_info = _terminal_group(producer_receipt, "179C producer receipt", producer_accepted, closed=True)
    producer_root = _terminal_group(producer_root_proof, "179C producer root proof", producer_accepted, closed=True)
    result = pair["inner"].get("result")
    typed = result.get("typed_output") if isinstance(result, Mapping) else None
    if not isinstance(result, Mapping) or not isinstance(typed, Mapping) or typed.get("sha256") != TYPED_H5_SHA or typed.get("bytes") != TYPED_H5_BYTES:
        raise Root191V2Error("ROOT197 typed H5 metadata differs from actual 179C product")
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
        "root197_binding": {
            "inner_request": {"path": str(pair["inner_path"]), "file_sha256": pair["inner_file_sha"],
                              "canonical_sha256": pair["inner_canonical_sha"], "case_id": pair["case_id"],
                              "attempt_id": pair["inner_attempt"], "source_root_marker": pair["source_root_marker"]},
            "outer_wrapper": {"path": str(pair["wrapper_path"]), "file_sha256": pair["wrapper_file_sha"],
                              "case_id": pair["case_id"], "attempt_id": pair["outer_attempt"],
                              "suffix": WRAPPER_SUFFIX},
            "observer_profile_sha256": PROFILE_SHA,
            "current_catalog_sha256": CURRENT_SHA,
            "parent_report": root197_parent,
            "completed_receipt": root197_receipt,
            "root_proof": root197_root,
            "fresh_v12_proof": root197_v12,
            "typed_h5": {"path": typed.get("path"), "sha256": TYPED_H5_SHA, "bytes": TYPED_H5_BYTES,
                         "content_verification": "PARENT_AFTER_RESERVATION"},
            "result": {"path": result.get("path"), "sha256": result.get("sha256"), "bytes": result.get("bytes"),
                       "content_verification": "PARENT_AFTER_RESERVATION"},
        },
        "producer_179c_binding": {
            "frozen_original_request": frozen,
            "parent_report": producer_parent,
            "completed_receipt": producer_receipt_info,
            "root_proof": producer_root,
            "same_source_case": "F2_ROOT179C_V66_ACTUAL_CONVERSION_LABEL_INTERFACE",
        },
        "source_binding": {
            "current_catalog_sha256": CURRENT_SHA,
            "cohort_selected_count": COHORT_COUNT,
            "cohort_identity_sha256": COHORT_IDENTITY_SHA,
            "initial_denominator_kg": DENOMINATOR_KG,
            "later_missing_mass_kg": LATER_MISSING_KG,
            "typed_h5_sha256": TYPED_H5_SHA,
            "typed_h5_bytes": TYPED_H5_BYTES,
            "observer_profile_sha256": PROFILE_SHA,
            "content_read_by_builder": False,
        },
        "evaluator_binding": {
            "entrypoint": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "schema": REQUEST_SCHEMA},
            "root191_v1_provenance": {"path": str(V1_SCRIPT), "sha256": sha256_file(V1_SCRIPT)},
            "fresh_proof_consumer_v12": {"path": str(V12_SCRIPT), "sha256": sha256_file(V12_SCRIPT), "schema": V12_FORWARD_SCHEMA},
            "fresh_proof_template_v66": {"path": str(V66_SCRIPT), "sha256": sha256_file(V66_SCRIPT), "request_schema": ROOT197_V8_SCHEMA},
            "existing_typed_evaluator_v1": {"path": str(V1_EVALUATOR_SCRIPT), "sha256": sha256_file(V1_EVALUATOR_SCRIPT)},
            "existing_no_model_evaluator_v3": {"path": str(V3_EVALUATOR_SCRIPT), "sha256": sha256_file(V3_EVALUATOR_SCRIPT)},
        },
        "execution": {
            "command_template": [sys.executable, str(SCRIPT), "run", "--request", "{request}", "--output", "{output}", "--parent-pid", "{parent_pid}"],
            "max_wall_seconds": 900.0, "read_hdf5_or_bi4": False, "raw_opened": False,
            "model_invoked": False, "cfd_invoked": False, "original_path_fallback": "FORBIDDEN",
            "result_content_verification": "PARENT_AFTER_RESERVATION",
        },
        "fresh_output_namespace": {"root": str(fresh_root), "is_new": True},
        "old_proof_reuse": False,
        "fresh_cold_credit": False,
        "limitations": [
            "ROOT197 parent report, completed receipt, root proof, and fresh V12 proof are all required.",
            "179C producer parent/receipt/root proof and the frozen original request are joined separately.",
            "ROOT194 and ROOT060 are provenance only; neither can satisfy this ROOT191 V2 request.",
            "Typed HDF5, V16 JSON, BI4, native frames, and models remain outside this metadata builder.",
            "QI/QN/QE and raw-to-typed/portable-cold credit remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(target),
            "file_sha256": sha256_file(target), "canonical_sha256": request["sha256"],
            "root197_inner_file_sha256": pair["inner_file_sha"],
            "root197_outer_file_sha256": pair["wrapper_file_sha"],
            "root197_v12_proof_file_sha256": root197_v12["file_sha256"],
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path, request = _json(path, "ROOT191 V2 evaluator request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Root191V2Error("ROOT191 V2 request schema/canonical SHA differs")
    V1._new_id(request.get("case_id"), "ROOT191 V2 case_id", "ROOT191")
    V1._new_id(request.get("attempt_id"), "ROOT191 V2 attempt_id", "ROOT191")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("model_invoked") is not False:
        raise Root191V2Error("ROOT191 V2 request is not model-free parent-ready")
    _unknown(request.get("qualification"), "ROOT191 V2 qualification")
    root = request.get("root197_binding")
    producer = request.get("producer_179c_binding")
    if not isinstance(root, Mapping) or not isinstance(producer, Mapping):
        raise Root191V2Error("ROOT191 V2 root197/179C bindings are missing")
    inner_path = _file(root.get("inner_request", {}).get("path"), "ROOT191 V2 inner request")
    wrapper_path = _file(root.get("outer_wrapper", {}).get("path"), "ROOT191 V2 outer wrapper")
    pair = _load_pair(inner_path, wrapper_path)
    if root.get("inner_request", {}).get("file_sha256") != pair["inner_file_sha"] or root.get("outer_wrapper", {}).get("file_sha256") != pair["wrapper_file_sha"]:
        raise Root191V2Error("ROOT191 V2 request root197 file SHA differs")
    # The actual terminal files are re-read only as bounded JSON metadata.
    accepted = {pair["inner_file_sha"], pair["inner_canonical_sha"], pair["wrapper_file_sha"]}
    _artifact(root.get("parent_report", {}).get("path"), "ROOT197 parent report", accepted)
    _artifact(root.get("completed_receipt", {}).get("path"), "ROOT197 receipt", accepted, require_closed=True)
    _artifact(root.get("root_proof", {}).get("path"), "ROOT197 root proof", accepted, require_closed=True)
    _validate_v12_proof(root.get("fresh_v12_proof", {}).get("path"), pair)
    frozen = producer.get("frozen_original_request")
    if not isinstance(frozen, Mapping):
        raise Root191V2Error("ROOT191 V2 frozen original binding is missing")
    frozen_path = _file(frozen.get("path"), "ROOT191 V2 frozen original request")
    frozen_info = _validate_frozen_original(frozen_path)
    if frozen.get("file_sha256") != frozen_info["file_sha256"]:
        raise Root191V2Error("ROOT191 V2 frozen original SHA differs")
    producer_accepted = {frozen_info["file_sha256"], frozen_info["canonical_sha256"]}
    _artifact(producer.get("parent_report", {}).get("path"), "179C producer parent report", producer_accepted)
    _artifact(producer.get("completed_receipt", {}).get("path"), "179C producer receipt", producer_accepted, require_closed=True)
    _artifact(producer.get("root_proof", {}).get("path"), "179C producer root proof", producer_accepted, require_closed=True)
    source = request.get("source_binding")
    if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != CURRENT_SHA or source.get("observer_profile_sha256") != PROFILE_SHA:
        raise Root191V2Error("ROOT191 V2 source binding differs")
    evaluator = request.get("evaluator_binding")
    for role in ("entrypoint", "root191_v1_provenance", "fresh_proof_consumer_v12", "fresh_proof_template_v66",
                 "existing_typed_evaluator_v1", "existing_no_model_evaluator_v3"):
        binding = evaluator.get(role) if isinstance(evaluator, Mapping) else None
        if not isinstance(binding, Mapping):
            raise Root191V2Error(f"ROOT191 V2 evaluator source role missing: {role}")
        source_file = _file(binding.get("path"), f"ROOT191 V2 evaluator source {role}")
        if binding.get("sha256") != sha256_file(source_file):
            raise Root191V2Error(f"ROOT191 V2 evaluator source SHA differs: {role}")
    if request.get("old_proof_reuse") is not False or request.get("fresh_cold_credit") is not False:
        raise Root191V2Error("ROOT191 V2 old-proof boundary is not closed")
    return {"schema": "ds02.stage2.f2-root191-metadata-preflight.v2",
            "status": "ROOT191_V2_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": sha256_file(request_path),
                        "canonical_sha256": request["sha256"]},
            "root197_inner": root["inner_request"], "root197_outer": root["outer_wrapper"],
            "root197_v12_proof": root["fresh_v12_proof"], "payload_read": False,
            "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("root197-inner", "root197-wrapper", "root197-parent-report", "root197-receipt", "root197-root-proof",
                 "root197-v12-proof", "producer-parent-report", "producer-receipt", "producer-root-proof",
                 "frozen-original-request", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = _build_request(
                root197_inner=args.root197_inner.absolute(), root197_wrapper=args.root197_wrapper.absolute(),
                root197_parent_report=args.root197_parent_report.absolute(), root197_receipt=args.root197_receipt.absolute(),
                root197_root_proof=args.root197_root_proof.absolute(), root197_v12_proof=args.root197_v12_proof.absolute(),
                producer_parent_report=args.producer_parent_report.absolute(), producer_receipt=args.producer_receipt.absolute(),
                producer_root_proof=args.producer_root_proof.absolute(), frozen_original_request=args.frozen_original_request.absolute(),
                output=args.output.absolute(), case_id=args.case_id, attempt_id=args.attempt_id,
                fresh_output_root=args.fresh_output_root.absolute())
        else:
            value = validate_request(args.request.absolute())
    except (Root191V2Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT191 V2 typed-only no-model evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
