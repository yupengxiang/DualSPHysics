#!/usr/bin/env python3
"""Guarded execution adapter for the three remaining ROOT226 F6 joins.

ROOT226 V2 is intentionally a source planner.  This forward version is the
first executable adapter: it accepts only the three launchable F6 contracts
emitted by the immutable V2 manifest, validates the conversion/current/native
edges, and delegates the deferred typed JSONL/PartOut/RunPARTs read to the
already reviewed official crosscheck parser.  A case is processed completely
before the next case starts and an individual failure is retained.

The adapter never opens H5 or BI4 content.  The H5 path is stat-checked after
the parent reservation because the typed producer proof binds it, while the
typed JSONL and the two small native CSVs are read once by the crosscheck
worker.  The result is a saved-frame diagnostic only; physical fate, legal
flux, continuous event time, dynamics and QI/QN/QE remain UNKNOWN.
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
CURRENT_SHA256 = "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b"
SOURCE_MANIFEST_DEFAULT = STAGE2 / (
    "requests/native-typed-cause-batch-root226-prepared-006/"
    "native-typed-cause-batch-v2-manifest.json"
)
SOURCE_MANIFEST_SHA256 = "24ab59e2ed88a0ec3c946db2c4ea9c368e34f6c4a81457c1a068b8135065512e"
INVENTORY = STAGE2 / "checkpoints/HISTORICAL118_NATIVE_TYPED_SOURCE_INVENTORY_AFTER_ROOT193_V1.json"
INVENTORY_SHA256 = "3d274db71d01f680b9997cc364298f9974a2cb09978acfb81f9a152622e75a00"
PROOFS = {
    "F6_203": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_203.json",
    "F6_210": STAGE2 / "checkpoints/TYPED_LIFECYCLE_BATCH_F6_ACTUAL_ROOT_VERIFICATION_210.json",
}
PROOF_SHA256 = {
    "F6_203": "e146f0a378f56eccc59c5052aa27703322c40712192f38e9c5edce7acb87793c",
    "F6_210": "4c02c64912a46523d94c71c1836f807508d10079051a74fb5ec65f739ec0f5e5",
}
ROOT212_CASE = "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0375_YAWM12_DP025"
ROOT216_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0625_YAWM06_DP025"
ROOT219_CASE = "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0875_YAWP06_DP025"
ROOT220_PROOF = STAGE2 / "checkpoints/F6_TYPED_NATIVE_CAUSE_BATCH_V1_ACTUAL_ROOT_VERIFICATION_220.json"
ROOT220_PROOF_SHA256 = "5234b72328de3e662eb1a2f590bd792eb5919c4bdab3870e5e986e976179be82"
ROOT212_PROOF = STAGE2 / "checkpoints/F6_DXYZ_TYPED_NATIVE_CROSSCHECK_V3_ACTUAL_ROOT_VERIFICATION_212.json"
ROOT212_PROOF_SHA256 = "6a562b36a26472fc459068751c29627db1fa6420b3b6f5a35f8110b36ff2a60e"
EXPECTED_CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_DXYZ_S0625_YAWM06_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYXZ_S0375_YAWM12_DP025",
    "F6_STAGE1_ANGULAR_RELEASE_DYZX_S0625_YAWM06_DP025",
}

MAX_SMALL_BYTES = 8 * 1024 * 1024
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
MAX_BATCH_OUTPUT_BYTES = 64 * 1024 * 1024
V3_SCHEMA = "ds02.stage2.native-typed-cause-batch.v3"
V3_CONTRACT_SCHEMA = "ds02.stage2.native-typed-cause-contract.v3"
REQUEST_SCHEMA = "ds02.request.v1"
BASE_CONTRACT_SCHEMA = "ds02.stage2.f6-dxyz-typed-native-crosscheck-contract.v1"
BASE_CURRENT_SCHEMA = "ds02.stage2.current336.v1"
BASE_PROOF_SCHEMA = "ds02.stage2.root-actual-verification.v1"
BASE_OMISSION_SCHEMA = "ds02.stage2.omission-forensics.v2"


class V3Error(ValueError):
    """Raised for an incomplete source, identity, or deferred-input contract."""


def _sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise V3Error(f"{label} must be a SHA-256 digest")
    value = value.lower()
    if any(char not in "0123456789abcdef" for char in value):
        raise V3Error(f"{label} is not hexadecimal")
    return value


def _path(value: Any, label: str, *, deferred: bool = False, directory: bool = False) -> Path:
    if not isinstance(value, (str, os.PathLike)) or not str(value):
        raise V3Error(f"{label} has no path")
    result = Path(value).expanduser().resolve()
    if directory:
        if not result.is_dir():
            raise V3Error(f"{label} directory is missing: {result}")
    elif not result.is_file():
        raise V3Error(f"{label} is missing: {result}")
    if not deferred and result.suffix.lower() in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl"}:
        raise V3Error(f"{label} is deferred payload content: {result}")
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
    path = _path(path, label, deferred=False)
    if max_bytes is not None and path.stat().st_size > max_bytes:
        raise V3Error(f"{label} exceeds bounded hash size: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path, label: str, *, max_bytes: int = MAX_SMALL_BYTES) -> dict[str, Any]:
    path = _path(path, label)
    if path.stat().st_size > max_bytes:
        raise V3Error(f"{label} exceeds bounded JSON size: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise V3Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise V3Error(f"{label} must be a JSON object")
    return value


def _small_ref(path: Path, label: str, expected: Any | None = None) -> dict[str, Any]:
    stat = _stat(path, label)
    if stat["bytes"] > MAX_SMALL_BYTES:
        raise V3Error(f"{label} exceeds small-input bound")
    actual = _digest(path, label, max_bytes=MAX_SMALL_BYTES)
    if expected is not None and actual != _sha(expected, f"{label} expected SHA"):
        raise V3Error(f"{label} SHA differs: expected {expected}, got {actual}")
    return {**stat, "sha256": actual, "content_opened": True}


def _deferred_ref(item: dict[str, Any], label: str) -> dict[str, Any]:
    path = _path(item.get("path"), label, deferred=True)
    stat = _stat(path, label, deferred=True)
    if item.get("bytes") is not None and int(item["bytes"]) != stat["bytes"]:
        raise V3Error(f"{label} byte count differs")
    declared = item.get("sha256", item.get("producer_declared_sha256"))
    if declared is None:
        raise V3Error(f"{label} has no producer SHA")
    return {
        **stat,
        "sha256": _sha(declared, f"{label} producer SHA"),
        "rows": item.get("rows"),
        "content_opened": False,
        "hash_checked": False,
        "read_policy": "DEFERRED_AFTER_PARENT_RESERVATION_SINGLE_PASS",
    }


def _atomic(path: Path, value: dict[str, Any], *, limit: int = MAX_OUTPUT_BYTES) -> None:
    path = Path(path).expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise V3Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, indent=2, ensure_ascii=False, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise V3Error(f"output exceeds {limit} bytes: {path}")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _load_base():
    spec = importlib.util.spec_from_file_location("_stage2_f6_crosscheck_v3_adapter", BASE_WORKER)
    if spec is None or spec.loader is None:
        raise V3Error(f"cannot load official crosscheck source: {BASE_WORKER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _proof_case(proof: dict[str, Any], case_id: str) -> dict[str, Any]:
    if proof.get("schema") != BASE_PROOF_SCHEMA:
        raise V3Error("typed proof schema differs")
    if not str(proof.get("status", "")).startswith("VERIFIED_ACTUAL_"):
        raise V3Error("typed proof is not an actual completed proof")
    cases = proof.get("case_verifications")
    if not isinstance(cases, list):
        raise V3Error("typed proof case_verifications is missing")
    matches = [item for item in cases if isinstance(item, dict) and item.get("physical_case_id") == case_id]
    if len(matches) != 1:
        raise V3Error(f"typed proof case is not unique: {case_id}")
    item = matches[0]
    if item.get("status") != "VERIFIED_SAVED_MASK_DIAGNOSTIC_ONLY":
        raise V3Error(f"typed proof case status differs: {case_id}")
    if item.get("source_H5_prepost_known_SHA_and_current_stat_equal") is not True:
        raise V3Error(f"typed proof H5 source closure differs: {case_id}")
    if item.get("native_cause_fate_legal_flux_dynamics") != "UNKNOWN":
        raise V3Error(f"typed proof grants physical credit: {case_id}")
    return item


def _proof_for_contract(proof_batch: str) -> tuple[Path, str]:
    path = PROOFS.get(proof_batch)
    if path is None:
        raise V3Error(f"unsupported typed proof batch: {proof_batch}")
    return path, PROOF_SHA256[proof_batch]


def _load_source_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_json(path, "ROOT226 V2 source manifest")
    if manifest.get("schema") != "ds02.stage2.native-typed-cause-batch.v2" or manifest.get("batch_id") != "ROOT226":
        raise V3Error("source manifest is not ROOT226 V2")
    contracts = manifest.get("contracts")
    if not isinstance(contracts, list):
        raise V3Error("source manifest contracts are missing")
    launchable = [item for item in contracts if isinstance(item, dict) and item.get("launchable") is True]
    ids = {item.get("physical_case_id") for item in launchable}
    if ids != EXPECTED_CASES or len(launchable) != 3:
        raise V3Error(f"ROOT226 launchable F6 set differs: {sorted(ids)}")
    if any(item.get("family_id") != "F6" for item in launchable):
        raise V3Error("ROOT226 source manifest contains a non-F6 launchable case")
    return manifest


def _root212_and_existing_overlap(case_id: str) -> bool:
    if case_id in {ROOT212_CASE, ROOT216_CASE, ROOT219_CASE}:
        return True
    if not ROOT220_PROOF.is_file():
        return False
    proof = _read_json(ROOT220_PROOF, "ROOT220 proof")
    if _digest(ROOT220_PROOF, "ROOT220 proof", max_bytes=MAX_SMALL_BYTES) != ROOT220_PROOF_SHA256:
        raise V3Error("ROOT220 proof SHA differs")
    return any(isinstance(item, dict) and item.get("physical_case_id") == case_id for item in proof.get("case_verifications", []))


def _validate_receipt(path: Path, expected: Any, label: str) -> dict[str, Any]:
    ref = _small_ref(path, label, expected)
    receipt = _read_json(path, label)
    status = str(receipt.get("status", "")).lower()
    if receipt.get("returncode") != 0 or status not in {"completed", "success", "succeeded"}:
        raise V3Error(f"{label} is not completed successfully")
    return {"ref": ref, "value": receipt}


def _normalize_contract(source_manifest_path: Path, source_item: dict[str, Any], base: Any) -> dict[str, Any]:
    case_path = _path(source_item.get("path"), "ROOT226 V2 case contract")
    case_sha = _sha(source_item.get("sha256"), "ROOT226 V2 case contract SHA")
    _small_ref(case_path, "ROOT226 V2 case contract", case_sha)
    source_contract = _read_json(case_path, "ROOT226 V2 case contract")
    case_id = source_contract.get("physical_case_id")
    if case_id not in EXPECTED_CASES or source_contract.get("family_id") != "F6":
        raise V3Error(f"case is not one of the three ROOT226 F6 cases: {case_id}")
    if _root212_and_existing_overlap(case_id):
        raise V3Error(f"case overlaps a completed/pending native join: {case_id}")
    if source_contract.get("schema") != "ds02.stage2.native-typed-cause-contract.v2" or source_contract.get("launchable") is not True:
        raise V3Error(f"case contract is not launchable V2 source: {case_id}")
    source_v2 = source_contract.get("source_artifacts")
    if not isinstance(source_v2, dict):
        raise V3Error(f"source artifacts are missing: {case_id}")
    current_identity = source_contract.get("current_identity")
    current_path = _path(current_identity.get("path"), f"{case_id} CURRENT", deferred=False)
    current_ref = _small_ref(current_path, f"{case_id} CURRENT", CURRENT_SHA256)
    current = _read_json(current_path, f"{case_id} CURRENT")
    if current.get("schema") != BASE_CURRENT_SCHEMA:
        raise V3Error(f"CURRENT schema differs: {case_id}")
    base.CASE_ID = case_id
    base.FAMILY_ID = "F6"
    base.CURRENT_SHA256 = CURRENT_SHA256
    base.SCRIPT = SCRIPT
    base.VENV = VENV
    current_row = base._current_case(current, case_id)

    typed = source_contract.get("typed_evidence")
    if not isinstance(typed, dict):
        raise V3Error(f"typed evidence is missing: {case_id}")
    summary_ref_decl = typed.get("summary")
    if not isinstance(summary_ref_decl, dict):
        raise V3Error(f"typed summary edge is missing: {case_id}")
    summary_path = _path(summary_ref_decl.get("path"), f"{case_id} typed summary")
    summary_ref = _small_ref(summary_path, f"{case_id} typed summary", summary_ref_decl.get("sha256"))
    summary = _read_json(summary_path, f"{case_id} typed summary")
    trajectory, records_base_ref = base._validate_summary(summary, summary_path, current_row, case_id, CURRENT_SHA256)
    if int(summary.get("role_ledgers", {}).get("fluid", {}).get("initial_count", -1)) != 327680:
        raise V3Error(f"F6 typed initial fluid count differs: {case_id}")
    if int(summary.get("role_ledgers", {}).get("fluid", {}).get("first_disappearance_count", -1)) <= 0:
        raise V3Error(f"F6 typed target set is empty: {case_id}")

    records_decl = typed.get("records")
    if not isinstance(records_decl, dict):
        raise V3Error(f"typed records edge is missing: {case_id}")
    typed_ref = _deferred_ref(records_decl, f"{case_id} typed records")
    typed_ref["rows"] = int(records_decl.get("rows", records_base_ref.get("rows", -1)))
    if typed_ref["sha256"] != records_base_ref["sha256"] or typed_ref["bytes"] != records_base_ref["bytes"]:
        raise V3Error(f"typed record edge differs from summary: {case_id}")

    native_decl = source_contract.get("native_evidence")
    if not isinstance(native_decl, dict):
        raise V3Error(f"native evidence is missing: {case_id}")
    native_path = _path(native_decl.get("path"), f"{case_id} native report")
    native_ref = _small_ref(native_path, f"{case_id} native report", native_decl.get("sha256"))
    native = _read_json(native_path, f"{case_id} native report")
    native_ids = base._validate_native_report(native, current_row, case_id)
    if not native_ids["excluded"]:
        raise V3Error(f"native target set is empty: {case_id}")
    if len(native_ids["excluded"]) != int(summary.get("role_ledgers", {}).get("fluid", {}).get("first_disappearance_count", -1)):
        raise V3Error(f"typed/native target counts differ: {case_id}")

    proof_batch = source_contract.get("proof_batch")
    proof_path, proof_sha = _proof_for_contract(proof_batch)
    proof_ref = _small_ref(proof_path, f"{case_id} typed proof", proof_sha)
    proof = _read_json(proof_path, f"{case_id} typed proof")
    proof_case = _proof_case(proof, case_id)
    if not _path(proof_case.get("summary"), f"{case_id} proof summary").samefile(summary_path):
        raise V3Error(f"typed proof summary path differs: {case_id}")
    if proof_case.get("summary_sha256") != summary_ref["sha256"]:
        raise V3Error(f"typed proof summary SHA differs: {case_id}")
    if proof_case.get("records_stat_only", {}).get("sha256") != typed_ref["sha256"]:
        raise V3Error(f"typed proof records SHA differs: {case_id}")

    source_refs: dict[str, Any] = {}
    for role, declaration in source_v2.items():
        if not isinstance(declaration, dict) or not declaration.get("path"):
            continue
        if role in {"raw_solver_root", "raw_solver_root_stat_only"}:
            source_refs[role] = {"path": str(_path(declaration["path"], f"{case_id} {role}", directory=True)), "stat": declaration.get("stat"), "content_opened": False}
            continue
        path = _path(declaration["path"], f"{case_id} {role}")
        source_refs[role] = _small_ref(path, f"{case_id} {role}", declaration.get("sha256"))

    conversion_ref = source_refs.get("conversion_report")
    xml_ref = source_refs.get("generated_xml")
    if not isinstance(conversion_ref, dict) or not isinstance(xml_ref, dict):
        raise V3Error(f"conversion/XML source edges are incomplete: {case_id}")
    conversion = _read_json(Path(conversion_ref["path"]), f"{case_id} conversion report")
    source_provenance = native.get("source_provenance")
    if not isinstance(source_provenance, dict):
        raise V3Error(f"native source provenance is missing: {case_id}")
    data_root = _path(source_provenance.get("data_root"), f"{case_id} native data root", directory=True)
    base._validate_conversion(conversion, current_row, Path(xml_ref["path"]), xml_ref["sha256"], data_root)
    for role in ("gencase_receipt", "solver_receipt"):
        if role in source_refs:
            _validate_receipt(Path(source_refs[role]["path"]), source_refs[role]["sha256"], f"{case_id} {role}")
    decoder = native.get("native_decode", {}).get("receipt") if isinstance(native.get("native_decode"), dict) else None
    if not isinstance(decoder, dict):
        raise V3Error(f"native decoder receipt edge is missing: {case_id}")
    decoder_path = _path(decoder.get("path"), f"{case_id} native decoder receipt")
    decoder_ref = _small_ref(decoder_path, f"{case_id} native decoder receipt", decoder.get("sha256"))
    _validate_receipt(decoder_path, decoder_ref["sha256"], f"{case_id} native decoder receipt")

    deferred_native = source_contract.get("native_deferred_inputs")
    if not isinstance(deferred_native, dict):
        raise V3Error(f"native deferred edges are missing: {case_id}")
    partout_ref = _deferred_ref(deferred_native.get("partout", {}), f"{case_id} native PartOut.csv")
    runparts_ref = _deferred_ref(deferred_native.get("runparts", {}), f"{case_id} native RunPARTs.csv")
    native_decode = native.get("native_decode") if isinstance(native.get("native_decode"), dict) else {}
    for role, ref in (("partout", partout_ref), ("runparts", runparts_ref)):
        edge = native_decode.get(role)
        if not isinstance(edge, dict) or os.path.realpath(str(edge.get("path"))) != os.path.realpath(ref["path"]):
            raise V3Error(f"{case_id} {role} path is not bound to native report")
        if edge.get("sha256") != ref["sha256"] or int(edge.get("bytes", -1)) != ref["bytes"]:
            raise V3Error(f"{case_id} {role} producer edge differs")

    h5_ref = _deferred_ref(current_identity.get("trajectory", {}), f"{case_id} source trajectory")
    if h5_ref["sha256"] != current_row["trajectory"].get("producer_declared_sha256"):
        raise V3Error(f"{case_id} source trajectory SHA differs")

    normalized = {
        "schema": V3_CONTRACT_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "launchable": True,
        "physical_case_id": case_id,
        "family_id": "F6",
        "source_v2_contract": {"path": str(case_path), "sha256": case_sha, "bytes": int(case_path.stat().st_size)},
        "proof": {"path": str(proof_path), "sha256": proof_sha, "bytes": proof_ref["bytes"], "proof_batch": proof_batch},
        "current336": current_ref,
        "typed_summary": summary_ref,
        "native_report": native_ref,
        "source_artifacts": source_refs,
        "deferred_inputs": {
            "trajectory_h5": h5_ref,
            "typed_records": typed_ref,
            "partout_csv": partout_ref,
            "runparts_csv": runparts_ref,
        },
        "target_ids": [[int(zone), int(idp)] for zone, idp in sorted(native_ids["excluded"])],
        "expected_fluid_initial_count": 327680,
        "first_disappearance_count": len(native_ids["excluded"]),
        "claim_boundary": {"typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "native_numerical_cause": "PRIOR_SOURCE_BOUND_EVIDENCE_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
        "read_policy": {"prepare": "bounded source JSON/XML/receipt plus deferred stat only", "audit": "typed JSONL, PartOut.csv and RunPARTs.csv after parent reservation", "forbidden": ["H5 content", "BI4/OBI4 content", "solver launch", "PartVTKOut launch"]},
    }
    return normalized


def _build_manifest(source_manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = _load_source_manifest(source_manifest_path)
    launchable = [item for item in source["contracts"] if isinstance(item, dict) and item.get("launchable") is True]
    base = _load_base()
    contracts = [_normalize_contract(source_manifest_path, item, base) for item in launchable]
    ids = {item["physical_case_id"] for item in contracts}
    if ids != EXPECTED_CASES:
        raise V3Error(f"normalized ROOT226 case set differs: {sorted(ids)}")
    manifest = {
        "schema": V3_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "batch_id": "ROOT226_V3",
        "family_id": "F6",
        "source_manifest": {"path": str(source_manifest_path), "sha256": _digest(source_manifest_path, "ROOT226 V2 source manifest", max_bytes=MAX_OUTPUT_BYTES)},
        "contracts": [],
        "case_ids": sorted(ids),
        "resource_policy": {"cpu_threads": 1, "max_wall_seconds": 3600, "memory_max_bytes": 4 * 1024 * 1024 * 1024, "case_count": 3, "one_sequential_case_at_a_time": True, "typed_records_passes_minimum": 1, "partout_passes_minimum": 1, "runparts_passes_minimum": 1, "h5_stat_only": True, "h5_content_read": False, "native_bi4_read": False, "solver_launch": False, "output_cap_bytes": MAX_BATCH_OUTPUT_BYTES},
        "claim_boundary": {"native_numerical_cause": "PRIOR_SOURCE_BOUND_EVIDENCE_ONLY", "typed_native_saved_frame_join": "DIAGNOSTIC_ONLY", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "three_f6_cases_are_not_f4_or_new_118_closure": True},
        "launch_allowed": True,
        "launch_owner": "root",
        "source_policy": "The source V2 manifest and every static contract edge are revalidated. H5 is stat-only; typed JSONL/PartOut/RunPARTs are deferred until parent reservation.",
    }
    return manifest, contracts


def _write_manifest_and_request(args: argparse.Namespace) -> dict[str, Any]:
    source_path = _path(args.source_manifest, "ROOT226 V2 source manifest")
    source_sha = _digest(source_path, "ROOT226 V2 source manifest", max_bytes=MAX_OUTPUT_BYTES)
    if source_sha != SOURCE_MANIFEST_SHA256:
        raise V3Error(f"ROOT226 V2 source manifest SHA differs: {source_sha}")
    manifest, contracts = _build_manifest(source_path)
    output_root = Path(args.output_root).expanduser().resolve()
    if output_root.exists():
        raise V3Error(f"refusing to overwrite immutable output root: {output_root}")
    contract_dir = output_root / "case-contracts"
    entries = []
    for contract in contracts:
        path = contract_dir / f"{contract['physical_case_id']}.json"
        _atomic(path, contract, limit=MAX_OUTPUT_BYTES)
        entries.append({"physical_case_id": contract["physical_case_id"], "family_id": "F6", "path": str(path), "sha256": _digest(path, "ROOT226 V3 case contract", max_bytes=MAX_OUTPUT_BYTES), "bytes": path.stat().st_size})
    manifest["contracts"] = entries
    total_read = sum(int(c["deferred_inputs"]["typed_records"]["bytes"]) + int(c["deferred_inputs"]["partout_csv"]["bytes"]) + int(c["deferred_inputs"]["runparts_csv"]["bytes"]) for c in contracts)
    manifest["resource_policy"]["estimated_deferred_read_bytes"] = total_read
    manifest_path = output_root / "native-typed-cause-batch-v3-manifest.json"
    _atomic(manifest_path, manifest, limit=MAX_OUTPUT_BYTES)
    request_path = Path(args.request_output).expanduser().resolve()
    request = _build_request(manifest_path, manifest, entries, source_path)
    _atomic(request_path, request, limit=MAX_OUTPUT_BYTES)
    result = {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT226 V3 manifest", max_bytes=MAX_OUTPUT_BYTES), "request": str(request_path), "request_sha256": _digest(request_path, "ROOT226 V3 request", max_bytes=MAX_OUTPUT_BYTES), "case_ids": manifest["case_ids"], "case_count": len(entries), "estimated_deferred_read_bytes": total_read, "launch_allowed": True}
    if args.checkpoint:
        checkpoint = Path(args.checkpoint).expanduser().resolve()
        _atomic(checkpoint, {"schema": "ds02.stage2.native-typed-cause-root226-v3.v1", "status": "SOURCE_PREPARED_NO_LAUNCH", **result, "payload_content_opened": False, "physical_fate": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}, limit=MAX_OUTPUT_BYTES)
        result["checkpoint"] = str(checkpoint)
    return result


def _build_request(manifest_path: Path, manifest: dict[str, Any], entries: list[dict[str, Any]], source_manifest_path: Path) -> dict[str, Any]:
    input_paths: set[Path] = {SCRIPT, BASE_WORKER, manifest_path, source_manifest_path, CURRENT_SHA256 and STAGE2 / "CURRENT336.json", INVENTORY, VENV, VENV.resolve(), VENV.parent.parent / "pyvenv.cfg"}
    runtime_dir = PRIMARY / "lagrangian-fluid-lab/scripts"
    input_paths.update(runtime_dir / name for name in ("ds_data02_runtime_v8.py", "ds_data02_stage2_dispatch_v8.py", "ds_data02_strict_dispatch_v8.py"))
    deferred: set[str] = set()
    for entry in entries:
        contract_path = _path(entry["path"], "ROOT226 V3 case contract")
        input_paths.add(contract_path)
        contract = _read_json(contract_path, "ROOT226 V3 case contract")
        input_paths.add(_path(contract["proof"]["path"], "typed proof"))
        input_paths.add(_path(contract["typed_summary"]["path"], "typed summary"))
        input_paths.add(_path(contract["native_report"]["path"], "native report"))
        for ref in contract.get("source_artifacts", {}).values():
            if isinstance(ref, dict) and isinstance(ref.get("path"), str) and ref.get("content_opened") is True:
                input_paths.add(_path(ref["path"], "static source edge"))
        for role in ("trajectory_h5", "typed_records", "partout_csv", "runparts_csv"):
            deferred.add(str(_path(contract["deferred_inputs"][role]["path"], role, deferred=True)))
    unique = sorted({p.expanduser().resolve() for p in input_paths if p.is_file() and p.suffix.lower() not in {".h5", ".hdf5", ".bi4", ".obi4", ".jsonl", ".csv"}}, key=str)
    input_sha = {str(path): _digest(path, "ROOT226 V3 static request input", max_bytes=MAX_SMALL_BYTES) for path in unique}
    return {
        "schema": REQUEST_SCHEMA,
        "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED",
        "task_kind": "audit",
        "family_id": "F6",
        "batch_id": "ROOT226_V3",
        "worker_version": "native-typed-cause-batch.v3",
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path.absolute()), "--output", "{attempt_root}/native-typed-cause-batch-v3-summary.json"],
        "input_files": [str(path) for path in unique],
        "input_sha256": input_sha,
        "deferred_input_files": sorted(deferred),
        "deferred_input_policy": "ONE_SEQUENTIAL_PASS_PER_CASE_AFTER_PARENT_RESERVATION; H5 STAT ONLY",
        "interpreter_binding": {"literal_command_path": str(VENV), "resolved_path": str(VENV.resolve()), "resolved_sha256": input_sha[str(VENV.resolve())], "pyvenv_cfg": {"path": str((VENV.parent.parent / "pyvenv.cfg").resolve()), "sha256": input_sha[str((VENV.parent.parent / "pyvenv.cfg").resolve())]}},
        "resource_policy": manifest["resource_policy"],
        "claim_boundary": manifest["claim_boundary"],
        "source_closure": {"manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path, "ROOT226 V3 manifest", max_bytes=MAX_OUTPUT_BYTES), "source_v2_manifest": str(source_manifest_path), "source_v2_manifest_sha256": _digest(source_manifest_path, "ROOT226 V2 source manifest", max_bytes=MAX_OUTPUT_BYTES), "base_worker_sha256": _digest(BASE_WORKER, "official crosscheck worker", max_bytes=MAX_SMALL_BYTES), "payload_content_opened_prepare": False},
        "launch_allowed": True,
        "launch_owner": "root",
    }


def _normalize_base_contract(contract: dict[str, Any], manifest_contract_path: Path) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    base = _load_base()
    case_id = contract.get("physical_case_id")
    base.CASE_ID = case_id
    base.FAMILY_ID = "F6"
    base.CURRENT_SHA256 = CURRENT_SHA256
    base.SCRIPT = SCRIPT
    base.VENV = VENV
    current = _read_json(Path(contract["current336"]["path"]), "CURRENT336")
    current_row = base._current_case(current, case_id)
    summary_path = Path(contract["typed_summary"]["path"])
    summary = _read_json(summary_path, "typed summary")
    trajectory, records_base = base._validate_summary(summary, summary_path, current_row, case_id, CURRENT_SHA256)
    native_path = Path(contract["native_report"]["path"])
    native = _read_json(native_path, "native report")
    native_ids = base._validate_native_report(native, current_row, case_id)
    if not native_ids["excluded"]:
        raise V3Error(f"empty native target set: {case_id}")
    records = contract["deferred_inputs"]["typed_records"]
    if int(records["rows"]) != int(records_base["rows"]) or int(records["bytes"]) != int(records_base["bytes"]) or records["sha256"] != records_base["sha256"]:
        raise V3Error(f"typed record declaration differs from summary: {case_id}")
    base_contract = {"schema": BASE_CONTRACT_SCHEMA, "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED", "physical_case_id": case_id, "family_id": "F6", "expected_current_sha256": CURRENT_SHA256, "source_contract": str(manifest_contract_path), "deferred_inputs": {"typed_records": records, "partout_csv": contract["deferred_inputs"]["partout_csv"], "runparts_csv": contract["deferred_inputs"]["runparts_csv"]}, "claim_boundary": contract["claim_boundary"]}
    return base, base_contract, current, summary, native, native_ids


def _audit_case(contract_path: Path, output_path: Path) -> dict[str, Any]:
    contract = _read_json(contract_path, "ROOT226 V3 case contract")
    if contract.get("schema") != V3_CONTRACT_SCHEMA or contract.get("status") != "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED" or contract.get("launchable") is not True:
        raise V3Error("ROOT226 V3 case contract is not audit-ready")
    base, base_contract, current, summary, native, native_ids = _normalize_base_contract(contract, contract_path)
    original_loader = base._load_static_contract
    base._load_static_contract = lambda _path: (base_contract, current, summary, native, native_ids)
    try:
        return base.audit(contract_path, output_path)
    finally:
        base._load_static_contract = original_loader


def _fixture_audit(manifest: dict[str, Any], manifest_path: Path, output_path: Path) -> dict[str, Any]:
    """Run the same CLI path on a test-only synthetic contract.

    Production requests never set ``fixture``.  This branch exists to exercise
    the subprocess boundary for the empty-target and cross-family negatives
    without opening any production payload.
    """
    if manifest.get("fixture") is not True:
        raise V3Error("fixture audit requires an explicit fixture manifest")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise V3Error("fixture contract is missing")
    if contract.get("family_id") != "F6":
        raise V3Error("fixture cross-family contract rejected")
    base = _load_base()
    case_id = str(contract.get("physical_case_id"))
    base.CASE_ID = case_id
    base.FAMILY_ID = "F6"
    summary = _read_json(Path(contract["summary_path"]), "fixture summary")
    native = _read_json(Path(contract["native_path"]), "fixture native report")
    records_path = _path(contract["records_path"], "fixture records", deferred=True)
    partout_path = _path(contract["partout_path"], "fixture PartOut", deferred=True)
    runparts_path = _path(contract["runparts_path"], "fixture RunPARTs", deferred=True)
    if not native.get("excluded_particles"):
        raise V3Error("fixture native target set is empty")
    expected = {role: _deferred_ref({"path": str(path), "bytes": path.stat().st_size, "sha256": _digest(path, role, max_bytes=MAX_OUTPUT_BYTES) if path.suffix != ".jsonl" else hashlib.sha256(path.read_bytes()).hexdigest()}, role) for role, path in (("typed_records", records_path), ("partout_csv", partout_path), ("runparts_csv", runparts_path))}
    expected["typed_records"]["rows"] = 1
    base_contract = {"schema": BASE_CONTRACT_SCHEMA, "status": "READY_PARENT_GUARDED_AUDIT_NOT_LAUNCHED", "physical_case_id": case_id, "family_id": "F6", "deferred_inputs": expected}
    native_ids = base._native_rows(native)
    current = {"schema": BASE_CURRENT_SCHEMA, "cases": [{"physical_case_id": case_id, "family_id": "F6", "frames": 1, "particles": 1, "trajectory": {"path": "/fixture/trajectory.h5", "producer_declared_sha256": "0" * 64}}]}
    original_loader = base._load_static_contract
    base._load_static_contract = lambda _path: (base_contract, current, summary, native, {"excluded": native_ids, "ids": native_ids})
    try:
        return base.audit(manifest_path, output_path)
    finally:
        base._load_static_contract = original_loader


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest_path = _path(args.manifest, "ROOT226 V3 manifest")
    manifest = _read_json(manifest_path, "ROOT226 V3 manifest")
    if manifest.get("fixture") is True:
        if not args.allow_test_fixture:
            raise V3Error("test fixture execution is disabled")
        return _fixture_audit(manifest, manifest_path, Path(args.output).expanduser().resolve())
    if manifest.get("schema") != V3_SCHEMA or manifest.get("batch_id") != "ROOT226_V3" or manifest.get("family_id") != "F6":
        raise V3Error("manifest schema/family differs")
    entries = manifest.get("contracts")
    if not isinstance(entries, list) or {item.get("physical_case_id") for item in entries if isinstance(item, dict)} != EXPECTED_CASES:
        raise V3Error("manifest case set is not the exact three F6 contracts")
    output_path = Path(args.output).expanduser().resolve()
    if output_path.exists():
        raise V3Error(f"refusing to overwrite immutable batch output: {output_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    case_results = []
    case_dir = output_path.parent / "cases"
    for entry in entries:
        case_id = entry.get("physical_case_id")
        contract_path = _path(entry.get("path"), f"{case_id} V3 case contract")
        case_output = case_dir / f"{case_id}.json"
        try:
            result = _audit_case(contract_path, case_output)
            case_results.append({"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_output), "result": result})
        except (V3Error, ValueError, OSError) as exc:
            case_results.append({"physical_case_id": case_id, "status": "FAILED", "error_type": type(exc).__name__, "error_message": str(exc), "saved_mask_credit": False})
    failed = [item for item in case_results if item["status"] != "COMPLETED"]
    result = {"schema": V3_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES" if failed else "COMPLETED_ALL_CASES", "batch_id": "ROOT226_V3", "family_id": "F6", "case_results": case_results, "counts": {"requested": len(case_results), "completed": len(case_results) - len(failed), "failed": len(failed)}, "source_manifest": manifest.get("source_manifest"), "claim_boundary": manifest.get("claim_boundary"), "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "continuous_event_time": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "source_read_cost": {"sequential_case_execution": True, "h5_content_read": False, "native_bi4_read": False}}
    _atomic(output_path, result, limit=MAX_BATCH_OUTPUT_BYTES)
    return {"status": result["status"], "output": str(output_path), "completed": result["counts"]["completed"], "failed": result["counts"]["failed"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare", help="prepare an executable ROOT226 V3 manifest")
    prep.add_argument("--source-manifest", type=Path, default=SOURCE_MANIFEST_DEFAULT)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    prep.add_argument("--checkpoint", type=Path)
    run = sub.add_parser("audit", help="execute the guarded three-case F6 adapter")
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--allow-test-fixture", action="store_true", help=argparse.SUPPRESS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _write_manifest_and_request(args) if args.command == "prepare" else audit(args)
    except (V3Error, OSError, ValueError) as exc:
        print(f"ROOT226 V3 ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
