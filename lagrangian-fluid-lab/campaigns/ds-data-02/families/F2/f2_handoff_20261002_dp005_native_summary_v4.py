#!/usr/bin/env python3
"""Run the compact DP005 summary with detailed typed fluid source ranges."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import xml.etree.ElementTree as ET


FAMILY_ROOT = Path(__file__).resolve().parent
V3_SCRIPT = FAMILY_ROOT / "f2_handoff_20261002_dp005_native_summary_v3.py"


def import_v3():
    spec = importlib.util.spec_from_file_location("f2_dp005_summary_v3", V3_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {V3_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def detailed_ranges(xml_path: Path):
    module = import_v3()
    root = ET.parse(xml_path).getroot()
    summary = root.find(".//particles/_summary")
    if summary is None:
        raise module.SummaryError(f"generated XML has no particles summary: {xml_path}")
    ranges = []
    for tag, type_id in (("fixed", 0), ("moving", 1)):
        for node in summary.findall(f"./{tag}"):
            low, high = (int(value) for value in str(node.attrib["id"]).split("-", 1))
            ranges.append({"low": low, "high": high, "type": type_id, "mk_values": [int(value) for value in str(node.attrib.get("mkvalues", "")).split("-") if value], "source": tag})
    for node in root.findall(".//particles/fluid"):
        if "begin" not in node.attrib or "count" not in node.attrib or "mk" not in node.attrib:
            continue
        low = int(node.attrib["begin"])
        count = int(node.attrib["count"])
        ranges.append({"low": low, "high": low + count - 1, "type": 3, "mk_values": [int(node.attrib["mk"])], "source": "fluid"})
    if not ranges:
        raise module.SummaryError(f"generated XML has no detailed particle ranges: {xml_path}")
    return ranges


def _install_detailed(base):
    base.parse_ranges = detailed_ranges
    return base


if __name__ == "__main__":
    # Capture v3's original importer before replacing it, then run the exact
    # same CLI/report logic with the detailed XML range resolver.
    v3 = import_v3()
    original_import = v3.import_v1
    v3.import_v1 = lambda: _install_detailed(original_import())
    raise SystemExit(v3.main())
