import importlib.util
from pathlib import Path

import numpy as np
import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f7_half_cfl_initial_qa_v3.py"


def _module():
    spec = importlib.util.spec_from_file_location("f7_initial_qa_v3_test_module", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _decoded():
    n = 70179
    types = np.full(n, 3, dtype=np.int8)
    types[:27495] = 0
    types[27495:27495 + 1984] = 1
    mks = np.full(n, 2, dtype=np.int16)
    mks[:27495] = 10
    mks[27495:27495 + 1984] = 12
    return {
        "zone": 0,
        "ids": np.arange(n, dtype=np.uint32),
        "position": np.zeros((n, 3), dtype=np.float32),
        "valid": np.ones(n, dtype=bool),
        "type": types,
        "mk": mks,
        "mass": np.where(types == 3, 0.015625, 0.03125).astype(np.float32),
        "metadata": {key: value for key, value in {
            "Dp": 0.02, "B": 1.0, "Rhop0": 1000.0, "Gamma": 7.0,
            "MassBound": 0.03125, "MassFluid": 0.015625,
        }.items()},
    }


def test_exact_initial_typed_contract_and_position_counterexample():
    module = _module()
    left, right = _decoded(), _decoded()
    report = module.compare_initial_arrays(left, right)
    assert report["identity_key"] == "(Zone,Idp)"
    assert report["expected_particle_count"] == 70179
    assert all(item["exact"] for item in report["arrays"])

    right["position"][123, 2] = 1.0e-3
    with pytest.raises(module.F7InitialQAError, match="typed arrays differ"):
        module.compare_initial_arrays(left, right)


def test_source_hash_guard_rejects_changed_small_source(tmp_path):
    module = _module()
    source = tmp_path / "motion.dat"
    source.write_bytes(b"a")
    before = module._snapshot(source)
    expected = module.sha256_file(source)
    assert module._verify_immutable_source(source, expected, before, "motion")["content_verified"]
    source.write_bytes(b"b")
    with pytest.raises(module.F7InitialQAError):
        module._verify_immutable_source(source, expected, before, "motion")


def test_request_hash_is_self_excluding_and_decoder_is_pinned():
    module = _module()
    value = {"schema": module.REQUEST_SCHEMA, "decoder": module.DECODER_SHA, "sha256": "old"}
    assert module.canonical_sha(value) == module.canonical_sha({**value, "sha256": "new"})
    assert module.DECODER_SHA == "b8ac8cf4aff68ffd089da6cf3ef19dfd0c6473121475f4c198b720a0ddaa8b2e"
