#!/usr/bin/env python3
"""Build a directly runnable, source-only post-GenCase handoff.

This is an additive wrapper around the consumed V2 chain builder.  V2 emits
``{attempt_root}/...manifest.json`` command operands, but the shared runtime
does not materialize those template files.  V3 keeps the V2 manifests and
reports byte-for-byte as generated artifacts, then rewrites only the new
request documents so ``--manifest`` names the exact static manifest that the
parent has already bound and hashed.  No product payload is opened here.

The resulting request remains execution-disabled and carries no scientific
qualification.  A missing decoder, source closure, or terminal producer edge
is reported as WAITING by V2 and is never promoted by this adapter.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_three_sentinel_owner_grid_post_gencase_chain_v2.py"
JSON_CAP = 10 * 1024 * 1024
SCHEMA = "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain.v3"
PACKAGE_SCHEMA = "ds02.stage2.three-sentinel.owner-grid-post-gencase-chain-package.v3"


class ChainV3Failure(RuntimeError):
    pass


def _load_v2() -> Any:
    spec = importlib.util.spec_from_file_location("post_gencase_chain_v2_for_v3", V2_PATH)
    if spec is None or spec.loader is None:
        raise ChainV3Failure(f"cannot load consumed V2 chain: {V2_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()


def _abs(value: Path | str) -> Path:
    return Path(value).expanduser().absolute()


def _stat(path: Path) -> dict[str, int]:
    value = path.stat()
    return {"device": int(value.st_dev), "inode": int(value.st_ino),
            "bytes": int(value.st_size), "mtime_ns": int(value.st_mtime_ns),
            "ctime_ns": int(value.st_ctime_ns)}


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _json_record(path: Path, label: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _abs(path)
    if path.is_symlink() or not path.is_file():
        raise ChainV3Failure(f"{label} is not a regular non-symlink file: {path}")
    before = _stat(path)
    if before["bytes"] > JSON_CAP:
        raise ChainV3Failure(f"{label} exceeds the 10 MiB metadata cap: {path}")
    raw = path.read_bytes()
    after = _stat(path)
    if before != after:
        raise ChainV3Failure(f"{label} changed during bounded read: {path}")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ChainV3Failure(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ChainV3Failure(f"{label} is not an object")
    return value, {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
                   "stat": after, "payload_read_by_builder": False,
                   "scope": "bounded_small_metadata"}


def _write_json(path: Path, value: dict[str, Any], label: str) -> dict[str, Any]:
    path = _abs(path)
    raw = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True,
                      allow_nan=False) + "\n").encode("utf-8")
    if len(raw) > JSON_CAP:
        raise ChainV3Failure(f"{label} exceeds the 10 MiB metadata cap")
    temporary = path.with_name(f".{path.name}.{__import__('os').getpid()}.v3tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    stat = _stat(path)
    return {"path": str(path), "sha256": _sha(raw), "bytes": len(raw),
            "stat": stat, "payload_read_by_builder": False,
            "scope": "builder_output_metadata"}


def _direct_request(request_path: Path, label: str) -> dict[str, Any]:
    """Replace only the manifest operand and rebind the request record."""
    request, _ = _json_record(request_path, label)
    command = request.get("command")
    if not isinstance(command, list) or "--manifest" not in command:
        raise ChainV3Failure(f"{label} has no --manifest command operand")
    manifest_ref = request.get("manifest")
    if not isinstance(manifest_ref, dict) or not isinstance(manifest_ref.get("path"), str):
        raise ChainV3Failure(f"{label} has no bound manifest path")
    manifest_path = _abs(manifest_ref["path"])
    _, manifest_record = _json_record(manifest_path, f"{label} manifest")
    index = command.index("--manifest")
    if index + 1 >= len(command):
        raise ChainV3Failure(f"{label} has an incomplete --manifest operand")
    command[index + 1] = str(manifest_path)
    request["command"] = command
    request["variant_schema"] = SCHEMA
    request["runtime_manifest_binding"] = {
        "mode": "DIRECT_STATIC_PATH",
        "path": str(manifest_path),
        "sha256": manifest_record["sha256"],
        "stat": manifest_record["stat"],
        "parent_must_bind_before_reservation": True,
        "attempt_root_manifest_materialization": False,
    }
    records = request.get("input_records")
    if not isinstance(records, dict) or str(manifest_path) not in records:
        raise ChainV3Failure(f"{label} manifest is not an input record")
    input_record = records[str(manifest_path)]
    if not isinstance(input_record, dict) or input_record.get("sha256") != manifest_record["sha256"]:
        raise ChainV3Failure(f"{label} manifest input record is stale")
    request["input_sha256"] = {
        str(path): record.get("sha256")
        for path, record in records.items()
        if isinstance(record, dict) and isinstance(record.get("sha256"), str)
    }
    _write_json(request_path, request, f"{label} direct-manifest request")
    return request


def _replace_record(records: list[Any], replacement: dict[str, Any]) -> list[Any]:
    path = replacement.get("path")
    out: list[Any] = []
    replaced = False
    for item in records:
        if isinstance(item, dict) and item.get("path") == path:
            out.append(replacement)
            replaced = True
        else:
            out.append(item)
    if not replaced:
        out.append(replacement)
    return out


def _patch_package(package_path: Path, request_records: dict[str, dict[str, Any]]) -> dict[str, Any]:
    package, _ = _json_record(package_path, "V2 chain package")
    package["schema"] = PACKAGE_SCHEMA
    package["variant_schema"] = SCHEMA
    package["runtime_manifest_binding"] = "DIRECT_STATIC_PATH"
    package["execution_allowed"] = False
    package["launch_disabled"] = True
    package["scientific_credit"] = 0
    package["payload_read_by_builder"] = False
    for stage in ("native_header", "initial_support"):
        request = package.get(stage, {}).get("request")
        if isinstance(request, dict) and request.get("path") in request_records:
            package[stage]["request"] = request_records[request["path"]]
    for item in package.get("calibration", []):
        if not isinstance(item, dict):
            continue
        request = item.get("request")
        if isinstance(request, dict) and request.get("path") in request_records:
            item["request"] = request_records[request["path"]]
    source_records = package.get("source_records")
    if isinstance(source_records, list):
        for path, record in request_records.items():
            source_records = _replace_record(source_records, record)
        package["source_records"] = source_records
    _write_json(package_path, package, "V3 chain package")
    package, package_record = _json_record(package_path, "V3 chain package")
    return {"value": package, "record": package_record}


def build(product_map: Path, output_dir: Path, *, decoder: Path | None = None) -> dict[str, Any]:
    output_dir = _abs(output_dir)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ChainV3Failure(f"refusing nonempty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    # V2 writes the nine-row edge, source closure, and all child manifests.
    # This is a new output namespace; the consumed V2 source and any previous
    # V2 output are never edited.
    result = V2.build(_abs(product_map), output_dir, decoder=_abs(decoder) if decoder else None)
    request_paths: list[Path] = [
        _abs(result["header_request"]), _abs(result["support_request"]),
        *( _abs(item["request"]["path"])
           for item in result.get("calibration", [])
           if isinstance(item, dict) and isinstance(item.get("request"), dict)
           and isinstance(item["request"].get("path"), str)),
    ]
    request_records: dict[str, dict[str, Any]] = {}
    request_values: dict[str, dict[str, Any]] = {}
    for request_path in request_paths:
        request_values[str(request_path)] = _direct_request(request_path, "post-GenCase V3 request")
        _, record = _json_record(request_path, "post-GenCase V3 request")
        request_records[str(request_path)] = record
    package_result = _patch_package(_abs(result["package"]), request_records)
    status = result.get("status")
    return {
        "status": status,
        "schema": SCHEMA,
        "package": str(result["package"]),
        "package_record": package_result["record"],
        "header_request": str(result["header_request"]),
        "support_request": str(result["support_request"]),
        "calibration": result.get("calibration", []),
        "request_records": request_records,
        "source_closure_missing": result.get("source_closure_missing", []),
        "validation_errors": result.get("validation_errors", []),
        "execution_allowed": False,
        "scientific_credit": 0,
    }


def _self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="post-gencase-chain-v3-") as td:
        root = Path(td)
        product_map = V2._fixture_map(root)
        result = build(product_map, root / "out")
        assert result["execution_allowed"] is False
        assert result["scientific_credit"] == 0
        for request_path in result["request_records"]:
            request, _ = _json_record(Path(request_path), "fixture V3 request")
            command = request["command"]
            index = command.index("--manifest")
            assert not str(command[index + 1]).startswith("{attempt_root}")
            assert Path(command[index + 1]).is_file()
            assert request["execution_allowed"] is False
        # A path replacement must not silently pass the bound SHA check.
        request_path = Path(result["header_request"])
        request, _ = _json_record(request_path, "fixture header request")
        request["input_records"][request["manifest"]["path"]]["sha256"] = "0" * 64
        _write_json(request_path, request, "tampered fixture request")
        try:
            _direct_request(request_path, "tampered fixture request")
        except ChainV3Failure:
            pass
        else:
            raise AssertionError("stale manifest SHA was accepted")
    print("PASS_POST_GENCASE_CHAIN_V3_DIRECT_STATIC_MANIFEST_FIXTURE")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--build", action="store_true")
    parser.add_argument("--product-map", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--decoder", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.self_test:
            _self_test()
            return 0
        if args.product_map is None or args.output_dir is None:
            parser.error("--build requires --product-map and --output-dir")
        result = build(args.product_map, args.output_dir, decoder=args.decoder)
        print(json.dumps({"status": result["status"], "schema": SCHEMA,
                          "package": result["package"],
                          "header_request": result["header_request"],
                          "support_request": result["support_request"],
                          "execution_allowed": False, "scientific_credit": 0}, sort_keys=True))
        return 0
    except (ChainV3Failure, V2.ChainFailure, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"WAITING_OR_REJECTED_POST_GENCASE_CHAIN_V3: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
