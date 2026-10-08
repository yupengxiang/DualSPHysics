#!/usr/bin/env python3
"""Prepare/consume the all-118 impact ledger under the shared v8 guard.

The v1 impact consumer is preserved.  This forward version consumes the
completed all-118 mechanism-probe report without rehashing its 1,291 declared
small source files during preparation, binds the v8/v6/v2 runtime chain, and
upgrades the one historical F2-S1 partial record only from the independent
completed native-source-closure sidecar.  It never opens HDF5, raw BI4, or a
trajectory and never starts a decoder or solver.

The ledger still reports source-visible mass only.  Physical fate, legal flux,
converter implementation, QN/QE, and dynamical impact remain UNKNOWN.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

import ds_data02_stage2_omission_impact_ledger_v1 as legacy


SCRIPT = Path(__file__).resolve()
WORKTREE_ROOT = SCRIPT.parents[2]
LAB_ROOT = WORKTREE_ROOT / "lagrangian-fluid-lab"
PRIMARY_LAB_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics/lagrangian-fluid-lab")
VENV = Path("/home/jade/Projects/DualSPHysics/lagrangian-fluid-lab/.venv/bin/python")
DATA_ROOT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
SOURCE_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_BOUNDS_118_V1/"
    "omission-mechanism-bounds-v2-primary-001-v5/omission-mechanism-bounds-v2.json"
)
PROBE_REPORT_DEFAULT = DATA_ROOT / (
    "families/infra/STAGE2_OMISSION_MECHANISM_PROBE_ALL118_V2/"
    "omission-mechanism-probe-v2-primary-001-v8-root/omission-mechanism-probe-v2.json"
)
CLOSURE_DEFAULT = LAB_ROOT / (
    "campaigns/ds-data-02/stage2/evidence/f2-s1-native-source-closure-v1/"
    "f2-s1-native-source-closure.json"
)
OUTPUT_SCHEMA = "ds02.stage2.omission-impact-ledger.v2"
MANIFEST_SCHEMA = "ds02.stage2.omission-impact-ledger-manifest.v2"
PROBE_SCHEMA = "ds02.stage2.omission-mechanism-probe.v2"
PROBE_STATUS = "MECHANISM_PROBE_SOURCE_CLOSED_NO_H5"
SOURCE_SCHEMA = "ds02.stage2.omission-mechanism-bounds.v1"
SOURCE_STATUS = "MECHANISM_BOUNDS_AUDITED_TYPED_NATIVE_SOURCE_CLOSED"
FAMILY_COUNTS = {"F2": 48, "F4": 22, "F6": 48}
F2_S1_KEY = "F2/scan-F2-S1-001"
H5_SUFFIXES = {".h5", ".hdf5", ".obi4", ".bi4"}


class LedgerV8Error(RuntimeError):
    """Raised when a v8 ledger binding or claim boundary is invalid."""


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def require(path: Path, label: str, *, allow_binary: bool = True) -> Path:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise LedgerV8Error(f"{label} is missing: {path}")
    if path.suffix.lower() in H5_SUFFIXES or (path.name.startswith("Part_") and path.suffix.lower() == ".bi4"):
        raise LedgerV8Error(f"forbidden trajectory/raw input: {path}")
    return path


def read_json(path: Path, label: str) -> dict[str, Any]:
    path = require(path, label)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerV8Error(f"{label} is invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise LedgerV8Error(f"{label} is not an object")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path = path.expanduser().resolve()
    if path.exists():
        raise LedgerV8Error(f"refusing to overwrite existing output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as stream:
            fd = -1
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if fd >= 0:
            os.close(fd)
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def declared(path: Path, expected: str, expected_bytes: int, label: str) -> dict[str, Any]:
    """Record a previously attested digest without reading the source bytes."""
    path = require(path, label)
    actual_bytes = path.stat().st_size
    if actual_bytes != int(expected_bytes):
        raise LedgerV8Error(f"{label} byte count differs: {path}")
    return {"path": str(path), "bytes": actual_bytes, "sha256": expected, "digest_source": "completed_probe_or_guard_receipt"}


def input_map(source_path: Path, source_sha: str, probe_path: Path, probe_sha: str, closure_path: Path, closure_sha: str) -> dict[str, dict[str, Any]]:
    """Collect declared source hashes from the completed report, without rehashing them."""
    result: dict[str, dict[str, Any]] = {}

    def add(path: Path, sha: str, bytes_value: int, label: str) -> None:
        path = path.expanduser().resolve()
        item = declared(path, sha, int(bytes_value), label)
        previous = result.get(str(path))
        if previous is not None and (previous["sha256"], previous["bytes"]) != (item["sha256"], item["bytes"]):
            raise LedgerV8Error(f"conflicting declared input: {path}")
        result[str(path)] = item

    add(source_path, source_sha, source_path.stat().st_size, "source report")
    add(probe_path, probe_sha, probe_path.stat().st_size, "probe report")
    add(closure_path, closure_sha, closure_path.stat().st_size, "F2-S1 closure")
    add(SCRIPT, digest(SCRIPT), SCRIPT.stat().st_size, "impact ledger v8 script")
    legacy_path = Path(legacy.__file__).resolve()
    add(legacy_path, digest(legacy_path), legacy_path.stat().st_size, "preserved impact ledger v1 script")

    runtime_names = (
        "ds_data02_runtime_v8.py",
        "ds_data02_runtime_v6.py",
        "ds_data02_runtime_v2.py",
        "ds_data02_stage2_dispatch_v8.py",
        "ds_data02_strict_dispatch_v8.py",
    )
    for name in runtime_names:
        path = PRIMARY_LAB_ROOT / "scripts" / name
        add(path, digest(path), path.stat().st_size, f"runtime binding {name}")

    probe = read_json(probe_path, "probe report")
    seen_cases: set[str] = set()
    for case in probe.get("cases", []):
        for name, item in (case.get("source_files") or {}).items():
            if not isinstance(item, dict):
                raise LedgerV8Error(f"invalid declared source file: {case.get('case_key')}/{name}")
            path = Path(str(item.get("path", "")))
            # v2 source_files are deliberately small sidecars/CSV/XML/tool
            # metadata.  A raw PartOut/H5 declaration would be rejected here.
            if path.suffix.lower() in H5_SUFFIXES or path.name.startswith("Part_") and path.suffix.lower() == ".bi4":
                raise LedgerV8Error(f"probe unexpectedly declares forbidden input: {path}")
            add(path, str(item["sha256"]), int(item["bytes"]), f"probe {case.get('case_key')}/{name}")
        seen_cases.add(str(case.get("case_key")))
    if len(seen_cases) != 118:
        raise LedgerV8Error(f"probe case count differs: {len(seen_cases)}")

    # The closure sidecar's validator uses these small outputs and reports;
    # keep them guard-bound.  Its raw BI4 and official decoder/config digests
    # remain attested by the completed config-closure receipt and are not added
    # as new impact-ledger inputs.
    closure = read_json(closure_path, "F2-S1 closure")
    for name in ("old_partvtkout_csv", "fresh_partvtkout_csv", "config_closure_manifest", "config_closure_report", "config_closure_receipt"):
        item = (closure.get("source_bindings") or {}).get(name)
        if not isinstance(item, dict):
            raise LedgerV8Error(f"closure lacks small binding: {name}")
        add(Path(item["path"]), str(item["sha256"]), int(item["bytes"]), f"closure {name}")
    return result


def source_and_probe(source_path: Path, probe_path: Path) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    source_path = require(source_path, "source report")
    probe_path = require(probe_path, "probe report")
    source_sha = digest(source_path)
    probe_sha = digest(probe_path)
    source = read_json(source_path, "source report")
    probe = read_json(probe_path, "probe report")
    if source.get("schema") != SOURCE_SCHEMA or source.get("status") != SOURCE_STATUS:
        raise LedgerV8Error("source report schema/status differs")
    if probe.get("schema") != PROBE_SCHEMA or probe.get("status") != PROBE_STATUS:
        raise LedgerV8Error("probe report schema/status differs")
    policy = probe.get("read_policy", {})
    forbidden = ("h5_opened", "trajectory_content_opened", "raw_partout_opened", "decoder_started", "solver_started", "cfd_or_model_run")
    if any(policy.get(name) is not False for name in forbidden):
        raise LedgerV8Error("probe read policy is not no-H5/no-decoder")
    if probe.get("source_report", {}).get("sha256") != source_sha:
        raise LedgerV8Error("probe/source report binding differs")
    if len(source.get("cases", [])) != 118 or len(probe.get("cases", [])) != 118:
        raise LedgerV8Error("source/probe case count differs")
    return source, probe, source_sha, probe_sha


def validate_closure(path: Path, expected_sha: str) -> dict[str, Any]:
    binding = declared(path, expected_sha, path.stat().st_size, "F2-S1 closure")
    closure = read_json(path, "F2-S1 closure")
    if closure.get("schema") != "ds02.stage2.f2-s1-native-source-closure.v1" or closure.get("status") != "EXACT_NATIVE_SOURCE_CLOSED_WITH_PHYSICAL_FATE_UNKNOWN":
        raise LedgerV8Error("F2-S1 closure sidecar is not exact native closure")
    result = closure.get("native_result", {})
    if result.get("joined_count") != 3 or result.get("idp") != [403829, 397194, 404024]:
        raise LedgerV8Error("F2-S1 closure IDs/count differ")
    if result.get("motive_counts") != {"position": 3, "density": 0, "movement": 0}:
        raise LedgerV8Error("F2-S1 closure motive counts differ")
    return {"binding": binding, "payload": closure}


def trusted_binding(value: Path | str, label: str, expected: str | None = None) -> dict[str, Any]:
    """Use producer-declared hashes; v8 guard owns content validation at launch."""
    path = require(Path(value), label)
    return {"path": str(path), "sha256": expected or "PRODUCER_DECLARED", "bytes": path.stat().st_size}


def upgraded_f2_s1_record(record: dict[str, Any], closure: dict[str, Any]) -> dict[str, Any]:
    record = json.loads(json.dumps(record))
    record["evidence_bindings"]["f2_s1_native_closure"] = closure["binding"]
    record["source_closure"] = {
        "status": "FULL_NATIVE_SOURCE_CLOSED",
        "missing_inputs": [],
        "upgrade_basis": "completed guarded 118-case config-closure report, case 030, exact semantic match to preserved PartOut.csv",
        "physical_fate_and_converter_source": "UNKNOWN",
    }
    record["conversion_omission"] = {
        "status": "NATIVE_PARENT_AND_DECODER_CLOSED_CONVERTER_IMPLEMENTATION_UNKNOWN",
        "decoder_status": "EXACT_SEMANTIC_MATCH",
        "decoder_rows": 3,
        "converter_source_closure": "UNKNOWN_NOT_BOUND_BY_CONVERTER_IMPLEMENTATION",
        "physical_interpretation": "closure proves source/decoder identity and native motive only; it does not prove physical spill or dynamics",
    }
    record["next_validation_control"]["status"] = "NATIVE_CLOSURE_COMPLETE_NO_REDECODE_REQUIRED"
    record["next_validation_control"]["repair_or_control"] = "paired physical/domain control remains required for fate/dynamics; no new native decoder is required"
    return record


def build_ledger(manifest_path: Path, output_path: Path) -> dict[str, Any]:
    manifest = read_json(manifest_path, "impact v8 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "PREPARED_ALL118_IMPACT_LEDGER_V8_NO_H5":
        raise LedgerV8Error("impact v8 manifest schema/status differs")
    source_path = Path(manifest["source_report"]["path"])
    probe_path = Path(manifest["probe_report"]["path"])
    closure_path = Path(manifest["f2_s1_closure"]["path"])
    source, probe, source_sha, probe_sha = source_and_probe(source_path, probe_path)
    if source_sha != manifest["source_report"]["sha256"] or probe_sha != manifest["probe_report"]["sha256"]:
        raise LedgerV8Error("manifest source/probe digest differs")
    closure = validate_closure(closure_path, manifest["f2_s1_closure"]["sha256"])
    source_by_key = legacy.source_cases(source)
    probe_by_key = legacy.probe_cases(probe, source_sha)
    if set(source_by_key) != set(probe_by_key) or set(source_by_key) != set(manifest["selected_case_keys"]):
        raise LedgerV8Error("source/probe/manifest case membership differs")

    old_binding = legacy.binding
    legacy.binding = trusted_binding
    try:
        records = []
        for key in sorted(source_by_key):
            record = legacy.validate_case(source_by_key[key], probe_by_key[key], source_sha)
            if key == F2_S1_KEY:
                record = upgraded_f2_s1_record(record, closure)
            records.append(record)
    finally:
        legacy.binding = old_binding

    family_counts = Counter(row["family_id"] for row in records)
    motive_counts = Counter(row["native_numerical_cause"]["motive"] for row in records)
    causes = Counter()
    for row in records:
        causes.update(row["native_numerical_cause"]["exit_cause_counts"])
    payload = {
        "schema": OUTPUT_SCHEMA,
        "status": "IMPACT_LEDGER_SOURCE_CLOSED_WITH_FATE_AND_DYNAMICS_UNKNOWN",
        "source_report": {"path": str(source_path.resolve()), "sha256": source_sha, "bytes": source_path.stat().st_size},
        "probe_report": {"path": str(probe_path.resolve()), "sha256": probe_sha, "bytes": probe_path.stat().st_size},
        "f2_s1_closure": closure["binding"],
        "coverage": {
            "case_count": len(records),
            "family_counts": dict(sorted(family_counts.items())),
            "native_motive_counts": dict(sorted(motive_counts.items())),
            "native_cause_counts": dict(sorted(causes.items())),
            "partial_source_case_count": sum(row["source_closure"]["status"].startswith("PARTIAL") for row in records),
            "full_source_case_count": sum(row["source_closure"]["status"] == "FULL_NATIVE_SOURCE_CLOSED" or row["source_closure"]["status"] == "FULL_PROBE_SOURCE_CLOSED" for row in records),
            "f2_s1_partial_repair_upgraded": True,
        },
        "claim_boundary": {
            "native_motive": "credited only where v2 source-bound native sidecars agree with CURRENT identity",
            "conversion_omission": "metadata/source parent and decoder identity are closed for F2-S1; converter implementation remains UNKNOWN",
            "mass": "source-visible missing lower bound only; not physical outflow or bounded dynamical error",
            "censoring": "saved-record brackets, not exact physical event times",
            "physical_fate": "UNKNOWN",
            "legal_flux": "UNKNOWN_NOT_PROVEN",
            "dynamical_impact": "UNKNOWN",
            "QN": "NOT_ASSESSED",
            "QE": "NOT_ASSESSED",
        },
        "read_policy": {
            "h5_opened": False,
            "trajectory_content_opened": False,
            "raw_partout_opened": False,
            "decoder_started": False,
            "solver_started": False,
            "cfd_or_model_run": False,
        },
        "cases": records,
    }
    atomic_json(output_path, payload)
    return {"status": payload["status"], "output": str(output_path.resolve()), **payload["coverage"]}


def prepare(output_dir: Path, *, source_path: Path = SOURCE_REPORT_DEFAULT, probe_path: Path = PROBE_REPORT_DEFAULT, closure_path: Path = CLOSURE_DEFAULT, variant: str = "v8") -> dict[str, Any]:
    source_path = require(source_path, "source report")
    probe_path = require(probe_path, "probe report")
    closure_path = require(closure_path, "F2-S1 closure")
    source, probe, source_sha, probe_sha = source_and_probe(source_path, probe_path)
    source_by_key = legacy.source_cases(source)
    probe_by_key = legacy.probe_cases(probe, source_sha)
    if set(source_by_key) != set(probe_by_key) or len(source_by_key) != 118:
        raise LedgerV8Error("source/probe membership is not exact all-118")
    closure_sha = digest(closure_path)
    validate_closure(closure_path, closure_sha)
    inputs = input_map(source_path, source_sha, probe_path, probe_sha, closure_path, closure_sha)
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    name = f"omission-impact-ledger-{variant}"
    manifest_path = output_dir / f"{name}-manifest.json"
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "PREPARED_ALL118_IMPACT_LEDGER_V8_NO_H5",
        "source_report": {"path": str(source_path.resolve()), "sha256": source_sha, "bytes": source_path.stat().st_size},
        "probe_report": {"path": str(probe_path.resolve()), "sha256": probe_sha, "bytes": probe_path.stat().st_size},
        "f2_s1_closure": {"path": str(closure_path.resolve()), "sha256": closure_sha, "bytes": closure_path.stat().st_size},
        "selected_case_counts": dict(sorted(FAMILY_COUNTS.items())),
        "selected_case_keys": sorted(source_by_key),
        "input_files": sorted(inputs),
        "input_sha256": {path: item["sha256"] for path, item in sorted(inputs.items())},
        "input_bytes": {path: item["bytes"] for path, item in sorted(inputs.items())},
        "read_policy": {"h5_opened": False, "trajectory_content_opened": False, "raw_partout_opened": False, "decoder_started": False, "solver_started": False, "cfd_or_model_run": False},
        "claim_boundary": "native cause and source-visible mass only; F2-S1 native parent/decoder closure is upgraded from completed case-030 sidecar; converter implementation, fate, legal flux and dynamics UNKNOWN",
        "source_binding_policy": "declared completed-probe/guard digests are carried forward; v8 runtime performs pre/post digest validation only after reservation",
    }
    atomic_json(manifest_path, manifest)
    inputs[str(manifest_path)] = {"path": str(manifest_path), "bytes": manifest_path.stat().st_size, "sha256": digest(manifest_path)}

    runtime_v8 = PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v8.py"
    dispatch_v8 = PRIMARY_LAB_ROOT / "scripts/ds_data02_stage2_dispatch_v8.py"
    strict_v8 = PRIMARY_LAB_ROOT / "scripts/ds_data02_strict_dispatch_v8.py"
    runtime_v6 = PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v6.py"
    runtime_v2 = PRIMARY_LAB_ROOT / "scripts/ds_data02_runtime_v2.py"
    request_path = output_dir / f"{name}-request.json"
    request_inputs = {path: item["sha256"] for path, item in sorted(inputs.items())}
    total_bytes = sum(int(item["bytes"]) for item in inputs.values())
    request = {
        "schema": "ds02.request.v1",
        "family_id": "infra",
        "case_id": "STAGE2_OMISSION_IMPACT_LEDGER_ALL118_V8",
        "physical_case_id": "F2_F4_F6_ALL118_IMPACT_LEDGER_V8",
        "attempt_id": f"{name}-primary-001",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "estimated_storage_bytes": 64 * 1024 * 1024,
        "cwd": str(SCRIPT.parent),
        "worktree_root": str(WORKTREE_ROOT),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/omission-impact-ledger-v8.json"],
        "input_files": sorted(request_inputs),
        "input_sha256": dict(sorted(request_inputs.items())),
        "shared_runtime_version": "v8",
        "runtime_binding": {
            "runtime_v8": {"path": str(runtime_v8), "sha256": digest(runtime_v8)},
            "runtime_v6": {"path": str(runtime_v6), "sha256": digest(runtime_v6)},
            "runtime_v2": {"path": str(runtime_v2), "sha256": digest(runtime_v2)},
        },
        "dispatch_binding": {"path": str(dispatch_v8), "sha256": digest(dispatch_v8)},
        "strict_dispatch_binding": {"path": str(strict_v8), "sha256": digest(strict_v8)},
        "source_read_cost": {
            "h5_bytes_read": 0,
            "trajectory_bytes_read": 0,
            "raw_partout_bytes_read": 0,
            "json_csv_xml_binary_bytes_read": total_bytes,
            "runtime_pre_post_hash_bytes": 2 * total_bytes,
            "estimated_output_bytes": 64 * 1024 * 1024,
        },
        "source_scope": {"selected_cases": dict(sorted(FAMILY_COUNTS.items())), "native_cause_and_mass_ledger": True, "f2_s1_native_closure_upgrade": True, "h5_content_read": False, "trajectory_content_read": False, "raw_partout_content_read": False, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN_NOT_PROVEN", "dynamical_impact": "UNKNOWN"},
        "canonical_ready": True,
        "launch": True,
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
        "primary_launch_owner": "root",
        "shared_lease_required": True,
        "foreign_process_protection_required": True,
        "physical_fate": "UNKNOWN",
        "legal_outflow_or_spill": "UNKNOWN_NOT_PROVEN",
        "dynamical_impact": "UNKNOWN",
        "QN": "NOT_ASSESSED",
        "QE": "NOT_ASSESSED",
        "launch_commit": subprocess.run(["git", "rev-parse", "HEAD"], cwd=WORKTREE_ROOT, check=True, capture_output=True, text=True).stdout.strip(),
        "request_note": "Forward all-118 impact consumer under v8. Uses completed v2 native mechanism report and exact F2-S1 native source closure case-030 sidecar; no H5, trajectory, raw PartOut, decoder, solver, CFD or model. Runtime v8/v6/v2 plus strict/dispatch v8 are digest-bound. Fate, legal flux, converter implementation, dynamics, QN and QE remain UNKNOWN.",
    }
    atomic_json(request_path, request)
    return {"status": "prepared", "manifest": str(manifest_path), "manifest_sha256": digest(manifest_path), "request": str(request_path), "request_sha256": digest(request_path), "selected_case_count": 118, "source_input_count": len(inputs), "source_input_bytes": total_bytes, "h5_opened": False, "launch_allowed": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-report", type=Path, default=SOURCE_REPORT_DEFAULT)
    prep.add_argument("--probe-report", type=Path, default=PROBE_REPORT_DEFAULT)
    prep.add_argument("--closure", type=Path, default=CLOSURE_DEFAULT)
    prep.add_argument("--output-dir", type=Path, required=True)
    prep.add_argument("--variant", default="v8")
    audit = sub.add_parser("audit")
    audit.add_argument("--manifest", type=Path, required=True)
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.action == "prepare":
            value = prepare(args.output_dir, source_path=args.source_report, probe_path=args.probe_report, closure_path=args.closure, variant=args.variant)
        else:
            value = build_ledger(args.manifest, args.output)
    except (LedgerV8Error, legacy.LedgerError) as exc:
        raise SystemExit(f"LedgerV8Error: {exc}")
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
