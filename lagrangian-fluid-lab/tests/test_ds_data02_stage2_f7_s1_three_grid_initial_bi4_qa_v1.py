from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f7_s1_three_grid_initial_bi4_qa_v1.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f7-s1-three-grid-initial-bi4-qa-v1-root-prepared-146-001"
MANIFEST = REQUEST_DIR / "f7-s1-three-grid-initial-bi4-qa-v1-manifest.json"
REQUEST = REQUEST_DIR / "f7-s1-three-grid-initial-bi4-qa-v1-root-prepared-146-001.json"
SPEC = importlib.util.spec_from_file_location("f7_s1_three_grid_initial_bi4_qa_v1", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _manifest(tmp_path: Path) -> tuple[dict, Path]:
    value = json.loads(MANIFEST.read_text(encoding="utf-8"))
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    return value, path


def test_static_manifest_closes_three_rungs_without_opening_deferred_bi4() -> None:
    manifest, paths, _, _ = MODULE._validate_static_manifest(MANIFEST)
    assert [r["label"] for r in manifest["rungs"]] == ["coarse", "original", "fine"]
    assert len(paths) == 25
    assert set(manifest["deferred_inputs"]) == {"coarse", "original", "fine"}
    assert all(entry["sha256"] == "PARENT_GUARD_COMPUTED" for entry in manifest["deferred_inputs"].values())
    assert all(Path(entry["path"]).suffix == ".bi4" for entry in manifest["deferred_inputs"].values())


def test_request_keeps_deferred_bi4_out_of_prelaunch_digest_inputs() -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    deferred = {entry["path"] for entry in request["deferred_input_files"]}
    assert len(deferred) == 3
    assert all(path not in request["input_files"] for path in deferred)
    assert request["guard_policy"]["worker_pre_post_for_deferred_bi4_after_all_payload_reads"] is True
    assert request["estimated_bi4_read_bytes"] == sum(entry["bytes"] for entry in request["deferred_input_files"])


def test_wrong_deferred_suffix_is_rejected(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["deferred_inputs"]["coarse"]["path"] = value["source_refs"][0]["path"]
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.ThreeGridQAError, match="deferred coarse is not BI4"):
        MODULE._validate_static_manifest(path)


def test_deferred_digest_must_be_parent_guarded(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["deferred_inputs"]["fine"]["sha256"] = "deadbeef"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.ThreeGridQAError, match="deferred fine SHA policy"):
        MODULE._validate_static_manifest(path)


def test_resolution_swap_cannot_hide_generated_xml_contract(tmp_path: Path) -> None:
    value, path = _manifest(tmp_path)
    value["rungs"][0]["generated_xml_ref"] = "generated_fine"
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(MODULE.ThreeGridQAError, match="coarse generated dp"):
        MODULE._validate_static_manifest(path)


def test_private_array_payloads_are_never_serialized() -> None:
    public = MODULE._strip_arrays({"id_unique": True, "_ids": [1], "_positions": [[0, 0, 0]], "header": {"CaseNp": 1}})
    assert public == {"id_unique": True, "header": {"CaseNp": 1}}
