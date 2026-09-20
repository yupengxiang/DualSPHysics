import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v1/preflight-root-review-v1.json"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_preflight_root_review_v1.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(RECEIPT.read_text())


def test_f5_preflight_review_authorizes_exactly_one_cpu_native_input():
    value = load()
    decision = value["review_decision"]
    assert value["schema"] == "core.f5.third_t1.preflight_root_review_receipt.v1"
    assert value["status"] == "authorized_one_fresh_cpu_native_preflight_only"
    assert decision["authorized_now"] is True
    assert decision["authorized_action"] == "run_exactly_one_fresh_cpu_gencase_native_decode"
    assert decision["authorized_solver"] is False
    assert decision["authorized_gpu"] is False
    assert decision["authorized_queue"] is False
    assert decision["authorized_matrix"] is False
    assert value["input_review"]["preflight_output_absent"] is True
    assert value["fixed_hard_gates"]["denominator_rows"] == 15
    assert value["fixed_hard_gates"]["qualification_credit"] == 0


def test_f5_preflight_review_rebinds_fresh_definition_and_motion():
    value = load()
    review = value["input_review"]
    assert review["definition"]["path"].endswith("F5_wave_runup_q0p50_dp0p0075_Def.xml")
    assert review["motion"]["path"].endswith("Mov_piston_q0p50_scaled.dat")
    assert review["xml_dp_m"] == 0.0075
    assert review["xml_time_max_s"] == 16.0
    assert review["xml_output_interval_s"] == 0.02
    assert review["external_gauges"] == ["WG1", "WG2", "WG3", "WG4"]
    assert review["old_generated_or_trajectory_reused"] is False


def test_f5_preflight_review_hash_bindings_are_current():
    value = load()
    binding = value["hash_bindings"]["implementation"]
    assert binding["path"] == "scripts/f5_wave_runup_preflight_root_review_v1.py"
    assert binding["sha256"] == sha256(IMPLEMENTATION)
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"]
