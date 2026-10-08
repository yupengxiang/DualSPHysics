#!/usr/bin/env python3
"""Build an additive V9 proof request from an immutable V8 request.

Only small JSON metadata is read.  The V16 result is stat-checked by the
source V8 request but its 62 MB content is never read here.  The builder
derives the exact provenance-only path declarations from the root051 producer
report and rejects any caller-supplied or undeclared path.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from typing import Any, Mapping


SCRIPT = Path(__file__).resolve()
V9_CONSUMER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v9.py"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V9RequestError(RuntimeError):
    pass


def _load_v9() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_fresh_v16_consumer_v9_builder", V9_CONSUMER)
    if spec is None or spec.loader is None:
        raise V9RequestError("cannot load V9 consumer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9 = _load_v9()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = Path(path).expanduser().resolve()
    if not target.is_file() or target.is_symlink():
        raise V9RequestError(f"{role} is not a regular file: {target}")
    if target.stat().st_size > MAX_METADATA_BYTES:
        raise V9RequestError(f"{role} exceeds metadata-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V9RequestError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise V9RequestError(f"{role} must be an object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise V9RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False)
        stream.write("\n")
    return target


def build_request(*, source_request: Path | str, producer_report: Path | str,
                  output: Path | str, consumer_script: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _json(source_request, "source V8 request")
    if source.get("schema") != REQUEST_SCHEMA or source.get("sha256") != V9.V8.canonical_sha(source):
        raise V9RequestError("source request is not a canonical V8 request")
    if source.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise V9RequestError("source V8 request is not parent-ready")
    report_path, report = _json(producer_report, "typed-only producer report")
    if report.get("schema") != PRODUCER_SCHEMA or report.get("sha256") != V9.V8.canonical_sha(report):
        raise V9RequestError("producer report is not canonical")
    declared = V9._derive_producer_paths(report)
    result = dict(source)
    relocation = dict(result.get("relocation", {}))
    if output_root is not None:
        new_output_root = Path(output_root).expanduser().resolve()
        if new_output_root.exists():
            raise V9RequestError(f"fresh V9 output root already exists: {new_output_root}")
        relocation["output_root"] = str(new_output_root)
    if not relocation.get("output_root"):
        raise V9RequestError("V9 output_root is required")
    result["relocation"] = relocation
    result["provenance_source_report"] = {
        "path": str(report_path), "sha256": sha256_file(report_path),
        "schema": PRODUCER_SCHEMA, "content_read_during_build": True,
    }
    result["provenance_path_declarations"] = [
        {"path": path, "role": "typed_input_binding.provenance", "source": "producer_report"}
        for path in sorted(declared)
    ]
    script = Path(consumer_script).expanduser().resolve() if consumer_script else V9_CONSUMER
    if not script.is_file() or script.is_symlink():
        raise V9RequestError(f"V9 consumer script is missing: {script}")
    result["v9_forward"] = {
        "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v9-forward.v1",
        "source_request": {"path": str(source_path), "sha256": sha256_file(source_path),
                           "schema": REQUEST_SCHEMA},
        "consumer": {"path": str(script), "sha256": sha256_file(script),
                      "schema": "fresh_v16_proof_consumer_v9"},
        "strict_provenance": True,
        "declared_path_count": len(declared),
        "opens_declared_provenance": False,
        "original_path_fallback": "FORBIDDEN",
        "hdf5_or_bi4_content_read_during_build": False,
    }
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["sha256"] = V9.V8.canonical_sha(result)
    path = _write_new(output, result)
    return {"schema": REQUEST_SCHEMA, "status": result["status"],
            "request": str(path), "sha256": result["sha256"],
            "source_request_sha256": sha256_file(source_path),
            "producer_report_sha256": sha256_file(report_path),
            "consumer_sha256": sha256_file(script),
            "declared_provenance_paths": sorted(declared),
            "content_read_during_build": False,
            "hdf5_or_bi4_content_read": False, "qualification": dict(UNKNOWN)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-request", type=Path, required=True)
    parser.add_argument("--producer-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--consumer-script", type=Path)
    args = parser.parse_args(argv)
    try:
        value = build_request(source_request=args.source_request,
                              producer_report=args.producer_report,
                              output=args.output, output_root=args.output_root,
                              consumer_script=args.consumer_script)
    except (V9RequestError, OSError, TypeError, ValueError,
            json.JSONDecodeError) as error:
        print(f"fresh V16 proof request V9: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
