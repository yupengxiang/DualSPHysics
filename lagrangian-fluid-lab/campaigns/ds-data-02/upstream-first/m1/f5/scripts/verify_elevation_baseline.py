#!/usr/bin/env python3
"""Audit the frozen F5 elevation baseline without changing comparison outputs.

This is a small read-only audit.  It records the official XML depth, the
MeasureTool PosZ metadata and first native elevation row, and the first
official ODS eta values.  It does not inspect native particle arrays and does
not choose a baseline from any comparison metric.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from xml.etree import ElementTree as ET


TABLE_NS = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
TEXT_NS = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
OFFICE_NS = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
TABLE = "{" + TABLE_NS + "}"
TEXT = "{" + TEXT_NS + "}"
OFFICE = "{" + OFFICE_NS + "}"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def number(value: object) -> Optional[float]:
    if value is None:
        return None
    text = str(value).strip().replace("\ufeff", "")
    if not text:
        return None
    try:
        result = float(text.replace(",", "."))
    except ValueError:
        return None
    return result if math.isfinite(result) else None


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", value.casefold())).strip()


def read_measuretool(path: Path) -> Dict[str, object]:
    with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as stream:
        rows = [row for row in csv.reader(stream, delimiter=";") if any(cell.strip() for cell in row)]
    posx_row = next((row for row in rows if any("posx" in normalize(cell) for cell in row)), None)
    posz_row = next((row for row in rows if any("posz" in normalize(cell) for cell in row)), None)
    header_index = next(
        (i for i, row in enumerate(rows) if row and normalize(row[0]) == "part"), None
    )
    if posx_row is None or posz_row is None or header_index is None:
        raise ValueError(f"missing PosX/PosZ/Part metadata in {path}")
    header = rows[header_index]
    body = rows[header_index + 1 :]
    first = next((row for row in body if len(row) >= len(header) and number(row[0]) is not None), None)
    if first is None:
        raise ValueError(f"no numeric first native row in {path}")
    positions: Dict[str, float] = {}
    elevations: Dict[str, float] = {}
    for index, cell in enumerate(posx_row):
        x = number(cell)
        if x in (5.0, 6.0, 7.0):
            key = f"x{int(x)}"
            positions[key] = x
            if index >= len(posz_row) or index >= len(first):
                raise ValueError(f"metadata/data column {index} missing for {key}")
            z = number(posz_row[index])
            value = number(first[index])
            if z is None or value is None:
                raise ValueError(f"non-numeric PosZ/first elevation for {key}")
            elevations[key] = value
    if set(positions) != {"x5", "x6", "x7"}:
        raise ValueError(f"expected x=5,6,7 metadata, found {positions}")
    return {
        "path": str(path),
        "sha256": sha256(path),
        "header_row_zero_based": header_index,
        "header": header,
        "first_native_part": int(float(first[0])),
        "first_native_time_s": number(first[1]),
        "metadata_positions_m": positions,
        "metadata_posz_m": {key: number(posz_row[index]) for key, index in ((key, next(i for i, cell in enumerate(posx_row) if number(cell) == x)) for key, x in positions.items())},
        "first_native_elevation_m": elevations,
    }


def read_depth(xml_path: Path) -> Dict[str, object]:
    root = ET.parse(xml_path).getroot()
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1].casefold() == "depth" and "value" in element.attrib:
            value = number(element.attrib["value"])
            if value is not None:
                return {"path": str(xml_path), "sha256": sha256(xml_path), "depth_m": value}
    raise ValueError(f"no depth value found in {xml_path}")


def ods_cell_text(cell: ET.Element) -> str:
    text = "".join(cell.itertext()).strip()
    if text:
        return text
    return cell.get(OFFICE + "value", "")


def read_ods_first_eta(ods_path: Path) -> Dict[str, object]:
    with zipfile.ZipFile(ods_path) as archive:
        root = ET.fromstring(archive.read("content.xml"))
    sheet = next(
        (element for element in root.findall(".//" + TABLE + "table") if element.get(TABLE + "name") == "REGULAR_BEACH"),
        None,
    )
    if sheet is None:
        raise ValueError("REGULAR_BEACH sheet not found")
    rows: List[List[str]] = []
    for row_element in sheet.findall(TABLE + "table-row"):
        row: List[str] = []
        for cell in row_element.findall(TABLE + "table-cell"):
            value = ods_cell_text(cell)
            repeat = int(cell.get(TABLE + "number-columns-repeated", "1"))
            row.extend([value] * min(repeat, 32 - len(row)))
            if len(row) >= 32:
                break
        rows.append(row)
        if len(rows) >= 12:
            break
    header_index = next((i for i, row in enumerate(rows) if any("ETA_2ndStokes" in cell for cell in row)), None)
    if header_index is None:
        raise ValueError("ODS theory eta header not found")
    header = rows[header_index]
    eta_columns = {
        "theory_eta": next(i for i, cell in enumerate(header) if "ETA_2ndStokes" in cell),
        "sph_eta_x5": next(i for i, cell in enumerate(header) if "ETA_SPH(x=5m)" in cell),
        "sph_eta_x6": next(i for i, cell in enumerate(header) if "ETA_SPH(x=6m)" in cell),
        "sph_eta_x7": next(i for i, cell in enumerate(header) if "ETA_SPH(x=7m)" in cell),
    }
    first = next((row for row in rows[header_index + 1 :] if number(row[0]) is not None), None)
    if first is None:
        raise ValueError("ODS has no first numeric data row")
    return {
        "path": str(ods_path),
        "sha256": sha256(ods_path),
        "sheet": "REGULAR_BEACH",
        "header_row_zero_based": header_index,
        "first_time_s": number(first[0]),
        "first_eta": {key: number(first[index]) for key, index in eta_columns.items()},
        "headers": {key: header[index] for key, index in eta_columns.items()},
    }


def build_report(csv_path: Path, xml_path: Path, ods_path: Path) -> Dict[str, object]:
    measure = read_measuretool(csv_path)
    depth = read_depth(xml_path)
    ods = read_ods_first_eta(ods_path)
    first = measure["first_native_elevation_m"]
    posz = measure["metadata_posz_m"]
    nominal_depth = depth["depth_m"]
    eta_from_first = {key: first[key] - first[key] for key in first}
    eta_from_nominal = {key: first[key] - nominal_depth for key in first}
    posz_offset = {key: posz[key] - nominal_depth for key in posz}
    return {
        "schema": "ds-data-02.upstream-first.f5-elevation-baseline-audit.v1",
        "status": "audit_only",
        "inputs": {"measuretool_elevation": measure, "official_case_xml": depth, "official_ods": ods},
        "frozen_transform": {
            "formula": "eta_m = MeasureTool Elevation_m - first native sample at the same probe",
            "reason": "MeasureTool PosZ and the first native values identify the sampled still-water surface; the XML depth is a control parameter, not a replacement probe baseline.",
            "comparison_metric_not_used_to_choose_baseline": True,
        },
        "cached_values": {
            "measuretool_posz_minus_xml_depth_m": posz_offset,
            "eta_at_first_native_sample_using_frozen_formula_m": eta_from_first,
            "eta_at_first_native_sample_if_xml_depth_were_subtracted_m": eta_from_nominal,
            "ods_first_eta_m": ods["first_eta"],
        },
        "conclusion": {
            "frozen_first_sample_baseline_supported": all(abs(value) <= 1e-15 for value in eta_from_first.values()),
            "xml_depth_subtraction_would_introduce_constant_offset_m": nominal_depth - next(iter(first.values())),
            "ods_eta_zero_at_first_row": all(abs(value or 0.0) <= 1e-15 for value in ods["first_eta"].values()),
            "rmse_retuning_performed": False,
        },
    }


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elevation", type=Path, required=True)
    parser.add_argument("--xml", type=Path, required=True)
    parser.add_argument("--ods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    for path in (args.elevation, args.xml, args.ods):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    if args.output.exists():
        parser.error(f"output already exists: {args.output}")
    report = build_report(args.elevation, args.xml, args.ods)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
