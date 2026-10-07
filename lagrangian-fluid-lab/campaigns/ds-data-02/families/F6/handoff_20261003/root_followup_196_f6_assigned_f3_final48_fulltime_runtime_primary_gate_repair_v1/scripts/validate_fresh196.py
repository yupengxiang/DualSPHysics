#!/usr/bin/env python3
"""Read-only validator for the F3 fresh196 full-time primary gate.

This validator imports only the local fresh196 metadata builder, reruns it in a
new temporary directory, and checks the current explicit F3 checkpoint.  JSON
is read/hashed as metadata; XML/XMF and PNG references are existence/stat-only.
Scientific payload suffixes are rejected before open or hash.  The validator
derives accepted and pending counts from the explicit checkpoint/index inputs;
it therefore handles a later 45/3 boundary and the eventual 48/0 boundary
without editing this source package.  An incomplete input snapshot must never
produce a final48 catalog.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

FORBIDDEN = {".h5", ".bi4", ".ibi4", ".csv", ".dat", ".vtk", ".vtu", ".pvtu"}
EXPECTED_FRAMES = 836
EXPECTED_PARTICLES = 179208


class ValidationError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationError(message)


def read_json(path: Path, label: str) -> Any:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON read attempted for {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        fail(f"invalid JSON {label}: {path}: {exc}")


def sha_json(path: Path, label: str) -> str:
    if path.suffix.lower() != ".json":
        fail(f"non-JSON hash attempted for {label}: {path}")
    if not path.is_file():
        fail(f"missing JSON {label}: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ref_path(ref: Any, label: str) -> Path:
    if isinstance(ref, dict) and isinstance(ref.get("path"), str):
        raw = ref["path"]
    elif isinstance(ref, str):
        raw = ref
    else:
        fail(f"{label} is not a path string/dict")
    if not raw.startswith("/"):
        fail(f"{label} is not absolute: {raw}")
    path = Path(raw)
    if path.suffix.lower() in FORBIDDEN:
        fail(f"scientific payload escaped into fresh196: {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    return path


def check_ref(ref: Any, label: str, *, json_only: bool = False, require_sha: bool = False) -> Path:
    path = ref_path(ref, label)
    if json_only and path.suffix.lower() != ".json":
        fail(f"{label} must be JSON: {path}")
    if path.suffix.lower() == ".json":
        actual = sha_json(path, label)
        declared = ref.get("sha256") if isinstance(ref, dict) else None
        if declared is not None and declared != actual:
            fail(f"{label} SHA mismatch: {declared} != {actual}")
        if require_sha and not isinstance(declared, str):
            fail(f"{label} has no declared observed JSON SHA")
    return path


def load_builder(package_dir: Path):
    path = package_dir / "scripts" / "build_fresh196.py"
    spec = importlib.util.spec_from_file_location("fresh196_builder", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_package_manifest(package_dir: Path) -> None:
    manifest = read_json(package_dir / "package-manifest.json", "package manifest")
    if manifest.get("schema") != "ds02.f6.fresh196.package-manifest.v1":
        fail("package manifest schema mismatch")
    if manifest.get("package_name") != package_dir.name:
        fail("package manifest package_name mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        fail("package manifest files are missing")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("package manifest contains malformed file entry")
        rel = item["path"]
        if rel in seen or rel.startswith("/") or ".." in Path(rel).parts:
            fail(f"package manifest path is duplicate/unsafe: {rel}")
        seen.add(rel)
        path = package_dir / rel
        if not path.is_file():
            fail(f"package manifest file missing: {path}")
        if path.suffix.lower() in FORBIDDEN:
            fail(f"package manifest includes scientific payload: {path}")
        expected = item.get("sha256")
        if not isinstance(expected, str):
            fail(f"package manifest file has no SHA: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            fail(f"package manifest SHA mismatch: {path}")
        if item.get("bytes") != path.stat().st_size:
            fail(f"package manifest byte count mismatch: {path}")
    if "package-manifest.json" in seen:
        fail("package manifest must not self-hash")
    declared = set(seen)
    actual_files = {
        str(p.relative_to(package_dir))
        for p in package_dir.rglob("*")
        if p.is_file() and "__pycache__" not in p.parts and p.name != "package-manifest.json"
    }
    if declared != actual_files:
        fail(f"package manifest file set mismatch: missing={sorted(actual_files-declared)} extra={sorted(declared-actual_files)}")


def _synthetic_receipt(path: Path, *, qa: bool = True) -> dict[str, Any]:
    obj = {
        "schema": "ds02.execution-receipt.v1",
        "status": "completed",
        "returncode": 0,
        "case_id": "CASE",
        "physical_case_id": "PHYSICAL",
        "output_root": str(path.parent / "attempt"),
        "request_sha256": "a" * 64,
        "input_hashes_at_launch": {"meta.json": "b" * 64},
        "request": {
            "schema": "ds02.runner-request.v3",
            "case_id": "CASE",
            "physical_case_id": "PHYSICAL",
            "worktree_root": str(path.parent),
            "cwd": str(path.parent),
            "input_files": ["meta.json"],
            "input_sha256": {"meta.json": "b" * 64},
            "cpu_task_kind": "audit" if qa else "render",
        },
    }
    path.write_text(json.dumps(obj), encoding="utf-8")
    return {"path": str(path), "sha256": sha_json(path, "synthetic receipt")}


def _synthetic_typed_report(path: Path, *, identity: Any = "INVALID_IDENTITY_KEY", exclusion: Any = None) -> dict[str, Any]:
    obj = {
        "schema": "ds-data-02.bi4-direct-conversion.v1",
        "conversion_status": "completed",
        "frames": EXPECTED_FRAMES,
        "particles": EXPECTED_PARTICLES,
        "solver_dimension": {"solver_dimension": 3},
        "typed_identity": {"key": identity, "initial_exclusion_ledger": exclusion, "blocks": [{"zone": 0}], "observed_types": [0, 3], "observed_mks": [0, 1]},
        "lifecycle": {"introduced_ids": "rejected", "frame_summary": []},
        "partvtk_validation": {"all_passed": True},
        "time_evidence": {"strictly_increasing": True},
        "source_provenance": {},
    }
    path.write_text(json.dumps(obj), encoding="utf-8")
    return {"path": str(path), "sha256": sha_json(path, "synthetic typed report"), "role": "typed_report"}


def run_negative_contract_tests(builder: Any) -> dict[str, Any]:
    """Prove the two historical false-positive classes and core gate failures."""
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="fresh196-contract-negative-") as raw:
        root = Path(raw)
        receipt = _synthetic_receipt(root / "receipt.json")
        # A completed execution receipt is not an initial-QA report.
        qa_only = builder._f3_qa_certificate([receipt], "CASE", "PHYSICAL")
        results["qa_receipt_without_report_rejected"] = qa_only.get("verified") is False and "genuine_initial_qa_report_pass_and_binding_missing" in qa_only.get("reasons", [])
        # A fake runner request cannot be interpreted as an execution receipt.
        request_path = root / "runner-request.json"
        request_path.write_text(json.dumps({"schema": "ds02.runner-request.v3", "status": "root_enabled_actual_XMF460_completed0_full836_render_pending"}), encoding="utf-8")
        request_cert = builder._f3_receipt_certificate({"path": str(request_path)}, "CASE", "PHYSICAL", "synthetic_render")
        results["runner_request_not_receipt"] = request_cert.get("verified") is False and "top_level_is_not_execution_receipt" in request_cert.get("reasons", [])
        # No 836 frame ledger can pass the report certificate.
        report_path = root / "short-report.json"
        report_path.write_text(json.dumps({"schema": "ds02.stage1.paraview-full-animation-integrity.v1", "frames": EXPECTED_FRAMES, "source_frames": EXPECTED_FRAMES, "frame_diagnostics": []}), encoding="utf-8")
        report_cert = builder._f3_report_certificate({"path": str(report_path)}, "CASE")
        results["short_frame_ledger_rejected"] = report_cert.get("verified") is False and any("diagnostics" in x for x in report_cert.get("reasons", []))
        # Wrong time is rejected by the XML/report join gate (report itself can be synthetic and short).
        wrong_report = root / "wrong-time-report.json"
        wrong_report.write_text(json.dumps({"schema": "ds02.stage1.paraview-full-animation-integrity.v1", "frames": EXPECTED_FRAMES, "source_frames": EXPECTED_FRAMES, "frame_selection": list(range(EXPECTED_FRAMES)), "frame_diagnostics": [{"frame": 0, "actual_time_s": 1.0}]}), encoding="utf-8")
        wrong_cert = builder._f3_report_certificate({"path": str(wrong_report)}, "CASE")
        results["incomplete_or_wrong_time_rejected"] = wrong_cert.get("verified") is False
        # Typed identity must be exact and must carry an initial exclusion ledger.
        typed_path = root / "typed-invalid.json"
        typed_ref = _synthetic_typed_report(typed_path)
        typed_cert = builder._f3_typed_certificate([typed_ref], "CASE", "PHYSICAL", None)
        reasons = set(typed_cert.get("reasons", []))
        reports = typed_cert.get("reports") or []
        report_reasons = set(reports[0].get("reasons", [])) if reports else set()
        results["typed_invalid_identity_rejected"] = typed_cert.get("verified") is False and "typed_identity_key_not_exact_Zone_Idp" in report_reasons
        results["typed_missing_initial_exclusion_rejected"] = typed_cert.get("verified") is False and "typed_initial_exclusion_ledger_missing" in report_reasons
        # XML must be an actual temporal Xdmf product, not a placeholder.
        xml_path = root / "short.xmf"
        xml_path.write_text("<Xdmf><Domain/></Xdmf>", encoding="utf-8")
        xml_cert = builder._f3_xml_certificate({"path": str(xml_path)}, None, "CASE")
        results["incomplete_xmf_rejected"] = xml_cert.get("verified") is False
        # Existing nonempty output is immutable and cannot be overwritten.
        out = root / "existing-output"
        out.mkdir()
        (out / "old.json").write_text("{}", encoding="utf-8")
        try:
            builder._prepare_output_dir(out)
        except Exception:
            results["existing_output_overwrite_rejected"] = True
        else:
            results["existing_output_overwrite_rejected"] = False
    failed = [k for k, value in results.items() if not value]
    if failed:
        fail(f"negative contract tests failed: {failed}")
    return results


def validate_current(package_dir: Path, checkpoint: Path, index: Path, membership: Path, legacy: Path) -> dict[str, Any]:
    builder = load_builder(package_dir)
    negative = run_negative_contract_tests(builder)
    with tempfile.TemporaryDirectory(prefix="fresh196-build-") as raw:
        out = Path(raw) / "fresh196-output"
        result = builder.build_from_inputs(checkpoint, index, membership, legacy, out)
        if result.get("mode") != "readiness":
            fail("current incomplete inputs unexpectedly produced final48")
        readiness = read_json(out / "fresh196-readiness.json", "fresh196 readiness")
        if readiness.get("schema") != "ds02.f3.fresh196.final48.readiness.v1":
            fail("readiness schema mismatch")
        if readiness.get("complete_final48_emitted") is not False:
            fail("incomplete inputs created a final catalog")
        if (out / "F3-FINAL48-COMPLETE-PRIMARY-DELIVERY.json").exists():
            fail("incomplete inputs left a final catalog")
        cp = read_json(checkpoint, "explicit checkpoint")
        idx = read_json(index, "explicit current index")
        mem = read_json(membership, "explicit membership")
        f3 = [r for r in idx.get("cases", []) if isinstance(r, dict) and r.get("family_id") == "F3"]
        accepted = [r for r in f3 if isinstance(r.get("accepted_decision"), dict)]
        pending = [r for r in f3 if not isinstance(r.get("accepted_decision"), dict)]
        if len(f3) != 48:
            fail(f"unexpected explicit registered F3 count: {len(f3)}")
        expected_counts = {"registered_final48": len(f3), "accepted_visual": len(accepted), "pending_visual": len(pending)}
        if readiness.get("observed_counts") != expected_counts:
            fail(f"readiness counts do not match explicit F3 index: {readiness.get('observed_counts')}")
        if cp.get("accepted_per_family", {}).get("F3") != len(accepted):
            fail("checkpoint accepted F3 count does not match the explicit current index")
        f8 = mem.get("frozen_first8_physical_case_ids")
        f24 = mem.get("actual_first24_physical_case_ids")
        f48 = mem.get("registered_final48_physical_case_ids")
        if not all(isinstance(x, list) for x in (f8, f24, f48)) or [len(x) for x in (f8, f24, f48)] != [8, 24, 48]:
            fail("fixed membership lists are not 8/24/48")
        if not (set(f8) <= set(f24) <= set(f48)):
            fail("fixed membership subset relation is false")
        rows = readiness.get("readiness_rows")
        if not isinstance(rows, list) or [r.get("physical_case_id") for r in rows] != f48:
            fail("readiness rows changed fixed registered order")
        by_id = {r.get("physical_case_id"): r for r in rows}
        pending_ids = [r.get("physical_case_id") for r in f3 if not isinstance(r.get("accepted_decision"), dict)]
        gap_ids = [r.get("physical_case_id") for r in f3 if isinstance(r.get("accepted_decision"), dict) and by_id[r.get("physical_case_id")].get("primary_refs_complete") is not True]
        expected_missing = pending_ids + [x for x in f48 if x in gap_ids]
        if readiness.get("missing_physical_case_ids") != expected_missing:
            fail("readiness missing IDs are not explicit pending+gap order")
        audits = readiness.get("accepted_ref_audit")
        if not isinstance(audits, list) or len(audits) != len(accepted):
            fail("accepted reference audit does not cover every accepted row")
        accepted_ids = {r.get("physical_case_id") for r in accepted}
        if {r.get("physical_case_id") for r in audits} != accepted_ids:
            fail("accepted reference audit IDs differ from checkpoint/index")
        for audit in audits:
            physical = audit.get("physical_case_id")
            check_ref(audit.get("accepted_decision"), f"{physical} accepted decision", json_only=True, require_sha=True)
            comp = audit.get("primary_ref_completeness")
            if not isinstance(comp, dict):
                fail(f"{physical} lacks primary completeness record")
            complete = comp.get("complete_for_final_primary_delivery") is True
            for key in ("actual_xmf_manifest", "actual_render_report", "actual_render_receipt"):
                value = audit.get(key)
                if value is not None:
                    check_ref(value, f"{physical} {key}", json_only=True)
                elif complete:
                    fail(f"{physical} complete row lacks {key}")
            xml_value = audit.get("actual_xmf_xml")
            if xml_value is not None:
                check_ref(xml_value, f"{physical} actual_xmf_xml")
            elif complete:
                fail(f"{physical} complete row lacks actual_xmf_xml")
            if not isinstance(comp.get("field_metadata_fulltime_certificate_verified"), bool):
                fail(f"{physical} lacks full-time field certificate flag")
            if comp.get("complete_for_final_primary_delivery") is not True and not comp.get("reasons"):
                fail(f"{physical} is incomplete without an evidence-based reason")
            for role_key, json_only in (("native_refs", True), ("typed_refs", True), ("gencase_or_definition_refs", False), ("initial_qa_or_audit_refs", True), ("owner_or_source_refs", False), ("contact_png_refs", False), ("key_png_refs", False)):
                refs = audit.get(role_key)
                if not isinstance(refs, list):
                    fail(f"{physical} missing role list {role_key}")
                for i, ref in enumerate(refs):
                    check_ref(ref, f"{physical} {role_key}[{i}]", json_only=json_only)
            presence = audit.get("metadata_role_presence")
            if not isinstance(presence, dict) or presence.get("selected_primary_refs_are_role_labeled") is not True:
                fail(f"{physical} lacks explicit role-labeled metadata evidence")
            runtime = comp.get("runtime_gate")
            if not isinstance(runtime, dict) or not isinstance(runtime.get("role_scope_presence_masks"), dict):
                fail(f"{physical} lacks role scope presence masks")
            # Any request-to-receipt correction is preserved as explicit
            # provenance when it exists.  Root1330 is an F2 correction and is
            # never imposed as an unrelated F3 acceptance gate.
            correction = audit.get("render_receipt_role_correction")
            if correction is not None and not isinstance(correction, dict):
                fail(f"{physical} has malformed render role correction provenance")
        return {"status": "PASS", "mode": "readiness", "counts": readiness["observed_counts"], "pending_or_incomplete": readiness["missing_physical_case_ids"], "accepted_rows_with_ref_gaps": len(readiness.get("accepted_rows_with_ref_gaps", [])), "negative_contract_tests": negative}


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate fresh196 F3 metadata builder and current readiness boundary.")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--current-index", type=Path, required=True)
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--legacy-catalog", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--skip-package-manifest", action="store_true")
    args = parser.parse_args()
    package_dir = args.package_dir.resolve()
    if not args.skip_package_manifest:
        validate_package_manifest(package_dir)
    print(json.dumps(validate_current(package_dir, args.checkpoint, args.current_index, args.membership, args.legacy_catalog), sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"fresh196 validation failed: {exc}")
