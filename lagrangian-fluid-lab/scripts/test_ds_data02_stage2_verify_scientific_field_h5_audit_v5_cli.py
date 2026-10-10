#!/usr/bin/env python3
"""V5 bounded-source admission tests using the real V3 worker CLI."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
V4_TEST_SPEC = importlib.util.spec_from_file_location(
    "v4_fixture_helpers",
    HERE / "test_ds_data02_stage2_verify_scientific_field_h5_audit_v4_cli.py",
)
assert V4_TEST_SPEC and V4_TEST_SPEC.loader
V4_TEST = importlib.util.module_from_spec(V4_TEST_SPEC)
V4_TEST_SPEC.loader.exec_module(V4_TEST)
VERIFIER = HERE / "ds_data02_stage2_verify_scientific_field_h5_audit_v5.py"
VENV = V4_TEST.VENV


def run_v5(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(VENV), "-B", str(VERIFIER), *args],
        text=True,
        capture_output=True,
        check=False,
    )


def rebind_report(report: Path, manifest: Path, destination: Path) -> Path:
    value = json.loads(report.read_text(encoding="utf-8"))
    value["manifest"]["path"] = str(manifest.resolve())
    value["manifest"]["sha256"] = V4_TEST.sha256(manifest)
    value["manifest"]["current_binding"]["manifest_path"] = str(manifest.resolve())
    value["manifest"]["current_binding"]["manifest_sha256"] = V4_TEST.sha256(manifest)
    value["manifest"]["current_binding"]["static_ref_count"] = len(json.loads(manifest.read_text(encoding="utf-8"))["static_source_refs"])
    for case_result in value.get("case_results", []):
        binding = case_result.get("source_binding")
        if isinstance(binding, dict) and isinstance(binding.get("manifest"), dict):
            binding["manifest"]["manifest_path"] = str(manifest.resolve())
            binding["manifest"]["manifest_sha256"] = V4_TEST.sha256(manifest)
    destination.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return destination


class ScientificFieldH5AuditV5CliTests(unittest.TestCase):
    def test_v3_worker_to_v5_verifier_reads_only_bounded_metadata(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v5-chain-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            V4_TEST.BASE.write_h5(h5_path)
            manifest = V4_TEST.write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = V4_TEST.run_cli(V4_TEST.WORKER, "audit", "--manifest", str(manifest), "--output", str(report), "--chunk", "2")
            self.assertEqual(worker.returncode, 0, worker.stderr)
            output = directory / "verified.json"
            result = run_v5("verify", "--manifest", str(manifest), "--report", str(report), "--output", str(output), "--allow-fixture-context")
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(value["schema"], "ds02.stage2.verify-scientific-field-h5-audit.v5")
            self.assertTrue(value["bounded_metadata_content_read_by_verifier"])
            self.assertFalse(value["scientific_payload_content_read_by_verifier"])
            self.assertFalse(value["production_eligible"])

    def test_v5_rejects_ibi4_pvtu_and_symlinked_static_refs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v5-payload-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            V4_TEST.BASE.write_h5(h5_path)
            manifest = V4_TEST.write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = V4_TEST.run_cli(V4_TEST.WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertEqual(worker.returncode, 0, worker.stderr)
            original = json.loads(manifest.read_text(encoding="utf-8"))
            for suffix in (".ibi4", ".pvtu"):
                candidate = directory / f"payload{suffix}"
                candidate.write_bytes(b"tiny-payload\n")
                document = json.loads(json.dumps(original))
                document["static_source_refs"].append({**V4_TEST.stat(candidate), "role": f"payload{suffix}", "sha256": V4_TEST.sha256(candidate)})
                changed = directory / f"manifest{suffix[1:]}.json"
                changed.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
                changed_report = rebind_report(report, changed, directory / f"report{suffix[1:]}.json")
                result = run_v5("verify", "--manifest", str(changed), "--report", str(changed_report), "--output", str(directory / f"bad{suffix[1:]}.json"), "--allow-fixture-context")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("scientific payload", result.stderr)
            safe = directory / "safe-control.json"
            safe.write_text("{}\n", encoding="utf-8")
            link = directory / "linked-control.json"
            os.symlink(safe, link)
            document = json.loads(json.dumps(original))
            symlink_ref = V4_TEST.stat(link)
            # Preserve the lexical symlink path.  stat() resolves it for the
            # metadata fields, so using its default path would test the target
            # and miss the admission boundary.
            symlink_ref["path"] = str(link)
            document["static_source_refs"].append({**symlink_ref, "role": "symlinked-control", "sha256": V4_TEST.sha256(link)})
            linked_manifest = directory / "manifest-linked.json"
            linked_manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            linked_report = rebind_report(report, linked_manifest, directory / "report-linked.json")
            result = run_v5("verify", "--manifest", str(linked_manifest), "--report", str(linked_report), "--output", str(directory / "bad-linked.json"), "--allow-fixture-context")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("symlink", result.stderr)

    def test_v5_rejects_literal_historical_alias_even_without_current_status_fields(self) -> None:
        with tempfile.TemporaryDirectory(prefix="stage2-field-v5-alias-") as raw:
            directory = Path(raw)
            h5_path = directory / "fixture.h5"
            V4_TEST.BASE.write_h5(h5_path)
            manifest = V4_TEST.write_metadata_chain(directory, h5_path)
            report = directory / "report.json"
            worker = V4_TEST.run_cli(V4_TEST.WORKER, "audit", "--manifest", str(manifest), "--output", str(report))
            self.assertEqual(worker.returncode, 0, worker.stderr)
            alias = "F2_STAGE1_FIRST48_OFFSET_OPEN_RIM_RX056_RY014_FILL080_ROT090"
            document = json.loads(manifest.read_text(encoding="utf-8"))
            document["cases"][0]["physical_case_id"] = alias
            alias_manifest = directory / "manifest-alias.json"
            alias_manifest.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            alias_report = rebind_report(report, alias_manifest, directory / "report-alias.json")
            report_document = json.loads(alias_report.read_text(encoding="utf-8"))
            report_document["case_results"][0]["physical_case_id"] = alias
            alias_report.write_text(json.dumps(report_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            result = run_v5("verify", "--manifest", str(alias_manifest), "--report", str(alias_report), "--output", str(directory / "bad-alias.json"), "--allow-fixture-context")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("historical alias", result.stderr)


if __name__ == "__main__":
    unittest.main()
