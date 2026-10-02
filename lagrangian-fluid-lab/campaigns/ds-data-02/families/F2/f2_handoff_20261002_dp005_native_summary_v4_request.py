#!/usr/bin/env python3
"""Freeze the typed-range additive wrapper request for DP005 evidence."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
V3_REQUEST_PRODUCER = F2_ROOT / "f2_handoff_20261002_dp005_native_summary_request.py"
V3_SCRIPT = F2_ROOT / "f2_handoff_20261002_dp005_native_summary_v3.py"
V4_SCRIPT = F2_ROOT / "f2_handoff_20261002_dp005_native_summary_v4.py"
RUNTIME_V2 = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
V2_ROOT = DATA_ROOT / "families/F2/F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC/diagnostic-f2-dp005-repair01-native-exclusions-v2"
OUTPUT_DIR = F2_ROOT / "handoff_20261002/postsolver_v7/dp005_native_summary_v4"
MANIFEST = OUTPUT_DIR / "dp005_native_summary_v4_manifest.json"
REQUEST = OUTPUT_DIR / "dp005_native_summary_v4_request.json"
ATTEMPT_ID = "diagnostic-f2-dp005-repair01-native-summary-v4"
CASE_ID = "F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC"


def import_v3_producer():
    spec = importlib.util.spec_from_file_location("f2_dp005_summary_request_v3", V3_REQUEST_PRODUCER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {V3_REQUEST_PRODUCER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value.resolve())
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def cases() -> list[dict[str, Any]]:
    source = import_v3_producer()
    return source.make_cases()


def make() -> tuple[Path, Path]:
    case_list = cases()
    paths: list[Path] = [V4_SCRIPT, V3_SCRIPT, V3_REQUEST_PRODUCER, RUNTIME_V2, PARTVTKOUT, V2_ROOT / "execution-receipt.json"]
    for case in case_list:
        paths.extend([
            case["generated_xml"], case["motion"], case["gencase_receipt"], case["solver_receipt"], case["runparts"],
            case["owner_metadata"], case["partvtkout_csv"], case["partvtkout_stats"], case["partvtkout_log"],
            case["rv4"]["generated_xml"], case["rv4"]["motion"], case["rv4"]["owner_metadata"], case["rv4"]["conversion_report"],
        ])
    paths = [require(path, "DP005 typed summary input") for path in paths]
    bindings = {str(path): {"path": str(path), "sha256": sha256(path)} for path in paths}
    manifest = {
        "schema": "ds-data-02.f2.dp005-native-summary-input.v1",
        "family_id": "F2",
        "diagnostic_id": "F2_DP005_NATIVE_EXCLUSION_SUMMARY_V4_TYPED_RANGES",
        "cases": case_list,
        "raw_export_provenance": {
            "producer_attempt": "diagnostic-f2-dp005-repair01-native-exclusions-v2",
            "producer_receipt": str(V2_ROOT / "execution-receipt.json"),
            "official_binary": str(PARTVTKOUT),
            "raw_csv_is_consumed_immutable": True,
        },
        "typed_identity_rule": "fluid ranges are resolved from generated XML particles/fluid begin/count/mk entries, preserving each source layer mk",
        "source_bindings": bindings,
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write(MANIFEST, manifest)
    attempt_root = DATA_ROOT / "families/F2" / CASE_ID / ATTEMPT_ID
    python = F2_ROOT.parents[4] / "lagrangian-fluid-lab/.venv/bin/python"
    request_inputs = paths + [MANIFEST]
    request_bindings = {str(path): {"path": str(path), "sha256": sha256(path)} for path in request_inputs}
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 4,
        "max_wall_seconds": 600,
        "estimated_storage_bytes": 192 * 1024**2,
        "command": [str(python), str(V4_SCRIPT), "--manifest", str(MANIFEST), "--output", "{attempt_root}/dp005-native-summary.json"],
        "cwd": str(F2_ROOT),
        "raw_output_root": str(DATA_ROOT / "families/F2"),
        "worktree_root": str(F2_ROOT.parents[4]),
        "input_files": [str(path) for path in request_inputs],
        "source_bindings": request_bindings,
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "report": str(attempt_root / "dp005-native-summary.json"),
            "compact_records": str(attempt_root / "artifacts/records"),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "status": "ready_for_root_shared_cpu_summary",
        "request_note": "Read-only typed-range summary of immutable v2 official PartVTKOut exports. Fluid Idp ranges are resolved to source mk 1/2/3; geometry/control comparison and all unknown-spill semantics remain unchanged. No rerun, solver, GPU, conversion, Q-I, Q-N, or production claim.",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write(REQUEST, request)
    return MANIFEST, REQUEST


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--request", type=Path, default=REQUEST)
    args = parser.parse_args()
    manifest, request = make()
    if args.manifest.resolve() != manifest.resolve() or args.request.resolve() != request.resolve():
        write(args.manifest.resolve(), json.loads(manifest.read_text(encoding="utf-8")))
        write(args.request.resolve(), json.loads(request.read_text(encoding="utf-8")))
    print(json.dumps({"manifest": str(manifest), "manifest_sha256": sha256(manifest), "request": str(request), "request_sha256": sha256(request), "status": "ready_for_root_shared_cpu_summary"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
