#!/usr/bin/env python3
"""Seal one completed V47 producer and prepare fresh V10/evaluator inputs.

This is the producer-side boundary between the V47 native replay and the
JSON-only V10 semantic consumer.  It intentionally consumes only bounded
metadata:

* the already source-bound V47 executor/parent/root verification JSON;
* a producer terminal manifest and a new source-contract JSON; and
* producer-attested path, SHA, byte count and stat records for products.

It never opens or hashes a typed HDF5 file, BI4 file, raw frame, or V16
result.  A product's declared content SHA is evidence from the guarded
producer.  The V10 consumer is the component that must rehash and parse the
new V16 JSON after its own parent reservation.  The builder therefore cannot
grant scientific qualification and leaves QI/QN/QE UNKNOWN.

The actionable CURRENT identity is the exact CURRENT336 source SHA (df7e...)
kept in provenance.  A fresh relocated runtime view has a different digest
and is the value used by the source binding.  Historical ROOT060/aabfb
products are rejected as inputs, even when their shape happens to match.

There are two additive entry points:

``seal-terminal``
    verifies the completed producer metadata and writes a fresh V8/V10
    request plus a small producer adapter/seal record.

``build-evaluator``
    consumes the new V10 proof (after V10 has actually run) and writes a new
    no-model evaluator request.  It does not execute the evaluator.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V47_INTERFACE = SCRIPT.parent / "ds_data02_stage2_f2_v47_fresh_product_interface_v1.py"
V8_CONSUMER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V10_CONSUMER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"
V11_CONSUMER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v11.py"

EXECUTOR_SCHEMA = "ds02.stage2.f2-portable-executor-request.v34"
PARENT_SCHEMA = "ds02.stage2.f2-portable-executor-parent-request.v3"
VERIFICATION_SCHEMA = "ds02.stage2.root-v47-metadata-verification.v1"
MANIFEST_SCHEMA = "ds02.stage2.f2-v47-producer-terminal-manifest.v1"
CONTRACT_SCHEMAS = {
    "ds02.stage2.f2-v47-fresh-v16-source-contract.v1",
    "ds02.stage2.f2-fresh-v16-source-contract.v40",
}
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
V10_REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
V10_PROOF_SCHEMA = "ds02.stage2.f2-fresh-v16-proof.v8"
EVALUATOR_REQUEST_SCHEMA = "ds02.stage2.f2-v47-fresh-no-model-evaluator-request.v1"
SEAL_SCHEMA = "ds02.stage2.f2-v47-producer-terminal-seal.v1"
ADAPTER_SCHEMA = PRODUCER_SCHEMA
BUILDER_SCHEMA = "ds02.stage2.f2-v47-terminal-sealer-v1"

UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 8 * 1024 * 1024
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
RAW_TREE_SHA = "08b0f5bef680bffc6bd0af05c81444340da6877eff403e318008994a56e4d0cd"
RAW_TREE_FILES = 405
RAW_TREE_FRAMES = 401
EXPECTED_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
EXPECTED_COUNT = 21114
EXPECTED_DENOMINATOR = 21.114001002861187
EXPECTED_LATER_MISSING = 0.003000000142492354
MISSING_SCOPE = "initial_fluid_source_cohort_global; identity fate unknown"
MISSING_SEMANTICS = (
    "initial denominator is already the frozen fluid mass; later missing mass "
    "remains in the unknown bucket and is never added"
)
STATUS_VOCABULARY = [
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
]
REQUIRED_TYPED_FIELDS = [
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "mass", "initial_type", "initial_mk", "initial_mass",
]


class SealerError(RuntimeError):
    """Raised for an unsafe or incomplete producer metadata hand-off."""


def canonical_sha(value: Any) -> str:
    """Canonical SHA used by stage2 JSON contracts."""
    if isinstance(value, Mapping):
        value = {
            key: item for key, item in value.items()
            if key not in {"sha256", "report_sha256", "canonical_sha256"}
        }
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    """Hash a bounded metadata file, never a producer payload artifact."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise SealerError(f"{role} must be a lowercase SHA-256")
    return value


