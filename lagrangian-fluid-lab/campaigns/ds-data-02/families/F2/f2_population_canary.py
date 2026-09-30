#!/usr/bin/env python3
"""Materialize one isolated F2 GenCase population repair canary.

The consumed F2 reference definitions use ``dp | bound`` for both fixed
geometry and the three fluid boxes.  The native audit proved that boundary
face coverage is complete, but it also measured a positive lattice-volume
error in every resolution.  This utility changes only the GenCase shape mode
to ``actual | bound`` for a new diagnostic physical case.  It copies the
source motion file and binds all source hashes in a CPU-only runner request.

It never runs GenCase or DualSPHysics.  The generated canary is deliberately
outside the 48-case registry and cannot be used as a qualification or
production result.  A completed shared-runner receipt must be inspected
before deciding whether this is a valid repair.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


SCHEMA = "ds-data-02.f2.population-canary.v1"
FAMILY_ID = "F2"
SHAPE_MODE = "actual | bound"
GENCASE = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64")
WORKTREE = Path(__file__).resolve().parents[5]
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def canonical_control_geometry(xml_text: str) -> str:
    """Return XML with the shape-mode token removed for stable comparison."""
    normalized = xml_text.replace("<setshapemode>dp | bound</setshapemode>", "<setshapemode>{{SHAPE_MODE}}</setshapemode>")
    normalized = normalized.replace("<setshapemode>actual | bound</setshapemode>", "<setshapemode>{{SHAPE_MODE}}</setshapemode>")
    return re.sub(r'<file name="[^"]+_motion\.dat"\s*/>', '<file name="{MOTION_FILE}" />', normalized)


def materialize(*, source_xml: Path, source_motion: Path, output_dir: Path, case_id: str, physical_case_id: str) -> dict[str, Any]:
    source_xml = source_xml.resolve()
    source_motion = source_motion.resolve()
    output_dir = output_dir.resolve()
    if not source_xml.is_file() or not source_motion.is_file():
        raise FileNotFoundError("source XML and motion must both exist")
    source_text = source_xml.read_text(encoding="utf-8")
    old_token = "<setshapemode>dp | bound</setshapemode>"
    if source_text.count(old_token) != 1:
        raise ValueError(f"expected exactly one source shape-mode token, found {source_text.count(old_token)}")
    output_dir.mkdir(parents=True, exist_ok=True)
    motion_name = f"{case_id}_motion.dat"
    definition_path = output_dir / f"{case_id}_Def.xml"
    motion_path = output_dir / motion_name
    transformed = source_text.replace(old_token, f"<setshapemode>{SHAPE_MODE}</setshapemode>")
    transformed = transformed.replace(source_motion.name, motion_name)
    if source_motion.name in transformed:
        raise ValueError("source motion filename was not fully replaced")
    definition_path.write_text(transformed, encoding="utf-8")
    shutil.copyfile(source_motion, motion_path)
    source_shape_hash = hashlib.sha256(canonical_control_geometry(source_text).encode("utf-8")).hexdigest()
    canary_shape_hash = hashlib.sha256(canonical_control_geometry(transformed).encode("utf-8")).hexdigest()
    metadata = {
        "schema": SCHEMA,
        "family_id": FAMILY_ID,
        "status": "diagnostic_only_definition_not_gencase_run",
        "qualification_claim": "none",
        "production_claim": "none",
        "case_id": case_id,
        "physical_case_id": physical_case_id,
        "registry_role": "outside_F2_48_case_registry_new_scope_required",
        "repair_attempt": 1,
        "repair_hypothesis": "GenCase actual shape mode may avoid the measured fluid lattice-volume overpopulation while preserving continuous box dimensions.",
        "shape_mode_before": "dp | bound",
        "shape_mode_after": SHAPE_MODE,
        "geometry_and_control_change_scope": "shape_mode_only; XML bytes otherwise copied from immutable consumed reference",
        "source_definition": {"path": str(source_xml), "sha256": sha256(source_xml)},
        "source_motion": {"path": str(source_motion), "sha256": sha256(source_motion)},
        "definition": {"path": str(definition_path), "sha256": sha256(definition_path)},
        "motion": {"path": str(motion_path), "sha256": sha256(motion_path)},
        "continuous_geometry_control_hash_scope": "canonical XML bytes with shape-mode token replaced by {SHAPE_MODE}; motion bytes are separately bound",
        "source_geometry_control_hash": source_shape_hash,
        "canary_geometry_control_hash": canary_shape_hash,
        "solver_parameters_copied_without_change": True,
        "motion_copied_without_change": True,
        "created_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    metadata_path = output_dir / f"{case_id}.metadata.json"
    write_json(metadata_path, metadata)
    metadata["metadata"] = {"path": str(metadata_path), "sha256": sha256(metadata_path)}
    return metadata


def runner_request(*, metadata: dict[str, Any], output_dir: Path, attempt_id: str) -> dict[str, Any]:
    definition = Path(metadata["definition"]["path"]).resolve()
    motion = Path(metadata["motion"]["path"]).resolve()
    source_xml = Path(metadata["source_definition"]["path"]).resolve()
    source_motion = Path(metadata["source_motion"]["path"]).resolve()
    metadata_path = definition.with_name(f"{metadata['case_id']}.metadata.json")
    case_id = str(metadata["case_id"])
    prefix = definition.with_suffix("")
    request = {
        "schema": "ds-data-02.runner.request.v1",
        "family_id": FAMILY_ID,
        "case_id": case_id,
        "attempt_id": attempt_id,
        "kind": "cpu",
        "cpu_task_kind": "gencase",
        "cpu_threads": 4,
        "max_wall_seconds": 300,
        "estimated_storage_bytes": 256 * 1024 * 1024,
        "command": [str(GENCASE), str(prefix), f"{{attempt_root}}/{case_id}", "-save:all"],
        "cwd": str(definition.parent),
        "raw_output_root": str(output_dir.resolve()),
        "worktree_root": str(WORKTREE),
        "solver_launch_forbidden": True,
        "generation_status": "diagnostic_only_definition_written_not_gencase_run",
        "registry_role": "outside_F2_48_case_registry_new_scope_required",
        "input_files": [str(Path(__file__).resolve()), str(source_xml), str(source_motion), str(definition), str(motion), str(metadata_path)],
        "source_definition_sha256": metadata["source_definition"]["sha256"],
        "source_motion_sha256": metadata["source_motion"]["sha256"],
        "definition_sha256": metadata["definition"]["sha256"],
        "motion_sha256": metadata["motion"]["sha256"],
        "metadata_sha256": sha256(metadata_path),
        "request_note": "Shared runner CPU GenCase only; no solver launch; do not infer qualification or production from this canary.",
    }
    return request


def git_commit() -> str:
    try:
        return subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN_GIT_COMMIT"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("materialize")
    p.add_argument("--source-xml", type=Path, required=True)
    p.add_argument("--source-motion", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--case-id", required=True)
    p.add_argument("--physical-case-id", required=True)
    p = sub.add_parser("request")
    p.add_argument("--metadata", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--attempt-id", required=True)
    p.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "materialize":
        result = materialize(source_xml=args.source_xml, source_motion=args.source_motion, output_dir=args.output_dir, case_id=args.case_id, physical_case_id=args.physical_case_id)
        result["git_commit"] = git_commit()
        print(json.dumps({"status": "materialized", "definition": result["definition"], "metadata": result["metadata"], "git_commit": result["git_commit"]}, ensure_ascii=False, indent=2))
        return 0
    metadata = json.loads(args.metadata.read_text(encoding="utf-8"))
    request = runner_request(metadata=metadata, output_dir=args.output_dir, attempt_id=args.attempt_id)
    request["launch_commit"] = git_commit()
    write_json(args.output, request)
    print(json.dumps({"status": "request_written", "path": str(args.output.resolve()), "sha256": sha256(args.output), "attempt_id": args.attempt_id}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
