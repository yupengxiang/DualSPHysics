import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-root-review-v1.json"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_root_review_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(RECEIPT.read_text())


def test_f5_root_review_authorizes_only_fresh_input_preparation():
    value = load()
    decision = value["review_decision"]
    assert value["schema"] == "core.f5.third_t1.root_review_receipt.v1"
    assert value["status"] == "definition_preparation_authorized_solver_closed"
    assert decision["candidate_family"] == "F5"
    assert decision["authorized_now"] is True
    assert decision["authorized_action"] == "write_one_fresh_definition_and_scaled_motion_file"
    assert decision["authorized_solver"] is False
    assert decision["authorized_cpu_native_preflight"] is False
    assert decision["authorized_matrix"] is False
    constraints = value["execution_constraints"]
    assert constraints["definition_written_by_review"] is False
    assert constraints["motion_written_by_review"] is False
    assert constraints["gencase_invoked"] is False
    assert constraints["native_decode_invoked"] is False
    assert constraints["solver_invoked"] is False
    assert constraints["gpu_started"] is False
    assert constraints["qualification_credit"] == 0
    assert constraints["core_gate_changed"] is False


def test_f5_root_review_has_complete_source_and_denominator_bindings():
    value = load()
    source = value["source_review"]
    assert source["official_inputs_verified"] is True
    assert source["official_input_count"] == 6
    assert source["r3_candidate_only_verified"] is True
    assert source["old_generated_products_qualification_reuse"] is False
    contract = value["scientific_contract"]
    assert contract["cell_count"] == 15
    assert contract["fixed_denominator"] is True
    assert contract["partial_credit"] is False
    assert contract["time_max_s"] == 16.0
    assert len(value["forbidden_actions"]) >= 5


def test_f5_root_review_hashes_are_current():
    value = load()
    implementation_binding = value["hash_bindings"]["implementation"]
    assert implementation_binding["path"] == "scripts/f5_wave_runup_root_review_v1.py"
    assert implementation_binding["sha256"] == sha256(IMPLEMENTATION)
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file()
        assert path.stat().st_size == item["bytes"]
        assert sha256(path) == item["sha256"]
