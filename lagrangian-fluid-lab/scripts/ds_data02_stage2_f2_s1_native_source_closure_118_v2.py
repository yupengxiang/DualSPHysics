#!/usr/bin/env python3
"""Bind the completed 117-case native audit to the F2-S1 v3 singleton.

This forward-only collector reads only JSON proof/report/receipt files and the
already registered CURRENT336 aliases.  It does not rerun any case, open H5 or
BI4 content, or reinterpret native numerical exclusion as physical outflow.
The prior V2 source-gap record is retained verbatim under ``prior_gap`` while
its exact singleton replacement is validated from the new adapter report and
execution receipt.  The producer receipt is checked as a strict contract: its
expanded output and manifest arguments must identify the report, every
declared input must be stable at launch/end, and forbidden trajectory inputs
are rejected.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "ds02.stage2.f2-s1-native-source-closure-118-manifest.v1"
OUTPUT_SCHEMA = "ds02.stage2.f2-s1-native-source-closure-118.v2"
EXPECTED_CURRENT_SHA = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
EXPECTED_SINGLE_REPORT_SHA = None  # supplied by the actual completed v3 receipt
GAP_CASE_KEY = "F2/scan-F2-S1-001"


class ClosureError(ValueError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical(value: str | Path) -> str:
    return str(Path(value).expanduser().resolve(strict=False))


def bind(ref: Any, label: str, *, forbid_h5: bool = True) -> tuple[Path, dict[str, Any]]:
    if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or not isinstance(ref.get("sha256"), str):
        raise ClosureError(f"{label} lacks exact path/SHA binding")
    path = Path(ref["path"]).expanduser().resolve()
    if forbid_h5 and (path.name.endswith(".h5") or (path.name.startswith("Part_") and path.name.endswith(".bi4"))):
        raise ClosureError(f"{label} points at forbidden trajectory content: {path}")
    if not path.is_file():
        raise ClosureError(f"{label} is missing: {path}")
    actual = sha256(path)
    if actual != ref["sha256"]:
        raise ClosureError(f"{label} digest differs")
    stat_bytes = path.stat().st_size
    if "bytes" in ref and int(ref["bytes"]) != stat_bytes:
        raise ClosureError(f"{label} stat size differs")
    return path, {"path": str(path), "sha256": actual, "bytes": stat_bytes}


def read_json(ref: Any, label: str) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    path, binding = bind(ref, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ClosureError(f"{label} is not valid JSON") from exc
    if not isinstance(value, dict):
        raise ClosureError(f"{label} is not a JSON object")
    return path, value, binding


def receipt_completed(receipt: dict[str, Any], label: str) -> None:
    if receipt.get("status") != "completed" or receipt.get("returncode") != 0:
        raise ClosureError(f"{label} is not a completed zero-return receipt")


def exact_ref(actual: dict[str, Any], expected: dict[str, Any], label: str) -> None:
    if canonical(actual.get("path", "")) != canonical(expected.get("path", "")) or actual.get("sha256") != expected.get("sha256"):
        raise ClosureError(f"{label} source path/SHA differs")


def _command_value(command: list[Any], flag: str, label: str) -> str:
    for index, value in enumerate(command[:-1]):
        if str(value) == flag:
            return str(command[index + 1])
    raise ClosureError(f"{label} producer command lacks {flag}")


def _expanded(command: list[Any], output_root: Path) -> list[str]:
    return [str(value).replace("{attempt_root}", str(output_root)) for value in command]


def _validate_singleton_producer(
    report_path: Path,
    report: dict[str, Any],
    receipt: dict[str, Any],
) -> dict[str, Any]:
    """Prove the singleton report is the output of its completed root063 run.

    The report and receipt are already immutable inputs to this closure.  This
    extra gate prevents a completed receipt for another adapter run from being
    joined merely because its report has the expected schema and IDs.
    """
    request = receipt.get("request")
    if not isinstance(request, dict):
        raise ClosureError("singleton receipt lacks producer request")
    output_root = Path(str(receipt.get("output_root", ""))).expanduser().resolve()
    if not output_root.is_dir() or report_path.resolve().parent != output_root:
        raise ClosureError("singleton report is outside the completed producer output root")
    command = request.get("command")
    if not isinstance(command, list) or not command:
        raise ClosureError("singleton producer command is missing")
    expanded = _expanded(command, output_root)
    output_arg = Path(_command_value(expanded, "--output", "singleton producer")).expanduser().resolve()
    if output_arg != report_path.resolve():
        raise ClosureError("singleton producer --output does not identify the bound report")
    manifest_arg = Path(_command_value(expanded, "--manifest", "singleton producer")).expanduser().resolve()
    report_manifest = report.get("manifest")
    if not isinstance(report_manifest, dict):
        raise ClosureError("singleton report lacks producer manifest binding")
    manifest_path, manifest_binding = bind(report_manifest, "singleton producer manifest")
    if manifest_path != manifest_arg:
        raise ClosureError("singleton report manifest differs from producer --manifest")
    # The receipt's input ledger is the authoritative launch/end binding.  Do
    # not accept a report when any declared producer input is missing from it.
    input_files = request.get("input_files")
    declared = request.get("input_sha256")
    launch = receipt.get("input_hashes_at_launch")
    finish = receipt.get("input_hashes_after_run")
    if not isinstance(input_files, list) or not isinstance(declared, dict) or not isinstance(launch, dict) or not isinstance(finish, dict):
        raise ClosureError("singleton producer receipt lacks complete input ledger")
    stable_count = 0
    for value in input_files:
        path = Path(str(value)).expanduser().resolve()
        if path.name.endswith(".h5") or (path.name.startswith("Part_") and path.name.endswith(".bi4")):
            raise ClosureError(f"singleton producer input includes forbidden trajectory content: {path}")
        key = str(path)
        expected = declared.get(key) or declared.get(str(value))
        launched = launch.get(key) or launch.get(str(value))
        ended = finish.get(key) or finish.get(str(value))
        if not expected or expected != launched or expected != ended:
            raise ClosureError(f"singleton producer input is not stable at launch/end: {path}")
        bind({"path": str(path), "sha256": expected}, f"singleton producer input {path.name}")
        stable_count += 1
    if stable_count != len(input_files):
        raise ClosureError("singleton producer input ledger count differs")
    return {
        "receipt_case_id": request.get("case_id"),
        "output_root": str(output_root),
        "expanded_output": str(output_arg),
        "expanded_manifest": str(manifest_arg),
        "manifest": manifest_binding,
        "stable_input_count": stable_count,
        "command": expanded,
    }


def _validate_manifest(data: dict[str, Any]) -> dict[str, Any]:
    if data.get("schema") != MANIFEST_SCHEMA:
        raise ClosureError(f"unsupported manifest schema: {data.get('schema')}")
    refs = data.get("bindings")
    if not isinstance(refs, dict):
        raise ClosureError("manifest bindings are missing")
    required = ("proof", "proof_report", "proof_receipt", "single_report", "single_receipt", "current_original", "current_root_alias")
    for key in required:
        if key not in refs:
            raise ClosureError(f"manifest lacks {key}")
    return refs


def collect(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest_path = Path(manifest_path).resolve()
    if not manifest_path.is_file():
        raise ClosureError(f"manifest is missing: {manifest_path}")
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    refs = _validate_manifest(manifest_data)

    proof_path, proof, proof_binding = read_json(refs["proof"], "117-case independent proof")
    proof_report_path, proof_report, proof_report_binding = read_json(refs["proof_report"], "117-case native report")
    proof_receipt_path, proof_receipt, proof_receipt_binding = read_json(refs["proof_receipt"], "117-case execution receipt")
    receipt_completed(proof_receipt, "117-case execution receipt")
    if proof.get("schema") != "ds02.stage2.root-actual-verification.v1" or proof.get("status") != "PASS_ACTUAL_117_CASE_NATIVE_IDENTITY_JOIN_ONE_SOURCE_GAP":
        raise ClosureError("independent proof is not the expected 117-case source-gap proof")
    if proof.get("report") != proof_report_binding["path"] or proof.get("report_sha256") != proof_report_binding["sha256"]:
        raise ClosureError("117 proof/report binding differs")
    if proof.get("receipt") != proof_receipt_binding["path"] or proof.get("receipt_sha256") != proof_receipt_binding["sha256"]:
        raise ClosureError("117 proof/receipt binding differs")
    if proof.get("current336_sha256") != EXPECTED_CURRENT_SHA:
        raise ClosureError("117 proof CURRENT SHA differs")
    if proof.get("H5_BI4_read_by_root") is not False or proof.get("H5_BI4_decode_by_worker") is not False:
        raise ClosureError("117 proof claims forbidden H5/BI4 access")

    if proof_report.get("schema") != "ds02.stage2.native-identity-audit.v2" or proof_report.get("status") != "COMPLETED_WITH_CASE_SCOPED_SOURCE_GAPS":
        raise ClosureError("117 native report status/schema differs")
    if proof_report.get("native_id_count") != 1325:
        raise ClosureError("117 native ID count differs")
    counts = proof_report.get("case_counts", {})
    if counts.get("native_identity_source_closed") != 117 or counts.get("source_incomplete") != 1 or counts.get("requested") != 118 or counts.get("source_binding_rejected") != 0:
        raise ClosureError("117 case counts do not describe exactly one source gap")
    cases = proof_report.get("cases")
    if not isinstance(cases, list) or len(cases) != 118:
        raise ClosureError("117 report case list is not the complete 118-case catalog")
    gap_cases = [case for case in cases if case.get("case_status") == "SOURCE_INCOMPLETE"]
    if len(gap_cases) != 1 or gap_cases[0].get("case_key") != GAP_CASE_KEY:
        raise ClosureError("117 report does not contain exactly the expected F2-S1 gap")
    closed_cases = [case for case in cases if case.get("case_status") == "NATIVE_IDENTITY_SOURCE_CLOSED"]
    if len(closed_cases) != 117:
        raise ClosureError("117 report closed-case count differs")
    proof_current = proof_report.get("source_reports", {}).get("current", {})
    if proof_current.get("sha256") != EXPECTED_CURRENT_SHA:
        raise ClosureError("117 report source CURRENT SHA differs")

    original_current_path, original_current, original_current_binding = read_json(refs["current_original"], "original CURRENT336")
    root_current_path, root_current, root_current_binding = read_json(refs["current_root_alias"], "root CURRENT336 alias")
    if original_current_binding["sha256"] != EXPECTED_CURRENT_SHA or root_current_binding["sha256"] != EXPECTED_CURRENT_SHA:
        raise ClosureError("CURRENT aliases do not have the frozen SHA")
    if original_current_binding["bytes"] != root_current_binding["bytes"]:
        raise ClosureError("CURRENT aliases have different stat sizes")
    proof_current_path = canonical(proof_current.get("path", ""))
    if proof_current_path not in {str(original_current_path), str(root_current_path)}:
        raise ClosureError("117 proof CURRENT path is not one of the declared exact aliases")
    if len(original_current.get("cases", [])) != 336 or len(root_current.get("cases", [])) != 336:
        raise ClosureError("CURRENT aliases do not expose all 336 cases")

    single_report_path, single_report, single_report_binding = read_json(refs["single_report"], "F2-S1 v3 singleton report")
    single_receipt_path, single_receipt, single_receipt_binding = read_json(refs["single_receipt"], "F2-S1 v3 singleton receipt")
    receipt_completed(single_receipt, "F2-S1 v3 singleton receipt")
    singleton_producer = _validate_singleton_producer(single_report_path, single_report, single_receipt)
    if single_report.get("status") != "COMPLETED_F2_S1_NATIVE_SOURCE_JOIN_WITH_PHYSICAL_FATE_UNKNOWN":
        raise ClosureError("F2-S1 singleton report is not the completed v3 source join")
    identity = single_report.get("case_identity", {})
    if identity.get("current_case_index") != 78 or identity.get("family_id") != "F2" or identity.get("physical_case_id") != "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090":
        raise ClosureError("F2-S1 singleton identity differs")
    native = single_report.get("native_identity", {})
    if native.get("id_count") != 3 or native.get("motive_counts") != {"position": 3, "density": 0, "movement": 0} or native.get("source_mk_counts") != {"1": 3, "2": 0, "3": 0}:
        raise ClosureError("F2-S1 singleton native identity differs")
    if single_report.get("claim_boundary", {}).get("physical_fate", "").startswith("UNKNOWN") is not True or single_report.get("claim_boundary", {}).get("dynamical_impact", "").startswith("UNKNOWN") is not True:
        raise ClosureError("F2-S1 singleton physical/dynamical boundary was widened")
    if single_report.get("claim_boundary", {}).get("QI") != "UNKNOWN" or single_report.get("claim_boundary", {}).get("QN") != "UNKNOWN" or single_report.get("claim_boundary", {}).get("QE") != "UNKNOWN":
        raise ClosureError("F2-S1 singleton qualification credit is not UNKNOWN")
    alias = single_report.get("current_alias", {})
    if alias.get("same_sha256") is not True or alias.get("same_bytes") is not True:
        raise ClosureError("F2-S1 singleton does not carry exact CURRENT alias closure")
    singleton_sources = single_report.get("source_bindings", {})
    if singleton_sources.get("v37_converter_report", {}).get("sha256") != "369a0deb576bca86ef9603ac13f9d26ed145d3a6b903074428132efe57a9e62c":
        raise ClosureError("F2-S1 singleton root-049 report binding differs")
    if singleton_sources.get("typed_only_producer_report", {}).get("sha256") != "6614fdd38608149841a26d373c103e8582e6804f3f02a0df17fd7470899a23c3":
        raise ClosureError("F2-S1 singleton typed-only owner binding differs")
    if singleton_sources.get("v37_output_hdf5", {}).get("opened") is not False:
        raise ClosureError("F2-S1 singleton typed HDF5 was opened")

    # Retain the old gap row verbatim for provenance while replacing it in the
    # active catalog with the source-complete singleton.  No other row is
    # re-read or recomputed.
    active_cases = list(closed_cases)
    replacement = {
        "case_key": GAP_CASE_KEY,
        "case_status": "NATIVE_IDENTITY_SOURCE_CLOSED",
        "family_id": "F2",
        "physical_case_id": identity["physical_case_id"],
        "current_identity": {
            "current_case_index": identity["current_case_index"],
            "family_id": identity["family_id"],
            "physical_case_id": identity["physical_case_id"],
            "runtime_case_alias": identity.get("runtime_case_alias"),
        },
        "native_cause": {
            "status": "SOURCE_CLOSED_SINGLETON_ADAPTER_V3",
            "native_count": native["id_count"],
            "motive": "position",
            "source": "official PartVTKOut CSV + root-049 typed blocks + exact CURRENT alias",
            "physical_fate": "UNKNOWN_NOT_PROVEN",
            "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
            "continuous_event_time": "UNKNOWN; saved first-missing bracket only",
            "dynamical_impact": "UNKNOWN; missing mass is a source-visible lower bound only",
        },
        "native_identity": native,
        "source_closure": {
            "singleton_report": single_report_binding,
            "singleton_receipt": single_receipt_binding,
            "previous_v2_gap": gap_cases[0],
        },
    }
    active_cases.append(replacement)
    active_cases.sort(key=lambda row: row["case_key"])
    if len(active_cases) != 118 or len({row["case_key"] for row in active_cases}) != 118:
        raise ClosureError("active 118-case catalog is not unique")

    result = {
        "schema": OUTPUT_SCHEMA,
        "status": "PASS_ACTUAL_118_CASE_SOURCE_CLOSED_WITH_PRIOR_GAP_SPECTRUM_PRESERVED",
        "source_bindings": {
            "proof_117": proof_binding,
            "proof_117_report": proof_report_binding,
            "proof_117_receipt": proof_receipt_binding,
            "singleton_report": single_report_binding,
            "singleton_receipt": single_receipt_binding,
            "singleton_producer": singleton_producer,
            "current_original": original_current_binding,
            "current_root_alias": root_current_binding,
        },
        "case_counts": {
            "requested": 118,
            "native_identity_source_closed": 118,
            "source_binding_rejected": 0,
            "source_incomplete_active": 0,
            "prior_v2_source_incomplete": 1,
        },
        "native_id_count": 1328,
        "cases": active_cases,
        "prior_gap": gap_cases[0],
        "provenance": {
            "v2_status": proof.get("status"),
            "v2_report_status": proof_report.get("status"),
            "singleton_replacement": "F2-S1 source gap replaced by one completed v3 report/receipt; the 117 existing rows were not rerun",
            "current_alias_policy": "forensic original and root alias require exact SHA/stat equality",
        },
        "claim_boundary": {
            "native_identity": "source-closed for all 118 cases, including the three F2-S1 official PartVTKOut rows",
            "conversion_initial_filter": "UNKNOWN outside the explicit selected root-049 typed metadata",
            "physical_fate": "UNKNOWN_NOT_PROVEN; numerical exclusion is not legal spill or physical outflow",
            "continuous_event_time": "UNKNOWN beyond saved first-missing brackets",
            "dynamical_impact": "UNKNOWN; mass visibility is not a dynamics bound",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
        },
        "read_policy": {
            "json_reports_receipts_current_opened": True,
            "h5_opened": False,
            "bi4_frames_opened": False,
            "raw_partout_opened": False,
            "decoder_started": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "manifest": {"path": str(manifest_path), "sha256": sha256(manifest_path), "bytes": manifest_path.stat().st_size},
    }
    output_path = Path(output_path).resolve()
    if output_path.exists():
        raise ClosureError(f"preserve existing output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    fd, tmp = tempfile.mkstemp(prefix=f".{output_path.name}.", dir=str(output_path.parent), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(payload); stream.flush(); os.fsync(stream.fileno())
        os.replace(tmp, output_path)
    except Exception:
        try: os.unlink(tmp)
        except FileNotFoundError: pass
        raise
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = collect(args.manifest, args.output)
    print(json.dumps({"status": result["status"], "case_count": result["case_counts"]["native_identity_source_closed"], "native_id_count": result["native_id_count"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
