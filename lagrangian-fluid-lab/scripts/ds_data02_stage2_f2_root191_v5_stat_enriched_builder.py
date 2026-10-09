#!/usr/bin/env python3
"""Build and admit a ROOT191 V5 stat-enriched request.

The V4 request and its bytes remain immutable.  This forward builder creates a
new request namespace from the already integrated main-worktree V3 builder,
then joins three small pieces of evidence:

* the ROOT200 proof's declared source-result stat (the proof only contains
  bytes, mode and mtime),
* the ROOT200 inner request's corresponding declaration, and
* a six-field ``stat(2)`` snapshot of the currently bound result file.

The result JSON, H5, BI4, native frames, and solver/evaluator are never opened
by this metadata builder.  The full stat is an admission contract; V5 refuses
if any field changes before a later consumer run.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


MAIN_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
SCRIPT_DIR = MAIN_ROOT / "lagrangian-fluid-lab/scripts"
PRIMARY_SCRIPT = SCRIPT_DIR / "ds_data02_stage2_f2_root191_v3_primary_builder.py"
V5_SCHEMA = "ds02.stage2.f2-root191-stat-enriched-builder.v1"
STAT_SCHEMA = "ds02.stage2.f2-root191-full-result-stat-contract.v1"
FULL_STAT_FIELDS = ("bytes", "mode_bits", "mtime_ns", "ctime_ns", "st_dev", "st_ino")
PROOF_STAT_FIELDS = ("bytes", "mode_bits", "mtime_ns")
MAX_METADATA_BYTES = 32 * 1024 * 1024

AGENT_STAGE2 = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2"
DEFAULT_OUTPUT = AGENT_STAGE2 / (
    "native-reconstruction/root191-v5-stat-enriched-20261009/"
    "f2-s1-root191-v5-stat-enriched-request.json"
)
DEFAULT_FRESH_ROOT = Path("/var/tmp/ds02-stage2/F2/STAGE2_F2_ROOT191_V5_STAT_ENRICHED_20261009")
DEFAULT_CASE = "f2-s1-root191-v5-stat-enriched-root200-001"
DEFAULT_ATTEMPT = "f2-s1-root191-v5-stat-enriched-root200-001-root-forward-030-001"


class Root191V5BuilderError(RuntimeError):
    """A strict V5 metadata or stat-binding error."""


def _load_primary() -> Any:
    if not PRIMARY_SCRIPT.is_file() or PRIMARY_SCRIPT.is_symlink():
        raise Root191V5BuilderError(f"main primary builder is unavailable: {PRIMARY_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_root191_primary_builder_for_v5", PRIMARY_SCRIPT)
    if spec is None or spec.loader is None:
        raise Root191V5BuilderError(f"cannot load main primary builder: {PRIMARY_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PRIMARY = _load_primary()


def _json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise Root191V5BuilderError(f"{role} is not a regular file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise Root191V5BuilderError(f"{role} exceeds bounded metadata size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise Root191V5BuilderError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise Root191V5BuilderError(f"{role} must be a JSON object")
    return value


def _sha(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise Root191V5BuilderError(f"expected a regular metadata file: {path}")
    if path.stat().st_size > MAX_METADATA_BYTES:
        raise Root191V5BuilderError(f"metadata file exceeds bounded size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _full_stat(path: Path) -> dict[str, int]:
    if path.is_symlink() or not path.is_file():
        raise Root191V5BuilderError(f"bound result must be a regular non-symlink file: {path}")
    info = path.stat()
    return {
        "bytes": int(info.st_size),
        "mode_bits": int(info.st_mode & 0o7777),
        "mtime_ns": int(info.st_mtime_ns),
        "ctime_ns": int(info.st_ctime_ns),
        "st_dev": int(info.st_dev),
        "st_ino": int(info.st_ino),
    }


def _require_int_fields(value: Mapping[str, Any], fields: Sequence[str], role: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for field in fields:
        if field not in value or isinstance(value[field], bool):
            raise Root191V5BuilderError(f"{role} lacks integer stat field {field}")
        try:
            result[field] = int(value[field])
        except (TypeError, ValueError) as error:
            raise Root191V5BuilderError(f"{role}.{field} is not an integer") from error
    return result


def _proof_stat(value: Any, role: str) -> tuple[dict[str, int], dict[str, Any]]:
    if not isinstance(value, Mapping):
        raise Root191V5BuilderError(f"{role} is missing its declared stat")
    mode = value.get("mode_bits", value.get("mode"))
    if mode is None:
        raise Root191V5BuilderError(f"{role} lacks mode_bits/mode")
    normalized = _require_int_fields(
        {"bytes": value.get("bytes"), "mode_bits": mode, "mtime_ns": value.get("mtime_ns")},
        PROOF_STAT_FIELDS,
        role,
    )
    return normalized, dict(value)


def _canonical(request: Mapping[str, Any]) -> str:
    try:
        return str(PRIMARY.V3.canonical_sha(request))
    except AttributeError as error:
        raise Root191V5BuilderError("main V3 canonical helper is unavailable") from error


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise Root191V5BuilderError(f"refusing to overwrite request: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                    encoding="utf-8")


def _load_root200_inputs(request: Mapping[str, Any]) -> tuple[Path, dict[str, Any], Path, dict[str, Any]]:
    root = request.get("root200_binding")
    if not isinstance(root, Mapping):
        raise Root191V5BuilderError("request lacks root200_binding")
    inner = root.get("inner_request")
    proof_binding = root.get("fresh_v12_proof")
    if not isinstance(inner, Mapping) or not isinstance(proof_binding, Mapping):
        raise Root191V5BuilderError("ROOT200 inner/proof bindings are incomplete")
    inner_path = Path(str(inner.get("path"))).expanduser()
    proof_path = Path(str(proof_binding.get("path"))).expanduser()
    inner_json = _json(inner_path, "ROOT200 inner request")
    proof_json = _json(proof_path, "ROOT200 fresh V12 proof")
    return inner_path, inner_json, proof_path, proof_json


def _make_stat_contract(request: dict[str, Any]) -> dict[str, Any]:
    inner_path, inner, proof_path, proof = _load_root200_inputs(request)
    result = request.get("root200_binding", {}).get("result")
    inner_result = inner.get("result")
    proof_result = proof.get("source_result")
    if not isinstance(result, Mapping) or not isinstance(inner_result, Mapping):
        raise Root191V5BuilderError("ROOT200 result binding is incomplete")
    if not isinstance(proof_result, Mapping):
        raise Root191V5BuilderError("ROOT200 proof has no source_result binding")
    for field in ("path", "sha256", "bytes"):
        if result.get(field) != inner_result.get(field) or proof_result.get(field) != result.get(field):
            raise Root191V5BuilderError(f"ROOT200 result identity differs for {field}")
    proof_stat, proof_stat_raw = _proof_stat(proof_result.get("stat"), "ROOT200 proof source_result.stat")
    inner_declared = inner_result.get("stat")
    if inner_declared is not None:
        inner_stat, _ = _proof_stat(inner_declared, "ROOT200 inner result.stat")
        if inner_stat != proof_stat:
            raise Root191V5BuilderError("ROOT200 proof and inner declared result stats differ")
    result_path = Path(str(result["path"])).expanduser()
    current = _full_stat(result_path)
    if current["bytes"] != int(result["bytes"]):
        raise Root191V5BuilderError("current result size differs from ROOT200 declared bytes")
    for field in PROOF_STAT_FIELDS:
        if current[field] != proof_stat[field]:
            raise Root191V5BuilderError(f"current result stat differs from ROOT200 proof for {field}")
    proof_file_stat = _full_stat(proof_path)
    proof_file_sha = _sha(proof_path)
    # The request result binding is deliberately replaced only in this new V5
    # request.  V4/001 and its source bytes are untouched.
    result_copy = dict(result)
    result_copy["stat"] = dict(current)
    result_copy["root200_actual_proof_stat"] = {
        "proof_file": {"path": str(proof_path), "sha256": proof_file_sha, "stat": proof_file_stat},
        "source_result_stat": proof_stat_raw,
        "source_result_stat_normalized": proof_stat,
        "source_result_stat_fields_available": list(proof_stat),
    }
    request["root200_binding"]["result"] = result_copy
    contract = {
        "schema": STAT_SCHEMA,
        "result": {
            "path": str(result_path),
            "sha256": result["sha256"],
            "bytes": int(result["bytes"]),
            "expected_pre_stat": dict(current),
            "expected_post_stat": dict(current),
        },
        "root200_actual_proof": {
            "proof_path": str(proof_path),
            "proof_file_sha256": proof_file_sha,
            "proof_source_result_stat": proof_stat_raw,
            "proof_source_result_stat_normalized": proof_stat,
            "proof_file_stat": proof_file_stat,
            "proof_source_result_stat_is_partial": True,
            "missing_from_root200_proof": ["ctime_ns", "st_dev", "st_ino"],
        },
        "current_full_stat": dict(current),
        "required_full_stat_fields": list(FULL_STAT_FIELDS),
        "stat_read_phase": "metadata_admission_only; no result content read",
        "source_content_read": False,
    }
    request["root191_v5_stat_contract"] = contract
    return contract


def build_enriched(*, output: Path = DEFAULT_OUTPUT, fresh_output_root: Path = DEFAULT_FRESH_ROOT,
                   case_id: str = DEFAULT_CASE, attempt_id: str = DEFAULT_ATTEMPT,
                   inputs: Mapping[str, Path] | None = None) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise Root191V5BuilderError(f"refusing to overwrite V5 request: {output}")
    # This creates a new request with the existing, integrated primary builder;
    # it does not touch the old ROOT191 V4 request.
    PRIMARY.build_primary(output=output, fresh_output_root=fresh_output_root,
                          case_id=case_id, attempt_id=attempt_id, inputs=inputs)
    request = _json(output, "new ROOT191 V5 request")
    contract = _make_stat_contract(request)
    request["root191_v5_stat_enriched_builder"] = {
        "schema": V5_SCHEMA,
        "main_worktree_root": str(MAIN_ROOT),
        "source_primary_builder": str(PRIMARY_SCRIPT),
        "source_primary_builder_sha256": _sha(PRIMARY_SCRIPT),
        "request_built_from_new_namespace": True,
        "old_v4_request_modified": False,
        "metadata_read_pass": {
            "root200_proof_and_inner_metadata_read": True,
            "result_stat_only": True,
            "result_content_read": False,
            "typed_h5_content_read": False,
            "bi4_native_content_read": False,
            "solver_or_evaluator_launched": False,
        },
        "stat_contract_schema": contract["schema"],
    }
    request["sha256"] = _canonical(request)
    output.write_text(json.dumps(request, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n",
                      encoding="utf-8")
    return {
        "schema": V5_SCHEMA,
        "status": "ROOT191_V5_STAT_ENRICHED_METADATA_BUILT",
        "request": str(output),
        "request_file_sha256": _sha(output),
        "request_canonical_sha256": request["sha256"],
        "result": contract["result"],
        "current_full_stat": contract["current_full_stat"],
        "root200_actual_proof": contract["root200_actual_proof"],
        "payload_read": False,
        "hdf5_bi4_native_read": False,
        "solver_or_evaluator_launched": False,
    }


def _validate_contract(path: Path, request: Mapping[str, Any]) -> dict[str, Any]:
    contract = request.get("root191_v5_stat_contract")
    if not isinstance(contract, Mapping) or contract.get("schema") != STAT_SCHEMA:
        raise Root191V5BuilderError("V5 full-stat contract is missing")
    current = _require_int_fields(contract.get("current_full_stat", {}), FULL_STAT_FIELDS,
                                  "V5 current_full_stat")
    result_contract = contract.get("result")
    result_binding = request.get("root200_binding", {}).get("result")
    if not isinstance(result_contract, Mapping) or not isinstance(result_binding, Mapping):
        raise Root191V5BuilderError("V5 result stat binding is incomplete")
    result_path = Path(str(result_contract.get("path"))).expanduser()
    if result_contract.get("path") != result_binding.get("path"):
        raise Root191V5BuilderError("V5 result path binding differs")
    if result_contract.get("sha256") != result_binding.get("sha256") or int(result_contract.get("bytes")) != int(result_binding.get("bytes")):
        raise Root191V5BuilderError("V5 result identity binding differs")
    expected = _require_int_fields(result_contract.get("expected_pre_stat", {}), FULL_STAT_FIELDS,
                                   "V5 expected_pre_stat")
    expected_post = _require_int_fields(result_contract.get("expected_post_stat", {}), FULL_STAT_FIELDS,
                                        "V5 expected_post_stat")
    if expected != current or expected_post != current:
        raise Root191V5BuilderError("V5 expected pre/post stat is not the current full stat")
    bound = _require_int_fields(result_binding.get("stat", {}), FULL_STAT_FIELDS,
                                "ROOT200 result.stat")
    if bound != current:
        raise Root191V5BuilderError("ROOT200 result.stat is not the V5 current full stat")
    actual = _full_stat(result_path)
    if actual != current:
        raise Root191V5BuilderError("bound result full stat differs from V5 expected stat")
    proof_meta = contract.get("root200_actual_proof")
    if not isinstance(proof_meta, Mapping):
        raise Root191V5BuilderError("V5 ROOT200 proof stat metadata is missing")
    proof_path = Path(str(proof_meta.get("proof_path"))).expanduser()
    proof_sha = _sha(proof_path)
    if proof_sha != proof_meta.get("proof_file_sha256"):
        raise Root191V5BuilderError("ROOT200 proof file SHA changed")
    proof = _json(proof_path, "ROOT200 V12 proof")
    source_result = proof.get("source_result")
    if not isinstance(source_result, Mapping):
        raise Root191V5BuilderError("ROOT200 proof source_result is missing")
    for field in ("path", "sha256", "bytes"):
        if source_result.get(field) != result_binding.get(field):
            raise Root191V5BuilderError(f"ROOT200 proof source result differs for {field}")
    proof_stat, _ = _proof_stat(source_result.get("stat"), "ROOT200 proof source_result.stat")
    if proof_stat != proof_meta.get("proof_source_result_stat_normalized"):
        raise Root191V5BuilderError("ROOT200 proof source stat changed")
    if any(current[field] != proof_stat[field] for field in PROOF_STAT_FIELDS):
        raise Root191V5BuilderError("current full stat no longer agrees with ROOT200 proof stat")
    if request.get("sha256") != _canonical(request):
        raise Root191V5BuilderError("V5 request canonical SHA is stale")
    return {"schema": STAT_SCHEMA, "status": "ROOT191_V5_FULL_STAT_METADATA_VALIDATED",
            "request": {"path": str(path), "file_sha256": _sha(path), "canonical_sha256": request["sha256"]},
            "result": {"path": str(result_path), "sha256": result_binding["sha256"],
                       "bytes": int(result_binding["bytes"]), "current_full_stat": current,
                       "proof_stat": proof_stat},
            "payload_read": False, "hdf5_bi4_native_read": False,
            "solver_or_evaluator_launched": False}


def validate_enriched(path: Path) -> dict[str, Any]:
    request = _json(path, "ROOT191 V5 request")
    primary_result = PRIMARY.validate_primary(path)
    checked = _validate_contract(path, request)
    checked["primary"] = primary_result
    return checked


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-enriched")
    build.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    build.add_argument("--fresh-output-root", type=Path, default=DEFAULT_FRESH_ROOT)
    build.add_argument("--case-id", default=DEFAULT_CASE)
    build.add_argument("--attempt-id", default=DEFAULT_ATTEMPT)
    check = sub.add_parser("validate-enriched")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build-enriched":
            value = build_enriched(output=args.output, fresh_output_root=args.fresh_output_root,
                                   case_id=args.case_id, attempt_id=args.attempt_id)
        else:
            value = validate_enriched(args.request)
    except (Root191V5BuilderError, OSError, ValueError, TypeError, json.JSONDecodeError,
            PRIMARY.V3.Root191V3Error) as error:
        print(f"ROOT191 V5 stat-enriched builder: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
