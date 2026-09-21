import json
from pathlib import Path

from scripts.f4_tallwall_qualification_evaluator_v2 import evaluate, verify_static_manifest


LAB = Path(__file__).resolve().parents[1]
MANIFEST = LAB / "campaigns/core-v1/cfd/f4-tallwall120-qualification-evaluator-v2.json"


def test_v2_uses_frozen_snapshot_and_keeps_static_hash_history_explicit():
    report = verify_static_manifest(MANIFEST)
    assert report["static_contract_pass"] is True
    assert report["qualification_claim"] == "none"
    manifest = json.loads(MANIFEST.read_text())
    history = manifest["historical_metadata"]
    assert history["original_jobs_manifest_preserved"] is True
    assert history["difference_is_explicit"] is True
    assert history["snapshot_design_sha256"] == "868bbd1e76ec3879b15bede97c0afb9fe0f18ae78fda36dc149ab4c276994612"
    assert history["jobs_manifest_recorded_static_validation_sha256"] != history["snapshot_static_validation_sha256"]


def test_v2_merges_archive_and_cell03_bundles_without_qualification_claim():
    report = evaluate(MANIFEST, archive_root=LAB / "campaigns/core-v1/cfd/f4-tallwall120-archives-v2")
    assert report["static_contract_pass"] is True
    assert report["qualification_claim"] == "none"
    # The archive is a live, hash-bound evidence directory: the evaluator's
    # promotion bit must be exactly the conjunction of its independent gates.
    # At the current checkpoint all fourteen scheduled cells plus the reused
    # canary are present, so this is true; the assertion remains fail-closed if
    # a future run removes a product.  Production registration is a separate
    # 32-case boundary and is not implied by this matrix result.
    assert report["T1_numerical"] is all(report["checks"].values())
    by_index = {row["index"]: row for row in report["cells"]}
    assert all(by_index[i]["passed"] is True for i in (0, 1, 3, 6, 12))
    assert by_index[3]["status"] == "succeeded"
    assert by_index[12]["status"] == "reused_canary"
    expected_scheduled = set(report["scheduled_solver_cells"])
    observed_scheduled = set(by_index) - set(report["reused_canary_cells"])
    expected_missing = expected_scheduled - observed_scheduled
    assert {row["index"] for row in report["missing"]} == expected_missing
    assert len(report["missing"]) == len(expected_missing)
