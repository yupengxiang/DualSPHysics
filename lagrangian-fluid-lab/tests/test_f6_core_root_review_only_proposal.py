import hashlib
import json
from pathlib import Path

import h5py
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = ROOT / "campaigns/core-v1/cfd/f6-fluid-rigid-body-root-review-only-proposal-v1-20260921.json"
REPORT = ROOT / "reports/F6-CORE-THIRD-T1-CANDIDATE-ROOT-REVIEW-2026-09-21.zh-CN.md"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_f6_proposal_is_new_read_only_and_unqualified():
    proposal = json.loads(PROPOSAL.read_text())
    assert proposal["proposal_id"] == "F6_fluid_rigid_body_root_review_only_20260921"
    assert proposal["qualification_claim"] == "none"
    assert proposal["family_admission"] is False
    assert proposal["candidate"]["family"] == "F6"
    policy = proposal["execution_policy"]
    for key in ("read_only", "qualification_claim_none"):
        assert policy[key] is True
    for key in ("solver_launch", "gpu_launch", "queue_mutation", "registry_mutation",
                "ledger_mutation", "matrix_mutation", "same_input_retry",
                "old_asset_reuse_as_qualification"):
        assert policy[key] is False
    assert proposal["decision"]["candidate_is_mechanistically_distinct"] is True
    assert proposal["decision"]["candidate_has_sufficient_evidence_for_t1"] is False
    assert REPORT.is_file()


def test_f6_legacy_probe_receipts_bind_and_fail_closed_on_body_closure():
    proposal = json.loads(PROPOSAL.read_text())
    expected_body_mass = {
        "F6_floating_box": (22, 500.0 * 0.24 * 0.16 * 0.16),
        "F6_heavy_box_entry": (22, 1400.0 * 0.20 * 0.16 * 0.16),
        "F6_twin_floaters": (22, 600.0 * 0.20 * 0.16 * 0.16),
    }
    for row in proposal["evidence"]["runtime_summary"]:
        definition = ROOT / row["definition"]
        trajectory = ROOT / row["trajectory"]
        assert _sha256(definition) == row["definition_sha256"]
        assert _sha256(trajectory) == row["trajectory_sha256"]
        with h5py.File(trajectory, "r") as handle:
            time = np.asarray(handle["time"][:])
            valid = np.asarray(handle["valid"][:])
            particle_id = np.asarray(handle["particle_id"][:])
            assert handle.attrs["schema_version"] == 2
            assert "material fidelity pending audit" in handle.attrs["trajectory_semantics"]
            assert np.all(np.diff(time) > 0)
            assert time[-1] >= 0.99 * row["target_time_s"]
            assert np.all(valid)
            assert len(np.unique(particle_id)) == len(particle_id)
            assert int(valid.shape[1]) == row["particles"]
            assert int(valid.shape[0]) == row["frames"]
            body_mk, expected_mass = expected_body_mass[row["case_id"]]
            body = np.asarray(handle["mk"][0]) == body_mk
            assert body.any()
            stored_body_mass = float(np.asarray(handle["mass"][0])[body].sum())
            assert not np.isclose(stored_body_mass, expected_mass, rtol=1e-6, atol=1e-6)
