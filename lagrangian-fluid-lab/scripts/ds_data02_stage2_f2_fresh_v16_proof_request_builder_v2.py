#!/usr/bin/env python3
"""Derive a fresh V8 proof request from frozen V15 and scan metadata.

This forward builder closes a gap in v1: the V8 ``expected`` contract is
derived from the producer's exact V15 request *and* its small scientific-scan
sidecar.  In particular, the selected fluid count, initial MK/type bounds,
initial mass denominator, initially-absent count, later-missing mass and
saved-time axis come from the scan's type ledger and are cross-checked against
V15.  A caller cannot supply a convenient placeholder count or mass.

Only JSON metadata and the newly produced JSON result are read.  The builder
never opens H5/BI4/raw payloads, starts a converter/evaluator, or grants
qualification.  The source contract and V8 request are immutable new files;
old V8 requests and result JSON remain untouched.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import stat
import sys
from typing import Any, Mapping, Sequence


SCRIPT = Path(__file__).resolve()
V1_SCRIPT = SCRIPT.parent / "ds_data02_stage2_f2_fresh_v16_proof_request_builder_v1.py"
V1_SCHEMA = "ds02.stage2.f2-fresh-v16-proof-request-builder.v1"
V15_SCHEMA = "ds02.stage2.f2-s1-replay-request.v15"
SCAN_SCHEMA = "ds02.stage2.scientific-scan.v1"
DERIVED_SCHEMA = "ds02.stage2.f2-fresh-v16-source-contract-derived.v2"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
HEX64 = set("0123456789abcdef")
MAX_METADATA_BYTES = 32 * 1024 * 1024


class V16DerivedRequestError(RuntimeError):
    """Raised when frozen producer metadata cannot close a V8 contract."""


def _load_v1() -> Any:
    if not V1_SCRIPT.is_file():
        raise V16DerivedRequestError(f"bound v1 builder is missing: {V1_SCRIPT}")
    spec = importlib.util.spec_from_file_location("ds02_stage2_f2_v16_builder_v1_bound", V1_SCRIPT)
    if spec is None or spec.loader is None:
        raise V16DerivedRequestError("cannot import bound v1 proof builder")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V1 = _load_v1()


def canonical_sha(value: Any) -> str:
    if isinstance(value, Mapping):
        value = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False, default=str).encode("utf-8")).hexdigest()


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).expanduser().resolve().open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _path(value: Any, name: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise V16DerivedRequestError(f"{name} must be an absolute path")
    return Path(value).expanduser()


def _resolved(value: Any, name: str) -> Path:
    return _path(value, name).resolve()


def _sha(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(char not in HEX64 for char in value):
        raise V16DerivedRequestError(f"{name} must be a lowercase SHA-256")
    return value


def _finite(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise V16DerivedRequestError(f"{name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise V16DerivedRequestError(f"{name} must be finite")
    return result


def _load_small_json(path: Path | str, name: str) -> tuple[Path, dict[str, Any]]:
    target = _resolved(str(path), name)
    try:
        info = target.stat()
    except OSError as error:
        raise V16DerivedRequestError(f"{name} is unavailable: {target}: {error}") from error
    if not stat.S_ISREG(info.st_mode):
        raise V16DerivedRequestError(f"{name} is not a regular file: {target}")
    if int(info.st_size) > MAX_METADATA_BYTES:
        raise V16DerivedRequestError(f"{name} exceeds metadata-only byte bound")
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise V16DerivedRequestError(f"cannot read {name}: {error}") from error
    if not isinstance(value, dict):
        raise V16DerivedRequestError(f"{name} must contain a JSON object")
    return target, value


def _under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _write_new(path: Path | str, value: Mapping[str, Any]) -> Path:
    target = _resolved(str(path), "output")
    if target.exists():
        raise V16DerivedRequestError(f"refusing existing output: {target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, ensure_ascii=False,
                  allow_nan=False, default=str)
        stream.write("\n")
    return target


def _source_files(v15: Mapping[str, Any], scan_path: Path, scan_sha: str) -> dict[str, str]:
    values = v15.get("source_files")
    if not isinstance(values, list) or not values:
        raise V16DerivedRequestError("V15 source_files are missing")
    result: dict[str, str] = {}
    scan_declared: str | None = None
    for index, item in enumerate(values):
        if not isinstance(item, Mapping) or not isinstance(item.get("role"), str):
            raise V16DerivedRequestError(f"V15 source_files[{index}] is malformed")
        role = str(item["role"])
        if role in result:
            raise V16DerivedRequestError(f"V15 source role is duplicated: {role}")
        digest = _sha(item.get("sha256"), f"V15 source_files.{role}.sha256")
        result[role] = digest
        if role == "scientific_scan_sidecar":
            scan_declared = digest
            declared_path = _path(item.get("path"), "V15 scientific_scan_sidecar.path").resolve()
            if declared_path != scan_path:
                raise V16DerivedRequestError(
                    "scan sidecar path differs from the exact V15 source binding")
    if scan_declared is None:
        raise V16DerivedRequestError("V15 scientific_scan_sidecar source binding is missing")
    if scan_declared != scan_sha:
        raise V16DerivedRequestError("scan sidecar content SHA differs from V15 source binding")
    for role in ("current_catalog", "generated_xml", "motion_dat", "initial_csv"):
        if role not in result:
            raise V16DerivedRequestError(f"V15 source binding lacks {role}")
    return result


def _scan_fluid(scan: Mapping[str, Any], v15: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    if scan.get("schema") != SCAN_SCHEMA or scan.get("scan_status") != "SCANNED":
        raise V16DerivedRequestError("scan sidecar is not a completed scientific scan")
    if scan.get("full_saved_timeline_scanned") is not True:
        raise V16DerivedRequestError("scan sidecar does not cover the complete saved timeline")
    ledgers = scan.get("type_ledgers")
    fluid = ledgers.get("fluid") if isinstance(ledgers, Mapping) else None
    if not isinstance(fluid, Mapping):
        raise V16DerivedRequestError("scan sidecar fluid type ledger is missing")
    if int(fluid.get("type_code", -1)) != 3:
        raise V16DerivedRequestError("scan fluid type ledger is not Type=3")
    cohort = v15.get("cohort")
    if not isinstance(cohort, Mapping):
        raise V16DerivedRequestError("V15 cohort is missing")
    selected = int(fluid.get("initial_active_count", -1))
    typed_initial = int(fluid.get("typed_initial_count", -1))
    declared_selected = int(cohort.get("expected_initial_fluid_count", -1))
    if selected <= 0 or typed_initial != selected or declared_selected != selected:
        raise V16DerivedRequestError(
            f"raw producer initial fluid count mismatch: scan={selected}/{typed_initial}, V15={declared_selected}")
    mk_codes = cohort.get("initial_mk_codes")
    csv_semantics = cohort.get("source_csv_semantics")
    if not isinstance(mk_codes, list) or not mk_codes or any(isinstance(x, bool) or not isinstance(x, int) for x in mk_codes):
        raise V16DerivedRequestError("V15 initial MK code bounds are missing")
    if not isinstance(csv_semantics, Mapping):
        raise V16DerivedRequestError("V15 source CSV MK semantics are missing")
    mk_counts = csv_semantics.get("fluid_mk_counts")
    if not isinstance(mk_counts, Mapping) or set(str(x) for x in mk_codes) != set(str(k) for k in mk_counts):
        raise V16DerivedRequestError("V15 initial MK count map does not equal initial MK bounds")
    if sum(int(v) for v in mk_counts.values()) != selected:
        raise V16DerivedRequestError("initial MK counts do not sum to the scan fluid cohort")
    initial_missing_count = int(fluid.get("initially_absent_count", -1))
    missing_mass = fluid.get("missing_initial_mass_kg")
    if not isinstance(missing_mass, list) or len(missing_mass) != int(scan.get("frames", -1)):
        raise V16DerivedRequestError("scan missing-mass ledger does not span all frames")
    initial_missing_mass = _finite(missing_mass[0], "scan missing_initial_mass_kg[0]")
    later_missing_mass = _finite(missing_mass[-1], "scan missing_initial_mass_kg[-1]")
    initial_mass = _finite(fluid.get("typed_initial_mass_kg"), "scan typed_initial_mass_kg")
    v15_mass = v15.get("initial_mass_denominator")
    if not isinstance(v15_mass, Mapping):
        raise V16DerivedRequestError("V15 initial_mass_denominator is missing")
    if not math.isclose(initial_mass, _finite(v15_mass.get("denominator_kg"), "V15 denominator_kg"), rel_tol=0.0, abs_tol=1e-12):
        raise V16DerivedRequestError("scan initial mass differs from V15 frozen denominator")
    if initial_missing_count != int(v15_mass.get("initially_absent_count", -1)):
        raise V16DerivedRequestError("scan initially_absent_count differs from V15")
    if not math.isclose(initial_missing_mass, _finite(v15_mass.get("initial_missing_mass_kg"), "V15 initial missing mass"), rel_tol=0.0, abs_tol=1e-12):
        raise V16DerivedRequestError("scan initial missing mass differs from V15")
    cumulative_unique = int(fluid.get("cumulative_unique_missing", -1))
    if cumulative_unique != int(v15_mass.get("later_missing_unique_count", -1)):
        raise V16DerivedRequestError("scan later missing unique count differs from V15")
    if not math.isclose(later_missing_mass, _finite(v15_mass.get("later_missing_mass_kg"), "V15 later missing mass"), rel_tol=0.0, abs_tol=1e-12):
        raise V16DerivedRequestError("scan later missing mass differs from V15")
    nonfinite = fluid.get("active_nonfinite")
    if not isinstance(nonfinite, Mapping) or any(int(value) != 0 for value in nonfinite.values()):
        raise V16DerivedRequestError("scan fluid ledger contains active nonfinite values")
    return dict(fluid), {"mk_codes": list(mk_codes), "mk_counts": {str(k): int(v) for k, v in mk_counts.items()}}


def _time_contract(v15: Mapping[str, Any], scan: Mapping[str, Any]) -> dict[str, Any]:
    times = scan.get("time_s")
    expected = v15.get("window", {}).get("expected_times_s") if isinstance(v15.get("window"), Mapping) else None
    if not isinstance(times, list) or not times or not isinstance(expected, list) or len(times) != len(expected):
        raise V16DerivedRequestError("V15/scan time axes are missing or have different lengths")
    for index, (actual, declared) in enumerate(zip(times, expected)):
        if _finite(actual, f"scan time_s[{index}]") != _finite(declared, f"V15 expected_times_s[{index}]"):
            raise V16DerivedRequestError(f"scan/V15 saved time differs at frame {index}")
    if int(scan.get("frames", -1)) != len(times) or int(scan.get("frames", -1)) != int(v15.get("window", {}).get("frame_stop", -1)) + 1:
        raise V16DerivedRequestError("scan/V15 frame count is not the frozen full timeline")
    return {
        "frame_count": len(times), "first_s": float(times[0]), "last_s": float(times[-1]),
        "tolerance_s": 0.0, "observer_profile_sha256": v15.get("observer_profile", {}).get("sha256"),
        "tolerance_source": "exact saved times from frozen scientific-scan sidecar; no builder widening",
    }


def derive_source_contract(*, v15_request: Path | str, scan_sidecar: Path | str,
                           source_contract_output: Path | str, original_roots: Sequence[Path | str]) -> dict[str, Any]:
    v15_path, v15 = _load_small_json(v15_request, "V15 request")
    scan_path, scan = _load_small_json(scan_sidecar, "scientific scan sidecar")
    if v15.get("schema") != V15_SCHEMA or v15.get("role") != "DEVELOPMENT":
        raise V16DerivedRequestError("V15 request schema/role is not the frozen development request")
    if v15.get("qualification") != UNKNOWN or v15.get("model_invoked") is not False:
        raise V16DerivedRequestError("V15 request is not conservative/model-free")
    scan_sha = sha256_file(scan_path)
    source_files = _source_files(v15, scan_path, scan_sha)
    fluid, mk = _scan_fluid(scan, v15)
    times = _time_contract(v15, scan)
    identity = v15.get("case_identity")
    cohort = v15.get("cohort")
    profile = v15.get("observer_profile")
    labels = v15.get("label_semantics")
    if not isinstance(identity, Mapping) or not isinstance(cohort, Mapping) or not isinstance(profile, Mapping) or not isinstance(labels, Mapping):
        raise V16DerivedRequestError("V15 identity/cohort/profile/label semantics are incomplete")
    identity_sha = cohort.get("source_identity_set_sha256")
    _sha(identity_sha, "V15 cohort.source_identity_set_sha256")
    expected = {
        "source_binding": {
            "binding_status": "EXACT_CURRENT_SOURCE_BOUND",
            "current_catalog_sha256": source_files["current_catalog"],
            "trajectory_h5_producer_sha256": _sha(v15.get("trajectory_h5", {}).get("producer_declared_sha256"), "V15 trajectory producer SHA"),
            "source_files": source_files,
        },
        "case_identity": dict(identity),
        "cohort": {
            "selected_count": int(fluid["initial_active_count"]),
            "identity_key": cohort.get("identity_key"),
            "identity_sha256": identity_sha,
            "initial_type_code": int(fluid["type_code"]),
            "initial_mk_codes": mk["mk_codes"],
            "initial_mk_counts": mk["mk_counts"],
            "raw_producer_initial_mk_bounds": {
                "type_code": int(fluid["type_code"]),
                "mk_codes": mk["mk_codes"],
                "mk_counts": mk["mk_counts"],
                "selection": cohort.get("source_definition"),
            },
        },
        "initial_mass_denominator": {
            "denominator_kg": float(fluid["typed_initial_mass_kg"]),
            "initial_missing_mass_kg": float(fluid["missing_initial_mass_kg"][0]),
            "later_missing_unique_count": int(fluid["cumulative_unique_missing"]),
            "later_missing_mass_kg": float(fluid["missing_initial_mass_kg"][-1]),
            "initially_absent_count": int(fluid["initially_absent_count"]),
            "derivation": "scientific-scan type_ledgers.fluid; frozen initial mass is not augmented by later missing IDs",
        },
        "time": times,
        "observer_fields": list(profile.get("observable_names", [])),
        "events": {
            "status_vocabulary": sorted(V1.V8.FIRST_PASSAGE_STATUSES),
            "require_unknown_recross": True,
            "require_total_net_interval": True,
            "require_receiver_labels": True,
            "require_residence_semantics": True,
            "semantics_source": dict(labels),
        },
    }
    contract = {
        "schema": V1.SOURCE_SCHEMA,
        "derived_schema": DERIVED_SCHEMA,
        "role": "DEVELOPMENT",
        "quality": dict(UNKNOWN),
        "original_roots": [str(_resolved(str(root), "original_root")) for root in original_roots],
        "expected": expected,
        "producer_metadata": {
            "v15_request": {"path": str(v15_path), "sha256": sha256_file(v15_path), "schema": V15_SCHEMA},
            "scientific_scan_sidecar": {"path": str(scan_path), "sha256": scan_sha, "schema": SCAN_SCHEMA},
            "mass_derivation": {"type_ledger": "fluid", "type_code": int(fluid["type_code"]),
                                 "selected_count": int(fluid["initial_active_count"]),
                                 "initial_mk_codes": mk["mk_codes"], "initial_mk_counts": mk["mk_counts"],
                                 "typed_initial_mass_kg": float(fluid["typed_initial_mass_kg"]),
                                 "initially_absent_count": int(fluid["initially_absent_count"]),
                                 "later_missing_unique_count": int(fluid["cumulative_unique_missing"]),
                                 "payload_read": False},
        },
    }
    contract["sha256"] = canonical_sha(contract)
    path = _write_new(source_contract_output, contract)
    return {"status": "READY_FOR_FRESH_V16_METADATA_DERIVATION", "source_contract": str(path),
            "source_contract_sha256": contract["sha256"], "v15_request_sha256": sha256_file(v15_path),
            "scan_sidecar_sha256": scan_sha, "selected_count": int(fluid["initial_active_count"]),
            "initial_mk_codes": mk["mk_codes"], "initial_mk_counts": mk["mk_counts"],
            "initial_mass_denominator_kg": float(fluid["typed_initial_mass_kg"]),
            "initially_absent_count": int(fluid["initially_absent_count"]),
            "later_missing_unique_count": int(fluid["cumulative_unique_missing"]),
            "payload_read": False, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def derive_and_build(*, v15_request: Path | str, scan_sidecar: Path | str,
                     source_contract_output: Path | str, result: Path | str,
                     target_root: Path | str, output_root: Path | str, output: Path | str,
                     original_roots: Sequence[Path | str], parent_guard_record: Path | str | None = None,
                     trace_audit_request: Path | str | None = None,
                     python_executable: Path | str | None = None,
                     max_wall_seconds: float = 900.0, max_result_bytes: int = 100_000_000) -> dict[str, Any]:
    derived = derive_source_contract(v15_request=v15_request, scan_sidecar=scan_sidecar,
                                     source_contract_output=source_contract_output,
                                     original_roots=original_roots)
    built = V1.build_request(source_contract=derived["source_contract"], result=result,
                             target_root=target_root, output_root=output_root, output=output,
                             parent_guard_record=parent_guard_record,
                             trace_audit_request=trace_audit_request,
                             python_executable=python_executable,
                             max_wall_seconds=max_wall_seconds,
                             max_result_bytes=max_result_bytes)
    return {"schema": DERIVED_SCHEMA, "status": "READY_FOR_PARENT_FRESH_V16_PROOF",
            "derived": derived, "request": built, "model_invoked": False,
            "cfd_invoked": False, "payload_read": False, "hdf5_or_bi4_content_read": False,
            "qualification": dict(UNKNOWN)}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?")
    parser.add_argument("--v15-request", type=Path, required=True)
    parser.add_argument("--scan-sidecar", type=Path, required=True)
    parser.add_argument("--source-contract-output", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--target-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--original-root", type=Path, action="append", required=True)
    parser.add_argument("--parent-guard-record", type=Path)
    parser.add_argument("--trace-audit-request", type=Path)
    parser.add_argument("--python-executable", type=Path)
    parser.add_argument("--max-wall-seconds", type=float, default=900.0)
    parser.add_argument("--max-result-bytes", type=int, default=100_000_000)
    args = parser.parse_args(argv)
    if args.command not in {None, "derive-and-build"}:
        parser.error("the only command is derive-and-build")
    try:
        value = derive_and_build(v15_request=args.v15_request, scan_sidecar=args.scan_sidecar,
                                 source_contract_output=args.source_contract_output, result=args.result,
                                 target_root=args.target_root, output_root=args.output_root, output=args.output,
                                 original_roots=args.original_root, parent_guard_record=args.parent_guard_record,
                                 trace_audit_request=args.trace_audit_request,
                                 python_executable=args.python_executable,
                                 max_wall_seconds=args.max_wall_seconds,
                                 max_result_bytes=args.max_result_bytes)
    except (V16DerivedRequestError, V1.V16RequestBuilderError, OSError, TypeError, ValueError, json.JSONDecodeError) as error:
        print(f"fresh V16 proof request builder v2: {error}", file=sys.stderr)
        return 2
    print(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
