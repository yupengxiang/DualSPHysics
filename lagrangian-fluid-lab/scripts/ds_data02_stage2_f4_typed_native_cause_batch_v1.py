#!/usr/bin/env python3
"""Guarded F4 typed/native saved-frame cause joins.

This is the F4-specific executable counterpart of the earlier F6 adapter.  It
audits the three ROOT201 F4 cases that have both a non-empty typed first-loss
set and an existing source-bound native omission report.  The five other F4
cases in ROOT201 have zero typed first-loss observations and are checked only
against the exact historical-118 membership index; they are recorded as
non-omission controls and are deliberately excluded from the deferred native
read set.

Prepare reads bounded JSON/XML/receipt metadata and records stat identities for
the large trajectory, typed-records JSONL, PartOut.csv, and RunPARTs.csv
inputs.  ``audit`` is the post-reservation entry: it streams the typed JSONL
and reads the two small native CSVs through the already reviewed official
26-column parser.  A saved-frame/bracket join and a prior numerical cause
report do not establish physical fate, continuous event time, flux, dynamics,
or QI/QN/QE; those remain UNKNOWN.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from typing import Any


SCRIPT = Path(__file__).resolve()
PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
STAGE2 = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
BASE_WORKER = SCRIPT.with_name("ds_data02_stage2_f6_dxyz_typed_native_crosscheck_v3.py")
CURRENT_PATH = STAGE2 / "CURRENT336.json"
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
F4_PROOF = STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F4_ACTUAL_ROOT_VERIFICATION_201.json"
F4_PROOF_SHA256 = "82705378c70f809543105d9182ebdab16e316de266c23fac699c0e41865dadd5"
HISTORICAL_INDEX = STAGE2 / "checkpoints/HISTORICAL_118_OMISSION_INDEX_VERIFICATION_001.json"
HISTORICAL_UNION = STAGE2 / "checkpoints/HISTORICAL_118_NATIVE_COVERAGE_UNION_003.json"
CURRENT_SCHEMA = "ds02.stage2.current336.v1"
PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
SUMMARY_SCHEMA = "ds02.stage2.typed-lifecycle-sidecar.v4"
OMISSION_SCHEMA = "ds02.stage2.omission-forensics.v2"
REQUEST_SCHEMA = "ds02.request.v1"
F4_SCHEMA = "ds02.stage2.f4-typed-native-cause-batch.v1"
F4_CONTRACT_SCHEMA = "ds02.stage2.f4-typed-native-cause-contract.v1"
F4_CROSSCHECK_SCHEMA = "ds02.stage2.f4-typed-native-crosscheck.v1"

MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_BATCH_OUTPUT_BYTES = 64 * 1024 * 1024
EXPECTED_FLUID_INITIAL_COUNT = 59072

TARGET_CASES = (
    "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p60000",
    "F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p40000",
    "F4_DROP_gap0p24000_xoffm0p08000_yoffm0p04000_uz0p40000",
)
CONTROL_CASES = (
    "F4_DROP_gap0p22000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_B08_gap0p18000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_B08_gap0p26000_xoff0p00000_yoff0p00000_uz0p50000",
    "F4_DROP_gap0p18000_xoff0p08000_yoff0p04000_uz0p40000",
    "F4_DROP_gap0p18000_xoff0p08000_yoffm0p04000_uz0p60000",
)
NATIVE_REPORTS = {
    TARGET_CASES[0]: (
        DATA / "families/F4/STAGE2_OMISSION_F4_148/omission-forensics-v1/omission-forensics.json",
        "2b3a975b60905754673942b98c0c6bceea876220036529f5be54f008d2ebc807",
    ),
    TARGET_CASES[1]: (
        DATA / "families/F4/STAGE2_OMISSION_F4_149/omission-forensics-v1/omission-forensics.json",
        "6c643cbb6bc3cef9775a10f93d225079790d7c5627bd1af080f6b72e1f1487fe",
    ),
    TARGET_CASES[2]: (
        DATA / "families/F4/STAGE2_OMISSION_F4_151/omission-forensics-v1/omission-forensics.json",
        "caaab39198756e6e752973e5ddf6837482dd181616951a279bb3eaf833321872",
    ),
}


class F4Error(ValueError):
    """Raised when a F4 identity or deferred-input contract is incomplete."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise F4Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise F4Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, deferred: bool = False, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise F4Error(f"{label} has no path")
    result = Path(value).expanduser().resolve()
    if directory:
        if not result.is_dir():
            raise F4Error(f"{label} directory is missing: {result}")
    elif not result.is_file():
        raise F4Error(f"{label} is missing: {result}")
    if not deferred and result.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}:
        raise F4Error(f"{label} is deferred payload content: {result}")
    return result


def _stat(path: Path, label: str, *, deferred: bool = False, directory: bool = False) -> dict[str, Any]:
    path = _path(path, label, deferred=deferred, directory=directory)
    value = path.stat()
    return {
        "path": str(path),
        "bytes": int(value.st_size),
        "mtime_ns": int(value.st_mtime_ns),
        "ctime_ns": int(value.st_ctime_ns),
        "st_dev": int(value.st_dev),
        "st_ino": int(value.st_ino),
    }


