#!/usr/bin/env python3
"""Archive Terra High's versioned static review binding for F8 R008 provenance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any

LAB = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LAB))

ROOT = Path("campaigns/core-v1/cfd/f8-oscillatory-pressure-channel-r008")
OUTPUT = LAB / ROOT / "per-case-provenance-implementation-review-v2/receipt.json"
SCHEMA = "core.cfd.f8.r008_per_case_provenance_implementation_review.v2"
RECORD_ID = "f8-r008-per-case-provenance-implementation-review-v2"
CODE_PATHS = {
    "safe_bi4_decoder": "scripts/f8_r008_safe_bi4_decoder_v1.py",
    "metadata_binding_api": "scripts/f8_r008_safe_bi4_metadata_binding_v1.py",
    "per_case_bundle_verifier": "scripts/f8_r008_per_case_bundle_verifier_v1.py",
}
REVIEWER = {
    "model": "gpt-5.6-terra",
    "reasoning_effort": "high",
    "agent_id": "01a0d24d-50f6-78a2-8ab3-8943a9e48cda",
    "verdict": "PASS",
    "review_mode": "read_only_static_implementation_review",
    "reviewer_ran_tests": False,
    "execution_or_evidence_mutation": False,
}
REVIEW_BOUNDARY = {
    "native_tools_invoked": False,
    "solver_or_worker_invoked": False,
    "gpu_or_queue_invoked": False,
    "production_evidence_mutated": False,
}


def _binding(relative_path: str) -> dict[str, Any]:
    path = LAB / relative_path
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError(f"review source must be a single-link regular file: {relative_path}")
        digest = hashlib.sha256()
        payload_bytes = 0
        while True:
            block = os.read(fd, 1024 * 1024)
            if not block:
                break
            payload_bytes += len(block)
            digest.update(block)
        after = os.fstat(fd)
        named = os.stat(path, follow_symlinks=False)
        identity = lambda st: (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns, st.st_ctime_ns, st.st_nlink)
        if identity(before) != identity(after) or identity(after) != identity(named):
            raise ValueError(f"review source changed while binding: {relative_path}")
        if payload_bytes != before.st_size:
            raise ValueError(f"review source byte count changed while binding: {relative_path}")
        return {"path": relative_path, "bytes": payload_bytes, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def build_receipt() -> dict[str, Any]:
    from scripts import f8_r008_per_case_bundle_verifier_v1 as verifier

    if verifier.CODE_REVIEW_SCHEMA != SCHEMA or verifier.CODE_REVIEW_RECORD_ID != RECORD_ID:
        raise ValueError("bundle verifier's versioned caller-trusted code-review contract changed")
    if verifier.CODE_REVIEW_FIELDS != {
        "schema", "record_id", "status", "reviewer", "code_bindings", "review_boundary",
    }:
        raise ValueError("bundle verifier's caller-trusted code-review fields changed")
    if verifier.CODE_SOURCE_PATHS != CODE_PATHS:
        raise ValueError("review source inventory differs from the verifier's D code-binding contract")
    return {
        "schema": SCHEMA,
        "record_id": RECORD_ID,
        "status": "PASS",
        "reviewer": REVIEWER,
        "code_bindings": {name: _binding(path) for name, path in CODE_PATHS.items()},
        "review_boundary": REVIEW_BOUNDARY,
    }


def verify_receipt(path: Path = OUTPUT) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if value != build_receipt():
        raise ValueError("immutable Terra High F8 R008 v2 implementation review no longer matches source bytes")
    return value


def write_receipt(path: Path = OUTPUT) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = LAB / target
    if target.exists() or target.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable F8 R008 v2 implementation review: {target}")
    payload = json.dumps(build_receipt(), indent=2, sort_keys=True, allow_nan=False) + "\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        target,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        0o644,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            target.unlink()
        except FileNotFoundError:
            pass
        raise
    return target


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the immutable Terra High review receipt once")
    arguments = parser.parse_args()
    if arguments.write:
        print(write_receipt().relative_to(LAB))
    else:
        print(json.dumps(build_receipt(), indent=2, sort_keys=True))
