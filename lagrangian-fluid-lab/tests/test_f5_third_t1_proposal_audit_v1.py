import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
PROPOSAL = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1-proposal-audit-v1.json"
IMPLEMENTATION = LAB / "scripts/f5_third_t1_proposal_audit_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(PROPOSAL.read_text())


def test_f5_proposal_is_read_only_and_unqualified():
    proposal = load()
    assert proposal["schema"] == "core.f5.third_t1.proposal_audit.v1"
    assert proposal["status"] == "proposal_only_root_review_required"
    assert proposal["qualification_claim"] == "none"
    assert proposal["candidate"]["family"] == "F5"
    assert proposal["core_gate"]["current_registered_t1_families"] == ["F3", "F4"]
    assert proposal["core_gate"]["qualification_credit_added"] == 0
    controls = proposal["execution_controls"]
    assert controls["read_only_audit"] is True
    assert controls["gencase_invoked"] is False
    assert controls["native_decode_invoked"] is False
    assert controls["solver_invoked"] is False
    assert controls["gpu_launched"] is False
    assert controls["queue_mutation"] == 0
    assert controls["central_ledger_mutation"] == 0
    assert controls["central_registry_mutation"] == 0
    assert controls["matrix_materialized"] is False
    assert controls["matrix_submitted"] is False


def test_f5_scope_has_fixed_15_cell_denominator_and_fresh_identity():
    proposal = load()
    design = proposal["fixed_scope_design"]
    assert design["cell_count"] == design["spatial_cell_count"] + design["temporal_cell_count"] == 15
    assert design["qualification_q"] == [0.0, 0.5, 1.0]
    assert design["held_out_q"] == [0.25, 0.75]
    assert design["resolutions_m"] == [0.01, 0.0075, 0.005]
    assert set(design["temporal_controls"]) == {"internal_time", "native_output"}
    assert all("all 15 rows" in item for item in design["denominator_policy"] if "15" in item)
    identity = proposal["fresh_input_contract"]
    assert identity["source_identity_changed"] is True
    assert identity["qualification_inheritance"] is False
    assert identity["old_generated_input_reused"] is False
    assert identity["old_trajectory_reused"] is False
    assert identity["new_definition_required"] is True
    assert identity["new_motion_file_required"] is True


def test_f5_proposal_binds_pinned_sources_and_implementation_hash():
    proposal = load()
    official = proposal["evidence"]["official_inputs"]
    assert len(official) == 6
    assert all(len(item["sha256"]) == 64 and item["bytes"] > 0 for item in official)
    implementation = proposal["implementation"]
    assert implementation["path"] == "scripts/f5_third_t1_proposal_audit_v1.py"
    assert implementation["sha256"] == sha256(IMPLEMENTATION)
    review = proposal["root_review_only_contract"]
    assert "fresh q=0.5" in review["step_1"]
    assert "exactly one" in review["step_3"]
    assert "complete fixed matrix" in review["step_5"]
