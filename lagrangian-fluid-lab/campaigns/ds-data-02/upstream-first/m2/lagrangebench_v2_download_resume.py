#!/usr/bin/env python3
"""Download the pinned LagrangeBench archive with strict HTTP resume rules.

This is an opt-in fallback for a failed bounded download.  It does not extract
or inspect the archive and does not modify the consumed v1 worker.  A partial
archive is resumed only when the server returns HTTP 206 with an exact
``Content-Range`` and ``Content-Length`` for the remaining pinned bytes.  A
HTTP 200 response to a resume request is rejected before opening the partial
file, so it can never be appended accidentally.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

try:
    from . import lagrangebench_v2_loader as loader
except ImportError:  # direct execution by the parent runner
    _M2_ROOT = Path(__file__).resolve().parent
    if str(_M2_ROOT) not in sys.path:
        sys.path.insert(0, str(_M2_ROOT))
    import lagrangebench_v2_loader as loader


SCHEMA = "ds-data-02.lagrangebench-v2-download-resume-worker.v2"
CHUNK_BYTES = 8 * 1024 * 1024
DEFAULT_MAX_ARCHIVE_BYTES = 400 * 1024**2
DEFAULT_MAX_WALL_SECONDS = 3600
_CONTENT_RANGE = re.compile(r"^bytes (\d+)-(\d+)/(\d+)$")


class DownloadError(RuntimeError):
    """Raised when the pinned source or bounded transfer is invalid."""


class Deadline:
    def __init__(self, seconds: float) -> None:
        if seconds <= 0:
            raise DownloadError("max wall seconds must be positive")
        self.end = time.monotonic() + float(seconds)

    def check(self) -> None:
        if time.monotonic() >= self.end:
            raise DownloadError("bounded download wall-clock limit exceeded")


def _expected() -> dict[str, Any]:
    return loader.archive_spec()


def _md5(path: Path, deadline: Deadline) -> tuple[int, str]:
    digest = hashlib.md5(usedforsecurity=False)
    total = 0
    with path.open("rb") as stream:
        while True:
            deadline.check()
            block = stream.read(CHUNK_BYTES)
            if not block:
                break
            total += len(block)
            digest.update(block)
    return total, digest.hexdigest()


def _verify_archive(path: Path, deadline: Deadline) -> dict[str, Any]:
    expected = _expected()
    if not path.is_file() or path.is_symlink():
        raise DownloadError(f"archive is not a regular file: {path}")
    size, digest = _md5(path, deadline)
    expected_md5 = expected["md5"].split(":", 1)[1]
    if size != expected["bytes"] or digest != expected_md5:
        raise DownloadError(
            f"archive does not match pinned source: bytes={size}, md5={digest}; "
            f"expected {expected['bytes']}, {expected_md5}"
        )
    return {"bytes": size, "md5": f"md5:{digest}", "file_name": path.name}


def _seed_partial(
    source: Path,
    destination: Path,
    *,
    max_bytes: int,
    deadline: Deadline,
) -> int:
    """Copy an old worker's immutable partial into this attempt's partial."""

    if not source.is_file() or source.is_symlink():
        raise DownloadError(f"seed partial is not a regular file: {source}")
    size = source.stat().st_size
    if size > max_bytes or size > _expected()["bytes"]:
        raise DownloadError(f"seed partial exceeds the pinned archive bound: {size}")
    temporary = destination.with_name(destination.name + f".seed-{os.getpid()}")
    if temporary.exists() or temporary.is_symlink():
        raise DownloadError(f"stale seed partial exists: {temporary}")
    try:
        digest_bytes = 0
        with source.open("rb") as input_stream, temporary.open("xb") as output_stream:
            while True:
                deadline.check()
                block = input_stream.read(CHUNK_BYTES)
                if not block:
                    break
                digest_bytes += len(block)
                if digest_bytes > max_bytes:
                    raise DownloadError("seed partial exceeds max archive bytes")
                output_stream.write(block)
            output_stream.flush()
            os.fsync(output_stream.fileno())
        if digest_bytes != size:
            raise DownloadError("seed partial changed during copy")
        os.replace(temporary, destination)
        return digest_bytes
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _status(response: Any) -> int:
    value = getattr(response, "status", None)
    if value is None:
        value = response.getcode()
    return int(value)


def _header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    value = headers.get(name)
    return str(value) if value is not None else None


def _require_resume_headers(response: Any, *, offset: int, expected_bytes: int) -> int:
    """Validate the exact range before any append-mode open occurs."""

    if _status(response) != 206:
        raise DownloadError(
            "resume request was not answered with HTTP 206; refusing to append "
            f"status={_status(response)}"
        )
    content_range = _header(response, "Content-Range")
    match = _CONTENT_RANGE.fullmatch(content_range or "")
    if match is None:
        raise DownloadError(f"resume response lacks an exact Content-Range: {content_range!r}")
    start, end, total = (int(value) for value in match.groups())
    if start != offset or end != expected_bytes - 1 or total != expected_bytes:
        raise DownloadError(
            "resume Content-Range differs from the pinned source: "
            f"{content_range!r}; expected bytes {offset}-{expected_bytes - 1}/{expected_bytes}"
        )
    content_length = _header(response, "Content-Length")
    if content_length is None:
        raise DownloadError("resume response lacks Content-Length")
    try:
        advertised = int(content_length)
    except ValueError as exc:
        raise DownloadError(f"invalid resume Content-Length: {content_length!r}") from exc
    if advertised != expected_bytes - offset:
        raise DownloadError(
            f"resume Content-Length {advertised} != expected {expected_bytes - offset}"
        )
    return advertised


def download_archive(
    destination: Path,
    *,
    max_bytes: int,
    deadline: Deadline,
    url: str | None = None,
    seed_partial: Path | None = None,
) -> dict[str, Any]:
    """Download or resume one exact pinned archive and atomically publish it."""

    expected = _expected()
    source_url = url or expected["download_url"]
    if source_url != expected["download_url"]:
        raise DownloadError("fallback downloader is pinned to the exact archive URL")
    if max_bytes < expected["bytes"]:
        raise DownloadError("max archive bytes is below the pinned archive size")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        verified = _verify_archive(destination, deadline)
        return {"downloaded": False, "resumed": False, "reused": True, **verified}

    partial = destination.with_name(destination.name + ".partial")
    if partial.is_symlink():
        raise DownloadError(f"partial archive is a symlink: {partial}")
    seeded_bytes = 0
    if seed_partial is not None and not partial.exists():
        seeded_bytes = _seed_partial(
            seed_partial,
            partial,
            max_bytes=max_bytes,
            deadline=deadline,
        )
    offset = partial.stat().st_size if partial.exists() else 0
    if offset > expected["bytes"]:
        raise DownloadError(f"partial archive exceeds pinned size: {offset}")
    if offset == expected["bytes"]:
        verified = _verify_archive(partial, deadline)
        os.replace(partial, destination)
        return {"downloaded": False, "resumed": True, "reused": False, **verified}

    digest = hashlib.md5(usedforsecurity=False)
    if offset:
        with partial.open("rb") as prefix:
            while True:
                deadline.check()
                block = prefix.read(CHUNK_BYTES)
                if not block:
                    break
                digest.update(block)
    headers = {"User-Agent": "ds-data-02-m2-worker/2"}
    if offset:
        headers["Range"] = f"bytes={offset}-"
    request = urllib.request.Request(source_url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_status = _status(response)
            if offset:
                advertised = _require_resume_headers(
                    response,
                    offset=offset,
                    expected_bytes=expected["bytes"],
                )
                mode = "ab"
            else:
                if response_status != 200:
                    raise DownloadError(
                        f"initial archive request expected HTTP 200, got {response_status}"
                    )
                content_length = _header(response, "Content-Length")
                if content_length is not None:
                    try:
                        advertised = int(content_length)
                    except ValueError as exc:
                        raise DownloadError(f"invalid Content-Length: {content_length!r}") from exc
                    if advertised != expected["bytes"]:
                        raise DownloadError(
                            f"initial Content-Length {advertised} != expected {expected['bytes']}"
                        )
                else:
                    advertised = expected["bytes"]
                mode = "wb"
            with partial.open(mode) as target:
                total = offset
                received = 0
                while True:
                    deadline.check()
                    chunk = response.read(CHUNK_BYTES)
                    if not chunk:
                        break
                    received += len(chunk)
                    total += len(chunk)
                    if received > advertised or total > expected["bytes"] or total > max_bytes:
                        raise DownloadError("download exceeds the pinned archive bound")
                    target.write(chunk)
                    digest.update(chunk)
                if received != advertised or total != expected["bytes"]:
                    raise DownloadError(
                        f"download ended at {total} bytes; expected {expected['bytes']}"
                    )
                target.flush()
                os.fsync(target.fileno())
    except Exception:
        # Preserve the partial for a later bounded retry.  It is never treated
        # as a complete archive and a 200 resume response is rejected before
        # the append-mode file open above.
        raise

    actual = digest.hexdigest()
    expected_md5 = expected["md5"].split(":", 1)[1]
    if actual != expected_md5:
        raise DownloadError(
            f"download checksum mismatch: md5={actual}; expected {expected_md5}"
        )
    os.replace(partial, destination)
    return {
        "downloaded": True,
        "resumed": bool(offset),
        "seeded_partial": bool(seeded_bytes),
        "seeded_partial_bytes": seeded_bytes,
        "reused": False,
        "bytes": expected["bytes"],
        "md5": f"md5:{actual}",
        "file_name": destination.name,
    }


def _write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise DownloadError(f"refusing to overwrite report: {path}")
    partial = path.with_name(path.name + f".partial-{os.getpid()}")
    try:
        with partial.open("x", encoding="utf-8") as stream:
            json.dump(report, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(partial, path)
    except Exception:
        partial.unlink(missing_ok=True)
        raise


def run(args: argparse.Namespace) -> dict[str, Any]:
    deadline = Deadline(args.max_wall_seconds)
    archive = Path(args.archive)
    result = download_archive(
        archive,
        max_bytes=args.max_archive_bytes,
        deadline=deadline,
        seed_partial=args.seed_partial,
    )
    report = {
        "schema": SCHEMA,
        "status": "completed",
        "mode": "download_only",
        "source": loader.archive_spec(),
        "archive": result,
        "limits": {
            "max_archive_bytes": args.max_archive_bytes,
            "max_wall_seconds": args.max_wall_seconds,
        },
        "heavy_work": {
            "solver": False,
            "training": False,
            "extraction": False,
            "conversion": False,
        },
        "resume_contract": {
            "partial_suffix": ".partial",
            "resume_requires_http_status": 206,
            "resume_requires_exact_content_range": True,
            "resume_requires_exact_content_length": True,
            "http_200_on_resume_is_rejected": True,
        },
    }
    _write_report(Path(args.report), report)
    return report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument(
        "--seed-partial",
        type=Path,
        help="immutable partial from a failed prior attempt to copy before resuming",
    )
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--max-archive-bytes", type=int, default=DEFAULT_MAX_ARCHIVE_BYTES)
    parser.add_argument("--max-wall-seconds", type=float, default=DEFAULT_MAX_WALL_SECONDS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except (OSError, ValueError, DownloadError, loader.LagrangeBenchError) as exc:
        print(f"m2-download-resume: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
