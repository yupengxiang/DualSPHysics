"""Run the current NoPenetration recipe with a four-layer boundary bridge.

The earlier CELL4 contrast is retained as a historical old no-projection
bridge.  This module binds the same one-factor boundary-layer change to the
passing NP01 input: ``-mdbc_noslip:1`` and ``NoPenetration=1`` remain fixed.
It is a diagnostic/recipe candidate only and can never rewrite the frozen
NP01--NP14 qualification gate.
"""
from __future__ import annotations

import copy
import json
import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

from scripts import l1r_q2_mdbc_bridge as q2
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts.l1r_input_preflight import check_input


SOURCE_ID = "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen"
BRIDGE_ID = "F3_CELL4_LONG_dp0p01_a1p000_noslip_visco1_nopen"
SOURCE_RECORD = OUT / (SOURCE_ID + "-PREPARED.json")
RECORD_PATH = OUT / (BRIDGE_ID + "-PREPARED.json")
ARTIFACT_ROOT = LAB / "campaigns/l1-resume/artifacts/cell4-nopen-long"


def _read(path: Path):
    return json.loads(path.read_text())


def _relative(path: Path) -> str:
    return str(path.resolve().relative_to(LAB.resolve()))


def _rewrite_layers(path: Path) -> None:
    tree = ET.parse(path)
    root = tree.getroot()
    nodes = root.findall(".//mainlist/drawbox/layers")
    if not nodes:
        raise ValueError("boundary layer node missing")
    changed = 0
    for node in nodes:
        if node.get("vdp") == "0,1,2":
            node.set("vdp", "0,1,2,3")
            changed += 1
    if changed != 1:
        raise ValueError(f"expected one three-layer boundary drawbox, got {changed}")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def prepare():
    source = _read(SOURCE_RECORD)
    source_prefix = (LAB / source["generated_prefix"]).resolve()
    target = ARTIFACT_ROOT / BRIDGE_ID
    if RECORD_PATH.exists():
        record = _read(RECORD_PATH)
        if (record.get("id") != BRIDGE_ID or record.get("case_id") != BRIDGE_ID
                or record.get("solver_mode") != "-mdbc_noslip:1"
                or record.get("expected_no_penetration") is not True
                or record.get("boundary_layer_count") != 4):
            raise ValueError("existing NoPenetration four-layer record changed")
        check_input(record)
        return record
    attempts = LAB / "campaigns/l1-resume/runs/branches" / BRIDGE_ID / "attempts"
    if target.exists() or attempts.exists():
        raise ValueError("incomplete NoPenetration four-layer bridge exists; inspect first")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_prefix.parent, target)
    prefix = target / source_prefix.name
    _rewrite_layers(prefix.with_suffix(".xml"))
    _rewrite_layers(prefix.with_name(prefix.name + "_Def.xml"))
    # GenCase creates the candidate from the modified definition.  Restore the
    # source acceleration file because GenCase also emits an empty template.
    gencase = LAB / "vendor/official/DualSPHysics_v5.4/bin/linux/GenCase_linux64"
    import os
    import subprocess
    result = subprocess.run(
        [str(gencase), str(prefix), str(prefix), "-save:all"],
        cwd=target, env=dict(os.environ, OMP_NUM_THREADS="4"),
        capture_output=True, text=True, timeout=120,
    )
    (target / "gencase.log").write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError("GenCase failed while preparing NoPenetration bridge")
    drive = target / "CaseSloshingAccData.csv"
    drive.write_bytes((source_prefix.parent / "CaseSloshingAccData.csv").read_bytes())
    if not drive.stat().st_size:
        raise ValueError("empty acceleration input after GenCase")
    source_assets = source.get("input_assets", {})
    source_xml = prefix.with_suffix(".xml")
    source_def = prefix.with_name(prefix.name + "_Def.xml")
    record = copy.deepcopy(source)
    record.update(
        id=BRIDGE_ID,
        case_id=BRIDGE_ID,
        phase="F3_CELL4_nopen_boundary_bridge",
        recipe_id="F3_CELL4_NS_visco1_native_nopen_boundary4",
        generated_prefix=_relative(prefix),
        candidate_definition=_relative(source_def),
        generated_xml_sha256=q2.sha256(source_xml),
        input_assets={
            drive.name: q2.sha256(drive),
            source_xml.name: q2.sha256(source_xml),
            source_def.name: q2.sha256(source_def),
            prefix.with_suffix(".bi4").name: q2.sha256(prefix.with_suffix(".bi4")),
        },
        gencase={"total_particles": 73028, "fluid_particles": 14580,
                 "boundary_particles": 58448, "source_case": SOURCE_ID},
        comparison_scope=("Current NP01 NoPenetration=True recipe with one boundary-layer change; "
                           "diagnostic candidate only, never a gate rewrite"),
        input_repair="add fourth external boundary layer while retaining NoPenetration=True",
        boundary_layer_count=4,
        boundary_bridge_sha256=q2.sha256(OUT / "F3-BOUNDARY4-DESIGN.json"),
        expected_no_penetration=True,
        expected_slip_mode="No-slip",
        solver_mode="-mdbc_noslip:1",
        solver_timeout_seconds=1800,
        max_attempts=1,
        formal_release=False,
        qualified=False,
        historical_source_assets=source_assets,
    )
    check_input(record)
    write(RECORD_PATH.name, record)
    return record


def run():
    record = prepare()
    from scripts.l1r_branch_runner import run as shared_run
    return shared_run(record)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare", "run"))
    args = parser.parse_args()
    if args.action == "prepare":
        print(prepare()["id"], flush=True)
    else:
        result = run()
        print(json.dumps({k: result.get(k) for k in
                          ("case_id", "status", "audit_status", "frames", "issues", "unknowns")},
                         indent=2), flush=True)
