#!/usr/bin/env python3
"""Forward-correct the unconsumed v1 family-motive summary.

The first local v1 preview wrote the F4 density rows correctly but formatted
their aggregate key with the last loop value (``F6:density``).  This
forward-only consumer binds that old preview by SHA, re-reads the completed
root064 JSON closure and its receipt, and emits case-qualified identity rows
with a corrected aggregate.  It never edits the old preview and never opens
H5, BI4, PartOut, or a solver input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


SCHEMA = "ds02.stage2.native-source-identity-development-subset.v2"
CLOSURE_SCHEMA = "ds02.stage2.f2-s1-native-source-closure-118.v2"
STALE_FAMILY_MOTIVE = {"F6:density": 51, "F6:position": 199}
CORRECTED_FAMILY_MOTIVE = {"F2:position": 1078, "F4:density": 51, "F6:position": 199}


class CorrectionError(ValueError):
    pass


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def bind(path: Path, label: str) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.suffix.lower() in {".h5", ".bi4"} or path.name.startswith("PartOut_"):
        raise CorrectionError(f"{label} points at forbidden trajectory content: {path}")
    if not path.is_file():
        raise CorrectionError(f"{label} is missing: {path}")
    return {"path": str(path), "sha256": sha256(path), "bytes": path.stat().st_size}


def read_json(path: Path, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path = Path(path).expanduser().resolve()
    binding = bind(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CorrectionError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict):
        raise CorrectionError(f"{label} is not a JSON object")
    return path, value, binding


def read_completed_product(report_path: Path, receipt_path: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    report_path, report, report_binding = read_json(report_path, "root064 closure report")
    receipt_path, receipt, receipt_binding = read_json(receipt_path, "root064 closure receipt")
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise CorrectionError("root064 closure receipt is not completed code 0")
    if Path(str(receipt.get("output_root", ""))).expanduser().resolve() != report_path.parent:
        raise CorrectionError("root064 closure report is outside receipt output root")
    guard = receipt.get("terminal_storage_guard", {})
    if guard.get("status") != "passed" or guard.get("actual_bytes") != receipt.get("bytes"):
        raise CorrectionError("root064 closure receipt is not fixed-point storage guarded")
    if receipt.get("source_preflight", {}).get("status") != "PASS_AFTER_RESERVATION":
        raise CorrectionError("root064 closure receipt lacks reservation-before-read preflight")
    if receipt.get("model_invoked") is not False or receipt.get("cfd_invoked") is not False:
        raise CorrectionError("root064 closure receipt invokes forbidden model/CFD")
    return report, receipt, report_binding, receipt_binding


def _numerical_cause(motive: str, code: Any) -> str:
    expected = {"position": 1, "density": 2, "movement": 3}
    if motive not in expected or code != expected[motive]:
        raise CorrectionError(f"native motive/code mismatch: {motive!r}/{code!r}")
    return {
        "position": "NATIVE_PARTVTKOUT_POSITION_EXCLUSION",
        "density": "NATIVE_PARTVTKOUT_DENSITY_EXCLUSION",
        "movement": "NATIVE_PARTVTKOUT_MOVEMENT_EXCLUSION",
    }[motive]


def collect_rows(closure: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if closure.get("schema") != CLOSURE_SCHEMA or closure.get("status") != "PASS_ACTUAL_118_CASE_SOURCE_CLOSED_WITH_PRIOR_GAP_SPECTRUM_PRESERVED":
        raise CorrectionError("root064 closure schema/status differs")
    if closure.get("case_counts") != {
        "native_identity_source_closed": 118,
        "prior_v2_source_incomplete": 1,
        "requested": 118,
        "source_binding_rejected": 0,
        "source_incomplete_active": 0,
    }:
        raise CorrectionError("root064 closure case counts differ")
    cases = closure.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise CorrectionError("root064 closure case list differs")
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, int]] = set()
    family_cases = Counter()
    family_motive = Counter()
    motive = Counter()
    source_mk = Counter()
    invalid_brackets = 0
    for case in cases:
        case_key = case.get("case_key")
        family = case.get("family_id")
        if not isinstance(case_key, str) or family not in {"F2", "F4", "F6"}:
            raise CorrectionError("root064 closure has unexpected case identity")
        if case.get("case_status") != "NATIVE_IDENTITY_SOURCE_CLOSED":
            raise CorrectionError(f"case is not source closed: {case_key}")
        family_cases[family] += 1
        native = case.get("native_identity", {})
        ids = native.get("ids")
        if not isinstance(ids, list):
            raise CorrectionError(f"native IDs missing: {case_key}")
        for item in ids:
            idp = item.get("idp")
            identity = (case_key, idp)
            if not isinstance(idp, int) or identity in seen:
                raise CorrectionError(f"invalid or duplicate case-qualified identity: {identity}")
            seen.add(identity)
            bracket = item.get("first_missing_bracket_s")
            if not isinstance(bracket, list) or len(bracket) != 2 or not all(isinstance(x, (int, float)) for x in bracket) or not bracket[0] < bracket[1]:
                invalid_brackets += 1
            motive_name = item.get("native_motive", item.get("motive"))
            cause = _numerical_cause(motive_name, item.get("native_motive_code", item.get("motive_code")))
            family_motive[(family, motive_name)] += 1
            motive[motive_name] += 1
            source_mk[(family, str(item.get("mk")))] += 1
            rows.append({
                "row_index": len(rows),
                "case_key": case_key,
                "family_id": family,
                "physical_case_id": case.get("physical_case_id"),
                "idp": idp,
                "mk": item.get("mk"),
                "type": item.get("type"),
                "native_motive": motive_name,
                "native_motive_code": item.get("native_motive_code", item.get("motive_code")),
                "numerical_cause": cause,
                "first_missing_bracket_s": bracket,
                "first_missing_frame": item.get("first_missing_frame"),
                "initial_mass_kg": item.get("initial_mass_kg"),
                "partvtk_density_kg_m3": item.get("partvtk_density_kg_m3", item.get("density_kg_m3")),
                "partvtk_position_m": item.get("partvtk_position_m", item.get("position_m")),
                "typed_tag": item.get("typed_tag"),
                "zone": item.get("zone"),
            })
    if invalid_brackets:
        raise CorrectionError(f"{invalid_brackets} invalid first-missing brackets")
    if len(rows) != 1328 or closure.get("native_id_count") != len(rows):
        raise CorrectionError("root064 closure row count differs")
    if family_cases != Counter({"F2": 48, "F4": 22, "F6": 48}):
        raise CorrectionError(f"family case counts differ: {family_cases}")
    if family_motive != Counter({("F2", "position"): 1078, ("F4", "density"): 51, ("F6", "position"): 199}):
        raise CorrectionError(f"family motive counts differ: {family_motive}")
    return rows, {
        "case_count": len(cases),
        "row_count": len(rows),
        "identity_key": "(case_key, Idp); Idp is not globally unique across physical cases",
        "global_idp_uniqueness": False,
        "family_case_counts": dict(sorted(family_cases.items())),
        "family_motive_id_counts": {f"{family}:{motive_name}": count for (family, motive_name), count in sorted(family_motive.items())},
        "motive_counts": dict(sorted(motive.items())),
        "source_mk_counts": {f"{family}:MK{mk}": count for (family, mk), count in sorted(source_mk.items())},
        "invalid_first_missing_brackets": invalid_brackets,
    }


def validate_prior(prior: dict[str, Any], closure_binding: dict[str, Any]) -> dict[str, Any]:
    if prior.get("schema") != "ds02.stage2.native-source-identity-development-subset.v1":
        raise CorrectionError("prior report is not native identity subset v1")
    subset = prior.get("native_source_closed_subset", {})
    if subset.get("row_count") != 1328 or subset.get("case_count") != 118:
        raise CorrectionError("prior report row/case count differs")
    prior_closure = prior.get("source_bindings", {}).get("root064_all118_closure", {})
    prior_report = prior_closure.get("report", {})
    if prior_report.get("path") != closure_binding["path"] or prior_report.get("sha256") != closure_binding["sha256"] or prior_report.get("bytes") != closure_binding["bytes"]:
        raise CorrectionError("prior report does not bind the same root064 closure report")
    stale = subset.get("family_motive_id_counts")
    if stale != STALE_FAMILY_MOTIVE:
        raise CorrectionError(f"prior report does not contain the known stale aggregate: {stale}")
    return {
        "path": prior_closure.get("report", {}).get("path"),
        "report_sha256": prior_closure.get("report", {}).get("sha256"),
        "prior_preview_sha256": None,
        "row_count": subset.get("row_count"),
        "stale_field": "native_source_closed_subset.family_motive_id_counts",
        "stale_value": stale,
    }


def build(args: argparse.Namespace) -> dict[str, Any]:
    prior_path, prior, prior_binding = read_json(args.prior_report, "prior v1 preview")
    closure, receipt, closure_binding, receipt_binding = read_completed_product(args.closure_report, args.closure_receipt)
    prior_summary = validate_prior(prior, closure_binding)
    prior_summary["prior_preview_sha256"] = prior_binding["sha256"]
    rows, stats = collect_rows(closure)
    return {
        "schema": SCHEMA,
        "status": "PASS_FORWARD_STATS_CORRECTION_ORIGINAL_V1_PRESERVED",
        "source_bindings": {
            "prior_v1_preview": prior_binding,
            "root064_closure_report": closure_binding,
            "root064_closure_receipt": receipt_binding,
        },
        "correction": {
            "field": "native_source_closed_subset.family_motive_id_counts",
            "prior_value": STALE_FAMILY_MOTIVE,
            "corrected_value": CORRECTED_FAMILY_MOTIVE,
            "reason": "v1 formatting comprehension used the last outer family variable for the display key; source rows and total motive counts were unaffected",
            "original_v1_bytes_preserved": True,
            "recomputed_from": "root064 closure cases[].native_identity.ids",
            "actual_row_count": len(rows),
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN",
            "dynamical_impact": "UNKNOWN",
        },
        "prior_report": prior_summary,
        "native_source_closed_subset": stats,
        "native_identity_records": rows,
        "claim_boundary": {
            "source_identity": "SOURCE_CLOSED for 118 exact case-qualified rows",
            "numerical_cause": "SOURCE_CLOSED native motive/code only; this is not physical fate",
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_flux": "UNKNOWN",
            "continuous_event_time": "UNKNOWN beyond saved first-missing brackets",
            "dynamical_impact": "UNKNOWN",
            "QI": "UNKNOWN",
            "QN": "UNKNOWN",
            "QE": "UNKNOWN",
            "scientific_split_safe": "UNKNOWN",
        },
        "read_policy": {
            "prior_and_root064_json_opened": True,
            "h5_opened": False,
            "bi4_opened": False,
            "raw_partout_opened": False,
            "decoder_started": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
    }


def write_atomic(path: Path, value: dict[str, Any]) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists():
        raise CorrectionError(f"preserve existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except Exception:
        try:
            os.unlink(temp)
        except FileNotFoundError:
            pass
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", choices=["build"])
    parser.add_argument("--prior-report", required=True, type=Path)
    parser.add_argument("--closure-report", required=True, type=Path)
    parser.add_argument("--closure-receipt", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = build(args)
    write_atomic(args.output, result)
    print(json.dumps({"status": result["status"], "native_rows": result["native_source_closed_subset"]["row_count"], "corrected_family_motive_id_counts": result["native_source_closed_subset"]["family_motive_id_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
