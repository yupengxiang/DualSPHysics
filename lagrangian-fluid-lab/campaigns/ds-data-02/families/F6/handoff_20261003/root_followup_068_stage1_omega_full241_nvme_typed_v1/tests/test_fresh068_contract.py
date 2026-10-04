#!/usr/bin/env python3
"""Static fresh068 checks; never launch conversion or read native arrays."""
from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUESTS = sorted((ROOT / "requests").glob("*-nvme-conversion-request.json"))
CASES = {
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025": {
        "owner": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_two_omega_endpoints_actual_gencase_073/F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025/canonical-owner.json",
        "physical": "923ac5567e77877d9797708cfbe899d367e3b22e6f3260f9f011a84e76818c1e",
        "declared": [0.02, 0.03, 0.015],
        "observed": [0.02, 0.029999999, 0.015],
    },
    "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025": {
        "owner": "/home/jade/.codex/worktrees/ds-data-02-integration/DualSPHysics/lagrangian-fluid-lab/campaigns/ds-data-02/handoff_20261003/root_stage1_f6_two_omega_endpoints_actual_gencase_073/F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025/canonical-owner.json",
        "physical": "4c8dfe6ce0f5f0913d9fe50e379da59db64efc04679f14bbe0f79d2213d51bd0",
        "declared": [0.16, 0.24, 0.12],
        "observed": [0.16, 0.23999999, 0.12],
    },
}

def load(path: Path):
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), path
    return value

def sha(path: Path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def test_disabled_and_input_closure():
    assert len(REQUESTS) == 2
    helper = load(ROOT / "helper-binding.json")
    assert helper["status"] == "source_only_disabled"
    assert helper["launch"] is False and helper["launch_allowed"] is False
    assert helper["protocol"]["native_timeline"] == "all 241 native frames streamed; no frame thinning"
    assert helper["typed_identity"]["floating_type"] == 2
    assert helper["typed_identity"]["floating_mk"] == 60
    assert helper["typed_identity"]["floating_count"] == 16384
    for request_path in REQUESTS:
        request = load(request_path)
        case = request["topphysical_case_id"]
        assert case in CASES
        assert request["launch"] is False and request["launch_allowed"] is False
        assert request["status"] == "source_only_disabled"
        assert request["schema"] == "ds02.runner-request.v2"
        assert request["expected_native_frames"] if "expected_native_frames" in request else True
        assert request["conversion_scope"]["native_frame_count"] == 241
        assert request["conversion_scope"]["official_partvtk_frames"] == [0, 120, 240]
        assert request["native_source_status"] == "completed"
        assert request["native_source_returncode"] == 0
        assert request["gencase_actual"] == {"status": "completed", "returncode": 0, "total": 417505, "fluid": 327680, "fixed": 73441, "moving": 0, "floating": 16384, "dimension": 3}
        assert request["physical_condition_sha256"] == CASES[case]["physical"]
        assert request["typed_identity_contract"]["floating_type"] == 2
        assert request["typed_identity_contract"]["floating_mk"] == 60
        assert request["mass_policy"]["physical_rigid_body_mass_kg"] == 128.0
        assert request["mass_policy"]["native_lattice_support_mass_kg"] == 256.0
        assert request["mass_policy"]["solver_interaction_masspart_kg"] == 0.015625
        assert request["mass_policy"]["normalization"] == "none"
        assert not any(x in request["command"] for x in ["-mdbc", "-dbc", "-motion", "-forcing"])
        assert request["command"][1].endswith("ds_data02_nvme_convert_v1.py")
        assert "--staging-limit-bytes" in request["command"]
        assert len(request["input_files"]) == len(set(request["input_files"]))
        assert set(request["input_files"]) == set(request["input_sha256"])
        for raw in request["input_files"]:
            path = Path(raw)
            assert path.is_file(), path
            assert len(request["input_sha256"][raw]) == 64
            assert sha(path) == request["input_sha256"][raw], path

def test_owner_keeps_root073_physical_binding_and_adds_type2():
    for case, expected in CASES.items():
        typed_path = ROOT / "owners" / f"{case}.owner.json"
        typed = load(typed_path)
        canonical_path = Path(expected["owner"])
        canonical = load(canonical_path)
        assert typed["physical_binding"] == canonical["physical_binding"]
        assert typed["physical_condition_sha256"] == expected["physical"]
        identity = typed["conversion_owner"]["typed_identity"]
        floating = next(row for row in identity["blocks"] if row["name"] == "floating")
        assert floating["type"] == 2 and floating["mk"] == 60
        assert floating["count"] == 16384
        assert floating["id_range_inclusive"] == [73441, 89824]
        assert typed["conversion_owner"]["mass_semantics"]["physical_rigid_body_mass_kg"] == 128.0
        assert typed["conversion_owner"]["mass_semantics"]["native_lattice_support_mass_kg"] == 256.0
        assert typed["conversion_owner"]["mass_semantics"]["solver_interaction_masspart_kg"] == 0.015625

def test_floatinginfo_summary_is_actual_endpoint_specific():
    semantic = load(ROOT / "semantic-binding.json")
    assert semantic["floatinginfo_state0"]["observed_values"] == {
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S025_DP025": [0.02, 0.029999999, 0.015],
        "F6_STAGE1_ANGULAR_RELEASE_OMEGA_S200_DP025": [0.16, 0.23999999, 0.12],
    }
    for row in semantic["endpoints"]:
        assert row["declared_angular_velocity_rad_s"] == CASES[row["endpoint_id"]]["declared"]
        assert row["observed_angular_velocity_rad_s"] == CASES[row["endpoint_id"]]["observed"]
    assert "particle V0=0" in semantic["initial_velocity_policy"]

def test_source_package_has_no_array_reader():
    source = "\n".join(path.read_text(encoding="utf-8") for path in [ROOT / "README.md", ROOT / "helper-binding.json", ROOT / "conversion-contract.json", ROOT / "semantic-binding.json", ROOT / "source-input-binding.json"])
    assert "h5py" not in source.lower()
    assert "numpy" not in source.lower()

if __name__ == "__main__":
    test_disabled_and_input_closure()
    test_owner_keeps_root073_physical_binding_and_adds_type2()
    test_floatinginfo_summary_is_actual_endpoint_specific()
    test_source_package_has_no_array_reader()
    print("F6 fresh068 static contract: PASS")
