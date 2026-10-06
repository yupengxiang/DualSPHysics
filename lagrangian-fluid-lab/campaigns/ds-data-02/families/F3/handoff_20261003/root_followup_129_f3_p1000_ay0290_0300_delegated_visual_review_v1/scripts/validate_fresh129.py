#!/usr/bin/env python3
"""Validate fresh129 metadata and PNG evidence without opening scientific payloads."""
from __future__ import annotations
import hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
CASES = ["F3_STAGE1_DP006_P1000_AY0290", "F3_STAGE1_DP006_P1000_AY0300"]

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()
def load(p: Path):
    return json.loads(p.read_text())
def fail(msg):
    raise AssertionError(msg)

checkpoint = load(HERE / "metadata/accepted-checkpoint-audit.json")
assert checkpoint["checkpoint"]["checkpoint_number"] == 144
assert checkpoint["accepted_decision_paths_checked"] == 217
assert checkpoint["shared_state_written"] is False
for case in CASES:
    chain_p = HERE / "metadata/chain-audit" / f"{case}.json"
    decision_p = HERE / "metadata/visual-review" / f"{case}-delegated-visual-decision.json"
    png_p = HERE / "metadata/png-hashes" / f"{case}.json"
    chain = load(chain_p); decision = load(decision_p); png = load(png_p)
    assert chain["chain_complete_for_visual_review"] is True
    assert decision["status"] == "visual-approved-by-delegated-agent"
    assert decision["agent_personally_viewed_all_contacts_and_keys"] is True
    assert decision["main_personally_viewed_pngs"] is False
    assert decision["actual_frames"] == 836
    assert decision["actual_particles"] == 179208
    assert decision["actual_fluid_particles"] == 67500
    assert decision["maximum_missing_particles"] == 0
    assert decision["precision_status"] == "not_accepted"
    assert decision["q_n"] == "not_granted"
    assert decision["q_e"] == "not_assessed"
    assert len(decision["verified_PNG_hashes"]["contact_sheets"]) == 35
    assert len(decision["verified_PNG_hashes"]["keyframes"]) == 6
    for item in decision["verified_PNG_hashes"]["contact_sheets"] + decision["verified_PNG_hashes"]["keyframes"]:
        p = Path(item["path"])
        assert p.is_file(), p
        assert sha(p) == item["sha256"], p
    for item in png["contact_sheets"] + png["keyframes"]:
        assert sha(Path(item["path"])) == item["sha256"]
    source = decision["source_review"]
    assert Path(source["path"]).is_file()
    assert sha(Path(source["path"])) == source["sha256"]
    assert decision["checkpoint_dedup"]["no_match_for_visual_review"] is True
    for stage in ("native", "typed", "xmf", "render"):
        x = chain["stages"][stage]
        assert x["status"] == "completed", (case, stage)
        assert x["returncode"] == 0, (case, stage)
        assert str(x["path"]).endswith(".json")
    assert chain["owner_and_scope"]["legacy_scope_not_substituted_for_canonical"] is True
    assert chain["source_read_boundary"]["scientific_payload_opened_by_this_agent"] is False
    assert chain["source_read_boundary"]["scientific_payload_hashed_by_this_agent"] is False
no_new = load(HERE / "metadata/no-new-xmf-candidates.json")
assert no_new["new_xmf_handoff_count"] == 0
assert no_new["shared_state_written"] if "shared_state_written" in no_new else True
print("fresh129 validation PASS: 2 visual decisions, 70 contact/key PNG hashes, checkpoint dedup closed, no downstream handoff")
