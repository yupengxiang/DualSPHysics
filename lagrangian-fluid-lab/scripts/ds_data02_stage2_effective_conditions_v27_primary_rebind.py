#!/usr/bin/env python3
"""Rebind V27 metadata inputs to a primary worktree without changing bytes.

The V27 artifact is immutable metadata, but the V26 request embedded
worktree-specific case-detail paths.  This forward-only utility verifies the
old and new bounded JSON files by both canonical SHA and file SHA, then emits
a fresh request plus an explicit sidecar.  It never rewrites the V26/V27
artifacts and never opens H5, BI4, raw arrays, JSONL or solver output.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


REQUEST_SCHEMA = "ds02.stage2.effective-condition-metadata-request.v27"
SIDECAR_SCHEMA = "ds02.stage2.effective-condition-v27-primary-rebinding.v1"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_CASE_BYTES = 256 * 1024
MAX_CASE_COUNT = 336


class RebindError(ValueError):
    """The immutable metadata or target path is not safely rebindable."""


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False, default=str)


def canonical_sha(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical({key: item for key, item in value.items()
                                     if key != "sha256"}).encode()).hexdigest()


def file_sha(path: Path, *, maximum: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise RebindError(f"expected regular non-symlink metadata file: {path}")
    if path.stat().st_size > maximum:
        raise RebindError(f"metadata file exceeds bounded limit: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path: Path, role: str, *, maximum: int) -> dict[str, Any]:
    observed = file_sha(path, maximum=maximum)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise RebindError(f"{role} must be an object")
    value["_observed_file_sha256"] = observed
    return value


def _without_observed(value: Mapping[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if key != "_observed_file_sha256"}


def _map_path(path: str, old_root: Path, new_root: Path, role: str) -> Path:
    source = Path(path).expanduser()
    if not source.is_absolute():
        raise RebindError(f"{role} path is not absolute: {path}")
    # The V27 request may already carry a primary-bound V26 index while its
    # embedded case-detail paths still point at the consumer worktree. Keep
    # an already-primary path unchanged, but still verify its bytes below.
    try:
        source.relative_to(new_root)
        return source
    except ValueError:
        pass
    try:
        relative = source.relative_to(old_root)
    except ValueError as error:
        raise RebindError(f"{role} path is outside declared source worktree: {path}") from error
    target = (new_root / relative).absolute()
    try:
        target.relative_to(new_root)
    except ValueError as error:  # pragma: no cover - defensive
        raise RebindError(f"{role} target escapes primary root: {target}") from error
    return target


def _verify_detail(path: Path, declared_canonical: str, declared_file: str,
                   declared_bytes: int, role: str) -> dict[str, Any]:
    observed_file = file_sha(path, maximum=MAX_CASE_BYTES)
    if observed_file != declared_file or path.stat().st_size != int(declared_bytes):
        raise RebindError(f"{role} file SHA/size differs after rebinding")
    value = read_json(path, role, maximum=MAX_CASE_BYTES)
    clean = _without_observed(value)
    if clean.get("sha256") != declared_canonical or canonical_sha(clean) != declared_canonical:
        raise RebindError(f"{role} canonical SHA differs after rebinding")
    return {"path": str(path), "file_sha256": observed_file,
            "canonical_sha256": declared_canonical, "bytes": int(path.stat().st_size),
            "content_policy": "bounded V26 case metadata; no payload arrays"}


def rebind_v27_request(*, request_path: Path | str, old_root: Path | str,
                       primary_root: Path | str, output_dir: Path | str) -> dict[str, Any]:
    source_request = Path(request_path).expanduser().absolute()
    old = Path(old_root).expanduser().absolute()
    primary = Path(primary_root).expanduser().absolute()
    output = Path(output_dir).expanduser().absolute()
    if output.exists() and any(output.iterdir()):
        raise RebindError(f"output directory is not fresh: {output}")
    request_raw = read_json(source_request, "V27 metadata request", maximum=MAX_REQUEST_BYTES)
    request = _without_observed(request_raw)
    if request.get("schema") != REQUEST_SCHEMA or request.get("sha256") != canonical_sha(request):
        raise RebindError("input is not a canonical V27 metadata request")
    source_inputs = request.get("source_inputs")
    if not isinstance(source_inputs, Mapping):
        raise RebindError("V27 request source_inputs is missing")
    v26 = source_inputs.get("v26_index")
    details = source_inputs.get("v26_case_details")
    if not isinstance(v26, Mapping) or not isinstance(details, list) or len(details) != MAX_CASE_COUNT:
        raise RebindError("V27 request lacks all 336 V26 metadata bindings")

    mapped_v26_path = _map_path(str(v26.get("path")), old, primary, "V26 index")
    v26_value = read_json(mapped_v26_path, "primary V26 index", maximum=MAX_INDEX_BYTES)
    v26_clean = _without_observed(v26_value)
    v26_file = file_sha(mapped_v26_path, maximum=MAX_INDEX_BYTES)
    if v26_file != v26.get("file_sha256") or (
            v26.get("bytes") is not None and
            mapped_v26_path.stat().st_size != int(v26["bytes"])):
        raise RebindError("primary V26 index file SHA/size differs")
    if v26_clean.get("sha256") != v26.get("sha256") or canonical_sha(v26_clean) != v26.get("sha256"):
        raise RebindError("primary V26 index canonical SHA differs")

    source_records: list[dict[str, Any]] = []
    rebound_details: list[dict[str, Any]] = []
    for index, item in enumerate(details):
        if not isinstance(item, Mapping) or not isinstance(item.get("path"), str):
            raise RebindError(f"V26 case detail {index} is malformed")
        target = _map_path(str(item["path"]), old, primary, f"V26 case detail {index}")
        verified = _verify_detail(target, str(item.get("sha256")), str(item.get("file_sha256")),
                                  int(item.get("bytes", -1)), f"V26 case detail {index}")
        source_records.append({"index": index, "old_path": str(Path(str(item["path"])).absolute()),
                               "new_path": str(target), "old_file_sha256": item.get("file_sha256"),
                               "new_file_sha256": verified["file_sha256"],
                               "canonical_sha256": verified["canonical_sha256"],
                               "bytes": verified["bytes"]})
        rebound = dict(item)
        rebound["path"] = str(target)
        rebound["rebound_from_path"] = str(Path(str(item["path"])).absolute())
        rebound_details.append(rebound)

    sidecar: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "status": "PRIMARY_REBOUND_METADATA_ONLY",
        "source_request": {"path": str(source_request),
                            "file_sha256": file_sha(source_request, maximum=MAX_REQUEST_BYTES),
                            "canonical_sha256": request["sha256"]},
        "source_worktree": str(old), "primary_worktree": str(primary),
        "v26_index": {"old_path": str(v26.get("path")), "new_path": str(mapped_v26_path),
                       "canonical_sha256": v26.get("sha256"),
                       "file_sha256": v26_file, "bytes": int(mapped_v26_path.stat().st_size)},
        "case_detail_count": len(source_records), "case_details": source_records,
        "read_scope": {"bounded_json_only": True, "h5_opened": False, "bi4_opened": False,
                        "raw_arrays_opened": False, "jsonl_opened": False,
                        "solver_output_opened": False, "ledger_mutated": False},
        "claim_boundary": "path provenance rebound only; no physical equivalence, payload or qualification credit",
    }
    sidecar["sha256"] = canonical_sha(sidecar)

    rebound_request = copy.deepcopy(request)
    rebound_inputs = dict(source_inputs)
    rebound_v26 = dict(v26)
    rebound_v26["path"] = str(mapped_v26_path)
    rebound_v26["rebound_from_path"] = str(v26.get("path"))
    rebound_inputs["v26_index"] = rebound_v26
    rebound_inputs["v26_case_details"] = rebound_details
    rebound_request["source_inputs"] = rebound_inputs
    rebound_request["request_variant"] = "PRIMARY_SOURCE_REBOUND_V1"
    rebound_request["source_rebinding_sidecar"] = {
        "path": str(output / "effective-condition-v27-primary-rebinding-sidecar.json"),
        "sha256": sidecar["sha256"], "content_policy": "bounded path/SHA metadata only",
    }
    rebound_request["read_policy"] = dict(rebound_request.get("read_policy", {}))
    rebound_request["read_policy"]["original_worktree_fallback"] = "REJECT"
    rebound_request["sha256"] = canonical_sha(rebound_request)

    output.mkdir(parents=True, exist_ok=True)
    sidecar_path = output / "effective-condition-v27-primary-rebinding-sidecar.json"
    request_out = output / "effective-condition-metadata-request-v27-primary-rebound.json"
    if sidecar_path.exists() or request_out.exists():
        raise RebindError("refusing to overwrite rebind artifacts")
    sidecar_text = json.dumps(sidecar, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    request_text = json.dumps(rebound_request, indent=2, sort_keys=True, ensure_ascii=True) + "\n"
    sidecar_path.write_text(sidecar_text, encoding="utf-8")
    request_out.write_text(request_text, encoding="utf-8")
    return {"request": str(request_out), "request_file_sha256": hashlib.sha256(request_text.encode()).hexdigest(),
            "request_canonical_sha256": rebound_request["sha256"],
            "sidecar": str(sidecar_path), "sidecar_file_sha256": hashlib.sha256(sidecar_text.encode()).hexdigest(),
            "sidecar_canonical_sha256": sidecar["sha256"], "case_detail_count": len(source_records),
            "bytes_verified": sum(item["bytes"] for item in source_records),
            "payload_read": False, "ledger_mutated": False}


def validate_rebound_request(request_path: Path | str, sidecar_path: Path | str) -> dict[str, Any]:
    request_target = Path(request_path).expanduser().absolute()
    sidecar_target = Path(sidecar_path).expanduser().absolute()
    request = _without_observed(read_json(request_target, "rebound V27 request", maximum=MAX_REQUEST_BYTES))
    sidecar = _without_observed(read_json(sidecar_target, "V27 rebind sidecar", maximum=MAX_REQUEST_BYTES))
    if request.get("schema") != REQUEST_SCHEMA or request.get("request_variant") != "PRIMARY_SOURCE_REBOUND_V1":
        raise RebindError("rebound request schema/variant differs")
    if request.get("sha256") != canonical_sha(request):
        raise RebindError("rebound request canonical SHA differs")
    if sidecar.get("schema") != SIDECAR_SCHEMA or sidecar.get("sha256") != canonical_sha(sidecar):
        raise RebindError("rebind sidecar schema/canonical SHA differs")
    binding = request.get("source_rebinding_sidecar")
    if not isinstance(binding, Mapping) or Path(str(binding.get("path"))).absolute() != sidecar_target \
            or binding.get("sha256") != sidecar.get("sha256"):
        raise RebindError("request/sidecar binding differs")
    details = request.get("source_inputs", {}).get("v26_case_details")
    if not isinstance(details, list) or len(details) != MAX_CASE_COUNT or sidecar.get("case_detail_count") != MAX_CASE_COUNT:
        raise RebindError("rebound case-detail closure is incomplete")
    return {"schema": SIDECAR_SCHEMA, "status": sidecar.get("status"),
            "request": str(request_target), "sidecar": str(sidecar_target),
            "case_detail_count": len(details), "payload_read": False,
            "ledger_mutated": False}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build")
    build.add_argument("--request", type=Path, required=True)
    build.add_argument("--old-root", type=Path, required=True)
    build.add_argument("--primary-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    check = sub.add_parser("validate")
    check.add_argument("--request", type=Path, required=True)
    check.add_argument("--sidecar", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "build":
            result = rebind_v27_request(request_path=args.request, old_root=args.old_root,
                                        primary_root=args.primary_root, output_dir=args.output)
        else:
            result = validate_rebound_request(args.request, args.sidecar)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True))
        return 0
    except (RebindError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"V27 primary rebind: {error}", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
