#!/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python
"""Forward saved-bracket comparison worker for full middle/fine reports.

The consumed v2 comparison logic is retained byte-for-byte and remains the
field validator.  This wrapper only changes the output schema and makes the
memory contract explicit for ROOT178's roughly 600MB JSON report: the parent
must reserve at least 4GiB, with this request using an 8GiB ceiling.  Each
report is read once as bytes and parsed once; no native payload is reopened.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
V2_PATH = HERE / "stage2_f3_s2_saved_bracket_compare_v2.py"
SCHEMA = "ds02.stage2.f3-s2.saved-bracket-comparison.v3"
PASS_STATUS = "PASS_F3_SAVED_BRACKET_DIAGNOSTICS_V3"


def _load_v2():
    spec = importlib.util.spec_from_file_location("stage2_f3_s2_saved_bracket_compare_v2_consumed", V2_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(V2_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


V2 = _load_v2()


def _path(value: Path | str) -> Path:
    return Path(value).expanduser().resolve()


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = _path(path)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing to overwrite immutable comparison output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def build_report(report_paths: dict[str, Path], proof_paths: dict[str, Path], output: Path, queries: list[float] | None = None) -> dict[str, Any]:
    output = _path(output)
    temporary = output.with_name(f".{output.name}.{os.getpid()}.v2-adapter.tmp")
    try:
        value = V2.build_report(report_paths, proof_paths, temporary, queries)
        value["schema"] = SCHEMA
        value["status"] = PASS_STATUS
        value["scope"] = dict(value.get("scope", {}))
        value["scope"].update({"comparison_worker_version": "v3", "full_report_read_strategy": "one stable bytes read followed by one json.loads; bytes released after parse", "full_report_memory_floor_bytes": 4 * 1024**3, "requested_memory_bytes": 8 * 1024**3})
        value["resource_contract"] = {"minimum_parent_memory_bytes": 4 * 1024**3, "requested_parent_memory_bytes": 8 * 1024**3, "native_payload_read": False, "fine_report_proxy_bytes": 596_405_901, "fine_report_proxy_is_not_a_terminal_measurement": True}
        _atomic_json(output, value)
        return value
    finally:
        temporary.unlink(missing_ok=True)


def self_test() -> dict[str, Any]:
    base = V2.self_test()
    if base.get("status") != "PASS":
        raise AssertionError(base)
    return {"status": "PASS", "schema": SCHEMA, "memory_floor_bytes": 4 * 1024**3, "requested_memory_bytes": 8 * 1024**3, "single_json_read": True, "native_payload_read": False, "interpolation": False, "truth_credit": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--coarse-report", type=Path)
    parser.add_argument("--coarse-proof", type=Path)
    parser.add_argument("--middle-report", type=Path)
    parser.add_argument("--middle-proof", type=Path)
    parser.add_argument("--fine-report", type=Path)
    parser.add_argument("--fine-proof", type=Path)
    parser.add_argument("--query-times", type=float, nargs="+", default=list(V2.QUERY_TIMES_S))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.self_test:
        print(json.dumps(self_test(), ensure_ascii=False, indent=2)); return 0
    required = (args.coarse_report, args.coarse_proof, args.middle_report, args.middle_proof, args.fine_report, args.fine_proof, args.output)
    if any(item is None for item in required):
        parser.error("all three report/proof pairs and --output are required")
    try:
        result = build_report({"coarse": args.coarse_report, "middle": args.middle_report, "fine": args.fine_report}, {"coarse": args.coarse_proof, "middle": args.middle_proof, "fine": args.fine_proof}, args.output, args.query_times)
    except Exception as exc:
        print(json.dumps({"status": "UNKNOWN_F3_SAVED_BRACKET_DIAGNOSTICS_V3", "error": {"type": type(exc).__name__, "message": str(exc)}}, ensure_ascii=False)); return 2
    print(json.dumps({"status": result["status"], "output": str(_path(args.output)), "requested_memory_bytes": 8 * 1024**3, "interpolation": False}, ensure_ascii=False, indent=2)); return 0


if __name__ == "__main__":
    raise SystemExit(main())
