#!/usr/bin/env python3
"""Prepare a guarded ROOT312 F4 intake from two independent producer proofs.

ROOT296 and ROOT297 are expected to provide three and four completed F4
physical-case proofs respectively.  This builder is deliberately strict:
both proofs, their declared case rows, and their small per-case reports must
exist before it writes anything.  It preserves the producer proofs as two
separate bundles and never manufactures a merged proof or infers completion
from a count.

Only small JSON and source metadata are read during preparation.  Native,
trajectory, HDF5, JSONL, BI4, and OBI4 content remain deferred to any later
case-specific worker.  Because the two future terminal proofs are not yet
available, no ROOT312 READY request is emitted by this source tree today.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import ds_data02_stage2_build_native_typed_mass_impact_v4 as mass_v4


SCRIPT = Path(__file__).resolve()
PRIMARY = mass_v4.PRIMARY
CURRENT = mass_v4.CURRENT
CURRENT_SHA = mass_v4.CURRENT_SHA
VENV = mass_v4.VENV
PYVENV = mass_v4.PYVENV
RUNTIME = mass_v4.RUNTIME
DISPATCH = mass_v4.DISPATCH
MAX_SMALL = mass_v4.MAX_SMALL
MAX_OUTPUT = mass_v4.MAX_OUTPUT
PAYLOAD_SUFFIXES = mass_v4.PAYLOAD_SUFFIXES
PROOF_SCHEMA = mass_v4.v3.root270.PROOF_SCHEMA
MANIFEST_SCHEMA = "ds02.stage2.root312-f4-multi-proof-intake.v1"
REPORT_SCHEMA = "ds02.stage2.root312-f4-multi-proof-intake-report.v1"


class Root312Error(ValueError):
    pass


def _json(path: Path, label: str) -> dict[str, Any]:
    try:
        return mass_v4._json(path, label)
    except mass_v4.MassV4Error as exc:
        raise Root312Error(str(exc)) from exc


def _small_ref(path: Path, label: str, expected: str | None = None) -> dict[str, Any]:
    try:
        return mass_v4._small_ref(path, label, expected)
    except mass_v4.MassV4Error as exc:
        raise Root312Error(str(exc)) from exc


def _proof_rows(proof: dict[str, Any], label: str) -> list[dict[str, Any]]:
    try:
        return mass_v4._proof_rows(proof, label)
    except mass_v4.MassV4Error as exc:
        raise Root312Error(str(exc)) from exc


def _deferred(value: Any, label: str) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        return mass_v4._deferred(value, label)
    except mass_v4.MassV4Error as exc:
        raise Root312Error(str(exc)) from exc


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic(path: Path, value: dict[str, Any], limit: int = MAX_OUTPUT) -> None:
    path = path.expanduser().resolve()
    if path.exists() or path.is_symlink():
        raise Root312Error(f"refusing to overwrite immutable output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        if temporary.stat().st_size > limit:
            raise Root312Error(f"{path} exceeds output bound")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _report_ref(row: dict[str, Any], case_id: str) -> dict[str, Any]:
    value = row.get("report")
    if isinstance(value, dict):
        path = value.get("path")
        expected = value.get("sha256")
    else:
        path = value
        expected = row.get("report_sha256")
    if not isinstance(path, str):
        raise Root312Error(f"{case_id} producer proof has no case report path")
    report_ref = _small_ref(Path(path), f"{case_id} producer case report", expected)
    report = _json(Path(report_ref["path"]), f"{case_id} producer case report")
    if report.get("physical_case_id") != case_id:
        raise Root312Error(f"{case_id} case report identity differs")
    if report.get("family_id") not in (None, "F4"):
        raise Root312Error(f"{case_id} case report family differs from F4")
    return report_ref


def _load_bundle(proof_path: Path, bundle_id: str, expected_count: int) -> dict[str, Any]:
    proof_ref = _small_ref(proof_path, f"{bundle_id} producer proof")
    proof = _json(proof_path, f"{bundle_id} producer proof")
    rows = _proof_rows(proof, f"{bundle_id} producer proof")
    if len(rows) != expected_count:
        raise Root312Error(f"{bundle_id} expected {expected_count} completed cases, got {len(rows)}")
    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        case_id = row["physical_case_id"]
        if case_id in seen:
            raise Root312Error(f"{bundle_id} duplicates case {case_id}")
        seen.add(case_id)
        if row.get("family_id") not in (None, "F4"):
            raise Root312Error(f"{case_id} is not an F4 producer row")
        report_ref = _report_ref(row, case_id)
        deferred = None
        for key in ("typed_records_stat_SHA_only", "records_stat_only", "typed_records", "records"):
            if isinstance(row.get(key), dict):
                deferred = _deferred(row[key], f"{case_id} deferred typed records")
                break
        cases.append({
            "physical_case_id": case_id,
            "family_id": "F4",
            "bundle_id": bundle_id,
            "proof_case_index": index,
            "producer_proof": proof_ref,
            "producer_case_report": report_ref,
            "deferred_typed_records": deferred,
        })
    return {
        "bundle_id": bundle_id,
        "family_id": "F4",
        "producer_proof": proof_ref,
        "case_count": len(cases),
        "case_ids": [case["physical_case_id"] for case in cases],
        "cases": cases,
        "producer_proof_preserved": True,
    }


def _all_source_refs(bundles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    refs: dict[str, dict[str, Any]] = {}
    for path, label, expected in (
        (SCRIPT, "ROOT312 intake worker", None),
        (mass_v4.SCRIPT, "V4 mass impact helper", None),
        (mass_v4.v3.SCRIPT, "V3 mass impact helper", None),
        (CURRENT, "CURRENT336", CURRENT_SHA),
        (VENV, "literal Python interpreter", None),
        (VENV.resolve(), "resolved Python interpreter", None),
        (PYVENV, "pyvenv.cfg", None),
        (RUNTIME, "runtime v8", None),
        (DISPATCH, "dispatch v8", None),
    ):
        ref = _small_ref(path, label, expected)
        refs[ref["path"]] = ref
    for bundle in bundles:
        proof_ref = bundle["producer_proof"]
        refs[proof_ref["path"]] = proof_ref
        for case in bundle["cases"]:
            report_ref = case["producer_case_report"]
            refs[report_ref["path"]] = report_ref
    return sorted(refs.values(), key=lambda item: item["path"])


def prepare(args: argparse.Namespace) -> dict[str, Any]:
    # Both loaders complete before output_root is created.  A missing or
    # incomplete future proof therefore leaves no misleading READY artifact.
    bundle_a = _load_bundle(args.proof_a.expanduser().resolve(), "ROOT296", 3)
    bundle_b = _load_bundle(args.proof_b.expanduser().resolve(), "ROOT297", 4)
    if set(bundle_a["case_ids"]) & set(bundle_b["case_ids"]):
        overlap = sorted(set(bundle_a["case_ids"]) & set(bundle_b["case_ids"]))
        raise Root312Error(f"producer proof bundles overlap: {overlap}")
    bundles = [bundle_a, bundle_b]
    refs = _all_source_refs(bundles)
    for ref in refs:
        if Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root312Error(f"payload entered ROOT312 static closure: {ref['path']}")
    output_root = args.output_root.expanduser().resolve()
    if output_root.exists():
        raise Root312Error(f"refusing to reuse output root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=False)
    cases = [case for bundle in bundles for case in bundle["cases"]]
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "status": "READY_SOURCE_ONLY_ROOT312_F4_SEPARATE_PROOFS",
        "namespace": "ROOT312_F4_MULTI_PROOF_INTAKE",
        "family_id": "F4",
        "proof_bundles": bundles,
        "cases": cases,
        "case_count": len(cases),
        "producer_proof_merge": {"created": False, "reason": "ROOT296 and ROOT297 remain independent producer proofs; no synthetic merged proof is emitted."},
        "source_refs": refs,
        "read_policy": {"proof_json_opened": True, "case_report_json_opened": True, "typed_jsonl_opened": False, "h5_opened": False, "native_payload_opened": False, "solver_started": False, "later_payload_read_after_parent_reservation": True},
        "claim_boundary": {"producer_proof_completeness": "VERIFIED_SMALL_PROOF_AND_CASE_REPORT_METADATA_ONLY", "native_typed_join": "DEFERRED", "physical_fate": "UNKNOWN", "physical_mass_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    manifest_path = output_root / "root312-f4-multi-proof-intake-manifest.json"
    _atomic(manifest_path, manifest)
    manifest_ref = _small_ref(manifest_path, "ROOT312 manifest")
    refs_with_manifest = sorted([*refs, manifest_ref], key=lambda item: item["path"])
    input_sha = {ref["path"]: ref["sha256"] for ref in refs_with_manifest}
    request = {
        "schema": "ds02.request.v1",
        "shared_runtime_version": "v8",
        "family_id": "INFRA",
        "case_id": "ROOT312_F4_MULTI_PROOF_INTAKE",
        "attempt_id": "root312-f4-multi-proof-intake-root-forward",
        "kind": "cpu",
        "cpu_task_kind": "audit",
        "cpu_threads": 1,
        "omp_threads": 1,
        "max_wall_seconds": 900,
        "max_memory_bytes": 1024 * 1024 * 1024,
        "estimated_storage_bytes": MAX_OUTPUT,
        "estimated_input_read_bytes": sum(int(ref["bytes"]) for ref in refs_with_manifest),
        "cwd": str(PRIMARY / "lagrangian-fluid-lab"),
        "worktree_root": str(PRIMARY),
        "command": [str(VENV), str(SCRIPT), "audit", "--manifest", str(manifest_path), "--output", "{attempt_root}/root312-f4-multi-proof-intake.json"],
        "input_files": sorted(input_sha),
        "input_sha256": dict(sorted(input_sha.items())),
        "manifest_contract": {"path": str(manifest_path), "sha256": manifest_ref["sha256"]},
        "producer_proofs": [{"bundle_id": bundle["bundle_id"], "path": bundle["producer_proof"]["path"], "sha256": bundle["producer_proof"]["sha256"], "case_count": bundle["case_count"]} for bundle in bundles],
        "producer_proof_merge": manifest["producer_proof_merge"],
        "read_policy": manifest["read_policy"],
        "claim_boundary": manifest["claim_boundary"],
        "launch_allowed": True,
        "execution_allowed": True,
        "launch_owner": "root",
    }
    _atomic(args.request_output.expanduser().resolve(), request)
    request_path = args.request_output.expanduser().resolve()
    return {"status": manifest["status"], "manifest": str(manifest_path), "manifest_sha256": _digest(manifest_path), "request": str(request_path), "request_sha256": _digest(request_path), "bundles": 2, "cases": len(cases), "producer_proof_merge_created": False, "payload_content_opened": False}


def _validate_manifest(path: Path) -> dict[str, Any]:
    manifest = _json(path, "ROOT312 manifest")
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("status") != "READY_SOURCE_ONLY_ROOT312_F4_SEPARATE_PROOFS":
        raise Root312Error("ROOT312 manifest schema/status differs")
    bundles = manifest.get("proof_bundles")
    if not isinstance(bundles, list) or len(bundles) != 2 or [bundle.get("case_count") for bundle in bundles] != [3, 4]:
        raise Root312Error("ROOT312 must preserve separate 3-case and 4-case proof bundles")
    if manifest.get("producer_proof_merge", {}).get("created") is not False:
        raise Root312Error("ROOT312 must not claim a merged producer proof")
    for ref in manifest.get("source_refs", []):
        if not isinstance(ref, dict) or not isinstance(ref.get("path"), str) or Path(ref["path"]).suffix.lower() in PAYLOAD_SUFFIXES:
            raise Root312Error("ROOT312 source ref is malformed or payload")
        _small_ref(Path(ref["path"]), "ROOT312 static source", ref.get("sha256"))
    return manifest


def audit(args: argparse.Namespace) -> dict[str, Any]:
    manifest = _validate_manifest(args.manifest)
    bundles = []
    for bundle in manifest["proof_bundles"]:
        proof = _json(Path(bundle["producer_proof"]["path"]), f"{bundle['bundle_id']} producer proof")
        rows = _proof_rows(proof, f"{bundle['bundle_id']} producer proof")
        if len(rows) != bundle["case_count"] or [row["physical_case_id"] for row in rows] != bundle["case_ids"]:
            raise Root312Error(f"{bundle['bundle_id']} producer proof changed")
        bundles.append({"bundle_id": bundle["bundle_id"], "case_count": len(rows), "case_ids": bundle["case_ids"], "status": "PROOF_METADATA_REVALIDATED_SEPARATELY"})
    report = {"schema": REPORT_SCHEMA, "status": "COMPLETED_ROOT312_SOURCE_PROOF_METADATA_ONLY", "producer_proof_bundles": bundles, "producer_proof_merge": manifest["producer_proof_merge"], "case_count": sum(item["case_count"] for item in bundles), "claim_boundary": manifest["claim_boundary"], "payload_content_opened": False}
    _atomic(args.output, report)
    return {"status": report["status"], "output": str(Path(args.output).expanduser().resolve()), "bundles": 2, "cases": report["case_count"], "producer_proof_merge_created": False}


def _self_test() -> dict[str, Any]:
    duplicate = [{"bundle_id": "ROOT296", "case_ids": ["C"]}, {"bundle_id": "ROOT297", "case_ids": ["C"]}]
    if not (set(duplicate[0]["case_ids"]) & set(duplicate[1]["case_ids"])):
        raise Root312Error("duplicate-bundle fixture was not detected")
    return {"schema": MANIFEST_SCHEMA, "status": "PASS", "checks": ["separate proof bundles", "exact 3/4 counts", "duplicate cases rejected", "no merged proof", "missing proof emits no READY artifact"]}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("self-test")
    prep = sub.add_parser("prepare")
    prep.add_argument("--proof-a", type=Path, required=True)
    prep.add_argument("--proof-b", type=Path, required=True)
    prep.add_argument("--output-root", type=Path, required=True)
    prep.add_argument("--request-output", type=Path, required=True)
    audit_parser = sub.add_parser("audit")
    audit_parser.add_argument("--manifest", type=Path, required=True)
    audit_parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = _self_test() if args.action == "self-test" else prepare(args) if args.action == "prepare" else audit(args)
    except (Root312Error, mass_v4.MassV4Error, mass_v4.v3.ImpactV3Error, OSError, ValueError, TypeError, KeyError) as exc:
        print(f"ROOT312_F4_MULTI_PROOF_INTAKE_ERROR: {exc}")
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
