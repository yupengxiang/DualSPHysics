#!/usr/bin/env python3
"""Validate that a current-bound typed evaluator consumes the rebind sidecar.

This is a JSON-only boundary check for the forward sidecar.  It does not run
the evaluator and does not open the V16 result.  A typed request may carry the
older conservative V1 CURRENT sidecar, but it is accepted here only when its
result SHA, actual CURRENT SHA, stale historical SHA, and case join agree with
the new source-rebind sidecar.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
SCHEMA = "ds02.stage2.f2-current-source-rebind-consumer.v1"
REBIND_SCHEMA = "ds02.stage2.f2-current-source-rebind.v1"
ACTUAL_CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
HISTORICAL_OVERLAY_SHA256 = "aabfb1e55e47df73276d2bfc053839bd2bce5792330a82a95ad561a6dcde2972"
MAX_JSON_BYTES = 8 * 1024 * 1024


class ConsumerRebindError(RuntimeError):
    pass


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                          ensure_ascii=True, allow_nan=False, default=str).encode()).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _file(value: Any, role: str) -> Path:
    if not isinstance(value, (str, Path)) or not str(value):
        raise ConsumerRebindError(f"{role} path is missing")
    path = Path(value).expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ConsumerRebindError(f"{role} is not a regular non-symlink file: {path}")
    return path


def _json(path: Path | str, role: str) -> tuple[Path, dict[str, Any]]:
    target = _file(path, role)
    if target.stat().st_size > MAX_JSON_BYTES:
        raise ConsumerRebindError(f"{role} exceeds the JSON-only bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ConsumerRebindError(f"cannot read {role}: {error}") from error
    if not isinstance(value, dict):
        raise ConsumerRebindError(f"{role} must be a JSON object")
    return target, value


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = Path(path).expanduser().resolve()
    if target.exists():
        raise ConsumerRebindError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def validate_request(*, typed_request: Path | str, rebind_sidecar: Path | str,
                     output: Path | str) -> dict[str, Any]:
    request_path, request = _json(typed_request, "current-bound typed evaluator request")
    sidecar_path, sidecar = _json(rebind_sidecar, "CURRENT source rebind sidecar")
    if sidecar.get("schema") != REBIND_SCHEMA or sidecar.get("sha256") != canonical_sha(sidecar):
        raise ConsumerRebindError("CURRENT source rebind sidecar schema/SHA differs")
    if sidecar.get("status") != "PASS_METADATA_ONLY_REBIND_ACTUAL_CURRENT_STALE_ALIAS_RECORDED":
        raise ConsumerRebindError("CURRENT source rebind sidecar is not conservative")
    actual = sidecar.get("actual_current", {})
    consumer = sidecar.get("consumer_binding", {})
    result = sidecar.get("result_header_rebind", {})
    binding = request.get("current_catalog_binding")
    forward = request.get("v2_current_forward")
    request_result = request.get("result")
    if not isinstance(binding, Mapping) or not isinstance(forward, Mapping) or not isinstance(request_result, Mapping):
        raise ConsumerRebindError("typed request lacks current binding, forward, or result metadata")
    if binding.get("current_catalog_sha256") != ACTUAL_CURRENT_SHA256:
        raise ConsumerRebindError("typed request current SHA is not actual CURRENT336")
    if binding.get("historical_result_current_catalog_sha256") != HISTORICAL_OVERLAY_SHA256:
        raise ConsumerRebindError("typed request stale SHA is not retained")
    if forward.get("actual_current_catalog_sha256") != ACTUAL_CURRENT_SHA256:
        raise ConsumerRebindError("typed request forward actual SHA differs")
    if forward.get("historical_result_current_catalog_sha256") != HISTORICAL_OVERLAY_SHA256:
        raise ConsumerRebindError("typed request forward stale SHA differs")
    if request_result.get("sha256") != result.get("result_sha256"):
        raise ConsumerRebindError("typed request result SHA differs from rebind sidecar")
    if request_result.get("bytes") != result.get("result_bytes"):
        raise ConsumerRebindError("typed request result bytes differ from rebind sidecar")
    if actual.get("sha256") != consumer.get("accepted_current_catalog_sha256"):
        raise ConsumerRebindError("rebind sidecar accepted SHA is inconsistent")
    if sidecar.get("source_case_rebind", {}).get("identity_exact") is not True:
        raise ConsumerRebindError("rebind sidecar does not prove exact case identity")
    value: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "PASS_JSON_ONLY_REBIND_CONSUMER_BOUND",
        "metadata_only": True,
        "typed_request": {"path": str(request_path), "sha256": sha256_file(request_path),
                           "schema": request.get("schema")},
        "rebind_sidecar": {"path": str(sidecar_path), "sha256": sha256_file(sidecar_path),
                            "schema": sidecar.get("schema")},
        "accepted_current_catalog_sha256": ACTUAL_CURRENT_SHA256,
        "historical_result_current_catalog_sha256": HISTORICAL_OVERLAY_SHA256,
        "result": {"sha256": result.get("result_sha256"), "bytes": result.get("result_bytes"),
                   "content_rehashed_by_this_check": False},
        "source_case_identity": sidecar.get("source_case_rebind", {}).get("identity"),
        "credit_boundary": {
            "current_source_rebind": "DEVELOPMENT_METADATA_ONLY",
            "label_array_values": "NOT_REOPENED",
            "portable_cold_replay": "NOT_CLAIMED",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "hdf5_bi4_raw_read": False,
        },
    }
    value["sha256"] = canonical_sha(value)
    target = _write_new(output, value)
    return {"status": value["status"], "consumer": str(target),
            "sha256": value["sha256"], "actual_current_catalog_sha256": ACTUAL_CURRENT_SHA256,
            "historical_overlay_sha256": HISTORICAL_OVERLAY_SHA256,
            "result_sha256": result.get("result_sha256"), "result_bytes": result.get("result_bytes"),
            "hdf5_bi4_raw_read": False}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--typed-request", type=Path, required=True)
    parser.add_argument("--rebind-sidecar", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        value = validate_request(typed_request=args.typed_request,
                                 rebind_sidecar=args.rebind_sidecar,
                                 output=args.output)
    except (ConsumerRebindError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        print(f"CURRENT source rebind consumer: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
