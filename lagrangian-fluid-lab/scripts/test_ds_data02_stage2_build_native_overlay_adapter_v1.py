"""Small source-only tests for the native overlay adapter.

These tests exercise the later admission boundary with a monkeypatched V5
verifier; they do not open a production payload.  The genuine worker-to-V5
shape is covered by ``test_ds_data02_stage2_verify_generic_native_join_v5_worker_fixture.py``.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from types import SimpleNamespace

SCRIPT_DIR = Path(__file__).resolve().parent
import sys
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
import ds_data02_stage2_build_native_overlay_adapter_v1 as subject


def _ref(path: Path) -> dict[str, object]:
    raw = path.read_bytes()
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "ctime_ns": stat.st_ctime_ns,
        "st_dev": stat.st_dev,
        "st_ino": stat.st_ino,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


class NativeOverlayAdapterTests(unittest.TestCase):
    def _adapter(self, root: Path) -> tuple[Path, Path]:
        for name in ("scope.json", "plan.json", "current.json", "report.json"):
            (root / name).write_text("{}\n", encoding="utf-8")
        contract = {
            "source_id": "ROOT-TINY",
            "family_id": "F4",
            "physical_case_ids": ["F4_TINY_CASE"],
            "manifest": _ref(root / "scope.json"),
            "request": _ref(root / "plan.json"),
            "contracts": [],
        }
        adapter = {
            "schema": subject.ADAPTER_SCHEMA,
            "status": "READY_WAITING_FOR_GUARDED_WORKER_REPORTS",
            "base_scope": _ref(root / "scope.json"),
            "lifecycle_plan": _ref(root / "plan.json"),
            "current_catalog": _ref(root / "current.json"),
            "source_batches": [contract],
            "physical_case_count": 118,
            "selected_case_count": 1,
            "selected_case_ids": ["F4_TINY_CASE"],
            "existing_join_case_count_before_adapter": 47,
            "alias_case_ids_excluded": ["F2_ALIAS"],
        }
        adapter_path = root / "adapter.json"
        adapter_path.write_text(json.dumps(adapter, sort_keys=True) + "\n", encoding="utf-8")
        result_map = {"results": [{"source_id": "ROOT-TINY", "report": _ref(root / "report.json")}]}
        result_map_path = root / "result-map.json"
        result_map_path.write_text(json.dumps(result_map, sort_keys=True) + "\n", encoding="utf-8")
        return adapter_path, result_map_path

    def test_admit_emits_join_only_and_no_cause_credit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter, result_map = self._adapter(root)
            original = subject.v5.verify

            def fake_verify(*_args, **_kwargs):
                return {
                    "case_verifications": [{"physical_case_id": "F4_TINY_CASE", "joined_identity_count": 2}],
                    "failures": [],
                }

            subject.v5.verify = fake_verify
            try:
                value = subject._admit(SimpleNamespace(adapter=adapter, result_map=result_map, output_dir=root / "out"))
            finally:
                subject.v5.verify = original
            self.assertEqual(value["verified_join_case_count"], 1)
            self.assertEqual(value["native_cause_credit_case_count"], 0)
            output = json.loads(Path(value["output"]["path"]).read_text())
            self.assertEqual(output["pending_source_ids"], [])
            self.assertEqual(output["new_typed_native_join_cases"][0]["native_cause_credit"], "NONE")
            self.assertEqual(output["claim_boundary"]["physical_fate"], "UNKNOWN")

    def test_admit_rejects_duplicate_source_result(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            adapter, result_map = self._adapter(root)
            value = json.loads(result_map.read_text())
            value["results"].append(value["results"][0])
            result_map.write_text(json.dumps(value) + "\n")
            original = subject.v5.verify
            subject.v5.verify = lambda *_args, **_kwargs: {"case_verifications": [], "failures": []}
            try:
                with self.assertRaises(subject.AdapterError):
                    subject._admit(SimpleNamespace(adapter=adapter, result_map=result_map, output_dir=root / "out"))
            finally:
                subject.v5.verify = original


if __name__ == "__main__":
    unittest.main(verbosity=2)
