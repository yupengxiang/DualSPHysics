#!/usr/bin/env python3
"""Freeze the additive v6 labels request for the RV4 OFFSET medium H5.

The historical OFFSET medium owner sidecar predates the RV4 staged XML and
declares a stale physical-condition hash.  This producer writes a new
baseline sidecar whose XML, motion, conversion report, and H5 all bind to the
actual RV4 source.  It then writes a CPU-only request for the already consumed
v6 pose/event operator.  No source H5, solver output, or old request is
modified.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from typing import Any


F2_ROOT = Path(__file__).resolve().parent
WORKTREE_ROOT = F2_ROOT.parents[4]
INTEGRATION_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")

CASE_ID = "F2H10V2_OFFSET_V1_MEDIUM_RV4D1_BASELINE_SAVE001"
BASE_CASE_ID = "F2H10V2_OFFSET_V1_MEDIUM"
CASE_ROOT = DATA_ROOT / "families/F2" / CASE_ID
SOLVER_ROOT = CASE_ROOT / "qualification-f2h10v2_offset_v1_medium_rv4d1_baseline_save001-native-fullstate-v1"
CONVERSION_ROOT = CASE_ROOT / "conversion-f2h10v2_offset_v1_medium_rv4d1_baseline_save001-fullstate-v5-002"
GENCASE_ROOT = DATA_ROOT / "families/F2/F2H10V2_OFFSET_V1_MEDIUM/gencase-f2-f2h10v2-offset-medium-20261002-002"
STAGED_ROOT = INTEGRATION_ROOT / (
    "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/"
    "handoff_20261002/root_rv4_launch_001/staged_inputs/"
    f"{CASE_ID}"
)

OLD_OWNER = F2_ROOT / "handoff_20261002/postsolver/owner_metadata/F2H10V2_OFFSET_V1_MEDIUM.generator.v2.metadata.json"
OWNER = F2_ROOT / f"handoff_20261002/postsolver_v7/owner_metadata/{CASE_ID}.generator.v7.metadata.json"
REQUEST = F2_ROOT / "handoff_20261002/postsolver_v7/offset_medium_v6_labels_request.json"

V6_SCRIPT = F2_ROOT / "f2_handoff_20261002_v6_labels.py"
V6_OPERATOR = F2_ROOT / "f2_handoff_20261002_event_semantics_v6.py"
V6_MANIFEST = F2_ROOT / "handoff_20261002/event_semantics_v6/operator_manifest.json"
POSE_HELPER = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_convert.py"
RUNTIME_V2 = INTEGRATION_ROOT / "lagrangian-fluid-lab/scripts/ds_data02_runtime_v2.py"
QUALITY_CONTRACT = F2_ROOT / "quality_contract.json"
EVENT_DEFINITIONS = F2_ROOT / "event_definitions.json"
SAVE_PLAN = F2_ROOT / "integration_save_plan.json"
CASE_REGISTRY = F2_ROOT / "case_registry.jsonl"

XML = STAGED_ROOT / f"{CASE_ID}.xml"
MOTION = STAGED_ROOT / "F2H10V2_OFFSET_V1_MEDIUM_motion.dat"
TRAJECTORY = CONVERSION_ROOT / "trajectory.h5"
CONVERSION_REPORT = CONVERSION_ROOT / "conversion-report.json"
CONVERSION_RECEIPT = CONVERSION_ROOT / "execution-receipt.json"
SOLVER_RECEIPT = SOLVER_ROOT / "execution-receipt.json"
RUN_OUT = SOLVER_ROOT / "solver_output/Run.out"
GENCASE_RECEIPT = GENCASE_ROOT / "execution-receipt.json"

ATTEMPT_ID = "labels-f2h10v2-offset-v1-medium-rv4d1-baseline-save001-event-semantics-v6-pose-v2"
ATTEMPT_ROOT = CASE_ROOT / ATTEMPT_ID


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(path: Path, label: str) -> Path:
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(f"{label} is missing: {path}")
    return path


def load(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(require(path, label).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} is not an object: {path}")
    return value


def write(path: Path, value: Any, *, refuse_existing: bool = False) -> None:
    path = path.resolve()
    if refuse_existing and path.exists():
        raise FileExistsError(f"refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_or_verify(path: Path, value: Any) -> None:
    """Keep a previously frozen additive sidecar byte-stable."""
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    path = path.resolve()
    if path.exists():
        if path.read_text(encoding="utf-8") != encoded:
            raise FileExistsError(f"existing additive sidecar differs: {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(encoded, encoding="utf-8")


def binding(paths: list[Path]) -> dict[str, dict[str, str]]:
    return {str(path.resolve()): {"path": str(path.resolve()), "sha256": sha256(path)} for path in paths}


def make_owner() -> dict[str, Any]:
    owner = copy.deepcopy(load(OLD_OWNER, "historical OFFSET medium owner metadata"))
    report = load(CONVERSION_REPORT, "RV4 OFFSET medium conversion report")
    physical_hash = str(report["hash_scopes"]["physical_condition_sha256"])
    numerical_hash = str(report["hash_scopes"]["numerical_parameters_sha256"])
    owner["schema"] = "ds-data-02.f2.gem-handoff-20261002.generator-v7-rv4-baseline"
    owner["case_id"] = CASE_ID
    owner["definition"] = {"path": str(XML.resolve()), "sha256": sha256(XML)}
    owner["motion"] = {"path": str(MOTION.resolve()), "sha256": sha256(MOTION)}
    owner["physical_condition_hash_declared"] = physical_hash
    owner["physical_binding_sha256"] = physical_hash
    owner["numerical_recipe_hash_declared"] = numerical_hash
    owner["source_lineage"] = {
        "historical_owner_metadata": {"path": str(OLD_OWNER.resolve()), "sha256": sha256(OLD_OWNER)},
        "rv4_conversion_report": {"path": str(CONVERSION_REPORT.resolve()), "sha256": sha256(CONVERSION_REPORT)},
        "rv4_baseline_xml": {"path": str(XML.resolve()), "sha256": sha256(XML)},
        "rv4_baseline_motion": {"path": str(MOTION.resolve()), "sha256": sha256(MOTION)},
        "physical_hash_authority": "conversion-report.hash_scopes.physical_condition_sha256",
        "numerical_hash_authority": "conversion-report.hash_scopes.numerical_parameters_sha256",
    }
    return owner


def make_request() -> dict[str, Any]:
    owner = load(OWNER, "new RV4 OFFSET medium owner metadata")
    numerical_hash = str(owner["numerical_recipe_hash_declared"])
    python = WORKTREE_ROOT / "lagrangian-fluid-lab/.venv/bin/python"
    inputs = [
        Path(__file__), V6_SCRIPT, V6_OPERATOR, V6_MANIFEST, POSE_HELPER, RUNTIME_V2,
        QUALITY_CONTRACT, EVENT_DEFINITIONS, SAVE_PLAN, CASE_REGISTRY, OWNER,
        TRAJECTORY, XML, MOTION, RUN_OUT, CONVERSION_REPORT, CONVERSION_RECEIPT,
        SOLVER_RECEIPT, GENCASE_RECEIPT,
    ]
    inputs = [require(path, "OFFSET medium v6 request input") for path in inputs]
    output = ATTEMPT_ROOT / "f2-v6-labels.h5"
    report = ATTEMPT_ROOT / "f2-v6-observations.json"
    augmented = ATTEMPT_ROOT / "trajectory-with-actual-pose.h5"
    pose_report = ATTEMPT_ROOT / "rigid-body-state.json"
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": "F2",
        "case_id": CASE_ID,
        "attempt_id": ATTEMPT_ID,
        "kind": "cpu",
        "cpu_task_kind": "labels",
        "cpu_threads": 4,
        "max_wall_seconds": 1200,
        "estimated_storage_bytes": 8 * 1024**3,
        "command": [
            str(python), str(V6_SCRIPT), "run",
            "--source-trajectory", str(TRAJECTORY),
            "--augmented-trajectory", "{attempt_root}/trajectory-with-actual-pose.h5",
            "--owner-metadata", str(OWNER),
            "--generated-xml", str(XML),
            "--motion-control", str(MOTION),
            "--run-out", str(RUN_OUT),
            "--conversion-report", str(CONVERSION_REPORT),
            "--solver-receipt", str(SOLVER_RECEIPT),
            "--gencase-receipt", str(GENCASE_RECEIPT),
            "--conversion-receipt", str(CONVERSION_RECEIPT),
            "--numerical-recipe-hash", numerical_hash,
            "--case-id", CASE_ID,
            "--output", "{attempt_root}/f2-v6-labels.h5",
            "--report", "{attempt_root}/f2-v6-observations.json",
            "--pose-report", "{attempt_root}/rigid-body-state.json",
        ],
        "cwd": str(F2_ROOT.resolve()),
        "raw_output_root": str((DATA_ROOT / "families/F2").resolve()),
        "worktree_root": str(WORKTREE_ROOT.resolve()),
        "input_files": [str(path) for path in inputs],
        "source_bindings": binding(inputs),
        "source_h5": {"path": str(TRAJECTORY), "sha256": sha256(TRAJECTORY)},
        "generated_xml": {"path": str(XML), "sha256": sha256(XML)},
        "motion_control": {"path": str(MOTION), "sha256": sha256(MOTION)},
        "physical_condition_hash": str(owner["physical_condition_hash_declared"]),
        "numerical_recipe_hash": numerical_hash,
        "expected_outputs": {
            "receipt": str(ATTEMPT_ROOT / "execution-receipt.json"),
            "augmented_trajectory": str(augmented),
            "pose_report": str(pose_report),
            "labels": str(output),
            "observations": str(report),
        },
        "solver_launch_forbidden": True,
        "gpu_launch": {"family_owner_launch": False, "primary_process_gpu_only": True},
        "qualification_claim": "none",
        "production_claim": "none",
        "request_note": "CPU-only additive v6 pose/event labels from immutable RV4 OFFSET medium full-state H5; owner metadata uses actual staged XML/motion and conversion physical hash; Q-I/Q-N/production remain pending.",
    }
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the new owner metadata and request")
    args = parser.parse_args()
    for path in (OLD_OWNER, XML, MOTION, TRAJECTORY, CONVERSION_REPORT, CONVERSION_RECEIPT, SOLVER_RECEIPT, RUN_OUT, GENCASE_RECEIPT):
        require(path, "OFFSET medium v6 input")
    owner = make_owner()
    write_or_verify(OWNER, owner)
    request = make_request()
    write_or_verify(REQUEST, request)
    print(json.dumps({
        "owner": str(OWNER),
        "owner_sha256": sha256(OWNER),
        "request": str(REQUEST),
        "request_sha256": sha256(REQUEST),
        "physical_condition_hash": request["physical_condition_hash"],
        "numerical_recipe_hash": request["numerical_recipe_hash"],
        "status": "ready_for_root_shared_cpu_labels",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
