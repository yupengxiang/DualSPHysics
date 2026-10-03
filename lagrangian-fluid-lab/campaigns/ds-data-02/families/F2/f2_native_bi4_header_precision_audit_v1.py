#!/usr/bin/env python3
"""DS-DATA-02 Family F2: Native BI4 Header Precision Audit Script v1.

Narrowly scoped, metered audit script for inspecting BI4 frame 0 header
constants (MassFluid, MassBound, Dp, Rhop0, Gamma, B) directly from binary
files without unmetered solver, PartVTK, or conversion executions.

Schema: ds-data-02.f2.bi4-header-precision-audit.v1
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
from typing import Any, BinaryIO, Mapping

SCHEMA = "ds-data-02.f2.bi4-header-precision-audit.v1"
HEADER_PREFIX = b"#FileJBD JPartDataBi4"
CODE_ITEM = b"\nITEM\n"
CODE_VALUES = b"\nVALUES"

# JBinaryDataDef::TpData enum code for DatDouble
TYPE_DOUBLE = 12
TYPE_FLOAT = 11


def read_string(stream: BinaryIO) -> str:
    """Read a length-prefixed UTF-8 string (uint32 length followed by bytes)."""
    raw_len = stream.read(4)
    if len(raw_len) < 4:
        raise ValueError("Unexpected EOF reading string length")
    length = struct.unpack("<I", raw_len)[0]
    data = stream.read(length)
    if len(data) < length:
        raise ValueError("Unexpected EOF reading string payload")
    return data.decode("utf-8", errors="replace")


def parse_bi4_header_constants(bi4_path: Path) -> dict[str, Any]:
    """Parse simulation constants from the root Item Values block of a BI4 file.
    
    This function reads only the initial header bytes necessary to inspect
    metadata values, strictly avoiding particle array materialization.
    """
    if not bi4_path.is_file():
        raise FileNotFoundError(f"BI4 file not found: {bi4_path}")

    file_size = bi4_path.stat().st_size
    with open(bi4_path, "rb") as f:
        # Check header magic (64 bytes)
        magic = f.read(64)
        if not magic.startswith(HEADER_PREFIX):
            raise ValueError(f"Invalid BI4 magic header: {magic[:32]!r}")

        # Root Item definition size
        raw_def_len = f.read(4)
        if len(raw_def_len) < 4:
            raise ValueError("Premature EOF at root item definition length")
        def_len = struct.unpack("<I", raw_def_len)[0]

        # Root item marker
        item_code = read_string(f)
        if item_code.encode("utf-8") != CODE_ITEM:
            raise ValueError(f"Expected ITEM marker, got: {item_code!r}")

        item_name = read_string(f)
        item_hidden = struct.unpack("<i", f.read(4))[0]
        hide_values = struct.unpack("<i", f.read(4))[0]
        fmt_float = read_string(f)
        fmt_double = read_string(f)
        num_arrays = struct.unpack("<I", f.read(4))[0]
        num_items = struct.unpack("<I", f.read(4))[0]
        values_bytes = struct.unpack("<I", f.read(4))[0]

        values: dict[str, dict[str, Any]] = {}
        if values_bytes > 0:
            val_code = read_string(f)
            if val_code.encode("utf-8") != CODE_VALUES:
                raise ValueError(f"Expected VALUES marker, got: {val_code!r}")
            num_vals = struct.unpack("<I", f.read(4))[0]

            for _ in range(num_vals):
                val_name = read_string(f)
                val_type = struct.unpack("<i", f.read(4))[0]

                if val_type == TYPE_DOUBLE:
                    payload = f.read(8)
                    if len(payload) < 8:
                        raise ValueError(f"Premature EOF reading double {val_name}")
                    d_val = struct.unpack("<d", payload)[0]
                    f32_val = struct.unpack("<f", struct.pack("<f", float(d_val)))[0]
                    f32_hex = struct.pack("<f", f32_val).hex()
                    values[val_name] = {
                        "type_code": val_type,
                        "type_name": "DatDouble",
                        "byte_length": 8,
                        "double_value": d_val,
                        "float32_value": f32_val,
                        "float32_hex": f32_hex,
                        "payload_hex": payload.hex(),
                    }
                elif val_type == TYPE_FLOAT:
                    payload = f.read(4)
                    f_val = struct.unpack("<f", payload)[0]
                    values[val_name] = {
                        "type_code": val_type,
                        "type_name": "DatFloat",
                        "byte_length": 4,
                        "float32_value": f_val,
                        "payload_hex": payload.hex(),
                    }
                elif val_type == 1:  # Text
                    t_val = read_string(f)
                    values[val_name] = {"type_code": val_type, "type_name": "DatText", "text_value": t_val}
                elif val_type in (2, 7, 8):  # Bool, Int, Uint
                    payload = f.read(4)
                    i_val = struct.unpack("<i" if val_type in (2, 7) else "<I", payload)[0]
                    values[val_name] = {"type_code": val_type, "type_name": "DatInt", "int_value": i_val}
                elif val_type in (9, 10):  # Llong, Ullong
                    payload = f.read(8)
                    ll_val = struct.unpack("<q" if val_type == 9 else "<Q", payload)[0]
                    values[val_name] = {"type_code": val_type, "type_name": "DatUllong", "int_value": ll_val}
                elif val_type == 23:  # Double3
                    payload = f.read(24)
                    d3_val = struct.unpack("<ddd", payload)
                    values[val_name] = {"type_code": val_type, "type_name": "DatDouble3", "double3_value": list(d3_val)}
                else:
                    # Skip other types according to their sizes if known
                    # For header constants, the critical variables are all DatDouble (type 12)
                    pass

    return {
        "file_size_bytes": file_size,
        "root_item_name": item_name,
        "fmt_float": fmt_float,
        "fmt_double": fmt_double,
        "constants": values,
    }


def audit_bi4_case_precision(
    case_id: str,
    resolution: str,
    dp_m: float,
    xml_decimal_mass_kg: float,
    bi4_path: Path,
) -> dict[str, Any]:
    """Audit mass precision for a single BI4 frame."""
    parsed = parse_bi4_header_constants(bi4_path)
    constants = parsed["constants"]

    mass_fluid_record = constants.get("MassFluid")
    if not mass_fluid_record:
        raise ValueError(f"BI4 file lacks MassFluid constant: {bi4_path}")

    d_val = mass_fluid_record["double_value"]
    f32_val = mass_fluid_record["float32_value"]
    f32_hex = mass_fluid_record["float32_hex"]

    delta_to_xml = d_val - xml_decimal_mass_kg
    rel_delta_to_xml = delta_to_xml / xml_decimal_mass_kg if xml_decimal_mass_kg > 0 else 0.0

    return {
        "case_id": case_id,
        "resolution": resolution,
        "dp_m": dp_m,
        "bi4_path": str(bi4_path),
        "xml_decimal_reference_mass_kg": xml_decimal_mass_kg,
        "header_mass_fluid_double": d_val,
        "header_mass_fluid_float32": f32_val,
        "header_mass_fluid_float32_hex": f32_hex,
        "bi4_type_code": mass_fluid_record["type_code"],
        "delta_to_xml_continuous_kg": delta_to_xml,
        "relative_delta_to_xml_continuous": rel_delta_to_xml,
        "fmt_double": parsed["fmt_double"],
        "other_constants": {
            k: v.get("double_value", v.get("int_value"))
            for k, v in constants.items()
            if k in ("Dp", "H", "B", "Rhop0", "Gamma", "MassBound")
        },
    }


def run_audit(config_path: Path, output_dir: Path) -> dict[str, Any]:
    """Execute the precision audit according to configuration."""
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    output_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, Any] = {}

    cases = config.get("cases", {})
    for case_key, case_info in cases.items():
        bi4_file = Path(case_info["bi4_path"])
        res_audit = audit_bi4_case_precision(
            case_id=case_info["case_id"],
            resolution=case_info["resolution"],
            dp_m=case_info["dp_m"],
            xml_decimal_mass_kg=case_info["xml_decimal_mass_kg"],
            bi4_path=bi4_file,
        )
        results[case_key] = res_audit

    report = {
        "schema": SCHEMA,
        "config_path": str(config_path),
        "results": results,
        "audit_policy_conclusions": {
            "bitwise_payload_invariance_is_not_physical_zero_defect": True,
            "rescaling_and_normalization_forbidden": True,
            "v6_labels_ledger_uses_xml_decimal_weights": True,
            "native_weight_bitwise_label_mass_pass_claimable": False,
        },
    }

    report_path = output_dir / "f2_native_bi4_header_precision_audit_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit native BI4 header mass precision")
    parser.add_argument("--config", type=Path, required=True, help="Path to audit config JSON")
    parser.add_argument("--output-dir", type=Path, required=True, help="Output directory")
    args = parser.parse_args()

    run_audit(args.config, args.output_dir)
    print("F2 Native BI4 Header Precision Audit completed successfully.")


if __name__ == "__main__":
    main()
