from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_consumer_evidence_catalog_v31.py"
ROOT_TREE = Path("/home/jade/.codex/worktrees/ds-data-02-stage2/DualSPHysics")
CHECKPOINT_ROOT = ROOT_TREE / "lagrangian-fluid-lab/campaigns/ds-data-02/stage2/checkpoints"
V29 = CHECKPOINT_ROOT / "FINAL_QUALIFICATION_CATALOG_V29_ACTUAL_INDEPENDENT_VERIFICATION_001.json"
V30 = CHECKPOINT_ROOT / "TASK_SCOPE_CATALOG_V30_ACTUAL_INDEPENDENT_VERIFICATION_001.json"


def _load():
    spec = importlib.util.spec_from_file_location("consumer_catalog_v31_test", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V31 = _load()


def test_build_catalog_joins_actual_checkpoints_without_payload_reads(tmp_path: Path) -> None:
    if not CHECKPOINT_ROOT.is_dir() or not V29.is_file() or not V30.is_file():
        pytest.skip("root checkpoint catalogs are not present")
    output = tmp_path / "consumer-evidence-v31.json"
    value = V31.build_catalog(checkpoint_root=CHECKPOINT_ROOT,
                              parent_catalog_v29=V29, parent_catalog_v30=V30,
                              output=output)
    assert value["schema"] == V31.SCHEMA
    assert value["status"] == "DEVELOPMENT_FORWARD_INDEX_ONLY"
    assert len(value["entries"]) == 11
    assert value["summary"]["pending_terminal_cpu_delta_count"] == 3
    assert value["summary"]["pending_terminal_cpu_delta_total_core_seconds"] == pytest.approx(
        0.223476 + 0.233708 + 0.216757)
    assert value["scientific_boundary"]["QI"] == "UNKNOWN"
    assert value["scientific_boundary"]["hidden_test_claim"] is False
    pending = [entry for entry in value["entries"] if entry["cpu"]["status"].startswith("PENDING")]
    assert {entry["request_sha256"] for entry in pending} == {
        "ca5600866a885e75de40e102d5d44438b13e09d8f114f07cdf57ced6662ce7af",
        "4f71b186826f5570cd6e66397a69dd2237b38ed0049461397596de76a19167ba",
        "d774075797cf9d2edc3ac5929389e3f9bf02b9083ea02df258b91f139de67c89",
    }
    assert all(entry["payload_read_by_catalog_builder"] is False for entry in value["entries"])


def test_catalog_refuses_non_unknown_qualification(tmp_path: Path) -> None:
    if not CHECKPOINT_ROOT.is_dir() or not V29.is_file() or not V30.is_file():
        pytest.skip("root checkpoint catalogs are not present")
    source = CHECKPOINT_ROOT / "F2_MIDDLE_CELL_SELECTOR_ACTUAL_GENCASE_MASS_ROOT_VERIFICATION_083.json"
    original = json.loads(source.read_text(encoding="utf-8"))
    # Use an isolated checkpoint root so the real root evidence remains
    # immutable; the builder must reject a non-UNKNOWN qualification claim.
    import shutil
    import tempfile
    with tempfile.TemporaryDirectory(prefix="ds02-catalog-v31-") as directory:
        isolated = Path(directory) / "checkpoints"
        isolated.mkdir()
        for name in V31.ENTRY_FILES:
            path = CHECKPOINT_ROOT / name
            if path.is_file():
                shutil.copyfile(path, isolated / name)
        altered = isolated / source.name
        modified = dict(original)
        modified["scientific_qualification"] = {"QI": "QUALIFIED", "QN": "UNKNOWN", "QE": "UNKNOWN"}
        altered.write_text(json.dumps(modified), encoding="utf-8")
        with pytest.raises(V31.CatalogError, match="non-UNKNOWN qualification"):
            V31.build_catalog(checkpoint_root=isolated, parent_catalog_v29=V29,
                              parent_catalog_v30=V30,
                              output=Path(directory) / "out.json")
