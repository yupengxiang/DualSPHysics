#!/usr/bin/env python3
"""Materialize a fresh, source-bound F3-S2 P1200/AY0750 GenCase input.

This is a forward-only repair worker.  It clones the exact S2 XML and
acceleration table into the new attempt directory, verifies the existing
prepared BI4 only after the parent guard has reserved and hashed it, and then
invokes the official GenCase binary on the clone.  The old S1 receipt and all
existing S2 products remain provenance only; no file in the data tree is
modified.

The worker reports two different masses deliberately.  The continuous owner
volume comes from the source physical-binding contract, while the generated
XML gives the discrete particle count and MassFluid sample.  A successful
GenCase run therefore closes source/control and initial-state identity only;
it does not grant QI/QN/QE or establish solver fate/dynamics.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Any


SCHEMA = "ds02.stage2.f3.s2.source-clone-gencase.v1"
PHYSICAL_CASE_ID = "F3_TWOAXIS_P1200_AY0750_STAGE1_FIRST48_PITCH_VARIANT"
EXPECTED_XML_SHA256 = "1162322010c42b9a084d76db0e20de571111cb009eb3afb699f2ee4c17d37406"
EXPECTED_CONTROL_SHA256 = "9a776c1c02aeeb779902964953cd51b2af1f8ab41905398bb5125a44b93e6989"
EXPECTED_SOURCE_BI4_SHA256 = "c9c3fb8315dad402f77dd015539be376c3df68f332f3ed6d03e6c174e4c57d80"
EXPECTED_PRIOR_SUPPORT_SHA256 = "3a882f545b4393f1d56863c54a6057871c31ba44e5db64a9a01cea7f343c64c0"
EXPECTED_FLUID_COUNT = 67500
EXPECTED_FIXED_COUNT = 111708
EXPECTED_TOTAL_COUNT = EXPECTED_FLUID_COUNT + EXPECTED_FIXED_COUNT
EXPECTED_MASSFLUID_KG = 0.000216
EXPECTED_CONTINUOUS_MASS_KG = 14.58


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_file(path: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} must be a regular file: {path}")
    return path


def copy_fresh(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(f"refusing to overwrite source clone: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    if sha256(target) != sha256(source):
        raise RuntimeError(f"source clone digest changed: {source} -> {target}")


def local_tag(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _canonical(node: ET.Element) -> tuple[Any, ...]:
    """Canonicalize an XML subtree while retaining physical attributes."""
    return (
        local_tag(node.tag),
        tuple(sorted(node.attrib.items())),
        (node.text or "").strip(),
        tuple(_canonical(child) for child in list(node)),
    )


def _xml_summary(path: Path) -> dict[str, Any]:
    root = ET.parse(path).getroot()
    casedef = next((node for node in root.iter() if local_tag(node.tag) == "casedef"), None)
    if casedef is None:
        raise ValueError(f"missing casedef in GenCase XML: {path}")
    definition = next((node for node in casedef.iter() if local_tag(node.tag) == "definition"), None)
    if definition is None:
        raise ValueError(f"missing geometry definition in GenCase XML: {path}")
    dp = float(definition.get("dp"))
    particles = next((node for node in root.iter() if local_tag(node.tag) == "particles"), None)
    if particles is None:
        raise ValueError(f"missing particles in GenCase XML: {path}")
    counts: dict[str, int] = {}
    for node in particles:
        tag = local_tag(node.tag)
        if tag in {"fixed", "moving", "floating", "fluid"}:
            counts[tag] = counts.get(tag, 0) + int(node.get("count", "0"))
    constants = next((node for node in root.iter() if local_tag(node.tag) == "constants"), None)
    mass_node = next(
        (node for node in (list(constants) if constants is not None else [])
         if local_tag(node.tag) == "massfluid"),
        None,
    )
    if mass_node is None:
        raise ValueError(f"missing massfluid in GenCase XML: {path}")
    massfluid = float(mass_node.get("value"))
    accinput = next((node for node in root.iter() if local_tag(node.tag) == "accinput"), None)
    control_name = None
    if accinput is not None:
        control = next((node for node in accinput if local_tag(node.tag) == "acctimesfile"), None)
        control_name = control.get("value") if control is not None else None
    if control_name is None:
        raise ValueError(f"missing acctimesfile in GenCase XML: {path}")
    geometry_fluid: list[dict[str, Any]] = []
    for node in root.iter():
        if local_tag(node.tag) != "drawbox":
            continue
        point = next((child for child in node if local_tag(child.tag) == "point"), None)
        size = next((child for child in node if local_tag(child.tag) == "size"), None)
        if point is None or size is None:
            continue
        geometry_fluid.append({
            "low_m": [float(point.get(axis)) for axis in "xyz"],
            "size_m": [float(size.get(axis)) for axis in "xyz"],
            "volume_m3": (float(size.get("x")) * float(size.get("y")) *
                          float(size.get("z"))),
        })
    return {
        "path": str(path),
        "sha256": sha256(path),
        "dp_m": dp,
        "particles": counts,
        "total_particles": sum(counts.values()),
        "massfluid_kg": massfluid,
        "sample_fluid_mass_kg": counts.get("fluid", 0) * massfluid,
        "acctimesfile": control_name,
        "fluid_drawboxes": geometry_fluid,
        "casedef_canonical": _canonical(casedef),
    }


def _source_report(report_path: Path) -> dict[str, Any]:
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("prepared source report is not the P1200/AY0750 S2 condition")
    if report.get("xml_sha256") != EXPECTED_XML_SHA256:
        raise ValueError("prepared source report XML digest is not the bound S2 XML")
    if report.get("forcing_sha256") != EXPECTED_CONTROL_SHA256:
        raise ValueError("prepared source report control digest is not the bound S2 control")
    if report.get("bi4_sha256") != EXPECTED_SOURCE_BI4_SHA256:
        raise ValueError("prepared source report BI4 digest is not the bound S2 source")
    binding = report.get("physical_binding") or {}
    if binding.get("physical_case_id") != PHYSICAL_CASE_ID:
        raise ValueError("prepared physical binding has the wrong S2 physical case")
    geometry = (binding.get("geometry") or {}).get("initial_fluid") or {}
    low = geometry.get("low_m")
    size = geometry.get("size_m")
    if low != [-0.45, -0.09, 0.0] or size != [0.9, 0.18, 0.09]:
        raise ValueError("continuous owner geometry is not the bound F3 cell3 volume")
    if binding.get("initial_state", {}).get("initial_mass_total_kg") != EXPECTED_CONTINUOUS_MASS_KG:
        raise ValueError("continuous owner mass contract changed")
    return report


def _prior_support_report(path: Path) -> dict[str, Any]:
    if sha256(path) != EXPECTED_PRIOR_SUPPORT_SHA256:
        raise ValueError("root081 support report changed; create a new forward request")
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or "cases" not in report:
        raise ValueError("root081 support report schema is not recognized")
    return report


def run(args: argparse.Namespace) -> dict[str, Any]:
    source_xml = require_file(Path(args.source_xml), "source XML")
    source_control = require_file(Path(args.source_control), "source control")
    source_bi4 = require_file(Path(args.source_bi4), "source BI4")
    prepared_report_path = require_file(Path(args.prepared_report), "prepared source report")
    prior_support_path = require_file(Path(args.prior_support_report), "root081 support report")
    gencase = require_file(Path(args.gencase), "official GenCase binary")
    output_dir = Path(args.output_dir).expanduser().resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        # The shared runtime owns stdout.log/receipts in the attempt root.  A
        # fresh child namespace is still required so this worker never
        # overwrites a previous output.
        clone_dir = output_dir / "source_clone"
        generated_dir = output_dir / "generated"
    else:
        output_dir.mkdir(parents=True, exist_ok=True)
        clone_dir = output_dir / "source_clone"
        generated_dir = output_dir / "generated"
    if clone_dir.exists() or generated_dir.exists():
        raise FileExistsError("source-clone GenCase child namespace already exists")

    if sha256(source_xml) != EXPECTED_XML_SHA256:
        raise ValueError("source XML digest does not match the exact S2 package")
    if sha256(source_control) != EXPECTED_CONTROL_SHA256:
        raise ValueError("source control digest does not match the exact S2 package")
    prepared = _source_report(prepared_report_path)
    _prior_support_report(prior_support_path)
    source_summary = _xml_summary(source_xml)
    if source_summary["acctimesfile"] != source_control.name:
        raise ValueError("source XML acctimesfile is not the bound control basename")
    if source_summary["dp_m"] != 0.006:
        raise ValueError("S2 source dp changed")

    clone_dir.mkdir(parents=True)
    clone_xml = clone_dir / source_xml.name
    clone_control = clone_dir / source_control.name
    clone_bi4 = clone_dir / source_bi4.name
    copy_fresh(source_xml, clone_xml)
    copy_fresh(source_control, clone_control)
    # The BI4 is not a GenCase input.  It is copied only after the parent
    # deferred-input guard and retained as the source recipe comparison.
    copy_fresh(source_bi4, clone_bi4)
    if sha256(clone_bi4) != EXPECTED_SOURCE_BI4_SHA256:
        raise ValueError("guarded source BI4 digest differs from prepared report")

    generated_dir.mkdir(parents=True)
    prefix = generated_dir / "F3_S2_P1200_AY0750_MATCHED"
    command = [str(gencase), str(clone_xml.with_suffix("")), str(prefix), "-save:all"]
    completed = subprocess.run(command, cwd=clone_dir, capture_output=True, text=True, check=False)
    (output_dir / "gencase.stdout").write_text(completed.stdout, encoding="utf-8")
    (output_dir / "gencase.stderr").write_text(completed.stderr, encoding="utf-8")
    if completed.returncode != 0:
        raise RuntimeError(f"official GenCase failed with return code {completed.returncode}")

    generated_xml = prefix.with_suffix(".xml")
    generated_bi4 = prefix.with_suffix(".bi4")
    if not generated_xml.is_file() or not generated_bi4.is_file():
        raise RuntimeError("official GenCase did not emit both XML and BI4")
    generated = _xml_summary(generated_xml)
    if generated["casedef_canonical"] != source_summary["casedef_canonical"]:
        raise ValueError("fresh GenCase changed the source casedef")
    if generated["particles"].get("fluid") != EXPECTED_FLUID_COUNT:
        raise ValueError("fresh GenCase fluid count does not match S2 source")
    if generated["particles"].get("fixed") != EXPECTED_FIXED_COUNT:
        raise ValueError("fresh GenCase fixed count does not match S2 source")
    if generated["total_particles"] != EXPECTED_TOTAL_COUNT:
        raise ValueError("fresh GenCase total count does not match S2 source")
    if generated["massfluid_kg"] != EXPECTED_MASSFLUID_KG:
        raise ValueError("fresh GenCase MassFluid changed")
    if generated["acctimesfile"] != source_control.name:
        raise ValueError("fresh GenCase lost the S2 control basename")

    owner = ((prepared.get("physical_binding") or {}).get("geometry") or {}).get("initial_fluid")
    owner_size = [float(value) for value in owner["size_m"]]
    owner_volume = owner_size[0] * owner_size[1] * owner_size[2]
    report = {
        "schema": SCHEMA,
        "status": "completed_source_clone_gencase",
        "case_id": "F3_S2_P1200_AY0750_MATCHED_SOURCE",
        "physical_case_id": PHYSICAL_CASE_ID,
        "source_binding": {
            "xml": {"path": str(source_xml), "sha256": EXPECTED_XML_SHA256},
            "control": {"path": str(source_control), "sha256": EXPECTED_CONTROL_SHA256},
            "prepared_source_report": {"path": str(prepared_report_path), "sha256": sha256(prepared_report_path)},
            "prior_root081_support_report": {"path": str(prior_support_path), "sha256": EXPECTED_PRIOR_SUPPORT_SHA256},
            "source_bi4": {
                "path": str(source_bi4),
                "sha256": EXPECTED_SOURCE_BI4_SHA256,
                "read_policy": "parent deferred pre/worker/post guard; copied only after reservation",
            },
            "s1_receipt_used": False,
        },
        "source_clone": {
            "directory": str(clone_dir),
            "xml": {"path": str(clone_xml), "sha256": sha256(clone_xml)},
            "control": {"path": str(clone_control), "sha256": sha256(clone_control)},
            "source_bi4": {"path": str(clone_bi4), "sha256": sha256(clone_bi4)},
        },
        "official_gencase": {
            "binary": str(gencase),
            "command": command,
            "returncode": completed.returncode,
            "output_prefix": str(prefix),
            "generated_xml": generated,
            "generated_bi4": {"path": str(generated_bi4), "sha256": sha256(generated_bi4)},
        },
        "continuous_owner": {
            "status": "SOURCE_DECLARED_CONTINUOUS_OWNER_CONTRACT",
            "low_m": list(owner["low_m"]),
            "size_m": owner_size,
            "volume_m3": owner_volume,
            "density_kg_m3": float((prepared.get("physical_binding") or {}).get("density_kg_m3", 1000.0)),
            "mass_kg": EXPECTED_CONTINUOUS_MASS_KG,
            "note": "This is the continuous owner contract; generated particle fill volume and sample mass are reported separately.",
        },
        "discrete_initial_state": {
            "fluid_particles": generated["particles"].get("fluid"),
            "fixed_particles": generated["particles"].get("fixed"),
            "total_particles": generated["total_particles"],
            "massfluid_kg": generated["massfluid_kg"],
            "sample_fluid_mass_kg": generated["sample_fluid_mass_kg"],
            "sample_mass_minus_continuous_mass_kg": generated["sample_fluid_mass_kg"] - EXPECTED_CONTINUOUS_MASS_KG,
        },
        "scientific_status": {
            "source_control_closed": True,
            "initial_recipe_closed": True,
            "continuous_owner_semantics": "source-contract-only; no solver validation",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "physical_fate": "UNKNOWN",
            "dynamics": "UNKNOWN",
        },
        "execution_scope": {
            "gencase_invoked": True,
            "solver_started": False,
            "gpu_started": False,
            "trajectory_h5_read": False,
            "old_products_modified": False,
        },
    }
    report_path = output_dir / "f3_s2_source_clone_gencase_v1.json"
    if report_path.exists():
        raise FileExistsError(report_path)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    return report


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-xml", required=True)
    p.add_argument("--source-control", required=True)
    p.add_argument("--source-bi4", required=True)
    p.add_argument("--prepared-report", required=True)
    p.add_argument("--prior-support-report", required=True)
    p.add_argument("--gencase", required=True)
    p.add_argument("--output-dir", required=True)
    return p


def main() -> int:
    try:
        result = run(parser().parse_args())
    except Exception as exc:  # shared runner records the failure receipt
        print(f"F3 S2 source-clone GenCase failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps({
        "schema": result["schema"],
        "status": result["status"],
        "case_id": result["case_id"],
        "fluid_particles": result["discrete_initial_state"]["fluid_particles"],
        "continuous_owner_mass_kg": result["continuous_owner"]["mass_kg"],
        "QI": result["scientific_status"]["QI"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
