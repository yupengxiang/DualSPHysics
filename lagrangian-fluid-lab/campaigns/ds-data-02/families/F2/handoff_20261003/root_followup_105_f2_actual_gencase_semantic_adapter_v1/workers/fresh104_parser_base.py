#!/usr/bin/env python3
"""Root-enabled F2 initial-QA worker with the corrected PartVTK CSV parser.

The old F2 worker passed the first PartVTK preface line to ``DictReader``.
That made the real semicolon header look like a data row, counted the units
row, and reported ``Type/Mk/Idp`` as missing.  This worker locates the typed
header in the stream, selects the semicolon delimiter, skips only the known
single units row, and then performs bounded streaming checks.  It keeps no
particle array in the report.

This file is source-only until Root enables a request.  At execution time it
may either audit a Root-registered existing CSV (``--csv``) or invoke the
official PartVTK producer.  It never runs GenCase, DualSPHysics, a converter,
or a renderer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


SCHEMA = "ds02.f2.stage1.fresh104.csv-parser-repair-initial-qa.v1"
EXPECTED_TIME_MAX = 4.0
EXPECTED_TIME_OUT = 0.01
EXPECTED_DP = 0.01


class QAError(RuntimeError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise QAError(message)


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"JSON object required: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def find_column(headers: Sequence[str], *, exact: Iterable[str] = (), contains: Iterable[str] = ()) -> int | None:
    values = [normalise(header) for header in headers]
    for alias in exact:
        target = normalise(alias)
        for index, value in enumerate(values):
            if value == target:
                return index
    for alias in contains:
        target = normalise(alias)
        for index, value in enumerate(values):
            if target in value:
                return index
    return None


def parse_int(value: str, label: str) -> int:
    number = float(str(value).strip())
    require(math.isfinite(number) and number.is_integer(), f"{label} is not a finite integer: {value!r}")
    return int(number)


def parse_type(value: str) -> str:
    text = str(value).strip().lower()
    aliases = {
        "0": "fixed", "fixed": "fixed",
        "1": "moving", "moving": "moving",
        "2": "floating", "floating": "floating", "body": "floating",
        "3": "fluid", "fluid": "fluid",
    }
    return aliases.get(text, "unknown")


def open_partvtk_rows(path: Path) -> tuple[Any, list[str], Iterator[list[str]], dict[str, Any]]:
    """Find the actual typed header and stream semicolon-separated rows.

    PartVTK writes a textual preface before the header and a units row directly
    after it.  The source of the prior failure was treating the first preface
    line as a DictReader header.  Header discovery is deliberately structural
    and accepts the official spelling variants used by F2/F6/F7.
    """
    handle = path.open("r", encoding="utf-8", errors="replace", newline="")
    for line_number, line in enumerate(handle, start=1):
        lowered = line.lower()
        if "pos.x" not in lowered or "type" not in lowered or "mk" not in lowered or "idp" not in lowered:
            continue
        delimiter = ";" if line.count(";") >= line.count(",") else ","
        reader = csv.reader(itertools.chain([line], handle), delimiter=delimiter)
        try:
            headers = [str(value).strip() for value in next(reader)]
        except StopIteration as exc:
            handle.close()
            raise QAError(f"PartVTK CSV header is empty: {path}") from exc
        required = {
            "x": find_column(headers, contains=("posx",)),
            "y": find_column(headers, contains=("posy",)),
            "z": find_column(headers, contains=("posz",)),
            "vx": find_column(headers, contains=("velx", "velocityx")),
            "vy": find_column(headers, contains=("vely", "velocityy")),
            "vz": find_column(headers, contains=("velz", "velocityz")),
            "idp": find_column(headers, exact=("idp", "particleid", "uid"), contains=("idp",)),
            "type": find_column(headers, exact=("type", "particletype"), contains=("type",)),
            "mk": find_column(headers, exact=("mk", "marker"), contains=("mk",)),
            "mass": find_column(headers, exact=("mass",), contains=("mass",)),
            "density": find_column(headers, exact=("rhop", "density"), contains=("rhop", "density")),
        }
        missing = [name for name, index in required.items() if index is None]
        require(not missing, f"PartVTK CSV header lacks required columns {missing}: {headers}")
        return handle, headers, reader, {
            "header_line_number": line_number,
            "delimiter": delimiter,
            "columns": {name: headers[int(index)] for name, index in required.items()},
            "indices": {name: int(index) for name, index in required.items()},
        }
    handle.close()
    raise QAError(f"typed PartVTK CSV header not found: {path}")


def looks_like_units_row(row: Sequence[str], indices: Mapping[str, int]) -> bool:
    """Recognise the official units row without hiding malformed particles."""
    if not row or not any(str(cell).strip() for cell in row):
        return True
    categorical = [str(row[indices[name]]).strip() for name in ("idp", "type", "mk") if indices[name] < len(row)]
    text = " ".join(str(cell).strip().lower() for cell in row)
    unit_markers = ("[m]", "[kg", "[pa", "[none]", "m/s", "kg/m", "(none)")
    has_numeric_category = any(re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?", value) for value in categorical)
    return not has_numeric_category and any(marker in text for marker in unit_markers)


def run_partvtk(partvtk: Path, bi4: Path, xml: Path, output_dir: Path) -> tuple[Path, dict[str, Any]]:
    output_dir.mkdir(parents=True, exist_ok=False)
    prefix = output_dir / "initial"
    command = [
        str(partvtk), "-filedata", str(bi4), "-filexml", str(xml), "-first:0", "-last:0", "-threads:4",
        "-savecsv", str(prefix), "-onlytype:+all", "-vars:-all,+idp,+vel,+rhop,+type,+mk,+mass,+zone", "-csvsep:1",
    ]
    completed = subprocess.run(command, cwd=output_dir, capture_output=True, text=True, check=False, timeout=1800)
    stdout = output_dir / "partvtk.stdout.log"
    stdout.write_text(completed.stdout + completed.stderr, encoding="utf-8")
    candidates = [path for path in sorted(output_dir.glob("initial*.csv")) if "stats" not in path.name.lower()]
    require(completed.returncode == 0, f"PartVTK failed with returncode={completed.returncode}")
    require(candidates, f"PartVTK did not produce a CSV under {output_dir}")
    return candidates[0], {"command": command, "returncode": completed.returncode, "stdout": str(stdout.resolve()), "stdout_sha256": sha256(stdout)}


def xml_contract(definition: Path) -> dict[str, Any]:
    root = ET.parse(definition).getroot()
    constants = root.find(".//execution/constants") or root.find(".//constants")
    definition_node = root.find(".//casedef/geometry/definition")
    params = {str(node.get("key")): str(node.get("value")) for node in root.findall(".//execution/parameters/parameter")}
    dp = float(definition_node.get("dp", "nan")) if definition_node is not None else float("nan")
    data2d = str(constants.find("data2d").get("value", "") if constants is not None and constants.find("data2d") is not None else "").lower()
    errors: list[str] = []
    if not math.isfinite(dp) or abs(dp - EXPECTED_DP) > 1e-12:
        errors.append(f"dp={dp!r}, expected {EXPECTED_DP}")
    try:
        if abs(float(params.get("TimeMax", "nan")) - EXPECTED_TIME_MAX) > 1e-12:
            errors.append("TimeMax drift")
        if abs(float(params.get("TimeOut", "nan")) - EXPECTED_TIME_OUT) > 1e-12:
            errors.append("TimeOut drift")
    except ValueError:
        errors.append("native time parameters missing")
    if data2d != "false":
        errors.append("generated XML is not 3-D")
    return {"status": "pass" if not errors else "fail", "errors": errors, "path": str(definition.resolve()), "sha256": sha256(definition), "dp_m": dp, "time_max_s": float(params.get("TimeMax", "nan")), "time_out_s": float(params.get("TimeOut", "nan")), "data2d": data2d}


def stream_csv(path: Path, expected: Mapping[str, Any], expected_csv_sha256: str | None = None) -> dict[str, Any]:
    if expected_csv_sha256:
        require(sha256(path) == expected_csv_sha256, f"registered CSV digest mismatch: {path}")
    handle, headers, rows, header = open_partvtk_rows(path)
    indices = header["indices"]
    expected_total = int(expected["total"])
    expected_counts = {str(k): int(v) for k, v in expected["counts"].items()}
    counts: Counter[str] = Counter()
    mk_counts: Counter[str] = Counter()
    ids: set[int] = set()
    parse_errors = 0
    raw_rows = 0
    unit_rows = 0
    data_rows = 0
    finite_rows = 0
    positive_mass_rows = 0
    positive_density_rows = 0
    fluid_ids: set[int] = set()
    try:
        for row in rows:
            raw_rows += 1
            if not any(str(cell).strip() for cell in row):
                continue
            if unit_rows == 0 and looks_like_units_row(row, indices):
                unit_rows += 1
                continue
            if len(row) <= max(indices.values()):
                parse_errors += 1
                continue
            try:
                numeric = [float(row[indices[name]]) for name in ("x", "y", "z", "vx", "vy", "vz", "mass", "density")]
                uid = parse_int(row[indices["idp"]], "Idp")
                kind = parse_type(row[indices["type"]])
                mk = parse_int(row[indices["mk"]], "Mk")
            except (ValueError, TypeError, QAError):
                parse_errors += 1
                continue
            data_rows += 1
            ids.add(uid)
            counts[kind] += 1
            mk_counts[f"{kind}:mk{mk}"] += 1
            if kind == "fluid":
                fluid_ids.add(uid)
            if all(math.isfinite(value) for value in numeric):
                finite_rows += 1
            if math.isfinite(numeric[6]) and numeric[6] > 0:
                positive_mass_rows += 1
            if math.isfinite(numeric[7]) and numeric[7] > 0:
                positive_density_rows += 1
    finally:
        handle.close()
    checks = {
        "header_found_after_preface": header["header_line_number"] > 1,
        "semicolon_delimiter": header["delimiter"] == ";",
        "units_row_skipped_once": unit_rows == 1,
        "row_count_exact_expected_particles": data_rows == expected_total,
        "all_required_rows_parse": parse_errors == 0,
        "all_reported_fields_finite": finite_rows == data_rows == expected_total,
        "particle_ids_unique_complete": len(ids) == expected_total and ids == set(range(expected_total)),
        "positive_type3_fluid": counts.get("fluid", 0) == expected_counts.get("fluid", -1) and len(fluid_ids) == expected_counts.get("fluid", -1),
        "type_partition_matches_prepared_counts": all(counts.get(key, 0) == value for key, value in expected_counts.items()),
        "positive_mass_all_rows": positive_mass_rows == data_rows,
        "positive_density_all_rows": positive_density_rows == data_rows,
    }
    return {
        "status": "pass" if all(checks.values()) else "fail",
        "csv": {"path": str(path.resolve()), "sha256": sha256(path), "bytes": path.stat().st_size},
        "header": {"line_number": header["header_line_number"], "delimiter": header["delimiter"], "columns": header["columns"]},
        "raw_rows_seen_after_header": raw_rows,
        "unit_rows_skipped": unit_rows,
        "data_rows": data_rows,
        "row_count": data_rows,
        "parse_errors": parse_errors,
        "finite_row_count": finite_rows,
        "unique_id_count": len(ids),
        "fluid_type3_count": counts.get("fluid", 0),
        "fluid_unique_id_count": len(fluid_ids),
        "type_counts": dict(sorted(counts.items())),
        "mk_counts": dict(sorted(mk_counts.items())),
        "checks": checks,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--definition", required=True, type=Path)
    parser.add_argument("--gencase-receipt", required=True, type=Path)
    parser.add_argument("--prepared-input-report", required=True, type=Path)
    parser.add_argument("--runtime-evidence", required=True, type=Path)
    parser.add_argument("--partvtk", required=True, type=Path)
    parser.add_argument("--partvtk-output-dir", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--csv", type=Path, default=None, help="Root-registered existing PartVTK CSV; skips producer invocation")
    parser.add_argument("--expected-csv-sha256", default=None)
    args = parser.parse_args()

    receipt = load_json(args.gencase_receipt)
    report = load_json(args.prepared_input_report)
    evidence = load_json(args.runtime_evidence)
    require(receipt.get("status") == "completed" and receipt.get("returncode") == 0, "raw GenCase receipt is not completed/0")
    require(evidence.get("contract_checks", {}).get("root353_solver_dimension_three") is True, "3-D producer evidence is missing")
    counts = report.get("generated_xml_particle_counts")
    total = report.get("actual_total_particles")
    require(isinstance(counts, dict) and isinstance(total, int) and total == sum(int(counts.get(k, 0)) for k in ("fixed", "moving", "floating", "fluid")), "prepared count closure failed")
    xml = xml_contract(args.definition)
    if args.csv is None:
        bi4 = Path(str(report.get("prefix", "")) + ".bi4")
        csv_path, producer = run_partvtk(args.partvtk, bi4, args.definition, args.partvtk_output_dir)
    else:
        csv_path = args.csv.resolve()
        require(csv_path.is_file(), f"registered CSV is missing: {csv_path}")
        producer = {"mode": "registered_existing_csv", "returncode": 0, "read_or_hashed_by_root_worker": True}
    csv_summary = stream_csv(csv_path, {"counts": counts, "total": total}, args.expected_csv_sha256)
    checks = {"actual_gencase_terminal_success": True, "actual_initial_csv_available": csv_path.is_file(), "source_xml_contract": xml["status"] == "pass", **csv_summary["checks"]}
    output = {
        "schema": SCHEMA,
        "case_id": args.case_id,
        "status": "pass" if all(checks.values()) else "fail",
        "claim": "actual bounded initial QA only; no solver, visual, precision, Q-N or production claim",
        "checks": checks,
        "gencase_receipt": {"path": str(args.gencase_receipt.resolve()), "sha256": sha256(args.gencase_receipt), "status": receipt.get("status"), "returncode": receipt.get("returncode"), "raw_receipt_immutable": True},
        "prepared_evidence": {"path": str(args.prepared_input_report.resolve()), "sha256": sha256(args.prepared_input_report), "counts": counts, "total": total, "dimension": 3},
        "xml_contract": xml,
        "partvtk": producer,
        "csv_summary": csv_summary,
        "semantic_adapter": {"dimension": 3, "source": "fresh102/root353 prepared producer evidence", "raw_receipt_rewritten": False},
        "source_only_worker": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if output["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
