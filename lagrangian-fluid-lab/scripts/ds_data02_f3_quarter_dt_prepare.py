#!/usr/bin/env python3
"""Prepare a co-located root-only F3 quarter-dt solver input.

This is a bounded CPU preparation step.  It copies the frozen HALF_DT BI4 and
control bytes and makes an additive XML whose only numeric changes are
DtIni, DtMin and DtFixed.  It never invokes GenCase, DualSPHysics, PartVTK or
GPU code, and it does not modify any source or consumed attempt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import resource
import shutil
from typing import Any


PHYSICAL_BINDING_SHA = "fdb645e24952ed2f41225ca537d067d0233c9a94746fd4af0c390205736c9b10"
CONTROL_SHA = "98cb5a00395301e4e5561d57b8d56189686f468a16f0b4420c6f96c3e4995e6b"
EXPECTED_QUARTER_DT = 5.53067421676747e-06
EXPECTED_SAVE = 0.0025
EXPECTED_TMAX = 10.0
PATCH_KEYS = ("DtIni", "DtMin", "DtFixed")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def usage() -> dict[str, float]:
    out: dict[str, float] = {}
    for who, label in ((resource.RUSAGE_SELF, "self"), (resource.RUSAGE_CHILDREN, "children")):
        value = resource.getrusage(who)
        out[f"{label}_user_seconds"] = float(value.ru_utime)
        out[f"{label}_system_seconds"] = float(value.ru_stime)
        out[f"{label}_max_rss_kib"] = float(value.ru_maxrss)
    return out


def _parameter_values(text: str) -> dict[str, str]:
    return {
        key: match.group(1)
        for key in ("DtIni", "DtMin", "DtFixed", "DtFixedFile", "TimeOut", "TimeMax")
        for match in [re.search(rf'<parameter key="{key}" value="([^"]*)"', text)]
        if match is not None
    }


def _patch_parameter(text: str, key: str, value: str) -> str:
    pattern = rf'(<parameter key="{re.escape(key)}" value=")[^"]*(")'
    updated, count = re.subn(pattern, rf"\g<1>{value}\g<2>", text, count=1)
    if count != 1:
        raise ValueError(f"expected one XML parameter {key}, got {count}")
    return updated


def prepare(*, source_xml: Path, source_bi4: Path, source_control: Path,
            output_dir: Path, output_report: Path, case_id: str,
            quarter_dt: float = EXPECTED_QUARTER_DT) -> dict[str, Any]:
    source_xml = source_xml.resolve()
    source_bi4 = source_bi4.resolve()
    source_control = source_control.resolve()
    output_dir = output_dir.resolve()
    output_report = output_report.resolve()
    for path in (source_xml, source_bi4, source_control):
        if not path.is_file():
            raise FileNotFoundError(path)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"refusing to reuse nonempty output directory: {output_dir}")
    if output_report.exists():
        raise FileExistsError(f"refusing to overwrite report: {output_report}")
    if quarter_dt <= 0:
        raise ValueError("quarter_dt must be positive")
    if sha256(source_control) != CONTROL_SHA:
        raise ValueError("source control hash differs from the frozen owner control")

    source_text = source_xml.read_text()
    before = _parameter_values(source_text)
    for key in ("TimeOut", "TimeMax", "DtFixedFile"):
        if key not in before:
            raise ValueError(f"source XML lacks required parameter {key}")
    if abs(float(before["TimeOut"]) - EXPECTED_SAVE) > 1e-12:
        raise ValueError(f"source save interval is not the registered .0025 s: {before['TimeOut']}")
    if abs(float(before["TimeMax"]) - EXPECTED_TMAX) > 1e-12:
        raise ValueError(f"source time window is not the registered 10 s: {before['TimeMax']}")
    if before["DtFixedFile"].upper() != "NONE":
        raise ValueError("quarter-dt input requires DtFixedFile=NONE")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_xml = output_dir / f"{case_id}.xml"
    output_bi4 = output_dir / f"{case_id}.bi4"
    output_control = output_dir / source_control.name
    patched = source_text
    for key in PATCH_KEYS:
        patched = _patch_parameter(patched, key, format(quarter_dt, ".17g"))
    after = _parameter_values(patched)
    for key, value in before.items():
        if key not in PATCH_KEYS and after.get(key) != value:
            raise ValueError(f"unexpected nonnumeric XML change for {key}: {value!r} -> {after.get(key)!r}")
    output_xml.write_text(patched)
    shutil.copyfile(source_bi4, output_bi4)
    shutil.copyfile(source_control, output_control)
    if sha256(output_bi4) != sha256(source_bi4) or sha256(output_control) != CONTROL_SHA:
        raise ValueError("co-located BI4/control copy hash mismatch")

    report = {
        "schema": "ds02.f3.quarter-dt-prepared-input.v1",
        "case_id": case_id,
        "physical_case_id": "F3_DUAL_AXIS_WEAK_006G_004G",
        "variant_id": "quarter_dt_same_save",
        "claim_boundary": "CPU input preparation only; no GenCase, solver, GPU, conversion, Q-N, or production claim.",
        "physical_binding_sha256": PHYSICAL_BINDING_SHA,
        "source_control_sha256": CONTROL_SHA,
        "source_inputs": {
            "xml": {"path": str(source_xml), "sha256": sha256(source_xml), "bytes": source_xml.stat().st_size},
            "bi4": {"path": str(source_bi4), "sha256": sha256(source_bi4), "bytes": source_bi4.stat().st_size},
            "control": {"path": str(source_control), "sha256": sha256(source_control), "bytes": source_control.stat().st_size},
        },
        "outputs": {
            "xml": {"path": str(output_xml), "sha256": sha256(output_xml), "bytes": output_xml.stat().st_size},
            "bi4": {"path": str(output_bi4), "sha256": sha256(output_bi4), "bytes": output_bi4.stat().st_size},
            "control": {"path": str(output_control), "sha256": sha256(output_control), "bytes": output_control.stat().st_size},
            "prepared_prefix": str(output_dir / case_id),
        },
        "numeric_parameters": {
            "source": before,
            "patched": after,
            "changed_keys": list(PATCH_KEYS),
            "quarter_dt_s": quarter_dt,
            "save_interval_s": EXPECTED_SAVE,
            "time_window_s": [0.0, EXPECTED_TMAX],
            "expected_saved_frames": 4001,
            "expected_steps_approx": 1808098,
        },
        "co_location": {
            "xml_bi4_same_directory": output_xml.parent == output_bi4.parent,
            "xml_control_same_directory": output_xml.parent == output_control.parent,
            "relative_control_filename": output_control.name,
        },
        "resource_usage": usage(),
        "source_immutability": True,
        "q_n_status": "not_assessed",
        "production_status": "not_accepted",
    }
    output_report.parent.mkdir(parents=True, exist_ok=True)
    output_report.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-xml", type=Path, required=True)
    parser.add_argument("--source-bi4", type=Path, required=True)
    parser.add_argument("--source-control", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--output-report", type=Path, required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--quarter-dt", type=float, default=EXPECTED_QUARTER_DT)
    args = parser.parse_args()
    report = prepare(**vars(args))
    print(json.dumps({"schema": report["schema"], "outputs": report["outputs"], "numeric_parameters": report["numeric_parameters"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
