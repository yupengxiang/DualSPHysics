from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "ds_data02_stage2_f4_s1_stream_v1.py"
SPEC = importlib.util.spec_from_file_location("stage2_f4_s1_stream_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def operators() -> dict:
    return {
        "schema": "ds02.f4.science-operators.v2",
        "physical_support": {"support_radius_m": 0.02},
        "transport": {
            "missing_identity_policy": "unknown state; missing particles are excluded from active aperture sums and never counted as physical exit"
        },
    }


def manifest() -> dict:
    variants = (
        ("coarse-native", "coarse", "native"),
        ("medium-native", "medium", "native"),
        ("fine-native", "fine", "native"),
        ("fine-half_dt", "fine", "half_dt"),
        ("fine-half_save", "fine", "half_save"),
    )
    items = []
    for suffix, resolution, time_variant in variants:
        entry = {
            "artifact_id": f"{MODULE.EXPECTED_ARTIFACT_PREFIX}-{suffix}",
            "case_id": MODULE.EXPECTED_CASE,
            "resolution": resolution,
            "time_variant": time_variant,
            "physical_binding_sha256": "a" * 64,
        }
        for key in ("trajectory_hdf5", "metadata", "conversion_report", "conversion_receipt", "source_regions"):
            entry[key] = {"path": f"/unread/{suffix}-{key}.json", "sha256": "b" * 64}
        items.append(entry)
    return {
        "schema": MODULE.MANIFEST_SCHEMA,
        "family_id": "F4",
        "case_id": MODULE.EXPECTED_CASE,
        "physical_binding_sha256": "a" * 64,
        "trajectory_read_policy": "guarded_h5_read_only_no_bi4_no_solver",
        "claim_boundary": {"q_n": "not_assessed", "physical_fate": "unknown"},
        "artifacts": items,
    }


def test_json_only_manifest_contract_accepts_all_five_variants():
    entries = MODULE.validate_manifest_dict(manifest(), operators=operators(), require_files=False)
    assert [entry["variant"] for entry in entries] == [
        "coarse-native", "medium-native", "fine-native", "fine-half_dt", "fine-half_save"
    ]


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: value["artifacts"].pop(),
        lambda value: value["artifacts"][0].update({"case_id": "F4_OTHER"}),
        lambda value: value["artifacts"][0]["metadata"].update({"sha256": "c" * 63}),
        lambda value: value.update({"trajectory_read_policy": "read_all_raw"}),
        lambda value: value["artifacts"][0].update({"physical_binding_sha256": "d" * 64}),
    ],
)
def test_json_only_manifest_contract_rejects_identity_or_scope_drift(mutator):
    value = manifest()
    mutator(value)
    with pytest.raises(MODULE.StreamContractError):
        MODULE.validate_manifest_dict(value, operators=operators(), require_files=False)


def test_operator_contract_rejects_support_radius_change():
    with pytest.raises(MODULE.StreamContractError):
        MODULE.validate_manifest_dict(manifest(), operators={**operators(), "physical_support": {"support_radius_m": 0.03}}, require_files=False)


def test_calibration_is_explicitly_nonphysical():
    result = MODULE._calibration()
    assert result["schema"] == "ds02.f4.source-support-calibration.v1"
    assert "not a physical F4 result" in result["interpretation"]
    assert result["registered_radius_m"] == 0.02
