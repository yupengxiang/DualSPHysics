#!/usr/bin/env python3
"""Audit a small, source-bound sample of native omission identities.

The completed 118-case PartVTKOut closure already proves the native
``Idp/PartOut/Motive`` rows.  This forward-only audit adds the missing
identity layer: each omitted fluid ``Idp`` is mapped to the typed conversion
report's ``(begin,count,mk,type)`` block and its native mass.  It consumes
only the completed small JSON/CSV/receipt products named by the manifest.  It
never opens trajectory HDF5, ``Part_*.bi4`` frames, or starts a decoder or a
solver.

The mapping is deliberately narrow.  A zero initial conversion exclusion
ledger means that the selected IDs were present in the typed initial axis; it
does not prove that the converter implementation is complete, that the
particles physically left the domain, or that a legal flux occurred.  Those
claims remain UNKNOWN until a source-bound continuous/destination audit is
available.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.native-identity-audit-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.native-identity-audit.v1"
MOTIVES = {1: "position", 2: "density", 3: "movement"}
RUNPART_FIELDS = ("NpOut", "NpOutPos", "NpOutRho", "NpOutMov")
FLOAT_TOL = 2.0e-12


class IdentityAuditError(ValueError):
    """Raised when a source-bound native identity cannot be closed."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _reject_scientific_payload(path: Path, label: str) -> None:
    name = Path(path).name
    if name == "trajectory.h5" or (name.startswith("Part_") and name.endswith(".bi4")):
        raise IdentityAuditError(f"{label} attempts to consume trajectory content: {path}")


def require_file(value: str | Path, label: str, *, reject_scientific: bool = True) -> Path:
    path = Path(value).expanduser().resolve()
    if reject_scientific:
        _reject_scientific_payload(path, label)
    if not path.is_file():
        raise IdentityAuditError(f"{label} is missing: {path}")
    return path


def ref(path: str | Path, expected: str | None, label: str) -> dict[str, Any]:
    actual_path = require_file(path, label)
    actual = sha256(actual_path)
    if expected is not None and actual != str(expected):
        raise IdentityAuditError(
            f"{label} digest differs: {actual_path}; expected {expected}, got {actual}"
        )
    return {"path": str(actual_path), "sha256": actual, "bytes": actual_path.stat().st_size}


