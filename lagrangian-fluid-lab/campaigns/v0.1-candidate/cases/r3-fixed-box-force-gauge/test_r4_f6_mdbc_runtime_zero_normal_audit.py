"""Minimal regression tests for the R4 F6 static normal audit."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path


CASE_ROOT = Path(__file__).resolve().parent
SCRIPT = CASE_ROOT.parents[3] / "scripts" / "r4_f6_mdbc_runtime_zero_normal_audit.py"
REPORT = CASE_ROOT / "r4-mdbc-runtime-zero-normal-audit.json"

SPEC = importlib.util.spec_from_file_location("r4_f6_audit", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def test_existing_report_has_complete_face_level_evidence():
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    assert report["audit_execution"]["mode"] == "cpu_static"
    assert report["audit_execution"]["solver_launched_by_audit"] is False
    assert report["summary"]["runtime_zero_normal_counts_by_resolution"] == {
        "canonical-2": 63,
        "fine-3": 240,
    }
    for case in report["cases"]:
        assert case["status"] == "complete"
        assert len(case["zero_normals_by_topology"]["faces"]) == 6
        assert len(case["zero_normals_by_topology"]["edges"]) == 12
        assert len(case["zero_normals_by_topology"]["corners"]) == 8
        assert case["checks"]["ghost_doubling_pass"] is True
        assert case["checks"]["construction_face_overlap_pass"] is True
        assert case["zero_normals"]["exact_vector_zero_count"] == 0


def test_report_is_reproducible_from_unchanged_artifacts():
    expected = json.loads(REPORT.read_text(encoding="utf-8"))
    actual = AUDIT.build_report(CASE_ROOT)
    assert actual == expected
