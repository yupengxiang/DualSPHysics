#!/usr/bin/env python3
"""ROOT242 V13 metadata endpoint using the current V23 access manifest.

V12 is already consumed and remains byte-for-byte unchanged.  This additive
wrapper reuses its bounded endpoint implementation while binding the current
V23 source/access manifest and emitting a new endpoint schema/file.  It reads
only bounded JSON and small license files.  V27 is an explicit physical-union
artifact; if a family anchor is still an unresolved historical alias, the
result remains blocked instead of silently selecting another case.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_V12_PATH = SCRIPT_DIR / "ds_data02_stage2_f2_root242_v12_dataset_only_endpoint.py"
_SPEC = importlib.util.spec_from_file_location("root242_v12_for_v13", _V12_PATH)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover - import setup
    raise ImportError(f"cannot load {_V12_PATH}")
_V12 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V12)


SCHEMA = "ds02.stage2.f2-root242-dataset-only-endpoint.v13"
ACCESS_SCHEMA = "ds02.stage2.seven-family-source-access-index.v23"
V27_SCHEMA = "ds02.stage2.all336-effective-condition-source-index.v27"


class DatasetEndpointV13Error(ValueError):
    """The V23/V27 endpoint input is stale, ambiguous, or unsafe."""


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def _read_json(path: Path, role: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _V12.MAX_METADATA_BYTES:
        raise DatasetEndpointV13Error(f"{role} must be a bounded regular metadata file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DatasetEndpointV13Error(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise DatasetEndpointV13Error(f"{role} must be a JSON object")
    return value


def _sha_file(path: Path) -> str:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > _V12.MAX_METADATA_BYTES:
        raise DatasetEndpointV13Error(f"invalid {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_v23_access(path: Path, current_file_sha: str, repo_root: Path) -> None:
    access = _read_json(path, "V23 source/access manifest")
    if access.get("schema") != ACCESS_SCHEMA or access.get("qualification") != _V12.UNKNOWN:
        raise DatasetEndpointV13Error("V23 source/access schema or qualification differs")
    current = access.get("current_binding")
    if not isinstance(current, Mapping) or current.get("sha256") != current_file_sha:
        raise DatasetEndpointV13Error("V23 source/access manifest does not bind CURRENT")
    policy = access.get("access_policy")
    if not isinstance(policy, Mapping) or policy.get("exact_paths_only") is not True \
            or policy.get("latest_or_glob_fallback") is not False \
            or policy.get("external_paths_are_provenance_only_until_parent_guard") is not True:
        raise DatasetEndpointV13Error("V23 access policy is not exact and parent-guarded")
    dependencies = access.get("dependencies_and_licenses")
    if not isinstance(dependencies, Mapping):
        raise DatasetEndpointV13Error("V23 dependency/license closure is missing")
    for role in ("repository_license", "reader_dependency_license_index_v13"):
        item = dependencies.get(role)
        if not isinstance(item, Mapping) or not isinstance(item.get("repo_relative_path"), str):
            raise DatasetEndpointV13Error(f"V23 {role} path is missing")
        target = (repo_root / str(item["repo_relative_path"])).absolute()
        if target.is_symlink() or not target.is_file() or target.stat().st_size > _V12.MAX_LICENSE_BYTES:
            raise DatasetEndpointV13Error(f"V23 {role} is missing or unbounded")
        if _sha_file(target) != item.get("sha256"):
            raise DatasetEndpointV13Error(f"V23 {role} SHA differs")
    interpreter = dependencies.get("runtime_interpreter")
    if not isinstance(interpreter, Mapping) or not isinstance(interpreter.get("required_invocation"), str):
        raise DatasetEndpointV13Error("V23 literal interpreter binding is missing")
    official = dependencies.get("official_solver_library")
    if not isinstance(official, Mapping):
        raise DatasetEndpointV13Error("V23 official solver library scope is missing")


def build_dataset_endpoint_v13(*, current_path: Path | str, catalog_path: Path | str,
                               v27_index_path: Path | str, anchor_index_path: Path | str,
                               source_access_path: Path | str, portable_request_path: Path | str,
                               portable_contract_path: Path | str, repo_root: Path | str,
                               output_dir: Path | str) -> dict[str, Any]:
    """Build a V13 endpoint through the consumed V12 validator in a temp dir."""
    current_target = Path(current_path).expanduser().absolute()
    current_meta = _V12._metadata_ref(current_target, "CURRENT336")
    _validate_v23_access(Path(source_access_path).expanduser().absolute(),
                         str(current_meta["file_sha256"]), Path(repo_root).expanduser().absolute())

    output = Path(output_dir).expanduser().absolute()
    if output.exists() and any(output.iterdir()):
        raise DatasetEndpointV13Error(f"output directory is not fresh: {output}")
    output.mkdir(parents=True, exist_ok=True)

    # The V12 implementation is pure bounded metadata validation.  Override
    # only its schema constant while it runs in an isolated temporary output;
    # no V12 artifact is changed and no V12 file is overwritten.
    old_schema = _V12.SCHEMA
    old_access_schema = _V12.ACCESS_SCHEMA
    _V12.SCHEMA = SCHEMA
    _V12.ACCESS_SCHEMA = ACCESS_SCHEMA
    try:
        with tempfile.TemporaryDirectory(prefix="root242-v13-build-") as temporary:
            result = _V12.build_dataset_endpoint(
                current_path=current_target, catalog_path=Path(catalog_path).expanduser().absolute(),
                v27_index_path=Path(v27_index_path).expanduser().absolute(),
                anchor_index_path=Path(anchor_index_path).expanduser().absolute(),
                source_access_path=Path(source_access_path).expanduser().absolute(),
                portable_request_path=Path(portable_request_path).expanduser().absolute(),
                portable_contract_path=Path(portable_contract_path).expanduser().absolute(),
                repo_root=Path(repo_root).expanduser().absolute(), output_dir=Path(temporary))
            old_path = Path(result["path"])
            endpoint = _read_json(old_path, "temporary V13 endpoint")
    except (_V12.DatasetEndpointError, OSError, ValueError, json.JSONDecodeError) as error:
        raise DatasetEndpointV13Error(str(error)) from error
    finally:
        _V12.SCHEMA = old_schema
        _V12.ACCESS_SCHEMA = old_access_schema

    endpoint["schema"] = SCHEMA
    endpoint["request_id"] = "root242-v13-dataset-only-endpoint-v23-root307-001"
    endpoint["access_and_rights"]["manifest"]["schema"] = ACCESS_SCHEMA
    endpoint["access_and_rights"]["manifest"]["access_schema_upgrade"] = {
        "from": "ds02.stage2.seven-family-source-access-index.v22",
        "to": ACCESS_SCHEMA,
        "reason": "V23 adds official solver library and current source proof scope",
    }
    endpoint["source_access_binding"] = {
        "schema": ACCESS_SCHEMA,
        "path": str(Path(source_access_path).expanduser().absolute()),
        "file_sha256": _sha_file(Path(source_access_path).expanduser().absolute()),
        "content_policy": "bounded access/license metadata only",
    }
    endpoint["sha256"] = _canonical_sha(endpoint)
    request_path = output / "root242-v13-dataset-only-endpoint-request.json"
    if request_path.exists() or request_path.is_symlink():
        raise DatasetEndpointV13Error(f"refusing to overwrite endpoint: {request_path}")
    text = json.dumps(endpoint, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    request_path.write_text(text, encoding="utf-8")
    return {"path": str(request_path), "schema": endpoint["schema"],
            "status": endpoint.get("status"), "canonical_sha256": endpoint["sha256"],
            "file_sha256": hashlib.sha256(text.encode()).hexdigest(),
            "source_access_schema": ACCESS_SCHEMA,
            "payload_read": False, "ledger_mutated": False, "launch_performed": False}


def validate_endpoint_v13(path: Path | str) -> dict[str, Any]:
    target = Path(path).expanduser().absolute()
    endpoint = _read_json(target, "V13 endpoint")
    if endpoint.get("schema") != SCHEMA or endpoint.get("sha256") != _canonical_sha(endpoint):
        raise DatasetEndpointV13Error("V13 endpoint schema/canonical SHA differs")
    access = endpoint.get("source_access_binding")
    if not isinstance(access, Mapping) or access.get("schema") != ACCESS_SCHEMA:
        raise DatasetEndpointV13Error("V13 endpoint lacks V23 source/access binding")
    selected = endpoint.get("anchor_binding", {}).get("selected")
    if not isinstance(selected, list) or len(selected) != 7:
        raise DatasetEndpointV13Error("V13 endpoint does not contain seven anchors")
    if endpoint.get("execution", {}).get("reserve_before_copy_or_payload_hash") is not True:
        raise DatasetEndpointV13Error("V13 endpoint does not reserve before payload access")
    if endpoint.get("portable_binding", {}).get("original_path_fallback") != "REJECT":
        raise DatasetEndpointV13Error("V13 endpoint permits original fallback")
    return {"schema": SCHEMA, "status": endpoint.get("status"), "path": str(target),
            "canonical_sha256": endpoint["sha256"], "anchor_count": len(selected),
            "canonical_anchor_count": endpoint.get("anchor_binding", {}).get("canonical_anchor_count"),
            "blocked_anchor_count": endpoint.get("anchor_binding", {}).get("blocked_anchor_count"),
            "source_access_schema": ACCESS_SCHEMA, "payload_read": False,
            "ledger_mutated": False, "launch_performed": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    for name in ("current", "catalog", "v27-index", "anchor-index", "source-access",
                 "portable-request", "portable-contract", "repo-root", "output"):
        build.add_argument("--" + name, type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = build_dataset_endpoint_v13(
                current_path=args.current, catalog_path=args.catalog,
                v27_index_path=args.v27_index, anchor_index_path=args.anchor_index,
                source_access_path=args.source_access,
                portable_request_path=args.portable_request,
                portable_contract_path=args.portable_contract, repo_root=args.repo_root,
                output_dir=args.output)
        else:
            result = validate_endpoint_v13(args.request)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except (DatasetEndpointV13Error, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"ROOT242 V13 dataset-only endpoint: {error}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
