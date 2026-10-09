from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_verify_generic_native_join_v4 as subject


RUNPARTS_COLUMNS = (
    "Part", "TimeStep [s]", "Steps", "DTsMin", "PartRuntime [s]", "NpSave", "NpSim", "NpNew", "NpOut", "NctSim",
    "NpAlloc [X]", "NctAlloc [X]", "SimRuntime [s]", "NpbSim", "NpfSim", "NpNormal", "NpOutPos", "NpOutRho",
    "NpOutMov", "DtMin [s]", "DtMax [s]", "MemCPU [MiB]", "MemGPU [MiB]", "MemGPU_Cells [MiB]", "NpAlloc", "NctAlloc",
)


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    st = path.stat()
    return {"path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "sha256": hashlib.sha256(raw).hexdigest()}


def make_fixture(root: Path, *, failed: bool = False, tamper_position: bool = False) -> dict[str, Path]:
    root.mkdir(parents=True, exist_ok=True)
    case_id = "F4_V4_TINY_CASE"
    typed = root / "deferred" / "typed.jsonl"
    typed.parent.mkdir()
    typed.write_text('{"schema":"ds02.stage2.typed-lifecycle-record.v4","record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n{"zone":0,"idp":1,"initial_role":"fluid","initial_type_code":3,"initial_mass_kg":0.125}\n', encoding="utf-8")
    typed_ref = {**ref(typed), "rows": 1, "deferred": True, "content_opened_by_preparer": False, "read_after_parent_reservation": True}

    summary = root / "summary.json"
    write_json(summary, {"schema": "ds02.stage2.typed-lifecycle-sidecar.v4", "physical_case_id": case_id, "timeline": {"time_s": [0.2, 0.3]}, "role_ledgers": {"fluid": {"first_disappearance_count": 1}}})
    summary_ref = ref(summary)

    data_dir = root / "native-data"
    data_dir.mkdir()
    obi4 = data_dir / "PartOut_000.obi4"
    obi4.write_bytes(b"deferred-native")
    obi4_ref = {**ref(obi4), "deferred": True, "read_after_parent_reservation": True}
    csv_path = root / "PartOut.csv"
    csv_path.write_text("Pos.x [m],Pos.y [m],Pos.z [m],PartOut,Motive,Idp,Vel.x [m/s],Vel.y [m/s],Vel.z [m/s],Rhop [kg/m^3]\n1.0,2.0,3.0,1,1,1,0,0,0,1000.0\n", encoding="utf-8")
    csv_ref = ref(csv_path)
    runparts = root / "RunPARTs.csv"
    row0 = ["0", "0.2", "1", "0.01", "0", "1", "1", "0", "0", "1", "1.0", "1.0", "0", "1", "1", "1", "0", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    row1 = ["1", "0.3", "2", "0.01", "0", "1", "1", "0", "1", "1", "1.0", "1.0", "0", "1", "1", "1", "1", "0", "0", "0.01", "0.02", "1", "0", "0", "1", "1"]
    runparts.write_text(";".join(RUNPARTS_COLUMNS) + "\n" + ";".join(row0) + "\n" + ";".join(row1) + "\n", encoding="utf-8")
    runparts_ref = ref(runparts)
    tool = root / "PartVTKOut_linux64"
    tool.write_bytes(b"tiny-official-decoder")
    tool_ref = ref(tool)

    contract = root / "contract.json"
    contract_value = {
        "schema": "ds02.stage2.generic-native-extract-contract.v1", "status": "READY_PARENT_GUARDED_NATIVE_EXTRACT", "physical_case_id": case_id, "family_id": "F4",
        "typed_deferred": {"summary": summary_ref, "records": typed_ref},
        "native_deferred": {"data_dir": {"path": str(data_dir.resolve())}, "partout_obi4": obi4_ref, "runparts_csv": runparts_ref},
    }
    write_json(contract, contract_value)
    contract_ref = ref(contract)

    case_report = root / "case-report.json"
    resume = root / "resume.csv"
    position = [9.0, 2.0, 3.0] if tamper_position else [1.0, 2.0, 3.0]
    case_value = {
        "schema": subject.WORKER_CASE_SCHEMA, "status": "COMPLETED_GENERIC_NATIVE_TYPED_SAVED_BRACKET_DIAGNOSTIC_ONLY", "physical_case_id": case_id, "family_id": "F4",
        "typed": {"pre_stat": {k: typed_ref[k] for k in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}, "post_stat": {k: typed_ref[k] for k in ("path", "bytes", "mtime_ns", "ctime_ns", "st_dev", "st_ino")}, "sha256": typed_ref["sha256"], "rows": 1, "target_count": 1},
        "native": {
            "official_tool": {"path": str(tool.resolve()), "sha256": tool_ref["sha256"], "command": [str(tool.resolve()), "-dirdata", str(data_dir.resolve()), "-savecsv", str(csv_path.resolve()), "-saveresume", str(resume.resolve()), "-createdirs:1", "-csvsep:1"]},
            "partout_obi4": {"pre_stat": obi4_ref, "post_stat": obi4_ref, "pre_sha256": obi4_ref["sha256"], "post_sha256": obi4_ref["sha256"]},
            "partout_csv": {"pre_stat": csv_ref, "post_stat": csv_ref, "sha256": csv_ref["sha256"]},
            "runparts": {"pre_stat": runparts_ref, "post_stat": runparts_ref, "sha256": runparts_ref["sha256"]},
        },
        "counts": {"typed_targets": 1, "native_rows": 1, "joined": 1},
        "rows": [{"identity_key": [0, 1], "zone": 0, "idp": 1, "first_missing_frame": 1, "first_missing_time_s": 0.3, "bracket_s": [0.2, 0.3], "motive_code": 1, "part_out": 1, "position_m": position, "density_kg_m3": 1000.0}],
    }
    write_json(case_report, case_value)

    proof = root / "old-single-proof.json"
    write_json(proof, {"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_OLD_SINGLE_CASE_NO_PHYSICAL_CREDIT", "physical_case_id": case_id})
    proof_ref = ref(proof)
    manifest = root / "manifest.json"
    manifest_value = {
        "schema": subject.ROOT312_MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT", "family_id": "F4", "physical_case_ids": [case_id],
        "contracts": [{"physical_case_id": case_id, **contract_ref}],
        "proof_bundles": [{"bundle_id": "ROOT296", "producer_proof": proof_ref, "full_case_count": 1, "full_case_ids": [case_id], "selected_case_ids": [case_id], "producer_proof_preserved": True}],
        "official_sources": {"partvtkout": tool_ref},
        "source_refs": [tool_ref, proof_ref, contract_ref, summary_ref],
        "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"},
    }
    write_json(manifest, manifest_value)
    manifest_ref = ref(manifest)
    worker = root / "worker.py"
    worker.write_text("# tiny immutable worker\n", encoding="utf-8")
    request = root / "request.json"
    static = [manifest, contract, proof, summary, tool]
    write_json(request, {"schema": subject.REQUEST_SCHEMA, "family_id": "F4", "physical_case_ids": [case_id], "manifest_contract": {"path": str(manifest.resolve()), "sha256": manifest_ref["sha256"]}, "command": [sys.executable, str(worker), "audit", "--manifest", str(manifest.resolve()), "--output", "{attempt_root}/report.json"], "input_files": [str(path.resolve()) for path in static], "input_sha256": {str(path.resolve()): ref(path)["sha256"] for path in static}, "deferred_input_files": [str(typed.resolve()), str(obi4.resolve())], "official_sources": {"partvtkout": tool_ref}})
    batch = root / "batch-report.json"
    if failed:
        write_json(batch, {"schema": subject.WORKER_REPORT_SCHEMA, "status": "COMPLETED_WITH_CASE_FAILURES", "family_id": "F4", "case_results": [{"physical_case_id": case_id, "status": "FAILED", "error_type": "SyntheticFailure", "error_message": "controlled fixture failure", "saved_mask_credit": False}], "counts": {"requested": 1, "completed": 0, "failed": 1}, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})
    else:
        write_json(batch, {"schema": subject.WORKER_REPORT_SCHEMA, "status": "COMPLETED_ALL_CASES", "family_id": "F4", "case_results": [{"physical_case_id": case_id, "status": "COMPLETED", "output": str(case_report.resolve()), "joined": 1}], "counts": {"requested": 1, "completed": 1, "failed": 0}, "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"})

    scope = root / "scope.json"
    old_scope_proof = root / "existing-proof.json"
    write_json(old_scope_proof, {"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_EXISTING", "physical_case_id": "old-existing"})
    write_json(scope, {"schema": subject.OVERLAY_SCHEMA, "status": "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS", "base_scope": {"path": str(scope.resolve()), "sha256": "0" * 64}, "physical_case_count": 2, "newly_bound_cases": [{"physical_case_id": "old-existing", "classification": "NATIVE_CAUSE_BOUND_PER_FLUID_ID"}], "remaining_cause_not_located_case_ids": [case_id], "actual_typed_native_saved_frame_join_physical_cases": 0, "actual_join_proofs": [], "qualification_boundary": {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN", "physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN"}})
    # The verifier tests use a direct V3 scope for this isolated case; the
    # production rolling-overlay test below covers the real V10 derivation.
    return {"manifest": manifest, "request": request, "batch": batch, "case": case_report, "typed": typed, "scope": scope}


class GenericNativeJoinV4Tests(unittest.TestCase):
    def test_real_v10_derives_cause_bound_missing_without_guessing_ids(self) -> None:
        overlay = Path(__file__).resolve().parents[1] / "campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
        scope, _ = subject._load_scope_v4(overlay)
        self.assertEqual(scope["derived_inventory"], {"physical_cases": 118, "bound": 94, "unresolved": 24, "existing": 47, "cause_bound_missing": 47, "aliases": 0})
        self.assertEqual(len(scope["selected"]), 71)
        self.assertNotIn("F2H10V2_OFFSET_V1", scope["selected"])

    def test_root317_manifest_is_inside_real_v10_canonical_selected_scope(self) -> None:
        root = Path(__file__).resolve().parents[1]
        overlay = root / "campaigns/ds-data-02/stage2/checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
        manifest = root / "campaigns/ds-data-02/stage2/requests/generic-native-extract-v3-root317-f2-root198-missing-join-prepared-002/generic-native-extract-v3-manifest.json"
        scope, _ = subject._load_scope_v4(overlay)
        loaded, _, contracts = subject.v3._load_worker_manifest_v3(manifest, scope)
        self.assertEqual(loaded["_v3_family"], "F2")
        self.assertEqual(len(contracts), 8)

    def test_count_only_summary_and_decoder_csv_pass(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td))
            # Build a direct V3 scope containing the old single-case proof and
            # the selected case; no production overlay is involved here.
            scope = Path(td) / "direct-scope.json"
            old = Path(td) / "existing-proof.json"
            write_json(old, {"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_EXISTING", "physical_case_id": "old-existing"})
            old_ref = ref(old)
            write_json(scope, {"schema": subject.SCOPE_SCHEMA, "case_scope": {"selected_case_ids": ["F4_V4_TINY_CASE"], "existing_join_case_ids": ["old-existing"], "unresolved_alias_case_ids": [], "selected_canonical_count": 1, "existing_exact_join_count": 1}, "producer_case_index": {"F4_V4_TINY_CASE": 0}, "actual_join_proofs": [old_ref]})
            out = Path(td) / "verification.json"
            value = subject.verify(scope, paths["manifest"], paths["request"], paths["batch"])
            subject._atomic(out, value)
            self.assertEqual(value["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertTrue(value["case_verifications"][0]["summary_first_missing_identity_rows"] is False)

    def test_partial_failed_case_has_no_join_credit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td), failed=True)
            scope = Path(td) / "direct-scope.json"
            old = Path(td) / "existing-proof.json"
            write_json(old, {"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_EXISTING", "physical_case_id": "old-existing"})
            old_ref = ref(old)
            write_json(scope, {"schema": subject.SCOPE_SCHEMA, "case_scope": {"selected_case_ids": ["F4_V4_TINY_CASE"], "existing_join_case_ids": ["old-existing"], "unresolved_alias_case_ids": [], "selected_canonical_count": 1, "existing_exact_join_count": 1}, "producer_case_index": {"F4_V4_TINY_CASE": 0}, "actual_join_proofs": [old_ref]})
            value = subject.verify(scope, paths["manifest"], paths["request"], paths["batch"])
            self.assertEqual(value["counts"]["worker_failed"], 1)
            self.assertEqual(value["failures"][0]["status"], "FAILED_NO_JOIN_CREDIT")

    def test_position_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            paths = make_fixture(Path(td), tamper_position=True)
            scope = Path(td) / "direct-scope.json"
            old = Path(td) / "existing-proof.json"
            write_json(old, {"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_EXISTING", "physical_case_id": "old-existing"})
            old_ref = ref(old)
            write_json(scope, {"schema": subject.SCOPE_SCHEMA, "case_scope": {"selected_case_ids": ["F4_V4_TINY_CASE"], "existing_join_case_ids": ["old-existing"], "unresolved_alias_case_ids": [], "selected_canonical_count": 1, "existing_exact_join_count": 1}, "producer_case_index": {"F4_V4_TINY_CASE": 0}, "actual_join_proofs": [old_ref]})
            with self.assertRaises(subject.GenericJoinV4Error):
                subject.verify(scope, paths["manifest"], paths["request"], paths["batch"])


if __name__ == "__main__":
    unittest.main()
