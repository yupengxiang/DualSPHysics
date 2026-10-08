from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_current_catalog_binding_v1.py"
CURRENT = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json")
FROZEN = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"
PROOF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TYPED_ONLY_FRESH_V16_PROOF_V10_ROOT_060/f2-s1-typed-only-fresh-v16-proof-v10-root-060-001-root-forward-030-001/fresh-v16-proof-v10.json")
SIDECAR = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"


def _load():
    spec = importlib.util.spec_from_file_location("current_catalog_binding_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


binding = _load()


def test_actual_current_v15_join_records_stale_result_binding():
    value = binding.validate_binding(SIDECAR, current_catalog=CURRENT,
                                     frozen_request=FROZEN, proof=PROOF)
    assert value["status"] == "PASS_FROZEN_V15_CURRENT_JOIN_RESULT_BINDING_STALE"
    assert value["current_catalog_sha256"] == binding.ACTUAL_CURRENT_SHA256
    assert value["historical_result_current_catalog_sha256"] == binding.HISTORICAL_RESULT_CURRENT_SHA256
    join = value["case_join"]
    assert join["status"] == "EXACT_CASE_INDEX_PHYSICAL_AND_RUNTIME_ALIAS_JOIN"
    assert join["expected_from_frozen_v15"] == join["actual_current336_row"]


def test_embedded_source_catalog_is_not_current_file_sha():
    value = json.loads(SIDECAR.read_text(encoding="utf-8"))
    current = value["current_catalog"]
    assert current["sha256"] == binding.ACTUAL_CURRENT_SHA256
    assert current["embedded_source_catalog_sha256"] != current["sha256"]
    assert current["embedded_source_catalog_is_not_current_file_sha"] is True


def test_same_size_or_mutated_catalog_cannot_pass(tmp_path: Path):
    mutated = tmp_path / "CURRENT336.json"
    data = CURRENT.read_bytes()
    mutated.write_bytes(data[:-1] + (b" " if data[-1:] != b" " else b"\n"))
    with pytest.raises(binding.CurrentBindingError, match="CURRENT336 SHA differs"):
        binding.build_binding(current_catalog=mutated, frozen_request=FROZEN,
                              proof=PROOF, output=tmp_path / "binding.json")


def test_case_alias_join_rejects_wrong_frozen_identity(tmp_path: Path):
    value = json.loads(FROZEN.read_text(encoding="utf-8"))
    value["case_identity"]["runtime_case_alias"] += "_WRONG"
    frozen = tmp_path / "frozen.json"
    frozen.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(binding.CurrentBindingError, match="CURRENT row identity differs for runtime_case_alias"):
        binding.build_binding(current_catalog=CURRENT, frozen_request=frozen,
                              proof=PROOF, output=tmp_path / "binding.json")
