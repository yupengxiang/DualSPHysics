#!/usr/bin/env python3
"""Build an additive v5-dispatch request from an immutable science request.

The source request remains untouched.  Existing CURRENT/HDF5/control/source
digests are carried verbatim as provenance; only the new v5 runner closure is
hashed locally and appended.  Mutable batch receipts and runtime batch
directories are rejected as inputs.  This builder performs stat checks only
for inherited large sources and never reads HDF5/BI4/CSV content.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "ds02.stage2.forward-science-request.v5"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
V5_ROLES = {
    "shared_dispatch_v5": "ds_data02_stage2_dispatch_v5.py",
    "shared_strict_dispatch_v5": "ds_data02_strict_dispatch_v5.py",
    "shared_runtime_v5": "ds_data02_runtime_v5.py",
    "shared_runtime_v2": "ds_data02_runtime_v2.py",
    "batch_runner_v5": "ds_data02_batch_runner_v5.py",
}


class ForwardRequestError(ValueError):
    pass


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, default=str).encode()).hexdigest()


def _load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise ForwardRequestError(f"cannot read source request: {path}: {error}") from error
    if not isinstance(value, dict):
        raise ForwardRequestError("source request must be a JSON object")
    return value


def _safe_identity(value: Any, role: str) -> str:
    if not isinstance(value, str) or not value or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-" for char in value):
        raise ForwardRequestError(f"{role} must be a safe nonempty identity")
    return value


def _source_digest_map(request: Mapping[str, Any]) -> dict[str, str]:
    values = request.get("input_sha256")
    if not isinstance(values, Mapping):
        raise ForwardRequestError("source request must carry immutable input_sha256 mapping")
    result: dict[str, str] = {}
    for path, digest in values.items():
        path_value = str(Path(str(path)).expanduser().resolve())
        if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ForwardRequestError(f"invalid inherited SHA for {path_value}")
        result[path_value] = digest
    return result


def build(source_request: Path | str, output: Path | str, *, shared_root: Path | str,
          attempt_id: str | None = None) -> dict[str, Any]:
    source_path = Path(source_request).expanduser().resolve()
    source = _load(source_path)
    for key in ("family_id", "case_id", "attempt_id", "input_files"):
        if key not in source:
            raise ForwardRequestError(f"source request lacks {key}")
    family = _safe_identity(source["family_id"], "family_id")
    case = _safe_identity(source["case_id"], "case_id")
    old_attempt = _safe_identity(source["attempt_id"], "attempt_id")
    digest_map = _source_digest_map(source)
    inherited_files = [str(Path(str(value)).expanduser().resolve()) for value in source["input_files"]]
    if len(set(inherited_files)) != len(inherited_files):
        raise ForwardRequestError("source input_files contains duplicate paths")
    for path in inherited_files:
        if path not in digest_map:
            raise ForwardRequestError(f"source input_files lacks immutable expected SHA: {path}")
        target = Path(path)
        if not target.is_file():
            raise ForwardRequestError(f"source input is missing: {target}")
        lowered = path.lower()
        if "runtime/batches" in lowered or "batch-receipt" in target.name.lower():
            raise ForwardRequestError(f"mutable batch receipt cannot be a scientific input: {target}")

    scripts = Path(shared_root).expanduser().resolve() / "lagrangian-fluid-lab" / "scripts"
    closure: list[dict[str, Any]] = []
    for role, filename in V5_ROLES.items():
        path = scripts / filename
        if not path.is_file():
            raise ForwardRequestError(f"v5 closure source is missing: {path}")
        stat = path.stat()
        digest = sha256_file(path)
        closure.append({"role": role, "path": str(path.resolve()), "bytes": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns, "sha256": digest,
                        "content_hash_status": "BUILDER_VERIFIED"})

    new_attempt = _safe_identity(attempt_id or f"{old_attempt}-forward-v5", "new attempt_id")
    forwarded = copy.deepcopy(source)
    forwarded["attempt_id"] = new_attempt
    forwarded["input_files"] = inherited_files + [item["path"] for item in closure]
    forwarded["input_sha256"] = dict(digest_map)
    for item in closure:
        forwarded["input_sha256"][item["path"]] = item["sha256"]
    forwarded["forward_runtime_note"] = (
        "Forward v5 shared dispatch/runtime; inherited CURRENT/control/HDF5 expected SHA values are immutable "
        "provenance. Mutable batch receipts are excluded; this request has a fresh attempt identity."
    )
    forwarded["forward_v5"] = {
        "schema": SCHEMA,
        "source_request_path": str(source_path),
        "source_request_sha256": sha256_file(source_path),
        "source_attempt_id": old_attempt,
        "new_attempt_id": new_attempt,
        "guard_closure": closure,
        "inherited_input_sha256_reused": True,
        "hdf5_bi4_csv_content_read_by_builder": False,
        "qualification": copy.deepcopy(UNKNOWN),
    }
    forwarded["qualification"] = copy.deepcopy(UNKNOWN)
    forwarded["model_invoked"] = False
    forwarded["cfd_invoked"] = False
    forwarded["sha256"] = canonical_sha(forwarded)
    target = Path(output).expanduser().resolve()
    if target.exists():
        raise ForwardRequestError(f"refusing to overwrite forwarded request: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(forwarded, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return forwarded


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-request", type=Path, required=True)
    parser.add_argument("--shared-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempt-id")
    args = parser.parse_args()
    try:
        value = build(args.source_request, args.output, shared_root=args.shared_root,
                      attempt_id=args.attempt_id)
    except (ForwardRequestError, OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps({"status": "READY_FOR_PARENT_V5", "attempt_id": value["attempt_id"],
                      "sha256": value["sha256"], "input_count": len(value["input_files"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

