#!/usr/bin/env python3
"""Bind Root101 F2 GenCase receipts to disabled, runnable PartVTK QA requests.

The builder reads only JSON/XML/text metadata and hashes.  It does not invoke
PartVTK, GenCase, a solver, or an array reader.  The emitted worker request is
disabled until Root enables it; when enabled, the worker streams frame zero
and writes its bounded report under the runner attempt root.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

HERE = Path(__file__).resolve().parent
F2_WORKTREE = Path("/home/jade/.codex/worktrees/ds-data-02-f2/DualSPHysics")
INTEGRATION = Path("/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics")
LAB = INTEGRATION / "lagrangian-fluid-lab"
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2")

WORKER = HERE / "workers/f2_stage1_initial_qa_worker_v2.py"
LEGACY_WORKER = F2_WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1/workers/f2_stage1_initial_qa_worker.py"
ENDPOINT_BUILDER = F2_WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1/build_f2_stage1_endpoints.py"
ENDPOINT_WORKER = F2_WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1/workers/f2_stage1_endpoint_worker.py"
SOURCE_DIR = F2_WORKTREE / "lagrangian-fluid-lab/campaigns/ds-data-02/families/F2/handoff_20261003/root_followup_090_f2_stage1_production_endpoints_v1/source"
PARTVTK = F2_WORKTREE / "lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/PartVTK_linux64"
PYTHON = F2_WORKTREE / "lagrangian-fluid-lab/.venv/bin/python"
RUNTIME = LAB / "scripts/ds_data02_runtime_v2.py"
STRICT_DISPATCH = LAB / "scripts/ds_data02_strict_dispatch_v1.py"
GOAL = LAB / "campaigns/ds-data-02/GOAL_STAGE1_VISUAL_GPT56LUNA_20261004_ZH.md"

CASES = (
    ("F2_STAGE1_OFFSET_P01_DP010_SPATIAL_REFERENCE_SAVE010", "offset-p01"),
    ("F2_STAGE1_OFFSET_P03_DP010_SPATIAL_REFERENCE_SAVE010", "offset-p03"),
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> Mapping[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def binding(path: Path, *, known_sha: str | None = None) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return {"path": str(path), "sha256": known_sha or sha256(path)}


def actual_case(case_id: str, short: str) -> dict[str, Any]:
    root = DATA_ROOT / case_id
    attempt_id = f"root-stage1-f2-{short}-genuine-gencase-count-fix-101"
    attempt = root / attempt_id
    receipt_path = attempt / "execution-receipt.json"
    report_path = attempt / "prepared/prepared-input-report.json"
    receipt = load(receipt_path)
    report = load(report_path)
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ValueError(f"Root101 receipt is not completed/0: {receipt_path}")
    if receipt.get("solver_dimension_from_gencase") != 3:
        raise ValueError(f"Root101 receipt is not 3D: {receipt_path}")
    output_files = receipt.get("output_files") if isinstance(receipt.get("output_files"), Mapping) else {}
    prefix = Path(str(report["prefix"])).resolve()
    xml_path = Path(str(output_files.get("xml"))).resolve() if isinstance(output_files.get("xml"), str) else prefix.with_suffix(".xml")
    bi4_path = Path(str(output_files.get("bi4"))).resolve() if isinstance(output_files.get("bi4"), str) else prefix.with_suffix(".bi4")
    source_prefix = SOURCE_DIR / case_id
    source_def = SOURCE_DIR / f"{case_id}_Def.xml"
    source_motion = SOURCE_DIR / f"{case_id}_motion.dat"
    source_metadata = SOURCE_DIR / f"{case_id}.metadata.json"
    actual_counts = report.get("generated_xml_particle_counts")
    if not isinstance(actual_counts, Mapping):
        raise ValueError(f"Root101 report has no generated XML particle counts: {report_path}")
    return {
        "case_id": case_id,
        "short": short,
        "attempt_id": attempt_id,
        "root": root,
        "receipt_path": receipt_path,
        "receipt": receipt,
        "report_path": report_path,
        "report": report,
        "source_prefix": source_prefix,
        "source_def": source_def,
        "source_motion": source_motion,
        "source_metadata": source_metadata,
        "actual_xml": xml_path,
        "actual_bi4": bi4_path,
        "actual_counts": dict(actual_counts),
    }


def make_binding(case: Mapping[str, Any]) -> dict[str, Any]:
    receipt = case["receipt"]
    report = case["report"]
    return {
        "schema": "ds02.f2.stage1.actual-initial-qa-binding.v2",
        "family_id": "F2",
        "case_id": case["case_id"],
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "root101_gencase": {
            "attempt_id": case["attempt_id"],
            "receipt": binding(case["receipt_path"]),
            "status": receipt.get("status"),
            "returncode": receipt.get("returncode"),
            "solver_dimension_from_gencase": receipt.get("solver_dimension_from_gencase"),
            "total_particles": receipt.get("total_particles"),
            "fluid_particles": receipt.get("fluid_particles"),
            "output_root": receipt.get("output_root"),
        },
        "actual_outputs": {
            "xml": binding(case["actual_xml"], known_sha=report.get("xml_sha256")),
            # The BI4 hash comes from Root's prepared-input report.  This
            # helper records it but never opens or interprets the binary.
            "bi4": binding(case["actual_bi4"], known_sha=report.get("bi4_sha256")),
            "prepared_input_report": binding(case["report_path"]),
        },
        "dynamic_xml_metadata": {
            "generated_xml_particle_counts": dict(report["generated_xml_particle_counts"]),
            "actual_total_particles": report.get("actual_total_particles"),
            "actual_generated_constants": report.get("actual_generated_constants"),
            "mass_evidence": report.get("mass_evidence"),
        },
        "source_definition": binding(case["source_def"]),
        "source_motion": binding(case["source_motion"]),
        "source_metadata": binding(case["source_metadata"]),
        "legacy_source_worker": binding(LEGACY_WORKER),
        "endpoint_builder": binding(ENDPOINT_BUILDER),
        "endpoint_worker": binding(ENDPOINT_WORKER),
        "qa_worker": binding(WORKER),
        "partvtk": binding(PARTVTK),
        "mass_policy": "derive unscaled native MassFluid/Mass from this case's actual XML and streamed QA CSV; never use any mother particle count",
        "root100_failure_policy": "preserve Root100 source/failure evidence; this binding consumes only Root101 completed/0",
    }


def make_request(case: Mapping[str, Any], bind_path: Path) -> dict[str, Any]:
    input_paths = [
        WORKER,
        LEGACY_WORKER,
        ENDPOINT_BUILDER,
        ENDPOINT_WORKER,
        case["source_def"],
        case["source_motion"],
        case["source_metadata"],
        case["receipt_path"],
        case["report_path"],
        case["actual_xml"],
        RUNTIME,
        STRICT_DISPATCH,
        PARTVTK,
        GOAL,
        bind_path,
    ]
    hashes = {str(Path(path).resolve()): sha256(Path(path)) for path in input_paths}
    command = [
        str(PYTHON.resolve()),
        str(WORKER.resolve()),
        "--case-id", case["case_id"],
        "--definition", str(case["source_def"].resolve()),
        "--gencase-receipt", str(case["receipt_path"].resolve()),
        "--partvtk", str(PARTVTK.resolve()),
        "--partvtk-output-dir", "{attempt_root}/partvtk",
        "--output", "{attempt_root}/actual-initial-qa.json",
    ]
    report = case["report"]
    return {
        "schema": "ds02.runner-request.v2",
        "family_id": "F2",
        "case_id": case["case_id"],
        "attempt_id": f"root-stage1-f2-{case['short']}-actual-initial-qa-091",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 2,
        "max_wall_seconds": 1800,
        "estimated_storage_bytes": 268435456,
        "cwd": str((F2_WORKTREE / "lagrangian-fluid-lab").resolve()),
        "worktree_root": str(F2_WORKTREE.resolve()),
        "command": command,
        "input_files": [str(Path(path).resolve()) for path in input_paths],
        "input_sha256": hashes,
        "launch_allowed": False,
        "execution_allowed": False,
        "source_only": True,
        "production_claim": "none",
        "qualification_claim": "none",
        "root_review_required": True,
        "depends_on_attempt": case["attempt_id"],
        "gencase_receipt": str(case["receipt_path"].resolve()),
        "gencase_receipt_sha256": sha256(case["receipt_path"]),
        "actual_gencase_output": {
            "xml": str(case["actual_xml"].resolve()),
            "xml_sha256": report.get("xml_sha256"),
            "bi4": str(case["actual_bi4"].resolve()),
            "bi4_sha256": report.get("bi4_sha256"),
            "generated_xml_particle_counts": dict(report["generated_xml_particle_counts"]),
            "actual_total_particles": report.get("actual_total_particles"),
            "actual_generated_constants": report.get("actual_generated_constants"),
        },
        "required_checks": [
            "actual Root101 receipt status completed and returncode 0",
            "actual generated XML is 3D and preserves dp=.01, TimeMax=4, TimeOut=.01",
            "PartVTK frame-zero CSV fields finite",
            "dynamic Type3 fluid and UID partitions",
            "unscaled Mass values reported from this case only",
        ],
        "disabled_reason": "Root must enable this bounded PartVTK audit; no QA/CSV is produced by source delivery",
        "raw_output_policy": "PartVTK CSV/log remain under external DS-DATA-02 runner attempt; report is bounded JSON only",
        "raw_output_root": str(case["root"].resolve()),
        "mass_policy": "actual case XML/CSV only; no fixed expected count and no mother mass substitution",
        "status": "source_only_disabled_root101_gencase_bound",
        "root101_report_sha256": sha256(case["report_path"]),
        "binding": str(bind_path.resolve()),
        "binding_sha256": sha256(bind_path),
    }


def build() -> dict[str, Any]:
    for path in (WORKER, LEGACY_WORKER, ENDPOINT_BUILDER, ENDPOINT_WORKER, PARTVTK, PYTHON, RUNTIME, STRICT_DISPATCH, GOAL):
        if not path.is_file():
            raise FileNotFoundError(path)
    binding_dir = HERE / "bindings"
    request_dir = HERE / "requests"
    binding_dir.mkdir(parents=True, exist_ok=True)
    request_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    for case_id_value, short in CASES:
        case = actual_case(case_id_value, short)
        value = make_binding(case)
        bind_path = binding_dir / f"{case_id_value}.json"
        write_json(bind_path, value)
        request = make_request(case, bind_path)
        request_path = request_dir / f"{case_id_value}-actual-qa.json"
        write_json(request_path, request)
        rows.append({
            "case_id": case_id_value,
            "gencase_attempt": case["attempt_id"],
            "gencase_receipt": str(case["receipt_path"].resolve()),
            "gencase_receipt_sha256": sha256(case["receipt_path"]),
            "actual_xml": str(case["actual_xml"].resolve()),
            "actual_xml_sha256": case["report"].get("xml_sha256"),
            "actual_bi4": str(case["actual_bi4"].resolve()),
            "actual_bi4_sha256": case["report"].get("bi4_sha256"),
            "actual_total_particles": case["receipt"].get("total_particles"),
            "actual_fluid_particles": case["receipt"].get("fluid_particles"),
            "generated_xml_particle_counts": dict(case["report"]["generated_xml_particle_counts"]),
            "binding": str(bind_path.resolve()),
            "request": str(request_path.resolve()),
            "execution_allowed": False,
        })
    manifest = {
        "schema": "ds02.f2.stage1.actual-initial-qa-manifest.v2",
        "family_id": "F2",
        "handoff": HERE.name,
        "source_only": True,
        "execution_allowed": False,
        "launch_allowed": False,
        "cases": rows,
        "dynamic_count_policy": "all counts are read from each Root101 receipt/XML/report; no mother 24576 assumption",
        "unscaled_mass_policy": "QA worker derives XML MassFluid/Mass and CSV mass sums per actual case without normalization",
        "root100_preservation": "Root100 failed/source evidence is not referenced as a completed result and remains untouched",
        "worker_launch": "Root can enable each disabled request; this package itself runs no PartVTK",
        "claims": {"production": False, "qualification": False, "visual": False, "precision": False},
    }
    write_json(HERE / "F2_STAGE1_ACTUAL_INITIAL_QA_MANIFEST.json", manifest)
    return {"package": str(HERE), "cases": [row["case_id"] for row in rows], "requests_disabled": True}


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False, indent=2))
