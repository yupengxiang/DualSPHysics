from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_effective_conditions_v27_primary_rebind.py"
V27 = ROOT / "scripts/ds_data02_stage2_effective_conditions_v27.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


R = _load(SCRIPT, "v27_primary_rebind_test")
V27MOD = _load(V27, "v27_builder_for_rebind_test")


def _primary_root() -> Path:
    return Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")


def _v26() -> Path:
    return _primary_root() / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/lineage/v26-effective-condition-directory/EFFECTIVE_PHYSICAL_SPLIT_INDEX_V26.json"


def test_rebind_verifies_all_primary_case_files_and_never_reads_payload(tmp_path: Path) -> None:
    v27 = V27MOD.build_from_index(v26_index=_v26(), output_dir=tmp_path / "v27")
    request = Path(v27["request"])
    old_root = Path("/home/jade/.codex/worktrees/ds-data-02-stage2-consumers/DualSPHysics")
    primary = _primary_root()
    out = tmp_path / "rebound"
    result = R.rebind_v27_request(request_path=request, old_root=old_root,
                                  primary_root=primary, output_dir=out)
    assert result["case_detail_count"] == 336
    assert result["payload_read"] is False
    checked = R.validate_rebound_request(result["request"], result["sidecar"])
    assert checked["case_detail_count"] == 336
    rebound = json.loads(Path(result["request"]).read_text())
    assert all(str(item["path"]).startswith(str(primary))
               for item in rebound["source_inputs"]["v26_case_details"])
    assert all("payload arrays" in item["content_role"]
               for item in rebound["source_inputs"]["v26_case_details"])


def test_rebind_rejects_a_target_with_changed_case_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    target = tmp_path / "target"
    source.mkdir()
    target.mkdir()
    case = {"schema": "ds02.stage2.effective-condition-case.v26", "current_index": 0,
            "family_id": "F1", "physical_case_id": "F1_TEST"}
    import hashlib
    def canon(v):
        return json.dumps({k:x for k,x in v.items() if k != "sha256"}, sort_keys=True,
                          separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    case["sha256"] = hashlib.sha256(canon(case).encode()).hexdigest()
    text = json.dumps(case, sort_keys=True) + "\n"
    (source / "case.json").write_text(text)
    (target / "case.json").write_text(text.replace("F1_TEST", "F1_CHANGED"))
    # Use a minimal malformed request; the target content must be rejected
    # before any payload-like path can be considered.
    bad = {"schema": R.REQUEST_SCHEMA, "sha256": "0" * 64,
           "source_inputs": {"v26_index": {}, "v26_case_details": []}}
    request = tmp_path / "request.json"
    request.write_text(json.dumps(bad))
    with pytest.raises(R.RebindError, match="canonical V27|canonical SHA|all 336"):
        R.rebind_v27_request(request_path=request, old_root=source,
                             primary_root=target, output_dir=tmp_path / "out")
