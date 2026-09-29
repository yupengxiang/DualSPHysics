#!/usr/bin/env python3
"""Build a read-only typed T1 model-case-run evidence intake.

The existing F3 current-manifest matrices and F4 Tallwall120 audits describe
planned cases, source metadata, or material sidecars.  None of them is a
single typed row that binds a model case-run to the fixed family/scope/case,
formal model/seed identity, a terminal receipt, and the exact source-reader
receipt.  This module defines that missing projection without counting a row.

Only bounded JSON metadata is read.  HDF5/checkpoint/trajectory content is
never opened, and this module has no solver, worker, GPU, queue, registry,
ledger, denominator, gate, completion, or PLAN write path.  Even a complete
synthetic candidate projection is returned as ``typed_binding_ready`` only;
Core observed/T1/credit state remains zero until an external authority admits
it.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CAMPAIGN = LAB_ROOT / (
    "campaigns/core-v1/cfd/t1-evidence/"
    "observed-model-case-run-binding-v1.json"
)
DEFAULT_REPORT = LAB_ROOT / (
    "reports/T1-OBSERVED-MODEL-CASE-RUN-EVIDENCE-BINDING-V1-2026-09-29.json"
)
DEFAULT_MARKDOWN_REPORT = DEFAULT_REPORT.with_suffix(".zh-CN.md")

SCHEMA = "core.t1.observed_model_case_run.evidence_binding.v1"
CONTRACT_SCHEMA = "core.t1.observed_model_case_run.evidence_binding_contract.v1"
CANDIDATE_SCHEMA = "core.t1.observed_model_case_run.v1"
MODEL_IDENTITY_SCHEMA = "core.t1.model_case_run_identity.v1"
READER_SCHEMA = "core.t1.source_reader_case_receipt.v1"
TERMINAL_SCHEMA = "core.t1.model_case_run_terminal_receipt.v1"

F3_MATRIX_PREFIX = "core.f3."
F4_MATRIX_SCHEMA = "core.material.f4.tallwall120.sidecar_matrix_contract.v1"
F4_AUDIT_SCHEMA = "core.f4.t1.denominator.bounded_audit.v1"
FORMAL_LAUNCH_SCHEMA = "core.formal_launch_contract.v1"
CAPACITY_SCHEMA = "core.formal_capacity_evidence.v1"
COMPLETION_SCHEMA = "core.completion.v1"

MODEL_KINDS = ("graph_raw", "graph_residual", "mlp")
SEEDS = (17, 29, 43)
F3_CASE_COUNT = 32
F4_COLLECTION_CASE_COUNT = 32
F4_EVALUATION_CASE_COUNT = 16
EXPECTED_T1_CASE_RUNS = (F3_CASE_COUNT + F4_EVALUATION_CASE_COUNT) * len(MODEL_KINDS) * len(SEEDS)
FORMAL_UPDATES = 32000
MAX_JSON_BYTES = 2 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

ZERO_CREDIT: dict[str, Any] = {
    "diagnostic_only": True,
    "formal": False,
    "formal_eligible": False,
    "T1_numerical": False,
    "T2_macro": False,
    "T2_path": False,
    "qualification": False,
    "credit": 0,
    "qualification_credit": 0,
}


class BindingError(ValueError):
    """Malformed or unsafe typed evidence is never partially admitted."""


def _fail(message: str) -> None:
    raise BindingError(f"fail-closed: {message}")


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail(f"{name} must be a lowercase SHA-256 digest")
    if len(set(value)) == 1:
        _fail(f"{name} is a placeholder digest")
    return value


def _string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        _fail(f"{name} must be a non-empty string")
    return value


def _integer(value: Any, name: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        _fail(f"{name} must be an integer >= {minimum}")
    return value


def _boolean(value: Any, name: str) -> bool:
    if type(value) is not bool:
        _fail(f"{name} must be boolean")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{name} must be an object")
    return value


def _reject_unknown(value: Mapping[str, Any], allowed: set[str], name: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        _fail(f"{name} contains unknown field(s): {', '.join(unknown)}")


def _exact(value: Mapping[str, Any], key: str, expected: Any, name: str) -> None:
    if key not in value:
        _fail(f"{name}.{key} is missing")
    actual = value[key]
    if isinstance(expected, bool) and type(actual) is not bool:
        _fail(f"{name}.{key} must be boolean")
    if type(expected) is int and type(actual) is not int:
        _fail(f"{name}.{key} must be integer")
    if actual != expected:
        _fail(f"{name}.{key} must be {expected!r}")


def _reject_constant(token: str) -> None:
    _fail(f"non-finite JSON constant is not allowed: {token}")


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail(f"duplicate JSON object key: {key}")
        result[key] = value
    return result


def _resolve_input(root: Path, value: str | Path, name: str) -> Path:
    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        _fail(f"{name} must be a non-empty path")
    path = Path(raw)
    if ".." in path.parts:
        _fail(f"{name} contains a lexical parent alias")
    if path.is_absolute():
        resolved = path
        try:
            resolved.relative_to(root)
        except ValueError:
            _fail(f"{name} must remain inside the lab root")
    else:
        resolved = root / path
    current = Path(root.anchor or os.curdir)
    for component in resolved.parts[1:] if resolved.is_absolute() else resolved.parts:
        current /= component
        try:
            info = os.lstat(current)
        except FileNotFoundError:
            break
        if stat.S_ISLNK(info.st_mode):
            _fail(f"{name} contains a symlink component: {current}")
    return resolved


def _read_json(root: Path, value: str | Path, *, name: str, max_bytes: int = MAX_JSON_BYTES) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _resolve_input(root, value, name)
    if path.suffix.lower() != ".json":
        _fail(f"{name} must be a JSON file")
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0))
    except OSError as error:
        _fail(f"{name} cannot be opened: {error}")
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            _fail(f"{name} is not a regular file")
        if before.st_size > max_bytes:
            _fail(f"{name} exceeds the bounded JSON limit")
        payload = os.read(descriptor, before.st_size + 1)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    before_signature = (before.st_dev, before.st_ino, before.st_mode, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    after_signature = (after.st_dev, after.st_ino, after.st_mode, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
    if before_signature != after_signature or len(payload) != before.st_size:
        _fail(f"{name} changed while being read")
    try:
        parsed = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        _fail(f"{name} is not strict JSON: {error}")
    if not isinstance(parsed, dict):
        _fail(f"{name} must contain a JSON object")
    return parsed, {
        "path": path.relative_to(root).as_posix(),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "opened": True,
    }


def _input_ref(meta: Mapping[str, Any], role: str) -> dict[str, Any]:
    return {"role": role, "path": meta["path"], "bytes": meta["bytes"], "sha256": meta["sha256"]}


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def _file_ref(value: Any, name: str) -> dict[str, Any]:
    record = _mapping(value, name)
    _reject_unknown(record, {"path", "sha256", "bytes"}, name)
    path = _string(record.get("path"), f"{name}.path")
    digest = _sha(record.get("sha256"), f"{name}.sha256")
    bytes_count = _integer(record.get("bytes"), f"{name}.bytes", minimum=1)
    return {"path": path, "sha256": digest, "bytes": bytes_count}


def _load_contract(root: Path, campaign: Path | str) -> tuple[dict[str, Any], dict[str, Any]]:
    contract, meta = _read_json(root, campaign, name="campaign contract")
    _exact(contract, "schema", CONTRACT_SCHEMA, "campaign")
    _reject_unknown(
        contract,
        {"schema", "contract_id", "version", "core_status", "formal_launch", "formal_capacity", "f3", "f4", "binding", "policy"},
        "campaign",
    )
    _exact(contract, "version", 1, "campaign")
    binding = _mapping(contract.get("binding"), "campaign.binding")
    _exact(binding, "candidate_schema", CANDIDATE_SCHEMA, "campaign.binding")
    _exact(binding, "model_identity_schema", MODEL_IDENTITY_SCHEMA, "campaign.binding")
    _exact(binding, "source_reader_schema", READER_SCHEMA, "campaign.binding")
    _exact(binding, "terminal_schema", TERMINAL_SCHEMA, "campaign.binding")
    _exact(binding, "formal_updates", FORMAL_UPDATES, "campaign.binding")
    return contract, meta


def _load_ref(root: Path, contract: Mapping[str, Any], key: str, role: str) -> tuple[dict[str, Any], dict[str, Any]]:
    section = _mapping(contract.get(key), f"campaign.{key}")
    path = _string(section.get("path"), f"campaign.{key}.path")
    return (*_read_json(root, path, name=role),)


def _formal_identity(launch: Mapping[str, Any]) -> tuple[tuple[str, ...], tuple[int, ...], int, list[str]]:
    _exact(launch, "schema", FORMAL_LAUNCH_SCHEMA, "formal launch")
    _exact(launch, "launch_allowed", False, "formal launch")
    _exact(launch, "formal_job_count", 0, "formal launch")
    _exact(launch, "required_formal_job_count", 9, "formal launch")
    protocol = _mapping(launch.get("protocol"), "formal launch.protocol")
    updates = _integer(protocol.get("updates"), "formal launch.protocol.updates", minimum=1)
    run_matrix = launch.get("run_matrix")
    if not isinstance(run_matrix, list) or len(run_matrix) != 9:
        _fail("formal launch run_matrix must contain exactly nine rows")
    models = tuple(sorted({ _string(_mapping(row, "formal launch.run_matrix[]").get("model"), "formal launch.run_matrix[].model") for row in run_matrix }))
    seeds = tuple(sorted({ _integer(_mapping(row, "formal launch.run_matrix[]").get("seed"), "formal launch.run_matrix[].seed", minimum=1) for row in run_matrix }))
    if models != MODEL_KINDS or seeds != SEEDS:
        _fail("formal launch model/seed identity does not match the fixed nine-run contract")
    run_ids = []
    for row in run_matrix:
        item = _mapping(row, "formal launch.run_matrix[]")
        model = _string(item.get("model"), "formal launch.run_matrix[].model")
        seed = _integer(item.get("seed"), "formal launch.run_matrix[].seed", minimum=1)
        _exact(item, "formal_job", False, "formal launch.run_matrix[]")
        _exact(item, "launch_allowed", False, "formal launch.run_matrix[]")
        run_ids.append(f"{model}-seed{seed}")
    return models, seeds, updates, sorted(run_ids)


def _f3_matrix(root: Path, path: str, model: str) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    payload, meta = _read_json(root, path, name=f"F3 {model} current-manifest matrix")
    if not str(payload.get("schema", "")).startswith(F3_MATRIX_PREFIX):
        _fail(f"F3 {model} matrix schema is not a current-manifest matrix")
    _exact(payload, "formal", False, f"F3 {model} matrix")
    if "launch_allowed" in payload:
        _exact(payload, "launch_allowed", False, f"F3 {model} matrix")
    _exact(payload, "credit", 0, f"F3 {model} matrix")
    manifest = _mapping(payload.get("manifest"), f"F3 {model} matrix.manifest")
    raw = _mapping(manifest.get("raw"), f"F3 {model} matrix.manifest.raw")
    manifest_path = _string(raw.get("path"), f"F3 {model} matrix.manifest.raw.path")
    manifest_sha = _sha(raw.get("sha256"), f"F3 {model} matrix.manifest.raw.sha256")
    scope_id = _string(manifest.get("scope_id"), f"F3 {model} matrix.manifest.scope_id")
    cases = payload.get("cases")
    if not isinstance(cases, list) or len(cases) != F3_CASE_COUNT:
        _fail(f"F3 {model} matrix must contain exactly 32 case metadata rows")
    case_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(cases):
        case = _mapping(raw_case, f"F3 {model} matrix.cases[{index}]")
        case_id = _string(case.get("case_id"), f"F3 {model} matrix.cases[{index}].case_id")
        if case_id in seen:
            _fail(f"F3 {model} matrix repeats case {case_id}")
        seen.add(case_id)
        _exact(case, "family", "F3", f"F3 {model} matrix.cases[{index}]")
        _exact(case, "scope_id", scope_id, f"F3 {model} matrix.cases[{index}]")
        source_path = _string(case.get("hdf5"), f"F3 {model} matrix.cases[{index}].hdf5")
        source_sha = _sha(case.get("hdf5_sha256", case.get("sha256")), f"F3 {model} matrix.cases[{index}].hdf5_sha256")
        case_rows.append({
            "family": "F3", "scope_id": scope_id, "case_id": case_id,
            "split": _string(case.get("split"), f"F3 {model} matrix.cases[{index}].split"),
            "manifest_path": manifest_path, "manifest_sha256": manifest_sha,
            "source_path": source_path, "source_sha256": source_sha,
        })
    coverage = _mapping(payload.get("coverage"), f"F3 {model} matrix.coverage")
    if coverage.get("cases") != F3_CASE_COUNT or coverage.get("seeds") != list(SEEDS):
        _fail(f"F3 {model} matrix coverage is not the fixed 32-case/3-seed projection")
    terminal = _mapping(payload.get("terminal_receipts"), f"F3 {model} matrix.terminal_receipts")
    _exact(terminal, "observed_count", 0, f"F3 {model} matrix.terminal_receipts")
    _exact(terminal, "required_count", F3_CASE_COUNT * len(SEEDS), f"F3 {model} matrix.terminal_receipts")
    expected = _mapping(payload.get("expected_contract"), f"F3 {model} matrix.expected_contract")
    matrix_model = expected.get("model_kind", expected.get("model"))
    _exact({"model": matrix_model}, "model", model, f"F3 {model} matrix.expected_contract")
    diagnostic_updates = _integer(expected.get("updates"), f"F3 {model} matrix.expected_contract.updates", minimum=1)
    matrix_ref = {
        "path": meta["path"], "sha256": meta["sha256"], "bytes": meta["bytes"],
        "report_id": _string(payload.get("report_id"), f"F3 {model} matrix.report_id"),
        "schema": _string(payload.get("schema"), f"F3 {model} matrix.schema"),
        "family": "F3", "scope_id": scope_id, "manifest_sha256": manifest_sha,
    }
    observation = {
        "family": "F3", "model_kind": model, "scope_id": scope_id,
        "matrix": matrix_ref, "manifest_path": manifest_path, "manifest_sha256": manifest_sha,
        "case_count": F3_CASE_COUNT, "evaluation_case_count": F3_CASE_COUNT,
        "planned_updates": diagnostic_updates, "terminal_observed": 0,
        "terminal_required": F3_CASE_COUNT * len(SEEDS),
        "status": payload.get("status"), "diagnostic_only": payload.get("diagnostic_only"),
        "source_bound": payload.get("source_bound"),
    }
    return payload, meta, case_rows, {"matrix_ref": matrix_ref, "observation": observation, "diagnostic_updates": diagnostic_updates}


def _f4_matrix(root: Path, matrix_path: str, audit_path: str) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    matrix, matrix_meta = _read_json(root, matrix_path, name="F4 current-manifest case matrix")
    audit, audit_meta = _read_json(root, audit_path, name="F4 T1 denominator audit")
    _exact(matrix, "schema", F4_MATRIX_SCHEMA, "F4 matrix")
    _exact(audit, "schema", F4_AUDIT_SCHEMA, "F4 T1 audit")
    scope = _mapping(matrix.get("scope"), "F4 matrix.scope")
    _exact(scope, "family", "F4", "F4 matrix.scope")
    scope_id = _string(scope.get("scope_id"), "F4 matrix.scope.scope_id")
    fixed = _mapping(matrix.get("fixed_matrix"), "F4 matrix.fixed_matrix")
    case_ids = fixed.get("case_ids")
    splits = _mapping(fixed.get("case_splits"), "F4 matrix.fixed_matrix.case_splits")
    if not isinstance(case_ids, list) or len(case_ids) != F4_COLLECTION_CASE_COUNT or len(set(case_ids)) != F4_COLLECTION_CASE_COUNT:
        _fail("F4 current-manifest matrix must contain exactly 32 unique case IDs")
    if set(splits) != set(case_ids):
        _fail("F4 current-manifest matrix split map does not cover the fixed 32 cases")
    audit_scope = _mapping(audit.get("scope"), "F4 T1 audit.scope")
    _exact(audit_scope, "family", "F4", "F4 T1 audit.scope")
    _exact(audit_scope, "qualified_scope_id", scope_id, "F4 T1 audit.scope")
    evaluation_ids_raw = audit_scope.get("evaluation_case_ids")
    if not isinstance(evaluation_ids_raw, list) or len(evaluation_ids_raw) != F4_EVALUATION_CASE_COUNT:
        _fail("F4 T1 audit must identify exactly 16 evaluation cases")
    prefix = scope_id + "_"
    normalized_ids = [item if str(item).startswith(prefix) else prefix + str(item) for item in evaluation_ids_raw]
    if set(normalized_ids) != {str(item) for item in case_ids if splits[item] != "train"}:
        _fail("F4 T1 audit evaluation IDs do not equal the fixed non-train case split")
    audit_result = _mapping(audit.get("audit_result"), "F4 T1 audit.audit_result")
    _exact(audit_result, "model_case_run_receipts_observed", 0, "F4 T1 audit.audit_result")
    _exact(audit_result, "formal_denominator_credit", 0, "F4 T1 audit.audit_result")
    bindings = _mapping(matrix.get("input_bindings"), "F4 matrix.input_bindings")
    collection = _mapping(bindings.get("collection_manifest"), "F4 matrix.input_bindings.collection_manifest")
    manifest_path = _string(collection.get("path"), "F4 collection manifest.path")
    manifest_sha = _sha(collection.get("sha256"), "F4 collection manifest.sha256")
    source_matrix = _mapping(matrix.get("source_binding"), "F4 matrix.source_binding").get("source_matrix")
    source_by_id: dict[str, Mapping[str, Any]] = {}
    if isinstance(source_matrix, list):
        for item in source_matrix:
            row = _mapping(item, "F4 matrix.source_binding.source_matrix[]")
            if isinstance(row.get("case_id"), str):
                source_by_id[row["case_id"]] = row
    matrix_ref = {
        "path": matrix_meta["path"], "sha256": matrix_meta["sha256"], "bytes": matrix_meta["bytes"],
        "report_id": "f4-tallwall120-material-sidecar-matrix-contract-v1",
        "schema": F4_MATRIX_SCHEMA, "family": "F4", "scope_id": scope_id,
        "manifest_sha256": manifest_sha,
    }
    rows: list[dict[str, Any]] = []
    for case_id in normalized_ids:
        source = source_by_id.get(case_id)
        if source is None:
            _fail(f"F4 source matrix is missing evaluation case {case_id}")
        rows.append({
            "family": "F4", "scope_id": scope_id, "case_id": case_id,
            "split": splits[case_id], "manifest_path": manifest_path, "manifest_sha256": manifest_sha,
            "source_path": _string(source.get("expected_source_path"), f"F4 source {case_id}.expected_source_path"),
            "source_sha256": _sha(source.get("expected_source_sha256"), f"F4 source {case_id}.expected_source_sha256"),
        })
    reader = _mapping(_mapping(matrix.get("source_binding"), "F4 matrix.source_binding").get("reader"), "F4 matrix.source_binding.reader")
    observation = {
        "family": "F4", "scope_id": scope_id, "matrix": matrix_ref,
        "manifest_path": manifest_path, "manifest_sha256": manifest_sha,
        "collection_case_count": F4_COLLECTION_CASE_COUNT, "evaluation_case_count": F4_EVALUATION_CASE_COUNT,
        "terminal_observed": 0, "terminal_required": F4_EVALUATION_CASE_COUNT * len(MODEL_KINDS) * len(SEEDS),
        "material_sidecars_observed": _mapping(matrix.get("matrix_summary"), "F4 matrix.matrix_summary").get("observed_sidecar_count"),
        "reader_manifest_sha_exact": reader.get("sha256_exact"),
        "reader_recorded_manifest_sha256": reader.get("recorded_manifest_sha256"),
        "status": matrix.get("status"),
    }
    return rows, observation, {"matrix": matrix, "meta": matrix_meta}, {"audit": audit, "meta": audit_meta}


def _expected_rows(contract: Mapping[str, Any], root: Path, models: tuple[str, ...], seeds: tuple[int, ...], updates: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    f3_section = _mapping(contract.get("f3"), "campaign.f3")
    f3_paths = f3_section.get("matrix_paths")
    if not isinstance(f3_paths, Mapping) or set(f3_paths) != set(MODEL_KINDS):
        _fail("campaign.f3.matrix_paths must cover exactly the three formal model kinds")
    rows: list[dict[str, Any]] = []
    observations: list[dict[str, Any]] = []
    seen_models: set[str] = set()
    for model in MODEL_KINDS:
        path = _string(f3_paths.get(model), f"campaign.f3.matrix_paths.{model}")
        _payload, _meta, cases, info = _f3_matrix(root, path, model)
        seen_models.add(model)
        observations.append(info["observation"])
        for case in cases:
            for seed in seeds:
                rows.append(_row(case, model, seed, info["matrix_ref"], updates))
    if seen_models != set(models):
        _fail("F3 matrix model set does not equal formal launch model set")
    f4_section = _mapping(contract.get("f4"), "campaign.f4")
    f4_paths = _mapping(f4_section, "campaign.f4")
    f4_rows, f4_observation, _f4_matrix_data, _f4_audit_data = _f4_matrix(
        root,
        _string(f4_paths.get("matrix_path"), "campaign.f4.matrix_path"),
        _string(f4_paths.get("denominator_audit_path"), "campaign.f4.denominator_audit_path"),
    )
    observations.append(f4_observation)
    for case in f4_rows:
        for model in models:
            for seed in seeds:
                rows.append(_row(case, model, seed, f4_observation["matrix"], updates))
    if len(rows) != EXPECTED_T1_CASE_RUNS:
        _fail(f"fixed typed T1 row count is {len(rows)}, expected {EXPECTED_T1_CASE_RUNS}")
    keys = [(row["family"], row["scope_id"], row["case_id"], row["model_kind"], row["seed"]) for row in rows]
    if len(keys) != len(set(keys)):
        _fail("fixed typed T1 rows contain duplicate family/scope/case/model/seed identities")
    return rows, observations, {"F3": len([row for row in rows if row["family"] == "F3"]), "F4": len([row for row in rows if row["family"] == "F4"])}


def _row(case: Mapping[str, Any], model: str, seed: int, matrix_ref: Mapping[str, Any], updates: int) -> dict[str, Any]:
    return {
        "family": case["family"], "scope_id": case["scope_id"], "case_id": case["case_id"],
        "split": case["split"], "model_kind": model, "seed": seed,
        "formal_run_id": f"{model}-seed{seed}", "formal_updates": updates,
        "matrix": dict(matrix_ref), "manifest_path": case["manifest_path"],
        "manifest_sha256": case["manifest_sha256"], "source_path": case["source_path"],
        "source_sha256": case["source_sha256"],
    }


def _validate_candidate_ref(value: Any, name: str) -> dict[str, Any]:
    return _file_ref(value, name)


def validate_candidate(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one complete typed row without reading any referenced artifact."""

    if not isinstance(candidate, Mapping):
        _fail("candidate must be an object")
    _reject_unknown(candidate, {"schema", "family", "scope_id", "case_id", "split", "model_kind", "seed", "matrix_binding", "model_binding", "source_reader", "terminal", "artifacts", "claims"}, "candidate")
    _exact(candidate, "schema", CANDIDATE_SCHEMA, "candidate")
    for key in ("family", "scope_id", "case_id", "split", "model_kind"):
        _exact(candidate, key, expected[key], "candidate")
    _exact(candidate, "seed", expected["seed"], "candidate")

    matrix = _mapping(candidate.get("matrix_binding"), "candidate.matrix_binding")
    _reject_unknown(matrix, {"path", "sha256", "bytes", "report_id", "schema", "family", "scope_id", "case_id", "manifest_sha256"}, "candidate.matrix_binding")
    for key in ("path", "sha256", "bytes"):
        _exact(matrix, key, expected["matrix"][key], "candidate.matrix_binding")
    for key in ("report_id", "schema", "family", "scope_id", "case_id", "manifest_sha256"):
        _exact(matrix, key, expected["matrix"][key] if key != "manifest_sha256" else expected["manifest_sha256"], "candidate.matrix_binding")

    model = _mapping(candidate.get("model_binding"), "candidate.model_binding")
    _reject_unknown(model, {"schema", "run_id", "model_kind", "seed", "training_updates", "training_receipt", "checkpoint"}, "candidate.model_binding")
    _exact(model, "schema", MODEL_IDENTITY_SCHEMA, "candidate.model_binding")
    _exact(model, "run_id", expected["formal_run_id"], "candidate.model_binding")
    _exact(model, "model_kind", expected["model_kind"], "candidate.model_binding")
    _exact(model, "seed", expected["seed"], "candidate.model_binding")
    _exact(model, "training_updates", expected["formal_updates"], "candidate.model_binding")
    training_ref = _validate_candidate_ref(model.get("training_receipt"), "candidate.model_binding.training_receipt")
    checkpoint_ref = _validate_candidate_ref(model.get("checkpoint"), "candidate.model_binding.checkpoint")

    reader = _mapping(candidate.get("source_reader"), "candidate.source_reader")
    _reject_unknown(reader, {"schema", "path", "sha256", "bytes", "family", "scope_id", "case_id", "manifest_path", "manifest_sha256", "source_path", "source_sha256", "status", "case_identity_verified", "source_identity_verified", "content_read"}, "candidate.source_reader")
    _exact(reader, "schema", READER_SCHEMA, "candidate.source_reader")
    for key in ("family", "scope_id", "case_id", "manifest_path", "manifest_sha256", "source_path", "source_sha256"):
        _exact(reader, key, expected[key], "candidate.source_reader")
    _exact(reader, "status", "complete", "candidate.source_reader")
    _exact(reader, "case_identity_verified", True, "candidate.source_reader")
    _exact(reader, "source_identity_verified", True, "candidate.source_reader")
    _exact(reader, "content_read", True, "candidate.source_reader")
    reader_ref = _file_ref({key: reader.get(key) for key in ("path", "sha256", "bytes")}, "candidate.source_reader")

    terminal = _mapping(candidate.get("terminal"), "candidate.terminal")
    _reject_unknown(terminal, {"schema", "path", "sha256", "bytes", "family", "scope_id", "case_id", "model_kind", "seed", "run_id", "status", "execution_complete", "natural_exit", "worker_exit_code", "source_reader_sha256", "checkpoint_sha256", "trajectory_sha256", "prediction_sha256", "score_sha256", "validator_sha256", "expected_frames", "observed_frames", "expected_transitions", "observed_transitions", "frame_denominator_fixed", "validator_passed"}, "candidate.terminal")
    _exact(terminal, "schema", TERMINAL_SCHEMA, "candidate.terminal")
    for key in ("family", "scope_id", "case_id", "model_kind", "seed", "run_id"):
        _exact(terminal, key, expected[key] if key in expected else expected["formal_run_id"], "candidate.terminal")
    _exact(terminal, "run_id", expected["formal_run_id"], "candidate.terminal")
    _exact(terminal, "status", "complete", "candidate.terminal")
    _exact(terminal, "execution_complete", True, "candidate.terminal")
    _exact(terminal, "natural_exit", True, "candidate.terminal")
    _exact(terminal, "worker_exit_code", 0, "candidate.terminal")
    terminal_ref = _file_ref({key: terminal.get(key) for key in ("path", "sha256", "bytes")}, "candidate.terminal")
    _exact(terminal, "source_reader_sha256", reader_ref["sha256"], "candidate.terminal")
    _exact(terminal, "checkpoint_sha256", checkpoint_ref["sha256"], "candidate.terminal")
    transitions = _integer(terminal.get("expected_transitions"), "candidate.terminal.expected_transitions", minimum=1)
    _exact(terminal, "observed_transitions", transitions, "candidate.terminal")
    frames = _integer(terminal.get("expected_frames"), "candidate.terminal.expected_frames", minimum=2)
    _exact(terminal, "observed_frames", frames, "candidate.terminal")
    if frames != transitions + 1:
        _fail("candidate.terminal frame/transition denominator is not fixed to frames=transitions+1")
    _exact(terminal, "frame_denominator_fixed", True, "candidate.terminal")
    _exact(terminal, "validator_passed", True, "candidate.terminal")

    artifacts = _mapping(candidate.get("artifacts"), "candidate.artifacts")
    _reject_unknown(artifacts, {"trajectory", "prediction", "score", "validator"}, "candidate.artifacts")
    artifact_refs = {key: _validate_candidate_ref(artifacts.get(key), f"candidate.artifacts.{key}") for key in ("trajectory", "prediction", "score", "validator")}
    if len({(ref["path"], ref["sha256"]) for ref in artifact_refs.values()}) != 4:
        _fail("candidate artifacts must have four distinct path/digest identities")
    for key in ("trajectory", "prediction", "score", "validator"):
        _exact(terminal, f"{key}_sha256", artifact_refs[key]["sha256"], "candidate.terminal")

    claims = _mapping(candidate.get("claims"), "candidate.claims")
    _reject_unknown(claims, set(ZERO_CREDIT), "candidate.claims")
    for key, value in ZERO_CREDIT.items():
        _exact(claims, key, value, "candidate.claims")
    return {
        "row_key": [expected["family"], expected["scope_id"], expected["case_id"], expected["model_kind"], expected["seed"]],
        "typed_binding_valid": True,
        "status": "typed_binding_ready_zero_credit",
        "observed_case_run": False,
        "t1": False,
        "credit": 0,
        "references": {"training_receipt": training_ref, "checkpoint": checkpoint_ref, "source_reader": reader_ref, "terminal": terminal_ref, "artifacts": artifact_refs},
    }


