from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in __import__("sys").path:
    __import__("sys").path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_verify_generic_native_join_v5 as subject


ROOT = SCRIPT_DIR.parent / "campaigns/ds-data-02/stage2"
OVERLAY = ROOT / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
PLAN = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT296_V4.json"
CURRENT = ROOT / "CURRENT336.json"
ROOT317_MANIFEST = ROOT / "requests/generic-native-extract-v3-root317-f2-root198-missing-join-prepared-002/generic-native-extract-v3-manifest.json"


class GenericNativeJoinV5Tests(unittest.TestCase):
    def test_real_v10_current_plan_separates_arithmetic_and_canonical_scope(self) -> None:
        scope, _ = subject._load_scope_v5(OVERLAY, PLAN, CURRENT)
        self.assertEqual(scope["derived_inventory"], {
            "physical_cases": 118,
            "bound": 94,
            "unresolved": 24,
            "existing": 47,
            "arithmetic_cause_bound_missing": 47,
            "canonical_cause_bound_missing": 46,
            "aliases": 1,
            "actual_join_proof_files": 12,
        })
        self.assertEqual(len(scope["selected"]), 70)
        self.assertEqual(scope["current336"]["case_count"], 336)
        self.assertEqual(scope["current336"]["alias_ids"], ["F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"])
        self.assertNotIn("F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090", scope["selected"])

    def test_real_root297_plan_keeps_same_hash_bound_alias_partition(self) -> None:
        plan = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT297_V4.json"
        scope, _ = subject._load_scope_v5(OVERLAY, plan, CURRENT)
        self.assertEqual(scope["derived_inventory"]["actual_join_proof_files"], 12)
        self.assertEqual(scope["derived_inventory"]["arithmetic_cause_bound_missing"], 47)
        self.assertEqual(scope["derived_inventory"]["canonical_cause_bound_missing"], 46)
        self.assertEqual(scope["current336"]["alias_ids"], ["F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"])

    def test_real_root317_contract_edges_bind_to_producer_rows(self) -> None:
        scope, _ = subject._load_scope_v5(OVERLAY, PLAN, CURRENT)
        manifest, _, contracts = subject._load_worker_manifest_v5(ROOT317_MANIFEST, scope)
        self.assertEqual(manifest["_v3_family"], "F2")
        self.assertEqual(len(contracts), 8)
        for entry in contracts.values():
            row = entry["v5_proof_row"]
            typed = entry["document"]["typed_deferred"]
            self.assertEqual(Path(row["summary"]).resolve(), Path(typed["summary"]["path"]).resolve())
            self.assertEqual(row["summary_sha256"], typed["summary"]["sha256"])
            self.assertEqual(row["records_stat_only"]["sha256"], typed["records"]["sha256"])
            self.assertEqual(row["records_stat_only"]["rows"], typed["records"]["rows"])

    def test_contract_can_not_repoint_typed_summary_while_updating_own_hash(self) -> None:
        scope, _ = subject._load_scope_v5(OVERLAY, PLAN, CURRENT)
        manifest_value = json.loads(ROOT317_MANIFEST.read_text(encoding="utf-8"))
        source_contract = Path(manifest_value["contracts"][0]["path"])
        contract_value = json.loads(source_contract.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            bad_contract = root / "repointed-contract.json"
            contract_value["typed_deferred"]["summary"] = {
                "path": str(bad_contract.resolve()),
                "sha256": hashlib.sha256(source_contract.read_bytes()).hexdigest(),
                "bytes": source_contract.stat().st_size,
            }
            bad_contract.write_text(json.dumps(contract_value, sort_keys=True) + "\n", encoding="utf-8")
            edge = manifest_value["contracts"][0]
            edge["path"] = str(bad_contract.resolve())
            edge["bytes"] = bad_contract.stat().st_size
            edge["sha256"] = hashlib.sha256(bad_contract.read_bytes()).hexdigest()
            bad_manifest = root / "bad-manifest.json"
            bad_manifest.write_text(json.dumps(manifest_value, sort_keys=True) + "\n", encoding="utf-8")
            with self.assertRaises(subject.GenericJoinV5Error):
                subject._load_worker_manifest_v5(bad_manifest, scope)

    def test_root312_full_eight_case_proof_keeps_selected_subset_and_edges(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            summary = root / "summary.json"
            summary.write_text(json.dumps({"schema": "ds02.stage2.typed-lifecycle-sidecar.v4", "physical_case_id": "full-0"}) + "\n", encoding="utf-8")
            records = root / "records.jsonl"
            records.write_text('{"record_fields":"one row per static (Zone, Idp); saved-frame lifecycle only"}\n', encoding="utf-8")
            def ref(path: Path, *, rows: int | None = None) -> dict[str, object]:
                raw = path.read_bytes(); st = path.stat()
                value = {"path": str(path.resolve()), "bytes": st.st_size, "mtime_ns": st.st_mtime_ns, "ctime_ns": st.st_ctime_ns, "st_dev": st.st_dev, "st_ino": st.st_ino, "sha256": hashlib.sha256(raw).hexdigest()}
                if rows is not None: value["rows"] = rows
                return value
            summary_ref = ref(summary)
            records_ref = ref(records, rows=1)
            case_contract = root / "case.json"
            case_contract.write_text(json.dumps({"schema": "ds02.stage2.generic-native-extract-contract.v1", "physical_case_id": "full-0", "family_id": "F4", "typed_deferred": {"summary": summary_ref, "records": records_ref}, "native_deferred": {}}, sort_keys=True) + "\n", encoding="utf-8")
            contract_ref = ref(case_contract)
            full_ids = [f"full-{i}" for i in range(8)]
            proof = root / "root296-proof.json"
            proof_rows = [{"physical_case_id": case_id} for case_id in full_ids]
            proof_rows[0].update({"summary": str(summary.resolve()), "summary_sha256": summary_ref["sha256"], "records_stat_only": records_ref})
            proof.write_text(json.dumps({"schema": subject.PROOF_SCHEMA, "status": "VERIFIED_ACTUAL_ROOT296_EIGHT_CASES", "case_verifications": proof_rows}, sort_keys=True) + "\n", encoding="utf-8")
            proof_ref = ref(proof)
            manifest = root / "root312.json"
            manifest.write_text(json.dumps({"schema": subject.ROOT312_MANIFEST_SCHEMA, "status": "READY_PARENT_GUARDED_ROOT312_F4_NATIVE_EXTRACT", "family_id": "F4", "physical_case_ids": ["full-0"], "contracts": [{"physical_case_id": "full-0", **contract_ref}], "proof_bundles": [{"bundle_id": "ROOT296", "producer_proof": proof_ref, "full_case_count": 8, "full_case_ids": full_ids, "selected_case_ids": ["full-0"], "producer_proof_preserved": True}], "claim_boundary": {"physical_fate": "UNKNOWN", "legal_flux": "UNKNOWN", "dynamics": "UNKNOWN", "QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}}, sort_keys=True) + "\n", encoding="utf-8")
            scope = {"selected": {"full-0"}, "existing": set(), "aliases": set()}
            loaded, _, contracts = subject._load_worker_manifest_v5(manifest, scope)
            self.assertEqual(loaded["_v3_normalized_bundles"][0]["proof_ids"], full_ids)
            self.assertEqual(loaded["_v3_normalized_bundles"][0]["selected_case_ids"], ["full-0"])
            self.assertEqual(contracts["full-0"]["v5_proof_row"]["records_stat_only"]["rows"], 1)


if __name__ == "__main__":
    unittest.main()
