"""Tiny end-to-end V5 worker-output fixture.

The fixture uses the ROOT312 production shape: proof_bundles[].producer_proof
points to a complete 8-row producer proof, while one selected contract is
consumed. A second copy switches the bundle edge to proof. All files are
temporary tiny fixtures; no production payload is opened.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_stage2_verify_generic_native_join_v5 as subject


def _ref(path: Path, *, rows: int | None = None) -> dict[str, object]:
    raw = path.read_bytes() if path.is_file() else b""
    st = path.stat()
    result: dict[str, object] = {
        "path": str(path.resolve()),
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    if rows is not None:
        result["rows"] = rows
    return result


class V5WorkerFixtureTests(unittest.TestCase):
    def _make_fixture(self, root: Path, *, bundle_edge: str) -> tuple[Path, Path, Path, dict[str, object]]:
        case_id = "F4_TINY_ROOT312_CASE_000"
        full_ids = [case_id] + [f"F4_TINY_ROOT312_DIAGNOSTIC_{i:03d}" for i in range(7)]

        summary_path = root / "typed-summary.json"
        summary_path.write_text(json.dumps({
            "schema": "ds02.stage2.typed-lifecycle-sidecar.v4",
            "physical_case_id": case_id,
            "timeline": {"time_s": [0.0, 1.0]},
            "role_ledgers": {"fluid": {"first_disappearance_count": 1}},
        }) + "\n", encoding="utf-8")
        records_path = root / "typed-records.jsonl"
        records_path.write_text('{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n', encoding="utf-8")
        case_manifest_path = root / "case-manifest.json"
        case_manifest_path.write_text(json.dumps({"physical_case_id": case_id}) + "\n", encoding="utf-8")
        receipt_path = root / "case-receipt.json"
        receipt_path.write_text(json.dumps({"status": "COMPLETED", "returncode": 0}) + "\n", encoding="utf-8")

        data_dir = root / "native-data"
        data_dir.mkdir()
        obi4_path = data_dir / "PartOut_000.obi4"
        obi4_path.write_bytes(b"tiny-obi4-fixture\n")
        partout_path = root / "PartOut.csv"
        partout_path.write_text(
            "Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Zone,Rhop [kg/m^3]\n"
            "0.1,0.2,0.3,1,1,1,0,1000.0\n", encoding="utf-8")
        runparts_path = root / "RunPARTs.csv"
        runparts_path.write_text(
            "Part,TimeStep [s],Steps,NpOut\n0,0.0,0,0\n1,1.0,1,0\n", encoding="utf-8")
        tool_path = root / "PartVTKOut_fixture"
        tool_path.write_bytes(b"#!/bin/sh\nexit 0\n")
        tool_path.chmod(0o755)
        resume_path = root / "resume.xml"

        summary_ref = _ref(summary_path)
        records_ref = _ref(records_path, rows=1)
        case_manifest_ref = _ref(case_manifest_path)
        receipt_ref = _ref(receipt_path)
        obi4_ref = _ref(obi4_path)
        partout_ref = _ref(partout_path)
        runparts_ref = _ref(runparts_path)
        tool_ref = _ref(tool_path)
        data_dir_ref = _ref(data_dir)

        contract = {
            "schema": "ds02.stage2.generic-native-extract-contract.v1",
            "physical_case_id": case_id,
            "family_id": "F4",
            "native_deferred": {
                "data_dir": data_dir_ref,
                "partout_obi4": {**obi4_ref, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True},
            },
            "typed_deferred": {
                "summary": summary_ref,
                "records": {**records_ref, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True},
            },
        }
        contract_path = root / "case-contract.json"
        contract_path.write_text(json.dumps(contract, sort_keys=True) + "\n", encoding="utf-8")
        contract_ref = _ref(contract_path)

        proof_row = {
            "physical_case_id": case_id,
            "summary": str(summary_path.resolve()),
            "summary_sha256": summary_ref["sha256"],
            "records_stat_only": records_ref,
            "case_manifest": str(case_manifest_path.resolve()),
            "case_manifest_sha256": case_manifest_ref["sha256"],
            "receipt": str(receipt_path.resolve()),
            "receipt_sha256": receipt_ref["sha256"],
        }
        proof_path = root / "producer-proof.json"
        proof_path.write_text(json.dumps({
            "schema": subject.PROOF_SCHEMA,
            "status": "VERIFIED_ACTUAL_F4_TYPED_LIFECYCLE_BATCH_SAVED_MASK_DIAGNOSTICS_NO_PHYSICAL_CREDIT",
            "counts": {"cases_requested": 8, "completed": 8, "failed": 0},
            "case_verifications": [proof_row] + [{"physical_case_id": item} for item in full_ids[1:]],
        }, sort_keys=True) + "\n", encoding="utf-8")
        proof_ref = _ref(proof_path)

        manifest = {
            "schema": subject.ROOT312_MANIFEST_SCHEMA,
            "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT",
            "family_id": "F4",
            "physical_case_ids": [case_id],
            "contracts": [{"physical_case_id": case_id, **contract_ref}],
            "proof_bundles": [{
                "bundle_id": "ROOT296",
                bundle_edge: proof_ref,
                "full_case_count": 8,
                "full_case_ids": full_ids,
                "selected_case_ids": [case_id],
                "producer_proof_preserved": True,
            }],
            "official_sources": {"partvtkout": tool_ref},
            "claim_boundary": {
                "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN",
                "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            },
        }
        manifest_path = root / f"manifest-{bundle_edge}.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

        request = {
            "schema": subject.REQUEST_SCHEMA,
            "family_id": "F4",
            "physical_case_ids": [case_id],
            "manifest_contract": {"path": str(manifest_path.resolve()), "sha256": _ref(manifest_path)["sha256"]},
            "command": ["python3", "tiny-worker.py", "audit", "--manifest", str(manifest_path.resolve())],
            "input_files": [str(manifest_path.resolve()), str(contract_path.resolve()), str(proof_path.resolve()), str(tool_path.resolve())],
            "input_sha256": {
                str(manifest_path.resolve()): _ref(manifest_path)["sha256"],
                str(contract_path.resolve()): contract_ref["sha256"],
                str(proof_path.resolve()): proof_ref["sha256"],
                str(tool_path.resolve()): tool_ref["sha256"],
            },
            "deferred_input_files": [str(records_path.resolve()), str(obi4_path.resolve()), str(partout_path.resolve()), str(runparts_path.resolve())],
            "official_sources": {"partvtkout": tool_ref},
        }
        request_path = root / f"request-{bundle_edge}.json"
        request_path.write_text(json.dumps(request, sort_keys=True) + "\n", encoding="utf-8")

        command = [
            str(tool_path.resolve()), "-dirdata", str(data_dir.resolve()),
            "-savecsv", str(partout_path.resolve()), "-saveresume", str(resume_path.resolve()),
            "-createdirs:1", "-csvsep:1",
        ]
        case_output = root / f"case-output-{bundle_edge}.json"
        case_output.write_text(json.dumps({
            "schema": subject.v3.WORKER_CASE_SCHEMA,
            "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY",
            "physical_case_id": case_id,
            "family_id": "F4",
            "counts": {"joined": 1, "typed_targets": 1, "native_rows": 1},
            "rows": [{
                "zone": 0, "idp": 1, "motive_code": 1, "part_out": 1,
                "first_missing_frame": 1, "first_missing_time_s": 1.0,
                "bracket_s": [0.0, 1.0], "position_m": [0.1, 0.2, 0.3],
                "density_kg_m3": 1000.0,
            }],
            "typed": {
                "summary": summary_ref, "sha256": records_ref["sha256"],
                "rows": 1, "target_count": 1, "pre_stat": records_ref, "post_stat": records_ref,
            },
            "native": {
                "official_tool": {"path": str(tool_path.resolve()), "sha256": tool_ref["sha256"], "command": command},
                "partout_obi4": {"pre_stat": obi4_ref, "post_stat": obi4_ref, "pre_sha256": obi4_ref["sha256"], "post_sha256": obi4_ref["sha256"], "sha256": obi4_ref["sha256"]},
                "partout_csv": {"pre_stat": partout_ref, "post_stat": partout_ref, "sha256": partout_ref["sha256"]},
                "runparts": {"pre_stat": runparts_ref, "post_stat": runparts_ref, "sha256": runparts_ref["sha256"], "saved_times_s": [0.0, 1.0]},
            },
        }, sort_keys=True) + "\n", encoding="utf-8")

        report_path = root / f"worker-report-{bundle_edge}.json"
        report_path.write_text(json.dumps({
            "schema": subject.WORKER_REPORT_SCHEMA, "status": "COMPLETED_ALL_CASES", "family_id": "F4",
            "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN",
            "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN",
            "case_results": [{"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_output.resolve()), "joined": 1}],
            "counts": {"requested": 1, "completed": 1, "failed": 0},
        }, sort_keys=True) + "\n", encoding="utf-8")

        scope_path = root / "scope.json"
        scope_path.write_text(json.dumps({"schema": "tiny-scope"}) + "\n", encoding="utf-8")
        scope = {
            "selected": {case_id}, "existing": set(), "aliases": set(),
            "actual_join_proof_count": 1, "actual_join_proof_file_count": 1,
            "actual_join_proof_row_count": 0, "actual_join_proof_ids": set(),
            "derived_inventory": {"physical_cases": 1, "bound": 0, "unresolved": 1, "existing": 0, "aliases": 0, "actual_join_proof_files": 1},
            "case_scope": {"existing_exact_join_count": 0},
            "current336": {"ref": {}, "plan": {}, "case_count": 1, "alias_ids": []},
        }
        return manifest_path, request_path, report_path, {"scope": scope, "scope_ref": _ref(scope_path), "case_id": case_id}

    def _verify(self, manifest, request, report, meta):
        original = subject._load_scope_v5
        subject._load_scope_v5 = lambda *_args: (meta["scope"], meta["scope_ref"])
        try:
            return subject.verify(meta["scope_ref"]["path"], manifest, request, report, Path("unused-plan"), Path("unused-current"))
        finally:
            subject._load_scope_v5 = original

    def test_worker_output_verifies_with_producer_proof_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, request, report, meta = self._make_fixture(Path(directory), bundle_edge="producer_proof")
            result = self._verify(manifest, request, report, meta)
            self.assertEqual(result["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(result["counts"]["worker_completed"], 1)
            self.assertEqual(result["counts"]["actual_join_proof_files_checked"], 1)

    def test_worker_output_verifies_with_proof_alias_edge(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest, request, report, meta = self._make_fixture(Path(directory), bundle_edge="proof")
            result = self._verify(manifest, request, report, meta)
            self.assertEqual(result["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")

    def test_failed_case_has_no_join_credit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest, request, report, meta = self._make_fixture(root, bundle_edge="producer_proof")
            value = json.loads(report.read_text())
            value["case_results"][0] = {"physical_case_id": meta["case_id"], "status": "FAILED", "error_type": "FixtureError", "error_message": "guarded decoder failure"}
            value["counts"] = {"requested": 1, "completed": 0, "failed": 1}
            report.write_text(json.dumps(value, sort_keys=True) + "\n")
            result = self._verify(manifest, request, report, meta)
            self.assertEqual(result["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_WITH_CASE_FAILURES")
            self.assertEqual(result["counts"]["worker_failed"], 1)
            self.assertEqual(result["failures"][0]["status"], "FAILED_NO_JOIN_CREDIT")


if __name__ == "__main__":
    unittest.main(verbosity=2)