def read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IdentityAuditError(f"{label} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise IdentityAuditError(f"{label} is not a JSON object: {path}")
    return value


def read_json_ref(value: dict[str, Any], label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    if not isinstance(value, dict) or not isinstance(value.get("path"), str):
        raise IdentityAuditError(f"{label} lacks a path reference")
    path = require_file(value["path"], label)
    binding = ref(path, value.get("sha256"), label)
    return path, read_json(path, label), binding


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def command_value(command: list[Any], flag: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise IdentityAuditError(f"decoder command is missing {flag}")


def expanded_command(request_command: list[Any], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root)) for value in request_command]


def _canonical(path: str | Path) -> str:
    return str(Path(path).expanduser().resolve(strict=False))


def receipt_input(receipt: dict[str, Any], path: Path, label: str, *, hash_now: bool = True) -> str:
    key = str(Path(path).resolve())
    request = receipt.get("request", {})
    declared = request.get("input_sha256", {}).get(key)
    launch = receipt.get("input_hashes_at_launch", {}).get(key)
    finish = receipt.get("input_hashes_after_run", {}).get(key)
    if not declared or declared != launch or declared != finish:
        raise IdentityAuditError(f"{label} launch/end input hash is incomplete: {key}")
    if hash_now:
        actual = sha256(path)
        if actual != declared:
            raise IdentityAuditError(f"{label} input hash changed: {key}")
    return str(declared)


def _request_files(receipt: dict[str, Any]) -> set[str]:
    return {_canonical(value) for value in receipt.get("request", {}).get("input_files", [])}


def read_partout(path: Path, label: str) -> list[dict[str, Any]]:
    _reject_scientific_payload(path, label)
    text = path.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise IdentityAuditError(f"{label} is empty: {path}")
    delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
    rows: list[dict[str, Any]] = []
    reader = csv.DictReader(lines, delimiter=delimiter)
    if not reader.fieldnames:
        raise IdentityAuditError(f"{label} header is missing")
    for raw in reader:
        row = {str(key).strip(): (value or "").strip() for key, value in raw.items() if key}
        try:
            idp = int(row["Idp"])
            part = int(row["PartOut"])
            motive_code = int(row["Motive"])
            position = [float(row[f"Pos.{axis} [m]"]) for axis in "xyz"]
            density = float(row["Rhop [kg/m^3]"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityAuditError(f"{label} contains an invalid row") from exc
        if motive_code not in MOTIVES or part < 1 or not all(
            math.isfinite(value) for value in (*position, density)
        ):
            raise IdentityAuditError(f"{label} contains invalid native values for Idp {idp}")
        rows.append({
            "idp": idp,
            "part_out": part,
            "motive_code": motive_code,
            "motive": MOTIVES[motive_code],
            "position_m": position,
            "density_kg_m3": density,
        })
    if not rows:
        raise IdentityAuditError(f"{label} has no native rows")
    if len({row["idp"] for row in rows}) != len(rows):
        raise IdentityAuditError(f"{label} has duplicate Idp rows")
    return rows


def read_runparts(path: Path, label: str) -> dict[str, Any]:
    _reject_scientific_payload(path, label)
    lines = [line for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip() and not line.lstrip().startswith("#")]
    reader = csv.DictReader(lines, delimiter=";")
    if not reader.fieldnames or not set(("Part", "TimeStep [s]", *RUNPART_FIELDS)) <= set(reader.fieldnames):
        raise IdentityAuditError(f"{label} lacks the native RunPARTs fields")
    rows: list[dict[str, Any]] = []
    totals = {name: 0 for name in RUNPART_FIELDS}
    for raw in reader:
        try:
            part = int(str(raw["Part"]).replace(",", ""))
            time_s = float(raw["TimeStep [s]"])
            counts = {name: int(str(raw[name]).replace(",", "")) for name in RUNPART_FIELDS}
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityAuditError(f"{label} contains an invalid row") from exc
        if part != len(rows) or not math.isfinite(time_s):
            raise IdentityAuditError(f"{label} has a non-contiguous Part/time sequence")
        if rows and time_s <= rows[-1]["time_s"]:
            raise IdentityAuditError(f"{label} time is not increasing")
        if any(value < 0 for value in counts.values()) or counts["NpOut"] != sum(
            counts[name] for name in RUNPART_FIELDS[1:]
        ):
            raise IdentityAuditError(f"{label} has inconsistent native motive counters")
        rows.append({"part": part, "time_s": time_s, **counts})
        for name, value in counts.items():
            totals[name] += value
    if not rows:
        raise IdentityAuditError(f"{label} has no rows")
    return {"rows": rows, "totals": totals}


def _source_refs(case: dict[str, Any]) -> dict[str, dict[str, Any]]:
    refs = case.get("source_refs")
    if not isinstance(refs, dict):
        raise IdentityAuditError(f"{case.get('case_key')} has no source_refs")
    required = (
        "scan", "scan_receipt", "native_csv", "runparts", "decoder_receipt",
        "raw_partout", "conversion_report", "solver_receipt", "gencase_receipt",
        "xml", "partvtk_binary",
    )
    for key in required:
        if not isinstance(refs.get(key), dict) or not refs[key].get("path"):
            raise IdentityAuditError(f"{case.get('case_key')} lacks source ref {key}")
    return refs


def _impact_row(impact: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    key = case.get("case_key")
    rows = [row for row in impact.get("cases", []) if row.get("case_key") == key]
    if len(rows) != 1:
        raise IdentityAuditError(f"impact report does not contain exactly one {key}")
    row = rows[0]
    for field in ("family_id", "physical_case_id"):
        if row.get(field) != case.get(field):
            raise IdentityAuditError(f"{key} {field} differs from impact report")
    cause = row.get("native_numerical_cause", {})
    if cause.get("motive") != case.get("expected_native_motive"):
        raise IdentityAuditError(f"{key} expected native motive differs from impact report")
    if int(cause.get("native_count", -1)) != int(case.get("expected_native_count", -2)):
        raise IdentityAuditError(f"{key} expected native count differs from impact report")
    return row


def _validate_current(current: dict[str, Any], case: dict[str, Any]) -> dict[str, Any]:
    rows = [row for row in current.get("cases", [])
            if row.get("family_id") == case.get("family_id")
            and row.get("physical_case_id") == case.get("physical_case_id")]
    if len(rows) != 1:
        raise IdentityAuditError(f"CURRENT does not contain exactly one {case.get('physical_case_id')}")
    return {
        "family_id": rows[0].get("family_id"),
        "physical_case_id": rows[0].get("physical_case_id"),
        "runtime_case_alias": rows[0].get("runtime_case_alias"),
        "frames": rows[0].get("frames"),
        "particles": rows[0].get("particles"),
    }


def _scan_and_receipt(case: dict[str, Any], refs: dict[str, dict[str, Any]]) -> tuple[
    dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]
]:
    scan_path, scan, scan_binding = read_json_ref(refs["scan"], f"{case['case_key']} scan")
    receipt_path, receipt, receipt_binding = read_json_ref(
        refs["scan_receipt"], f"{case['case_key']} scan receipt"
    )
    if scan.get("schema") != "ds02.stage2.scientific-scan.v1":
        raise IdentityAuditError(f"{case['case_key']} scan schema is unsupported")
    if scan.get("scan_status") != "SCANNED" or scan.get("failures"):
        raise IdentityAuditError(f"{case['case_key']} scan is not clean")
    if scan.get("family_id") != case.get("family_id") or scan.get("physical_case_id") != case.get("physical_case_id"):
        raise IdentityAuditError(f"{case['case_key']} scan physical identity differs")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise IdentityAuditError(f"{case['case_key']} scan receipt is not completed")
    if receipt.get("output_root") != str(scan_path.parent):
        raise IdentityAuditError(f"{case['case_key']} scan receipt output root differs")
    command = receipt.get("command", [])
    if command_value(command, "--output") != str(scan_path):
        raise IdentityAuditError(f"{case['case_key']} scan receipt output differs")
    if command_value(command, "--case-id") != str(case["physical_case_id"]):
        raise IdentityAuditError(f"{case['case_key']} scan receipt case differs")
    trajectory = Path(str(scan.get("trajectory", ""))).expanduser().resolve()
    # The trajectory is only compared as receipt metadata.  It is deliberately
    # never opened or hashed by this worker.
    request = receipt.get("request", {})
    request_files = {_canonical(value) for value in request.get("input_files", [])}
    if str(trajectory) not in request_files:
        raise IdentityAuditError(f"{case['case_key']} scan receipt does not bind trajectory")
    trajectory_key = str(trajectory)
    declared = request.get("input_sha256", {}).get(trajectory_key)
    launch = receipt.get("input_hashes_at_launch", {}).get(trajectory_key)
    finish = receipt.get("input_hashes_after_run", {}).get(trajectory_key)
    if not declared or declared != launch or declared != finish:
        raise IdentityAuditError(f"{case['case_key']} scan trajectory receipt hashes are unstable")
    # Compare only producer metadata here; the caller checks this digest against
    # the completed conversion report.  The trajectory itself is never opened.
    missing = [row for row in scan.get("missing_id_records", [])
               if int(row.get("type_code", -1)) == 3 and row.get("missing_at_final") is True]
    if len(missing) != int(scan.get("type_ledgers", {}).get("fluid", {}).get("missing_at_final", -1)):
        raise IdentityAuditError(f"{case['case_key']} scan missing ledger count differs")
    by_id: dict[int, dict[str, Any]] = {}
    for row in missing:
        try:
            idp = int(row["idp"])
            first_frame = int(row["first_missing_frame"])
            zone = int(row["zone"])
            mass = float(row["initial_mass_kg"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityAuditError(f"{case['case_key']} scan omission record is malformed") from exc
        if idp in by_id or first_frame < 1 or not math.isfinite(mass) or mass <= 0:
            raise IdentityAuditError(f"{case['case_key']} scan omission identity is invalid")
        by_id[idp] = {
            "idp": idp,
            "zone": zone,
            "first_missing_frame": first_frame,
            "first_missing_bracket_s": row.get("first_missing_bracket_s"),
            "initial_mass_kg": mass,
        }
    return scan, receipt, scan_binding, receipt_binding, list(by_id.values())


def _decoder_sources(case: dict[str, Any], refs: dict[str, dict[str, Any]], conversion: dict[str, Any],
                     conversion_path: Path, native_path: Path, runparts_path: Path,
                     decoder_path: Path, decoder: dict[str, Any], decoder_binding: dict[str, Any]) -> dict[str, Any]:
    if decoder.get("status") != "completed" or decoder.get("returncode") != 0:
        raise IdentityAuditError(f"{case['case_key']} decoder receipt is not completed")
    output_root = Path(str(decoder.get("output_root", ""))).expanduser().resolve()
    if output_root != native_path.parent:
        raise IdentityAuditError(f"{case['case_key']} decoder output root differs from PartOut CSV")
    command = decoder.get("command", [])
    binary = Path(str(command[0])).expanduser().resolve() if command else Path()
    if not binary.is_file() or binary.name != "PartVTKOut_linux64":
        raise IdentityAuditError(f"{case['case_key']} decoder is not the official PartVTKOut binary")
    if command_value(command, "-savecsv") != str(native_path):
        raise IdentityAuditError(f"{case['case_key']} decoder -savecsv differs")
    resume = Path(command_value(command, "-saveresume")).expanduser().resolve()
    if resume.parent != output_root or not resume.is_file():
        raise IdentityAuditError(f"{case['case_key']} decoder resume is not in output root")
    data_root = Path(str(conversion.get("source_provenance", {}).get("data_root", ""))).expanduser().resolve()
    if not data_root.is_dir() or Path(command_value(command, "-dirdata")).expanduser().resolve() != data_root:
        raise IdentityAuditError(f"{case['case_key']} decoder data root differs from conversion provenance")
    if runparts_path.parent != data_root.parent:
        raise IdentityAuditError(f"{case['case_key']} RunPARTs is not from the solver parent")
    request_command = decoder.get("request", {}).get("command", [])
    if expanded_command(request_command, output_root) != [str(value) for value in command]:
        raise IdentityAuditError(f"{case['case_key']} decoder command differs from request")
    request_files = _request_files(decoder)
    required_paths = [
        refs["scan"]["path"], refs["runparts"]["path"], refs["conversion_report"]["path"],
        refs["solver_receipt"]["path"], refs["gencase_receipt"]["path"], refs["xml"]["path"],
        refs["raw_partout"]["path"], refs["partvtk_binary"]["path"],
    ]
    for value in required_paths:
        path = Path(value).expanduser().resolve()
        if _canonical(path) not in request_files:
            raise IdentityAuditError(f"{case['case_key']} decoder request omits source {path}")
        receipt_input(decoder, path, f"{case['case_key']} decoder source", hash_now=True)
    raw = Path(refs["raw_partout"]["path"]).expanduser().resolve()
    if raw.parent != data_root or raw.name != "PartOut_000.obi4":
        raise IdentityAuditError(f"{case['case_key']} raw PartOut is not under -dirdata")
    provenance = conversion.get("source_provenance", {})
    provenance_partvtk = provenance.get("partvtk", {})
    provenance_binary = Path(str(provenance_partvtk.get("path", ""))).expanduser().resolve()
    # Historical conversion reports called the same official binary
    # ``PartVTK_linux64`` while the native decoder receipt called it
    # ``PartVTKOut_linux64``.  Accept this only as a digest-closed alias;
    # never accept a path mismatch by name alone.
    if not provenance_binary.is_file() or provenance_partvtk.get("sha256") != sha256(binary):
        raise IdentityAuditError(f"{case['case_key']} conversion PartVTK provenance digest differs")
    if decoder.get("binary_sha256") != refs["partvtk_binary"].get("sha256"):
        raise IdentityAuditError(f"{case['case_key']} decoder binary digest differs")
    for field, ref_key in (("generated_xml", "xml"), ("solver_receipt", "solver_receipt"),
                           ("gencase_receipt", "gencase_receipt")):
        source = provenance.get(field, {})
        if source.get("path") != str(Path(refs[ref_key]["path"]).expanduser().resolve()):
            raise IdentityAuditError(f"{case['case_key']} conversion {field} path differs")
        if source.get("sha256") != refs[ref_key].get("sha256"):
            raise IdentityAuditError(f"{case['case_key']} conversion {field} digest differs")
    return {
        "receipt": decoder_binding,
        "command": [str(value) for value in command],
        "binary": ref(binary, refs["partvtk_binary"].get("sha256"), f"{case['case_key']} PartVTKOut binary"),
        "conversion_provenance_alias": {
            "path": str(provenance_binary),
            "sha256": str(provenance_partvtk.get("sha256")),
            "same_digest_as_decoder_binary": True,
            "path_equal": provenance_binary == binary,
        },
        "data_root": str(data_root),
        "raw_partout": ref(raw, refs["raw_partout"].get("sha256"), f"{case['case_key']} raw PartOut"),
        "output_root": str(output_root),
        "partout": ref(native_path, refs["native_csv"].get("sha256"), f"{case['case_key']} PartOut CSV"),
        "resume": ref(resume, None, f"{case['case_key']} decoder resume"),
        "trajectory_h5_opened": False,
        "part_frames_opened": False,
    }


def _typed_blocks(conversion: dict[str, Any], label: str) -> tuple[list[dict[str, Any]], float, float]:
    typed = conversion.get("typed_identity", {})
    blocks = typed.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise IdentityAuditError(f"{label} typed conversion blocks are missing")
    normalized: list[dict[str, Any]] = []
    for row in blocks:
        try:
            begin = int(row["begin"])
            count = int(row["count"])
            mk = int(row["mk"])
            typ = int(row["type"])
        except (KeyError, TypeError, ValueError) as exc:
            raise IdentityAuditError(f"{label} typed block is malformed") from exc
        if begin < 0 or count <= 0:
            raise IdentityAuditError(f"{label} typed block range is invalid")
        normalized.append({
            "begin": begin, "count": count, "mk": mk, "mkfluid": row.get("mkfluid"),
            "tag": row.get("tag"), "type": typ,
        })
    normalized.sort(key=lambda row: (row["begin"], row["mk"], row["type"]))
    previous_end = -1
    for row in normalized:
        if row["begin"] < previous_end:
            raise IdentityAuditError(f"{label} typed block ranges overlap")
        previous_end = row["begin"] + row["count"]
    constants = conversion.get("hash_scopes", {}).get("numerical_parameters", {}).get("decoder_header_constants", {})
    try:
        mass_fluid = float(constants["MassFluid"])
        mass_bound = float(constants["MassBound"])
    except (KeyError, TypeError, ValueError) as exc:
        raise IdentityAuditError(f"{label} decoder mass constants are missing") from exc
    if not math.isfinite(mass_fluid) or mass_fluid <= 0 or not math.isfinite(mass_bound) or mass_bound <= 0:
        raise IdentityAuditError(f"{label} decoder mass constants are invalid")
    return normalized, mass_fluid, mass_bound


def _find_block(blocks: list[dict[str, Any]], idp: int, label: str) -> dict[str, Any]:
    matches = [row for row in blocks if row["begin"] <= idp < row["begin"] + row["count"]]
    if len(matches) != 1:
        raise IdentityAuditError(f"{label} Idp {idp} maps to {len(matches)} typed blocks")
    return matches[0]


def _audit_case(case: dict[str, Any], impact: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    refs = _source_refs(case)
    impact_row = _impact_row(impact, case)
    current_row = _validate_current(current, case)
    loaded: dict[str, tuple[Path, dict[str, Any], dict[str, Any]]] = {}
    for key in ("conversion_report", "decoder_receipt", "solver_receipt", "gencase_receipt"):
        loaded[key] = read_json_ref(refs[key], f"{case['case_key']} {key}")
    conversion_path, conversion, conversion_binding = loaded["conversion_report"]
    decoder_path, decoder, decoder_binding = loaded["decoder_receipt"]
    solver_path, solver, solver_binding = loaded["solver_receipt"]
    gencase_path, gencase, gencase_binding = loaded["gencase_receipt"]
    if conversion.get("conversion_status") != "completed":
        raise IdentityAuditError(f"{case['case_key']} conversion is not completed")
    scan, scan_receipt, scan_binding, scan_receipt_binding, missing = _scan_and_receipt(case, refs)
    trajectory_key = str(Path(str(scan.get("trajectory", ""))).expanduser().resolve())
    scan_trajectory_hash = scan_receipt.get("request", {}).get("input_sha256", {}).get(trajectory_key)
    if not isinstance(scan_trajectory_hash, str) or conversion.get("output_sha256") != scan_trajectory_hash:
        raise IdentityAuditError(f"{case['case_key']} conversion output hash differs from scan producer metadata")
    if conversion.get("output_hdf5") != str(Path(trajectory_key)):
        raise IdentityAuditError(f"{case['case_key']} conversion output path differs from scan trajectory")
    native_path = require_file(refs["native_csv"]["path"], f"{case['case_key']} PartOut CSV")
    native_binding = ref(native_path, refs["native_csv"].get("sha256"), f"{case['case_key']} PartOut CSV")
    runparts_path = require_file(refs["runparts"]["path"], f"{case['case_key']} RunPARTs")
    runparts_binding = ref(runparts_path, refs["runparts"].get("sha256"), f"{case['case_key']} RunPARTs")
    decoder_sources = _decoder_sources(
        case, refs, conversion, conversion_path, native_path, runparts_path,
        decoder_path, decoder, decoder_binding,
    )
    blocks, mass_fluid, mass_bound = _typed_blocks(conversion, case["case_key"])
    rows = read_partout(native_path, f"{case['case_key']} PartOut")
    runparts = read_runparts(runparts_path, f"{case['case_key']} RunPARTs")
    missing_by_id = {row["idp"]: row for row in missing}
    if set(missing_by_id) != {row["idp"] for row in rows}:
        raise IdentityAuditError(f"{case['case_key']} native IDs differ from scan final missing IDs")
    expected_motive = str(case["expected_native_motive"])
    by_mk: dict[int, dict[str, Any]] = {}
    identities: list[dict[str, Any]] = []
    for native in sorted(rows, key=lambda row: row["idp"]):
        scan_row = missing_by_id[native["idp"]]
        block = _find_block(blocks, native["idp"], case["case_key"])
        if block["type"] != 3:
            raise IdentityAuditError(f"{case['case_key']} missing Idp {native['idp']} is not typed fluid")
        if native["motive"] != expected_motive:
            raise IdentityAuditError(f"{case['case_key']} native motive differs for Idp {native['idp']}")
        if native["part_out"] != int(scan_row["first_missing_frame"]):
            raise IdentityAuditError(f"{case['case_key']} PartOut differs from first missing frame for Idp {native['idp']}")
        if not math.isclose(float(scan_row["initial_mass_kg"]), mass_fluid, rel_tol=0.0, abs_tol=FLOAT_TOL):
            raise IdentityAuditError(f"{case['case_key']} scan mass differs from decoder MassFluid for Idp {native['idp']}")
        mk = int(block["mk"])
        group = by_mk.setdefault(mk, {"mk": mk, "count": 0, "mass_kg": 0.0,
                                      "types": {}, "idp_min": native["idp"], "idp_max": native["idp"],
                                      "first_missing_frame_min": native["part_out"],
                                      "first_missing_frame_max": native["part_out"]})
        group["count"] += 1
        group["mass_kg"] += mass_fluid
        group["types"][str(block["type"])] = int(group["types"].get(str(block["type"]), 0)) + 1
        group["idp_min"] = min(group["idp_min"], native["idp"])
        group["idp_max"] = max(group["idp_max"], native["idp"])
        group["first_missing_frame_min"] = min(group["first_missing_frame_min"], native["part_out"])
        group["first_missing_frame_max"] = max(group["first_missing_frame_max"], native["part_out"])
        identities.append({
            "zone": int(scan_row["zone"]), "idp": native["idp"],
            "first_missing_frame": native["part_out"],
            "first_missing_bracket_s": scan_row.get("first_missing_bracket_s"),
            "native_motive": native["motive"], "native_motive_code": native["motive_code"],
            "partvtk_position_m": native["position_m"],
            "partvtk_density_kg_m3": native["density_kg_m3"],
            "mk": mk, "mkfluid": block.get("mkfluid"), "type": int(block["type"]),
            "typed_tag": block.get("tag"), "initial_mass_kg": mass_fluid,
        })
    totals = runparts["totals"]
    counts = {name: sum(1 for row in rows if row["motive"] == name) for name in MOTIVES.values()}
    expected_counts = {"position": totals["NpOutPos"], "density": totals["NpOutRho"],
                       "movement": totals["NpOutMov"]}
    if totals["NpOut"] != len(rows) or counts != expected_counts:
        raise IdentityAuditError(f"{case['case_key']} RunPARTs totals do not match native rows")
    initial_filter = conversion.get("typed_identity", {}).get("initial_exclusion_ledger", {})
    initial_filter_count = int(initial_filter.get("count", -1))
    if initial_filter_count < 0:
        raise IdentityAuditError(f"{case['case_key']} initial conversion exclusion ledger is missing")
    source_conversion_status = (
        "NO_INITIAL_CONVERSION_FILTER_OBSERVED_FOR_SELECTED_IDS"
        if initial_filter_count == 0 else "INITIAL_CONVERSION_FILTER_OBSERVED"
    )
    missing_mass = sum(float(row["initial_mass_kg"]) for row in missing)
    typed_total = float(scan.get("type_ledgers", {}).get("fluid", {}).get("typed_initial_mass_kg", float("nan")))
    return {
        "case_key": case["case_key"], "family_id": case["family_id"],
        "physical_case_id": case["physical_case_id"], "current_identity": current_row,
        "source_bindings": {
            "scan": scan_binding, "scan_receipt": scan_receipt_binding,
            "conversion_report": conversion_binding, "decoder_receipt": decoder_sources["receipt"],
            "native_csv": native_binding, "runparts": runparts_binding,
            "solver_receipt": solver_binding, "gencase_receipt": gencase_binding,
            "xml": ref(refs["xml"]["path"], refs["xml"].get("sha256"), f"{case['case_key']} XML"),
        },
        "native_identity": {
            "native_rows": len(rows), "runparts_totals": totals,
            "motive_counts": counts, "typed_total_mass_kg": typed_total,
            "missing_mass_kg": missing_mass,
            "mass_per_fluid_particle_kg": mass_fluid,
            "mass_bound_kg": mass_bound,
            "source_mk_counts": sorted(by_mk.values(), key=lambda item: item["mk"]),
            "ids": identities,
            "typed_identity_key": conversion.get("typed_identity", {}).get("key"),
            "typed_zone_source": conversion.get("typed_identity", {}).get("zone_source"),
            "observed_mks": conversion.get("typed_identity", {}).get("observed_mks"),
            "observed_types": conversion.get("typed_identity", {}).get("observed_types"),
        },
        "conversion_filtering": {
            "initial_exclusion_ledger_count": initial_filter_count,
            "initial_exclusion_ledger_mass_kg": initial_filter.get("mass_kg"),
            "selected_ids_present_in_typed_initial_blocks": True,
            "selected_status": source_conversion_status,
            "converter_source_program": str(
                impact_row.get("conversion_omission", {}).get("converter_source_closure",
                                                               "UNKNOWN_NOT_BOUND_BY_CONVERSION_RECEIPT")
            ),
            "conversion_report_output_hdf5_checked_as_metadata_only": True,
            "trajectory_h5_opened": False,
        },
        "native_cause": {
            "motive": expected_motive, "native_count": len(rows),
            "source": "official PartVTKOut CSV + same-solver RunPARTs receipt-bound output",
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "continuous_event_time": "UNKNOWN; saved first-missing bracket only",
            "post_gap_destination": "UNKNOWN; no trajectory content opened",
            "dynamical_impact": "UNKNOWN; no bounded paired physical audit",
        },
        "read_policy": {
            "scientific_scan_json_opened": True, "scan_receipt_json_opened": True,
            "conversion_report_json_opened": True, "decoder_receipt_json_opened": True,
            "native_partout_csv_opened": True, "runparts_csv_opened": True,
            "trajectory_h5_opened": False, "part_frames_opened": False,
            "solver_started": False, "decoder_started": False, "cfd_or_model_run": False,
        },
    }


def audit(manifest_path: Path, output: Path) -> dict[str, Any]:
    manifest_path = require_file(manifest_path, "identity audit manifest")
    manifest = read_json(manifest_path, "identity audit manifest")
    if manifest.get("schema") != SCHEMA:
        raise IdentityAuditError(f"unsupported manifest schema: {manifest.get('schema')}")
    impact_path, impact, impact_binding = read_json_ref(manifest["impact_report"], "all118 impact report")
    current_path, current, current_binding = read_json_ref(manifest["current"], "CURRENT336")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases or len(cases) > 4:
        raise IdentityAuditError("identity audit must contain one to four bounded cases")
    if len({case.get("case_key") for case in cases}) != len(cases):
        raise IdentityAuditError("identity audit case keys are not unique")
    results = [_audit_case(case, impact, current) for case in cases]
    all_ids = sum((row["native_identity"]["ids"] for row in results), [])
    return {
        "schema": OUTPUT_SCHEMA, "status": "COMPLETED_NATIVE_IDENTITY_MK_TYPE_AUDIT",
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path),
                      "bytes": manifest_path.stat().st_size},
        "source_reports": {"impact": impact_binding, "current": current_binding,
                           "impact_case_count": len(impact.get("cases", [])),
                           "current_case_count": len(current.get("cases", []))},
        "selected_case_count": len(results), "selected_native_id_count": len(all_ids),
        "cases": results,
        "claim_boundary": {
            "native_identity": "CLOSED for selected IDs: official PartVTKOut Idp/PartOut/Motive rows map to typed conversion MK/type blocks and constant native mass",
            "conversion_initial_filter": "NO_INITIAL_CONVERSION_FILTER_OBSERVED_FOR_SELECTED_IDS only when the producer ledger count is zero; converter source implementation remains UNKNOWN",
            "physical_fate": "UNKNOWN; native numerical exclusion is not legal spill or physical outflow",
            "dynamical_impact": "UNKNOWN; missing mass is a source-visible lower bound only",
            "event_time": "UNKNOWN beyond saved first-missing bracket",
            "source_mk_scope": "selected three cases only; no family-wide generalization",
            "QN": "NOT_ASSESSED", "QE": "NOT_ASSESSED",
        },
        "read_policy": {
            "trajectory_h5_opened": False, "part_frames_opened": False,
            "solver_started": False, "decoder_started": False, "cfd_or_model_run": False,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"preserve existing output: {args.output}")
    result = audit(args.manifest, args.output)
    atomic_json(args.output, result)
    print(json.dumps({"status": result["status"],
                      "selected_cases": result["selected_case_count"],
                      "selected_native_ids": result["selected_native_id_count"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
