from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("condition_product_queue_v2", HERE / "run_condition_product_queue_v2.py")
assert SPEC and SPEC.loader
QUEUE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(QUEUE)


class ConditionProductQueueV2Tests(unittest.TestCase):
    def _h060_context(self):
        case = "UF_F1_MDBC_DP010_H060"
        paths = QUEUE._case_paths(case)
        owner_info = QUEUE._prepare_owner(case, paths)
        owner = owner_info["record"]
        manifest = QUEUE._load(paths["manifest"], "H060 manifest")
        gates = QUEUE._strict_source_gates(case, paths, owner, manifest)
        return case, paths, owner_info, manifest, gates

    def test_h060_actual_metadata_and_all_source_bindings_are_ready(self) -> None:
        case, paths, owner_info, manifest, gates = self._h060_context()
        metadata = QUEUE._validate_owner_recipe(case, paths, owner_info["record"], manifest)
        self.assertEqual(metadata["recipe"]["initial_depth_m"], 0.6)
        self.assertEqual(metadata["recipe"]["time_out_s"], 0.025)
        self.assertEqual(gates["status"], "ready")
        self.assertEqual({gates[key]["status"] for key in ("gencase", "solver", "native_integrity_receipt", "native_frame_scan_receipt")}, {"completed"})
        for key in ("gencase", "solver", "native_integrity_receipt", "native_frame_scan_receipt"):
            self.assertIn("request_binding", gates[key])
        self.assertEqual({value["status"] for value in gates["native_roots"].values()}, {"ready"})

    def test_future_h052_does_not_create_candidate_before_native_audits(self) -> None:
        plan = QUEUE._build_plan("UF_F1_MDBC_DP010_H052", create_candidate=True)
        self.assertEqual(plan["status"], "blocked_actual_completed_sources")
        self.assertIsNone(plan["direct_candidate"])
        self.assertTrue(any("native_integrity" in blocker for blocker in plan["blockers"]))
        self.assertTrue(any("native_frame_scan" in blocker for blocker in plan["blockers"]))

    def test_wrong_solver_generated_root_is_rejected(self) -> None:
        case, paths, _, manifest, _ = self._h060_context()
        request = QUEUE._load(QUEUE.BASE / "requests" / f"{case}-solver-001.json", "H060 solver request")
        request["generated_prefix"] = str(Path("/tmp/wrong-case-root") / case)
        with self.assertRaisesRegex(QUEUE.QueueError, "generated_prefix"):
            QUEUE._validate_source_request(case, "solver-001", request, paths, manifest)

    def test_changed_converter_v2_binding_is_rejected(self) -> None:
        case, paths, owner_info, _, gates = self._h060_context()
        candidate = QUEUE._load(paths["candidate"], "H060 direct candidate")
        changed = copy.deepcopy(candidate)
        changed["input_file_bindings"][str(QUEUE.CONVERTER_V2)]["sha256"] = "0" * 64
        with self.assertRaisesRegex(QUEUE.QueueError, "converter v2 binding"):
            QUEUE._validate_candidate_v2(changed, case, paths, gates, owner_info["binding"])

    def test_old_timeout_in_owner_recipe_is_rejected(self) -> None:
        case, paths, owner_info, manifest, _ = self._h060_context()
        changed_owner = copy.deepcopy(owner_info["record"])
        changed_owner["numerical_output_recipe"]["time_out_s"] = 0.01
        with self.assertRaisesRegex(QUEUE.QueueError, "numerical_output_recipe"):
            QUEUE._validate_owner_recipe(case, paths, changed_owner, manifest)

    def test_missing_source_request_hash_is_rejected(self) -> None:
        case = "UF_F1_MDBC_DP010_H060"
        attempt = "solver-001"
        with tempfile.TemporaryDirectory(prefix="m4-v2-receipt-") as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(json.dumps({
                "schema": QUEUE.REQUEST_SCHEMA,
                "family_id": "F1",
                "case_id": case,
                "attempt_id": attempt,
            }), encoding="utf-8")
            receipt = {
                "schema": QUEUE.RECEIPT_SCHEMA,
                "status": "completed",
                "returncode": 0,
                "request": {"case_id": case, "attempt_id": attempt},
            }
            with self.assertRaisesRegex(QUEUE.QueueError, "request_sha256"):
                QUEUE._assert_source_receipt_request_binding(receipt, request_path, case, attempt)

    def test_fresh_plan_prefix_does_not_select_consumed_v1_plan(self) -> None:
        path = QUEUE._fresh_plan_path("UF_F1_MDBC_DP010_H060")
        self.assertIn("product-queue-v2-", path.name)
        self.assertNotIn("product-queue-004", path.name)
        self.assertTrue(path.is_relative_to(QUEUE.PREP))


if __name__ == "__main__":
    unittest.main()