def project_candidate(candidate: Mapping[str, Any], expected: Mapping[str, Any]) -> dict[str, Any]:
    try:
        return validate_candidate(candidate, expected)
    except BindingError as error:
        return {
            "row_key": [candidate.get("family"), candidate.get("scope_id"), candidate.get("case_id"), candidate.get("model_kind"), candidate.get("seed")] if isinstance(candidate, Mapping) else [],
            "typed_binding_valid": False,
            "status": "blocked_fail_closed",
            "observed_case_run": False,
            "t1": False,
            "credit": 0,
            "blocked_reasons": [str(error)],
        }


def build_report(root: Path = LAB_ROOT, campaign: Path | str = DEFAULT_CAMPAIGN, candidate_paths: Sequence[str | Path] = ()) -> dict[str, Any]:
    root = Path(root).resolve()
    contract, contract_meta = _load_contract(root, campaign)
    input_bindings: list[dict[str, Any]] = [_input_ref(contract_meta, "T1 typed-evidence campaign contract")]
    status, status_meta = _load_ref(root, contract, "core_status", "Core campaign status")
    launch, launch_meta = _load_ref(root, contract, "formal_launch", "Core formal launch contract")
    capacity, capacity_meta = _load_ref(root, contract, "formal_capacity", "Core formal capacity evidence")
    for meta, role in ((status_meta, "Core campaign status"), (launch_meta, "Core formal launch contract"), (capacity_meta, "Core formal capacity evidence")):
        input_bindings.append(_input_ref(meta, role))
    if status.get("schema") != COMPLETION_SCHEMA:
        _fail("Core campaign status schema drift")
    models, seeds, updates, formal_run_ids = _formal_identity(launch)
    if updates != FORMAL_UPDATES:
        _fail("formal launch update target drifted from 32000")
    if capacity.get("schema") != CAPACITY_SCHEMA or capacity.get("formal_capacity_evidence") is not False:
        _fail("formal capacity contract is not the expected blocked zero-capacity record")
    rows, observations, family_counts = _expected_rows(contract, root, models, seeds, updates)
    # Bind matrix input hashes after the fixed row projection has been checked.
    for observation in observations:
        input_bindings.append({"role": f"{observation['family']} {observation.get('model_kind', 'T1')} current matrix", **observation["matrix"]})
    f4_section = _mapping(contract.get("f4"), "campaign.f4")
    _f4_audit, f4_audit_meta = _read_json(root, _string(f4_section.get("denominator_audit_path"), "campaign.f4.denominator_audit_path"), name="F4 T1 denominator audit for binding")
    input_bindings.append(_input_ref(f4_audit_meta, "F4 T1 denominator audit"))

    expected_by_key = {
        (row["family"], row["scope_id"], row["case_id"], row["model_kind"], row["seed"]): row for row in rows
    }
    candidate_projections: list[dict[str, Any]] = []
    seen_candidate_keys: set[tuple[Any, ...]] = set()
    for candidate_path in candidate_paths:
        candidate, candidate_meta = _read_json(root, candidate_path, name="candidate typed evidence")
        input_bindings.append(_input_ref(candidate_meta, "candidate typed evidence"))
        key = tuple(candidate.get(name) for name in ("family", "scope_id", "case_id", "model_kind", "seed"))
        if key in seen_candidate_keys:
            candidate_projections.append({"row_key": list(key), "typed_binding_valid": False, "status": "blocked_fail_closed", "observed_case_run": False, "t1": False, "credit": 0, "blocked_reasons": ["fail-closed: duplicate candidate row identity"]})
            continue
        seen_candidate_keys.add(key)
        expected = expected_by_key.get(key)
        if expected is None:
            candidate_projections.append({"row_key": list(key), "typed_binding_valid": False, "status": "blocked_fail_closed", "observed_case_run": False, "t1": False, "credit": 0, "blocked_reasons": ["fail-closed: candidate identity is outside the fixed T1 matrix"]})
        else:
            candidate_projections.append(project_candidate(candidate, expected))

    valid_candidates = [item for item in candidate_projections if item.get("typed_binding_valid") is True]
    matrix_gap_count = sum(int(item.get("terminal_required", 0)) - int(item.get("terminal_observed", 0)) for item in observations)
    gap_findings = [
        {"code": "NO_OBSERVED_MODEL_CASE_RUN_RECEIPTS", "severity": "blocking", "affected_rows": EXPECTED_T1_CASE_RUNS, "observed": 0, "required": EXPECTED_T1_CASE_RUNS, "reason": "F3/F4 matrices and the existing F4 denominator audit contain no observed model case-run receipt."},
        {"code": "MATRIX_PLANS_ARE_NOT_TERMINAL_EVIDENCE", "severity": "blocking", "affected_rows": matrix_gap_count, "reason": "planned case×seed rows expose output placeholders but no natural-exit terminal receipt cross-bound to a source-reader receipt."},
        {"code": "F3_TRAINING_MATRIX_IS_DIAGNOSTIC_FRONTIER_ONLY", "severity": "blocking", "affected_rows": F3_CASE_COUNT * len(MODEL_KINDS) * len(SEEDS), "reason": "current-manifest matrices plan diagnostic 500-update identities while the formal launch contract requires 32000-update model/seed identities."},
        {"code": "F4_SOURCE_READER_MANIFEST_SHA_DRIFT", "severity": "blocking", "affected_rows": F4_EVALUATION_CASE_COUNT * len(MODEL_KINDS) * len(SEEDS), "reason": "F4 material matrix records reader manifest SHA mismatch; a future source-reader receipt must bind the exact current manifest digest."},
        {"code": "F4_MATERIAL_SIDECAR_IS_NOT_MODEL_CASE_RUN_EVIDENCE", "severity": "blocking", "affected_rows": F4_EVALUATION_CASE_COUNT * len(MODEL_KINDS) * len(SEEDS), "reason": "the F4 sidecar matrix is a material/trajectory contract and has zero complete sidecars/model case-run receipts."},
        {"code": "FORMAL_CAPACITY_AND_LAUNCH_NOT_ADMITTED", "severity": "blocking", "affected_rows": EXPECTED_T1_CASE_RUNS, "reason": "formal capacity evidence is false and the nine-run launch contract is proposal-only/launch-disallowed."},
    ]
    report: dict[str, Any] = {
        "schema": SCHEMA,
        "report_id": "t1-observed-model-case-run-evidence-binding-v1",
        "status": "typed_evidence_gap_fail_closed",
        "decision": "define_missing_typed_projection_without_observing_or_counting_any_case-run",
        "source_bound": True,
        "fail_closed": True,
        **ZERO_CREDIT,
        "observed_case_runs": 0,
        "required_case_runs": EXPECTED_T1_CASE_RUNS,
        "missing_case_runs": EXPECTED_T1_CASE_RUNS,
        "formal_run_ids": formal_run_ids,
        "core_status": {
            "can_finalize": status.get("can_finalize"), "t1_families": status.get("t1_families"),
            "observed_t1_case_runs": status.get("observed_t1_case_runs"), "minimum_t1_case_runs": status.get("minimum_t1_case_runs"),
            "missing_target_t1_case_runs": status.get("missing_target_t1_case_runs"), "missing_material_case_runs": status.get("missing_material_case_runs"),
        },
        "formal_contract": {
            "schema": launch.get("schema"), "launch_allowed": launch.get("launch_allowed"),
            "formal_job_count": launch.get("formal_job_count"), "required_formal_job_count": launch.get("required_formal_job_count"),
            "updates": updates, "capacity_claim": _mapping(launch.get("resource_estimates"), "formal launch.resource_estimates").get("capacity_claim"),
        },
        "capacity_contract": {
            "schema": capacity.get("schema"), "status": capacity.get("status"),
            "formal_capacity_evidence": capacity.get("formal_capacity_evidence"),
            "observed_update_frontier": capacity.get("observed_update_frontier"),
        },
        "fixed_t1_projection": {
            "family_counts": family_counts, "model_kinds": list(models), "seeds": list(seeds),
            "f3_case_count": F3_CASE_COUNT, "f4_evaluation_case_count": F4_EVALUATION_CASE_COUNT,
            "expected_row_count": len(rows), "rows": rows,
        },
        "typed_binding_contract": {
            "candidate_schema": CANDIDATE_SCHEMA,
            "required_identity": ["family", "scope_id", "case_id", "split", "model_kind", "seed"],
            "required_bindings": ["matrix_binding", "model_binding", "source_reader", "terminal", "artifacts", "claims"],
            "cross_bindings": [
                "matrix_binding→fixed family/scope/case/manifest digest",
                "model_binding→formal model/seed/run_id/32000-update identity",
                "source_reader→fixed family/scope/case/manifest/source digest",
                "terminal→same model/case identity, source_reader digest, checkpoint and artifact digests",
                "terminal→natural exit, complete validator, fixed frames/transitions",
                "claims→diagnostic-only, T1=false, credit=0",
            ],
            "candidate_projection_never_counts": True,
        },
        "candidate_intake": {
            "supplied_count": len(candidate_projections),
            "typed_binding_ready_count": len(valid_candidates),
            "observed_case_runs": 0,
            "T1_numerical": False,
            "credit": 0,
            "rows": candidate_projections,
        },
        "matrix_observations": observations,
        "gap_findings": gap_findings,
        "input_bindings": input_bindings,
        "input_boundary": {
            "bounded_json_only": True,
            "hdf5_content_opened": False,
            "hdf5_hash_recomputed": False,
            "checkpoint_content_opened": False,
            "trajectory_content_opened": False,
            "solver_started": False,
            "worker_started": False,
            "gpu_started": False,
            "queue_started": False,
        },
        "protected_state": {
            "registry_mutations": 0, "ledger_mutations": 0, "denominator_mutations": 0,
            "gate_mutations": 0, "completion_mutations": 0, "plan_mutations": 0,
        },
        "interpretation": "This additive intake identifies the missing typed observed model case-run projection. It does not convert matrix plans, material sidecars, progress, PID, static claims, or diagnostic training into observed T1 evidence.",
    }
    validate_report(report)
    return report


