#!/usr/bin/env python3
"""Static contract check for the fresh103/fresh097 frame-0 handoff.

This checker reads Python source text and JSON metadata only.  It deliberately
does not import either worker, invoke subprocesses, open a scientific file, or
re-hash any BI4/H5/VTK/CSV/DAT artifact.
"""

from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path


PACKAGE = Path(__file__).resolve().parents[1]
FRESH103 = PACKAGE.parent / "root_followup_103_stage1_f4_first48_gencase_to_native_initial_qa_v1"
FRESH097 = PACKAGE.parent / "root_followup_097_stage1_f4_native_frame0_partvtk_vz_to_typed_v1"
CONTRACT = PACKAGE / "metadata" / "fresh104-frame0-worker-contract.json"
EVIDENCE = PACKAGE / "evidence" / "actual-root616-root619-root623-root626.json"


def sha_source(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    contract = load(CONTRACT)
    wrapper = FRESH103 / "workers" / "run_fresh103_frame0_audit.py"
    audit = FRESH097 / "workers" / "native_frame0_partvtk_vz_audit.py"
    assert wrapper.is_file() and audit.is_file()
    assert sha_source(wrapper) == contract["wrapper"]["sha256"]
    assert sha_source(audit) == contract["per_case_audit"]["sha256"]

    wrapper_text = wrapper.read_text(encoding="utf-8")
    audit_text = audit.read_text(encoding="utf-8")
    ast.parse(wrapper_text, filename=str(wrapper))
    ast.parse(audit_text, filename=str(audit))
    assert 'template["cases"][0]' in wrapper_text
    assert "--binding" in wrapper_text and "--output-dir" in wrapper_text
    assert "mod.audit(c,a.output_dir)" in wrapper_text
    assert "def audit(" in audit_text
    assert "subprocess" in audit_text
    assert "gencase_declared_velocity_used_as_evidence" in audit_text

    evidence = load(EVIDENCE)
    assert evidence["case_count"] == 24
    assert evidence["root623_frame0_completed_pass"] == 24
    assert evidence["full_typed_render_visual_acceptance"] == "pending"
    assert all(row["root623_frame0"]["report"]["status"] == "completed_pass" for row in evidence["cases"])
    assert all(row["root623_frame0"]["raw_mk_type_observed"] is True for row in evidence["cases"])
    assert all(row["root623_frame0"]["raw_velocity_observed"] is True for row in evidence["cases"])
    assert contract["arrays_read_or_hashed_by_source"] is False
    assert contract["jobs_started_by_source"] is False
    print("fresh104 frame0 worker contract: PASS (singleton wrapper, per-case audit, 24 actual Root623 passes)")


if __name__ == "__main__":
    main()
