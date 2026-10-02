#!/usr/bin/env python3
"""Materialise the bounded F1 native-normal support repair candidate.

The existing F1 finite-center definition already has ``svshapes=true`` and
``distanceh=2.0``.  This additive preparation changes only the latter to the
requested ``distanceh=3.0``.  It refuses to overwrite either source or
candidate files and verifies that the byte delta is exactly the one declared
in the repair plan.  It does not run GenCase or any solver.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path
import resource
from typing import Any


OLD_TOKEN = b'<distanceh v="2.0" />'
NEW_TOKEN = b'<distanceh v="3.0" />'
SVSHAPES_TOKEN = b'<svshapes v="true" />'


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _rusage() -> dict[str, float]:
    self_usage = resource.getrusage(resource.RUSAGE_SELF)
    child_usage = resource.getrusage(resource.RUSAGE_CHILDREN)
    return {
        "self_user_seconds": float(self_usage.ru_utime),
        "self_system_seconds": float(self_usage.ru_stime),
        "children_user_seconds": float(child_usage.ru_utime),
        "children_system_seconds": float(child_usage.ru_stime),
        "combined_user_seconds": float(self_usage.ru_utime + child_usage.ru_utime),
        "combined_system_seconds": float(self_usage.ru_stime + child_usage.ru_stime),
        "max_rss_kib_self": float(self_usage.ru_maxrss),
        "max_rss_kib_children": float(child_usage.ru_maxrss),
    }


def prepare_definition(source: Path, output: Path) -> dict[str, Any]:
    """Write one new definition with the declared normal-support delta."""

    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    if output.exists():
        raise FileExistsError(f"refusing to overwrite candidate: {output}")
    source_bytes = source.read_bytes()
    if source_bytes.count(OLD_TOKEN) != 1:
        raise ValueError(
            "source must contain exactly one distanceh=2.0 token; "
            f"found {source_bytes.count(OLD_TOKEN)}"
        )
    if source_bytes.count(NEW_TOKEN):
        raise ValueError("source already contains the candidate distanceh=3.0 token")
    if source_bytes.count(SVSHAPES_TOKEN) != 1:
        raise ValueError("source must explicitly retain exactly one svshapes=true token")
    candidate_bytes = source_bytes.replace(OLD_TOKEN, NEW_TOKEN)
    expected_bytes = source_bytes.replace(OLD_TOKEN, NEW_TOKEN)
    if candidate_bytes != expected_bytes:
        raise AssertionError("candidate byte delta is not the declared replacement")
    if candidate_bytes.count(NEW_TOKEN) != 1 or candidate_bytes.count(OLD_TOKEN):
        raise AssertionError("candidate normal block does not match the declared delta")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(candidate_bytes)
    observed = output.read_bytes()
    if observed != candidate_bytes:
        raise AssertionError("candidate changed while being written")
    if sha256(source) != sha256_bytes(source_bytes):
        raise AssertionError("source changed during preparation")
    return {
        "source": str(source),
        "candidate": str(output),
        "source_sha256": sha256_bytes(source_bytes),
        "candidate_sha256": sha256_bytes(candidate_bytes),
        "source_distanceh": "2.0",
        "candidate_distanceh": "3.0",
        "source_svshapes": "true",
        "candidate_svshapes": "true",
        "byte_delta": {"replace_once": [OLD_TOKEN.decode(), NEW_TOKEN.decode()]},
        "source_unchanged": sha256(source) == sha256_bytes(source_bytes),
        "candidate_exists": output.is_file(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    before = _rusage()
    result = prepare_definition(args.source, args.output)
    result["resource_usage"] = {"before": before, "after": _rusage()}
    print(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
