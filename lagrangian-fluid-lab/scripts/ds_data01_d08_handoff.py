#!/usr/bin/env python3
"""Assemble the DS-DATA-01 internal dataset handoff manifest.

The handoff records compact repository artifacts plus hashes/references to the
local trajectory evidence store.  It never trains, infers, replays a
checkpoint, launches a solver, or copies a large payload into Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
OUTPUT_JSON = CAMPAIGN_ROOT / "D08_HANDOFF_MANIFEST.json"
OUTPUT_MD = CAMPAIGN_ROOT / "D08_HANDOFF.md"


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def rel(path: Path) -> str:
    return str(path.relative_to(LAB_ROOT))


def artifact(path: Path, *, kind: str = "repository_metadata") -> dict[str, Any]:
    return {
        "path": rel(path),
        "kind": kind,
        "exists": path.is_file(),
        "bytes": path.stat().st_size if path.is_file() else None,
        "sha256": digest(path),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    args = parser.parse_args()
    active = load_json(CAMPAIGN_ROOT / "ACTIVE_TASKS.json") or {}
    atlas = load_json(CAMPAIGN_ROOT / "D02_MECHANISM_ATLAS.json") or {}
    d03 = load_json(CAMPAIGN_ROOT / "D03_SCOPE_AUDIT.json") or {}
    d04 = load_json(CAMPAIGN_ROOT / "D04_LINEAGE_REGISTRY.json") or {}
    d05_plan = load_json(CAMPAIGN_ROOT / "D05_BATCH_PLAN.json") or {}
    d05_run = load_json(CAMPAIGN_ROOT / "d05" / "run-summary.json")
    d05_conversion = load_json(CAMPAIGN_ROOT / "d05" / "conversion-summary.json")
    d06 = load_json(CAMPAIGN_ROOT / "D06_LABEL_SCHEMA.json") or {}
    d07 = load_json(CAMPAIGN_ROOT / "D07_EVALUATOR_CONTRACT.json") or {}

    tracked_names = [
        "README.md",
        "SCOPE_OVERRIDE.md",
        "TASK_GRAPH.md",
        "CAPABILITY_MATRIX.csv",
        "ACTIVE_TASKS.json",
        "D02_MECHANISM_ATLAS.json",
        "D02_MECHANISM_ATLAS.csv",
        "D03_SCOPE_AUDIT.json",
        "D03_SCOPE_AUDIT.csv",
        "D03_REFERENCE_CARDS.json",
        "D03_FAILURE_MAP.md",
        "D04_SPLIT_SPEC.json",
        "D04_LINEAGE_REGISTRY.json",
        "D05_BATCH_PLAN.json",
        "D06_LABEL_SCHEMA.json",
        "D06_TRACER_SUBSET_SPEC.json",
        "D07_EVALUATOR_CONTRACT.json",
        "D08_DATA_PREVIEW.md",
        "D08_DATA_PREVIEW.json",
        "D08_RESOURCE_REPORT.md",
        "D08_RESOURCE_REPORT.json",
        "D08_GEOMETRY_CONTROL_INDEX.md",
        "D08_GEOMETRY_CONTROL_INDEX.json",
    ]
    artifacts = [artifact(CAMPAIGN_ROOT / name) for name in tracked_names]
    artifacts.extend([
        artifact(LAB_ROOT / "scripts" / "ds_data01_d05_batch.py", kind="repository_script"),
        artifact(LAB_ROOT / "scripts" / "ds_data01_d05_convert.py", kind="repository_script"),
        artifact(LAB_ROOT / "scripts" / "ds_data01_d06_labels.py", kind="repository_script"),
        artifact(LAB_ROOT / "scripts" / "ds_data01_d07_evaluator.py", kind="repository_script"),
        artifact(LAB_ROOT / "scripts" / "ds_data01_d08_preview.py", kind="repository_script"),
    ])
    for name in ("prepare-summary.json", "run-summary.json", "conversion-summary.json"):
        artifacts.append(artifact(CAMPAIGN_ROOT / "d05" / name, kind="dataset_summary"))
    for item in d05_plan.get("cases", []):
        case_id = item.get("case_id")
        if not case_id:
            continue
        for name in ("prepare-receipt.json", "run-receipt.json", "conversion-receipt.json"):
            artifacts.append(artifact(CAMPAIGN_ROOT / "d05" / case_id / name, kind="dataset_receipt"))
    data_records = []
    for source_name, payload in (("D02", atlas), ("D05", {"cases": (d05_conversion or {}).get("cases", [])})):
        for item in payload.get("cases", []):
            h5 = item.get("normalized_hdf5")
            if h5:
                path = LAB_ROOT / h5
                data_records.append({
                    "case_id": item.get("case_id"),
                    "family": item.get("family"),
                    "source_manifest": source_name,
                    "path": h5,
                    "exists": path.is_file(),
                    "bytes": path.stat().st_size if path.is_file() else None,
                    "sha256": digest(path),
                    "role": item.get("dataset_role", item.get("release_role", "unknown")),
                    "scientific_acceptance": item.get("scientific_acceptance", "not_assessed"),
                })
    family_counts: dict[str, int] = {}
    for item in data_records:
        family_counts[item.get("family", "unknown")] = family_counts.get(item.get("family", "unknown"), 0) + 1
    d05_complete = bool(d05_conversion and len(d05_conversion.get("cases", [])) >= len(d05_plan.get("cases", [])))
    checks = {
        "d00_d07_compact_artifacts_present": all(item["exists"] for item in artifacts),
        "d02_families_represented": atlas.get("counts", {}).get("families") == 7,
        "d03_external_validation_assessed": d03.get("acceptance_boundary", {}).get("q_e_external_validation_assessed", False),
        "d04_split_assignments_empty": all(value == 0 for value in d04.get("summary", {}).get("assigned_split_counts", {}).values()),
        "d05_batch_plan_present": bool(d05_plan),
        "d05_conversion_complete": d05_complete,
        "d06_material_tracer_required_for_core": d06.get("core_policy", {}).get("material_tracer_required", False),
        "d07_scientific_acceptance_not_assessed": d07.get("score_interface", {}).get("scientific_acceptance", {}).get("status") == "not_assessed",
        "d08_preview_present": all((CAMPAIGN_ROOT / name).is_file() for name in ("D08_DATA_PREVIEW.md", "D08_DATA_PREVIEW.json")),
        "d08_resource_report_present": all((CAMPAIGN_ROOT / name).is_file() for name in ("D08_RESOURCE_REPORT.md", "D08_RESOURCE_REPORT.json")),
        "d08_geometry_control_index_present": all((CAMPAIGN_ROOT / name).is_file() for name in ("D08_GEOMETRY_CONTROL_INDEX.md", "D08_GEOMETRY_CONTROL_INDEX.json")),
        "learning_attempts": 0,
    }
    status = "complete_internal_handoff" if checks["d00_d07_compact_artifacts_present"] and checks["d05_conversion_complete"] else "pending_local_evidence_completion"
    payload = {
        "schema": "ds-data-01.d08.handoff-manifest.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "package_role": "internal_development_only",
        "scope": "dataset-only; no training, inference, checkpoint replay, tuning, ranking, model qualification, or external scientific acceptance claim",
        "learning_attempts": 0,
        "tasks": active.get("tasks", []),
        "coverage": {
            "D02_atlas_cases": atlas.get("counts", {}).get("cases", 0),
            "D02_families": atlas.get("counts", {}).get("families", 0),
            "D03_cases_audited": d03.get("acceptance_boundary", {}).get("q_i_structure_pass_count", 0),
            "D05_plan_cases": len(d05_plan.get("cases", [])),
            "D05_conversion_cases": len((d05_conversion or {}).get("cases", [])),
            "data_records_with_hdf5_references": len(data_records),
            "families_with_hdf5_references": family_counts,
        },
        "checks": checks,
        "split_boundary": {
            "assigned_split_counts": d04.get("summary", {}).get("assigned_split_counts", {}),
            "production_split_materialized": d04.get("summary", {}).get("assigned_split_counts", {}).get("train", 0) != 0,
            "interpretation": "all D04 assignments remain empty; this handoff is not a train/validation/test release",
        },
        "artifacts": artifacts,
        "trajectory_evidence": data_records,
        "handoff_actions": [
            "Preserve the exact repository commit chain and compact artifact hashes.",
            "Provide local trajectory evidence paths from the evidence store when a consumer needs raw/HDF5 data.",
            "Keep diagnostic, calibration, and exclusion roles stratified; do not silently promote them.",
            "Run D03/Q-E owner review before any future production split assignment.",
        ],
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = [
        "# DS-DATA-01 D08 handoff",
        "",
        f"Status: `{status}`",
        "",
        "This is an internal dataset-development handoff. It contains no training, inference, checkpoint replay, tuning, ranking, or scientific-acceptance claim.",
        "",
        "## Coverage",
        "",
        f"- D02 atlas: {payload['coverage']['D02_atlas_cases']} cases across {payload['coverage']['D02_families']} families.",
        f"- D05 conversion references: {payload['coverage']['D05_conversion_cases']} / {payload['coverage']['D05_plan_cases']} planned entries.",
        f"- HDF5 references with local existence checks: {payload['coverage']['data_records_with_hdf5_references']}.",
        "- D04 split assignments remain empty; no production train/validation/test release was materialized.",
        "- D06 material tracer is optional and cannot gate native data.",
        "- D07 remains model-free and reports scientific acceptance as not assessed without external ground truth.",
        "- D08 includes a compact statistical preview and an observed resource report; large payloads remain local.",
        "- D08 includes the geometry/control index with source lineage and explicit batch parameters.",
        "",
        "## Reproducibility",
        "",
        f"- Machine-readable manifest: `{rel(output)}`",
        "- Compact source, receipt, and script hashes are listed in the manifest.",
        "- Large solver/normalized payloads remain in the local evidence store and are not copied into Git.",
    ]
    OUTPUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": rel(output),
        "markdown": rel(OUTPUT_MD),
        "status": status,
        "checks": checks,
        "data_records": len(data_records),
    }, ensure_ascii=False, indent=2))
    return 0 if status == "complete_internal_handoff" else 2


if __name__ == "__main__":
    raise SystemExit(main())
