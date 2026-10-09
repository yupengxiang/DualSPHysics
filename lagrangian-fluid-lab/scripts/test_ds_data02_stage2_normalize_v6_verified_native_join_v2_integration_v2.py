"""End-to-end tiny producer/normalizer/overlay integration coverage.

The fixture invokes the reviewed ROOT312 V4 audit, verifies its production
report with V6, normalizes the exact same request/manifest/report chain with
V2 under an explicit test-only fixture context, and passes that normalized
proof to the frozen V5 rolling overlay builder under the same test-only
context.  A second tiny worker is then verified by V6 against the resulting
V5 overlay.  All payloads are test-owned tiny files; the real CURRENT336 and
lifecycle-plan bindings are still used by the V6 verifier and V5 admission,
and every normalized/overlay result is explicitly non-production.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ds_data02_stage2_build_native_overlay_adapter_v5 as v5
import ds_data02_stage2_normalize_v6_verified_native_join_v2 as normalizer
import ds_data02_stage2_verify_generic_native_join_v6 as v6


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPT_DIR / filename)
    if spec is None or spec.loader is None:
        raise RuntimeError(filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


v2_fixture = _load(
    "stage2_v2_normalizer_integration_fixture",
    "test_ds_data02_stage2_normalize_v6_verified_native_join_v2.py",
)
v6_fixture = _load(
    "stage2_v6_root312_integration_fixture",
    "test_ds_data02_stage2_verify_generic_native_join_v6_root312.py",
)
tiny_fixture = v6_fixture.fixture

ROOT = SCRIPT_DIR.parents[0] / "campaigns/ds-data-02/stage2"
BASE_SCOPE = ROOT / "checkpoints/ORIGINAL118_NATIVE_CAUSE_AFTER_ROOT268_ACTUAL_OVERLAY_V10.json"
LIFECYCLE_PLAN = ROOT / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT269_V4.json"
CURRENT = v6_fixture.CURRENT


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _ref(path: Path) -> dict[str, object]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "bytes": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
        "ctime_ns": int(stat.st_ctime_ns),
        "st_dev": int(stat.st_dev),
        "st_ino": int(stat.st_ino),
        "sha256": _sha(path),
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _retarget_tiny_generic_fixture(paths: dict[str, Path], case_id: str) -> dict[str, Path]:
    """Retarget one test-owned producer contract to another CURRENT case."""
    summary = paths["summary"]
    summary_doc = json.loads(summary.read_text(encoding="utf-8"))
    summary_doc["physical_case_id"] = case_id
    _write(summary, summary_doc)

    contract = paths["contract"]
    contract_doc = json.loads(contract.read_text(encoding="utf-8"))
    contract_doc["physical_case_id"] = case_id
    contract_doc["typed_deferred"]["summary"] = _ref(summary)
    _write(contract, contract_doc)

    proof = paths["proof"]
    proof_doc = json.loads(proof.read_text(encoding="utf-8"))
    for row in proof_doc["case_verifications"]:
        row["physical_case_id"] = case_id
        row["summary"] = str(summary.resolve())
        row["summary_sha256"] = _sha(summary)
        row["records_stat_only"] = {**_ref(paths["typed"]), "rows": 1}
    _write(proof, proof_doc)

    manifest = paths["manifest"]
    manifest_doc = json.loads(manifest.read_text(encoding="utf-8"))
    manifest_doc["physical_case_ids"] = [case_id]
    manifest_doc["contracts"] = [{"physical_case_id": case_id, **_ref(contract)}]
    bundle = manifest_doc["proof_bundles"][0]
    bundle["producer_proof"] = _ref(proof)
    bundle["full_case_ids"] = [case_id]
    bundle["selected_case_ids"] = [case_id]
    _write(manifest, manifest_doc)

    request = paths["request"]
    request_doc = json.loads(request.read_text(encoding="utf-8"))
    request_doc["physical_case_ids"] = [case_id]
    request_doc["manifest_contract"] = {"path": str(manifest.resolve()), "sha256": _sha(manifest)}
    request_doc["input_sha256"] = {
        str(Path(path).resolve()): _sha(Path(path)) for path in request_doc["input_files"]
    }
    _write(request, request_doc)
    return paths


class StrictV2PipelineIntegrationTests(unittest.TestCase):
    def test_root312_v6_v2_v5_pipeline_uses_one_terminal_identity(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = v2_fixture.StrictV2NormalizerTests()

            # _run_v6 invokes the genuine ROOT312 V4 audit and then the V6
            # verifier.  Its manifest/request/report are the producer edges
            # reused by every later stage in this test.
            manifest, report, request, first_v6 = helper._run_v6(root)
            self.assertTrue(first_v6["status"].startswith("VERIFIED_"))
            self.assertEqual(first_v6["counts"]["worker_failed"], 0)

            terminal = v2_fixture._make_same_chain_terminal(root, request, manifest, report)
            terminal_doc = json.loads(terminal.read_text(encoding="utf-8"))
            _write(terminal, terminal_doc)

            normalized = root / "normalized-v2.json"
            normalized_value = normalizer.normalize(
                root / "v6-result.json",
                terminal,
                normalized,
                allow_fixture_context=True,
            )
            self.assertFalse(normalized_value["production_eligible"])
            normalized_doc = json.loads(normalized.read_text(encoding="utf-8"))
            case_ids = [row["physical_case_id"] for row in normalized_doc["case_verifications"]]
            first_case_ids = [row["physical_case_id"] for row in first_v6["case_verifications"]]
            self.assertEqual(case_ids, first_case_ids)
            self.assertEqual(normalized_doc["v6_producer_identity"]["request"]["path"], str(request.resolve()))
            self.assertEqual(normalized_doc["v6_producer_identity"]["manifest"]["path"], str(manifest.resolve()))
            self.assertEqual(normalized_doc["v6_producer_identity"]["report"]["path"], str(report.resolve()))

            # The same test-only path is callable through the reviewed CLI;
            # the explicit exemption must be present and the output remains
            # non-production.
            cli_output = root / "normalized-v2-cli.json"
            cli = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT_DIR / "ds_data02_stage2_normalize_v6_verified_native_join_v2.py"),
                    "--v6-result", str(root / "v6-result.json"),
                    "--terminal-identity", str(terminal),
                    "--output", str(cli_output),
                    "--allow-fixture-context",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(cli.returncode, 0, cli.stdout + cli.stderr)
            self.assertTrue(cli_output.is_file())
            self.assertFalse(json.loads(cli_output.read_text(encoding="utf-8"))["production_eligible"])

            # V5 consumes the V2 proof as the exact selected join proof.  Its
            # terminal top refs and charge are intentionally unchanged, so a
            # valid proof from a different producer cannot be substituted.
            v5_terminal_doc = copy.deepcopy(terminal_doc)
            v5_terminal_doc["actual_join_proof"] = _ref(normalized)
            v5_terminal_doc["selected_case_ids"] = case_ids
            v5_terminal = root / "v5-terminal-from-v2.json"
            _write(v5_terminal, v5_terminal_doc)
            overlay = root / "v5-overlay.json"
            overlay_value = v5.build(
                BASE_SCOPE,
                v5_terminal,
                overlay,
                LIFECYCLE_PLAN,
                CURRENT,
                allow_fixture_context=True,
            )
            self.assertEqual(overlay_value["status"], "VERIFIED_ROOT_TERMINAL_ROLLING_OVERLAY")
            overlay_doc = json.loads(overlay.read_text(encoding="utf-8"))
            self.assertEqual(overlay_doc["terminal_admission"]["failed_case_ids"], [])
            self.assertEqual(overlay_doc["terminal_admission"]["new_cause_case_ids"], sorted(case_ids))

            # Now exercise the literal V5 -> V6 edge.  V6 intentionally
            # rejects replaying the seven cases that V5 just admitted, so use
            # one different unresolved CURRENT F4 case and run the genuine
            # tiny producer worker for that case.
            post_scope, _ = v6._load_scope_v5(overlay, LIFECYCLE_PLAN, CURRENT)
            remaining_f4 = sorted(
                case_id for case_id in post_scope["selected"]
                if case_id.startswith("F4_") and case_id not in case_ids
            )
            self.assertTrue(remaining_f4)
            next_case_id = remaining_f4[0]
            second_paths = _retarget_tiny_generic_fixture(
                tiny_fixture._make_fixture(root / "post-v5-worker", "generic-v3"),
                next_case_id,
            )
            second_report = root / "post-v5-worker" / "worker-report.json"
            worker_run = subprocess.run(
                [
                    sys.executable,
                    str(tiny_fixture.WORKER),
                    "audit",
                    "--manifest", str(second_paths["manifest"]),
                    "--backend", "generic-v3",
                    "--output", str(second_report),
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(worker_run.returncode, 0, worker_run.stdout + worker_run.stderr)
            post_v5_v6 = v6.verify(
                overlay,
                second_paths["manifest"],
                second_paths["request"],
                second_report,
                LIFECYCLE_PLAN,
                CURRENT,
            )
            self.assertEqual(post_v5_v6["status"], "VERIFIED_GENERIC_OR_ROOT312_WORKER_OUTPUT_ALL_CASES")
            self.assertEqual(post_v5_v6["counts"]["worker_requested"], 1)
            self.assertEqual(post_v5_v6["counts"]["worker_completed"], 1)
            self.assertEqual(post_v5_v6["case_verifications"][0]["physical_case_id"], next_case_id)
            self.assertEqual(post_v5_v6["claim_boundary"]["physical_fate"], "UNKNOWN")
            self.assertEqual(post_v5_v6["claim_boundary"]["QI"], "UNKNOWN")


if __name__ == "__main__":
    unittest.main(verbosity=2)
