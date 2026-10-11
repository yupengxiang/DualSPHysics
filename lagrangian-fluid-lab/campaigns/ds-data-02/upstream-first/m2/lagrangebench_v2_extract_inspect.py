#!/usr/bin/env python3
"""Extract and inspect a previously verified LagrangeBench archive.

This is a separate, opt-in fallback stage.  It performs no download and does
not alter the consumed v1 worker.  The archive is fully size/MD5 verified
before the existing worker's safe extraction utility is called; inspection
then uses the existing bounded raw loader.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

try:
    from . import lagrangebench_v2_loader as loader
    from . import lagrangebench_v2_worker as worker
except ImportError:  # direct execution by the parent runner
    _M2_ROOT = Path(__file__).resolve().parent
    if str(_M2_ROOT) not in sys.path:
        sys.path.insert(0, str(_M2_ROOT))
    import lagrangebench_v2_loader as loader
    import lagrangebench_v2_worker as worker


SCHEMA = "ds-data-02.lagrangebench-v2-extract-inspect-worker.v2"
DEFAULT_MAX_EXTRACT_BYTES = 5 * 1024**3
DEFAULT_MAX_WALL_SECONDS = 7200


class ExtractError(RuntimeError):
    """Raised when the verified archive cannot be safely extracted."""


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ExtractError(f"refusing to overwrite report: {path}")
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def run(args: argparse.Namespace) -> dict[str, Any]:
    deadline = worker.Deadline(args.max_wall_seconds)
    archive = Path(args.archive)
    dataset_root = Path(args.dataset_root)
    if not archive.is_file() or archive.is_symlink():
        raise ExtractError(f"archive is not a regular file: {archive}")
    if dataset_root.exists() or dataset_root.is_symlink():
        raise ExtractError(f"dataset root must be fresh: {dataset_root}")
    # Reuse the consumed worker's deadline-aware pinned verification helper;
    # extraction begins only after the complete archive hash is confirmed.
    archive_result = worker._verify_existing_archive(archive, deadline)
    deadline.check()
    extraction = worker.extract_archive(
        archive,
        dataset_root,
        max_bytes=args.max_extract_bytes,
        deadline=deadline,
    )
    inspection = loader.inspect_dataset(dataset_root)
    deadline.check()
    report = {
        "schema": SCHEMA,
        "status": "completed",
        "mode": "extract_and_inspect_only",
        "source": loader.archive_spec(),
        "archive": archive_result,
        "extraction": extraction,
        "dataset_root": dataset_root.name,
        "inspection": inspection,
        "limits": {
            "max_extract_bytes": args.max_extract_bytes,
            "max_wall_seconds": args.max_wall_seconds,
        },
        "heavy_work": {
            "solver": False,
            "training": False,
            "archive_extraction": True,
            "conversion": True,
        },
    }
    _write_report(Path(args.report), report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--dataset-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-extract-bytes", type=int, default=DEFAULT_MAX_EXTRACT_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (OSError, ValueError, ExtractError, worker.WorkerError, loader.LagrangeBenchError) as exc:
        print(f"m2-extract-inspect: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
