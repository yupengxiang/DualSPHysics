#!/usr/bin/env python3
"""Prove per-source-MK native mass denominators from conversion metadata.

The v3 screen allocated the scan's aggregate typed mass by XML source-MK
counts.  This forward-only enrichment consumes the already completed
conversion report and its execution receipt, then checks the producer's
typed identity blocks, float32 mass extrema, XML ranges, and scan receipt
hashes.  It does not open trajectory HDF5 and does not alter v3/v4 sidecars.

This v5 forward-only revision accepts a producer receipt whose interpreter
was recorded through a symlink under a different path (for example the venv
Python versus ``/usr/bin/python3.10``) only when the paths resolve to the same
filesystem target and the declared/launch/end digest is identical.  The
alias is retained in the output evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ds_data02_runtime_v2 import atomic_json
from ds_data02_stage2_omission_task_impact_v3 import assess as assess_v3
from ds_data02_stage2_omission_task_impact_v2 import EvidenceError


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def binding(path: Path) -> dict:
    path = Path(path)
    stat = path.stat()
    return {"path": str(path), "sha256": sha256(path), "bytes": stat.st_size}


def _require(path: Path, label: str) -> Path:
    path = Path(path)
    if not path.is_file():
        raise EvidenceError(f"{label} is missing: {path}")
    return path


def _command_value(command: list[str], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if value == flag:
            return command[index + 1]
    raise EvidenceError(f"conversion receipt is missing {flag}")


def _canonical_path(path: str | Path) -> str:
    return str(Path(path).resolve(strict=False))


def _canonical_digest_map(mapping: dict, label: str) -> dict[str, tuple[str, str]]:
    result: dict[str, tuple[str, str]] = {}
    for raw_path, digest in mapping.items():
        key = _canonical_path(raw_path)
        previous = result.get(key)
        if previous is not None and previous[1] != digest:
            raise EvidenceError(f"{label} has conflicting aliases for {key}")
        result[key] = (str(raw_path), digest)
    return result


def _stable_receipt_inputs(receipt: dict) -> tuple[list[str], list[dict[str, str]]]:
    files = [Path(value) for value in receipt.get("request", {}).get("input_files", [])]
    declared = receipt.get("request", {}).get("input_sha256", {})
    launch = receipt.get("input_hashes_at_launch", {})
    finish = receipt.get("input_hashes_after_run", {})
    if not files:
        raise EvidenceError("conversion receipt input digest map is incomplete")
    file_keys = {_canonical_path(path) for path in files}
    declared_by_canonical = _canonical_digest_map(declared, "declared input digest map")
    launch_by_canonical = _canonical_digest_map(launch, "launch input digest map")
    finish_by_canonical = _canonical_digest_map(finish, "end input digest map")
    if set(declared_by_canonical) != file_keys:
        raise EvidenceError("conversion receipt input digest map is incomplete")
    unobserved = []
    aliases: list[dict[str, str]] = []
    for path in files:
        key = str(path)
        canonical = _canonical_path(path)
        declared_key, declared_digest = declared_by_canonical[canonical]
        launch_entry = launch_by_canonical.get(canonical)
        finish_entry = finish_by_canonical.get(canonical)
        launch_digest = None if launch_entry is None else launch_entry[1]
        finish_digest = None if finish_entry is None else finish_entry[1]
        if launch_digest is None and finish_digest is None:
            unobserved.append(key)
            continue
        if (launch_digest is None or finish_digest is None or
                declared_digest != launch_digest or declared_digest != finish_digest):
            raise EvidenceError(f"conversion input digest changed: {path}")
        observed_keys = {declared_key}
        if launch_entry is not None:
            observed_keys.add(launch_entry[0])
        if finish_entry is not None:
            observed_keys.add(finish_entry[0])
        if any(value != key for value in observed_keys):
            aliases.append({
                "input_file": key,
                "canonical_path": canonical,
                "declared_path": declared_key,
                "launch_path": launch_entry[0] if launch_entry is not None else "",
                "end_path": finish_entry[0] if finish_entry is not None else "",
                "sha256": declared_digest,
            })
    return unobserved, aliases


def _scan_and_conversion(sidecar: dict, conversion_path: Path,
                         conversion_receipt_path: Path) -> tuple[dict, dict, dict, dict, Path]:
    source = sidecar.get("source_provenance", {})
    scan_info = sidecar.get("scan", {})
    scan_path = _require(Path(scan_info.get("path", "")), "bound scan")
    scan = json.loads(scan_path.read_text())
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise EvidenceError("bound scan schema is unsupported")
    if scan.get("physical_case_id") != sidecar.get("physical_case_id"):
        raise EvidenceError("bound scan physical identity differs from sidecar")
    if sha256(scan_path) != scan_info.get("sha256"):
        raise EvidenceError("bound scan digest differs from sidecar")
    scan_receipt_path = scan_path.parent / "execution-receipt.json"
    scan_receipt = json.loads(_require(scan_receipt_path, "scan receipt").read_text())
    if scan_receipt.get("status") != "completed" or scan_receipt.get("returncode") != 0:
        raise EvidenceError("bound scan receipt is not completed")
    scan_request = scan_receipt.get("request", {})
    trajectory = Path(scan.get("trajectory", ""))
    if trajectory not in [Path(value) for value in scan_request.get("input_files", [])]:
        raise EvidenceError("scan receipt does not bind trajectory")
    trajectory_key = str(trajectory)
    if (scan_request.get("input_sha256", {}).get(trajectory_key) !=
            scan_receipt.get("input_hashes_at_launch", {}).get(trajectory_key) or
            scan_request.get("input_sha256", {}).get(trajectory_key) !=
            scan_receipt.get("input_hashes_after_run", {}).get(trajectory_key)):
        raise EvidenceError("scan trajectory launch/end hashes differ")
    conversion_path = _require(conversion_path, "conversion report")
    conversion = json.loads(conversion_path.read_text())
    if conversion.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or conversion.get("conversion_status") != "completed":
        raise EvidenceError("conversion report is not completed direct conversion")
    provenance = conversion.get("source_provenance", {})
    if provenance.get("data_root") != source.get("data_root"):
        raise EvidenceError("conversion data_root differs from native join source")
    for field in ("generated_xml", "solver_receipt", "gencase_receipt"):
        if source.get(field, {}).get("path") != provenance.get(field, {}).get("path"):
            raise EvidenceError(f"conversion {field} differs from native join source")
    if conversion.get("output_hdf5") != str(trajectory):
        raise EvidenceError("conversion output HDF5 differs from scan trajectory")
    if conversion.get("output_sha256") != scan_request.get("input_sha256", {}).get(trajectory_key):
        raise EvidenceError("conversion output hash differs from scan launch hash")
    if (conversion.get("output_sha256") != scan_receipt.get("input_hashes_at_launch", {}).get(trajectory_key) or
            conversion.get("output_sha256") != scan_receipt.get("input_hashes_after_run", {}).get(trajectory_key)):
        raise EvidenceError("conversion output hash differs from scan receipt end hash")
    conversion_receipt_path = _require(conversion_receipt_path, "conversion execution receipt")
    conversion_receipt = json.loads(conversion_receipt_path.read_text())
    if (conversion_receipt.get("status") != "completed" or
            conversion_receipt.get("returncode") != 0 or
            Path(conversion_receipt.get("output_root", "")) != conversion_receipt_path.parent):
        raise EvidenceError("conversion execution receipt is not completed at its output root")
    command = conversion_receipt.get("command", [])
    if (Path(_command_value(command, "--output")) != trajectory or
            Path(_command_value(command, "--report")) != conversion_path):
        raise EvidenceError("conversion receipt output/report differs from bound files")
    unobserved_inputs, path_aliases = _stable_receipt_inputs(conversion_receipt)
    conversion_receipt["_forensics_unobserved_input_digests"] = unobserved_inputs
    conversion_receipt["_forensics_input_path_aliases"] = path_aliases
    return scan, scan_receipt, conversion, conversion_receipt, scan_path


def _typed_block_proof(sidecar_result: dict, scan: dict, conversion: dict) -> dict:
    fluid = scan.get("type_ledgers", {}).get("fluid", {})
    typed_count = int(fluid["typed_initial_count"])
    typed_total = float(fluid["typed_initial_mass_kg"])
    typed = conversion.get("typed_identity", {})
    blocks = typed.get("blocks", [])
    fluid_blocks = [row for row in blocks
                    if row.get("tag") == "fluid" and int(row.get("type", -1)) == 3]
    if not fluid_blocks:
        raise EvidenceError("conversion report has no typed fluid blocks")
    if any(int(row.get("count", 0)) <= 0 for row in fluid_blocks):
        raise EvidenceError("conversion fluid block count is invalid")
    mass_min = float(typed.get("initial_mass_min_kg"))
    mass_max = float(typed.get("initial_mass_max_kg"))
    if not math.isfinite(mass_min) or mass_min <= 0 or mass_min != mass_max:
        raise EvidenceError("conversion metadata does not prove constant typed mass")
    block_count = sum(int(row["count"]) for row in fluid_blocks)
    block_mass = math.fsum(int(row["count"]) * mass_min for row in fluid_blocks)
    if block_count != typed_count or not math.isclose(block_mass, typed_total, rel_tol=0.0, abs_tol=2e-12):
        raise EvidenceError("conversion fluid blocks do not reproduce scan typed total")
    constants = conversion.get("hash_scopes", {}).get("numerical_parameters", {}).get("decoder_header_constants", {})
    if not math.isclose(float(constants.get("MassFluid", "nan")), mass_min,
                        rel_tol=0.0, abs_tol=1e-15):
        raise EvidenceError("decoder MassFluid metadata differs from typed mass extrema")
    xml_path = Path(sidecar_result["source_evidence"]["generated_xml"]["path"])
    root = ET.parse(_require(xml_path, "generated XML")).getroot()
    xml_blocks = []
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] != "fluid":
            continue
        if not {"mk", "mkfluid", "begin", "count"} <= set(element.attrib):
            continue
        xml_blocks.append({"mk": int(element.attrib["mk"]),
                           "mkfluid": int(element.attrib["mkfluid"]),
                           "begin": int(element.attrib["begin"]),
                           "count": int(element.attrib["count"])})
    converted_blocks = [{"mk": int(row["mk"]), "mkfluid": int(row.get("mkfluid", -1)),
                         "begin": int(row["begin"]), "count": int(row["count"])}
                        for row in fluid_blocks]
    if sorted(xml_blocks, key=lambda row: (row["begin"], row["mk"])) != sorted(
            converted_blocks, key=lambda row: (row["begin"], row["mk"])):
        raise EvidenceError("XML source-MK ranges differ from conversion typed blocks")
    by_mk = {int(row["mk"]): row for row in fluid_blocks}
    groups = sidecar_result.get("source_mk_breakdown", [])
    for group in groups:
        mk = int(group["mk"])
        if mk not in by_mk:
            raise EvidenceError(f"missing conversion typed block for MK {mk}")
        denominator = int(by_mk[mk]["count"]) * mass_min
        if not math.isclose(float(group["initial_mass_denominator_kg"]), denominator,
                            rel_tol=0.0, abs_tol=2e-12):
            raise EvidenceError(f"existing MK denominator differs for MK {mk}")
        group["initial_mass_denominator_kg"] = denominator
        group["denominator_source"] = "conversion typed_identity fluid block count × constant native float32 MassFluid; XML begin/count and scan total cross-checked"
    return {
        "schema": "ds02.stage2.native-per-mk-mass-proof.v1",
        "fluid_block_count": len(fluid_blocks),
        "fluid_blocks": converted_blocks,
        "typed_initial_count": typed_count,
        "typed_initial_mass_kg": typed_total,
        "native_mass_kg_per_fluid_particle": mass_min,
        "initial_mass_min_kg": mass_min,
        "initial_mass_max_kg": mass_max,
        "sum_block_count_times_mass_kg": block_mass,
        "uniform_mass_proven": True,
        "xml_ranges_match_conversion_blocks": True,
        "h5_opened": False,
    }


def assess(sidecar_path: Path, conversion_path: Path,
           conversion_receipt_path: Path) -> dict:
    result = assess_v3(sidecar_path)
    scan, scan_receipt, conversion, conversion_receipt, scan_path = _scan_and_conversion(
        json.loads(Path(sidecar_path).read_text()), Path(conversion_path),
        Path(conversion_receipt_path))
    proof = _typed_block_proof(result, scan, conversion)
    result["schema"] = "ds02.stage2.omission-task-impact.v5"
    result["status"] = "TASK_IMPACT_SCREENED_NATIVE_TYPED_DENOMINATOR_CONVERSION_VERIFIED_DYNAMICS_UNAVAILABLE"
    result.setdefault("source_evidence", {}).update({
        "scan_receipt": binding(scan_path.parent / "execution-receipt.json"),
        "conversion_report": binding(Path(conversion_path)),
        "conversion_receipt": binding(Path(conversion_receipt_path)),
        "converter_execution_command": conversion_receipt.get("command", []),
        "converter_execution_input_hashes_stable": True,
        "converter_execution_input_digests_unobserved": conversion_receipt.get(
            "_forensics_unobserved_input_digests", []),
        "converter_execution_input_path_aliases": conversion_receipt.get(
            "_forensics_input_path_aliases", []),
        "native_per_mk_mass_proof": proof,
        "task_module_version": "v5-conversion-block-proof-realpath-alias",
        "trajectory_h5_read": False,
    })
    result["per_mk_denominator_validation"] = proof
    result.setdefault("unknown_and_acceptance", {})["denominator_version"] = "native_typed_conversion_blocks_v5_realpath_alias"
    result["unknown_and_acceptance"]["physical_fate"] = "UNKNOWN"
    result["unknown_and_acceptance"]["dynamical_impact"] = "NOT_ASSESSED"
    result["unknown_and_acceptance"]["QN"] = "NOT_ASSESSED"
    result["unknown_and_acceptance"]["QE"] = "NOT_ASSESSED"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sidecar", type=Path, required=True)
    parser.add_argument("--conversion-report", type=Path, required=True)
    parser.add_argument("--conversion-receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing task-impact sidecar: " + str(args.output))
    result = assess(args.sidecar, args.conversion_report, args.conversion_receipt)
    atomic_json(args.output, result)
    print(json.dumps({"status": result["status"], "case": result["physical_case_id"],
                      "uniform_mass_proven": result["per_mk_denominator_validation"]["uniform_mass_proven"],
                      "screen": result["missing_mass_screen"]["screen"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
