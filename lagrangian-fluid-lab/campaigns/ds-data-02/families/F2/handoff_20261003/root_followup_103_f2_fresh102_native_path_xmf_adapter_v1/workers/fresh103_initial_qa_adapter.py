#!/usr/bin/env python3
"""Run the F2 initial-QA worker with an attempt-local semantic receipt.

The Root353 execution receipt is an immutable producer artifact.  Some real
fresh102 receipts contain status/returncode but omit
``solver_dimension_from_gencase``.  The fresh102 prepared-evidence sidecar
records the independently checked 3-D XML/count contract.  This wrapper uses
that sidecar to supply the missing *semantic* field to the existing PartVTK
worker in a temporary receipt, then rewrites the resulting report so its
``gencase_receipt`` points back to the raw receipt and a separate
``gencase_semantic_adapter`` object explains the derivation.

It is an execution-time CPU worker.  Source preparation never invokes it;
PartVTK and scientific payload reads happen only if Root explicitly enables a
disabled request.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Mapping


FRESH100 = Path(__file__).resolve().parents[2] / "root_followup_100_f2_stage1_motion_entry_metadata_adapter_v1"
AUDIT = FRESH100 / "workers/f2_prepared_report_contract_audit.py"
INNER = FRESH100 / "workers/f2_stage1_initial_qa_worker.py"
SCHEMA = "ds02.f2.stage1.fresh103.semantic-initial-qa-adapter.v1"


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, Mapping):
        raise ValueError(f"JSON object required: {path}")
    return dict(value)


def validate_evidence(case_id: str, raw_path: Path, prepared_path: Path, xml_path: Path, sidecar_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    raw = load(raw_path)
    prepared = load(prepared_path)
    sidecar = load(sidecar_path)
    if sidecar.get("schema") != "ds02.f2.stage1.fresh102.gencase-runtime-evidence.v1":
        raise ValueError("fresh102 sidecar schema mismatch")
    if sidecar.get("case_id") != case_id:
        raise ValueError("fresh102 sidecar case mismatch")
    recorded_raw = sidecar.get("raw_gencase_receipt") or {}
    if Path(str(recorded_raw.get("path"))).resolve() != raw_path.resolve() or recorded_raw.get("sha256") != sha(raw_path):
        raise ValueError("raw receipt path/digest does not close sidecar")
    if recorded_raw.get("raw_receipt_immutable") is not True:
        raise ValueError("raw receipt immutability is required")
    if raw.get("status") != "completed" or raw.get("returncode") != 0:
        raise ValueError("raw GenCase receipt is not completed/0")
    checks = sidecar.get("contract_checks") or {}
    if checks.get("root353_solver_dimension_three") is not True:
        raise ValueError("fresh102 producer sidecar does not prove 3-D")
    report_ref = sidecar.get("prepared_input_report") or {}
    xml_ref = sidecar.get("prepared_generated_xml") or {}
    if Path(str(report_ref.get("path"))).resolve() != prepared_path.resolve() or report_ref.get("sha256") != sha(prepared_path):
        raise ValueError("prepared report path/digest does not close sidecar")
    if Path(str(xml_ref.get("path"))).resolve() != xml_path.resolve() or xml_ref.get("sha256") != sha(xml_path):
        raise ValueError("prepared XML path/digest does not close sidecar")
    counts = prepared.get("generated_xml_particle_counts")
    total = prepared.get("actual_total_particles")
    if not isinstance(counts, Mapping) or not isinstance(total, int):
        raise ValueError("prepared count evidence is missing")
    if sum(int(counts.get(k, -1)) for k in ("fixed", "moving", "floating", "fluid")) != total or total <= 0:
        raise ValueError("prepared count evidence does not close")
    if prepared.get("native_initial_typed_QA") != "pending actual arrays":
        raise ValueError("prepared report already contains an impermissible QA claim")
    return raw, prepared, sidecar, {"counts": dict(counts), "total": total, "dimension": 3}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--definition", required=True)
    parser.add_argument("--gencase-receipt", required=True)
    parser.add_argument("--prepared-input-report", required=True)
    parser.add_argument("--runtime-evidence", required=True)
    parser.add_argument("--prepared-report-output", required=True)
    parser.add_argument("--partvtk", required=True)
    parser.add_argument("--partvtk-output-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    raw_path = Path(args.gencase_receipt).resolve()
    prepared_path = Path(args.prepared_input_report).resolve()
    xml_path = Path(args.definition).resolve()
    sidecar_path = Path(args.runtime_evidence).resolve()
    raw, prepared, sidecar, summary = validate_evidence(args.case_id, raw_path, prepared_path, xml_path, sidecar_path)

    prepared_report_output = Path(args.prepared_report_output).resolve()
    prepared_report_output.parent.mkdir(parents=True, exist_ok=True)
    audit_cmd = [sys.executable, str(AUDIT), "--case-id", args.case_id, "--prepared-input-report", str(prepared_path), "--gencase-receipt", str(raw_path), "--output", str(prepared_report_output)]
    audit = subprocess.run(audit_cmd, check=False)
    if audit.returncode:
        return audit.returncode

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="fresh103-semantic-gencase-", dir=str(output.parent)) as temp:
        semantic_path = Path(temp) / "semantic-execution-receipt.json"
        semantic = dict(raw)
        # This is deliberately a derived semantic view, never the producer
        # receipt.  It exists only while the inner worker runs.
        semantic["solver_dimension_from_gencase"] = 3
        # Root353 stores the generated XML/BI4 and motion control file in the
        # flat ``prepared/`` prefix.  The older inner worker derives these
        # names from receipt.output_root, so point only the temporary semantic
        # view at that directory.  The raw receipt keeps its original
        # output_root and is restored in the final report below.
        semantic["output_root"] = str(prepared_path.parent)
        semantic["ds02_semantic_adapter"] = {
            "schema": SCHEMA,
            "raw_receipt_path": str(raw_path),
            "raw_receipt_sha256": sha(raw_path),
            "evidence_sidecar_path": str(sidecar_path),
            "evidence_sidecar_sha256": sha(sidecar_path),
            "derived_dimension": 3,
            "derived_counts": summary["counts"],
            "derived_total": summary["total"],
            "semantic_output_root": str(prepared_path.parent),
            "raw_output_root": raw.get("output_root"),
            "flat_prepared_prefix": str(prepared_path.parent),
            "raw_receipt_rewritten": False,
            "execution_receipt_claim": "none; this temporary file is not a producer receipt",
        }
        semantic_path.write_text(json.dumps(semantic, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        inner_cmd = [sys.executable, str(INNER), "--case-id", args.case_id, "--definition", str(xml_path), "--gencase-receipt", str(semantic_path), "--partvtk", args.partvtk, "--partvtk-output-dir", args.partvtk_output_dir, "--output", str(output)]
        result = subprocess.run(inner_cmd, check=False)

    if not output.is_file():
        return result.returncode
    report = load(output)
    report["schema"] = SCHEMA
    report["gencase_receipt"] = {"path": str(raw_path), "sha256": sha(raw_path), "status": raw.get("status"), "returncode": raw.get("returncode"), "output_root": raw.get("output_root")}
    report["gencase_semantic_adapter"] = {
        "schema": SCHEMA,
        "path": None,
        "sha256": None,
        "lifetime": "attempt-local temporary file; removed after inner worker",
        "derived_dimension": 3,
        "derived_counts": summary["counts"],
        "derived_total": summary["total"],
        "semantic_output_root": str(prepared_path.parent),
        "raw_output_root": raw.get("output_root"),
        "flat_prepared_prefix": str(prepared_path.parent),
        "source_sidecar": {"path": str(sidecar_path), "sha256": sha(sidecar_path)},
        "raw_receipt_immutable": True,
        "not_an_execution_receipt": True,
    }
    report["prepared_evidence"] = {"path": str(prepared_path), "sha256": sha(prepared_path), "counts": summary["counts"], "total": summary["total"], "dimension": 3}
    report["raw_receipt_dimension_field_present"] = "solver_dimension_from_gencase" in raw
    report["raw_receipt_dimension_field_value"] = raw.get("solver_dimension_from_gencase")
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
