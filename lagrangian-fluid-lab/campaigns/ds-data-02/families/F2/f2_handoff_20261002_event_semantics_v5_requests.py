#!/usr/bin/env python3
"""Freeze CPU conversion handoffs for the four completed RV4 baseline views.

This producer only writes request JSON.  It never launches a converter or a
solver.  The requests bind the actual root RV4 solver receipts and staged
XML/BI4/motion bytes.  A follow-up command template runs the v5 observer after
the conversion H5 exists; the fine RV4 partial attempts are deliberately not
included.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
F2_ROOT = Path(__file__).parent
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
WORKTREE_ROOT = F2_ROOT.parents[4]
LAUNCH_ROOT = INTEGRATION_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001"
DIRECT_CONVERTER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_direct_convert.py"
DECODER = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/campaigns/l1-resume/artifacts/bi4_dump")
PARTVTK = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTKOut_linux64")
PYTHON = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
V5_SCRIPT = F2_ROOT / "f2_handoff_20261002_event_semantics_v5.py"
REQUEST_GENERATOR = F2_ROOT / "f2_handoff_20261002_event_semantics_v5_requests.py"
V5_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v5/operator_manifest.json"

VIEWS = (
    ("CENTER", "COARSE"),
    ("CENTER", "MEDIUM"),
    ("OFFSET", "COARSE"),
    ("OFFSET", "MEDIUM"),
)


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


def request_for(background: str, resolution: str) -> tuple[dict[str, Any], dict[str, Any]]:
    old_case = f"F2H10V2_{background}_V1_{resolution}"
    case_id = f"{old_case}_RV4D1_BASELINE_SAVE001"
    token = case_id.lower()
    launch_path = require_file(LAUNCH_ROOT / f"{case_id}_request.json")
    launch = json.loads(launch_path.read_text(encoding="utf-8"))
    staged = LAUNCH_ROOT / "staged_inputs" / case_id
    xml = require_file(staged / f"{case_id}.xml")
    bi4 = require_file(staged / f"{case_id}.bi4")
    motion = require_file(staged / f"F2H10V2_{background}_V1_{resolution}_motion.dat")
    solver_attempt = DATA_ROOT / "families/F2" / case_id / f"qualification-{token}-native-fullstate-v1"
    solver_output = require_file(solver_attempt / "solver_output/Run.out").parent
    data_root = solver_output / "data"
    if not data_root.is_dir():
        raise FileNotFoundError(data_root)
    solver_receipt = require_file(solver_attempt / "execution-receipt.json")
    gencase_receipt = require_file(Path(str(launch["gencase_receipt"])))
    owner = require_file(F2_ROOT / f"handoff_20261002/postsolver/owner_metadata/{old_case}.generator.v2.metadata.json")
    conversion_attempt = f"conversion-{token}-fullstate-v5-001"
    labels_attempt = f"labels-{token}-event-semantics-v5-001"
    attempt_root = DATA_ROOT / "families/F2" / case_id / conversion_attempt
    converted = attempt_root / "trajectory.h5"
    data_frames = sorted(data_root.glob("Part_*.bi4"))
    if not data_frames:
        raise FileNotFoundError(f"no native Part_*.bi4 frames under {data_root}")
    data_samples = [data_frames[0], data_frames[len(data_frames) // 2], data_frames[-1]]
    input_paths = [
        DIRECT_CONVERTER, DECODER, PARTVTK, owner, xml, bi4, motion,
        solver_receipt, gencase_receipt, solver_output / "Run.out",
        solver_output / "Run.csv", solver_output / "RunPARTs.csv",
        *data_samples,
        F2_ROOT / "quality_contract.json", F2_ROOT / "event_definitions.json",
        F2_ROOT / "integration_save_plan.json", F2_ROOT / "case_registry.jsonl",
        V5_SCRIPT, REQUEST_GENERATOR, V5_MANIFEST,
    ]
    input_paths = [require_file(path) for path in input_paths]
    physical_hash = str(launch["physical_condition_hash"])
    numerical_hash = str(launch["numerical_recipe_hash"])
    command = [
        str(PYTHON), str(DIRECT_CONVERTER),
        "--data-root", str(solver_output / "data"),
        "--generated-xml", str(xml),
        "--output", "{attempt_root}/trajectory.h5",
        "--report", "{attempt_root}/conversion-report.json",
        "--solver-log", str(solver_output / "Run.out"),
        "--solver-receipt", str(solver_receipt),
        "--gencase-receipt", str(gencase_receipt),
        "--owner-metadata", str(owner),
        "--decoder", str(DECODER),
        "--partvtk", str(PARTVTK),
        "--validation-dir", "{attempt_root}/partvtk-validation",
        "--keep-validation-csv",
    ]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": case_id,
        "attempt_id": conversion_attempt,
        "kind": "cpu",
        "cpu_task_kind": "conversion",
        "command": command,
        "cwd": str(F2_ROOT.parent.parent.parent.parent),
        "max_wall_seconds": 1200,
        "cpu_threads": 4,
        "estimated_storage_bytes": 12 * 1024**3 if resolution == "MEDIUM" else 8 * 1024**3,
        "raw_output_root": str(DATA_ROOT / "families/F2"),
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "physical_condition_hash": physical_hash,
        "numerical_recipe_hash": numerical_hash,
        "generated_xml": {"path": str(xml), "sha256": sha256(xml)},
        "actual_source": {
            "event_window_s": [0.0, 4.0],
            "solver_attempt": str(solver_attempt),
            "solver_receipt": str(solver_receipt),
            "gencase_receipt": str(gencase_receipt),
            "generated_prefix": str(xml.with_suffix("")),
            "data_root": str(data_root),
            "native_frame_count": len(data_frames),
            "native_frame_samples": [str(path) for path in data_samples],
            "solver_dimension": 3,
        },
        "input_files": [str(path) for path in input_paths],
        "worktree_root": str(WORKTREE_ROOT),
        "source_bindings": binding(input_paths),
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "trajectory": str(converted),
            "conversion_report": str(attempt_root / "conversion-report.json"),
        },
        "request_note": "CPU-only direct BI4 full-frame conversion for completed RV4 coarse/medium baseline; no solver/GPU/Q-I/Q-N claim.",
        "v5_label_followup": {
            "attempt_id": labels_attempt,
            "trajectory": str(converted),
            "owner_metadata": str(owner),
            "definition_override": str(xml),
            "numerical_recipe_hash": numerical_hash,
            "case_id_override": case_id,
            "command_template": [
                str(PYTHON), str(V5_SCRIPT), "observe",
                "--trajectory", str(converted), "--owner-metadata", str(owner),
                "--definition-override", str(xml),
                "--numerical-recipe-hash", numerical_hash,
                "--case-id-override", case_id,
                "--output", "{attempt_root}/f2-v5-labels.h5",
                "--report", "{attempt_root}/f2-v5-observations.json",
            ],
            "requires_conversion_terminal": True,
            "operator_sha256": json.loads(V5_MANIFEST.read_text(encoding="utf-8"))["operator_sha256"],
        },
    }
    return request, {"case_id": case_id, "conversion_request": request, "converted": str(converted)}


def build(output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for background, resolution in VIEWS:
        request, _ = request_for(background, resolution)
        path = output_dir / f"{request['case_id']}_conversion_request_v5.json"
        path.write_text(json.dumps(request, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=F2_ROOT / "handoff_20261002/event_semantics_v5/requests")
    args = parser.parse_args()
    for path in build(args.output_dir.resolve()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
