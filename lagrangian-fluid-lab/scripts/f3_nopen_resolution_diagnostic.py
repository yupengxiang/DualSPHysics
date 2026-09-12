"""Run one pre-registered CFL contrast for the failed NoPen resolution ladder.

This is a separately charged root-cause diagnostic.  It reuses the NP06 native
initial state, forcing, boundary recipe and output schedule, changing only
the CFL/CoefDtMin pair from 0.05 to 0.025.  Its source and score are never
accepted by the frozen NP01--NP14 qualification gates.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET

from scripts import l1r_q2_mdbc_bridge as q2
from scripts.l1r_continuation_evidence import LAB, OUT
from scripts.l1r_input_preflight import check_input


SOURCE_ID = "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen"
DIAGNOSTIC_ID = SOURCE_ID + "_cflhalf_retry"
SOURCE_RECORD = OUT / (SOURCE_ID + "-PREPARED.json")
RECORD_PATH = OUT / (DIAGNOSTIC_ID + "-PREPARED.json")
ARTIFACT_ROOT = LAB / "campaigns/l1-resume/artifacts/f3-nopen-diagnostics"


def _read(path: Path):
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _rewrite_xml(path: Path):
    tree = ET.parse(path)
    root = tree.getroot()
    for node in root.findall(".//cflnumber"):
        node.set("value", "0.025")
    for node in root.findall(".//parameter"):
        if node.get("key") == "CoefDtMin":
            node.set("value", "0.025")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def prepare():
    """Create or verify the immutable diagnostic input record."""
    source = _read(SOURCE_RECORD)
    source_prefix = (LAB / source["generated_prefix"]).resolve()
    target = ARTIFACT_ROOT / DIAGNOSTIC_ID
    if RECORD_PATH.exists():
        record = _read(RECORD_PATH)
        if (record.get("id") != DIAGNOSTIC_ID or record.get("case_id") != DIAGNOSTIC_ID
                or record.get("cfl_number") != .025 or record.get("coef_dt_min") != .025):
            raise ValueError("resolution diagnostic record changed")
        check_input(record)
        return record
    attempts = LAB / "campaigns/l1-resume/runs/branches" / DIAGNOSTIC_ID / "attempts"
    if target.exists() or attempts.exists():
        raise ValueError("incomplete resolution diagnostic exists; inspect before reuse")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_prefix.parent, target)
    prefix = target / source_prefix.name
    _rewrite_xml(prefix.with_suffix(".xml"))
    _rewrite_xml(prefix.with_name(prefix.name + "_Def.xml"))
    record = copy.deepcopy(source)
    record.update(
        id=DIAGNOSTIC_ID,
        case_id=DIAGNOSTIC_ID,
        phase="F3_CELL3_resolution_root_cause_diagnostic",
        comparison_scope=("Separate CFL contrast for NP01-NP06 resolution failure; "
                          "diagnostic evidence only, never a qualification source"),
        generated_prefix=_relative(prefix),
        generated_xml_sha256=q2.sha256(prefix.with_suffix(".xml")),
        cfl_number=.025,
        coef_dt_min=.025,
        solver_timeout_seconds=3600,
        resource_category="qualification",
        max_attempts=1,
        retry_of={
            "case_id": SOURCE_ID + "_cflhalf",
            "attempt_path": "campaigns/l1-resume/runs/branches/" + SOURCE_ID +
                             "_cflhalf/attempts/20260912T090644.223676Z-8cb0e4b1.failed/attempt.json",
        },
        qualified=False,
        formal_release=False,
    )
    record["input_assets"] = {
        path.name: q2.sha256(path) for path in target.iterdir() if path.is_file()
    }
    check_input(record)
    q2.atomic_json(RECORD_PATH, record)
    return record


def run():
    """Execute once through the shared single-solver and resource guards."""
    record = prepare()
    from scripts.l1r_branch_runner import run as shared_run
    return shared_run(record)


if __name__ == "__main__":
    result = run()
    print(json.dumps({k: result.get(k) for k in ("case_id", "status", "audit_status", "frames", "issues", "unknowns")}, indent=2), flush=True)
