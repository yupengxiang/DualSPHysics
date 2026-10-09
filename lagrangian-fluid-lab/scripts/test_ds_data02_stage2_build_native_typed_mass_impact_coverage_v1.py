from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ds_data02_stage2_build_native_typed_mass_impact_coverage_v1 as subject


def _write(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> argparse.Namespace:
    ids = [f"F2_CASE_{i:03d}" for i in range(48)] + [f"F4_CASE_{i:03d}" for i in range(22)] + [f"F6_CASE_{i:03d}" for i in range(48)]
    families = ["F2"] * 48 + ["F4"] * 22 + ["F6"] * 48
    rows = [{
        "physical_case_id": case_id, "family_id": family, "current336_index": i,
        "historical_118_membership": True,
        "cause_and_fate_scope": {"physical_fate": "UNKNOWN"},
    } for i, (case_id, family) in enumerate(zip(ids, families))]
    inventory = {"schema": "ds02.stage2.historical118-source-inventory.v1", "status": "SOURCE_INVENTORY_READY_METADATA_ONLY",
                 "scope": {"historical_case_count": 118, "f3_fine512_included": False, "root192_typed_particle_records_added_as_cases": False},
                 "rows": rows}
    inventory_path = _write(tmp_path / "inventory.json", inventory)

    evidence_sha = "a" * 64
    newly = {"physical_case_id": ids[0], "family_id": "F2", "native_cause": "NUMERICAL_POSITION_EXCLUSION",
             "evidence": "/immutable/proof.json", "evidence_sha256": evidence_sha, "fluid_identity_count": 1,
             "saved_frame_join": {"saved_frame_matches": 1}}
    overlay = {"schema": "ds02.stage2.original118-native-cause-actual-overlay.v1", "status": "VERIFIED_METADATA_JOIN_TO_ACTUAL_PER_ID_PROOFS",
               "physical_case_count": 118, "native_cause_bound_per_fluid_id_cases": 94,
               "cause_not_located_after_completed_scan_cases": 24, "actual_typed_native_saved_frame_join_physical_cases": 1,
               "newly_bound_cases": [newly], "remaining_cause_not_located_case_ids": ids[1:25],
               "root_H5_native_JSONL_content_read": False}
    overlay_path = _write(tmp_path / "overlay.json", overlay)

    root313_ids = ids[25:42]  # 17 source-ready cases, distinct from the future requests below.
    bundles = [("ROOT258", "F6", root313_ids[:7]), ("ROOT264", "F4", root313_ids[7:10]), ("ROOT268", "F6", root313_ids[10:])]
    manifest_cases = []
    manifest_bundles = []
    spec_bundles = []
    for bundle_id, family, bundle_ids in bundles:
        proof = {"path": f"/immutable/{bundle_id}.json", "sha256": "b" * 64}
        manifest_bundles.append({"bundle_id": bundle_id, "case_count": len(bundle_ids), "case_ids": bundle_ids,
                                 "family_id": family, "producer_proof_preserved": True, "proof": proof,
                                 "typed_jsonl_case_count": len(bundle_ids), "typed_jsonl_source_bytes": 100,
                                 "typed_jsonl_minimum_three_pass_read_bytes": 300})
        spec_bundles.append({"bundle_id": bundle_id, "family_id": family, "case_ids": bundle_ids,
                             "expected_case_count": len(bundle_ids), "proof_path": proof["path"], "proof_sha256": proof["sha256"]})
        for case_id in bundle_ids:
            manifest_cases.append({"physical_case_id": case_id, "family_id": family, "proof_bundle_id": bundle_id,
                                   "producer_proof": proof, "native_report": {"path": "/immutable/report.json"},
                                   "typed_records_deferred": {"bytes": 100}, "selected_native_id_count": 1})
    manifest = {"schema": "ds02.stage2.native-typed-mass-impact.root313-manifest",
                "status": "READY_SOURCE_ONLY_NATIVE_TYPED_MASS_IMPACT_ROOT313", "case_count": 17,
                "producer_proof_merge": {"created": False}, "cases": manifest_cases, "proof_bundles": manifest_bundles}
    manifest_path = _write(tmp_path / "root313-manifest.json", manifest)
    spec_path = _write(tmp_path / "root313-spec.json", {"schema": "ds02.stage2.native-typed-mass-impact-proof-spec.v1", "bundles": spec_bundles})

    future_paths = {}
    for name, family, selected in (("274", "F6", ids[42:49]), ("308", "F4", ids[49:53]), ("309", "F6", ids[53:59])):
        request = {"schema": "ds02.request.v1", "family_id": family, "physical_case_ids": selected,
                   "launch_allowed": True, "execution_allowed": True, "estimated_deferred_read_bytes": 10,
                   "estimated_storage_bytes": 10}
        future_paths[name] = _write(tmp_path / f"request-{name}.json", request)
    pending_path = _write(tmp_path / "root312.json", {"schema": "ds02.stage2.root312-f4-multi-proof-intake-pending.v2",
        "status": "WAITING_FULL_TERMINAL_PROOFS", "full_producer_case_count": 16,
        "selected_original118_case_count": 7, "launch_allowed": False, "payload_content_opened": False,
        "source_only": True, "producer_proofs": [{"bundle_id": "ROOT296", "producer_proof": "NOT_AVAILABLE"},
                                                   {"bundle_id": "ROOT297", "producer_proof": "NOT_AVAILABLE"}]})
    return argparse.Namespace(inventory=inventory_path, overlay=overlay_path, root313_manifest=manifest_path,
                              root313_spec=spec_path, root274_request=future_paths["274"], root308_request=future_paths["308"],
                              root309_request=future_paths["309"], root312_checkpoint=pending_path,
                              output=tmp_path / "coverage.json")


def test_coverage_builder_emits_118_rows_and_keeps_mass_pending(tmp_path: Path) -> None:
    args = _fixture(tmp_path)
    value = subject.build(args)
    assert value["cases"] == 118
    result = json.loads(args.output.read_text(encoding="utf-8"))
    assert len(result["case_rows"]) == 118
    assert result["summary"]["root313_mass_source_ready_not_actual"] == 17
    assert result["summary"]["root313_mass_actual_completed"] == 0
    assert result["read_policy"]["deferred_jsonl_h5_bi4_obi4_content_opened"] is False
    assert all(row["qualification"]["QI"] == "UNKNOWN" for row in result["case_rows"])


def test_coverage_builder_rejects_duplicate_inventory_case(tmp_path: Path) -> None:
    args = _fixture(tmp_path)
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    inventory["rows"][1]["physical_case_id"] = inventory["rows"][0]["physical_case_id"]
    args.inventory.write_text(json.dumps(inventory) + "\n", encoding="utf-8")
    with pytest.raises(subject.CoverageError, match="case identities are not unique"):
        subject.build(args)


def test_coverage_builder_rejects_root313_case_outside_original118(tmp_path: Path) -> None:
    args = _fixture(tmp_path)
    manifest = json.loads(args.root313_manifest.read_text(encoding="utf-8"))
    manifest["cases"][0]["physical_case_id"] = "NOT_IN_118"
    args.root313_manifest.write_text(json.dumps(manifest) + "\n", encoding="utf-8")
    with pytest.raises(subject.CoverageError, match="outside/duplicated"):
        subject.build(args)


def test_coverage_builder_rejects_pending_checkpoint_with_fake_proof(tmp_path: Path) -> None:
    args = _fixture(tmp_path)
    pending = json.loads(args.root312_checkpoint.read_text(encoding="utf-8"))
    pending["producer_proofs"][0]["producer_proof"] = "/fake/proof.json"
    args.root312_checkpoint.write_text(json.dumps(pending) + "\n", encoding="utf-8")
    with pytest.raises(subject.CoverageError, match="unexpectedly has a producer proof"):
        subject.build(args)


def test_coverage_builder_has_real_cli_self_test() -> None:
    completed = subprocess.run([sys.executable, str(subject.SCRIPT), "self-test"], capture_output=True, text=True, check=False)
    assert completed.returncode == 0
    assert '"status": "PASS"' in completed.stdout
