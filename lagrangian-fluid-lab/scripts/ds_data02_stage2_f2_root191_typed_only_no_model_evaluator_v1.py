#!/usr/bin/env python3
"""Build and run the ROOT191 typed-only, model-free evaluator bridge.

ROOT194 is a fresh V12 proof attempt.  This bridge is deliberately downstream
of *all* of its small terminal evidence: the completed parent report, the
completed Home receipt, the independent ROOT proof, and the V12 proof file.
It refuses to manufacture a proof while ROOT194 is absent or failed, and it
does not accept ROOT190/ROOT060 artefacts as a substitute.

The builder reads bounded JSON and the producer-declared typed-HDF5 metadata
only.  It never hashes or opens the HDF5, the 62 MB V16 JSON, native BI4, or
raw frames.  ``run`` is the later parent-guarded JSON-only operator stage; it
rehashes/parses the V16 JSON only after its caller has made the reservation.
The operator score remains DEVELOPMENT-only and QI/QN/QE remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCRIPT_DIR = SCRIPT.parent
V8_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
# V66 is the existing producer-side fresh-proof template.  ROOT191 does not
# execute it, but records its exact source in the closure and checks that its
# V8 request contract is the one consumed by the V12 proof adapter.
V66_TEMPLATE_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_fresh_v16_proof_request_v66.py"
V1_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_typed_only_evaluator_v1.py"
V3_EVALUATOR_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_no_model_evaluator_v3.py"

ROOT194_WRAPPER_SCHEMA = "ds02.request.v1"
ROOT194_V8_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V8_PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
V12_FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
V12_SIDECAR_SCHEMA = "ds02.stage2.f2-fresh-v16-missing-scope-sidecar.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-request.v1"
REPORT_SCHEMA = "ds02.stage2.f2-root191-typed-only-no-model-evaluator-report.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 16 * 1024 * 1024
MAX_PROOF_BYTES = 16 * 1024 * 1024

CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
TYPED_H5_SHA = "2a2ef5cf5c0e1f164018466fa4815a4465ab72dbf1071bf60e76c33657288664"
TYPED_H5_BYTES = 1191110528
COHORT_COUNT = 21114
COHORT_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
DENOMINATOR_KG = 21.114001002861187
LATER_MISSING_KG = 0.003000000142492354

STALE_ACTIONABLE = ("root060", "root190", "oldproof", "old-proof", "aabfb")
OLD_RESULT_SHAS = {
    # ROOT190/060 proof identities are forbidden; the actual 179C producer
    # result SHA may be the same source result and is therefore not rejected.
    "2b71dcb5370b9cdbd745ece877e892a6f30871207e9351c102cfb9720422fb47",
}


class Root191Error(RuntimeError):
    """A strict ROOT191 source, proof, or terminal binding failure."""


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    try:
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                total += len(block)
                if max_bytes is not None and total > max_bytes:
                    raise Root191Error(f"metadata file exceeds bound: {target}")
                digest.update(block)
    except OSError as error:
        raise Root191Error(f"cannot hash {target}: {error}") from error
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise Root191Error(f"{role} must be a lowercase SHA-256")
    return value


def _file(value: Any, role: str, *, max_bytes: int | None = None) -> Path:
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root191Error(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise Root191Error(f"{role} must be a regular non-symlink file: {path}")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise Root191Error(f"{role} exceeds metadata-only bound: {path}")
    return path.resolve()


def _absolute_path(value: Any, role: str) -> Path:
    """Validate a path binding without opening or stat'ing its payload.

    ROOT194's typed HDF5 and V16 result are producer outputs.  Their content
    and final stat are intentionally checked by the parent guarded stage.  A
    metadata builder must therefore be able to bind a not-yet-materialized
    relocated path without turning that binding into an unreserved payload
    read (or a 62 MB JSON read).
    """
    if isinstance(value, Path):
        value = str(value)
    if not isinstance(value, str) or not value.startswith("/"):
        raise Root191Error(f"{role} must be an absolute path")
    return Path(value).expanduser().resolve(strict=False)


def _json(value: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> tuple[Path, dict[str, Any]]:
    path = _file(value, role, max_bytes=max_bytes)
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root191Error(f"cannot read {role}: {error}") from error
    if not isinstance(parsed, dict):
        raise Root191Error(f"{role} must be a JSON object")
    return path, parsed


def _stat(path: Path, role: str) -> dict[str, int]:
    path = _file(str(path), role)
    info = path.stat()
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(info.st_mode & 0o777)}


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise Root191Error(f"refusing existing ROOT191 output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                      encoding="utf-8")
    return target


def _new_id(value: Any, role: str, marker: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise Root191Error(f"{role} must be a non-empty string")
    result = value.strip()
    lowered = result.lower()
    if marker.lower() not in lowered:
        raise Root191Error(f"{role} must carry the fresh {marker} identity")
    if any(token in lowered for token in STALE_ACTIONABLE):
        raise Root191Error(f"{role} carries a historical ROOT190/ROOT060 marker")
    return result


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise Root191Error(f"{role} must retain QI/QN/QE UNKNOWN")


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _contains_stale_actionable(value: Any, role: str) -> None:
    """Reject stale markers in new actionable artefacts, allowing provenance fields."""
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in STALE_ACTIONABLE):
            raise Root191Error(f"{role} contains a historical proof/result marker: {value}")
    elif isinstance(value, Mapping):
        for key, item in value.items():
            # ROOT194 is allowed to carry ROOT190 as an explicit historical
            # provenance edge.  It is never copied into the ROOT191 action.
            if str(key).lower() in {"provenance", "historical_provenance", "case_provenance", "forward_of"}:
                continue
            _contains_stale_actionable(item, f"{role}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _contains_stale_actionable(item, f"{role}[{index}]")


def _status_values(value: Any, *, key: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, Mapping):
        for name, item in value.items():
            if isinstance(item, str) and (name.lower() in {"status", "state", "terminal_status", "charge_status",
                                                              "ledger_status", "verification_status", "result_status"}
                                         or name.lower().endswith("_status")):
                found.append((name, item))
            found.extend(_status_values(item, key=name))
    elif isinstance(value, list):
        for item in value:
            found.extend(_status_values(item, key=key))
    return found


def _require_completed_status(value: Mapping[str, Any], role: str) -> list[tuple[str, str]]:
    statuses = _status_values(value)
    bad = [(key, status) for key, status in statuses
           if any(word in status.upper() for word in ("FAIL", "ERROR", "CANCEL", "ABORT", "TIMEOUT"))]
    if bad:
        raise Root191Error(f"{role} has a failed terminal status: {bad[0][1]}")
    good = [(key, status) for key, status in statuses
            if any(word in status.upper() for word in ("COMPLETE", "COMPLETED", "PASS", "SUCCESS", "VERIFIED", "CLOSED"))]
    if not good:
        raise Root191Error(f"{role} has no completed/success terminal status")
    return statuses


def _request_hash_candidates(value: Mapping[str, Any]) -> list[str]:
    candidates: list[str] = []

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, Mapping):
            for name, child in item.items():
                lowered = str(name).lower()
                if isinstance(child, str) and len(child) == 64 and all(ch in HEX64 for ch in child):
                    if "request" in lowered and ("sha" in lowered or lowered in {"sha256", "file_sha256"}):
                        candidates.append(child)
                if isinstance(child, Mapping) and ("request" in lowered or lowered in {"parent", "binding", "receipt"}):
                    path_value = child.get("path")
                    if isinstance(path_value, str):
                        for name2 in ("sha256", "file_sha256", "canonical_sha256", "request_sha256"):
                            hash_value = child.get(name2)
                            if isinstance(hash_value, str) and len(hash_value) == 64 and all(ch in HEX64 for ch in hash_value):
                                candidates.append(hash_value)
                visit(child, name)
        elif isinstance(item, list):
            for child in item:
                visit(child, key)

    visit(value)
    return candidates


def _bind_terminal_artifact(path: Path, value: Mapping[str, Any], role: str,
                            accepted_request_hashes: set[str], *, require_closed: bool = False) -> dict[str, Any]:
    _require_completed_status(value, role)
    candidates = _request_hash_candidates(value)
    if not set(candidates).intersection(accepted_request_hashes):
        raise Root191Error(f"{role} is not bound to the ROOT194 request")
    if require_closed:
        closed = False
        for key, status in _status_values(value):
            lowered = f"{key}:{status}".lower()
            if any(token in lowered for token in ("charge", "ledger", "accounting", "terminal")) and any(
                    token in status.upper() for token in ("COMPLETE", "COMPLETED", "PASS", "SUCCESS", "APPLIED", "CLOSED")):
                closed = True
        if isinstance(value.get("ledger_mutated"), bool) and value.get("ledger_mutated"):
            closed = True
        if isinstance(value.get("charge"), Mapping):
            charge_status = str(value["charge"].get("status", "")).upper()
            closed = closed or any(token in charge_status for token in ("APPLIED", "COMPLETE", "CLOSED", "SUCCESS"))
        if not closed:
            raise Root191Error(f"{role} has no closed same-parent accounting evidence")
    return {"path": str(path), "sha256": sha256_file(path), "status": value.get("status"),
            "request_sha256_candidates": sorted(set(candidates).intersection(accepted_request_hashes))}


def _load_root194_request(path: Path | str) -> tuple[Path, dict[str, Any], Path, dict[str, Any], dict[str, Any]]:
    outer_path, outer = _json(path, "ROOT194 request")
    _contains_stale_actionable({"case_id": outer.get("case_id"), "attempt_id": outer.get("attempt_id")},
                               "ROOT194 request identity")
    if outer.get("schema") == ROOT194_V8_SCHEMA:
        v8_path, v8 = outer_path, outer
        wrapper = None
    elif outer.get("schema") == ROOT194_WRAPPER_SCHEMA:
        if outer.get("fresh_cold_credit") is not False or outer.get("no_old_ROOT060_reuse") is not True:
            raise Root191Error("ROOT194 wrapper is missing its no-old-proof boundary")
        binding = outer.get("consumer_request_binding")
        if not isinstance(binding, Mapping):
            raise Root191Error("ROOT194 wrapper consumer_request_binding is missing")
        v8_path, v8 = _json(binding.get("path"), "ROOT194 inner V8 request")
        if binding.get("sha256") != sha256_file(v8_path):
            raise Root191Error("ROOT194 wrapper inner request file SHA differs")
        if binding.get("canonical_sha256") != v8.get("sha256"):
            raise Root191Error("ROOT194 wrapper inner request canonical SHA differs")
        wrapper = outer
    else:
        raise Root191Error("ROOT194 request schema is neither ds02.request.v1 nor V8")
    if v8.get("schema") != ROOT194_V8_SCHEMA or v8.get("sha256") != canonical_sha(v8):
        raise Root191Error("ROOT194 inner request is not canonical V8")
    case = _new_id(v8.get("case_id"), "ROOT194 case_id", "ROOT194")
    attempt = _new_id(v8.get("attempt_id"), "ROOT194 attempt_id", "ROOT194")
    if wrapper is not None and (wrapper.get("case_id") != case or wrapper.get("attempt_id") != attempt):
        raise Root191Error("ROOT194 wrapper and V8 identity differ")
    if v8.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise Root191Error("ROOT194 proof request is not a parent-ready V8 request")
    if v8.get("model_invoked") is not False or v8.get("cfd_invoked") is not False:
        raise Root191Error("ROOT194 proof request model/CFD boundary is not closed")
    _unknown(v8.get("quality", v8.get("qualification")), "ROOT194 quality")
    marker = v8.get("v12_forward")
    if not isinstance(marker, Mapping) or marker.get("schema") != V12_FORWARD_SCHEMA:
        raise Root191Error("ROOT194 request does not select the V12 proof consumer")
    consumer = marker.get("consumer")
    if not isinstance(consumer, Mapping):
        raise Root191Error("ROOT194 V12 consumer binding is missing")
    consumer_path = _file(consumer.get("path"), "ROOT194 V12 consumer")
    if consumer.get("schema") != "ds02.stage2.f2-fresh-v16-proof-consumer-v12":
        raise Root191Error("ROOT194 V12 consumer schema differs")
    if consumer.get("sha256") != sha256_file(consumer_path):
        raise Root191Error("ROOT194 V12 consumer SHA differs")
    sidecar = marker.get("semantic_sidecar")
    if not isinstance(sidecar, Mapping):
        raise Root191Error("ROOT194 semantic sidecar binding is missing")
    sidecar_path = _file(sidecar.get("path"), "ROOT194 semantic sidecar")
    if sidecar.get("schema") != V12_SIDECAR_SCHEMA or sidecar.get("sha256") != sha256_file(sidecar_path):
        raise Root191Error("ROOT194 semantic sidecar schema/SHA differs")
    current = v8.get("current_manifest_binding")
    if not isinstance(current, Mapping) or current.get("sha256") != CURRENT_SHA:
        raise Root191Error("ROOT194 CURRENT is not exact df7e")
    expected = v8.get("expected")
    if not isinstance(expected, Mapping):
        raise Root191Error("ROOT194 expected source contract is missing")
    source = expected.get("source_binding")
    if not isinstance(source, Mapping) or source.get("current_catalog_sha256") != CURRENT_SHA:
        raise Root191Error("ROOT194 expected source is not exact df7e")
    cohort = expected.get("cohort")
    if not isinstance(cohort, Mapping) or cohort.get("selected_count") != COHORT_COUNT or cohort.get("identity_sha256") != COHORT_IDENTITY_SHA:
        raise Root191Error("ROOT194 cohort is not the source-bound 21114 cohort")
    mass = expected.get("initial_mass_denominator")
    if not isinstance(mass, Mapping) or float(mass.get("denominator_kg", -1)) != DENOMINATOR_KG or float(mass.get("later_missing_mass_kg", -1)) != LATER_MISSING_KG:
        raise Root191Error("ROOT194 mass contract differs from the frozen source")
    result = v8.get("result")
    if not isinstance(result, Mapping):
        raise Root191Error("ROOT194 result binding is missing")
    result_sha = _sha(result.get("sha256"), "ROOT194 V16 result SHA")
    result_bytes = result.get("bytes")
    if isinstance(result_bytes, bool) or not isinstance(result_bytes, int) or result_bytes <= 0:
        raise Root191Error("ROOT194 V16 result bytes are invalid")
    typed = result.get("typed_output")
    if not isinstance(typed, Mapping) or _sha(typed.get("sha256"), "ROOT194 typed H5 SHA") != TYPED_H5_SHA or typed.get("bytes") != TYPED_H5_BYTES:
        raise Root191Error("ROOT194 derived typed H5 is not the actual 179C product")
    typed_path = _absolute_path(typed.get("path"), "ROOT194 typed H5 path")
    # Do not stat or open these payloads here.  The producer request carries
    # the expected bytes/stat, while the actual parent guard performs the
    # after-reservation content/stat check.  In particular, the V16 result is
    # tens of megabytes and must not be read by this metadata-only builder.
    typed_stat = typed.get("stat") if isinstance(typed.get("stat"), Mapping) else {
        "bytes": TYPED_H5_BYTES,
    }
    if typed_stat.get("bytes") != TYPED_H5_BYTES:
        raise Root191Error("ROOT194 typed H5 producer stat differs from the frozen product")
    result_path = _absolute_path(result.get("path"), "ROOT194 V16 result")
    result_stat = result.get("stat") if isinstance(result.get("stat"), Mapping) else {
        "bytes": result_bytes,
    }
    if result_stat.get("bytes") != result_bytes:
        raise Root191Error("ROOT194 V16 result producer stat differs from its binding")
    roots = v8.get("fresh_proof_namespace", {})
    fresh_root = roots.get("root") if isinstance(roots, Mapping) else None
    if not isinstance(fresh_root, str) or "root194" not in fresh_root.lower() or any(token in fresh_root.lower() for token in STALE_ACTIONABLE):
        raise Root191Error("ROOT194 fresh proof namespace is not actionable")
    return outer_path, outer, v8_path, v8, {
        "case_id": case, "attempt_id": attempt, "consumer": {"path": str(consumer_path), "sha256": sha256_file(consumer_path)},
        "sidecar": {"path": str(sidecar_path), "sha256": sha256_file(sidecar_path)},
        "result": {"path": str(result_path), "sha256": result_sha, "bytes": int(result_bytes), "stat": dict(result_stat)},
        "payload_content_verification": "PARENT_AFTER_RESERVATION",
        "typed_h5": {"path": str(typed_path), "sha256": TYPED_H5_SHA, "bytes": TYPED_H5_BYTES, "stat": dict(typed_stat)},
        "current": {"path": str(_file(current.get("path"), "ROOT194 CURRENT")), "sha256": CURRENT_SHA},
        "outer_file_sha256": sha256_file(outer_path), "v8_file_sha256": sha256_file(v8_path),
        "v8_canonical_sha256": v8["sha256"], "fresh_root": str(Path(fresh_root).expanduser().resolve()),
    }


def _validate_v12_proof(path: Path, v8_path: Path, v8: Mapping[str, Any], info: Mapping[str, Any]) -> dict[str, Any]:
    proof_path, proof = _json(path, "ROOT194 V12 proof", max_bytes=MAX_PROOF_BYTES)
    if proof.get("schema") != V8_PROOF_SCHEMA or proof.get("sha256") != canonical_sha(proof):
        raise Root191Error("ROOT194 fresh proof is not canonical V8")
    if proof.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise Root191Error("ROOT194 fresh proof is not completed")
    _unknown(proof.get("quality"), "ROOT194 proof quality")
    _unknown(proof.get("qualification"), "ROOT194 proof qualification")
    execution = proof.get("execution")
    if not isinstance(execution, Mapping) or execution.get("hdf5_or_bi4_content_read") is not False or execution.get("raw_opened") is not False:
        raise Root191Error("ROOT194 V12 proof is not JSON-only")
    adapter = proof.get("v12_semantic_scope_adapter")
    if not isinstance(adapter, Mapping) or adapter.get("schema") != V12_FORWARD_SCHEMA:
        raise Root191Error("ROOT194 proof lacks the V12 semantic adapter")
    if adapter.get("normalized_for_v8_only") is not True or adapter.get("original_result_bytes_unchanged") is not True:
        raise Root191Error("ROOT194 proof does not preserve immutable result bytes")
    sidecar_path = _file(adapter.get("sidecar_path"), "ROOT194 proof sidecar")
    if adapter.get("sidecar_sha256") != sha256_file(sidecar_path):
        raise Root191Error("ROOT194 proof sidecar SHA differs")
    request = proof.get("request")
    if not isinstance(request, Mapping) or Path(str(request.get("path"))).expanduser().resolve() != v8_path.resolve():
        raise Root191Error("ROOT194 proof points at a different V8 request")
    if request.get("sha256") != v8.get("sha256"):
        raise Root191Error("ROOT194 proof request canonical SHA differs")
    source_result = proof.get("source_result")
    if not isinstance(source_result, Mapping) or source_result.get("sha256") != info["result"]["sha256"] or source_result.get("bytes") != info["result"]["bytes"] or source_result.get("content_sha_verified") is not True:
        raise Root191Error("ROOT194 proof does not bind the requested V16 result")
    binding = proof.get("source_binding")
    if not isinstance(binding, Mapping) or binding.get("current_catalog_sha256") != CURRENT_SHA:
        raise Root191Error("ROOT194 proof source binding is not exact df7e")
    return {"path": str(proof_path), "file_sha256": sha256_file(proof_path), "canonical_sha256": proof["sha256"],
            "schema": proof["schema"], "result_sha256": info["result"]["sha256"],
            "status": proof["status"], "adapter": {"schema": adapter["schema"], "sidecar_sha256": adapter["sidecar_sha256"]}}


def _build_request(*, root194_request: Path, parent_report: Path, receipt: Path,
                   root_proof: Path, v12_proof: Path, frozen_request: Path,
                   output: Path, case_id: str, attempt_id: str,
                   fresh_output_root: Path, max_wall_seconds: float = 900.0) -> dict[str, Any]:
    outer_path, outer, v8_path, v8, info = _load_root194_request(root194_request)
    case = _new_id(case_id, "ROOT191 case_id", "ROOT191")
    attempt = _new_id(attempt_id, "ROOT191 attempt_id", "ROOT191")
    fresh_root = Path(fresh_output_root).expanduser().resolve()
    if fresh_root.exists():
        raise Root191Error(f"ROOT191 output namespace already exists: {fresh_root}")
    if any(token in str(fresh_root).lower() for token in STALE_ACTIONABLE) or "root191" not in str(fresh_root).lower():
        raise Root191Error("ROOT191 output namespace is not a fresh actionable root")
    frozen_path = _file(frozen_request, "frozen observer/profile request", max_bytes=MAX_METADATA_BYTES)
    frozen_sha = sha256_file(frozen_path)
    _, frozen = _json(frozen_path, "frozen observer/profile request")
    if frozen.get("schema") is None:
        raise Root191Error("frozen observer/profile request lacks a schema")
    accepted = {info["outer_file_sha256"], info["v8_file_sha256"], info["v8_canonical_sha256"]}
    parent_path, parent = _json(parent_report, "ROOT194 parent report")
    parent_info = _bind_terminal_artifact(parent_path, parent, "ROOT194 parent report", accepted)
    receipt_path, receipt_value = _json(receipt, "ROOT194 completed receipt")
    receipt_info = _bind_terminal_artifact(receipt_path, receipt_value, "ROOT194 completed receipt", accepted)
    proof_path, root_value = _json(root_proof, "ROOT194 root proof")
    root_info = _bind_terminal_artifact(proof_path, root_value, "ROOT194 root proof", accepted, require_closed=True)
    _contains_stale_actionable({"parent": parent_info, "receipt": receipt_info, "root": root_info},
                               "ROOT194 terminal artefacts")
    v12_info = _validate_v12_proof(_file(v12_proof, "ROOT194 V12 proof", max_bytes=MAX_PROOF_BYTES), v8_path, v8, info)

    if not isinstance(max_wall_seconds, (int, float)) or isinstance(max_wall_seconds, bool) or float(max_wall_seconds) <= 0:
        raise Root191Error("max_wall_seconds must be positive")
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
        "root194_binding": {
            "outer_request": {"path": str(outer_path), "file_sha256": info["outer_file_sha256"], "schema": outer.get("schema")},
            "v8_request": {"path": str(v8_path), "file_sha256": info["v8_file_sha256"], "canonical_sha256": info["v8_canonical_sha256"], "schema": v8["schema"]},
            "case_id": info["case_id"], "attempt_id": info["attempt_id"],
            "parent_report": parent_info,
            "completed_receipt": receipt_info,
            "root_proof": root_info,
            "fresh_v12_proof": v12_info,
            "typed_h5": dict(info["typed_h5"]),
            "current": dict(info["current"]),
            "result": dict(info["result"]),
        },
        "frozen_profile_binding": {"path": str(frozen_path), "sha256": frozen_sha, "schema": frozen["schema"],
                                    "content_verification": "PARENT_AFTER_RESERVATION"},
        "source_binding": {
            "current_catalog_sha256": CURRENT_SHA,
            "cohort_selected_count": COHORT_COUNT,
            "cohort_identity_sha256": COHORT_IDENTITY_SHA,
            "initial_denominator_kg": DENOMINATOR_KG,
            "later_missing_mass_kg": LATER_MISSING_KG,
            "typed_h5_sha256": TYPED_H5_SHA,
            "typed_h5_bytes": TYPED_H5_BYTES,
            "typed_h5_content_read_by_builder": False,
        },
        "evaluator_binding": {
            "entrypoint": {"path": str(SCRIPT), "sha256": sha256_file(SCRIPT), "schema": REQUEST_SCHEMA},
            "existing_typed_evaluator_v1": {"path": str(V1_EVALUATOR_SCRIPT), "sha256": sha256_file(V1_EVALUATOR_SCRIPT)},
            "existing_no_model_evaluator_v3": {"path": str(V3_EVALUATOR_SCRIPT), "sha256": sha256_file(V3_EVALUATOR_SCRIPT)},
            "fresh_proof_consumer_v12": {"path": str(V12_SCRIPT), "sha256": sha256_file(V12_SCRIPT), "schema": V12_FORWARD_SCHEMA},
            "fresh_proof_template_v66": {"path": str(V66_TEMPLATE_SCRIPT),
                                          "sha256": sha256_file(V66_TEMPLATE_SCRIPT),
                                          "request_schema": ROOT194_V8_SCHEMA,
                                          "consumed_by": "ROOT194 producer metadata only"},
            "compatibility": "V12 proof retains V8 proof schema; ROOT191 validates v12_semantic_scope_adapter before the model-free operator stage",
        },
        "execution": {
            "command_template": [sys.executable, str(SCRIPT), "run", "--request", "{request}", "--output", "{output}", "--parent-pid", "{parent_pid}"],
            "max_wall_seconds": float(max_wall_seconds),
            "read_hdf5_or_bi4": False,
            "raw_opened": False,
            "model_invoked": False,
            "cfd_invoked": False,
            "original_path_fallback": "FORBIDDEN",
            "result_content_verification": "PARENT_AFTER_RESERVATION",
            "typed_h5_role": "PROVENANCE_ONLY; evaluator does not open HDF5",
            "v16_json_role": "JSON_ONLY_AFTER_PARENT_RESERVATION",
        },
        "fresh_output_namespace": {"root": str(fresh_root), "is_new": True},
        "old_proof_reuse": False,
        "fresh_cold_credit": False,
        "limitations": [
            "ROOT194 completion, root proof, receipt, and V12 proof are all required; absence/failure rejects this request.",
            "ROOT190/ROOT060 proofs and failed receipts cannot satisfy the ROOT191 binding.",
            "The 1,191,110,528-byte typed HDF5 is source metadata only; no HDF5/BI4/raw content is read by this builder or evaluator.",
            "The evaluator is a model-free DEVELOPMENT operator stage. QI/QN/QE and raw-to-typed/portable-cold credit remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(target),
            "sha256": sha256_file(target), "canonical_sha256": request["sha256"],
            "root194_request_file_sha256": info["outer_file_sha256"],
            "root194_v12_proof_file_sha256": v12_info["file_sha256"],
            "typed_h5_sha256": TYPED_H5_SHA, "typed_h5_bytes": TYPED_H5_BYTES,
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def validate_request(path: Path | str) -> dict[str, Any]:
    request_path, request = _json(path, "ROOT191 evaluator request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise Root191Error("ROOT191 request schema/canonical SHA differs")
    _new_id(request.get("case_id"), "ROOT191 case_id", "ROOT191")
    _new_id(request.get("attempt_id"), "ROOT191 attempt_id", "ROOT191")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("model_invoked") is not False:
        raise Root191Error("ROOT191 request is not model-free parent-ready")
    _unknown(request.get("qualification"), "ROOT191 qualification")
    root = request.get("root194_binding")
    if not isinstance(root, Mapping):
        raise Root191Error("ROOT191 ROOT194 binding is missing")
    if root.get("fresh_v12_proof", {}).get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise Root191Error("ROOT191 request does not bind a completed V12 proof")
    typed = root.get("typed_h5")
    if not isinstance(typed, Mapping) or typed.get("sha256") != TYPED_H5_SHA or typed.get("bytes") != TYPED_H5_BYTES:
        raise Root191Error("ROOT191 typed H5 binding differs")
    evaluator = request.get("evaluator_binding")
    if not isinstance(evaluator, Mapping):
        raise Root191Error("ROOT191 evaluator source closure is missing")
    for role in ("fresh_proof_consumer_v12", "fresh_proof_template_v66", "existing_typed_evaluator_v1",
                 "existing_no_model_evaluator_v3", "entrypoint"):
        binding = evaluator.get(role)
        if not isinstance(binding, Mapping):
            raise Root191Error(f"ROOT191 evaluator source role is missing: {role}")
        source = _file(binding.get("path"), f"ROOT191 evaluator source {role}")
        if binding.get("sha256") != sha256_file(source):
            raise Root191Error(f"ROOT191 evaluator source SHA differs: {role}")
    if evaluator["fresh_proof_template_v66"].get("request_schema") != ROOT194_V8_SCHEMA:
        raise Root191Error("ROOT191 V66 template request schema is not V8")
    if request.get("old_proof_reuse") is not False or request.get("fresh_cold_credit") is not False:
        raise Root191Error("ROOT191 old-proof/cold-credit boundary is not closed")
    return {"schema": "ds02.stage2.f2-root191-metadata-preflight.v1", "status": "ROOT191_METADATA_VALIDATED_READY_FOR_PARENT",
            "request": {"path": str(request_path), "file_sha256": sha256_file(request_path), "canonical_sha256": request["sha256"]},
            "root194_v12_proof": root["fresh_v12_proof"], "typed_h5": typed,
            "payload_read": False, "hdf5_or_bi4_read": False, "qualification": dict(UNKNOWN)}


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise Root191Error(f"cannot load evaluator module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_trial(request_path: Path | str, *, output: Path | str, parent_pid: int | None = None) -> dict[str, Any]:
    """Run the JSON-only no-model bridge after an outer parent reservation.

    This intentionally does not open the typed HDF5.  It loads the V16 JSON,
    validates it against the real V12/V8 contract in memory, then reuses the
    existing V1 score contract.  The caller owns the reservation and process
    ancestry; a direct parent check is required for an approved run.
    """
    request_file, request = _json(request_path, "ROOT191 evaluator request")
    validate_request(request_file)
    if parent_pid is None or os.getppid() != int(parent_pid):
        raise Root191Error("ROOT191 run requires the direct parent guard")
    root = request["root194_binding"]
    proof_req_path, proof_req = _json(root["v8_request"]["path"], "ROOT194 V8 proof request")
    proof_path = _file(root["fresh_v12_proof"]["path"], "ROOT194 V12 proof", max_bytes=MAX_PROOF_BYTES)
    info = {"result": root["result"]}
    _validate_v12_proof(proof_path, proof_req_path, proof_req, info)
    result_path = _file(root["result"]["path"], "V16 JSON result", max_bytes=100_000_000)
    result_sha = sha256_file(result_path)
    if result_sha != root["result"]["sha256"]:
        raise Root191Error("V16 JSON result SHA differs from ROOT194 binding")
    v12 = _load(V12_SCRIPT, "ds02_bound_root191_v12")
    v1 = _load(V1_EVALUATOR_SCRIPT, "ds02_bound_root191_typed_v1")
    bound = v12.V8._validate_request(proof_req, verify_result_stat=True)
    raw_result = v12.V8._read_result(result_path, int(bound["max_result_bytes"]))[0]
    contract = v12._load_marker(proof_req_path)[2]
    old_validator = v12._ACTIVE_SCOPE
    v12._ACTIVE_SCOPE = contract
    try:
        summary = v12._validate_result_v12(raw_result, bound, result_sha, result_path.stat().st_size)
    finally:
        v12._ACTIVE_SCOPE = old_validator
    frozen_path = _file(request["frozen_profile_binding"]["path"], "frozen observer/profile request")
    frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
    adapted_score = v1._score_typed_result(raw_result, frozen)
    report: dict[str, Any] = {
        "schema": REPORT_SCHEMA,
        "status": "PASS_DEVELOPMENT_TYPED_ONLY_NO_MODEL_OPERATOR_TRIAL_ROOT191",
        "request": {"path": str(request_file), "file_sha256": sha256_file(request_file), "canonical_sha256": request["sha256"]},
        "root194_v12_proof": root["fresh_v12_proof"],
        "typed_only_product": {"result_path": str(result_path), "result_sha256": result_sha,
                                "result_bytes": result_path.stat().st_size,
                                "typed_h5": root["typed_h5"], "hdf5_or_bi4_content_read": False,
                                "raw_opened": False},
        "v12_result_validation": summary,
        "operator_score": adapted_score,
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "credit_boundary": {"typed_only": True, "raw_to_typed_credit": "NOT_CLAIMED",
                             "portable_cold_replay_credit": "NOT_CLAIMED", "scientific_qualification": "UNKNOWN"},
    }
    report["sha256"] = canonical_sha(report)
    _write_new(output, report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-request")
    for name in ("root194-request", "parent-report", "receipt", "root-proof", "v12-proof", "frozen-request", "output"):
        build.add_argument(f"--{name}", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    build.add_argument("--max-wall-seconds", type=float, default=900.0)
    validate = sub.add_parser("validate")
    validate.add_argument("--request", type=Path, required=True)
    run = sub.add_parser("run")
    run.add_argument("--request", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--parent-pid", type=int, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            value = _build(root194_request=args.root194_request.absolute(), parent_report=args.parent_report.absolute(),
                           receipt=args.receipt.absolute(), root_proof=args.root_proof.absolute(),
                           v12_proof=args.v12_proof.absolute(), frozen_request=args.frozen_request.absolute(),
                           output=args.output.absolute(), case_id=args.case_id, attempt_id=args.attempt_id,
                           fresh_output_root=args.fresh_output_root.absolute(), max_wall_seconds=args.max_wall_seconds)
        elif args.command == "validate":
            value = validate_request(args.request.absolute())
        else:
            value = run_trial(args.request.absolute(), output=args.output.absolute(), parent_pid=args.parent_pid)
    except (Root191Error, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"ROOT191 typed-only no-model evaluator: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"status": value.get("status"), "sha256": value.get("sha256"),
                      "qualification": value.get("qualification", UNKNOWN)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
