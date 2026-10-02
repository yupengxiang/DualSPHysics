#!/usr/bin/env python3
"""Freeze a compact CPU reader for the completed DP005 PartVTKOut exports."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
RUNTIME_V2 = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
PARTVTKOUT = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
SUMMARY_SCRIPT = F2_ROOT / "f2_handoff_20261002_dp005_native_summary_v3.py"
V1_SCRIPT = F2_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_v1.py"
V2_ROOT = DATA_ROOT / "families/F2/F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC/diagnostic-f2-dp005-repair01-native-exclusions-v2"
OUTPUT_DIR = F2_ROOT / "handoff_20261002/postsolver_v7/dp005_native_summary_v3"
MANIFEST = OUTPUT_DIR / "dp005_native_summary_v3_manifest.json"
REQUEST = OUTPUT_DIR / "dp005_native_summary_v3_request.json"
ATTEMPT_ID = "diagnostic-f2-dp005-repair01-native-summary-v3"
CASE_ID = "F2_COMM4_DP005_REPAIR01_NATIVE_EXCLUSION_DIAGNOSTIC"


def import_source() -> Any:
    path = F2_ROOT / "f2_handoff_20261002_dp005_native_diagnostic_request.py"
    spec = importlib.util.spec_from_file_location("f2_dp005_request_v2", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
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


def make_cases() -> list[dict[str, Any]]:
    source = import_source()
    cases: list[dict[str, Any]] = []
    for original in source.CASES:
        case = dict(original)
        case["rv4"] = dict(original["rv4"])
        case_id = str(case["case_id"])
        raw_root = V2_ROOT / "artifacts/partvtkout" / case_id
        case.update({
            "partvtkout_binary": PARTVTKOUT,
            "partvtkout_binary_sha256": sha256(require(PARTVTKOUT, "PartVTKOut binary")),
            "partvtkout_csv": raw_root / "excluded_particles.csv",
            "partvtkout_stats": raw_root / "excluded_particles_stats.csv",
            "partvtkout_log": raw_root / "excluded_particles.stdout.log",
            "v2_receipt": V2_ROOT / "execution-receipt.json",
        })
        cases.append(case)
    return cases


def make() -> tuple[Path, Path]:
    cases = make_cases()
    paths: list[Path] = [SUMMARY_SCRIPT, V1_SCRIPT, RUNTIME_V2, PARTVTKOUT, V2_ROOT / "execution-receipt.json"]
    for case in cases:
        paths.extend([
            case["generated_xml"], case["motion"], case["gencase_receipt"], case["solver_receipt"], case["runparts"],
            case["owner_metadata"], case["partvtkout_csv"], case["partvtkout_stats"], case["partvtkout_log"],
            case["rv4"]["generated_xml"], case["rv4"]["motion"], case["rv4"]["owner_metadata"], case["rv4"]["conversion_report"],
        ])
    paths = [require(path, "DP005 summary input") for path in paths]
    bindings = {str(path): {"path": str(path), "sha256": sha256(path)} for path in paths}
    manifest = {
        "schema": "ds-data-02.f2.dp005-native-summary-input.v1",
        "family_id": "F2",
        "diagnostic_id": "F2_DP005_NATIVE_EXCLUSION_SUMMARY_V3",
        "cases": cases,
        "raw_export_provenance": {
            "producer_attempt": "diagnostic-f2-dp005-repair01-native-exclusions-v2",
            "producer_receipt": str(V2_ROOT / "execution-receipt.json"),
            "official_binary": str(PARTVTKOUT),
            "raw_csv_is_consumed_immutable": True,
        },
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
        "command": [str(python), str(SUMMARY_SCRIPT), "--manifest", str(MANIFEST), "--output", "{attempt_root}/dp005-native-summary.json"],
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
        "request_note": "Read-only compact CPU summary of the two already completed official PartVTKOut exports. It preserves raw CSV/Stats provenance, joins Idp/PartOut/Motive/position to RunPARTs time, and measures DP005 versus RV4 geometry/control. No PartVTKOut rerun, solver, GPU, conversion, Q-I, Q-N, or production claim.",
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
