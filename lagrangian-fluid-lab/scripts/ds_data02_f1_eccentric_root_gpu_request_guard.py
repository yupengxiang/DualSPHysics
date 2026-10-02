"""Validate the immutable input/prefix contract of an F1 ECC GPU request.

The solver receives a *prefix*, not the directory containing the generated
files.  This guard deliberately rejects a directory prefix and also rejects a
prefix whose ``.xml``/``.bi4`` siblings do not match the request's paths or
recorded SHA-256 values.  It is a prelaunch check only; it never invokes a
solver or changes an input artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


class RequestValidationError(ValueError):
    """Raised when a request cannot be safely passed to the solver."""

    def __init__(self, errors: list[str], report: Mapping[str, Any] | None = None) -> None:
        self.errors = list(errors)
        self.report = dict(report or {})
        super().__init__("; ".join(self.errors))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, field: str, errors: list[str]) -> Path | None:
    if not isinstance(value, str) or not value:
        errors.append(f"{field} must be a non-empty path string")
        return None
    return Path(value)


def validate_request(
    request: Mapping[str, Any] | str | Path,
    *,
    check_file_hashes: bool = True,
) -> dict[str, Any]:
    """Validate one request and return a JSON-serializable report.

    ``check_file_hashes`` can be disabled for a cheap structural check.  The
    default checks the generated XML and BI4 bytes as well as their entries in
    both request hash maps when those entries are present.
    """

    request_path: Path | None = None
    if isinstance(request, (str, Path)):
        request_path = Path(request)
        payload = json.loads(request_path.read_text(encoding="utf-8"))
    else:
        payload = dict(request)

    errors: list[str] = []
    command = payload.get("command")
    if not isinstance(command, list) or len(command) < 2:
        errors.append("command must contain solver executable and prefix")

    prefix = _path(payload.get("gencase_prefix"), "gencase_prefix", errors)
    generated_xml = _path(payload.get("gencase_xml"), "gencase_xml", errors)
    native_bi4 = _path(payload.get("gencase_bi4"), "gencase_bi4", errors)

    expected_xml: Path | None = None
    expected_bi4: Path | None = None
    if prefix is not None:
        expected_xml = prefix.with_suffix(".xml")
        expected_bi4 = prefix.with_suffix(".bi4")
        if prefix.is_dir():
            errors.append(f"gencase_prefix is a directory, not a file prefix: {prefix}")
        if isinstance(command, list) and len(command) >= 2 and command[1] != str(prefix):
            errors.append("command[1] does not equal gencase_prefix")
        if generated_xml is not None and generated_xml != expected_xml:
            errors.append(f"gencase_xml is not prefix + .xml: {generated_xml} != {expected_xml}")
        if native_bi4 is not None and native_bi4 != expected_bi4:
            errors.append(f"gencase_bi4 is not prefix + .bi4: {native_bi4} != {expected_bi4}")

    input_hashes = payload.get("input_sha256") or payload.get("input_hashes") or {}
    if not isinstance(input_hashes, dict):
        errors.append("input_sha256/input_hashes must be an object")
        input_hashes = {}
    native_hashes = payload.get("native_source_hashes") or {}
    if not isinstance(native_hashes, dict):
        errors.append("native_source_hashes must be an object")
        native_hashes = {}

    checked: dict[str, str] = {}
    for label, actual, native_key in (
        ("generated XML", generated_xml, "generated_xml"),
        ("native BI4", native_bi4, "bi4"),
    ):
        if actual is None:
            continue
        if not actual.is_file():
            errors.append(f"{label} is not a regular file: {actual}")
            continue
        if not check_file_hashes:
            continue
        actual_sha = _sha256(actual)
        checked[str(actual)] = actual_sha
        expected_values = {
            str(input_hashes[str(actual)])
            for key in (str(actual),)
            if key in input_hashes
        }
        if native_key in native_hashes:
            expected_values.add(str(native_hashes[native_key]))
        if expected_values and any(actual_sha != expected for expected in expected_values):
            errors.append(
                f"{label} SHA-256 mismatch for {actual}: actual={actual_sha}; "
                f"expected={sorted(expected_values)}"
            )

    report = {
        "schema": "ds02.f1.eccentric-thick-boundary.root-gpu-request-guard.v1",
        "request": str(request_path) if request_path is not None else None,
        "valid": not errors,
        "errors": errors,
        "command_prefix": command[1] if isinstance(command, list) and len(command) >= 2 else None,
        "gencase_prefix": str(prefix) if prefix is not None else None,
        "prefix_is_directory": bool(prefix is not None and prefix.is_dir()),
        "expected_prefix_siblings": {
            "xml": str(expected_xml) if expected_xml is not None else None,
            "bi4": str(expected_bi4) if expected_bi4 is not None else None,
        },
        "checked_sha256": checked,
        "solver_or_gpu_started": False,
    }
    if errors:
        raise RequestValidationError(errors, report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("request", type=Path, nargs="+")
    args = parser.parse_args(argv)
    failed = False
    for path in args.request:
        try:
            report = validate_request(path)
        except RequestValidationError as exc:
            report = exc.report
            failed = True
        print(json.dumps(report, indent=2, sort_keys=True))
    return 2 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
