from __future__ import annotations
import json
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
def load(rel): return json.loads((ROOT / rel).read_text(encoding="utf-8"))
def test_target_extension_is_disjoint():
    inv = load("inventory/existing-physical-condition-inventory.json")
    assert inv["current_exact24"]["count"] == 24
    assert inv["historical_internal8"]["count"] == 8
    assert inv["fresh102_proposed24"]["count"] == 24
    for key in ("internal8_intersects_current24", "internal8_intersects_proposed24", "current24_intersects_proposed24", "registry_intersects_proposed24"):
        assert inv["set_relations"][key] == []
def test_recipe_and_claim_boundary():
    plan = load("source-plan.json")
    assert len(plan["rows"]) == 24
    assert plan["recipe"] == {"dp_m": 0.01, "time_max_s": 1.2, "time_out_s": 0.001, "native_frame_count": 1201, "solver_options": ["-tmax:1.2", "-tout:0.001"], "no_forcing": True, "no_mdbc": True}
    assert plan["stage_contract"]["launch_allowed"] is False
    assert plan["stage_contract"]["actual_counts"] is None
def test_all_gencase_requests_disabled_and_unknown():
    idx = load("requests/index.json")
    assert len(idx["rows"]) == 24 and idx["launch_allowed"] is False
    for row in idx["rows"]:
        d = json.loads(Path(row["path"]).read_text(encoding="utf-8"))
        assert d["disabled"] and not d["launch_allowed"] and not d["execution_allowed"]
        assert d["expected"]["total_particles_from_gencase"] is None
        assert d["expected"]["fluid_particles_from_gencase"] is None
        assert d["output_contract"]["future_sha256"] is None
        assert d["precision_status"] == "not_accepted" and d["q_n_status"] == "not_granted"
