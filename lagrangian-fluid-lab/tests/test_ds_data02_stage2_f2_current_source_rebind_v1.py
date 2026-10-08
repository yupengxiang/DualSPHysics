from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts" / "ds_data02_stage2_f2_current_source_rebind_v1.py"
PY_ROOT = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
DATA = Path("/home/jade/Projects/DualSPHysics-data/ds-data-02")
CURRENT = DATA / "families/infra/STAGE2_CURRENT336_CATALOG/catalog-003/CURRENT336.json"
FROZEN = ROOT / "campaigns/ds-data-02/stage2/replay/v15/f2-s1-replay-request-v15-001.json"
PROOF = DATA / "families/F2/STAGE2_F2_S1_TYPED_ONLY_FRESH_V16_PROOF_V10_ROOT_060/f2-s1-typed-only-fresh-v16-proof-v10-root-060-001-root-forward-030-001/fresh-v16-proof-v10.json"
PRODUCER = PY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v37-full-chain-root-049/f2-s1-typed-labels-only-producer-v1-root-051.json"
REPORT = DATA / "families/F2/STAGE2_F2_S1_TYPED_LABELS_ONLY_V1_ROOT_051/f2-s1-typed-labels-only-v1-root-051-001-root-forward-030-001/labels/typed-label-only-report-v1.json"
CONTRACT = ROOT / "campaigns/ds-data-02/stage2/native-reconstruction/raw-to-label-v38-full-chain/f2-s1-fresh-v16-source-contract-v3-001.json"
PROOF_REQUEST = PY_ROOT / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/native-reconstruction/typed-only-fresh-proof-root-055/f2-s1-fresh-v16-proof-request-v10-root-060.json"


def _load():
    spec = importlib.util.spec_from_file_location("current_source_rebind_v1_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rebind = _load()


def _build(tmp_path: Path) -> tuple[dict, Path]:
    output = tmp_path / "rebind.json"
    value = rebind.build_rebind(
        current_catalog=CURRENT,
        frozen_request=FROZEN,
        historical_proof=PROOF,
        producer_request=PRODUCER,
        producer_report=REPORT,
        source_contract=CONTRACT,
        historical_proof_request=PROOF_REQUEST,
        output=output,
    )
    return value, output


def test_rebind_finds_overlay_writer_and_binds_actual_current(tmp_path: Path):
    value, output = _build(tmp_path)
    assert value["status"] == "PASS_METADATA_ONLY_REBIND_ACTUAL_CURRENT_STALE_ALIAS_RECORDED"
    assert value["actual_current_catalog_sha256"] == rebind.ACTUAL_CURRENT_SHA256
    assert value["historical_overlay_sha256"] == rebind.HISTORICAL_OVERLAY_SHA256
    assert value["result_sha256"] == rebind.EXPECTED_RESULT_SHA256
    assert value["hdf5_bi4_raw_read"] is False
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["overlay_origin"]["json_difference"]["path"] == "/cases/78/trajectory/path"
    assert report["overlay_origin"]["alias_generator"]["function"] == "_prepare_relocated_requests"
    assert report["consumer_binding"]["historical_exact_current_claim"] == "REJECTED_STALE_OVERLAY_SHA"
    assert report["result_header_rebind"]["label_array_equivalence"].startswith("NOT_PROVEN")
    assert report["sha256"] == rebind.canonical_sha(report)


def test_validate_rebind_requires_exact_current_and_preserves_stale_audit(tmp_path: Path):
    _, output = _build(tmp_path)
    value = rebind.validate_rebind(output, current_catalog=CURRENT,
                                   frozen_request=FROZEN, historical_proof=PROOF)
    assert value["actual_current_catalog_sha256"] == rebind.ACTUAL_CURRENT_SHA256
    assert value["historical_overlay_sha256"] == rebind.HISTORICAL_OVERLAY_SHA256
    assert value["json_difference_count"] == 1


def test_same_size_wrong_current_is_rejected(tmp_path: Path):
    mutated = tmp_path / "CURRENT336.json"
    data = CURRENT.read_bytes()
    mutated.write_bytes(data[:-1] + (b" " if data[-1:] != b" " else b"\n"))
    with pytest.raises(rebind.RebindError, match="actual CURRENT336 SHA differs"):
        rebind.build_rebind(
            current_catalog=mutated, frozen_request=FROZEN,
            historical_proof=PROOF, producer_request=PRODUCER,
            producer_report=REPORT, output=tmp_path / "bad.json",
            source_contract=CONTRACT, historical_proof_request=PROOF_REQUEST,
        )


def test_wrong_alias_content_is_rejected(tmp_path: Path):
    alias = Path("/var/tmp/ds02-stage2/ds-data-02/families/F2/STAGE2_F2_S1_PORTABLE_RAW_TO_LABEL_V5/f2-s1-v37-executor-root-049/reference-products-v37/relocated-runtime/CURRENT336-case78-trajectory-overlay.json")
    assert alias.is_file()
    producer = json.loads(PRODUCER.read_text(encoding="utf-8"))
    producer["v15_request"]["current_binding"]["path"] = str(tmp_path / "wrong-alias.json")
    (tmp_path / "wrong-alias.json").write_bytes(CURRENT.read_bytes())
    producer_path = tmp_path / "producer.json"
    producer["sha256"] = rebind.canonical_sha(producer)
    producer_path.write_text(json.dumps(producer, sort_keys=True) + "\n", encoding="utf-8")
    with pytest.raises(rebind.RebindError, match="historical stale SHA"):
        rebind.build_rebind(
            current_catalog=CURRENT, frozen_request=FROZEN,
            historical_proof=PROOF, producer_request=producer_path,
            producer_report=REPORT, output=tmp_path / "bad.json",
            source_contract=CONTRACT, historical_proof_request=PROOF_REQUEST,
        )
