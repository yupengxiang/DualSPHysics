#!/usr/bin/env python3
"""Create the additive v6 pose/labels request for OFFSET coarse.

The request producer reads the completed v5-002 conversion audit and binds all
actual source hashes.  It only writes a request and a versioned owner sidecar;
it never runs labels, a converter, GenCase, or a solver.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET


F2_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = F2_ROOT.parents[4]
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CASE_ID = "F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001"
CASE_ROOT = DATA_ROOT / "families/F2" / CASE_ID
CONVERSION_ROOT = CASE_ROOT / "conversion-f2h10v2_offset_v1_coarse_rv4d1_baseline_save001-fullstate-v5-002"
SOLVER_RECEIPT = CASE_ROOT / "qualification-f2h10v2_offset_v1_coarse_rv4d1_baseline_save001-native-fullstate-v1/execution-receipt.json"
SOLVER_OUT = SOLVER_RECEIPT.parent / "solver_output"
GENCASE_RECEIPT = DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_COARSE/gencase-f2-f2h10v2-offset-coarse-20261002-002/execution-receipt.json"
GENERATED_XML = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261002/root_rv4_launch_001/staged_inputs/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001/F2H10V2_OFFSET_V1_COARSE_RV4D1_BASELINE_SAVE001.xml")
MOTION = GENERATED_XML.parent / "F2H10V2_OFFSET_V1_COARSE_motion.dat"
OWNER_SOURCE = F2_ROOT / "handoff_20261002/postsolver/owner_metadata/F2H10V2_OFFSET_V1_COARSE.generator.v2.metadata.json"
V6_SCRIPT = F2_ROOT / "f2_handoff_20261002_v6_labels.py"
V6_OPERATOR = F2_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
V6_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
POSE_HELPER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
RUNTIME_V2 = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
QUALITY_CONTRACT = F2_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = F2_ROOT / "event_definitions.json"
SAVE_PLAN = F2_ROOT / "integration_save_plan.json"
CASE_REGISTRY = F2_ROOT / "case_registry.jsonl"
AUDIT_SCRIPT = F2_ROOT / "f2_handoff_20261002_offset_coarse_audit.py"
DEFAULT_AUDIT = F2_ROOT / "handoff_20261002/postsolver_v7/offset_coarse_actual_audit.json"
OUTPUT_DIR = F2_ROOT / "handoff_20261002/postsolver_v7"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label}: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return value


def write(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(paths: list[Path]) -> dict[str, dict[str, str]]:
    return {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in paths}


def xml_parameters(path: Path) -> dict[str, str]:
    root = ET.parse(path).getroot()
    return {
        str(item.get("key")): str(item.get("value"))
        for item in root.findall(".//execution/parameters/parameter")
        if item.get("key") is not None
    }


def owner_metadata(report: dict[str, Any], out_dir: Path) -> Path:
    owner = load(OWNER_SOURCE, "OFFSET coarse source owner metadata")
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    numerical_hash = str(report["hash_scopes"]["numerical_parameters_sha256"])
    owner["schema"] = "ds-data-02.f2.gem-handoff-20261002.generator-v7-baseline"
    owner["case_id"] = CASE_ID
    owner["definition"] = {"path": str(GENERATED_XML), "sha256": sha256(GENERATED_XML)}
    owner["motion"] = {"path": str(MOTION), "sha256": sha256(MOTION)}
    owner["solver_parameters"] = xml_parameters(GENERATED_XML)
    owner["physical_condition_hash_declared"] = physical_hash
    owner["numerical_recipe_hash_declared"] = numerical_hash
    owner["numerical_view"] = {
        "variant_case_id": CASE_ID,
        "variant": "RV4D1_BASELINE_SAVE001",
        "physical_condition_hash": physical_hash,
        "source_owner_metadata": {"path": str(OWNER_SOURCE), "sha256": sha256(OWNER_SOURCE)},
        "scope": "RV4 repaired-domain baseline; exact offset physical/control binding is retained and numerical recipe is separate",
    }
    output = out_dir / "owner_metadata" / f"{CASE_ID}.generator.v7.metadata.json"
    write(output, owner)
    return output


def make_request(audit_path: Path, output_path: Path) -> dict[str, Any]:
    audit = load(audit_path, "OFFSET coarse actual audit")
    report_path = require(Path(str(audit["conversion"]["report"]["path"])), "OFFSET coarse conversion report")
    report = load(report_path, "OFFSET coarse conversion report")
    source_h5 = require(Path(str(audit["conversion"]["trajectory"]["path"])), "OFFSET coarse trajectory")
    conversion_receipt = require(Path(str(audit["conversion"]["receipt"]["path"])), "OFFSET coarse conversion receipt")
    solver_receipt = require(Path(str(audit["solver"]["receipt"]["path"])), "OFFSET coarse solver receipt")
    gencase_receipt = require(GENCASE_RECEIPT, "OFFSET coarse GenCase receipt")
    run_out = require(SOLVER_OUT / "Run.out", "OFFSET coarse Run.out")
    generated_xml = require(Path(str(report["source_provenance"]["generated_xml"]["path"])), "OFFSET coarse generated XML")
    motion = require(MOTION, "OFFSET coarse motion control")
    owner = owner_metadata(report, output_path.parent)
    owner_data = load(owner, "OFFSET coarse v7 owner metadata")
    numerical_hash = str(report["hash_scopes"]["numerical_parameters_sha256"])
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    attempt_id = "labels-f2h10v2-offset-v1-coarse-rv4d1-baseline-save001-event-semantics-v6-pose-v1"
    attempt_root = DATA_ROOT / "families/F2" / CASE_ID / attempt_id
    augmented = attempt_root / "trajectory-with-actual-pose.h5"
    labels = attempt_root / "f2-v6-labels.h5"
    observations = attempt_root / "f2-v6-observations.json"
    pose_report = attempt_root / "rigid-body-state.json"
    python = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
    input_paths = [
        Path(__file__), AUDIT_SCRIPT, V6_SCRIPT, V6_OPERATOR, V6_MANIFEST,
        POSE_HELPER, RUNTIME_V2, QUALITY_CONTRACT, EVENT_DEFINITIONS,
        SAVE_PLAN, CASE_REGISTRY, source_h5, audit_path, report_path,
        conversion_receipt, solver_receipt, gencase_receipt, generated_xml,
        motion, owner, run_out,
    ]
    input_paths = [require(path, "OFFSET coarse labels input") for path in input_paths]
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 8 * 1024**3,
        "command": [
            str(python), str(V6_SCRIPT), "run",
            "--source-trajectory", str(source_h5),
            "--augmented-trajectory", "{attempt_root}/trajectory-with-actual-pose.h5",
            "--owner-metadata", str(owner), "--generated-xml", str(generated_xml),
            "--motion-control", str(motion), "--run-out", str(run_out),
            "--conversion-report", str(report_path), "--solver-receipt", str(solver_receipt),
            "--gencase-receipt", str(gencase_receipt), "--conversion-receipt", str(conversion_receipt),
            "--numerical-recipe-hash", numerical_hash, "--case-id", CASE_ID,
            "--output", "{attempt_root}/f2-v6-labels.h5",
            "--report", "{attempt_root}/f2-v6-observations.json",
            "--pose-report", "{attempt_root}/rigid-body-state.json",
        ],
        "cwd": str(F2_ROOT),
        "raw_output_root": str(DATA_ROOT / "families/F2"),
        "worktree_root": str(WORKTREE_ROOT),
        "input_files": [str(path) for path in input_paths],
        "source_bindings": binding(input_paths),
        "source_h5": {"path": str(source_h5), "sha256": sha256(source_h5)},
        "actual_audit": {"path": str(audit_path), "sha256": sha256(audit_path)},
        "conversion_receipt": {"path": str(conversion_receipt), "sha256": sha256(conversion_receipt)},
        "conversion_report": {"path": str(report_path), "sha256": sha256(report_path)},
        "solver_receipt": {"path": str(solver_receipt), "sha256": sha256(solver_receipt)},
        "gencase_receipt": {"path": str(gencase_receipt), "sha256": sha256(gencase_receipt)},
        "generated_xml": {"path": str(generated_xml), "sha256": sha256(generated_xml)},
        "motion_control": {"path": str(motion), "sha256": sha256(motion)},
        "physical_condition_hash": physical_hash,
        "physical_binding_sha256": owner_data.get("physical_binding_sha256"),
        "numerical_recipe_hash": numerical_hash,
        "expected_outputs": {
            "receipt": str(attempt_root / "execution-receipt.json"),
            "augmented_trajectory": str(augmented),
            "pose_report": str(pose_report),
            "labels": str(labels),
            "observations": str(observations),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "status": "ready_for_root_shared_labels_after_conversion_terminal",
        "request_note": "CPU-only additive v6 pose and event labels from completed OFFSET coarse v5-002 full-state H5; source H5 remains immutable, saved Type=1 pose is fitted with frozen motion control, and Q-I/Q-N/production remain pending.",
        "qualification_claim": "none",
        "production_claim": "none",
    }
    write(output_path, request)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit", type=Path, default=DEFAULT_AUDIT)
    parser.add_argument("--request", type=Path, default=OUTPUT_DIR / "offset_coarse_v6_labels_request.json")
    args = parser.parse_args()
    request = make_request(args.audit.resolve(), args.request.resolve())
    print(json.dumps({"request": str(args.request.resolve()), "request_sha256": sha256(args.request.resolve()), "status": request["status"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