def validate_report(report: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema") != SCHEMA:
        errors.append("schema drift")
    if report.get("status") != "typed_evidence_gap_fail_closed":
        errors.append("status drift")
    for key, expected in ZERO_CREDIT.items():
        if report.get(key) != expected:
            errors.append(f"{key} must be {expected!r}")
    if report.get("observed_case_runs") != 0 or report.get("required_case_runs") != EXPECTED_T1_CASE_RUNS or report.get("missing_case_runs") != EXPECTED_T1_CASE_RUNS:
        errors.append("observed/required/missing fixed T1 counts drift")
    if report.get("fail_closed") is not True:
        errors.append("report must remain fail-closed")
    projection = report.get("fixed_t1_projection")
    if not isinstance(projection, Mapping) or projection.get("expected_row_count") != EXPECTED_T1_CASE_RUNS:
        errors.append("fixed T1 projection row count drift")
    intake = report.get("candidate_intake")
    if not isinstance(intake, Mapping) or intake.get("observed_case_runs") != 0 or intake.get("T1_numerical") is not False or intake.get("credit") != 0:
        errors.append("candidate intake authority drift")
    boundary = report.get("input_boundary")
    if not isinstance(boundary, Mapping):
        errors.append("input_boundary missing")
    else:
        for key in ("hdf5_content_opened", "hdf5_hash_recomputed", "checkpoint_content_opened", "trajectory_content_opened", "solver_started", "worker_started", "gpu_started", "queue_started"):
            if boundary.get(key) is not False:
                errors.append(f"input_boundary.{key} must be false")
    protected = report.get("protected_state")
    if not isinstance(protected, Mapping):
        errors.append("protected_state missing")
    else:
        for key in ("registry_mutations", "ledger_mutations", "denominator_mutations", "gate_mutations", "completion_mutations", "plan_mutations"):
            if protected.get(key) != 0:
                errors.append(f"protected_state.{key} must be zero")
    return errors


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    except OSError as error:
        raise BindingError(f"refusing to overwrite output {path}: {error}") from error
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)


