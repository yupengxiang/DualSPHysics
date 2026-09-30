#!/usr/bin/env python3
"""Build compact DS-DATA-01 preview and resource reports.

The reports summarize manifests and filesystem metadata only.  They do not
load the large trajectory payloads, launch a solver, use a GPU, or infer
material lineage from numerical particle identity.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any


LAB_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = LAB_ROOT / "campaigns" / "ds-data-01"
D05_ROOT = CAMPAIGN_ROOT / "d05"
STATUS_PATH = CAMPAIGN_ROOT / "DATASET_STATUS.json"
ATLAS_PATH = CAMPAIGN_ROOT / "D02_MECHANISM_ATLAS.json"
D03_PATH = CAMPAIGN_ROOT / "D03_SCOPE_AUDIT.json"
D04_PATH = CAMPAIGN_ROOT / "D04_LINEAGE_REGISTRY.json"
D05_PLAN_PATH = CAMPAIGN_ROOT / "D05_BATCH_PLAN.json"
D05_RUN_PATH = D05_ROOT / "run-summary.json"
D05_CONVERSION_PATH = D05_ROOT / "conversion-summary.json"
PREVIEW_JSON = CAMPAIGN_ROOT / "D08_DATA_PREVIEW.json"
PREVIEW_MD = CAMPAIGN_ROOT / "D08_DATA_PREVIEW.md"
RESOURCE_JSON = CAMPAIGN_ROOT / "D08_RESOURCE_REPORT.json"
RESOURCE_MD = CAMPAIGN_ROOT / "D08_RESOURCE_REPORT.md"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def atomic_write(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def rel(path: Path) -> str:
    return str(path.relative_to(LAB_ROOT))


def path_bytes(path: Path) -> int | None:
    return path.stat().st_size if path.is_file() else None


def recursive_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def d02_preview(atlas: dict[str, Any]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in atlas.get("cases", []):
        grouped[str(item.get("family", "unknown"))].append(item)
    rows = []
    for family in sorted(grouped):
        cases = sorted(grouped[family], key=lambda item: str(item.get("case_id", "")))
        roles = Counter(str(item.get("dataset_role", item.get("status", "unknown"))) for item in cases)
        representative = cases[0]
        rows.append({
            "family": family,
            "case_count": len(cases),
            "role_counts": dict(sorted(roles.items())),
            "representative_case": representative.get("case_id"),
            "representative_mechanism": representative.get("mechanism"),
            "representative_dimension": representative.get("dimension"),
            "representative_hdf5": representative.get("normalized_hdf5"),
        })
    return rows


def d05_preview(plan: dict[str, Any], run_summary: dict[str, Any], conversion: dict[str, Any]) -> list[dict[str, Any]]:
    plan_by_id = {item.get("case_id"): item for item in plan.get("cases", [])}
    run_by_id = {item.get("case_id"): item for item in run_summary.get("cases", [])}
    rows = []
    for item in sorted(conversion.get("cases", []), key=lambda value: str(value.get("case_id", ""))):
        case_id = item.get("case_id")
        plan_item = plan_by_id.get(case_id, {})
        run_item = run_by_id.get(case_id, {})
        audit = item.get("audit", {})
        h5_value = item.get("normalized_hdf5")
        h5_path = LAB_ROOT / h5_value if h5_value else None
        rows.append({
            "case_id": case_id,
            "family": item.get("family", plan_item.get("family")),
            "mechanism": item.get("mechanism", plan_item.get("mechanism")),
            "release_role": item.get("release_role", plan_item.get("release_role", "internal_development_only")),
            "plan_role": plan_item.get("d04_role", plan_item.get("role")),
            "conversion_status": item.get("status", audit.get("status")),
            "scientific_acceptance": item.get("scientific_acceptance", "not_assessed"),
            "split": item.get("split", "unassigned"),
            "frames": audit.get("time_count"),
            "identity_count": audit.get("identity_count"),
            "active_initial": audit.get("active_initial"),
            "active_final": audit.get("active_final"),
            "identity_retention": audit.get("identity_retention"),
            "introduced_after_initial": audit.get("introduced_after_initial"),
            "initial_missing_at_final": audit.get("initial_missing_at_final"),
            "gpu": run_item.get("gpu"),
            "solver_elapsed_seconds": run_item.get("elapsed_seconds"),
            "raw_bytes": run_item.get("raw_bytes"),
            "normalized_hdf5": h5_value,
            "normalized_hdf5_bytes": path_bytes(h5_path) if h5_path else None,
        })
    return rows


def build_preview(atlas: dict[str, Any], d03: dict[str, Any], d04: dict[str, Any], plan: dict[str, Any], run_summary: dict[str, Any], conversion: dict[str, Any]) -> dict[str, Any]:
    d05_cases = d05_preview(plan, run_summary, conversion)
    return {
        "schema": "ds-data-01.d08.data-preview.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "package_role": "internal_development_only",
        "scope": "compact statistical preview; no scientific acceptance claim and no material-lineage inference",
        "coverage": {
            "D02_atlas_cases": atlas.get("counts", {}).get("cases", 0),
            "D02_families": atlas.get("counts", {}).get("families", 0),
            "D03_q_i_structure_pass": d03.get("acceptance_boundary", {}).get("q_i_structure_pass_count", 0),
            "D04_assigned_train": d04.get("summary", {}).get("assigned_split_counts", {}).get("train", 0),
            "D04_assigned_validation": d04.get("summary", {}).get("assigned_split_counts", {}).get("validation", 0),
            "D04_assigned_test": d04.get("summary", {}).get("assigned_split_counts", {}).get("test", 0),
            "D05_cases": len(d05_cases),
            "D05_q_i_structure_pass": sum(item.get("conversion_status") == "Q-I-structure-pass" for item in d05_cases),
        },
        "family_preview": d02_preview(atlas),
        "D05_case_preview": d05_cases,
        "interpretation": [
            "D05 records are internal development evidence and remain split=unassigned.",
            "Q-I structure pass checks finite active fields, increasing time, and positive active mass; it is not Q-E scientific validation.",
            "Numerical particle identity is not asserted to be material identity.",
            "Open lifecycle and missing-identity behavior remain visible in the per-case fields.",
        ],
    }


def build_resource(status: dict[str, Any], plan: dict[str, Any], run_summary: dict[str, Any], conversion: dict[str, Any]) -> dict[str, Any]:
    run_cases = run_summary.get("cases", [])
    conversion_cases = conversion.get("cases", [])
    gpu_assignments = {
        item.get("case_id"): item.get("gpu")
        for item in run_cases
        if item.get("status") == "completed"
    }
    process_counts = Counter(item.get("classification", "unknown") for item in status.get("processes", []))
    raw_bytes = sum(int(item.get("raw_bytes") or 0) for item in run_cases)
    csv_bytes = sum(recursive_bytes(D05_ROOT / str(item.get("case_id")) / "attempt-001" / "csv") for item in run_cases)
    hdf5_bytes = sum(
        path_bytes(LAB_ROOT / str(item.get("normalized_hdf5"))) or 0
        for item in conversion_cases
        if item.get("normalized_hdf5")
    )
    disk = shutil.disk_usage(CAMPAIGN_ROOT)
    return {
        "schema": "ds-data-01.d08.resource-report.v1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "observation_source": "DATASET_STATUS.json plus committed D05 run/conversion receipts",
        "package_role": "internal_development_only",
        "learning_attempts": 0,
        "official_package": status.get("official_package", {}),
        "gpu_snapshot": status.get("gpu", {}),
        "process_classification_counts": dict(sorted(process_counts.items())),
        "protected_process_policy": "pre-existing unrelated processes are observe-only; no process was stopped by GPU number or name",
        "D05_resource_totals": {
            "planned_cases": len(plan.get("cases", [])),
            "solver_replays": sum(item.get("status") == "completed" for item in run_cases),
            "reference_reuse": sum(item.get("status") == "reference_reuse_only" for item in run_cases),
            "gpu_assignments": gpu_assignments,
            "solver_wall_seconds_sum": round(sum(float(item.get("elapsed_seconds") or 0.0) for item in run_cases), 4),
            "raw_solver_bytes": raw_bytes,
            "partvtk_csv_bytes": csv_bytes,
            "normalized_hdf5_bytes": hdf5_bytes,
            "conversion_cases": len(conversion_cases),
        },
        "filesystem_at_report_time": {
            "mount": str(CAMPAIGN_ROOT),
            "total_bytes": disk.total,
            "used_bytes": disk.used,
            "free_bytes": disk.free,
        },
        "resource_interpretation": [
            "GPU indices are historical D05 launch assignments; the final snapshot is idle and no GPU is reserved.",
            "PartVTK and HDF5 normalization are CPU/disk work and did not require a GPU.",
            "Large raw, CSV, and normalized payloads remain in the local evidence store; compact receipts are the Git review surface.",
        ],
    }


def preview_markdown(preview: dict[str, Any]) -> str:
    lines = [
        "# DS-DATA-01 compact data preview",
        "",
        "This preview is metadata-only. It does not claim external scientific validation or material lineage.",
        "",
        "## Coverage",
        "",
        f"- D02 atlas: {preview['coverage']['D02_atlas_cases']} cases across {preview['coverage']['D02_families']} families.",
        f"- D03 Q-I structure pass: {preview['coverage']['D03_q_i_structure_pass']} cases.",
        f"- D05 internal cases: {preview['coverage']['D05_cases']} ({preview['coverage']['D05_q_i_structure_pass']} Solver conversions with Q-I structure pass).",
        "- D04 production assignments: train=0, validation=0, test=0.",
        "",
        "## Family view",
        "",
        "| Family | Atlas cases | Roles | Representative | Mechanism |",
        "|---|---:|---|---|---|",
    ]
    for row in preview["family_preview"]:
        roles = ", ".join(f"{key}={value}" for key, value in row["role_counts"].items())
        lines.append(f"| {row['family']} | {row['case_count']} | {roles} | `{row['representative_case']}` | {row['representative_mechanism']} |")
    lines.extend([
        "",
        "## D05 case view",
        "",
        "| Case | Family | Frames | Identities | Initial → final | Retention | Q-I | HDF5 | Role |",
        "|---|---|---:|---:|---:|---:|---|---:|---|",
    ])
    for row in preview["D05_case_preview"]:
        initial = row.get("active_initial")
        final = row.get("active_final")
        retention = row.get("identity_retention")
        retention_text = "—" if retention is None else f"{retention:.4f}"
        h5_bytes = row.get("normalized_hdf5_bytes")
        h5_text = "reuse" if h5_bytes is None else f"{h5_bytes / (1024 ** 2):.1f} MiB"
        lines.append(
            f"| `{row['case_id']}` | {row['family']} | {row.get('frames') or '—'} | {row.get('identity_count') or '—'} | {initial if initial is not None else '—'} → {final if final is not None else '—'} | {retention_text} | {row['conversion_status']} | {h5_text} | {row.get('plan_role') or 'reference_reuse'} |"
        )
    lines.extend([
        "",
        "## Reading rules",
        "",
        "- `Q-I-structure-pass` is a numerical storage/schema gate, not an external scientific validation result.",
        "- `introduced_after_initial` and `initial_missing_at_final` are shown to expose open lifecycle and numerical loss behavior.",
        "- All D05 cases remain `internal_development_only` and `unassigned`; no train/validation/test release is implied.",
    ])
    return "\n".join(lines) + "\n"


def resource_markdown(resource: dict[str, Any]) -> str:
    totals = resource["D05_resource_totals"]
    disk = resource["filesystem_at_report_time"]
    lines = [
        "# DS-DATA-01 resource report",
        "",
        "This is an observed resource/provenance report for dataset construction. It contains no training or model qualification accounting.",
        "",
        "## Official package",
        "",
        f"- Root: `{resource['official_package'].get('root')}`",
        f"- Version: `{resource['official_package'].get('version_info', '').splitlines()[0] if resource['official_package'].get('version_info') else 'unknown'}`",
        f"- Files: {resource['official_package'].get('file_count', 'unknown')}; example groups: {resource['official_package'].get('example_directory_count', 'unknown')}; PDFs: {resource['official_package'].get('example_pdf_count', 'unknown')}.",
        "",
        "## D05 resource totals",
        "",
        f"- Planned cases: {totals['planned_cases']}; Solver replays: {totals['solver_replays']}; reference reuse: {totals['reference_reuse']}.",
        f"- Sum of Solver wall times: {totals['solver_wall_seconds_sum']:.1f} s.",
        f"- Raw Solver output: {totals['raw_solver_bytes'] / (1024 ** 3):.2f} GiB; PartVTK CSV: {totals['partvtk_csv_bytes'] / (1024 ** 3):.2f} GiB; normalized HDF5: {totals['normalized_hdf5_bytes'] / (1024 ** 3):.2f} GiB.",
        f"- GPU assignments: {', '.join(f'{case}=GPU{gpu}' for case, gpu in sorted(totals['gpu_assignments'].items()))}.",
        "",
        "## Final snapshot",
        "",
        f"- Filesystem free at report time: {disk['free_bytes'] / (1024 ** 4):.2f} TiB of {disk['total_bytes'] / (1024 ** 4):.2f} TiB.",
        f"- Process classifications: {resource['process_classification_counts'] or 'none observed'}.",
        "- GPU policy: GPU0 remained protected; D05 used only fresh-preflight idle GPUs in the internal pool; all GPUs were idle after completion.",
        "- Unrelated pre-existing processes were observed only and were not stopped.",
        "",
        "## Evidence boundary",
        "",
        "- Large raw/CSV/HDF5 payloads remain local and are referenced by compact receipts and hashes.",
        "- CPU/disk conversion did not require a GPU.",
        "- No learning, inference, checkpoint replay, ranking, or model qualification was started.",
    ]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="validate existing generated reports without rewriting them")
    args = parser.parse_args()
    status = load(STATUS_PATH)
    atlas = load(ATLAS_PATH)
    d03 = load(D03_PATH)
    d04 = load(D04_PATH)
    plan = load(D05_PLAN_PATH)
    run_summary = load(D05_RUN_PATH)
    conversion = load(D05_CONVERSION_PATH)
    preview = build_preview(atlas, d03, d04, plan, run_summary, conversion)
    resource = build_resource(status, plan, run_summary, conversion)
    if args.check:
        expected_preview = json.loads(PREVIEW_JSON.read_text(encoding="utf-8")) if PREVIEW_JSON.is_file() else None
        expected_resource = json.loads(RESOURCE_JSON.read_text(encoding="utf-8")) if RESOURCE_JSON.is_file() else None
        if expected_preview is None or expected_resource is None:
            raise SystemExit("missing generated preview/resource report")
        if expected_preview.get("coverage") != preview.get("coverage"):
            raise SystemExit("preview coverage is stale")
        if expected_resource.get("D05_resource_totals") != resource.get("D05_resource_totals"):
            raise SystemExit("resource totals are stale")
        print(json.dumps({"status": "pass", "preview": rel(PREVIEW_JSON), "resource": rel(RESOURCE_JSON)}, ensure_ascii=False, indent=2))
        return 0
    atomic_write(PREVIEW_JSON, preview)
    atomic_write(RESOURCE_JSON, resource)
    PREVIEW_MD.write_text(preview_markdown(preview), encoding="utf-8")
    RESOURCE_MD.write_text(resource_markdown(resource), encoding="utf-8")
    print(json.dumps({
        "status": "written",
        "preview_json": rel(PREVIEW_JSON),
        "preview_markdown": rel(PREVIEW_MD),
        "resource_json": rel(RESOURCE_JSON),
        "resource_markdown": rel(RESOURCE_MD),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
