from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_root311_current_array_only as subject
from test_ds_data02_stage2_typed_lifecycle_sidecar_v4 import write_fixture


CASE_ID = subject.CASE_DEFAULT


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> str:
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    return sha(path)


def make_source(root: Path) -> dict[str, Path | str]:
    source = write_fixture(root)
    current_path = Path(source["current"])
    current = json.loads(current_path.read_text())
    original = current["cases"][0]
    cases = []
    for index in range(subject.CURRENT_INDEX):
        cases.append({
            "family_id": "F1", "physical_case_id": f"DUMMY_{index}",
            "frames": original["frames"], "particles": original["particles"],
            "trajectory": dict(original["trajectory"]),
        })
    target = dict(original)
    target["family_id"] = "F2"
    target["physical_case_id"] = CASE_ID
    target["runtime_case_alias"] = "F2_ALIAS_FIXTURE_DP010"
    cases.append(target)
    current["cases"] = cases
    current_sha = write_json(current_path, current)

    scan_path = Path(source["scan"])
    scan = json.loads(scan_path.read_text())
    scan["physical_case_id"] = CASE_ID
    scan_sha = write_json(scan_path, scan)
    receipt_path = Path(source["receipt"])
    receipt_sha = sha(receipt_path)
    audit_path = Path(source["audit"])
    audit = json.loads(audit_path.read_text())
    audit["current_catalog"] = {"path": str(current_path), "sha256": current_sha}
    row = audit["verified_cases"][0]
    row["family_id"] = "F2"
    row["physical_case_id"] = CASE_ID
    row["trajectory"] = str(Path(source["h5"]).resolve())
    row["trajectory_verified_sha256"] = source["h5_sha"]
    row["scan"] = str(scan_path.resolve())
    row["scan_sha256"] = scan_sha
    row["receipt"] = str(receipt_path.resolve())
    row["receipt_sha256"] = receipt_sha
    row["exact_CURRENT_path_and_declared_sha_match"] = True
    audit_sha = write_json(audit_path, audit)

    alias_path = root / "alias-resolution.json"
    alias_sha = write_json(alias_path, {
        "alias": {"current_index": subject.CURRENT_INDEX, "physical_case_id": CASE_ID, "plan_status": "HISTORICAL_ALIAS_UNRESOLVED", "scientific_credit": "NONE"},
        "evidence": {"audit_023_exact_current_path_and_declared_sha_match": True, "canonical_binding_present": False, "registry_has_target_producer": False},
    })
    mismatch_path = root / "alias-mismatch.json"
    mismatch_sha = write_json(mismatch_path, {"scientific_credit": "NONE", "original_producer_exact_current_binding": False})
    source.update({"current_sha": current_sha, "audit_sha": audit_sha, "scan_sha": scan_sha, "receipt_sha": receipt_sha, "alias": alias_path, "alias_sha": alias_sha, "mismatch": mismatch_path, "mismatch_sha": mismatch_sha})
    return source


def prepare_args(root: Path, source: dict[str, Path | str], output_dir: Path) -> SimpleNamespace:
    python = root / "python"
    python.write_text("fixture interpreter\n", encoding="utf-8")
    runtime = {}
    for name in ("runtime-v2", "runtime-v6", "runtime-v8", "dispatch-v8", "strict-v8"):
        path = root / f"{name}.py"
        path.write_text(f"{name}\n", encoding="utf-8")
        runtime[name] = path
    config = root / "runtime-config.xml"
    config.write_text("<config fixture=\"true\"/>\n", encoding="utf-8")
    return SimpleNamespace(
        current=source["current"], audit_verification=source["audit"], scan=source["scan"], receipt=source["receipt"],
        alias_resolution=source["alias"], mismatch_verification=source["mismatch"], case_id=CASE_ID,
        expected_current_sha256=source["current_sha"], output_dir=output_dir, worker=subject.SCRIPT, python=python,
        runtime_config=config, runtime_v2=runtime["runtime-v2"], runtime_v6=runtime["runtime-v6"], runtime_v8=runtime["runtime-v8"],
        dispatch_v8=runtime["dispatch-v8"], strict_v8=runtime["strict-v8"], cwd=root, worktree_root=root,
    )


class Root311CurrentArrayOnlyTests(unittest.TestCase):
    def test_self_test_is_no_credit_and_nonlaunching(self) -> None:
        result = subject.self_test()
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["current_index"], 78)
        self.assertEqual(result["canonical_coverage_credit"], "NONE")
        self.assertEqual(result["producer_identity"], "UNKNOWN_CANONICAL_PRODUCER_BINDING")
        self.assertFalse(result["payload_opened"])

    def test_prepare_binds_exact_index_and_defers_h5(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            before_sha = sha(Path(source["h5"]))
            prepared = subject.prepare(prepare_args(root, source, root / "prepared"))
            manifest = json.loads(Path(prepared["manifest"]).read_text())
            request = json.loads(Path(prepared["request"]).read_text())
            h5_ref = next(ref for ref in manifest["source_refs"] if ref["role"] == "trajectory_h5")
            self.assertEqual(manifest["current_index"], 78)
            self.assertEqual(manifest["producer_identity"]["status"], "UNKNOWN_CANONICAL_PRODUCER_BINDING")
            self.assertEqual(manifest["coverage_credit"]["canonical_335_coverage_credit"], "NONE")
            self.assertFalse(h5_ref["content_read_by_preparer"])
            self.assertNotIn(str(source["h5"]), request["input_files"])
            self.assertIn(str(source["h5"]), request["deferred_input_files"])
            self.assertEqual(request["physical_case_id"], CASE_ID)
            self.assertEqual(request["current_index"], 78)
            self.assertEqual(before_sha, sha(Path(source["h5"])))

    def test_real_cli_audit_tiny_fixture_preserves_alias_no_credit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            prepared = subject.prepare(prepare_args(root, source, root / "prepared"))
            summary = root / "audit-summary.json"
            records = root / "audit-records.jsonl"
            completed = subprocess.run(
                [sys.executable, str(subject.SCRIPT), "audit", "--manifest", prepared["manifest"], "--summary", str(summary), "--records", str(records), "--chunk", "2"],
                cwd=root, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr or completed.stdout)
            result = json.loads(completed.stdout)
            self.assertEqual(result["status"], "COMPLETED_CURRENT_ARRAY_ONLY_NO_CANONICAL_CREDIT")
            report = json.loads(summary.read_text())
            self.assertEqual(report["current_index"], 78)
            self.assertEqual(report["coverage_credit"]["canonical_335_coverage_credit"], "NONE")
            self.assertEqual(report["producer_identity"]["status"], "UNKNOWN_CANONICAL_PRODUCER_BINDING")
            self.assertEqual(report["scientific_qualification"]["QI"], "UNKNOWN")
            self.assertTrue(records.is_file())

    def test_manifest_rejects_canonical_credit_or_wrong_index(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = make_source(root)
            prepared = subject.prepare(prepare_args(root, source, root / "prepared"))
            manifest_path = Path(prepared["manifest"])
            manifest = json.loads(manifest_path.read_text())
            manifest["coverage_credit"]["canonical_335_coverage_credit"] = "VERIFIED"
            bad = root / "bad-manifest.json"
            bad.write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaises(subject.CurrentArrayOnlyError):
                subject._validate_manifest(bad)


if __name__ == "__main__":
    unittest.main()
