#!/usr/bin/env python3
"""Run the source-closed CPU metadata guard for the v16 domain cards.

The committed v16 card/report files are development evidence.  This forward
entrypoint makes their parent guard executable: it verifies the complete v15
small-source input closure by exact path, stat, and content SHA, checks the
actual shared v4 guard files, and regenerates the seven cards in a new output
directory.  The closure intentionally excludes HDF5, BI4, XMF, initial CSV,
visual files, raw PartOut/RunPARTs, and mutable scan/batch receipts.  It never
opens a scientific trajectory or native particle array, and it leaves every
qualification and split-safety field UNKNOWN/false.

``build`` is metadata/stat-only and produces a guarded request.  ``run`` is
the CPU parent task: it hashes the 336-case v15 small-source closure and runs
the existing v16 metadata generator.  The generated cards are checked against
the bound card content SHA.  A caller must use a new output directory and
``--cpu-slot-approved``; no HDF5/BI4 read flag exists for this task.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from typing import Any, Mapping, Sequence


SCHEMA = "ds02.request.v1"
REQUEST_KIND = "ds02.stage2.current336-provisional-domain-audit.v16-cpu-metadata.v17"
REPORT_SCHEMA = "ds02.stage2.current336-provisional-domain-audit.v16"
UNKNOWN = {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}
FAMILIES = tuple(f"F{index}" for index in range(1, 8))
FORBIDDEN_ROLE_MARKERS = ("trajectory_h5", "raw_partout", "raw_runparts", "initial_csv", "initial_stats", "visual")
FORBIDDEN_SUFFIXES = (".h5", ".hdf5", ".bi4", ".obi4", ".xmf")


class V17Error(ValueError):
    """Raised when a v17 metadata request is incomplete or unsafe."""


def sha256_file(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_sha(value: Mapping[str, Any]) -> str:
    body = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def _load(path: Path | str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).expanduser().resolve().read_text())
    except (OSError, json.JSONDecodeError) as error:
        raise V17Error(f"cannot read JSON {path}: {error}") from error
    if not isinstance(value, dict):
        raise V17Error(f"JSON object required: {path}")
    return value


def _write_new(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise V17Error(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def _bind(path: Path | str, role: str, *, expected_sha: str | None = None,
          status: str = "ACTUAL_METADATA_SOURCE") -> dict[str, Any]:
    target = Path(path).expanduser().resolve()
    if not target.is_file():
        raise V17Error(f"source is missing: {role}: {target}")
    stat = target.stat()
    if expected_sha is not None and (not isinstance(expected_sha, str) or len(expected_sha) != 64):
        raise V17Error(f"invalid expected SHA for {role}: {expected_sha!r}")
    return {
        "role": role,
        "path": str(target),
        "sha256": expected_sha,
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "content_hash_status": "PARENT_GUARD_REQUIRED" if expected_sha else "BUILDER_VERIFIED",
        "status": status,
    }


def _guard_paths(stage2_root: Path) -> dict[str, Path]:
    scripts = stage2_root / "lagrangian-fluid-lab" / "scripts"
    return {
        "shared_guard:runtime_v2": scripts / "ds_data02_runtime_v2.py",
        "shared_guard:runtime_v4": scripts / "ds_data02_runtime_v4.py",
        "shared_guard:stage2_dispatch_v4": scripts / "ds_data02_stage2_dispatch_v4.py",
        "shared_guard:strict_dispatch_v4": scripts / "ds_data02_strict_dispatch_v4.py",
    }


def _v15_sources(audit: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows = audit.get("input_roles")
    if not isinstance(rows, list) or not rows:
        raise V17Error("v15 input_roles are required")
    by_path: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("path"), str) or not isinstance(row.get("role"), str):
            raise V17Error("malformed v15 input role")
        role = str(row["role"])
        path = Path(str(row["path"])).expanduser().resolve()
        lowered_role = role.lower()
        lowered_path = str(path).lower()
        if any(marker in lowered_role for marker in FORBIDDEN_ROLE_MARKERS):
            raise V17Error(f"v15 closure contains forbidden scientific source role: {role}")
        if "scan" in lowered_role or "batch" in lowered_role:
            raise V17Error(f"mutable scan/batch role is forbidden: {role}")
        if any(lowered_path.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            raise V17Error(f"scientific array/trajectory source is forbidden in metadata closure: {path}")
        expected_sha = row.get("sha256")
        pending_run_out = role == "case:run_out" and row.get("hash_mode") == "parent_content_sha256_required"
        if not pending_run_out and (not isinstance(expected_sha, str) or len(expected_sha) != 64):
            raise V17Error(f"v15 source lacks a content SHA: {path}")
        record = by_path.get(str(path))
        if record is None:
            record = {
                "role": "v15_input:" + role,
                "v15_roles": [role],
                "case_indices": sorted(index for index in row.get("case_indices", []) if isinstance(index, int)),
                "path": str(path),
                "sha256": expected_sha,
                "bytes": int(row.get("bytes", path.stat().st_size)),
                "mtime_ns": int(row.get("mtime_ns", path.stat().st_mtime_ns)),
                "content_hash_status": "PARENT_GUARD_REQUIRED_PENDING_RUN_OUT" if pending_run_out else "PARENT_GUARD_REQUIRED",
                "status": "ACTUAL_V15_SOURCE_DECLARATION",
            }
            by_path[str(path)] = record
        else:
            if record["sha256"] not in (None, expected_sha) and expected_sha is not None:
                raise V17Error(f"conflicting v15 source declaration: {path}")
            if record["bytes"] != int(row.get("bytes", record["bytes"])):
                raise V17Error(f"conflicting v15 source declaration: {path}")
            record["v15_roles"].append(role)
            record["case_indices"] = sorted(set(record["case_indices"]) | {index for index in row.get("case_indices", []) if isinstance(index, int)})
    return [by_path[key] for key in sorted(by_path)]


def _card_bindings(report_file: Path, report: Mapping[str, Any]) -> list[dict[str, Any]]:
    cards = report.get("cards")
    if not isinstance(cards, Mapping) or set(cards) != set(FAMILIES):
        raise V17Error("v16 report must bind exactly seven cards")
    result = []
    for family in FAMILIES:
        item = cards[family]
        if not isinstance(item, Mapping) or item.get("status") != "PROVISIONAL_DOMAIN_CARD; QUALIFICATION_UNKNOWN":
            raise V17Error(f"{family} card is not provisional/unknown")
        path = (report_file.parent / str(item.get("path"))).resolve()
        card = _load(path)
        if card.get("sha256") != item.get("sha256"):
            raise V17Error(f"{family} card canonical SHA differs from report")
        result.append(_bind(path, f"v16_{family}_family_card", expected_sha=sha256_file(path)))
    return result


def build(report_path: Path | str, output_path: Path | str, *, stage2_root: Path | str | None = None) -> dict[str, Any]:
    report_file = Path(report_path).expanduser().resolve()
    output_file = Path(output_path).expanduser().resolve()
    report = _load(report_file)
    if report.get("schema") != REPORT_SCHEMA or report.get("status") != "PROVISIONAL_336_DOMAIN_CATEGORIES; SEMANTIC_CLOSURE_PENDING; QUALIFICATION_UNKNOWN":
        raise V17Error("report is not the conservative v16 provisional result")
    if report.get("audit_scope", {}).get("case_count") != 336 or report.get("audit_scope", {}).get("hdf5_or_bi4_read") is not False:
        raise V17Error("v16 report must be metadata-only for all 336 cases")
    if report.get("qualification") != UNKNOWN or report.get("split_policy", {}).get("split_safe") is not False:
        raise V17Error("v16 report cannot grant qualification or split safety")
    source_audit = report.get("audit_scope", {}).get("source_audit")
    if not isinstance(source_audit, Mapping):
        raise V17Error("v15 source audit binding is missing")
    audit_file = (report_file.parent / str(source_audit.get("path"))).resolve()
    audit = _load(audit_file)
    if audit.get("schema") != "ds02.request.v1" or audit.get("kind") != "stage2_current336_lineage_v15_full_small_source_closure":
        raise V17Error("v15 source audit schema is unexpected")
    if audit.get("audit_scope", {}).get("trajectory_h5_stat_or_content_read") is not False:
        raise V17Error("v15 source audit must exclude HDF5 content/stat reads")
    if audit.get("qualification") != UNKNOWN:
        raise V17Error("v15 audit qualification is not UNKNOWN")
    if sha256_file(audit_file) != source_audit.get("sha256"):
        raise V17Error("v15 source audit SHA differs from v16 report")
    cards = _card_bindings(report_file, report)
    lineage_root = report_file.parent.parent
    v13_cards = []
    for family in FAMILIES:
        path = lineage_root / "v13" / f"{family}-family-card-v13.json"
        v13_cards.append(_bind(path, f"immutable_{family}_v13_card", expected_sha=sha256_file(path)))
    stage2 = Path(stage2_root).expanduser().resolve() if stage2_root else Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics").resolve()
    guards = [_bind(path, role, expected_sha=sha256_file(path), status="ACTUAL_SHARED_V4_GUARD_SOURCE") for role, path in _guard_paths(stage2).items()]
    v16_script = Path(__file__).resolve().with_name("ds_data02_stage2_lineage_v16_provisional_domains.py")
    v16_test = Path(__file__).resolve().parents[1] / "tests/test_ds_data02_stage2_lineage_v16_provisional_domains.py"
    v15_script = Path(__file__).resolve().with_name("ds_data02_stage2_lineage_audit_v15.py")
    v15_test = Path(__file__).resolve().parents[1] / "tests/test_ds_data02_stage2_lineage_audit_v15.py"
    v17_script = Path(__file__).resolve()
    worker_bindings = [
        _bind(v16_script, "v16_domain_card_generator", expected_sha=sha256_file(v16_script)),
        _bind(v16_test, "v16_domain_card_test", expected_sha=sha256_file(v16_test)),
        _bind(v15_script, "v15_lineage_worker", expected_sha=sha256_file(v15_script)),
        _bind(v15_test, "v15_lineage_test", expected_sha=sha256_file(v15_test)),
        _bind(v17_script, "v17_cpu_metadata_guard_worker", expected_sha=sha256_file(v17_script)),
    ]
    catalog = audit.get("catalog_binding", {}).get("path")
    if not isinstance(catalog, str):
        raise V17Error("v15 catalog binding is missing")
    catalog_binding = _bind(catalog, "current336_catalog", expected_sha=audit["catalog_binding"].get("sha256"))
    dependency = audit.get("execution_closure", {}).get("root_dependency_license_path")
    if not isinstance(dependency, str):
        raise V17Error("root dependency/license path is missing")
    dependency_binding = _bind(dependency, "root_dependency_license_index", expected_sha=sha256_file(dependency))
    v15_inputs = _v15_sources(audit)
    fixed = [_bind(audit_file, "v15_small_source_audit", expected_sha=sha256_file(audit_file)), _bind(report_file, "v16_domain_audit_report", expected_sha=sha256_file(report_file)), catalog_binding, dependency_binding]
    bindings = fixed + cards + v13_cards + guards + worker_bindings + v15_inputs
    # Every source is an exact file and each mutable scan/batch role has been
    # rejected above.  Keep the role inventory explicit for review.
    if any("scan" in str(item.get("role", "")).lower() or "batch" in str(item.get("role", "")).lower() for item in bindings):
        raise V17Error("mutable scan/batch source role entered CPU closure")
    unique: dict[str, dict[str, Any]] = {}
    for item in bindings:
        old = unique.get(item["path"])
        if old is not None and old.get("sha256") not in (None, item.get("sha256")) and item.get("sha256") is not None:
            raise V17Error(f"conflicting closure SHA for {item['path']}")
        unique.setdefault(item["path"], item)
    inputs = [unique[key] for key in sorted(unique)]
    request = {
        "schema": SCHEMA,
        "request_id": "current336-provisional-domain-audit-v16-cpu-metadata-v17-001",
        "orchestration_schema": REQUEST_KIND,
        "status": "READY_FOR_PARENT_GUARD",
        "role": "DEVELOPMENT",
        "source_hashes_preverified_by_parent": False,
        "input_files": [item["path"] for item in inputs],
        "input_hashes": {item["path"]: item.get("sha256") for item in inputs},
        "input_stat_binding": {item["path"]: {"bytes": item["bytes"], "mtime_ns": item["mtime_ns"]} for item in inputs},
        "source_bindings": inputs,
        "closure_summary": {
            "v15_source_records": len(v15_inputs),
            "unique_input_records": len(inputs),
            "v15_declared_source_roles": audit.get("source_role_counts"),
            "actual_shared_guard_roles": sorted(item["role"] for item in guards),
            "mutable_scan_batch_receipts": "EXCLUDED_AND_REJECTED",
            "forbidden_scientific_arrays": "HDF5/BI4/XMF/initial CSV/raw PartOut excluded",
        },
        "actual_source_worker_outputs": {
            "v15_audit": next(item for item in inputs if item["role"] == "v15_small_source_audit"),
            "v16_report": next(item for item in inputs if item["role"] == "v16_domain_audit_report"),
            "cards": [item for item in inputs if item["role"].startswith("v16_F")],
            "status": "ACTUAL_METADATA_OUTPUTS; FULL_V15_SMALL_SOURCE_CLOSURE_BOUND; NO_H5_OR_BI4_READ",
        },
        "planned_followups": [{"role": "seven_family_raw_anchor_stream_plan", "path": str((report_file.parent / "seven-family-raw-anchor-stream-plan-v1.json").resolve()), "sha256": sha256_file(report_file.parent / "seven-family-raw-anchor-stream-plan-v1.json"), "status": "PLANNED_ONLY; NOT_EXECUTED; RAW_BI4_NOT_READ"}],
        "execution_contract": {
            "entrypoint": str(v17_script),
            "command": [sys.executable, str(v17_script), "run", "--request", "<request>", "--output-dir", "<new-output-root>", "--cpu-slot-approved"],
            "read_scope": "hash and parse the exact v15 JSON/XML/receipt/control/owner/manifest small-source closure, then regenerate v16 cards",
            "hdf5_or_bi4_read": False,
            "native_raw_reconstruction": "NOT_EXECUTED",
            "typed_comparison": "NOT_EXECUTED",
            "family_labels": "NOT_EXECUTED",
            "model_invoked": False,
            "cfd_invoked": False,
            "no_original_path_fallback": True,
            "output_policy": "new output directory only; existing outputs are refused",
        },
        "lineage_scope": {
            "case_count": 336,
            "family_case_counts": {family: 48 for family in FAMILIES},
            "split_safe": False,
            "semantic_closure": "PENDING",
            "qualification": UNKNOWN,
        },
        "resource_request": {
            "cpu": 1,
            "max_wall_seconds": 1800,
            "max_rss_bytes": 2 * 1024**3,
            "source_bytes_from_stat": sum(int(item["bytes"]) for item in inputs),
            "estimated_new_storage_bytes": 128 * 1024**2,
            "hdf5_read": "forbidden",
            "bi4_read": "forbidden",
            "xmf_read": "forbidden",
            "scan_batch_receipt_read": "forbidden",
        },
        "model_invoked": False,
        "cfd_invoked": False,
        "qualification": UNKNOWN,
        "limitations": [
            "Cards remain provisional source-role/domain categories, not effective physical equivalence closure",
            "split_safe remains false; recovery/resolution/window equivalence and all QI/QN/QE remain UNKNOWN",
            "Raw BI4-to-typed reconstruction and family labels are separate parent tasks",
        ],
    }
    request["sha256"] = canonical_sha(request)
    _write_new(output_file, request)
    return {"path": str(output_file), "sha256": request["sha256"], "input_count": len(inputs), "source_bytes": request["resource_request"]["source_bytes_from_stat"]}


def _validate(request: Mapping[str, Any], *, verify_content: bool) -> list[dict[str, Any]]:
    if request.get("schema") != SCHEMA or request.get("orchestration_schema") != REQUEST_KIND:
        raise V17Error("unsupported v17 CPU metadata request")
    if request.get("status") != "READY_FOR_PARENT_GUARD" or request.get("role") != "DEVELOPMENT":
        raise V17Error("request is not parent-guard ready development scope")
    if request.get("qualification") != UNKNOWN or request.get("lineage_scope", {}).get("split_safe") is not False:
        raise V17Error("qualification or split safety was promoted")
    declared = request.get("sha256")
    if declared != canonical_sha(request):
        raise V17Error("request canonical SHA differs")
    files = request.get("source_bindings")
    if not isinstance(files, list) or not files:
        raise V17Error("source_bindings are required")
    if request.get("execution_contract", {}).get("hdf5_or_bi4_read") is not False:
        raise V17Error("CPU metadata task must forbid HDF5/BI4 reads")
    for item in files:
        if not isinstance(item, Mapping):
            raise V17Error("source binding is malformed")
        path = Path(str(item.get("path"))).expanduser().resolve()
        if not path.is_file():
            raise V17Error(f"source disappeared: {path}")
        stat = path.stat()
        if stat.st_size != int(item.get("bytes", -1)) or stat.st_mtime_ns != int(item.get("mtime_ns", -1)):
            raise V17Error(f"source stat changed: {path}")
        role = str(item.get("role", ""))
        lowered_role = role.lower()
        lowered_path = str(path).lower()
        if any(marker in lowered_role for marker in FORBIDDEN_ROLE_MARKERS) or "scan" in lowered_role or "batch" in lowered_role:
            raise V17Error(f"forbidden source role: {role}")
        if any(lowered_path.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
            raise V17Error(f"forbidden scientific source path: {path}")
        expected = item.get("sha256")
        pending_run_out = role == "v15_input:case:run_out" and expected is None
        if not pending_run_out and (not isinstance(expected, str) or len(expected) != 64):
            raise V17Error(f"source SHA missing: {path}")
        if verify_content and expected is not None and sha256_file(path) != expected:
            raise V17Error(f"source content SHA differs: {path}")
    return [dict(item) for item in files]


def run(request_path: Path | str, output_dir: Path | str, *, cpu_slot_approved: bool = False) -> dict[str, Any]:
    request_file = Path(request_path).expanduser().resolve()
    request = _load(request_file)
    inputs = _validate(request, verify_content=cpu_slot_approved)
    output = Path(output_dir).expanduser().resolve()
    if output.exists():
        raise V17Error(f"refusing to overwrite output directory: {output}")
    if not cpu_slot_approved:
        report = {"schema": "ds02.stage2.current336-provisional-domain-audit.v16-cpu-metadata-report.v17", "status": "READY_FOR_PARENT_CPU_SLOT", "request": {"path": str(request_file), "sha256": sha256_file(request_file)}, "source_count": len(inputs), "content_verified": False, "execution_boundary": {"hdf5_or_bi4_read": False, "model_invoked": False, "cfd_invoked": False}, "qualification": UNKNOWN}
        _write_new(output / "metadata-preflight.json", report)
        return report
    output.mkdir(parents=True, exist_ok=False)
    audit = next(Path(item["path"]) for item in inputs if item["role"] == "v15_small_source_audit")
    cards_root = audit.parent.parent.parent
    generator_item = next(item for item in inputs if item["role"] == "v16_domain_card_generator")
    spec = importlib.util.spec_from_file_location("_ds02_v16_domain_generator_v17", generator_item["path"])
    if spec is None or spec.loader is None:
        raise V17Error("cannot import v16 domain generator")
    generator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generator)
    result = generator.build(audit, cards_root, output)
    generated_report = Path(result["report"])
    generated_cards = {family: output / f"{family}-family-card-v16-provisional.json" for family in FAMILIES}
    expected_cards = {Path(item["path"]).name: item["sha256"] for item in inputs if item["role"].startswith("v16_F")}
    card_checks = {}
    for family, path in generated_cards.items():
        digest = sha256_file(path)
        expected = expected_cards.get(path.name)
        card_checks[family] = {"path": str(path), "sha256": digest, "matches_bound_card": digest == expected}
        if expected is None or digest != expected:
            raise V17Error(f"regenerated {family} card differs from bound v16 card")
    generated = _load(generated_report)
    if generated.get("schema") != REPORT_SCHEMA or generated.get("audit_scope", {}).get("case_count") != 336 or generated.get("qualification") != UNKNOWN:
        raise V17Error("regenerated v16 report is not conservative")
    verified_manifest = []
    pending_run_out_count = 0
    for item in inputs:
        digest = item["sha256"]
        if digest is None:
            pending_run_out_count += 1
            digest = sha256_file(item["path"])
        verified_manifest.append({"path": item["path"], "sha256": digest, "role": item["role"]})
    manifest_sha = hashlib.sha256(json.dumps(verified_manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    report = {
        "schema": "ds02.stage2.current336-provisional-domain-audit.v16-cpu-metadata-report.v17",
        "status": "COMPLETE_METADATA_DEVELOPMENT_UNKNOWN",
        "request": {"path": str(request_file), "sha256": sha256_file(request_file)},
        "source_closure": {"input_count": len(inputs), "verified_content_count": len(inputs), "pending_run_out_sha_count": pending_run_out_count, "source_manifest_sha256": manifest_sha, "source_bytes": sum(int(item["bytes"]) for item in inputs), "mutable_scan_batch_receipts": "NONE_READ_OR_BOUND", "hdf5_or_bi4_read": False},
        "regenerated_v16": {"report": str(generated_report), "report_sha256": sha256_file(generated_report), "cards": card_checks, "source_audit_sha256": generated.get("audit_scope", {}).get("source_audit", {}).get("sha256")},
        "execution_boundary": {"hdf5_or_bi4_read": False, "raw_reconstruction": False, "typed_comparison": False, "family_labels": False, "model_invoked": False, "cfd_invoked": False},
        "lineage_scope": {"case_count": 336, "split_safe": False, "semantic_closure": "PENDING"},
        "qualification": UNKNOWN,
    }
    report["report_sha256"] = canonical_sha(report)
    _write_new(output / "cpu-metadata-execution-report.json", report)
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build-request")
    build_parser.add_argument("--report", type=Path, required=True)
    build_parser.add_argument("--output", type=Path, required=True)
    build_parser.add_argument("--stage2-root", type=Path)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--request", type=Path, required=True)
    run_parser.add_argument("--output-dir", type=Path, required=True)
    run_parser.add_argument("--cpu-slot-approved", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "build-request":
            result = build(args.report, args.output, stage2_root=args.stage2_root)
        else:
            result = run(args.request, args.output_dir, cpu_slot_approved=args.cpu_slot_approved)
    except (OSError, json.JSONDecodeError, V17Error, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(result, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
