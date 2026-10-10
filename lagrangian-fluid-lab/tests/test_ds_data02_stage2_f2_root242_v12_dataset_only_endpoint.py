from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V6 = _load(SCRIPTS / "ds_data02_stage2_namespace330_scoped_v6.py", "v6_for_endpoint_test")
V27 = _load(SCRIPTS / "ds_data02_stage2_effective_conditions_v27.py", "v27_for_endpoint_test")
ENDPOINT = _load(SCRIPTS / "ds_data02_stage2_f2_root242_v12_dataset_only_endpoint.py", "v12_endpoint_test")

PRIMARY = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
BASE = PRIMARY / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2"
CURRENT = BASE / "CURRENT336.json"
PLAN = BASE / "checkpoints/CURRENT336_TYPED_LIFECYCLE_AFTER_ROOT307_V4.json"
REGISTRY = BASE / "requests/typed-lifecycle-evidence-registry-v4-after-root307-001.json"
ANCHORS = BASE / "lineage/v14/raw-anchor-plans/family-raw-anchor-plan-index-v1.json"
ACCESS = BASE / "lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json"
V11_REQUEST = BASE / "requests/root242-v11-primary-source-prepared-001/root242-v11-parent-request.json"
V11_CONTRACT = BASE / "requests/root242-v11-primary-source-prepared-001/root242-v11-metadata-contract.json"
V26 = BASE / "lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"


def _inputs(tmp_path: Path) -> tuple[Path, Path]:
    v6_dir = tmp_path / "v6"
    V6.build_namespace330_scoped_v6(
        current_path=CURRENT, plan_path=PLAN, registry_path=REGISTRY,
        output_dir=v6_dir,
    )
    v27 = V27.build_from_index(v26_index=V26, output_dir=tmp_path / "v27")
    return v6_dir / "namespace330-scoped-v6-root307-catalog.json", Path(v27["index"])


def test_v12_binds_all_seven_anchors_but_blocks_historical_alias(tmp_path: Path) -> None:
    catalog, v27 = _inputs(tmp_path)
    result = ENDPOINT.build_dataset_endpoint(
        current_path=CURRENT, catalog_path=catalog, v27_index_path=v27,
        anchor_index_path=ANCHORS, source_access_path=ACCESS,
        portable_request_path=V11_REQUEST, portable_contract_path=V11_CONTRACT,
        repo_root=PRIMARY, output_dir=tmp_path / "endpoint",
    )
    assert result["status"] == "BLOCKED_HISTORICAL_ALIAS_ANCHOR"
    checked = ENDPOINT.validate_endpoint(result["path"])
    assert checked["anchor_count"] == 7
    assert checked["canonical_anchor_count"] == 6
    assert checked["blocked_anchor_count"] == 1
    assert checked["payload_read"] is False
    assert checked["ledger_mutated"] is False
    document = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
    assert document["physical_union_binding"]["upper_split_boundary"] == "physical_union_group_id_v27"
    assert document["physical_union_binding"]["forbidden_cross_split_dimensions"] == [
        "resolution", "window", "recovery"
    ]
    f2 = next(item for item in document["anchor_binding"]["selected"] if item["family_id"] == "F2")
    assert f2["identity_status"] == "HISTORICAL_ALIAS_UNRESOLVED"
    assert f2["canonical_case_id"] is None


def test_v12_rejects_union_row_that_drops_resolution_window_recovery_boundary(tmp_path: Path) -> None:
    catalog, v27 = _inputs(tmp_path)
    value = json.loads(v27.read_text(encoding="utf-8"))
    value["cases"][0]["forbidden_cross_split_dimensions"] = ["resolution"]
    value["sha256"] = ENDPOINT.canonical_sha(value)
    bad = tmp_path / "bad-v27.json"
    bad.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")
    with pytest.raises(ENDPOINT.DatasetEndpointError, match="forbidden split axis"):
        ENDPOINT.build_dataset_endpoint(
            current_path=CURRENT, catalog_path=catalog, v27_index_path=bad,
            anchor_index_path=ANCHORS, source_access_path=ACCESS,
            portable_request_path=V11_REQUEST, portable_contract_path=V11_CONTRACT,
            repo_root=PRIMARY, output_dir=tmp_path / "bad-endpoint",
        )