def _finite(value: Any, role: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise SealerError(f"{role} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise SealerError(f"{role} must be finite")
    return result


def _unknown(value: Any, role: str) -> None:
    if value != UNKNOWN:
        raise SealerError(f"{role} must retain QI/QN/QE UNKNOWN")


def _file(value: Any, role: str, *, max_bytes: int | None = None) -> Path:
    if not isinstance(value, (str, Path)) or not str(value).startswith("/"):
        raise SealerError(f"{role} must be an absolute path")
    path = Path(value).expanduser()
    if path.is_symlink() or not path.is_file():
        raise SealerError(f"{role} must be a regular non-symlink file: {path}")
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise SealerError(f"{role} exceeds the metadata-only bound")
    return path


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role, max_bytes=MAX_METADATA_BYTES)
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SealerError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise SealerError(f"{role} must contain a JSON object")
    return target, value


def _stat(path: Path, role: str) -> dict[str, int]:
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise SealerError(f"{role} is not a regular non-symlink file")
    return {
        "bytes": int(info.st_size),
        "mtime_ns": int(info.st_mtime_ns),
        "mode_bits": int(stat.S_IMODE(info.st_mode)),
    }


def _under(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser()
    if target.exists() or target.is_symlink():
        raise SealerError(f"refusing to overwrite existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def _historical_path(path: str) -> bool:
    lowered = path.lower()
    return any(token in lowered for token in (
        "root060", "root-060", "root_060", "typed-only-fresh-v16-proof-v8-root-060",
        "f2-s1-native-raw-portable-overlay-v38", HISTORICAL_OVERLAY_SHA,
    ))


def _module_v47() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_v47_interface_for_sealer", V47_INTERFACE)
    if spec is None or spec.loader is None:
        raise SealerError(f"cannot load V47 interface: {V47_INTERFACE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _v47_inputs(executor_path: Path, parent_path: Path, verification_path: Path) -> dict[str, Any]:
    """Re-run the source-bound V47 metadata checks without payload access."""
    v47 = _module_v47()
    _ep, executor = _json(executor_path, "V47 executor request")
    _pp, parent = _json(parent_path, "V47 parent request")
    _vp, verification = _json(verification_path, "V47 root metadata verification")
    executor_summary = v47._verify_executor(executor_path, executor)
    parent_summary = v47._verify_parent(parent_path, parent, executor_path, executor_summary["binding"])
    roots = executor_summary["fresh_roots"]
    verification_summary = v47._verify_root_metadata(
        verification_path, verification, executor_path=executor_path,
        parent_path=parent_path, executor_binding=executor_summary,
        parent_binding=parent_summary, roots=roots)
    return {
        "executor": executor_summary,
        "parent": parent_summary,
        "verification": verification_summary,
        "roots": {"target_root": Path(roots["target_root"]), "output_root": Path(roots["output_root"])},
    }


def _request_ref(path: Path, value: Mapping[str, Any], role: str) -> dict[str, Any]:
    physical = sha256_file(path)
    canonical = _sha(value.get("sha256"), f"{role}.canonical_sha256")
    if canonical != canonical_sha(value):
        raise SealerError(f"{role} canonical SHA differs")
    info = _stat(path, role)
    return {
        "path": str(path),
        "physical_sha256": physical,
        "canonical_sha256": canonical,
        **info,
        "content_read_during_sealer": True,
    }


def _declared_stat(value: Mapping[str, Any], role: str) -> dict[str, int]:
    raw = value.get("stat")
    if isinstance(raw, Mapping):
        source = raw
    else:
        source = value
    result: dict[str, int] = {}
    for key in ("bytes", "mtime_ns", "mode_bits"):
        if isinstance(source.get(key), bool) or not isinstance(source.get(key), int):
            raise SealerError(f"{role}.{key} must be an integer stat")
        result[key] = int(source[key])
    if result["bytes"] <= 0:
        raise SealerError(f"{role}.bytes must be positive")
    return result


def _product_binding(value: Any, role: str, *, output_root: Path,
                     namespace_root: Path) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise SealerError(f"terminal manifest artifact {role} is missing")
    raw_path = value.get("path")
    if not isinstance(raw_path, str) or not raw_path.startswith("/"):
        raise SealerError(f"{role}.path must be absolute")
    if _historical_path(raw_path):
        raise SealerError(f"{role} points to a historical ROOT060/old overlay path")
    path = Path(raw_path).expanduser()
    if not _under(path, output_root) and not _under(path, namespace_root):
        raise SealerError(f"{role} is outside the fresh V47 namespace")
    actual = _stat(path, role)
    declared = _declared_stat(value, role)
    if actual != declared:
        raise SealerError(f"{role} stat differs from the producer terminal manifest")
    sha = _sha(value.get("sha256"), f"{role}.sha256")
    if value.get("content_sha_verified") is not True:
        raise SealerError(f"{role} lacks producer content SHA verification")
    phase = str(value.get("verification_phase", ""))
    if "AFTER_PARENT_RESERVATION" not in phase and "AFTER_PRODUCER_TERMINAL" not in phase:
        raise SealerError(f"{role} SHA was not verified after the parent reservation")
    if not isinstance(value.get("verified_by"), str) or not value["verified_by"].strip():
        raise SealerError(f"{role}.verified_by is missing")
    return {
        "role": role,
        "path": str(path),
        "sha256": sha,
        "bytes": actual["bytes"],
        "stat": actual,
        "content_sha_verified_by_producer": True,
        "content_sha_reverified_by_v10_after_parent_reservation": False,
        "verification_phase": phase,
    }


def _source_file_digest(value: Any, role: str) -> str:
    if isinstance(value, str):
        return _sha(value, role)
    if isinstance(value, Mapping):
        return _sha(value.get("sha256"), role)
    raise SealerError(f"{role} must be a SHA-256 or digest mapping")


def _validate_source_contract(path: Path, contract: Mapping[str, Any], *, relocated_sha: str,
                              manifest: Mapping[str, Any]) -> dict[str, Any]:
    if contract.get("schema") not in CONTRACT_SCHEMAS:
        raise SealerError("new source contract schema is not supported")
    if contract.get("sha256") != canonical_sha(contract):
        raise SealerError("source contract canonical SHA differs")
    expected = contract.get("expected")
    if not isinstance(expected, Mapping):
        raise SealerError("source contract expected binding is missing")
    source = expected.get("source_binding")
    if not isinstance(source, Mapping):
        raise SealerError("source contract source_binding is missing")
    if source.get("current_catalog_sha256") != relocated_sha:
        raise SealerError("source contract current catalog is not the new relocated view")
    if source.get("binding_status") != "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND":
        raise SealerError("source contract is not marked relocated-runtime source-bound")
    source_files = source.get("source_files")
    if not isinstance(source_files, Mapping):
        raise SealerError("source contract source_files is missing")
    if _source_file_digest(source_files.get("current_catalog"), "source_files.current_catalog") != relocated_sha:
        raise SealerError("source contract source_files.current_catalog differs")
    provenance = contract.get("current_catalog_provenance")
    if not isinstance(provenance, Mapping):
        raise SealerError("source contract current_catalog_provenance is missing")
    actual = provenance.get("actual_current_catalog")
    view = provenance.get("relocated_runtime_view")
    if not isinstance(actual, Mapping) or actual.get("sha256") != ACTUAL_CURRENT_SHA:
        raise SealerError("source contract exact CURRENT provenance is not df7e")
    if not isinstance(view, Mapping) or view.get("sha256") != relocated_sha:
        raise SealerError("source contract relocated view provenance differs")
    _unknown(contract.get("quality"), "source contract quality")

    cohort = expected.get("cohort")
    if not isinstance(cohort, Mapping) or cohort.get("selected_count") != EXPECTED_COUNT:
        raise SealerError("source contract cohort count differs from frozen F2-S1 cohort")
    if cohort.get("identity_key") != "(Zone,Idp)" or cohort.get("identity_sha256") != EXPECTED_IDENTITY_SHA:
        raise SealerError("source contract cohort identity differs")
    mass = expected.get("initial_mass_denominator")
    if not isinstance(mass, Mapping):
        raise SealerError("source contract initial mass denominator is missing")
    if abs(_finite(mass.get("denominator_kg"), "denominator_kg") - EXPECTED_DENOMINATOR) > 1e-14:
        raise SealerError("source contract frozen mass denominator differs")
    if abs(_finite(mass.get("initial_missing_mass_kg"), "initial_missing_mass_kg")) > 1e-14:
        raise SealerError("source contract initial missing mass differs")
    if abs(_finite(mass.get("later_missing_mass_kg"), "later_missing_mass_kg") - EXPECTED_LATER_MISSING) > 1e-14:
        raise SealerError("source contract later missing mass differs")
    if mass.get("initially_absent_count") != 0 or mass.get("later_missing_unique_count") != 3:
        raise SealerError("source contract missing counts differ")
    if "not augmented by later missing" not in str(mass.get("derivation", "")):
        raise SealerError("source contract does not freeze later-missing denominator semantics")
    events = expected.get("events")
    if not isinstance(events, Mapping):
        raise SealerError("source contract events are missing")
    if set(events.get("status_vocabulary", [])) != set(STATUS_VOCABULARY):
        raise SealerError("source contract first-passage vocabulary differs")
    for key in ("require_unknown_recross", "require_total_net_interval", "require_receiver_labels"):
        if events.get(key) is not True:
            raise SealerError(f"source contract events.{key} is not explicit")
    if not isinstance(expected.get("observer_fields"), list) or not expected["observer_fields"]:
        raise SealerError("source contract observer fields are missing")
    time = expected.get("time")
    if not isinstance(time, Mapping) or time.get("frame_count") != RAW_TREE_FRAMES:
        raise SealerError("source contract does not bind all 401 saved frames")

    declared_contract = manifest.get("source_contract")
    if not isinstance(declared_contract, Mapping):
        raise SealerError("terminal manifest source_contract binding is missing")
    if declared_contract.get("path") != str(path) or declared_contract.get("sha256") != sha256_file(path):
        raise SealerError("terminal manifest source contract binding differs")
    return {
        "path": str(path),
        "sha256": contract["sha256"],
        "schema": contract["schema"],
        "expected": copy.deepcopy(expected),
        "current_catalog_provenance": copy.deepcopy(provenance),
        "original_roots": list(contract.get("original_roots", [])),
    }


def _validate_manifest(path: Path, manifest: Mapping[str, Any], *, executor_path: Path,
                      parent_path: Path, verification_path: Path,
                      v47: Mapping[str, Any]) -> dict[str, Any]:
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise SealerError("terminal producer manifest schema differs")
    if manifest.get("sha256") != canonical_sha(manifest):
        raise SealerError("terminal producer manifest canonical SHA differs")
    if manifest.get("status") not in {"COMPLETE_V47_PRODUCER_DEVELOPMENT_UNKNOWN", "COMPLETED_DEVELOPMENT_UNKNOWN"}:
        raise SealerError("terminal producer manifest is not complete")
    _unknown(manifest.get("qualification"), "terminal producer qualification")
    terminal = manifest.get("terminal")
    if not isinstance(terminal, Mapping):
        raise SealerError("terminal producer manifest terminal section is missing")
    required_true = (
        "parent_guard_completed", "reservation_closed", "charge_closed", "ledger_mutated",
        "payload_read_after_reservation", "model_invoked", "cfd_invoked",
    )
    for key in required_true[:4]:
        if terminal.get(key) is not True:
            raise SealerError(f"terminal.{key} is not true")
    if terminal.get("payload_read_after_reservation") is not True:
        raise SealerError("terminal payload-read phase is not parent-guarded")
    if terminal.get("model_invoked") is not False or terminal.get("cfd_invoked") is not False:
        raise SealerError("terminal producer model/CFD boundary is not closed")
    bindings = manifest.get("request_bindings")
    if not isinstance(bindings, Mapping):
        raise SealerError("terminal request_bindings are missing")
    expected_requests = {
        "executor": executor_path, "parent": parent_path, "root_metadata_verification": verification_path,
    }
    request_summaries: dict[str, Any] = {}
    for role, expected_path in expected_requests.items():
        row = bindings.get(role)
        if not isinstance(row, Mapping) or row.get("path") != str(expected_path):
            raise SealerError(f"terminal request binding {role} differs")
        request_summaries[role] = {
            "path": str(expected_path),
            "physical_sha256": sha256_file(expected_path),
            "declared_physical_sha256": _sha(row.get("physical_sha256"), f"{role}.physical_sha256"),
        }
        if request_summaries[role]["declared_physical_sha256"] != request_summaries[role]["physical_sha256"]:
            raise SealerError(f"terminal request binding {role} SHA differs")
    identity = manifest.get("source_identity")
    if not isinstance(identity, Mapping):
        raise SealerError("terminal source_identity is missing")
    if identity.get("actual_current_catalog_sha256") != ACTUAL_CURRENT_SHA:
        raise SealerError("terminal exact CURRENT identity differs from df7e")
    relocated_sha = _sha(identity.get("relocated_runtime_view_sha256"), "relocated runtime view SHA")
    if relocated_sha in {ACTUAL_CURRENT_SHA, HISTORICAL_OVERLAY_SHA}:
        raise SealerError("terminal relocated view is stale or equal to the original CURRENT")
    if identity.get("raw_tree_sha256") != RAW_TREE_SHA or identity.get("raw_tree_file_count") != RAW_TREE_FILES or identity.get("raw_tree_frame_count") != RAW_TREE_FRAMES:
        raise SealerError("terminal raw tree identity differs from frozen 405-file/401-frame source")
    roots = v47["roots"]
    namespace_root = roots["output_root"].parent
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, Mapping):
        raise SealerError("terminal artifacts are missing")
    required_roles = {
        "worker_report", "raw_converter_report", "typed_hdf5", "v15_result", "v16_result",
        "current_runtime_view", "relocated_v15_request", "engine_report", "source_contract",
    }
    if not required_roles.issubset(artifacts):
        raise SealerError(f"terminal artifacts miss {sorted(required_roles.difference(artifacts))}")
    output_root = roots["output_root"]
    artifact_bindings = {
        role: _product_binding(artifacts[role], role, output_root=output_root, namespace_root=namespace_root)
        for role in sorted(required_roles)
    }
    source_contract = artifact_bindings["source_contract"]
    return {
        "path": str(path), "sha256": sha256_file(path), "status": manifest["status"],
        "request_bindings": request_summaries, "source_identity": {
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated_sha,
            "raw_tree_sha256": RAW_TREE_SHA,
            "raw_tree_file_count": RAW_TREE_FILES,
            "raw_tree_frame_count": RAW_TREE_FRAMES,
        },
        "terminal": dict(terminal), "artifacts": artifact_bindings,
        "source_contract_binding": source_contract,
        "namespace_root": namespace_root, "output_root": output_root,
        "parent_attempt_id": manifest.get("parent_attempt_id"),
        "charge_id": manifest.get("charge_id"),
    }


def _binding_for_result(row: Mapping[str, Any], role: str) -> dict[str, Any]:
    """Convert a producer-attested artifact to V8's result binding."""
    return {
        "path": row["path"], "sha256": row["sha256"], "bytes": row["bytes"],
        "stat": dict(row["stat"]), "content_sha_verified": False,
        "content_sha_verified_by_producer": True,
        "content_verification_phase": "PARENT_AFTER_RESERVATION",
        "artifact_role": role,
    }


def _make_adapter(*, manifest: Mapping[str, Any], contract: Mapping[str, Any],
                  contract_path: Path, v47: Mapping[str, Any], output: Path) -> tuple[Path, dict[str, Any]]:
    a = manifest["artifacts"]
    adapter: dict[str, Any] = {
        "schema": ADAPTER_SCHEMA,
        "status": "COMPLETE_TYPED_ONLY_LABELS_DEVELOPMENT_UNKNOWN",
        "sha256_scope": "canonical_sha256_excludes_top_level_sha256",
        "model_invoked": False, "cfd_invoked": False, "qualification": dict(UNKNOWN),
        "typed_input": {
            **_binding_for_result(a["typed_hdf5"], "typed_hdf5"),
            "path": a["typed_hdf5"]["path"],
            "content_sha256_phase": "PRODUCER_PARENT_AFTER_RESERVATION",
        },
        "typed_validation": {
            "frames": RAW_TREE_FRAMES,
            "selected_particles": EXPECTED_COUNT,
            "identity_sha256": EXPECTED_IDENTITY_SHA,
            "typed_fields_validated": list(REQUIRED_TYPED_FIELDS),
            "raw_tree_sha256": RAW_TREE_SHA,
        },
        "labels": {
            "v15": _binding_for_result(a["v15_result"], "v15_result"),
            "v16": _binding_for_result(a["v16_result"], "v16_result"),
        },
        # V9 derives the only two permitted producer provenance paths from
        # these historical field names.  They are declarations only: the
        # relocated V10/V11 consumer never opens them as fallback inputs.
        "v37_provenance": {
            "converter_report": {
                "path": a["raw_converter_report"]["path"],
                "sha256": a["raw_converter_report"]["sha256"],
            },
        },
        "source_binding": {
            "binding_status": "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND",
            "current_catalog_sha256": manifest["source_identity"]["relocated_runtime_view_sha256"],
            "source_files": {"current_catalog": manifest["source_identity"]["relocated_runtime_view_sha256"]},
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "trajectory_h5_producer_sha256": contract["expected"]["source_binding"].get("trajectory_h5_producer_sha256"),
        },
        "v47_provenance": {
            "executor_request": dict(v47["executor"]["binding"]),
            "parent_request": dict(v47["parent"]["binding"]),
            "root_metadata_verification": dict(v47["verification"]["binding"]),
            "terminal_manifest": {"path": manifest["path"], "sha256": manifest["sha256"]},
            "source_contract": {"path": str(contract_path), "sha256": contract["sha256"]},
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": manifest["source_identity"]["relocated_runtime_view_sha256"],
            "old_root060_reuse": "FORBIDDEN",
        },
        "execution_boundary": {
            "raw_opened": True, "hdf5_opened": True, "model_invoked": False, "cfd_invoked": False,
            "parent_stage2guard_required": True,
            "v10_result_content_rehash_deferred": True,
        },
        "limitations": [
            "Producer terminal metadata is source-bound but this adapter does not read any payload artifact.",
            "V10 must rehash and parse the V16 result after its own parent reservation.",
            "The relocated CURRENT view is actionable; exact CURRENT df7e is retained as provenance identity.",
            "This product is DEVELOPMENT and QI/QN/QE remain UNKNOWN.",
        ],
    }
    adapter["sha256"] = canonical_sha(adapter)
    return _write_new(output, adapter), adapter


def _build_expected(contract: Mapping[str, Any], relocated_sha: str) -> dict[str, Any]:
    expected = copy.deepcopy(contract["expected"])
    source = expected["source_binding"]
    source["binding_status"] = "RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"
    source["current_catalog_sha256"] = relocated_sha
    files = source.get("source_files")
    if not isinstance(files, dict):
        files = dict(files or {})
        source["source_files"] = files
    files["current_catalog"] = relocated_sha
    # V8 checks every sha256-valued source field.  Preserve the exact source
    # identity as an explicit separate provenance field instead of replacing it.
    expected["source_identity_provenance"] = {
        "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
        "relocated_runtime_view_sha256": relocated_sha,
        "historical_overlay_input_policy": "FORBIDDEN; provenance only",
    }
    return expected


def _make_v10_request(*, adapter_path: Path, adapter: Mapping[str, Any], contract_path: Path,
                      contract: Mapping[str, Any], v47: Mapping[str, Any], manifest: Mapping[str, Any],
                      output: Path, max_wall_seconds: float, max_result_bytes: int) -> tuple[Path, dict[str, Any]]:
    roots = v47["roots"]
    target_root, output_root = roots["target_root"], roots["output_root"]
    if target_root == output_root:
        raise SealerError("V47 target/output roots must differ")
    relocated_sha = manifest["source_identity"]["relocated_runtime_view_sha256"]
    result = _binding_for_result(manifest["artifacts"]["v16_result"], "v16_result")
    expected = _build_expected(contract, relocated_sha)
    original_roots = [str(value) for value in contract.get("original_roots", []) if isinstance(value, str)]
    if not original_roots:
        raise SealerError("new source contract has no original roots")
    request: dict[str, Any] = {
        "schema": V10_REQUEST_SCHEMA,
        "role": "DEVELOPMENT", "status": "READY_FOR_PARENT_GUARD",
        "model_invoked": False, "cfd_invoked": False, "ledger_mutated": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "result": result,
        "producer_report": {
            "path": str(adapter_path), "sha256": sha256_file(adapter_path),
            "schema": PRODUCER_SCHEMA, "content_read": True,
        },
        "provenance_source_report": {
            "path": str(adapter_path), "sha256": sha256_file(adapter_path),
            "schema": PRODUCER_SCHEMA, "content_read_during_build": True,
        },
        "source_contract": {
            "path": str(contract_path), "sha256": contract["sha256"],
            "schema": contract["schema"], "content_read_during_build": True,
            "current_catalog_identity_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated_sha,
        },
        "relocation": {
            "target_root": str(target_root), "output_root": str(output_root),
            "original_roots": original_roots,
            "original_path_fallback": "FORBIDDEN",
        },
        "expected": expected,
        "execution": {
            "max_wall_seconds": float(max_wall_seconds), "max_result_bytes": int(max_result_bytes),
            "read_hdf5_or_bi4": False, "raw_opened": False,
            "result_content_verification": "after_parent_reservation",
            "original_path_fallback": "FORBIDDEN", "parent_guard_required": True,
            "content_hash_scope": "V16_JSON_ONLY_AFTER_PARENT_RESERVATION",
            "builder_payload_read": False,
        },
        "v8_consumer": {"path": str(V8_CONSUMER), "sha256": sha256_file(V8_CONSUMER), "schema": V10_REQUEST_SCHEMA},
        "v10_consumer": {"path": str(V10_CONSUMER), "sha256": sha256_file(V10_CONSUMER), "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v10"},
        "v11_consumer": {"path": str(V11_CONSUMER), "sha256": sha256_file(V11_CONSUMER), "schema": "fresh_v16_proof_consumer_v11"},
        "provenance_path_declarations": [
            {"path": adapter["typed_input"]["path"], "role": "typed_input.provenance"},
            {"path": adapter["v37_provenance"]["converter_report"]["path"], "role": "typed_input.converter_report"},
        ],
        "v11_forward": {
            "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v11-forward.v1",
            "v10_consumer": {"path": str(V10_CONSUMER), "sha256": sha256_file(V10_CONSUMER)},
            "consumer": {"path": str(V11_CONSUMER), "sha256": sha256_file(V11_CONSUMER)},
            "relocated_status_allowlist": ["RELOCATED_RUNTIME_CURRENT_VIEW_SOURCE_BOUND"],
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_view_sha256": relocated_sha,
            "current_catalog_provenance": {
                "original_current_catalog_sha256": ACTUAL_CURRENT_SHA,
                "relocated_view_sha256": relocated_sha,
                "exact_current_claim": "REJECTED_FOR_RELOCATED_VIEW",
            },
            "original_path_fallback": "FORBIDDEN",
            "qualification": dict(UNKNOWN),
        },
        "v47_binding": {
            "executor_request": dict(v47["executor"]["binding"]),
            "parent_request": dict(v47["parent"]["binding"]),
            "root_metadata_verification": dict(v47["verification"]["binding"]),
            "terminal_manifest": {"path": manifest["path"], "sha256": manifest["sha256"]},
            "source_contract": {"path": str(contract_path), "sha256": contract["sha256"]},
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated_sha,
            "raw_tree_sha256": RAW_TREE_SHA, "raw_tree_file_count": RAW_TREE_FILES, "raw_tree_frame_count": RAW_TREE_FRAMES,
            "old_root060_result_or_proof_reuse": "FORBIDDEN",
        },
        "v10_mass_scope_contract": {
            "accepted_result_missing_scope": MISSING_SCOPE,
            "semantics": MISSING_SEMANTICS,
            "source_report": {"path": str(adapter_path), "sha256": sha256_file(adapter_path), "schema": PRODUCER_SCHEMA},
            "later_missing_is_not_added_to_initial_denominator": True,
            "source_bound_only": True,
        },
        "fresh_result_binding": {
            "path": result["path"], "sha256": result["sha256"], "bytes": result["bytes"],
            "content_sha_verified_by_producer": True,
            "content_sha_reverified_by_v10_after_parent_reservation": False,
            "old_result_reuse": "FORBIDDEN",
        },
        "parent_guard_record": None,
        "trace_audit": {"status": "PENDING_V10_PARENT_GUARD"},
        "limitations": [
            "This builder reads only terminal/source metadata and stats; it does not read/hash V16 or typed HDF5 payloads.",
            "V10 is responsible for post-reservation V16 content SHA and all event/mass/time semantic checks.",
            "Result and proof are a fresh relocated attempt; ROOT060 and the historical aabfb view are forbidden.",
            "Development-only: QI/QN/QE remain UNKNOWN.",
        ],
    }
    request["sha256"] = canonical_sha(request)
    return _write_new(output, request), request


def seal_terminal(*, v47_executor_request: Path | str, v47_parent_request: Path | str,
                  metadata_verification: Path | str, terminal_manifest: Path | str,
                  source_contract: Path | str, adapter_output: Path | str,
                  v10_request_output: Path | str, seal_output: Path | str,
                  max_wall_seconds: float = 900.0, max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    if not math.isfinite(max_wall_seconds) or max_wall_seconds <= 0:
        raise SealerError("max_wall_seconds must be finite and positive")
    if isinstance(max_result_bytes, bool) or not isinstance(max_result_bytes, int) or max_result_bytes <= 0:
        raise SealerError("max_result_bytes must be a positive integer")
    executor_path, _ = _json(v47_executor_request, "V47 executor request")
    parent_path, _ = _json(v47_parent_request, "V47 parent request")
    verification_path, _ = _json(metadata_verification, "V47 root metadata verification")
    manifest_path, manifest_value = _json(terminal_manifest, "terminal producer manifest")
    contract_path, contract_value = _json(source_contract, "fresh source contract")
    v47 = _v47_inputs(executor_path, parent_path, verification_path)
    manifest = _validate_manifest(manifest_path, manifest_value, executor_path=executor_path,
                                  parent_path=parent_path, verification_path=verification_path, v47=v47)
    contract = _validate_source_contract(contract_path, contract_value,
                                         relocated_sha=manifest["source_identity"]["relocated_runtime_view_sha256"],
                                         manifest=manifest_value)
    adapter_path, adapter = _make_adapter(manifest=manifest, contract=contract,
                                          contract_path=contract_path, v47=v47,
                                          output=Path(adapter_output).expanduser())
    request_path, request = _make_v10_request(
        adapter_path=adapter_path, adapter=adapter, contract_path=contract_path, contract=contract,
        v47=v47, manifest=manifest, output=Path(v10_request_output).expanduser(),
        max_wall_seconds=max_wall_seconds, max_result_bytes=max_result_bytes)
    seal: dict[str, Any] = {
        "schema": SEAL_SCHEMA, "status": "READY_FOR_PARENT_V10_SEMANTIC_GUARD",
        "builder": {"schema": BUILDER_SCHEMA, "path": str(SCRIPT), "sha256": sha256_file(SCRIPT)},
        "terminal_manifest": {"path": str(manifest_path), "sha256": manifest["sha256"]},
        "source_contract": {"path": str(contract_path), "sha256": contract["sha256"],
                            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
                            "relocated_runtime_view_sha256": manifest["source_identity"]["relocated_runtime_view_sha256"]},
        "producer_adapter": {"path": str(adapter_path), "sha256": sha256_file(adapter_path), "schema": PRODUCER_SCHEMA},
        "v10_request": {"path": str(request_path), "sha256": request["sha256"], "schema": V10_REQUEST_SCHEMA},
        "source_identity": dict(manifest["source_identity"]),
        "execution_boundary": {
            "payload_read_by_sealer": False, "typed_hdf5_read_by_sealer": False,
            "v16_result_read_by_sealer": False, "model_invoked": False, "cfd_invoked": False,
            "v10_content_read_deferred_until_parent_guard": True,
        },
        "fresh_v10_semantic_proof": {
            "status": "REQUIRED_AFTER_V10_RUN",
            "schema": V10_PROOF_SCHEMA, "path": None, "sha256": None,
            "old_root060_reuse": "FORBIDDEN",
        },
        "qualification": dict(UNKNOWN),
        "limitations": [
            "This seal is a guarded input descriptor, not a semantic pass by itself.",
            "Only the parent-approved V10 consumer may create the fresh semantic proof.",
            "No scientific QI/QN/QE credit is granted.",
        ],
    }
    seal["sha256"] = canonical_sha(seal)
    seal_path = _write_new(seal_output, seal)
    return {
        "schema": SEAL_SCHEMA, "status": seal["status"],
        "seal": str(seal_path), "seal_sha256": seal["sha256"],
        "producer_adapter": str(adapter_path), "producer_adapter_sha256": sha256_file(adapter_path),
        "v10_request": str(request_path), "v10_request_sha256": request["sha256"],
        "fresh_semantic_proof": "PENDING_V10_PARENT_GUARD",
        "payload_read_by_builder": False, "qualification": dict(UNKNOWN),
    }


def _load_canonical(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target, value = _json(path, role)
    if value.get("sha256") != canonical_sha(value):
        raise SealerError(f"{role} canonical SHA differs")
    return target, value


def _proof_binding(path: Path, proof: Mapping[str, Any], request: Mapping[str, Any],
                   seal: Mapping[str, Any]) -> dict[str, Any]:
    if proof.get("schema") != V10_PROOF_SCHEMA:
        raise SealerError("fresh proof schema differs")
    if proof.get("status") != "FRESH_V16_RESULT_VERIFIED_DEVELOPMENT_UNKNOWN":
        raise SealerError("fresh proof is not a completed development proof")
    _unknown(proof.get("quality"), "fresh proof quality")
    _unknown(proof.get("qualification"), "fresh proof qualification")
    source_result = proof.get("source_result")
    result = request.get("result")
    if not isinstance(source_result, Mapping) or not isinstance(result, Mapping):
        raise SealerError("fresh proof/result binding is missing")
    if source_result.get("path") != result.get("path") or source_result.get("sha256") != result.get("sha256"):
        raise SealerError("fresh proof is bound to a different V16 result")
    if source_result.get("content_sha_verified") is not True:
        raise SealerError("fresh proof does not attest V16 content SHA")
    source = proof.get("source_binding")
    expected = request.get("expected")
    if not isinstance(source, Mapping) or not isinstance(expected, Mapping):
        raise SealerError("fresh proof source binding is missing")
    expected_source = expected.get("source_binding")
    if not isinstance(expected_source, Mapping):
        raise SealerError("fresh request source binding is missing")
    if source.get("current_catalog_sha256") != expected_source.get("current_catalog_sha256"):
        raise SealerError("fresh proof relocated CURRENT digest differs")
    if source.get("current_catalog_sha256") in {ACTUAL_CURRENT_SHA, HISTORICAL_OVERLAY_SHA}:
        raise SealerError("fresh proof uses stale/current-original digest as runtime view")
    if source.get("original_current_catalog_sha256", source.get("actual_current_catalog_sha256")) != ACTUAL_CURRENT_SHA:
        raise SealerError("fresh proof exact CURRENT provenance is not df7e")
    guard = proof.get("parent_guard")
    if not isinstance(guard, Mapping) or guard.get("supplied") is not True:
        raise SealerError("fresh proof has no parent guard record")
    if "ROOT060" in str(proof) or _historical_path(str(source_result.get("path"))):
        raise SealerError("fresh proof contains a historical ROOT060 actionable binding")
    seal_ref = seal.get("v10_request")
    if not isinstance(seal_ref, Mapping) or seal_ref.get("path") != str(Path(request.get("__path__", ""))):
        # The request path is supplied explicitly by build_evaluator_request;
        # this branch is only a defensive check for malformed programmatic calls.
        pass
    return {
        "path": str(path), "sha256": sha256_file(path), "schema": proof["schema"],
        "status": proof["status"], "result": {"path": source_result["path"], "sha256": source_result["sha256"], "bytes": source_result.get("bytes")},
        "source_binding": {
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": source["current_catalog_sha256"],
        },
        "guard": dict(guard),
    }


def build_evaluator_request(*, seal_path: Path | str, v10_request_path: Path | str,
                            fresh_proof_path: Path | str, output: Path | str) -> dict[str, Any]:
    seal_file, seal = _load_canonical(seal_path, "V47 terminal seal")
    request_file, request = _load_canonical(v10_request_path, "fresh V10 request")
    proof_file, proof = _load_canonical(fresh_proof_path, "fresh V10 semantic proof")
    if seal.get("schema") != SEAL_SCHEMA or seal.get("status") != "READY_FOR_PARENT_V10_SEMANTIC_GUARD":
        raise SealerError("terminal seal is not the V47 sealer output")
    if request.get("schema") != V10_REQUEST_SCHEMA:
        raise SealerError("evaluator source must be the fresh V10 request")
    if request.get("status") != "READY_FOR_PARENT_GUARD":
        raise SealerError("fresh V10 request is not parent-guard ready")
    seal_request = seal.get("v10_request")
    if not isinstance(seal_request, Mapping) or seal_request.get("path") != str(request_file):
        raise SealerError("terminal seal does not bind the supplied V10 request")
    if seal_request.get("sha256") != request["sha256"]:
        raise SealerError("terminal seal V10 request SHA differs")
    # The proof validator deliberately reads only the small proof JSON.  It
    # never hashes the result here; V10 already recorded its content SHA.
    proof_binding = _proof_binding(proof_file, proof, {**request, "__path__": str(request_file)}, seal)
    source_contract = request.get("source_contract")
    expected = request.get("expected")
    result = request.get("result")
    if not isinstance(source_contract, Mapping) or not isinstance(expected, Mapping) or not isinstance(result, Mapping):
        raise SealerError("fresh V10 source/result contract is incomplete")
    relocated_sha = expected.get("source_binding", {}).get("current_catalog_sha256")
    if relocated_sha != proof_binding["source_binding"]["relocated_runtime_view_sha256"]:
        raise SealerError("evaluator source/proof relocated digest differs")
    if source_contract.get("current_catalog_identity_sha256") != ACTUAL_CURRENT_SHA:
        raise SealerError("evaluator source contract exact CURRENT identity differs")
    if source_contract.get("relocated_runtime_view_sha256") != relocated_sha:
        raise SealerError("evaluator source contract relocated digest differs")
    raw_report = request.get("producer_report")
    v47_binding = request.get("v47_binding")
    if not isinstance(raw_report, Mapping) or not isinstance(v47_binding, Mapping):
        raise SealerError("evaluator producer/V47 bindings are incomplete")
    for path_value in (str(proof_file), str(request_file), str(seal_file), str(raw_report.get("path"))):
        if _historical_path(path_value):
            raise SealerError("evaluator input contains a historical ROOT060/old overlay path")
    output_file = Path(output).expanduser()
    evaluator: dict[str, Any] = {
        "schema": EVALUATOR_REQUEST_SCHEMA,
        "status": "READY_FOR_PARENT_EVALUATOR_GUARD",
        "role": "DEVELOPMENT",
        "request_id": "f2-s1-v47-fresh-no-model-evaluator-v1",
        "model_invoked": False, "cfd_invoked": False,
        "quality": dict(UNKNOWN), "qualification": dict(UNKNOWN),
        "execution": {
            "run_allowed": True, "json_only_result_input": True,
            "read_hdf5_or_bi4": False, "raw_opened": False,
            "original_path_fallback": "FORBIDDEN",
            "parent_guard_required": True,
            "content_sha_verification": "AFTER_PARENT_RESERVATION",
            "fresh_proof_required": True,
            "old_root060_result_or_proof_reuse": "FORBIDDEN",
        },
        "source_identity": {
            "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA,
            "relocated_runtime_view_sha256": relocated_sha,
            "historical_overlay_input_policy": "FORBIDDEN; provenance only",
        },
        "source_contract": dict(source_contract),
        "v47_binding": dict(v47_binding),
        "fresh_v10_request": {"path": str(request_file), "sha256": request["sha256"], "schema": V10_REQUEST_SCHEMA},
        "fresh_v10_proof": proof_binding,
        "producer_report": dict(raw_report),
        "fresh_result": {
            "path": result.get("path"), "sha256": result.get("sha256"), "bytes": result.get("bytes"),
            "stat": copy.deepcopy(result.get("stat")),
            "content_sha_verified_by_v10": True,
        },
        "evaluator_inputs": {
            "typed_hdf5": "producer-attested only; not read by this builder",
            "raw_converter_report": "producer-attested report path from V47 adapter",
            "v15_result": "producer-attested only; not read by this builder",
            "v16_result": dict(result),
            "fresh_v10_proof": proof_binding,
        },
        "observer_contract": {
            "source": "fresh V10 semantic proof",
            "required_identity_axis": "(Zone,Idp)",
            "initial_mass_denominator_kg": EXPECTED_DENOMINATOR,
            "later_missing_mass_is_unknown_not_added": True,
            "event_status_vocabulary": list(STATUS_VOCABULARY),
            "scientific_qualification": dict(UNKNOWN),
        },
        "limitations": [
            "This request is a fresh model-free evaluator descriptor; it does not execute scoring.",
            "The producer result/proof was generated by a separate guarded V10 stage.",
            "No HDF5/BI4/raw payload is read or hashed while building this request.",
            "All scientific quality and qualification fields remain UNKNOWN.",
        ],
    }
    evaluator["sha256"] = canonical_sha(evaluator)
    _write_new(output_file, evaluator)
    return {
        "schema": EVALUATOR_REQUEST_SCHEMA, "status": evaluator["status"],
        "request": str(output_file), "request_sha256": evaluator["sha256"],
        "fresh_v10_proof": str(proof_file), "fresh_result_sha256": result.get("sha256"),
        "payload_read_by_builder": False, "model_invoked": False, "cfd_invoked": False,
        "qualification": dict(UNKNOWN),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    seal = sub.add_parser("seal-terminal")
    seal.add_argument("--v47-executor-request", type=Path, required=True)
    seal.add_argument("--v47-parent-request", type=Path, required=True)
    seal.add_argument("--metadata-verification", type=Path, required=True)
    seal.add_argument("--terminal-manifest", type=Path, required=True)
    seal.add_argument("--source-contract", type=Path, required=True)
    seal.add_argument("--adapter-output", type=Path, required=True)
    seal.add_argument("--v10-request-output", type=Path, required=True)
    seal.add_argument("--seal-output", type=Path, required=True)
    seal.add_argument("--max-wall-seconds", type=float, default=900.0)
    seal.add_argument("--max-result-bytes", type=int, default=100_000_000)
    evaluator = sub.add_parser("build-evaluator")
    evaluator.add_argument("--seal", type=Path, required=True)
    evaluator.add_argument("--v10-request", type=Path, required=True)
    evaluator.add_argument("--fresh-proof", type=Path, required=True)
    evaluator.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal-terminal":
            result = seal_terminal(
                v47_executor_request=args.v47_executor_request,
                v47_parent_request=args.v47_parent_request,
                metadata_verification=args.metadata_verification,
                terminal_manifest=args.terminal_manifest,
                source_contract=args.source_contract,
                adapter_output=args.adapter_output,
                v10_request_output=args.v10_request_output,
                seal_output=args.seal_output,
                max_wall_seconds=args.max_wall_seconds,
                max_result_bytes=args.max_result_bytes,
            )
        else:
            result = build_evaluator_request(
                seal_path=args.seal, v10_request_path=args.v10_request,
                fresh_proof_path=args.fresh_proof, output=args.output)
    except (SealerError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"V47 terminal sealer: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
