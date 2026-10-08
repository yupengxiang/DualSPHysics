import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_omission_mechanism_probe_v3.py"
SPEC = importlib.util.spec_from_file_location("mechanism_probe_v3", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def test_frozen_mass_gate_is_screen_only():
    semantics = MODULE.semantic_counterexamples()
    assert semantics["frozen_whole_initial_mass_gate_fraction"] == 0.003
    assert semantics["gate_role"] == "screen_only; never a dynamics/QN/QE credit"
    assert semantics["claim_boundary"]["dynamical_impact"] == "UNKNOWN"


def test_repeated_crossing_cannot_become_net_flux():
    semantics = MODULE.semantic_counterexamples()
    repeated = semantics["repeated_crossing_control"]
    assert repeated["saved_states"] == ["inside", "outside", "inside", "outside"]
    assert repeated["inferred_net_flux"] == "UNKNOWN"
    assert semantics["signed_net_flux_cancellation_control"]["inferred_net_flux"] == "UNKNOWN"


def test_unknown_width_and_region_destination_remain_unknown():
    semantics = MODULE.semantic_counterexamples()
    width = semantics["unknown_width_control"]
    region = semantics["material_region_control"]
    assert width["inferred_upper_bound"] == "UNKNOWN"
    assert width["unobserved_reentry_or_region_mass"] == "UNKNOWN"
    assert region["destination_material_region"] == "UNKNOWN"
    assert region["legal_flux"] == "UNKNOWN_NOT_PROVEN"


def test_raw_h5_and_bi4_predicates_are_rejected():
    assert MODULE.forbidden(Path("trajectory.h5"))
    assert MODULE.forbidden(Path("trajectory.hdf5"))
    assert MODULE.forbidden(Path("Part_000.bi4"))
    assert MODULE.forbidden(Path("PartOut_000.obi4"))
    assert not MODULE.forbidden(Path("PartFloatInfo.ibi4"))
