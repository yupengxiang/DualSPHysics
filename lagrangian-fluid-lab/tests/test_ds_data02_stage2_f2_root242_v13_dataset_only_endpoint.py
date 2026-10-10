from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_root242_v13_dataset_only_endpoint.py"
V27 = ROOT / "scripts/ds_data02_stage2_effective_conditions_v27.py"
V26 = ROOT / "scripts/ds_data02_stage2_effective_conditions_v26.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V13 = _load(SCRIPT, "root242_v13_endpoint_test")
V27MOD = _load(V27, "effective_v27_for_v13_test")


def _current() -> Path:
    return ROOT / "campaigns/ds-data-02/stage2/CURRENT336.json"


def _primary(name: str) -> Path:
    primary = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
    return primary / name


def _v26() -> Path:
    return _primary("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json")


def _access() -> Path:
    return ROOT / "campaigns/ds-data-02/stage2/lineage/v23-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V23.json"


def _anchor() -> Path:
    return ROOT / "campaigns/ds-data-02/stage2/lineage/v14/raw-anchor-plans/family-raw-anchor-plan-index-v1.json"


def test_v13_builds_from_v23_and_explicit_v27_without_payload(tmp_path: Path) -> None:
    catalog = _primary("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v34-namespace330-v6-root307-actual335-primary-001/namespace330-scoped-v6-root307-catalog.json")
    request = _primary("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/root242-v11-primary-source-prepared-001/root242-v11-parent-request.json")
    contract = _primary("lagrangian-fluid-lab/campaigns/ds-data-02/stage2/requests/root242-v11-primary-source-prepared-001/root242-v11-metadata-contract.json")
    assert catalog.is_file() and request.is_file() and contract.is_file()
    v27 = V27MOD.build_from_index(v26_index=_v26(), output_dir=tmp_path / "v27")
    result = V13.build_dataset_endpoint_v13(
        current_path=_current(), catalog_path=catalog, v27_index_path=v27["index"],
        anchor_index_path=_anchor(), source_access_path=_access(),
        portable_request_path=request, portable_contract_path=contract,
        repo_root=_primary(""), output_dir=tmp_path / "endpoint")
    assert result["schema"] == V13.SCHEMA
    assert result["source_access_schema"] == V13.ACCESS_SCHEMA
    assert result["payload_read"] is False
    checked = V13.validate_endpoint_v13(result["path"])
    assert checked["source_access_schema"] == V13.ACCESS_SCHEMA
    assert checked["blocked_anchor_count"] == 1
    assert checked["canonical_anchor_count"] == 6


def test_v13_rejects_v22_access_and_changed_v27(tmp_path: Path) -> None:
    # The V13 endpoint must force the current V23 source/access contract and
    # must not silently accept the older V22 manifest.
    v22 = ROOT / "campaigns/ds-data-02/stage2/lineage/v22-source-proof/SEVEN_FAMILY_SOURCE_ACCESS_INDEX_V22.json"
    with pytest.raises(V13.DatasetEndpointV13Error, match="V23 source/access schema"):
        V13._validate_v23_access(v22, "df7ea3229efed933aab1e1219823b151218427cb22c024a70b12f9513304c62b", ROOT)

    bad = {"schema": "ds02.stage2.all336-effective-condition-source-index.v27",
           "sha256": "0" * 64, "cases": [], "physical_union_groups": []}
    path = tmp_path / "bad-v27.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(Exception):
        V13._V12._validate_v27(path)