def render_markdown(report: Mapping[str, Any]) -> str:
    projection = _mapping(report["fixed_t1_projection"], "report.fixed_t1_projection")
    observations = report["matrix_observations"]
    lines = [
        "# T1 observed model case-run evidence binding",
        "",
        f"- 状态：`{report['status']}`；typed projection：`{report['source_bound']}`；fail-closed：`{report['fail_closed']}`",
        f"- Core observed T1 case-runs：`{report['observed_case_runs']}/{report['required_case_runs']}`；缺口：`{report['missing_case_runs']}`",
        "- T1：`false`；formal：`false`；credit：`0`；本 intake 不写入 Core 状态。",
        "",
        "## 真正未覆盖的 typed binding",
        "",
        "每个未来 row 必须把 `family/scope/case/seed` 同时绑定到 matrix digest、formal model identity、source-reader receipt、natural-exit terminal receipt 与四个产物 digest；现有 matrix/audit 没有这一整行 observed receipt。",
        "",
        "| family | matrix planned/observed terminal | typed rows |",
        "|---|---:|---:|",
    ]
    for item in observations:
        typed_rows = (F3_CASE_COUNT * len(SEEDS)) if item["family"] == "F3" else (F4_EVALUATION_CASE_COUNT * len(MODEL_KINDS) * len(SEEDS))
        lines.append(f"| {item['family']} {item.get('model_kind', 'T1')} | {item.get('terminal_required', 0)}/{item.get('terminal_observed', 0)} | {typed_rows} |")
    lines.extend(["", "## 阻塞原因", ""])
    for finding in report["gap_findings"]:
        lines.append(f"- `{finding['code']}`：{finding['reason']}")
    lines.extend([
        "",
        "## 边界",
        "",
        "只读取有界 JSON 元数据；没有打开/重哈希 HDF5、checkpoint 或 trajectory，没有启动 solver/worker/GPU/queue，也没有修改 registry、ledger、denominator、gate、completion 或 PLAN。",
        "",
        "完整 candidate 即使通过本 projection，也只会得到 `typed_binding_ready_zero_credit`，不会被计为 observed/T1。",
        "",
    ])
    return "\n".join(lines)


def write_report(report: Mapping[str, Any], output: Path = DEFAULT_REPORT, markdown_output: Path = DEFAULT_MARKDOWN_REPORT) -> tuple[Path, Path]:
    errors = validate_report(report)
    if errors:
        raise BindingError("report validation failed: " + "; ".join(errors))
    json_path = Path(output)
    md_path = Path(markdown_output)
    _write_new(json_path, (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"))
    _write_new(md_path, render_markdown(report).encode("utf-8"))
    return json_path, md_path


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, default=DEFAULT_CAMPAIGN)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_REPORT)
    parser.add_argument("--candidate", action="append", default=[], type=Path)
    args = parser.parse_args(argv)
    report = build_report(LAB_ROOT, args.campaign, args.candidate)
    output, markdown = write_report(report, args.output, args.markdown_output)
    print(json.dumps({"output": str(output), "markdown": str(markdown), "observed_case_runs": 0, "credit": 0}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
