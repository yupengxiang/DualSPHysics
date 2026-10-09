#!/usr/bin/env python3
"""Convert a fresh V50 seal or V47 evaluator descriptor to evaluator-v4.

The V47 terminal sealer deliberately emits a hand-off descriptor whose
``target_evaluator_schema`` is v4; it is not itself an evaluator-v4 request.
For a completed V50 producer it consumes the immutable V50 terminal seal and
the separately produced fresh V10 proof; the seal is transformed into an
in-memory descriptor and is never rewritten.  The legacy V47 descriptor path
is retained for development compatibility.  Both paths consume the fresh V10
request, the terminal manifest's relocated V15 request, and an explicit
copied-code closure.  They only read bounded JSON/code metadata and stat
records.  Producer result/proof content is verified later by the evaluator's
own same-parent guard.

No ROOT060/aabfb input or original-worktree fallback is accepted.  Every code
role used by evaluator v4 and its proof/operator imports must be listed in the
post-terminal closure manifest and point inside its private runtime root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import stat
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
REQUEST_SCHEMA = "ds02.stage2.f2-no-model-evaluator-request.v4"
V47_DESCRIPTOR_SCHEMA = "ds02.stage2.f2-v47-fresh-no-model-evaluator-request.v1"
DESCRIPTOR_SCHEMA = "ds02.stage2.f2-v50-fresh-no-model-evaluator-descriptor.v2"
V50_SEAL_SCHEMA = "ds02.stage2.f2-v50-producer-terminal-seal.v2"
V50_SEAL_STATUS = "READY_FOR_PARENT_V10_SEMANTIC_GUARD_V2"
V10_PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
V10_PROOF_STATUS = "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN"
CLOSURE_SCHEMA = "ds02.stage2.f2-postterminal-evaluator-runtime-closure.v1"
CLOSURE_STATUS = "READY_FOR_PARENT_EVALUATOR_GUARD"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 8 * 1024 * 1024
REQUIRED_CLOSURE_ROLES = {
    "python_executable", "evaluator_v4", "evaluator_v3", "evaluator_v2",
    "v14_operator", "v15_operator", "v16_operator", "raw_converter",
    "raw_reconstruction_worker", "proof_consumer_v11", "proof_consumer_v10",
    "proof_consumer_v9", "proof_consumer_v8", "v47_terminal_sealer_v1",
    "v47_fresh_product_interface_v1",
}


class EvaluatorAdapterError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(c not in HEX64 for c in value):
        raise EvaluatorAdapterError(f"{role} must be a lowercase SHA-256")
    return value


def _file(path: Any, role: str, *, max_bytes: int = MAX_METADATA_BYTES) -> Path:
    if not isinstance(path, (str, Path)) or not str(path).startswith("/"):
        raise EvaluatorAdapterError(f"{role} must be an absolute path")
    target = Path(path).expanduser()
    if target.is_symlink() or not target.is_file():
        raise EvaluatorAdapterError(f"{role} must be a regular non-symlink file: {target}")
    if target.stat().st_size > max_bytes:
        raise EvaluatorAdapterError(f"{role} exceeds the bounded metadata size")
    return target


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluatorAdapterError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluatorAdapterError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise EvaluatorAdapterError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _stat(path: Path) -> dict[str, int]:
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise EvaluatorAdapterError(f"bound input is not a regular non-symlink file: {path}")
    return {"bytes": int(info.st_size), "mtime_ns": int(info.st_mtime_ns),
            "mode_bits": int(stat.S_IMODE(info.st_mode))}


def _declared_binding(value: Any, role: str, *, under: Path | None = None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise EvaluatorAdapterError(f"{role} binding is missing")
    path = _file(value.get("path"), role, max_bytes=2**63 - 1)
    if under is not None:
        try:
            path.relative_to(under)
        except ValueError as error:
            raise EvaluatorAdapterError(f"{role} is outside its declared fresh namespace") from error
    sha = _sha(value.get("sha256"), f"{role}.sha256")
    raw_bytes = value.get("bytes")
    if isinstance(raw_bytes, bool) or not isinstance(raw_bytes, int) or raw_bytes != path.stat().st_size:
        raise EvaluatorAdapterError(f"{role}.bytes differs from current stat")
    declared_stat = value.get("stat")
    if isinstance(declared_stat, Mapping):
        actual = _stat(path)
        for key in ("bytes", "mtime_ns", "mode_bits"):
            if key in declared_stat and int(declared_stat[key]) != actual[key]:
                raise EvaluatorAdapterError(f"{role}.stat.{key} differs")
    return {"path": str(path), "sha256": sha, "bytes": int(raw_bytes),
            "stat": _stat(path), "content_verification_phase": "AFTER_PARENT_RESERVATION"}


def _validate_descriptor(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") not in {V47_DESCRIPTOR_SCHEMA, DESCRIPTOR_SCHEMA}:
        raise EvaluatorAdapterError("source descriptor is not a V47/V50 fresh evaluator descriptor")
    if value.get("status") != "READY_FOR_PARENT_EVALUATOR_GUARD":
        raise EvaluatorAdapterError("source descriptor is not evaluator-guard ready")
    if value.get("sha256") != canonical_sha(value):
        raise EvaluatorAdapterError("source descriptor canonical SHA differs")
    if value.get("model_invoked") is not False or value.get("cfd_invoked") is not False:
        raise EvaluatorAdapterError("descriptor model/CFD boundary is not closed")
    if value.get("qualification") != UNKNOWN or value.get("target_evaluator_schema") != REQUEST_SCHEMA:
        raise EvaluatorAdapterError("descriptor target/qualification differs")
    source_identity = value.get("source_identity")
    if not isinstance(source_identity, Mapping):
        raise EvaluatorAdapterError("descriptor source identity is missing")
    if source_identity.get("historical_overlay_input_policy") != "FORBIDDEN; provenance only":
        raise EvaluatorAdapterError("descriptor historical overlay policy differs")
    if "ROOT060" in json.dumps(value, sort_keys=True):
        # A literal policy string is useful; actionable old paths are not.
        for key in ("result", "fresh_v10_request", "fresh_v10_proof", "producer_report"):
            if "ROOT060" in str(value.get(key)):
                raise EvaluatorAdapterError(f"descriptor {key} contains ROOT060")
    return dict(value)


def _binding_for_json(path: Path, role: str) -> dict[str, Any]:
    """Return a bounded canonical JSON binding without reading any product."""
    target, value = _json(path, role)
    if value.get("sha256") != canonical_sha(value):
        raise EvaluatorAdapterError(f"{role} canonical SHA differs")
    return {
        "path": str(target), "sha256": str(value["sha256"]),
        "bytes": int(target.stat().st_size), "stat": _stat(target),
    }


def _descriptor_from_v50_seal(*, seal_path: Path, seal: Mapping[str, Any],
                              v10_path: Path, v10: Mapping[str, Any],
                              proof_path: Path) -> dict[str, Any]:
    """Adapt the additive V50 seal into the descriptor contract in memory.

    The V50 sealer intentionally does not rewrite itself after the semantic
    proof is produced.  This adapter therefore accepts the immutable seal plus
    the newly produced proof and derives a v2 descriptor in memory.  The
    descriptor is still bound to the actual V50 seal and proof paths; it is not
    a claim that the old V47 descriptor was used.
    """
    if seal.get("schema") != V50_SEAL_SCHEMA or seal.get("status") != V50_SEAL_STATUS:
        raise EvaluatorAdapterError("V50 terminal seal is not the additive V2 seal")
    if seal.get("sha256") != canonical_sha(seal):
        raise EvaluatorAdapterError("V50 terminal seal canonical SHA differs")
    # The immutable V50 seal may mention ROOT060 in an explicit policy string
    # (``old_root060_reuse=FORBIDDEN``).  Only actionable path/provenance
    # fields are forbidden here; a policy sentence must not make every real
    # V50 seal unusable.
    for key in ("v10_request", "producer_adapter", "terminal_manifest", "source_contract", "source_identity"):
        if "ROOT060" in str(seal.get(key)):
            raise EvaluatorAdapterError(f"V50 terminal seal {key} contains an actionable ROOT060 binding")
    v10_ref = seal.get("v10_request")
    if not isinstance(v10_ref, Mapping) or v10_ref.get("path") != str(v10_path):
        raise EvaluatorAdapterError("V50 terminal seal does not bind the supplied V10 request")
    if v10_ref.get("sha256") != v10.get("sha256"):
        raise EvaluatorAdapterError("V50 terminal seal V10 SHA differs")

    proof_path, proof = _json(proof_path, "fresh V10 semantic proof")
    if proof.get("schema") != V10_PROOF_SCHEMA or proof.get("status") != V10_PROOF_STATUS:
        raise EvaluatorAdapterError("fresh V10 proof is not a completed development proof")
    if proof.get("quality") != UNKNOWN or proof.get("qualification") != UNKNOWN:
        raise EvaluatorAdapterError("fresh V10 proof quality/qualification is not UNKNOWN")
    source_result = proof.get("source_result")
    result = v10.get("result")
    if not isinstance(source_result, Mapping) or not isinstance(result, Mapping):
        raise EvaluatorAdapterError("fresh proof/result binding is missing")
    if source_result.get("path") != result.get("path") or source_result.get("sha256") != result.get("sha256"):
        raise EvaluatorAdapterError("fresh proof is bound to a different V16 result")
    if source_result.get("content_sha_verified") is not True:
        raise EvaluatorAdapterError("fresh proof does not attest V16 content SHA")
    guard = proof.get("parent_guard")
    if not isinstance(guard, Mapping) or guard.get("supplied") is not True:
        raise EvaluatorAdapterError("fresh proof has no parent guard record")
    proof_source = proof.get("source_binding")
    expected = v10.get("expected")
    expected_source = expected.get("source_binding") if isinstance(expected, Mapping) else None
    if not isinstance(proof_source, Mapping) or not isinstance(expected_source, Mapping):
        raise EvaluatorAdapterError("fresh proof/source expected binding is missing")
    relocated = expected_source.get("current_catalog_sha256")
    if proof_source.get("current_catalog_sha256") != relocated:
        raise EvaluatorAdapterError("fresh proof relocated CURRENT digest differs")
    if relocated in {None, "", "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b",
                     "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"}:
        raise EvaluatorAdapterError("fresh proof runtime view is missing or stale")
    if proof_source.get("original_current_catalog_sha256",
                         proof_source.get("actual_current_catalog_sha256")) != \
            "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise EvaluatorAdapterError("fresh proof exact CURRENT provenance is not df7e")
    marker = v10.get("v11_forward")
    if not isinstance(marker, Mapping) or marker.get("actual_current_catalog_sha256") != \
            "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise EvaluatorAdapterError("fresh V10 request lacks exact CURRENT provenance marker")

    producer_ref = seal.get("producer_adapter")
    if not isinstance(producer_ref, Mapping):
        raise EvaluatorAdapterError("V50 terminal seal producer adapter binding is missing")
    adapter_path, adapter = _json(producer_ref.get("path"), "V50 producer adapter")
    if producer_ref.get("sha256") != hashlib.sha256(adapter_path.read_bytes()).hexdigest():
        raise EvaluatorAdapterError("V50 producer adapter SHA differs")
    if adapter.get("schema") != "ds02.stage2.f2-s1-typed-label-only-report.v1" or \
            adapter.get("sha256") != canonical_sha(adapter):
        raise EvaluatorAdapterError("V50 producer adapter is not canonical")
    raw_report = adapter.get("raw_to_label_report")
    if not isinstance(raw_report, Mapping):
        raise EvaluatorAdapterError("V50 producer adapter lacks raw-to-label binding")
    source_identity = seal.get("source_identity")
    if not isinstance(source_identity, Mapping):
        raise EvaluatorAdapterError("V50 terminal source identity is missing")
    actual_current = source_identity.get("actual_current_catalog_sha256")
    if actual_current != "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b":
        raise EvaluatorAdapterError("V50 terminal exact CURRENT provenance differs")
    descriptor = {
        "schema": DESCRIPTOR_SCHEMA, "status": "READY_FOR_PARENT_EVALUATOR_GUARD",
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "target_evaluator_schema": REQUEST_SCHEMA,
        "source_identity": {
            **dict(source_identity),
            "historical_overlay_input_policy": "FORBIDDEN; provenance only",
            "v50_terminal_seal": {"path": str(seal_path), "sha256": str(seal["sha256"])},
        },
        "fresh_v10_request": {"path": str(v10_path), "sha256": str(v10["sha256"])},
        "fresh_v10_proof": _binding_for_json(proof_path, "fresh V10 semantic proof"),
        "raw_to_label_report": dict(raw_report),
        "source_contract": dict(v10.get("source_contract", {})),
        "producer_adapter": {"path": str(adapter_path), "sha256": str(producer_ref["sha256"])},
        "v50_terminal_seal": {"path": str(seal_path), "sha256": str(seal["sha256"])},
        "fresh_result_source": {"path": result.get("path"), "sha256": result.get("sha256")},
    }
    descriptor["sha256"] = canonical_sha(descriptor)
    return descriptor


def _validate_closure(path: Path, value: Mapping[str, Any]) -> tuple[Path, list[dict[str, Any]]]:
    if value.get("schema") != CLOSURE_SCHEMA or value.get("status") != CLOSURE_STATUS:
        raise EvaluatorAdapterError("post-terminal evaluator closure schema/status differs")
    root_value = value.get("runtime_root")
    if not isinstance(root_value, str) or not root_value.startswith("/"):
        raise EvaluatorAdapterError("post-terminal runtime_root is missing")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise EvaluatorAdapterError(f"post-terminal runtime_root is missing: {root}")
    if value.get("original_path_fallback") != "FORBIDDEN":
        raise EvaluatorAdapterError("post-terminal closure permits original fallback")
    rows = value.get("roles")
    if not isinstance(rows, list) or not rows:
        raise EvaluatorAdapterError("post-terminal closure roles are missing")
    roles: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or not isinstance(raw.get("role"), str):
            raise EvaluatorAdapterError(f"closure role {index} is malformed")
        role = str(raw["role"])
        if role in roles:
            raise EvaluatorAdapterError(f"duplicate closure role: {role}")
        roles[role] = _declared_binding(raw, f"closure.{role}", under=root)
    missing = REQUIRED_CLOSURE_ROLES.difference(roles)
    if missing:
        raise EvaluatorAdapterError(f"post-terminal closure misses roles: {sorted(missing)}")
    return root, [{"role": role, **binding} for role, binding in sorted(roles.items())]


def _v10_inputs(path: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    if value.get("schema") != "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8":
        raise EvaluatorAdapterError("fresh V10 request schema differs")
    if value.get("status") != "READY_FOR_PARENT_GUARD" or value.get("sha256") != canonical_sha(value):
        raise EvaluatorAdapterError("fresh V10 request is not canonical/guard-ready")
    if value.get("qualification") != UNKNOWN or value.get("execution", {}).get("original_path_fallback") != "FORBIDDEN":
        raise EvaluatorAdapterError("fresh V10 request policy differs")
    result = _declared_binding(value.get("result"), "fresh V16 result")
    proof_ref = value.get("v11_forward", {}).get("consumer") if isinstance(value.get("v11_forward"), Mapping) else None
    source_contract = value.get("source_contract")
    if not isinstance(source_contract, Mapping):
        raise EvaluatorAdapterError("fresh V10 source contract binding is missing")
    return {"path": str(path), "value": dict(value), "result": result,
            "source_contract": dict(source_contract), "proof_consumer": proof_ref}


def _terminal_v15(manifest_path: Path, manifest: Mapping[str, Any]) -> dict[str, Any]:
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise EvaluatorAdapterError("terminal manifest artifacts are missing")
    row = artifacts.get("relocated_v15_request")
    binding = _declared_binding(row, "terminal relocated V15 request")
    path = Path(binding["path"])
    value = _json(path, "relocated V15 request")[1]
    if value.get("schema") != "ds02.stage2.f2-s1-replay-request.v15":
        raise EvaluatorAdapterError("relocated V15 request schema differs")
    if "ROOT060" in str(path) or "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972" in str(path):
        raise EvaluatorAdapterError("relocated V15 request is historical")
    current = value.get("current_binding")
    if isinstance(current, Mapping):
        for key in ("current_catalog_sha256", "catalog_sha256", "current_catalog_identity_sha256"):
            if current.get(key) == "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972":
                raise EvaluatorAdapterError("relocated V15 request carries the historical overlay as actionable CURRENT")
    return {"path": str(path), "value": value, **binding}


def build_request(*, descriptor: Path | str | None = None,
                  fresh_v10_request: Path | str,
                  terminal_manifest: Path | str, runtime_closure: Path | str,
                  output: Path | str, v50_seal: Path | str | None = None,
                  fresh_proof: Path | str | None = None) -> dict[str, Any]:
    if (descriptor is None) == (v50_seal is None):
        raise EvaluatorAdapterError("supply exactly one of --descriptor or --v50-seal")
    v10_path, v10_value = _json(fresh_v10_request, "fresh V10 request")
    v10 = _v10_inputs(v10_path, v10_value)
    descriptor_from_seal = v50_seal is not None
    if descriptor_from_seal:
        if fresh_proof is None:
            raise EvaluatorAdapterError("--fresh-proof is required with --v50-seal")
        descriptor_path, seal_value = _json(v50_seal, "V50 terminal seal")
        descriptor_value = _descriptor_from_v50_seal(
            seal_path=descriptor_path, seal=seal_value,
            v10_path=v10_path, v10=v10_value, proof_path=_file(fresh_proof, "fresh V10 proof"))
    else:
        descriptor_path, descriptor_value = _json(descriptor, "V47 evaluator descriptor")
    descriptor_value = _validate_descriptor(descriptor_path, descriptor_value)
    descriptor_v10 = descriptor_value.get("fresh_v10_request")
    if not isinstance(descriptor_v10, Mapping) or descriptor_v10.get("path") != str(v10_path):
        raise EvaluatorAdapterError("descriptor does not bind the supplied fresh V10 request")
    if descriptor_v10.get("sha256") != _sha(v10_value.get("sha256"), "fresh V10 canonical SHA"):
        raise EvaluatorAdapterError("descriptor fresh V10 SHA differs")
    manifest_path, manifest = _json(terminal_manifest, "terminal manifest")
    v15 = _terminal_v15(manifest_path, manifest)
    closure_path, closure = _json(runtime_closure, "post-terminal evaluator closure")
    runtime_root, closure_rows = _validate_closure(closure_path, closure)
    result = v10["result"]
    proof = _declared_binding(descriptor_value.get("fresh_v10_proof"), "fresh V10 proof")
    raw_report = _declared_binding(descriptor_value.get("raw_to_label_report"), "fresh raw-to-label report")
    source_contract = descriptor_value.get("source_contract")
    if not isinstance(source_contract, Mapping):
        raise EvaluatorAdapterError("descriptor source contract is missing")
    # Copy the source-bound observer/profile fields from the relocated V15
    # request.  This avoids the stale V3/ROOT060 template entirely.
    request: dict[str, Any] = {
        "schema": REQUEST_SCHEMA,
        "request_id": "f2-s1-no-model-evaluator-v4-fresh-v50-adapter-001",
        "role": "DEVELOPMENT", "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "scope": "F2-S1 fresh V50 raw-to-typed-to-label model-free operator evaluation",
        "current_binding": dict(v15["value"].get("current_binding", {})),
        "trajectory_h5": dict(v15["value"].get("trajectory_h5", {})),
        "source_files": list(v15["value"].get("source_files", [])),
        "cohort": dict(v15["value"].get("cohort", {})),
        "case_identity": v15["value"].get("case_identity"),
        "observer_profile": dict(v15["value"].get("observer_profile", {})),
        "motion_completion_semantics": dict(v15["value"].get("motion_completion_semantics", {})),
        "frozen_request": {"path": v15["path"], "schema": v15["value"]["schema"],
                           "sha256": v15["sha256"]},
        "result": {**result, "schema": "ds02.stage2.f2-s1-replay-result.v16"},
        "independent_proof": proof,
        "raw_to_label_report": raw_report,
        "source_stat_only": [
            {"role": item.get("role"), "path": item.get("path"),
             "declared_sha256": item.get("sha256"), "access": "stat_only"}
            for item in v15["value"].get("source_files", []) if isinstance(item, Mapping)
        ],
        "trajectory_h5_stat_only": dict(v15["value"].get("trajectory_h5", {})),
        "source_contract": dict(source_contract),
        "v50_producer_descriptor": {
            "path": str(descriptor_path),
            "sha256": _sha(descriptor_value.get("sha256"), "descriptor.sha256"),
            "schema": descriptor_value["schema"],
            "binding_kind": "v50_terminal_seal_transformed_descriptor" if descriptor_from_seal else "v47_descriptor",
            **({"physical_sha256": hashlib.sha256(descriptor_path.read_bytes()).hexdigest()}
               if descriptor_from_seal else {}),
        },
        "v50_terminal_manifest": {"path": str(manifest_path), "sha256": _sha(manifest.get("sha256"), "manifest.sha256")},
        "postterminal_runtime_closure": {"path": str(closure_path),
                                          "sha256": _sha(closure.get("sha256"), "closure.sha256"),
                                          "runtime_root": str(runtime_root),
                                          "roles": closure_rows},
        "input_files": [
            {"role": "v16_label_result", **result},
            {"role": "frozen_v15_request", **v15},
            {"role": "independent_raw_proof", **proof},
            {"role": "raw_to_label_report", **raw_report},
            *closure_rows,
        ],
        "execution": {
            "command": [next(item["path"] for item in closure_rows if item["role"] == "python_executable"),
                         next(item["path"] for item in closure_rows if item["role"] == "evaluator_v4"),
                         "run", "--request", "<this-request>", "--output", "<new-output.json>"],
            "requires_shared_four_guard": True,
            "io_slot": "CPU_JSON_RESULT_AND_SMALL_PROOF;NO_HDF5_OR_BI4_READ",
            "hdf5_or_bi4_read": False, "raw_partout_read": False,
            "original_path_fallback": "FORBIDDEN",
            "private_module_imports_must_match_input_sha256": True,
            "content_sha_verification": "AFTER_PARENT_RESERVATION",
        },
        "adapter": {
            "schema": "ds02.stage2.f2-v50-descriptor-to-evaluator-v4-adapter.v1",
            "descriptor_schema": descriptor_value["schema"],
            "relocated_v15_request_used": True,
            "old_template_reuse": "FORBIDDEN",
            "result_content_read_during_build": False,
            "runtime_code_content_verification": "AFTER_PARENT_RESERVATION",
        },
        "score_contract": {
            "source_and_identity_errors": "BINDING_ERROR",
            "wrong_prediction_values": "SCIENTIFIC_SCORE_FAIL",
            "thresholds": "frozen observer_profile only; caller overrides forbidden",
            "time_and_output_budget_basis": "scientific-error fractions; runtime/bytes diagnostic only",
        },
        "limitations": [
            "This adapter reads only small JSON/code stat metadata and does not read the V16 result content.",
            "The evaluator parent must rehash all input_files after reservation and then invoke evaluator-v4.",
            "The relocated V15 request supplies the observer/profile contract; no stale ROOT060 template is used.",
            "For V50, the immutable terminal seal plus the separately supplied fresh proof are transformed in memory; the seal is not rewritten.",
            "QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    out = _write_new(output, request)
    return {"schema": REQUEST_SCHEMA, "status": request["status"], "request": str(out),
            "request_sha256": request["sha256"], "result_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    descriptor_group = parser.add_mutually_exclusive_group(required=True)
    descriptor_group.add_argument("--descriptor", type=Path)
    descriptor_group.add_argument("--v50-seal", type=Path)
    parser.add_argument("--fresh-proof", type=Path)
    parser.add_argument("--fresh-v10-request", type=Path, required=True)
    parser.add_argument("--terminal-manifest", type=Path, required=True)
    parser.add_argument("--runtime-closure", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.v50_seal is not None and args.fresh_proof is None:
            parser.error("--fresh-proof is required with --v50-seal")
        result = build_request(descriptor=args.descriptor, v50_seal=args.v50_seal,
                               fresh_proof=args.fresh_proof, fresh_v10_request=args.fresh_v10_request,
                               terminal_manifest=args.terminal_manifest,
                               runtime_closure=args.runtime_closure, output=args.output)
    except (EvaluatorAdapterError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"f2 evaluator-v4 adapter: {error}", file=__import__("sys").stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
