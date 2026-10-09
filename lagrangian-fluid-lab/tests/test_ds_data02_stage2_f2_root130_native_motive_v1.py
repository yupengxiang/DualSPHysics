from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_domain_native_motive_v1.py"
REQUEST_DIR = ROOT / "campaigns/ds-data-02/stage2/requests/f2-s1-root130-native-motive-v1-root-prepared-142-001"
MANIFEST = REQUEST_DIR / "f2-s1-root130-native-motive-v1-manifest.json"
REQUEST = REQUEST_DIR / "f2-s1-root130-native-motive-v1-request.json"


def loaded():
    spec = importlib.util.spec_from_file_location("f2_root130_native_motive_v1", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_request_binds_root130_paths_and_preserves_root138_identity_scope():
    module = loaded()
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    script_path = Path(request["command"][1])
    manifest_path = Path(request["command"][3])
    assert script_path.is_file()
    assert manifest_path.is_file()
    assert request["input_sha256"][str(script_path)] == hashlib.sha256(script_path.read_bytes()).hexdigest()
    assert request["input_sha256"][str(manifest_path)] == hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    assert manifest["case_id"] == module.ROOT130_CASE_ID
    assert manifest["identity_scope"]["root138_aggregate"] == {
        "old_count": 153,
        "new_count": 67,
        "common_ids": 27,
        "old_only_ids": 126,
        "new_only_ids": 40,
        "new_set_is_subset_of_old": False,
    }
    assert manifest["contract"]["no_synthetic_ids_from_aggregate"] is True
    assert request["guard_policy"]["aggregate_never_expands_to_ids"] is True


def _deferred_stat_without_content(ref: dict[str, object], label: str):
    p = Path(str(ref["path"]))
    assert p.is_file(), label
    st = p.stat()
    return p, {
        "path": str(p.resolve()),
        "bytes": st.st_size,
        "mtime_ns": st.st_mtime_ns,
        "ctime_ns": st.st_ctime_ns,
        "st_dev": st.st_dev,
        "st_ino": st.st_ino,
        "sha256": "PARENT_GUARD_COMPUTED",
    }


def test_static_validation_does_not_require_native_payload_hash_before_guard(monkeypatch):
    module = loaded()
    monkeypatch.setattr(module, "_deferred_ref", _deferred_stat_without_content)
    manifest, paths, context = module._validate_manifest(MANIFEST)
    assert manifest["status"].startswith("PREPARED_PARENT_GUARDED")
    assert paths["raw_partout"].name == "PartOut_000.obi4"
    assert context["domain_proof"]["RunPARTs_summary"]["saved_window_new_exclusion_sums"]["NpOut"] == 67.0
    assert context["root138"]["native_control_identity_comparison"]["new_set_is_subset_of_old"] is False


def test_wrong_root130_case_is_rejected_before_deferred_payload_access(tmp_path: Path, monkeypatch):
    module = loaded()
    monkeypatch.setattr(module, "_deferred_ref", _deferred_stat_without_content)
    payload = copy.deepcopy(json.loads(MANIFEST.read_text(encoding="utf-8")))
    payload["case_id"] = "F2_WRONG_CASE"
    bad = tmp_path / "bad-manifest.json"
    bad.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(module.NativeQaError, match="ROOT130 case/family binding"):
        module._validate_manifest(bad)


def test_saved_brackets_are_record_windows_and_rows_are_csv_authoritative():
    module = loaded()
    csv_path = Path("/tmp") / "ds02-root142-test.csv"
    csv_path.write_text(
        "PartOut,Idp,Motive,Pos.x [m],Pos.y [m],Pos.z [m],Rhop [kg/m^3]\n"
        "2,512883,1,0,0,0,1000\n"
        "2,522133,1,0,0,0,1000\n",
        encoding="utf-8",
    )
    try:
        rows = module.parse_native_csv(csv_path, [
            {"begin": 512883, "count": 9250, "mkfluid": 0, "mk": 1},
            {"begin": 522133, "count": 9250, "mkfluid": 1, "mk": 2},
        ])
    finally:
        csv_path.unlink(missing_ok=True)
    runparts = {"rows": [
        {"part": 1, "time_s": 0.01},
        {"part": 2, "time_s": 0.02},
    ], "last_time_s": 0.02, "totals": {"NpOut": 2, "NpOutPos": 2, "NpOutRho": 0, "NpOutMov": 0}}
    module.attach_saved_brackets(rows, runparts)
    assert [row["idp"] for row in rows] == [512883, 522133]
    assert all(row["motive"] == "position" for row in rows)
    assert rows[0]["saved_record_bracket_s"] == [0.01, 0.02]
    assert rows[0]["saved_record_time_s"] == 0.02
    assert rows[0]["saved_record_bracket_s"] != "exact_physical_event_time"
