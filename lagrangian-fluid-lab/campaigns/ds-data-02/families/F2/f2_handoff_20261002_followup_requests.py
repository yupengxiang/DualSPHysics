#!/usr/bin/env python3
"""Register conversion handoffs after an actual F2 solver receipt terminalizes.

This producer never launches a solver or converter.  It discovers only
completed solver receipts named on the command line, binds the actual staged
XML/BI4/motion and native output samples, and writes a CPU conversion request
with deferred v5/v6 label commands.  A label request is materialized only
after the conversion trajectory and receipt exist.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_ROOT = Path(__file__).parent
WORKTREE_ROOT = F2_ROOT.parents[4]
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DIRECT_CONVERTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
# Full-frame validation must use PartVTK_linux64.  PartVTKOut_linux64 is the
# native exclusion accounting tool and rejects the full Part_*.bi4 sequence.
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64")
PYTHON = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
V5_SCRIPT = F2_ROOT / "f2_handoff_20261002_event_semantics_v5.py"
V5_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v5/operator_manifest.json"
V6_SCRIPT = F2_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
V6_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
FOLLOWUP_SCRIPT = F2_ROOT / "f2_handoff_20261002_followup_requests.py"

LAUNCH_REQUESTS = {
    "CENTER_FINE_RETRY_V2": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/F2H10V2_CENTER_V1_FINE_RV4D1_BASELINE_SAVE001_request.json",
    "CENTER_MEDIUM_HALF_DT": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_temporal_launch_001/center_medium_half_native_dt_request.json",
    "OFFSET_FINE_RETRY_V2": INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/F2H10V2_OFFSET_V1_FINE_RV4D1_BASELINE_SAVE001_request.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path) -> Path:
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def binding(paths: list[Path]) -> dict[str, dict[str, str]]:
    return {str(path): {"path": str(path), "sha256": sha256(path)} for path in paths}


def completed_solver_receipt(case_id: str, launch: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    case_root = DATA_ROOT / "families/F2" / case_id
    candidates = []
    for path in sorted(case_root.glob("qualification-*/execution-receipt.json")):
        receipt = json.loads(path.read_text(encoding="utf-8"))
        if receipt.get("status") == "completed" and receipt.get("returncode", receipt.get("exit_code")) == 0:
            candidates.append((path, receipt))
    if not candidates:
        raise RuntimeError(f"no completed solver receipt for {case_id}")
    preferred = [item for item in candidates if "native-fullstate-v2" in item[0].parent.name]
    return (preferred or candidates)[-1]


def path_from_prefix(prefix: Path, suffix: str) -> Path:
    return require_file(prefix.with_suffix(suffix))


def old_case(case_id: str) -> str:
    return case_id.split("_RV4D1_", 1)[0]


def build_case(alias: str, output_dir: Path) -> Path:
    launch_path = require_file(LAUNCH_REQUESTS[alias])
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    case_id = str(launch["case_id"])
    solver_receipt_path, solver_receipt = completed_solver_receipt(case_id, launch)
    solver_output = Path(str(solver_receipt.get("output_root", ""))) / "solver_output"
    if not solver_output.is_dir():
        solver_output = Path(str(solver_receipt.get("output_root", "")))
    require_file(solver_output / "Run.out")
    require_file(solver_output / "Run.csv")
    require_file(solver_output / "RunPARTs.csv")
    data_root = solver_output / "data"
    if not data_root.is_dir():
        raise FileNotFoundError(data_root)
    data_frames = sorted(data_root.glob("Part_*.bi4"))
    if not data_frames:
        raise FileNotFoundError(f"native Part files missing under {data_root}")
    samples = [data_frames[0], data_frames[len(data_frames) // 2], data_frames[-1]]

    prefix = Path(str(launch["command"][1]))
    xml = path_from_prefix(prefix, ".xml")
    bi4 = path_from_prefix(prefix, ".bi4")
    motion_candidates = sorted(prefix.parent.glob("*_motion.dat"))
    if len(motion_candidates) != 1:
        raise RuntimeError(f"expected one copied motion file near {prefix}, found {motion_candidates}")
    motion = require_file(motion_candidates[0])
    owner = require_file(F2_ROOT / f"handoff_20261002/postsolver/owner_metadata/{old_case(case_id)}.generator.v2.metadata.json")
    gencase_receipt = require_file(Path(str(launch["gencase_receipt"])))
    token = case_id.lower()
    conversion_attempt = f"conversion-{token}-fullstate-followup-v1"
    attempt_root = DATA_ROOT / "families/F2" / case_id / conversion_attempt
    converted = attempt_root / "trajectory.h5"
    request_paths = [
        DIRECT_CONVERTER, DECODER, PARTVTK, owner, xml, bi4, motion,
        launch_path, solver_receipt_path, gencase_receipt,
        solver_output / "Run.out", solver_output / "Run.csv", solver_output / "RunPARTs.csv",
        *samples, F2_ROOT / "quality_contract.json", F2_ROOT / "event_definitions.json",
        F2_ROOT / "integration_save_plan.json", F2_ROOT / "case_registry.jsonl",
        V5_SCRIPT, V5_MANIFEST, V6_SCRIPT, V6_MANIFEST, FOLLOWUP_SCRIPT,
    ]
    request_paths = [require_file(path) for path in request_paths]
    numerical_hash = str(launch["numerical_recipe_hash"])
    physical_hash = str(launch["physical_condition_hash"])
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": conversion_attempt,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": [
            str(PYTHON), str(DIRECT_CONVERTER), "--data-root", str(data_root),
            "--generated-xml", str(xml), "--output", "{attempt_root}/trajectory.h5",
            "--report", "{attempt_root}/conversion-report.json", "--solver-log", str(solver_output / "Run.out"),
            "--solver-receipt", str(solver_receipt_path), "--gencase-receipt", str(gencase_receipt),
            "--owner-metadata", str(owner), "--decoder", str(DECODER), "--partvtk", str(PARTVTK),
            "--validation-dir", "{attempt_root}/partvtk-validation", "--keep-validation-csv",
        ],
        "cwd": str(WORKTREE_ROOT / "lagrangian-fluid-lab"),
        "max_wall_seconds": 1800 if "FINE" in case_id else 1200,
        "cpu_threads": 4,
        "estimated_storage_bytes": 100 * 1024**3 if "FINE" in case_id else 16 * 1024**3,
        "raw_output_root": str(DATA_ROOT / "families/F2"),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in request_paths],
        "source_bindings": binding(request_paths),
        "physical_condition_hash": physical_hash,
        "numerical_recipe_hash": numerical_hash,
        "generated_xml": {"path": str(xml), "sha256": sha256(xml)},
        "actual_source": {
            "solver_attempt": str(Path(str(solver_receipt.get("output_root", "")))),
            "solver_receipt": str(solver_receipt_path),
            "gencase_receipt": str(gencase_receipt),
            "data_root": str(data_root),
            "native_frame_count": len(data_frames),
            "native_frame_samples": [str(path) for path in samples],
            "solver_dimension": 3,
            "event_window_s": [0.0, 4.0],
        },
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "trajectory": str(converted),
            "conversion_report": str(attempt_root / "conversion-report.json"),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "request_note": "CPU-only direct conversion after a completed F2 solver receipt; v5/v6 observation and Q-N remain deferred.",
        "label_request_plan": {
            "requires_conversion_terminal": True,
            "trajectory": str(converted),
            "owner_metadata": str(owner),
            "definition_override": str(xml),
            "numerical_recipe_hash": numerical_hash,
            "case_id_override": case_id,
            "v5": [str(PYTHON), str(V5_SCRIPT), "observe", "--trajectory", str(converted), "--owner-metadata", str(owner), "--definition-override", str(xml), "--numerical-recipe-hash", numerical_hash, "--case-id-override", case_id, "--output", "{attempt_root}/f2-v5-labels.h5", "--report", "{attempt_root}/f2-v5-observations.json"],
            "v6": [str(PYTHON), str(V6_SCRIPT), "observe", "--trajectory", str(converted), "--owner-metadata", str(owner), "--definition-override", str(xml), "--numerical-recipe-hash", numerical_hash, "--case-id-override", case_id, "--output", "{attempt_root}/f2-v6-labels.h5", "--report", "{attempt_root}/f2-v6-observations.json"],
            "operator_hashes": {
                "v5": json.loads(V5_MANIFEST.read_text(encoding="utf-8"))["operator_sha256"],
                "v6": json.loads(V6_MANIFEST.read_text(encoding="utf-8"))["operator_sha256"],
            },
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"{case_id}_conversion_followup_request.json"
    path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--alias", action="append", choices=sorted(LAUNCH_REQUESTS), required=True)
    parser.add_argument("--output-dir", type=Path, default=F2_ROOT / "handoff_20261002/event_semantics_v6/followup_requests")
    args = parser.parse_args()
    for alias in args.alias:
        print(build_case(alias, args.output_dir.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
