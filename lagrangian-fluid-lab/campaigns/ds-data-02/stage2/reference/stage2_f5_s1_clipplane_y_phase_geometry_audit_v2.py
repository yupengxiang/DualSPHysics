#!/usr/bin/env python3
"""Forward geometry-only F5 Y-phase audit with safe immutable output.

This wrapper keeps the v1 arithmetic and source scope but fixes its optional
JSON output path.  The v1 writer removed its temporary file in ``finally``
before calling ``os.replace``; v2 writes and fsyncs the temporary file, then
replaces it only after the handle is closed.  No VTK, BI4, HDF5, GenCase or
solver payload is read or started.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


BASE_PATH = Path(__file__).with_name("stage2_f5_s1_clipplane_y_phase_geometry_audit_v1.py")
SCHEMA = "ds02.stage2.f5-s1.clipplane-y-phase-geometry-audit.v2"


def load_base() -> Any:
    spec = importlib.util.spec_from_file_location("stage2_f5_y_phase_geometry_v1", BASE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load geometry audit base: {BASE_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_immutable_json(path: Path, value: Any) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refuse to overwrite immutable report: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        with os.fdopen(fd, "wb") as handle:
            fd = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        if fd >= 0:
            os.close(fd)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def build_parser(base: Any) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--self-test", action="store_true")
    mode.add_argument("--audit", action="store_true")
    parser.add_argument("--source-def", type=Path, default=base.SOURCE_DEF_DEFAULT)
    parser.add_argument("--legacy-root", type=Path, default=base.LEGACY_ROOT_DEFAULT)
    parser.add_argument("--yhalf-root", type=Path, default=base.YHALF_ROOT_DEFAULT)
    parser.add_argument("--changes", type=Path, default=base.CHANGES_DEFAULT)
    parser.add_argument("--template", type=Path, default=base.TEMPLATE_DEFAULT)
    parser.add_argument("--output", type=Path)
    return parser


def self_test(base: Any) -> dict[str, Any]:
    result = dict(base.self_test())
    result["schema"] = SCHEMA
    # Exercise the previously untested output path without touching the
    # repository.  A successful replace proves that the temporary file is
    # still present after the file handle closes.
    import tempfile

    with tempfile.TemporaryDirectory(prefix="stage2-f5-y-phase-v2-") as directory:
        output = Path(directory) / "audit.json"
        write_immutable_json(output, {"schema": SCHEMA, "status": "SELF_TEST"})
        loaded = json.loads(output.read_text(encoding="utf-8"))
        if loaded.get("schema") != SCHEMA or loaded.get("status") != "SELF_TEST":
            raise AssertionError("immutable output self-test did not round-trip")
    result["immutable_output_writer"] = "PASS"
    return result


def main() -> int:
    base = load_base()
    args = build_parser(base).parse_args()
    if args.self_test:
        print(json.dumps(self_test(base), ensure_ascii=False, indent=2))
        return 0
    # Prevent v1 from entering its broken writer: make a shallow namespace
    # with output disabled, then write the v2 report atomically here.
    base_args = argparse.Namespace(**vars(args))
    base_args.output = None
    report = dict(base.audit(base_args))
    report["schema"] = SCHEMA
    if args.output is not None:
        output = args.output.expanduser().resolve()
        report["output"] = str(output)
        write_immutable_json(output, report)
    print(json.dumps({"status": report["status"], "schema": report["schema"], "grids": report["grids"], "output": report.get("output"), "gencase_started": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
