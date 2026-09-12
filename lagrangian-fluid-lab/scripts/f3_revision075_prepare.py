"""Prepare the prospective 0.0075 m F3 revision matrix without launching CFD.

This command only creates immutable input directories, transformed forcing
files, preflight records and prepared records.  It deliberately has no
``run`` action: a separately approved runner must be written after the owner
authorizes the revision and resource changes.
"""
from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from scripts import l1r_q2_mdbc_bridge as q2
from scripts.l1r_continuation_evidence import LAB, OUT, write
from scripts.l1r_input_preflight import check_input


MANIFEST = LAB / "diagnostics/f3-audit/F3-075-REVISION-MATRIX-MANIFEST.json"
TARGET_ROOT = LAB / "campaigns/l1-resume/artifacts/f3-revision075"
OUT_PREFIX = OUT
SOURCE_CASES = {
    0.01: "F3_CELL3_LONG_dp0p01_a1p000_noslip_visco1_nopen",
    0.0075: "F3_CELL3_LONG_dp0p0075_a1p000_noslip_visco1_nopen",
    0.006: "F3_CELL3_LONG_dp0p006_a1p000_noslip_visco1_nopen",
}
VENDOR_DRIVE = LAB / "vendor/official/DualSPHysics_v5.4/examples/main/05_SloshingTank/CaseSloshingAccData.csv"


def _read(path: Path):
    return json.loads(path.read_text())


def _source(dp: float):
    case = SOURCE_CASES[dp]
    return _read(OUT / (case + "-PREPARED.json"))


def _prefix(record):
    return (LAB / record["generated_prefix"]).resolve()


def _case_id(cell):
    return "F3_REV075_" + cell["cell_id"]


def _rewrite_xml(path: Path, cell):
    tree = ET.parse(path)
    root = tree.getroot()
    params = root.findall("./execution/parameters/parameter")
    by_key = {node.get("key"): node for node in params}
    if len(by_key) != len(params):
        raise ValueError("duplicate execution parameter in " + str(path))
    expected = {"TimeMax": 8.35, "TimeOut": cell["output_interval_s"],
                "CoefDtMin": cell["coef_dt_min"]}
    for key, value in expected.items():
        if key not in by_key:
            raise ValueError("missing parameter " + key)
        by_key[key].set("value", str(value))
    cfl = root.findall(".//cflnumber")
    if not cfl:
        raise ValueError("missing CFL node")
    for node in cfl:
        node.set("value", str(cell["cfl_number"]))
    definition = root.find("./casedef/geometry/definition")
    if definition is None or float(definition.get("dp")) != cell["dp_m"]:
        raise ValueError("source dp differs from manifest")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _drive(target: Path, amplitude: float):
    nominal = np.loadtxt(VENDOR_DRIVE, delimiter=";", comments="#")
    actual = nominal.copy()
    gravity = np.array([0.0, 0.0, -9.81])
    actual[:, 1:4] = gravity + amplitude * (nominal[:, 1:4] - gravity)
    actual[:, 4:7] = amplitude * nominal[:, 4:7]
    np.savetxt(
        target, actual, delimiter=";", fmt="%.17g",
        header="Time;LinearAccX;LinearAccY;LinearAccZ;AngularAccX;AngularAccY;AngularAccZ",
    )


def _prepare_cell(cell, manifest_sha):
    dp = float(cell["dp_m"])
    source_record = _source(dp)
    source_prefix = _prefix(source_record)
    case_id = _case_id(cell)
    target = TARGET_ROOT / case_id
    target_prefix = target / source_prefix.name
    prepared_path = OUT_PREFIX / (case_id + "-PREPARED.json")
    if target.exists() and not prepared_path.exists():
        raise ValueError("target exists without prepared record: " + case_id)
    if prepared_path.exists():
        record = _read(prepared_path)
        if (record.get("id") != case_id or record.get("revision_manifest_sha256") != manifest_sha
                or record.get("launch_allowed") is not False):
            raise ValueError("immutable revision record changed: " + case_id)
        check_input(record)
        return record
    target.mkdir(parents=True, exist_ok=False)
    for filename in source_record["input_assets"]:
        shutil.copy2(source_prefix.parent / filename, target / filename)
    for suffix in (".xml", "_Def.xml"):
        _rewrite_xml(target / (source_prefix.name + suffix), cell)
    _drive(target / "CaseSloshingAccData.csv", float(cell["amplitude"]))

    record = copy.deepcopy(source_record)
    timeout = 1800 if dp == 0.01 else (3600 if dp == 0.0075 else 5400)
    record.update(
        id=case_id,
        case_id=case_id,
        phase="F3_revision075_preparation_only",
        plan_case_id=cell["cell_id"],
        role=cell["role"],
        recipe_id="F3_CELL3_NS_visco1_native_nopen_revision075",
        generated_prefix=str(target_prefix.relative_to(LAB)),
        candidate_definition=str((target / (source_prefix.name + "_Def.xml")).relative_to(LAB)),
        generated_xml_sha256=q2.sha256(target_prefix.with_suffix(".xml")),
        drive_amplitude=float(cell["amplitude"]),
        cfl_number=float(cell["cfl_number"]),
        coef_dt_min=float(cell["coef_dt_min"]),
        time_out_s=float(cell["output_interval_s"]),
        solver_timeout_seconds=timeout,
        max_attempts=1,
        resource_category="qualification",
        launch_allowed=False,
        qualified=False,
        formal_release=False,
        revision_manifest_sha256=manifest_sha,
        preparer_sha256=q2.sha256(Path(__file__)),
        comparison_scope=("Prospective 0.0075 m recipe revision cell; preparation only, "
                          "no qualification or production status"),
        input_repair="none; only registered revision control/resolution/output transformation",
        input_assets={p.name: q2.sha256(p) for p in target.iterdir() if p.is_file()},
        drive_sha256=q2.sha256(target / "CaseSloshingAccData.csv"),
    )
    check_input(record)
    write(prepared_path.name, record)
    return record


def prepare_all():
    manifest = _read(MANIFEST)
    if manifest.get("launch_allowed") is not False or manifest.get("status") != "prepared_manifest_only":
        raise ValueError("revision manifest is not preparation-only")
    cells = manifest.get("cells", [])
    if len(cells) != 11 or len({c.get("cell_id") for c in cells}) != 11:
        raise ValueError("revision manifest must contain 11 unique cells")
    manifest_sha = q2.sha256(MANIFEST)
    records = [_prepare_cell(cell, manifest_sha) for cell in cells]
    summary = {
        "schema": "f3.revision075.preparation_summary.v1",
        "status": "prepared_only",
        "launch_allowed": False,
        "manifest_sha256": manifest_sha,
        "preparer_sha256": q2.sha256(Path(__file__)),
        "cell_ids": [r["plan_case_id"] for r in records],
        "prepared_records": [str((OUT / (r["id"] + "-PREPARED.json")).relative_to(LAB)) for r in records],
        "input_preflights": [str((OUT / (r["id"] + "-INPUT-PREFLIGHT.json")).relative_to(LAB)) for r in records],
        "solver_attempts": 0,
        "qualification_attempts_charged": 0,
        "qualified": False,
        "formal_release": False,
    }
    write("F3-075-REVISION-PREPARATION-SUMMARY.json", summary)
    print(json.dumps(summary, indent=2), flush=True)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prepare-all",))
    args = parser.parse_args()
    prepare_all()
