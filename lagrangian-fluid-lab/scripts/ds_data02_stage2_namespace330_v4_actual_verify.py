#!/usr/bin/env python3
"""Independently verify a bounded namespace330 V4 metadata product.

The verifier checks the committed catalog/request and re-hashes only the
declared bounded metadata inputs.  It never follows case payload paths and it
does not infer mass, native credit, or qualification from aggregate fields.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
_SPEC = importlib.util.spec_from_file_location(
    "namespace330_scoped_v4_for_actual_verify",
    SCRIPT_DIR / "ds_data02_stage2_namespace330_scoped_v4.py",
)
if _SPEC is None or _SPEC.loader is None:  # pragma: no cover
    raise ImportError("namespace330 V4 source is unavailable")
_V4 = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_V4)


class Namespace330V4VerificationError(ValueError):
    """The product or one of its bounded metadata bindings is stale."""


def _sha(path: Path, *, maximum: int) -> str:
    if path.is_symlink() or not path.is_file():
        raise Namespace330V4VerificationError(f"source is not a regular file: {path}")
    if path.stat().st_size > maximum:
        raise Namespace330V4VerificationError(f"source exceeds metadata bound: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_namespace330_v4(output_dir: Path | str, *, expected_native_rows: int | None = None,
                           expected_request_id: str | None = None) -> dict[str, Any]:
    output = Path(output_dir).expanduser()
    loaded = _V4.load_namespace330_scoped_v4(output)
    catalog = _V4._read_json(output / "namespace330-scoped-v4-catalog.json", "V4 catalog")
    request = _V4._read_json(output / "namespace330-scoped-v4-source-request.json", "V4 request")
    rows = catalog.get("cases")
    if not isinstance(rows, list) or len(rows) != 336:
        raise Namespace330V4VerificationError("catalog does not contain exactly 336 cases")
    if request.get("status") != "READY_FOR_ROOT_SOURCE_METADATA_GUARD":
        raise Namespace330V4VerificationError("request is not a source metadata guard request")
    if expected_request_id is not None and request.get("request_id") != expected_request_id:
        raise Namespace330V4VerificationError("request id differs from expected actual scope")
    if catalog.get("qualification") != {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}:
        raise Namespace330V4VerificationError("qualification was promoted")
    summary = catalog.get("input_summary", {})
    native_summary = summary.get("native", {})
    if expected_native_rows is not None and native_summary.get("matching_case_rows") != expected_native_rows:
        raise Namespace330V4VerificationError("native exact-row count differs")
    if native_summary.get("unmatched_case_rows") or native_summary.get("unscoped_top_level_proofs"):
        raise Namespace330V4VerificationError("an aggregate/unmatched native row was attached")
    if summary.get("mass", {}).get("proof_count") != 0:
        raise Namespace330V4VerificationError("unexpected mass proof was attached to actual263 product")
    source_inputs = catalog.get("source_inputs")
    if not isinstance(source_inputs, list) or not source_inputs:
        raise Namespace330V4VerificationError("source_inputs is missing")
    checked = []
    for ref in source_inputs:
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
            raise Namespace330V4VerificationError("malformed source input reference")
        path = Path(ref["path"]).expanduser()
        observed = _sha(path, maximum=int(_V4.MAX_METADATA_BYTES))
        if observed != ref.get("file_sha256"):
            raise Namespace330V4VerificationError(f"source SHA changed: {path}")
        checked.append({"role": ref.get("role"), "path": str(path),
                        "file_sha256": observed, "bytes": int(path.stat().st_size)})
    current_binding = catalog.get("current_binding")
    if not isinstance(current_binding, Mapping) or current_binding.get("file_sha256") != next(
            (ref.get("file_sha256") for ref in source_inputs if ref.get("role") == "CURRENT336"), None):
        raise Namespace330V4VerificationError("CURRENT binding is not joined to source_inputs")
    return {
        "schema": "ds02.stage2.namespace330.scoped-proof-catalog.v4.independent-verification.v1",
        "status": "VERIFIED_METADATA_ONLY_ACTUAL263",
        "catalog_sha256": catalog.get("sha256"),
        "request_sha256": request.get("sha256"),
        "request_id": request.get("request_id"),
        "case_count": len(rows),
        "family_counts": catalog.get("family_counts"),
        "native_matching_case_rows": native_summary.get("matching_case_rows"),
        "mass_matching_case_rows": summary.get("mass", {}).get("matching_case_rows"),
        "qualification": catalog.get("qualification"),
        "source_inputs_checked": checked,
        "read_scope": {"small_metadata_only": True, "payload_opened": False,
                        "aggregate_fallback": False, "mass_credit": "UNKNOWN"},
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verification-output", type=Path)
    parser.add_argument("--expected-native-rows", type=int)
    parser.add_argument("--expected-request-id")
    args = parser.parse_args(argv)
    try:
        report = verify_namespace330_v4(args.output, expected_native_rows=args.expected_native_rows,
                                        expected_request_id=args.expected_request_id)
        if args.verification_output is not None:
            target = args.verification_output.expanduser()
            if target.exists() or target.is_symlink():
                raise Namespace330V4VerificationError(f"refusing to overwrite: {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(report, sort_keys=True))
    except (OSError, json.JSONDecodeError, Namespace330V4VerificationError, _V4.Namespace330ScopedV4Error) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
