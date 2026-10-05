#!/usr/bin/env python3
"""Fresh105 Root-owned initial-QA parser.

This is the bounded repair for the fresh104 interface assumptions exposed by
Root397. Official PartVTK output may use comma or semicolon delimiters, and
units may be embedded in header labels (for example ``Pos.x [m]``) or appear
in at most one immediate units row. Scientific predicates remain unchanged.

The source package is disabled. When Root enables a request, this worker may
read a registered CSV or invoke official PartVTK; the source builder and its
tests use only synthetic text fixtures and never read or hash registered
CSV/BI4/DAT/H5 payloads.
"""
from __future__ import annotations

from fresh104_parser_base import *  # noqa: F401,F403

SCHEMA = "ds02.f2.stage1.fresh105.csv-layout-repair-initial-qa.v1"


def stream_csv(path: Path, expected: Mapping[str, Any], expected_csv_sha256: str | None = None) -> dict[str, Any]:
    """Run the fresh104 scientific checks with layout-neutral checks."""
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
        "supported_delimiter": header["delimiter"] in {",", ";"},
        "units_layout_supported": unit_rows in {0, 1},
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
    parser.add_argument("--csv", type=Path, default=None)
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
