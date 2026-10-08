#!/usr/bin/env python3
"""Build a strict V10 request from the immutable V9/V8 request.

The only semantic forward is the source-bound root051 missing-scope contract.
The request remains V8-shaped so V10 can delegate identity, event, time,
mass-sum, path, and stat checks to V8/V9.  This builder reads only the small
request and producer report; it never opens the V16 JSON payload.
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
V10_CONSUMER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_consumer_v10.py"
V9_BUILDER = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_request_forward_v9.py"
REQUEST_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-consumer-request.v8"
PRODUCER_SCHEMA = "ds02.stage2.f2-s1-typed-label-only-report.v1"
ACCEPTED_MISSING_SCOPE = "initial_fluid_source_cohort_global; identity fate unknown"
ACCEPTED_SCOPE_SEMANTICS = (
    "initial denominator is already the frozen fluid mass; later missing mass "
    "remains in the unknown bucket and is never added"
)
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


class V10RequestError(RuntimeError):
    pass


def _load_v9_builder() -> Any:
    spec = importlib.util.spec_from_file_location("ds02_bound_fresh_v16_request_builder_v9_for_v10", V9_BUILDER)
    if spec is None or spec.loader is None:
        raise V10RequestError(f"cannot load V9 request builder: {V9_BUILDER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V9B = _load_v9_builder()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    return V9B._json(path, role)


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise V10RequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
    return target


def build_request(*, source_request: Path | str, producer_report: Path | str,
                  output: Path | str, consumer_script: Path | str | None = None,
                  output_root: Path | str | None = None) -> dict[str, Any]:
    source_path, source = _json(source_request, "source V9 request")
    if source.get("schema") != REQUEST_SCHEMA or source.get("sha256") != V9B.V9.V8.canonical_sha(source):
        raise V10RequestError("source request is not a canonical V8/V9 request")
    if source.get("status") not in {"READY_FOR_PARENT_GUARD", "PENDING_PARENT_IO_SLOT"}:
        raise V10RequestError("source request is not parent-ready")
    report_path, report = _json(producer_report, "root051 producer report")
    if report.get("schema") != PRODUCER_SCHEMA or report.get("sha256") != V9B.V9.V8.canonical_sha(report):
        raise V10RequestError("producer report is not canonical root051 producer v1")
    if report.get("model_invoked") is not False or report.get("cfd_invoked") is not False:
        raise V10RequestError("producer report is not model/CFD-free")
    typed_validation = report.get("typed_validation")
    if not isinstance(typed_validation, Mapping) or typed_validation.get("selected_particles") != 21114:
        raise V10RequestError("producer report does not bind the root051 21114-particle cohort")
    declared = V9B.V9._derive_producer_paths(report)
    result = dict(source)
    relocation = dict(result.get("relocation", {}))
    if output_root is not None:
        new_output_root = Path(output_root).expanduser().resolve()
        if new_output_root.exists():
            raise V10RequestError(f"fresh V10 output root already exists: {new_output_root}")
        relocation["output_root"] = str(new_output_root)
    if not relocation.get("output_root"):
        raise V10RequestError("V10 output_root is required")
    result["relocation"] = relocation
    report_sha = sha256_file(report_path)
    result["provenance_source_report"] = {
        "path": str(report_path), "sha256": report_sha,
        "schema": PRODUCER_SCHEMA, "content_read_during_build": True,
    }
    result["provenance_path_declarations"] = [
        {"path": path, "role": "typed_input_binding.provenance", "source": "producer_report"}
        for path in sorted(declared)
    ]
    scope_source = {"path": str(report_path), "sha256": report_sha, "schema": PRODUCER_SCHEMA}
    result["v10_mass_scope_contract"] = {
        "accepted_result_missing_scope": ACCEPTED_MISSING_SCOPE,
        "semantics": ACCEPTED_SCOPE_SEMANTICS,
        "source_report": scope_source,
        "later_missing_is_not_added_to_initial_denominator": True,
        "source_bound_only": True,
    }
    script = Path(consumer_script).expanduser().resolve() if consumer_script else V10_CONSUMER
    if not script.is_file() or script.is_symlink():
        raise V10RequestError(f"V10 consumer script is missing: {script}")
    result["v10_forward"] = {
        "schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v10-forward.v1",
        "source_request": {"path": str(source_path), "sha256": sha256_file(source_path),
                           "schema": REQUEST_SCHEMA},
        "consumer": {"path": str(script), "sha256": sha256_file(script),
                      "schema": "fresh_v16_proof_consumer_v10"},
        "delegates_to": {"v9_schema": "ds02.stage2.f2-fresh-v16-proof-consumer-v9-forward.v1",
                         "v8_schema": REQUEST_SCHEMA},
        "strict_mass_scope": True,
        "opens_declared_provenance": False,
        "original_path_fallback": "FORBIDDEN",
        "hdf5_or_bi4_content_read_during_build": False,
    }
    result["status"] = "READY_FOR_PARENT_GUARD"
    result["sha256"] = V9B.V9.V8.canonical_sha(result)
    target = _write_new(output, result)
    return {"schema": REQUEST_SCHEMA, "status": result["status"], "request": str(target),
            "sha256": result["sha256"], "source_request_sha256": sha256_file(source_path),
            "producer_report_sha256": report_sha, "consumer_sha256": sha256_file(script),
            "declared_provenance_paths": sorted(declared), "mass_scope": ACCEPTED_MISSING_SCOPE,
            "content_read_during_build": False, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


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
                              producer_report=args.producer_report, output=args.output,
                              output_root=args.output_root, consumer_script=args.consumer_script)
    except (V10RequestError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request V10: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
