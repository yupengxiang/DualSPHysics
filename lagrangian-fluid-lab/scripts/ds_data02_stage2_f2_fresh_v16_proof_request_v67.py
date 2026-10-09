#!/usr/bin/env python3
"""Build ROOT194's V12 proof request from the consumed V66 metadata.

The builder is deliberately a metadata bridge.  It does not reopen the V16
result, HDF5, BI4, raw frames, or the old ROOT190 attempt.  A small sidecar is
created from the canonical V66 request and a pinned producer source file; the
sidecar then binds the exact producer spelling of ``missing_scope`` to the
frozen denominator and the V2 nested-report provenance.  The resulting V8
shaped request has a new ROOT194 case/attempt/output namespace and selects the
additive V12 consumer.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V8_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v8.py"
V12_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v12.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
SIDECAR_SCHEMA = "ds02.stage2.f2-fresh-v16-missing-scope-sidecar.v1"
FORWARD_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-v12-forward.v1"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
ACTUAL_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_COUNT = 21114
EXPECTED_IDENTITY_SHA = "bc7c25286faeb5c9bbc9f27c176671c027bbc0650b9051f9d08241b4f3397d70"
EXPECTED_DENOMINATOR = 21.114001002861187
EXPECTED_INITIAL_MISSING = 0.0
EXPECTED_LATER_MISSING = 0.003000000142492354
EXPECTED_LATER_MISSING_COUNT = 3
MISSING_SCOPE = "initial_fluid_source_cohort_global; identity fate unknown"
SCOPE_SEMANTICS = (
    "initial denominator is already the frozen fluid mass; later missing mass "
    "remains in the unknown bucket and is never added"
)
REQUIRED_TYPED_FIELDS = sorted({
    "time", "particle_id", "particle_zone", "valid", "position", "velocity",
    "mass", "initial_type", "initial_mk", "initial_mass",
})
REQUIRED_STATUS_VOCABULARY = sorted({
    "observed", "right_censored", "failed_before_observation",
    "initially_inside", "ambiguous_multiple_crossing",
})
HEX64 = set("0123456789abcdef")
MAX_JSON_BYTES = 32 * 1024 * 1024
MAX_SCOPE_SOURCE_BYTES = 4 * 1024 * 1024
MAX_NESTED_REPORT_BYTES = 4 * 1024 * 1024


class V67RequestError(RuntimeError):
    pass


def _load_v8() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_v8_for_v67", V8_SCRIPT)
    if spec is None or spec.loader is None:
        raise V67RequestError(f"cannot load V8 consumer: {V8_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V8 = _load_v8()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _sha(value: Any, role: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(ch not in HEX64 for ch in value):
        raise V67RequestError(f"{role} must be a lowercase SHA-256")
    return value


def sha256_file(path: Path | str, *, max_bytes: int | None = None) -> str:
    target = Path(path).expanduser()
    digest = hashlib.sha256()
    total = 0
    with target.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(block)
            if max_bytes is not None and total > max_bytes:
                raise V67RequestError(f"file exceeds bound: {target}")
            digest.update(block)
    return digest.hexdigest()


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, str) or not value.startswith("/"):
        raise V67RequestError(f"{role} must be an absolute path")
    target = Path(value).expanduser()
    if target.is_symlink() or not target.is_file():
        raise V67RequestError(f"{role} must be a regular non-symlink file: {target}")
    return target


def _json(path: Path | str, role: str, *, max_bytes: int = MAX_JSON_BYTES) -> tuple[Path, dict[str, Any]]:
    target = _file(str(path), role)
    if target.stat().st_size > max_bytes:
        raise V67RequestError(f"{role} exceeds metadata-only limit")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V67RequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V67RequestError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise V67RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return target


def _finite_close(value: Any, expected: float, role: str, tolerance: float = 1e-14) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or abs(float(value) - expected) > tolerance:
        raise V67RequestError(f"{role} differs from source-bound value")


def _mapping(value: Any, role: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise V67RequestError(f"{role} must be an object")
    return value


def _report_canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items()
            if key not in {"sha256", "report_sha256"}}
    return hashlib.sha256(json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def _static_bindings(value: Any) -> list[Mapping[str, Any]]:
    """Collect declared static bindings from the real producer request.

    The V66 proof request intentionally keeps the parent request as a small
    path/SHA provenance record.  Reopening that bounded parent request here
    is how V67 proves that the scope source was one of its actual static
    inputs; a file merely containing the same literal is insufficient.
    """
    found: list[Mapping[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            rows = item.get("static_bindings")
            if isinstance(rows, list):
                found.extend(row for row in rows if isinstance(row, Mapping))
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return found


def _nested_report_binding(parent_binding: Mapping[str, Any], *, parent_request: Mapping[str, Any]) -> dict[str, Any]:
    nested = _mapping(parent_binding.get("nested_worker_report"), "source V66 nested report")
    nested_path = _file(nested.get("path"), "source V66 nested report")
    declared_sha = _sha(nested.get("sha256"), "source V66 nested report SHA")
    nested_file, nested_value = _json(nested_path, "actual V2 nested report",
                                      max_bytes=MAX_NESTED_REPORT_BYTES)
    observed_sha = sha256_file(nested_file, max_bytes=MAX_NESTED_REPORT_BYTES)
    if observed_sha != declared_sha:
        raise V67RequestError("actual V2 nested report SHA differs from V66 binding")
    if nested_value.get("schema") != "ds02.stage2.f2-native-raw-to-typed-to-label-report.v2":
        raise V67RequestError("actual V2 nested report schema differs")
    report_sha = nested_value.get("report_sha256")
    if not isinstance(report_sha, str) or report_sha != _report_canonical_sha(nested_value):
        raise V67RequestError("actual V2 nested report canonical SHA differs")

    parent_request_path = _file(parent_binding.get("request", {}).get("path"),
                                "V66 producer parent request")
    parent_declared_sha = _sha(parent_binding.get("request", {}).get("file_sha256"),
                               "V66 producer parent request SHA")
    if sha256_file(parent_request_path, max_bytes=MAX_JSON_BYTES) != parent_declared_sha:
        raise V67RequestError("V66 producer parent request SHA differs")
    parent_canonical = parent_request.get("sha256")
    if not isinstance(parent_canonical, str) or parent_canonical != canonical_sha(parent_request):
        raise V67RequestError("V66 producer parent request canonical SHA differs")
    bindings = _static_bindings(parent_request)
    if not bindings:
        raise V67RequestError("V66 producer parent request has no static_bindings")
    return {
        "path": str(nested_file), "sha256": observed_sha,
        "schema": str(nested_value["schema"]),
        "report_canonical_sha256": report_sha,
        "parent_request": {"path": str(parent_request_path),
                            "file_sha256": parent_declared_sha,
                            "canonical_sha256": parent_canonical},
        "static_bindings": bindings,
    }


def _validate_v66_source(path: Path, source: Mapping[str, Any]) -> dict[str, Any]:
    if source.get("schema") != REQUEST_SCHEMA or source.get("sha256") != canonical_sha(source):
        raise V67RequestError("source request is not a canonical V8 request")
    if source.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise V67RequestError("source V66 request is not parent-ready")
    if source.get("model_invoked") is not False or source.get("cfd_invoked") is not False:
        raise V67RequestError("source request model/CFD boundary is not closed")
    if source.get("quality", source.get("qualification")) != UNKNOWN:
        raise V67RequestError("source request may not promote QI/QN/QE")
    parent = _mapping(source.get("v66_parent_binding"), "source.v66_parent_binding")
    producer_case = parent.get("producer_case_id")
    producer_attempt = parent.get("producer_attempt_id")
    if not isinstance(producer_case, str) or not isinstance(producer_attempt, str):
        raise V67RequestError("source V66 producer identity is missing")
    if any(token in (producer_case + producer_attempt).lower() for token in ("root060", "oldproof", "old-proof")):
        raise V67RequestError("historical proof identity cannot seed ROOT194")
    producer_request = _mapping(parent.get("request"), "source.v66_parent_binding.request")
    _sha(producer_request.get("file_sha256"), "source producer request file SHA")
    _sha(producer_request.get("canonical_sha256"), "source producer request canonical SHA")
    # The V66 proof request has only path/SHA for this provenance edge.  Read
    # the bounded actual report and its bounded parent request to recover the
    # schema and the real static source edge; do not trust a missing schema
    # field or an arbitrary source file containing the same literal.
    producer_parent_request_path = _file(
        _mapping(parent.get("request"), "source V66 parent request").get("path"),
        "source V66 parent request")
    _, producer_parent_request = _json(producer_parent_request_path,
                                       "source V66 parent request")
    nested = _nested_report_binding(parent, parent_request=producer_parent_request)
    result = _mapping(source.get("result"), "source V66 result")
    _sha(result.get("sha256"), "source V66 result SHA")
    if isinstance(result.get("bytes"), bool) or not isinstance(result.get("bytes"), int) or result.get("bytes") <= 0:
        raise V67RequestError("source V66 result bytes are invalid")
    current = _mapping(source.get("current_manifest_binding"), "source V66 CURRENT binding")
    if current.get("sha256") != ACTUAL_CURRENT_SHA:
        raise V67RequestError("source V66 CURRENT is not exact df7e")
    expected = _mapping(source.get("expected"), "source V66 expected")
    cohort = _mapping(expected.get("cohort"), "source expected cohort")
    if cohort.get("selected_count") != EXPECTED_COUNT or cohort.get("identity_key") != "(Zone,Idp)" or cohort.get("identity_sha256") != EXPECTED_IDENTITY_SHA:
        raise V67RequestError("source V66 cohort is not the exact 21114 cohort")
    mass = _mapping(expected.get("initial_mass_denominator"), "source expected mass")
    _finite_close(mass.get("denominator_kg"), EXPECTED_DENOMINATOR, "source denominator")
    _finite_close(mass.get("initial_missing_mass_kg"), EXPECTED_INITIAL_MISSING, "source initial missing")
    _finite_close(mass.get("later_missing_mass_kg"), EXPECTED_LATER_MISSING, "source later missing")
    if mass.get("later_missing_unique_count") != EXPECTED_LATER_MISSING_COUNT:
        raise V67RequestError("source later-missing identity count differs")
    return {
        "source_request_path": str(path),
        "source_request_file_sha256": sha256_file(path),
        "source_request_canonical_sha256": source["sha256"],
        "producer_case_id": producer_case,
        "producer_attempt_id": producer_attempt,
        "producer_nested_report": {
            key: nested[key] for key in
            ("path", "sha256", "schema", "report_canonical_sha256", "parent_request")
        },
        "producer_static_bindings": nested["static_bindings"],
        "result": dict(result),
        "current": dict(current),
        "expected": dict(expected),
    }


def build_semantic_sidecar(*, source_request: Path, scope_source: Path, output: Path) -> dict[str, Any]:
    source_path, source = _json(source_request, "V66 source request")
    source_binding = _validate_v66_source(source_path, source)
    code_path = _file(str(scope_source), "scope source")
    if code_path.stat().st_size > MAX_SCOPE_SOURCE_BYTES:
        raise V67RequestError("scope source exceeds bounded code limit")
    code = code_path.read_text(encoding="utf-8")
    if MISSING_SCOPE not in code:
        raise V67RequestError("scope source does not contain the exact producer missing_scope literal")
    static_match = None
    for static_binding in source_binding["producer_static_bindings"]:
        candidate = static_binding.get("path", static_binding.get("source_path"))
        candidate_sha = static_binding.get("sha256", static_binding.get("file_sha256"))
        if candidate == str(code_path):
            static_match = (static_binding, candidate_sha)
            break
    if static_match is None:
        raise V67RequestError("scope source is not an actual V66 producer static binding")
    if static_match[1] != sha256_file(code_path, max_bytes=MAX_SCOPE_SOURCE_BYTES):
        raise V67RequestError("scope source SHA differs from the producer static binding")
    sidecar: dict[str, Any] = {
            "schema": SIDECAR_SCHEMA,
        "status": "SOURCE_BOUND_SEMANTIC_CONTRACT",
        "role": "DEVELOPMENT",
        "producer_v66_request": {
            "path": source_binding["source_request_path"],
            "file_sha256": source_binding["source_request_file_sha256"],
            "canonical_sha256": source_binding["source_request_canonical_sha256"],
            "producer_case_id": source_binding["producer_case_id"],
            "producer_attempt_id": source_binding["producer_attempt_id"],
        },
        "producer_nested_report": source_binding["producer_nested_report"],
        "v16_result": source_binding["result"],
        "current_manifest": {
            "path": source_binding["current"].get("path"),
            "sha256": ACTUAL_CURRENT_SHA,
            "identity": "EXACT_CURRENT_SOURCE_IDENTITY_DF7E",
        },
        "missing_scope": MISSING_SCOPE,
        "denominator_semantics": SCOPE_SEMANTICS,
        "scope_source": {
            "path": str(code_path),
            "sha256": sha256_file(code_path, max_bytes=MAX_SCOPE_SOURCE_BYTES),
            "missing_scope_literal": MISSING_SCOPE,
            "producer_static_role": static_match[0].get("role", static_match[0].get("name")),
            "verification": "pinned producer source contains exact V2 spelling; no result bytes read",
        },
        "expected": {
            "identity_key": "(Zone,Idp)", "selected_count": EXPECTED_COUNT,
            "identity_sha256": EXPECTED_IDENTITY_SHA,
            "denominator_kg": EXPECTED_DENOMINATOR,
            "initial_missing_mass_kg": EXPECTED_INITIAL_MISSING,
            "later_missing_mass_kg": EXPECTED_LATER_MISSING,
            "later_missing_unique_count": EXPECTED_LATER_MISSING_COUNT,
        },
        "typed_fields": list(REQUIRED_TYPED_FIELDS),
        "status_vocabulary": list(REQUIRED_STATUS_VOCABULARY),
        "qualification": dict(UNKNOWN),
        "content_read_scope": "V66 request and pinned producer source only; no V16/HDF5/BI4/raw payload",
    }
    sidecar["sha256"] = canonical_sha(sidecar)
    target = _write_new(output, sidecar)
    return {"schema": SIDECAR_SCHEMA, "status": "SOURCE_BOUND_SEMANTIC_CONTRACT",
            "path": str(target), "sha256": sha256_file(target),
            "producer_request_sha256": source_binding["source_request_file_sha256"],
            "result_sha256": source_binding["result"]["sha256"], "payload_read": False}


def _validate_sidecar_for_request(source_path: Path, source: Mapping[str, Any],
                                  sidecar_path: Path, sidecar: Mapping[str, Any]) -> dict[str, Any]:
    binding = _validate_v66_source(source_path, source)
    if sidecar.get("schema") != SIDECAR_SCHEMA or sidecar.get("sha256") != canonical_sha(sidecar):
        raise V67RequestError("semantic sidecar schema/canonical SHA differs")
    producer = _mapping(sidecar.get("producer_v66_request"), "sidecar producer request")
    if producer.get("file_sha256") != binding["source_request_file_sha256"] or producer.get("canonical_sha256") != binding["source_request_canonical_sha256"]:
        raise V67RequestError("semantic sidecar is bound to a different V66 request")
    if producer.get("producer_case_id") != binding["producer_case_id"] or producer.get("producer_attempt_id") != binding["producer_attempt_id"]:
        raise V67RequestError("semantic sidecar producer identity differs")
    nested = _mapping(sidecar.get("producer_nested_report"), "sidecar nested report")
    if nested.get("path") != binding["producer_nested_report"].get("path") or nested.get("sha256") != binding["producer_nested_report"].get("sha256"):
        raise V67RequestError("semantic sidecar nested report differs from V66")
    if nested.get("schema") != binding["producer_nested_report"].get("schema") or nested.get("report_canonical_sha256") != binding["producer_nested_report"].get("report_canonical_sha256"):
        raise V67RequestError("semantic sidecar nested report schema/canonical SHA differs")
    scope = _mapping(sidecar.get("scope_source"), "sidecar scope source")
    scope_path = scope.get("path")
    scope_sha = scope.get("sha256")
    if not isinstance(scope_path, str) or not isinstance(scope_sha, str):
        raise V67RequestError("sidecar scope source path/SHA is missing")
    if not any(item.get("path", item.get("source_path")) == scope_path and
               item.get("sha256", item.get("file_sha256")) == scope_sha
               for item in binding["producer_static_bindings"]):
        raise V67RequestError("sidecar scope source is not an actual V66 static binding")
    if scope.get("missing_scope_literal") != MISSING_SCOPE:
        raise V67RequestError("sidecar scope source literal differs")
    if sidecar.get("missing_scope") != MISSING_SCOPE or sidecar.get("denominator_semantics") != SCOPE_SEMANTICS:
        raise V67RequestError("semantic sidecar denominator contract differs")
    result = _mapping(sidecar.get("v16_result"), "sidecar V16 result")
    if result.get("path") != binding["result"].get("path") or result.get("sha256") != binding["result"].get("sha256") or result.get("bytes") != binding["result"].get("bytes"):
        raise V67RequestError("semantic sidecar V16 result differs from V66")
    current = _mapping(sidecar.get("current_manifest"), "sidecar CURRENT")
    if current.get("sha256") != ACTUAL_CURRENT_SHA or current.get("path") != binding["current"].get("path"):
        raise V67RequestError("semantic sidecar CURRENT differs from V66")
    expected = _mapping(sidecar.get("expected"), "sidecar expected")
    if expected.get("selected_count") != EXPECTED_COUNT or expected.get("identity_sha256") != EXPECTED_IDENTITY_SHA:
        raise V67RequestError("semantic sidecar identity contract differs")
    _finite_close(expected.get("denominator_kg"), EXPECTED_DENOMINATOR, "sidecar denominator")
    _finite_close(expected.get("initial_missing_mass_kg"), EXPECTED_INITIAL_MISSING, "sidecar initial missing")
    _finite_close(expected.get("later_missing_mass_kg"), EXPECTED_LATER_MISSING, "sidecar later missing")
    if expected.get("later_missing_unique_count") != EXPECTED_LATER_MISSING_COUNT:
        raise V67RequestError("semantic sidecar later-missing count differs")
    return {"path": str(sidecar_path), "sha256": sha256_file(sidecar_path),
            "schema": SIDECAR_SCHEMA, "missing_scope": MISSING_SCOPE,
            "denominator_semantics": SCOPE_SEMANTICS}


def build_request(*, source_request: Path, semantic_sidecar: Path, output: Path,
                  case_id: str, attempt_id: str, fresh_output_root: Path,
                  consumer_script: Path | None = None) -> dict[str, Any]:
    source_path, source = _json(source_request, "V66 source request")
    binding = _validate_v66_source(source_path, source)
    sidecar_path, sidecar = _json(semantic_sidecar, "semantic sidecar")
    sidecar_meta = _validate_sidecar_for_request(source_path, source, sidecar_path, sidecar)
    if not isinstance(case_id, str) or not case_id.strip() or not isinstance(attempt_id, str) or not attempt_id.strip():
        raise V67RequestError("ROOT194 case_id and attempt_id are required")
    if any(token in (case_id + attempt_id).lower() for token in ("root060", "root190", "oldproof", "old-proof")):
        raise V67RequestError("ROOT194 identity cannot reuse historical/root190 proof identity")
    fresh_root = Path(fresh_output_root).expanduser().resolve()
    if fresh_root.exists():
        raise V67RequestError(f"ROOT194 output namespace already exists: {fresh_root}")
    result_path = Path(str(binding["result"]["path"])).expanduser().resolve()
    relocation = copy.deepcopy(source.get("relocation", {}))
    target_root = Path(str(relocation.get("target_root", ""))).expanduser().resolve()
    producer_output = Path(str(relocation.get("output_root", ""))).expanduser().resolve()
    if not target_root.is_absolute() or not producer_output.is_absolute():
        raise V67RequestError("source relocation roots are malformed")
    if fresh_root == producer_output or fresh_root == target_root:
        raise V67RequestError("ROOT194 output must be a new namespace")
    relocation["output_root"] = str(fresh_root)
    request = copy.deepcopy(source)
    request["case_id"] = case_id.strip()
    request["attempt_id"] = attempt_id.strip()
    request["relocation"] = relocation
    request["fresh_proof_namespace"] = {
        "root": str(fresh_root), "is_new": True, "content_copy_performed": False,
        "producer_result_path": str(result_path),
    }
    script = Path(consumer_script).expanduser().resolve() if consumer_script else V12_SCRIPT
    if script.is_symlink() or not script.is_file():
        raise V67RequestError(f"V12 consumer script is missing: {script}")
    request["v12_forward"] = {
        "schema": FORWARD_SCHEMA,
        "version": 12,
        "source_request": {
            "path": str(source_path), "sha256": binding["source_request_file_sha256"],
            "canonical_sha256": binding["source_request_canonical_sha256"],
            "schema": REQUEST_SCHEMA,
        },
        "semantic_sidecar": sidecar_meta,
        "consumer": {"path": str(script), "sha256": sha256_file(script),
                      "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v12"},
        "normalization": "in-memory-only-before-immutable-v8-validation",
        "original_result_missing_scope_preserved": True,
        "original_path_fallback": "FORBIDDEN",
    }
    request["status"] = "READY_FOR_PARENT_GUARD"
    request["sha256"] = canonical_sha(request)
    target = _write_new(output, request)
    return {"schema": FORWARD_SCHEMA, "status": "READY_FOR_PARENT_V12_PROOF",
            "request": str(target), "sha256": sha256_file(target),
            "request_canonical_sha256": request["sha256"],
            "consumer_sha256": sha256_file(script),
            "semantic_sidecar": sidecar_meta,
            "source_request_sha256": binding["source_request_file_sha256"],
            "result_sha256": binding["result"]["sha256"],
            "fresh_case_id": case_id, "fresh_attempt_id": attempt_id,
            "fresh_output_root": str(fresh_root), "payload_read": False,
            "qualification": dict(UNKNOWN)}


def validate_emitted_request(path: Path | str) -> dict[str, Any]:
    request_path, request = _json(path, "V67 proof request")
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise V67RequestError("emitted V67 request schema/canonical SHA differs")
    marker = _mapping(request.get("v12_forward"), "emitted v12_forward")
    sidecar_path, sidecar = _json(_mapping(marker.get("semantic_sidecar"), "emitted sidecar binding").get("path"), "emitted sidecar")
    source_path = _file(_mapping(marker.get("source_request"), "emitted source binding").get("path"), "emitted source request")
    _, source = _json(source_path, "emitted source request")
    sidecar_meta = _validate_sidecar_for_request(source_path, source, sidecar_path, sidecar)
    v8 = V8._validate_request(request, verify_result_stat=True)
    return {"schema": "ds02.stage2.f2-v67-proof-request-metadata.v1",
            "status": "V67_METADATA_VALIDATED_READY_FOR_PARENT_PROOF",
            "request": {"path": str(request_path), "sha256": sha256_file(request_path)},
            "case_id": request["case_id"], "attempt_id": request["attempt_id"],
            "result": {"path": str(v8["result_path"]), "sha256": v8["result_sha256"],
                       "bytes": v8["result_bytes"], "content_sha_verified": False},
            "semantic_sidecar": sidecar_meta, "payload_read": False,
            "hdf5_or_bi4_content_read": False, "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    side = sub.add_parser("sidecar")
    side.add_argument("--source-request", type=Path, required=True)
    side.add_argument("--scope-source", type=Path, required=True)
    side.add_argument("--output", type=Path, required=True)
    build = sub.add_parser("build")
    build.add_argument("--source-request", type=Path, required=True)
    build.add_argument("--semantic-sidecar", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--case-id", required=True)
    build.add_argument("--attempt-id", required=True)
    build.add_argument("--fresh-output-root", type=Path, required=True)
    build.add_argument("--consumer-script", type=Path)
    val = sub.add_parser("validate")
    val.add_argument("--request", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "sidecar":
            value = build_semantic_sidecar(source_request=args.source_request.absolute(),
                                           scope_source=args.scope_source.absolute(), output=args.output.absolute())
        elif args.command == "build":
            value = build_request(source_request=args.source_request.absolute(),
                                  semantic_sidecar=args.semantic_sidecar.absolute(), output=args.output.absolute(),
                                  case_id=args.case_id, attempt_id=args.attempt_id,
                                  fresh_output_root=args.fresh_output_root.absolute(),
                                  consumer_script=args.consumer_script.absolute() if args.consumer_script else None)
        else:
            value = validate_emitted_request(args.request.absolute())
    except (V67RequestError, V8.ProofConsumerError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request V67: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
