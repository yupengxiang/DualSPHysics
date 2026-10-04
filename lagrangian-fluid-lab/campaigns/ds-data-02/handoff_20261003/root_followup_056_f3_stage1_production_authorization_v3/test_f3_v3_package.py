#!/usr/bin/env python3
"""Focused source-only tests for the concrete F3 v3 authorization package."""
from __future__ import annotations

import importlib.util
import ast
import json
from pathlib import Path
import unittest


HERE = Path(__file__).resolve().parent
VALIDATOR_PATH = HERE / "validate_f3_v3_package.py"
TEMPLATES_PATH = HERE / "build_f3_v3_templates.py"
QA_WORKER_PATH = HERE / "f3_v3_postrun_qa_worker_disabled.py"
PROSPECTIVE = (
    "F3_STAGE1_DP006_P1000_AY0320",
    "F3_STAGE1_DP006_P1000_AY0390",
    "F3_STAGE1_DP006_P1000_AY0460",
    "F3_STAGE1_DP006_P1000_AY0570",
    "F3_STAGE1_DP006_P1000_AY0640",
)


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class F3V3PackageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.validator = _module("f3_v3_validator_test", VALIDATOR_PATH)
        cls.templates = _module("f3_v3_templates_test", TEMPLATES_PATH)
        cls.worker = _module("f3_v3_worker_test", QA_WORKER_PATH)

    def test_metadata_and_hash_invariants_cover_frozen_eight(self) -> None:
        result = self.validator.validate_metadata()
        self.assertEqual(
            result,
            {
                "manifest_cases": 8,
                "prospective_cases": 5,
                "observed_cases": 3,
                "status": "metadata_and_hash_invariants_passed",
            },
        )

    def test_authorize_runs_against_actual_evidence_but_stays_fixture_only(self) -> None:
        result = self.templates.authorize_actual_preflight(PROSPECTIVE[0])
        self.assertEqual(result["status"], "preflight_authorize_passed_actual_evidence")
        self.assertTrue(result["fixture_only"])
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["q_n"], "not_granted")
        self.assertTrue(result["prospective_domain_launch"])
        self.assertGreater(result["hash_count"], 0)

    def test_request_templates_preserve_explicit_launch_boundary(self) -> None:
        for case_id in PROSPECTIVE:
            request = json.loads((HERE / "requests" / f"{case_id}.json").read_text())
            self.assertFalse(request["launch_allowed"])
            self.assertEqual(request["production_approval"], "none")
            self.assertEqual(request["complete_event_window_s"], [0.0, 8.35])
            self.assertEqual(request["command"][-2:], ["-tmax:8.35", "-tout:0.01"])
            self.assertEqual(request["command"][1], "-mdbc_noslip:1")
            immutable_paths = set(request["input_sha256"])
            self.assertTrue(any(path.endswith("ds_data02_stage1_production_v2.py") for path in immutable_paths))
            self.assertTrue(any(path.endswith("ds_data02_strict_dispatch_v1.py") for path in immutable_paths))
            self.assertTrue(any(path.endswith("ds_data02_runtime_v2.py") for path in immutable_paths))
            self.assertFalse(any(path.endswith("F3_V3_AUTHORIZE_PREFLIGHT_INDEX.fixture.json") for path in immutable_paths))

    def test_disabled_postrun_worker_does_not_certify_initial_metadata(self) -> None:
        self.assertFalse(self.worker.ENABLED)
        result = self.worker.checklist(PROSPECTIVE[0])
        self.assertFalse(result["enabled"])
        self.assertFalse(result["execution_allowed"])
        self.assertFalse(result["production_scope_approval"])
        self.assertTrue(result["initial_metadata_only"])
        self.assertTrue(result["unknown_loss_preserved"])
        self.assertFalse(result["all_required_evidence_supplied"])
        self.assertFalse(result["approval_created"])

    def test_source_only_scripts_contain_no_process_launch_primitive(self) -> None:
        for path in (HERE / "build_f3_v3_package.py", TEMPLATES_PATH, VALIDATOR_PATH, QA_WORKER_PATH):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name == "subprocess" for alias in node.names), path.name)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, "subprocess", path.name)
                if isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Attribute):
                        self.assertFalse(
                            isinstance(node.func.value, ast.Name)
                            and node.func.value.id in {"os", "subprocess"}
                            and node.func.attr in {"system", "popen", "run", "Popen"},
                            f"process call in {path.name}",
                        )
                    if isinstance(node.func, ast.Name):
                        self.assertNotEqual(node.func.id, "Popen", path.name)


if __name__ == "__main__":
    unittest.main()