def _digest(path: Path, label: str, *, max_bytes: int | None = None) -> str:
    path = _path(path, label)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise F4Error(f"{label} exceeds bounded hash size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise F4Error(f"{label} exceeds bounded JSON size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise F4Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise F4Error(f"{label} must be a JSON object")
    return value


def _small_ref(path: Path, label: str, expected: Any | None = None) -> dict[str, Any]:
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise F4Error(f"{label} exceeds small-input bound")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise F4Error(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred_ref(item: dict[str, Any], label: str, *, suffixes: set[str] | None = None) -> dict[str, Any]:
    path = _path(item.get("path"), label, deferred=True)
    if suffixes and path.suffix.lower() not in suffixes:
        raise F4Error(f"{label} has an unexpected suffix: {path}")
    stat = _stat(path, label, deferred=True)
    declared = item.get("sha256", item.get("known_sha256", item.get("producer_declared_sha256")))
    if declared is None:
        raise F4Error(f"{label} has no producer SHA")
    declared = _sha(declared, f"{label} producer SHA")
    if item.get("bytes") is not None and int(item["bytes"]) != stat["bytes"]:
        raise F4Error(f"{label} byte count differs")
    return {
        **stat,
        "sha256": declared,
        "rows": item.get("rows"),
        "content_opened": False,
        "hash_checked": False,
        "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS",
    }


def _same_path(left: Any, right: Path) -> bool:
    try:
        return Path(left).expanduser().resolve() == right.resolve()
    except (TypeError, ValueError, OSError):
        return False


STAT_FIELDS = ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")


def _same_stat(actual: dict[str, Any], declared: dict[str, Any], label: str) -> None:
    if not isinstance(declared, dict):
        raise F4Error(f"{label} declared stat is missing")
    for field in STAT_FIELDS:
        if actual.get(field) != declared.get(field):
            raise F4Error(f"{label} stat differs at {field}")


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise F4Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temp.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temp.stat().st_size > limit:
            raise F4Error(f"output exceeds {limit} bytes: {path}")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("_stage2_f4_official_crosscheck", BASE_WORKER)
    if spec is None or spec.loader is None:
        raise F4Error(f"cannot load official crosscheck worker: {BASE_WORKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.FAMILY_ID = "F4"
    module.SCHEMA = F4_CROSSCHECK_SCHEMA
    return module


def _proof_case(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    if proof.get("schema") != PROOF_SCHEMA or proof.get("status") != "VERIFIED_ACTUAL_F4_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT":
        raise F4Error("ROOT201 proof schema/status differs")
    counts = proof.get("counts")
    if not isinstance(counts, dict) or counts.get("cases_requested") != 8 or counts.get("completed") != 8 or counts.get("failed") != 0:
        raise F4Error("ROOT201 proof is not the complete eight-case proof")
    rows = [row for row in proof.get("case_verifications", []) if isinstance(row, dict) and row.get("physical_case_id") == case_id]
    if len(rows) != 1:
        raise F4Error(f"ROOT201 case is not unique: {case_id}")
    row = rows[0]
    if row.get("family_id") != "F4" or row.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise F4Error(f"ROOT201 case status/family differs: {case_id}")
    if row.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise F4Error(f"ROOT201 H5 source closure differs: {case_id}")
    if row.get("native_cause_fate_legal_flux_dynamics") != "UNKNOWN":
        raise F4Error(f"ROOT201 grants physical credit: {case_id}")
    return row


def _proof_case_count(proof: dict[str, Any], case_id: str) -> int:
    row = _proof_case(proof, case_id)
    ledger = row.get("actual_role_ledgers", {}).get("fluid", {})
    count = ledger.get("first_disappearance_count")
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise F4Error(f"ROOT201 fluid first-disappearance count is invalid: {case_id}")
    return count


def _current_row(current: dict[str, Any], case_id: str, base: Any) -> dict[str, Any]:
    if current.get("schema") != CURRENT_SCHEMA:
        raise F4Error("CURRENT schema differs")
    base.FAMILY_ID = "F4"
    try:
        return base._current_case(current, case_id)
    except Exception as exc:
        raise F4Error(f"CURRENT case is not an exact F4 row: {case_id}") from exc


def _validate_conversion_f4(conversion: dict[str, Any], row: dict[str, Any], trajectory: dict[str, Any], generated_xml: dict[str, Any]) -> dict[str, Any]:
    if conversion.get("schema") != "ds-data-02.bi4-direct-conversion.v1" or conversion.get("conversion_status") != "completed":
        raise F4Error("F4 conversion report schema/status differs")
    if int(conversion.get("frames", -1)) != int(row.get("frames", -2)) or int(conversion.get("particles", -1)) != int(row.get("particles", -2)):
        raise F4Error("F4 conversion shape differs from CURRENT")
    if conversion.get("output_sha256") != trajectory.get("producer_declared_sha256"):
        raise F4Error("F4 conversion output SHA differs from CURRENT trajectory")
    blocks = conversion.get("typed_identity", {}).get("blocks") if isinstance(conversion.get("typed_identity"), dict) else None
    fluids = [item for item in blocks or [] if isinstance(item, dict) and item.get("tag") == "fluid" and item.get("type") == 3]
    if not fluids or sum(int(item.get("count", -1)) for item in fluids) != EXPECTED_FLUID_INITIAL_COUNT:
        raise F4Error("F4 conversion fluid partition does not total 59072")
    if not _same_path(conversion.get("output_hdf5"), Path(trajectory["path"])):
        raise F4Error("F4 conversion output path differs from CURRENT trajectory")
    if not _same_path(generated_xml.get("path"), Path(str(row.get("source_bindings", {}).get("generated_xml", {}).get("path")))):
        raise F4Error("F4 generated XML source edge differs")
    return {"fluid_blocks": [{"count": int(item["count"]), "mkfluid": item.get("mkfluid"), "type": item.get("type"), "tag": item.get("tag")} for item in fluids]}


def _receipt_ref(path: Path, expected: str, label: str) -> dict[str, Any]:
    ref = _small_ref(path, label, expected)
    value = _read_json(path, label)
    if str(value.get("status", "")).lower() not in {"completed", "success", "succeeded"} or value.get("returncode") != 0:
        raise F4Error(f"{label} is not a completed successful receipt")
    return ref


def _current_static_refs(row: dict[str, Any], label_prefix: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for role in ("manifest", "xmf", "conversion_report"):
        decl = row.get(role)
        if isinstance(decl, dict) and decl.get("path") and decl.get("recomputed_sha256"):
            path = Path(str(decl["path"]))
            if path.is_file():
                result[f"current_{role}"] = _small_ref(path, f"{label_prefix} CURRENT {role}", decl["recomputed_sha256"])
    bindings = row.get("source_bindings")
    if isinstance(bindings, dict):
        for role, decl in bindings.items():
            if not isinstance(decl, dict) or not decl.get("path") or not decl.get("sha256"):
                continue
            path = Path(str(decl["path"]))
            if path.is_file():
                result[role] = _small_ref(path, f"{label_prefix} source {role}", decl["sha256"])
    return result


def _build_case(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    if case_id not in TARGET_CASES:
        raise F4Error(f"unsupported F4 target: {case_id}")
    proof_case = _proof_case(proof, case_id)
    first_count = _proof_case_count(proof, case_id)
    if first_count <= 0:
        raise F4Error(f"F4 target has no typed first-disappearance target: {case_id}")
    case_manifest_path = _path(proof_case.get("case_manifest"), f"{case_id} ROOT201 case manifest")
    case_manifest_ref = _small_ref(case_manifest_path, f"{case_id} ROOT201 case manifest", proof_case.get("case_manifest_sha256"))
    case_manifest = _read_json(case_manifest_path, f"{case_id} ROOT201 case manifest")
    if case_manifest.get("family_id") != "F4" or case_manifest.get("physical_case_id") != case_id:
        raise F4Error(f"{case_id} case manifest identity differs")
    refs = case_manifest.get("source_refs")
    if not isinstance(refs, list):
        raise F4Error(f"{case_id} case manifest source_refs is missing")
    ref_by_role = {item.get("role"): item for item in refs if isinstance(item, dict) and item.get("role")}
    current_decl = ref_by_role.get("current336")
    if not isinstance(current_decl, dict):
        raise F4Error(f"{case_id} case manifest CURRENT edge is missing")
    current_path = _path(current_decl.get("path"), f"{case_id} CURRENT")
    current_ref = _small_ref(current_path, f"{case_id} CURRENT", CURRENT_SHA256)
    current = _read_json(current_path, f"{case_id} CURRENT")
    base = _load_base()
    base.CASE_ID = case_id
    base.CURRENT_SHA256 = CURRENT_SHA256
    current_row = _current_row(current, case_id, base)
    if int(current_row.get("frames", -1)) != 1201 or int(current_row.get("particles", -1)) != 83233:
        raise F4Error(f"{case_id} CURRENT shape differs from ROOT201")
    trajectory_decl = case_manifest.get("trajectory_h5")
    if not isinstance(trajectory_decl, dict):
        raise F4Error(f"{case_id} trajectory edge is missing")
    trajectory_ref = _deferred_ref(trajectory_decl, f"{case_id} trajectory H5", suffixes={".h5", ".hdf5"})
    if trajectory_ref["sha256"] != current_row["trajectory"].get("producer_declared_sha256"):
        raise F4Error(f"{case_id} trajectory SHA differs from CURRENT")
    summary_path = _path(proof_case.get("summary"), f"{case_id} typed summary")
    summary_ref = _small_ref(summary_path, f"{case_id} typed summary", proof_case.get("summary_sha256"))
    summary = _read_json(summary_path, f"{case_id} typed summary")
    base.FAMILY_ID = "F4"
    _, records_base_ref = base._validate_summary(summary, summary_path, current_row, case_id, CURRENT_SHA256)
    ledger = summary.get("role_ledgers", {}).get("fluid", {})
    if int(ledger.get("initial_count", -1)) != EXPECTED_FLUID_INITIAL_COUNT or int(ledger.get("first_disappearance_count", -1)) != first_count:
        raise F4Error(f"{case_id} typed fluid ledger differs from ROOT201")
    records_decl = summary.get("records")
    records_ref = _deferred_ref(records_decl, f"{case_id} typed records", suffixes={".jsonl"})
    records_ref["rows"] = int(records_decl.get("rows", records_base_ref.get("rows", -1)))
    if records_ref["sha256"] != records_base_ref["sha256"] or records_ref["bytes"] != records_base_ref["bytes"]:
        raise F4Error(f"{case_id} typed records edge differs from summary")
    native_path, native_sha = NATIVE_REPORTS[case_id]
    native_ref = _small_ref(native_path, f"{case_id} native omission report", native_sha)
    native = _read_json(native_path, f"{case_id} native omission report")
    native_ids = base._validate_native_report(native, current_row, case_id)
    if len(native_ids["excluded"]) != first_count:
        raise F4Error(f"{case_id} typed/native target counts differ")
    source_prov = native.get("source_provenance")
    native_decode = native.get("native_decode")
    if not isinstance(source_prov, dict) or not isinstance(native_decode, dict):
        raise F4Error(f"{case_id} native source provenance is incomplete")
    if source_prov.get("generated_xml", {}).get("sha256") != current_row.get("source_bindings", {}).get("generated_xml", {}).get("sha256"):
        raise F4Error(f"{case_id} generated XML is not CURRENT-bound")
    if source_prov.get("solver_receipt", {}).get("sha256") != current_row.get("source_bindings", {}).get("solver_receipt", {}).get("sha256"):
        raise F4Error(f"{case_id} solver receipt is not CURRENT-bound")
    generated_xml = _small_ref(_path(source_prov["generated_xml"]["path"], f"{case_id} generated XML"), f"{case_id} generated XML", source_prov["generated_xml"]["sha256"])
    conversion_decl = current_row.get("conversion_report")
    conversion_path = _path(conversion_decl.get("path"), f"{case_id} conversion report") if isinstance(conversion_decl, dict) else None
    if conversion_path is None:
        raise F4Error(f"{case_id} conversion report is missing")
    conversion_ref = _small_ref(conversion_path, f"{case_id} conversion report", conversion_decl.get("recomputed_sha256"))
    conversion = _read_json(conversion_path, f"{case_id} conversion report")
    conversion_info = _validate_conversion_f4(conversion, current_row, current_row["trajectory"], generated_xml)
    source_static = _current_static_refs(current_row, case_id)
    source_static["generated_xml"] = generated_xml
    for role in ("gencase_receipt", "solver_receipt"):
        decl = current_row.get("source_bindings", {}).get(role)
        if not isinstance(decl, dict):
            raise F4Error(f"{case_id} CURRENT source binding missing: {role}")
        source_static[role] = _receipt_ref(_path(decl["path"], f"{case_id} {role}"), decl["sha256"], f"{case_id} {role}")
    decoder_receipt_decl = native_decode.get("receipt")
    if not isinstance(decoder_receipt_decl, dict):
        raise F4Error(f"{case_id} native decoder receipt is missing")
    decoder_receipt = _receipt_ref(_path(decoder_receipt_decl["path"], f"{case_id} native decoder receipt"), decoder_receipt_decl["sha256"], f"{case_id} native decoder receipt")
    partout_decl = native_decode.get("partout")
    runparts_decl = native_decode.get("runparts")
    partout_ref = _deferred_ref(partout_decl, f"{case_id} native PartOut.csv", suffixes={".csv"})
    runparts_ref = _deferred_ref(runparts_decl, f"{case_id} native RunPARTs.csv", suffixes={".csv"})
    if partout_ref["sha256"] != native_decode["partout"].get("sha256") or runparts_ref["sha256"] != native_decode["runparts"].get("sha256"):
        raise F4Error(f"{case_id} native deferred edge differs from report")
    proof_records = proof_case.get("records_stat_only")
    if not isinstance(proof_records, dict) or not _same_path(proof_records.get("path"), Path(records_ref["path"])) or proof_records.get("sha256") != records_ref["sha256"] or int(proof_records.get("bytes", -1)) != records_ref["bytes"]:
        raise F4Error(f"{case_id} ROOT201 records edge differs")
    for role, decl in ref_by_role.items():
        if role in {"current336", "worker", "python", "runtime_config"} or decl.get("deferred") is True:
            continue
        path = Path(str(decl.get("path")))
        if path.suffix.lower() in {".h5", ".hdf5", ".jsonl"}:
            continue
        if path.is_file() and int(decl.get("bytes", 0)) <= MAX_SMALL_BYTES:
            source_static.setdefault(role, _small_ref(path, f"{case_id} case source {role}", decl.get("sha256")))
    native_decoder_binary = native_decode.get("binary")
    if isinstance(native_decoder_binary, dict) and native_decoder_binary.get("path") and native_decoder_binary.get("sha256"):
        path = _path(native_decoder_binary["path"], f"{case_id} PartVTKOut binary")
        source_static["partvtk_binary"] = _small_ref(path, f"{case_id} PartVTKOut binary", native_decoder_binary["sha256"])
    return {
        "schema": F4_CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "launchable": True,
        "physical_case_id": case_id,
        "family_id": "F4",
        "current336": current_ref,
        "root201_proof": _small_ref(F4_PROOF, f"{case_id} ROOT201 proof", F4_PROOF_SHA256),
        "root201_case_manifest": case_manifest_ref,
        "typed_summary": summary_ref,
        "native_report": native_ref,
        "source_artifacts": {key: value for key, value in source_static.items()},
        "conversion": {"ref": conversion_ref, "fluid_partition": conversion_info["fluid_blocks"]},
        "deferred_inputs": {
            "trajectory_h5": trajectory_ref,
            "typed_records": records_ref,
            "partout_csv": partout_ref,
            "runparts_csv": runparts_ref,
        },
        "decoder_receipt": decoder_receipt,
        "target_ids": [[int(zone), int(idp)] for zone, idp in sorted(native_ids["excluded"])],
        "expected_fluid_initial_count": EXPECTED_FLUID_INITIAL_COUNT,
        "first_disappearance_count": first_count,
        "claim_boundary": {"historical_native_cause": "SOURCE_BOUND_PRIOR_REPORT_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "bounded source JSON/XML/receipt plus deferred stat only", "audit": "typed JSONL, PartOut.csv and RunPARTs.csv after parent reservation", "forbidden": ["H5 content", "BI4/OBI4 content", "solver launch", "PartVTKOut launch"]},
    }


def _load_indexes() -> tuple[dict[str, Any], dict[str, Any], set[str]]:
    index = _read_json(HISTORICAL_INDEX, "historical 118 index")
    union = _read_json(HISTORICAL_UNION, "historical 118 union")
    if union.get("schema") != "ds02.stage2.historical118-native-coverage-union.v3" or union.get("status") != "PASS_EXACT_118_OF118_SOURCE_CASE_UNION":
        raise F4Error("historical 118 union is not exact")
    evidence = union.get("native_evidence")
    if not isinstance(evidence, list) or len(evidence) != 118:
        raise F4Error("historical 118 union does not expose 118 source cases")
    ids = {row.get("physical_case_id") for row in evidence if isinstance(row, dict)}
    if len(ids) != 118 or None in ids:
        raise F4Error("historical 118 union case identities are not unique")
    return index, union, ids


def _build_control_rows(proof: dict[str, Any], historical_ids: set[str]) -> list[dict[str, Any]]:
    rows = []
    for case_id in CONTROL_CASES:
        count = _proof_case_count(proof, case_id)
        if count != 0:
            raise F4Error(f"control case unexpectedly has a typed first-disappearance target: {case_id}")
        if case_id in historical_ids:
            raise F4Error(f"zero control is in exact historical 118 union: {case_id}")
        row = _proof_case(proof, case_id)
        rows.append({"physical_case_id": case_id, "family_id": "F4", "typed_first_disappearance_count": 0, "historical118_member": False, "status": "NOT_ORIGINAL118_ZERO_CONTROL_NO_NATIVE_TARGET", "case_manifest": row.get("case_manifest"), "case_manifest_sha256": row.get("case_manifest_sha256"), "native_decode_requested": False, "credit": "CURRENT_TYPED_ZERO_CONTROL_ONLY"})
    return rows


def _build_request(manifest_path: Path, manifest: dict[str, Any], entries: list[dict[str, Any]], *, output_path: Path | None = None) -> dict[str, Any]:
    input_paths: set[Path] = {SCRIPT, BASE_WORKER, manifest_path, F4_PROOF, CURRENT_PATH, HISTORICAL_INDEX, HISTORICAL_UNION, VENV, VENV.resolve(), VENV.parent.parent / "pyvenv.cfg"}
    for entry in entries:
        contract_path = _path(entry["path"], "F4 case contract")
        input_paths.add(contract_path)
        contract = _read_json(contract_path, "F4 case contract")
        for key in ("current336", "root201_proof", "root201_case_manifest", "typed_summary", "native_report"):
            ref = contract.get(key)
            if isinstance(ref, dict) and ref.get("path"):
                input_paths.add(_path(ref["path"], f"F4 contract {key}"))
        for ref in contract.get("source_artifacts", {}).values():
            if isinstance(ref, dict) and ref.get("path"):
                input_paths.add(_path(ref["path"], "F4 static source artifact"))
        conversion = contract.get("conversion", {}).get("ref")
        if isinstance(conversion, dict) and conversion.get("path"):
            input_paths.add(_path(conversion["path"], "F4 conversion report"))
        for ref in (contract.get("decoder_receipt"),):
            if isinstance(ref, dict) and ref.get("path"):
                input_paths.add(_path(ref["path"], "F4 decoder receipt"))
    runtime_dir = SCRIPT.parent
    for name in ("ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py"):
        path = runtime_dir / name
        if path.is_file():
            input_paths.add(path)
    config = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/vendor/official/DualSPHysics_v5.4/bin/linux/DsphConfig.xml")
    input_paths.add(config)
    static = sorted({path.expanduser().resolve() for path in input_paths if path.is_file() and path.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl", ".csv"}}, key=str)
    input_sha = {str(path): _digest(path, "F4 request static input", max_bytes=MAX_SMALL_BYTES) for path in static}
    deferred: set[str] = set()
    for entry in entries:
        contract = _read_json(_path(entry["path"], "F4 case contract"), "F4 case contract")
        for role in ("trajectory_h5", "typed_records", "partout_csv", "runparts_csv"):
            deferred.add(str(_path(contract["deferred_inputs"][role]["path"], role, deferred=True)))
    resource = manifest["resource_policy"]
    return {
        "schema": REQUEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "task_kind": "audit",
        "family_id": "F4",
        "batch_id": manifest["batch_id"],
        "worker_version": "f4-typed-native-cause-batch.v1",
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path.absolute()), "--output", "{attempt_root}/f4-typed-native-cause-v1-summary.json"],
        "input_files": [str(path) for path in static],
        "input_sha256": input_sha,
        "deferred_input_files": sorted(deferred),
        "deferred_input_policy": "ONE_SEQUENTIAL_PASS_PER_CASE_AFTER_PARENT_RESERVATION; H5 STAT ONLY",
        "interpreter_binding": {"literal_command_path": str(VENV), "resolved_path": str(VENV.resolve()), "sha256": input_sha[str(VENV.resolve())], "pyvenv_cfg": {"path": str((VENV.parent.parent / "pyvenv.cfg").resolve()), "sha256": input_sha[str((VENV.parent.parent / "pyvenv.cfg").resolve())]}},
        "resource_policy": resource,
        "claim_boundary": manifest["claim_boundary"],
        "source_closure": {"manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "F4 manifest", max_bytes=MAX_OUTPUT_BYTES), "proof_sha256": F4_PROOF_SHA256, "base_worker_sha256": _digest(BASE_WORKER, "official crosscheck worker", max_bytes=MAX_SMALL_BYTES), "payload_content_opened_prepare": False},
        "launch_allowed": True,
        "launch_owner": "root",
    }


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    proof_ref = _small_ref(F4_PROOF, "ROOT201 F4 proof", F4_PROOF_SHA256)
    proof = _read_json(F4_PROOF, "ROOT201 F4 proof")
    index, union, historical_ids = _load_indexes()
    if index.get("exact_historical118_membership_verified") is not True:
        raise F4Error("historical index does not assert exact membership")
    contracts = [_build_case(proof, case_id) for case_id in TARGET_CASES]
    target_ids = {item["physical_case_id"] for item in contracts}
    if target_ids != set(TARGET_CASES):
        raise F4Error("F4 target case set differs")
    controls = _build_control_rows(proof, historical_ids)
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise F4Error(f"refusing to overwrite immutable output root: {output_root}")
    case_dir = output_root / "case-contracts"
    entries = []
    for contract in contracts:
        path = case_dir / f"{contract['physical_case_id']}.json"
        _atomic(path, contract)
        entries.append({"physical_case_id": contract["physical_case_id"], "family_id": "F4", "path": str(path), "sha256": _digest(path, "F4 case contract", max_bytes=MAX_OUTPUT_BYTES), "bytes": path.stat().st_size})
    deferred_bytes = sum(sum(int(contract["deferred_inputs"][role]["bytes"]) for role in ("typed_records", "partout_csv", "runparts_csv")) for contract in contracts)
    h5_bytes = sum(int(contract["deferred_inputs"]["trajectory_h5"]["bytes"]) for contract in contracts)
    manifest = {
        "schema": F4_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "batch_id": "ROOT229_F4_TYPED_NATIVE_CAUSE_V1",
        "family_id": "F4",
        "root201_proof": proof_ref,
        "historical_index": _small_ref(HISTORICAL_INDEX, "historical 118 index"),
        "historical_union": _small_ref(HISTORICAL_UNION, "historical 118 union"),
        "contracts": entries,
        "control_cases": controls,
        "target_case_ids": sorted(target_ids),
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "case_count": len(entries), "one_sequential_case_at_a_time": True, "expected_fluid_initial_count": EXPECTED_FLUID_INITIAL_COUNT, "typed_records_passes_minimum": 1, "partout_passes_minimum": 1, "runparts_passes_minimum": 1, "trajectory_h5_stat_only": True, "h5_content_read": False, "native_bi4_read": False, "solver_launch": False, "partvtk_launch": False, "typed_records_bytes": deferred_bytes, "trajectory_h5_bytes": h5_bytes, "estimated_deferred_read_bytes": deferred_bytes, "output_cap_bytes": MAX_BATCH_OUTPUT_BYTES},
        "claim_boundary": {"native_numerical_cause": "PRIOR_SOURCE_BOUND_REPORT_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "zero_controls": "CURRENT_TYPED_ZERO_NO_HISTORICAL_TARGET; NO_NATIVE_DECODE_REQUESTED", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "launch_allowed": True,
        "launch_owner": "root",
        "source_policy": "ROOT201 and exact historical union are revalidated. The five zero-first-loss F4 controls are recorded as non-members of historical118 and are excluded from native reads. H5, typed JSONL, PartOut.csv and RunPARTs.csv are deferred after parent reservation.",
    }
    manifest_path = output_root / "f4-typed-native-cause-batch-v1-manifest.json"
    _atomic(manifest_path, manifest, limit=MAX_OUTPUT_BYTES)
    request_path = Path(args.request_output).expanduser().resolve()
    request = _build_request(manifest_path, manifest, entries)
    _atomic(request_path, request, limit=MAX_OUTPUT_BYTES)
    result = {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "F4 manifest", max_bytes=MAX_OUTPUT_BYTES), "request": str(request_path), "request_sha256": _digest(request_path, "F4 request", max_bytes=MAX_OUTPUT_BYTES), "case_ids": sorted(target_ids), "case_count": len(entries), "control_case_count": len(controls), "estimated_deferred_read_bytes": deferred_bytes, "launch_allowed": True}
    if args.checkpoint:
        checkpoint = Path(args.checkpoint).expanduser().resolve()
        _atomic(checkpoint, {"schema": "ds02.stage2.native-typed-cause-f4-root229.v1", "status": "SOURCE_PREPARED_NO_LAUNCH", **result, "payload_content_opened": False, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
        result["checkpoint"] = str(checkpoint)
    return result


def _load_contract(path: Path) -> tuple[dict[str, Any], Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    contract = _read_json(path, "F4 case contract")
    if contract.get("schema") != F4_CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED" or contract.get("launchable") is not True:
        raise F4Error("F4 case contract is not audit-ready")
    case_id = contract.get("physical_case_id")
    if case_id not in TARGET_CASES or contract.get("family_id") != "F4":
        raise F4Error("F4 case contract identity differs")
    for role in ("current336", "root201_proof", "root201_case_manifest", "typed_summary", "native_report"):
        ref = contract.get(role)
        if not isinstance(ref, dict):
            raise F4Error(f"F4 contract static role missing: {role}")
        _small_ref(_path(ref.get("path"), f"F4 contract {role}"), f"F4 contract {role}", ref.get("sha256"))
    current_path = _path(contract["current336"]["path"], "F4 CURRENT")
    current = _read_json(current_path, "F4 CURRENT")
    base = _load_base()
    base.CASE_ID = case_id
    base.FAMILY_ID = "F4"
    base.CURRENT_SHA256 = CURRENT_SHA256
    row = _current_row(current, case_id, base)
    summary_path = _path(contract["typed_summary"]["path"], "F4 typed summary")
    summary = _read_json(summary_path, "F4 typed summary")
    _, records_base = base._validate_summary(summary, summary_path, row, case_id, CURRENT_SHA256)
    native_path = _path(contract["native_report"]["path"], "F4 native report")
    native = _read_json(native_path, "F4 native report")
    native_ids = base._validate_native_report(native, row, case_id)
    if len(native_ids["excluded"]) != int(contract.get("first_disappearance_count", -1)):
        raise F4Error("F4 contract target count differs from native report")
    records_ref = contract["deferred_inputs"]["typed_records"]
    if records_ref.get("sha256") != records_base.get("sha256") or int(records_ref.get("bytes", -1)) != int(records_base.get("bytes", -2)):
        raise F4Error("F4 contract typed records edge differs from summary")
    for role, suffixes in (("trajectory_h5", {".h5", ".hdf5"}), ("typed_records", {".jsonl"}), ("partout_csv", {".csv"}), ("runparts_csv", {".csv"})):
        _same_stat(_stat(Path(contract["deferred_inputs"][role]["path"]), f"F4 {role}", deferred=True), contract["deferred_inputs"][role], f"F4 {role}")
        if Path(contract["deferred_inputs"][role]["path"]).suffix.lower() not in suffixes:
            raise F4Error(f"F4 {role} suffix differs")
    return contract, base, current, summary, native, native_ids


def _audit_case(contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract, base, current, summary, native, native_ids = _load_contract(contract_path)
    original_loader = base._load_static_contract
    base._load_static_contract = lambda _path: (contract, current, summary, native, native_ids)
    try:
        return base.audit(contract_path, output_path)
    finally:
        base._load_static_contract = original_loader


def _fixture_runparts(path: Path) -> None:
    columns = ("Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpAlloc [X]", "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho", "NpOutMov", "DtMin [s]", "DtMax [s]", "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc")
    ints = {"Part", "Steps", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho", "NpOutMov", "NpAlloc", "NctAlloc"}
    values = ["0" if col in ints else "0.0" for col in columns]
    values[columns.index("NpAlloc [X]")] = "1.0"
    values[columns.index("NctAlloc [X]")] = "1.0"
    path.write_text(";".join(columns) + "\n" + ";".join(values) + "\n# fixture footer\n", encoding="utf-8")


def _fixture_audit(manifest_path: Path, output_path: Path, allow: bool) -> dict[str, Any]:
    if not allow:
        raise F4Error("fixture execution is disabled")
    manifest = _read_json(manifest_path, "F4 fixture manifest")
    if manifest.get("fixture") is not True:
        raise F4Error("fixture audit requires explicit fixture manifest")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise F4Error("fixture contract is missing")
    if contract.get("family_id") != "F4":
        raise F4Error("fixture cross-family contract rejected")
    base = _load_base()
    base.CASE_ID = str(contract.get("physical_case_id"))
    base.FAMILY_ID = "F4"
    summary = _read_json(Path(contract["summary_path"]), "F4 fixture summary")
    native = _read_json(Path(contract["native_path"]), "F4 fixture native")
    target = base._native_rows(native)
    if not target:
        raise F4Error("fixture native target set is empty")
    records = _path(contract["records_path"], "F4 fixture records", deferred=True)
    partout = _path(contract["partout_path"], "F4 fixture PartOut", deferred=True)
    runparts = _path(contract["runparts_path"], "F4 fixture RunPARTs", deferred=True)
    def deferred(path: Path, rows: int | None = None) -> dict[str, Any]:
        ref = _stat(path, "F4 fixture deferred", deferred=True)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        ref.update({"sha256": digest, "rows": rows, "content_opened": False, "hash_checked": False})
        return ref
    refs = {"typed_records": deferred(records, 1), "partout_csv": deferred(partout, 1), "runparts_csv": deferred(runparts, 1)}
    current = {"schema": CURRENT_SCHEMA, "cases": [{"physical_case_id": base.CASE_ID, "family_id": "F4", "frames": 1, "particles": 1, "trajectory": {"path": "/fixture/trajectory.h5", "producer_declared_sha256": "0" * 64}}]}
    contract_obj = {"schema": F4_CONTRACT_SCHEMA, "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED", "physical_case_id": base.CASE_ID, "family_id": "F4", "deferred_inputs": refs}
    original_loader = base._load_static_contract
    base._load_static_contract = lambda _path: (contract_obj, current, summary, native, {"excluded": target, "ids": target})
    try:
        return base.audit(manifest_path, output_path)
    finally:
        base._load_static_contract = original_loader


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _path(args.manifest, "F4 batch manifest")
    manifest = _read_json(manifest_path, "F4 batch manifest")
    if manifest.get("fixture") is True:
        return _fixture_audit(manifest_path, Path(args.output).expanduser().resolve(), args.allow_test_fixture)
    if manifest.get("schema") != F4_SCHEMA or manifest.get("batch_id") != "ROOT229_F4_TYPED_NATIVE_CAUSE_V1" or manifest.get("family_id") != "F4":
        raise F4Error("F4 batch manifest schema/family differs")
    entries = manifest.get("contracts")
    if not isinstance(entries, list) or {item.get("physical_case_id") for item in entries if isinstance(item, dict)} != set(TARGET_CASES):
        raise F4Error("F4 batch manifest target case set differs")
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists():
        raise F4Error(f"refusing to overwrite immutable F4 batch output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    case_results = []
    case_dir = output_path.parent / "cases"
    for entry in entries:
        case_id = entry.get("physical_case_id")
        contract_path = _path(entry.get("path"), f"{case_id} F4 contract")
        case_output = case_dir / f"{case_id}.json"
        try:
            result = _audit_case(contract_path, case_output)
            case_results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_output), "result": result})
        except (F4Error, ValueError, OSError) as exc:
            case_results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [item for item in case_results if item["status"] != "COMPLETED"]
    result = {"schema": F4_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "batch_id": manifest["batch_id"], "family_id": "F4", "case_results": case_results, "control_cases": manifest.get("control_cases", []), "counts": {"requested": len(case_results), "completed": len(case_results) - len(failed), "failed": len(failed), "zero_control_cases_not_decoded": len(manifest.get("control_cases", []))}, "claim_boundary": manifest.get("claim_boundary"), "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "source_read_cost": {"sequential_case_execution": True, "h5_content_read": False, "native_bi4_read": False}}
    _atomic(output_path, result, limit=MAX_BATCH_OUTPUT_BYTES)
    return {"status": result["status"], "output": str(output_path), "completed": result["counts"]["completed"], "failed": result["counts"]["failed"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="prepare ROOT229 F4 source contracts")
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    prep.add_argument("--checkpoint", type=Path)
    run = sub.add_parser("audit", help="audit deferred F4 typed/native inputs after parent reservation")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--allow-test-fixture", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = prepare(args) if args.command == "prepare" else audit(args)
    except (F4Error, OSError, ValueError) as exc:
        print(f"F4_TYPED_NATIVE_CAUSE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
