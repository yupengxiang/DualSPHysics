from __future__ import annotations

import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
EVALUATOR = ROOT / "scripts" / "ds_data02_stage2_f2_typed_only_evaluator_v2_current_bound.py"
CURRENT = ROOT / "campaigns/ds-data-02/stage2/evaluator/v2/f2-s1-current-catalog-binding-v1-001.json"
PRODUCER = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TYPED_LABELS_ONLY_V1_ROOT_051/f2-s1-typed-labels-only-v1-root-051-001-root-forward-030-001/labels/typed-label-only-report-v1.json")
PROOF = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02/families/F2/STAGE2_F2_S1_TYPED_ONLY_FRESH_V16_PROOF_V10_ROOT_060/f2-s1-typed-only-fresh-v16-proof-v10-root-060-001-root-forward-030-001/fresh-v16-proof-v10.json")
PROOF_REQUEST = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/typed-only-fresh-proof-root-055/f2-s1-fresh-v16-proof-request-v10-root-060.json"
SOURCE_CONTRACT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain/f2-s1-fresh-v16-source-contract-v3-001.json"
FROZEN = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluator = _load(EVALUATOR, "typed_evaluator_v2_current_bound_test")


def test_build_request_requires_current_reconciliation_without_payload_read(tmp_path: Path):
    output = tmp_path / "typed-request.json"
    result = evaluator.build_request(
        producer_report=PRODUCER, proof_request=PROOF_REQUEST, proof=PROOF,
        source_contract=SOURCE_CONTRACT, frozen_request=FROZEN,
        current_binding=CURRENT, output=output, max_wall_seconds=300.0,
        max_result_bytes=100_000_000)
    request = json.loads(output.read_text(encoding="utf-8"))
    assert result["payload_read"] is False
    assert result["hdf5_or_bi4_read"] is False
    assert request["current_catalog_binding"]["current_catalog_sha256"] == evaluator.CURRENT.ACTUAL_CURRENT_SHA256
    assert request["v2_current_forward"]["historical_exact_current_claim"] == "REJECTED_STALE_CATALOG_BINDING"
    assert request["qualification"] == evaluator.UNKNOWN
    assert request["sha256"] == evaluator.canonical_sha(request)
    _, request = evaluator._load_request(output)
    _, info = evaluator._validate_current_request(request)
    assert info["case_join"]["status"] == "EXACT_CASE_INDEX_PHYSICAL_AND_RUNTIME_ALIAS_JOIN"
