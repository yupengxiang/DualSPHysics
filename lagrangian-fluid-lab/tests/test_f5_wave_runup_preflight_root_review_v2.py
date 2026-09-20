import hashlib
import json
from pathlib import Path


LAB = Path(__file__).resolve().parents[1]
RECEIPT = LAB / "campaigns/core-v1/cfd/f5-wave-runup-third-t1/fresh-definition-v2/preflight-root-review-v2.json"
IMPLEMENTATION = LAB / "scripts/f5_wave_runup_preflight_root_review_v2.py"
RUNNER = LAB / "scripts/f5_wave_runup_preflight_v2.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load():
    return json.loads(RECEIPT.read_text())


def test_f5_v2_review_authorizes_one_new_cpu_native_preflight():
    value = load()
    decision = value["review_decision"]
    assert value["schema"] == "core.f5.third_t1.preflight_root_review_receipt.v2"
    assert value["status"] == "authorized_one_fresh_cpu_native_preflight_only"
    assert decision["authorized_now"] is True
    assert decision["authorized_action"] == "run_exactly_one_fresh_v2_cpu_gencase_native_decode"
    assert decision["authorized_solver"] is False
    assert decision["authorized_gpu"] is False
    assert decision["authorized_queue"] is False
    assert decision["authorized_matrix"] is False
    assert value["repair_review"]["asset_closure_pass"] is True
    assert value["fixed_hard_gates"]["qualification_credit"] == 0


def test_f5_v2_review_binds_new_assets_and_preserves_v1_failure():
    value = load()
    repair = value["repair_review"]
    assert repair["prior_v1_failure"]["path"].endswith("fresh-definition-v1/preflight-v1/preflight.json")
    assert repair["prior_v1_reused"] is False
    assert repair["adjacent_slope"]["path"].endswith("fresh-definition-v2/Slope.stl")
    assert repair["adjacent_blocks"]["path"].endswith("fresh-definition-v2/Blocks_3D_scaled.stl")
    assert repair["preflight_output_absent"] is True


def test_f5_v2_review_hashes_are_current():
    value = load()
    binding = value["hash_bindings"]["implementation"]
    assert binding["path"] == "scripts/f5_wave_runup_preflight_root_review_v2.py"
    assert binding["sha256"] == sha256(IMPLEMENTATION)
    runner = value["hash_bindings"]["preflight_runner"]
    assert runner["path"] == "scripts/f5_wave_runup_preflight_v2.py"
    assert runner["sha256"] == sha256(RUNNER)
    for item in value["hash_bindings"].values():
        path = LAB / item["path"]
        assert path.is_file() and path.stat().st_size == item["bytes"] and sha256(path) == item["sha256"]
