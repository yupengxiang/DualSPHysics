#!/usr/bin/env python3
"""Read-only validator for the fresh195 final48 builder.

The validator re-runs the builder against explicit JSON metadata inputs in a
throw-away directory.  It reads and hashes JSON only; XMF/XML/PNG references
are existence/stat checks, and H5/BI4/IBI4/CSV/DAT/VTK payloads are rejected
before any open/hash operation.  At the current checkpoint the expected result
is a readiness file (44 accepted, 4 pending), never a final48 catalog.
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


def check_ref(ref: Any, label: str, *, json_only: bool = False) -> Path:
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
        fail(f"scientific payload ref escaped into fresh195: {label}: {path}")
    if not path.is_file():
        fail(f"missing {label}: {path}")
    if json_only and path.suffix.lower() != ".json":
        fail(f"{label} must be JSON: {path}")
    if path.suffix.lower() == ".json":
        actual = sha_json(path, label)
        declared = ref.get("sha256") if isinstance(ref, dict) else None
        if declared is not None and declared != actual:
            fail(f"{label} SHA mismatch: {declared} != {actual}")
    return path


def load_builder(package_dir: Path):
    path = package_dir / "scripts" / "build_fresh195.py"
    spec = importlib.util.spec_from_file_location("fresh195_builder", path)
    if spec is None or spec.loader is None:
        fail(f"cannot import builder: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_package_manifest(package_dir: Path) -> None:
    manifest_path = package_dir / "package-manifest.json"
    manifest = read_json(manifest_path, "package manifest")
    if manifest.get("schema") != "ds02.f6.fresh195.package-manifest.v1":
        fail("package manifest schema mismatch")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        fail("package manifest files are missing")
    for item in files:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            fail("package manifest contains malformed file entry")
        path = package_dir / item["path"]
        if not path.is_file():
            fail(f"package manifest file missing: {path}")
        if path.suffix.lower() in FORBIDDEN:
            fail(f"package manifest includes scientific payload: {path}")
        if path.name == "package-manifest.json":
            continue
        expected = item.get("sha256")
        if not isinstance(expected, str):
            fail(f"package manifest file has no SHA: {path}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            fail(f"package manifest SHA mismatch: {path}")



def run_negative_contract_tests(builder: Any) -> dict[str, Any]:
    """Exercise the four producer-gate failures using synthetic metadata only."""
    results: dict[str, bool] = {}
    with tempfile.TemporaryDirectory(prefix="fresh195-contract-negative-") as raw:
        root = Path(raw)
        request_path = root / "request.json"
        request_path.write_text(json.dumps({"schema": "ds02.runner-request.v3", "status": "root_enabled_actual_XMF460_completed0_full401_render_pending_F7renderdrain"}), encoding="utf-8")
        request_ref = {"path": str(request_path), "sha256": sha_json(request_path, "synthetic request")}
        request_gate = builder._execution_receipt_certificate(request_ref, "CASE", "PHYSICAL", "synthetic_render")
        results["runner_request_is_rejected_as_receipt"] = request_gate.get("terminal_completed_returncode_zero") is False

        base_diag = []
        for i in range(401):
            base_diag.append({
                "frame": i,
                "actual_time_s": float(i) * 0.01,
                "missing": 0,
                "finite_positions_active": True,
                "identity_axis_preserved": True,
                "finite_fields": {field: {"finite_active": True, "nonfinite_active": 0} for field in ("mass", "velocity", "density", "pressure")},
                "type_counts_active": {"fixed": 1, "moving": 0, "floating": 0, "fluid": 1, "unknown": 0},
            })
        base_report = {
            "schema": "ds02.stage1.paraview-full-animation-integrity.v1",
            "frames": 401,
            "source_frames": 401,
            "all_frames_rendered": True,
            "actual_times_preserved_exactly": True,
            "native_identity_axis_preserved": True,
            "nonfinite_active_states": 0,
            "frame_selection": list(range(401)),
            "frame_diagnostics": base_diag,
            "outputs": {"contact_sheets": ["contact.png"], "key_frames": ["key.png"]},
        }
        missing = dict(base_report)
        missing["frame_diagnostics"] = base_diag[:-1]
        missing_path = root / "missing-frame-report.json"
        missing_path.write_text(json.dumps(missing), encoding="utf-8")
        missing_probe = builder._report_certificate({"path": str(missing_path)}, None)
        results["missing_frame_is_rejected"] = missing_probe.get("fulltime_metadata_certificate_verified") is False
        wrong_time = json.loads(json.dumps(base_report))
        wrong_time["frame_diagnostics"][10]["actual_time_s"] = -1.0
        wrong_path = root / "wrong-time-report.json"
        wrong_path.write_text(json.dumps(wrong_time), encoding="utf-8")
        wrong_probe = builder._report_certificate({"path": str(wrong_path)}, None)
        results["wrong_time_is_rejected"] = wrong_probe.get("fulltime_metadata_certificate_verified") is False

        existing = root / "existing"
        existing.mkdir()
        (existing / "sentinel").write_text("immutable", encoding="utf-8")
        try:
            builder._prepare_output_dir(existing)
        except Exception:
            results["existing_output_dir_is_rejected"] = True
        else:
            results["existing_output_dir_is_rejected"] = False

        # The XMF gate must reject a terminal receipt whose output root does
        # not contain the selected manifest, even when the receipt itself has
        # status completed/returncode 0.
        xmf_root = root / "xmf-attempt"
        (xmf_root / "xdmf").mkdir(parents=True)
        manifest_path = xmf_root / "xdmf" / "manifest.json"
        manifest_path.write_text(json.dumps({"case_id": "CASE", "physical_case_id": "PHYSICAL"}), encoding="utf-8")
        (xmf_root / "execution-receipt.json").write_text(json.dumps({
            "schema": "ds02.execution-receipt.v1",
            "status": "completed",
            "returncode": 0,
            "output_root": str(root / "wrong-attempt"),
            "request": {
                "schema": "ds02.runner-request.v3",
                "case_id": "CASE",
                "physical_case_id": "PHYSICAL",
                "input_files": ["/tmp/metadata.json"],
                "input_sha256": {"/tmp/metadata.json": "0" * 64},
                "worktree_root": "/tmp/worktree",
                "cwd": "/tmp/worktree",
            },
        }), encoding="utf-8")
        xmf_probe = builder._xmf_execution_certificate({"path": str(manifest_path)}, "CASE", "PHYSICAL")
        results["xmf_receipt_wrong_output_root_is_rejected"] = xmf_probe.get("verified") is False

        # A bare `status: pass` report is not initial-QA evidence.  It must
        # carry an all-true check map and direct prepared/PartVTK input scope.
        qa_path = root / "bare-qa.json"
        qa_path.write_text(json.dumps({"schema": "qa", "case_id": "CASE", "status": "pass"}), encoding="utf-8")
        qa_probe = builder._qa_certificate([{"path": str(qa_path)}], "CASE", "PHYSICAL")
        results["bare_qa_pass_without_scope_is_rejected"] = qa_probe.get("verified") is False
    if not all(results.values()):
        fail(f"negative contract tests failed: {results}")
    return results


def validate_current(package_dir: Path, checkpoint: Path, index: Path, membership: Path, legacy: Path) -> dict[str, Any]:
    builder = load_builder(package_dir)
    negative_tests = run_negative_contract_tests(builder)
    temp = Path(tempfile.mkdtemp(prefix="fresh195-validator-"))
    try:
        result = builder.build_from_inputs(checkpoint, index, membership, legacy, temp)
        if result.get("mode") != "readiness":
            fail("current explicit inputs unexpectedly emitted a final48 catalog")
        readiness_path = Path(result["path"])
        readiness = read_json(readiness_path, "fresh195 readiness")
        if readiness.get("schema") != "ds02.f2.fresh195.final48.readiness.v1":
            fail("readiness schema mismatch")
        if readiness.get("complete_final48_emitted") is not False:
            fail("incomplete inputs emitted/claimed complete final48")
        if (temp / "F2-FINAL48-COMPLETE-PRIMARY-DELIVERY.json").exists():
            fail("incomplete inputs created a final catalog")

        cp = read_json(checkpoint, "explicit checkpoint")
        idx = read_json(index, "explicit current index")
        mem = read_json(membership, "explicit membership")
        f2 = [r for r in idx.get("cases", []) if isinstance(r, dict) and r.get("family_id") == "F2"]
        accepted = [r for r in f2 if isinstance(r.get("accepted_decision"), dict)]
        pending = [r for r in f2 if not isinstance(r.get("accepted_decision"), dict)]
        if readiness.get("observed_counts") != {"registered_final48": 48, "accepted_visual": len(accepted), "pending_visual": len(pending)}:
            fail("readiness counts do not match explicit current index")
        cp_count = cp.get("accepted_per_family", {}).get("F2")
        if isinstance(cp_count, int) and cp_count != len(accepted):
            fail("checkpoint accepted F2 count does not match current index")
        f8 = mem.get("frozen_first8_physical_case_ids")
        f24 = mem.get("actual_first24_physical_case_ids")
        f48 = mem.get("registered_final48_physical_case_ids")
        if not (isinstance(f8, list) and isinstance(f24, list) and isinstance(f48, list)):
            fail("membership lists missing")
        if len(f8) != 8 or len(f24) != 24 or len(f48) != 48:
            fail("membership list lengths are not 8/24/48")
        if not set(f8) <= set(f24) <= set(f48):
            fail("fixed membership subset relation is false")
        rows = readiness.get("readiness_rows")
        if not isinstance(rows, list) or [r.get("physical_case_id") for r in rows] != f48:
            fail("readiness rows changed fixed registered order")
        expected_missing = [r.get("physical_case_id") for r in f2 if not isinstance(r.get("accepted_decision"), dict)]
        expected_missing.extend(r.get("physical_case_id") for r in rows if r.get("accepted_decision_present") is True and r.get("primary_refs_complete") is not True)
        if readiness.get("missing_physical_case_ids") != expected_missing:
            fail("pending/incomplete IDs are not in explicit registered order")
        audits = readiness.get("accepted_ref_audit")
        if not isinstance(audits, list) or len(audits) != len(accepted):
            fail("accepted reference audit does not cover each accepted row")
        accepted_ids = {r.get("physical_case_id") for r in accepted}
        if {r.get("physical_case_id") for r in audits} != accepted_ids:
            fail("accepted reference audit physical IDs differ from current index")
        for audit in audits:
            physical = audit["physical_case_id"]
            for key in ("accepted_decision", "actual_xmf_manifest", "actual_render_report", "actual_render_receipt"):
                check_ref(audit.get(key), f"{physical} {key}", json_only=True)
            check_ref(audit.get("actual_xmf_xml"), f"{physical} actual_xmf_xml")
            comp = audit.get("primary_ref_completeness")
            if not isinstance(comp, dict):
                fail(f"current accepted row lacks primary completeness gate: {physical}")
            if not isinstance(comp.get("field_metadata_fulltime_certificate_verified"), bool):
                fail(f"{physical} lacks field_metadata_fulltime_certificate_verified")
            if comp.get("complete_for_final_primary_delivery") is not True and not comp.get("reasons"):
                fail(f"{physical} failed completeness without a recorded reason")
            # Preserve and validate each selected primary role. JSON refs are
            # opened/hashed as metadata; XMF and PNG refs are stat-only.
            for role_key, json_only in (
                ("native_refs", True),
                ("typed_refs", True),
                ("gencase_or_definition_refs", False),
                ("initial_qa_or_audit_refs", True),
                ("owner_or_source_refs", False),
                ("contact_png_refs", False),
                ("key_png_refs", False),
            ):
                refs = audit.get(role_key)
                if not isinstance(refs, list):
                    fail(f"{physical} missing role list {role_key}")
                for i, ref in enumerate(refs):
                    check_ref(ref, f"{physical} {role_key}[{i}]", json_only=json_only)
            role_presence = audit.get("metadata_role_presence")
            if not isinstance(role_presence, dict) or role_presence.get("selected_primary_refs_are_role_labeled") is not True:
                fail(f"{physical} missing explicit plan/runtime role presence")
            report_ref = audit["actual_render_report"]
            report_path = Path(report_ref["path"])
            if report_ref.get("sha256") != sha_json(report_path, f"{physical} render report"):
                fail(f"{physical} render report SHA is not observed JSON SHA")
            render_gate = ((comp.get("runtime_gate") or {}).get("render_receipt") or {})
            if render_gate.get("terminal_completed_returncode_zero") is not True and comp.get("complete_for_final_primary_delivery") is True:
                fail(f"{physical} claimed complete despite non-terminal render receipt: {render_gate}")
            if physical in {
                "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX046_RY014_FILL080_ROT120",
                "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT065",
                "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX048_RY014_FILL080_ROT120",
                "F2_STAGE1_FIRST24_OFFSET_OPEN_RIM_RX052_RY014_FILL080_ROT065",
            }:
                if not isinstance(audit.get("historical_source_render_request_role"), dict):
                    fail(f"{physical} did not preserve Root1330 historical request role")
                correction = audit.get("render_receipt_role_correction")
                if not isinstance(correction, dict) or correction.get("role_correction_is_explicit_and_not_silent") is not True:
                    fail(f"{physical} lacks explicit Root1330 request-to-receipt correction")
        return {"status": "PASS", "mode": "readiness", "counts": readiness["observed_counts"], "pending": readiness["missing_physical_case_ids"], "negative_contract_tests": negative_tests}
    finally:
        shutil.rmtree(temp, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate fresh195 metadata builder and current readiness boundary.")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--current-index", type=Path, required=True)
    parser.add_argument("--membership", type=Path, required=True)
    parser.add_argument("--legacy-catalog", type=Path, required=True)
    parser.add_argument("--package-dir", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--skip-package-manifest", action="store_true")
    args = parser.parse_args()
    package_dir = args.package_dir.resolve()
    if not args.skip_package_manifest:
        validate_package_manifest(package_dir)
    result = validate_current(package_dir, args.checkpoint, args.current_index, args.membership, args.legacy_catalog)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except ValidationError as exc:
        raise SystemExit(f"fresh195 validation failed: {exc}")
