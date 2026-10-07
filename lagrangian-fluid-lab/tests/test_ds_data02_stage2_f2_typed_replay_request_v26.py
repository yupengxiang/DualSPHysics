from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/ds_data02_stage2_f2_typed_replay_request_v26.py"
REQUEST = ROOT / (
    "campaigns/ds-data-02/stage2/replay/v26/"
    "f2-s1-portable-typed-only-full401-replay-request-v26-001.json"
)


def _module():
    spec = importlib.util.spec_from_file_location("typed_replay_v26", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _request() -> dict:
    return json.loads(REQUEST.read_text(encoding="utf-8"))


def _canonical(value: dict) -> str:
    payload = {key: item for key, item in value.items() if key != "sha256"}
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()


def test_v26_request_is_typed_only_full401_and_canonical() -> None:
    request = _request()
    assert request["schema"] == "ds02.request.v1"
    assert request["orchestration_schema"].endswith("typed-only-full401-replay.v26")
    assert request["status"] == "READY_FOR_PARENT_IO_SLOT"
    assert request["sha256"] == _canonical(request)
    assert request["typed_replay_scope"]["frames"] == 401
    assert request["typed_replay_scope"]["logical_fluid_cohort"] == 21114
    assert request["typed_replay_scope"]["raw_to_typed_reconstruction_invoked"] is False
    assert request["typed_replay_scope"]["raw_to_label_complete"] is False
    assert request["qualification"] == {"QI": "UNKNOWN", "QN": "UNKNOWN", "QE": "UNKNOWN"}


def test_v26_validate_checks_stat_and_does_not_hash_h5(monkeypatch) -> None:
    module = _module()
    request = _request()
    original = module.sha256_file

    def fail_if_h5(path):
        if Path(path).suffix.lower() in {".h5", ".hdf5"}:
            raise AssertionError("request validation must not read HDF5 content")
        return original(path)

    monkeypatch.setattr(module, "sha256_file", fail_if_h5)
    result = module.validate_request(request)
    assert result["status"] == "VALIDATED_NO_HDF5_CONTENT_READ"
    assert result["hdf5_content_read_by_validator"] is False
    assert result["hdf5_stat_checked"] is True


def test_v26_has_all_overlay_roles_and_os_trace() -> None:
    request = _request()
    assert request["execution_closure"]["all_actionable_overlay_roles"] == 33
    assert request["trajectory_h5"]["content_hash_source"].startswith("INHERITED_IMMUTABLE_V22")
    assert request["trajectory_h5"]["parent_must_rehash_before_native_C_open"] is True
    command = " ".join(request["command"])
    assert "/usr/bin/strace" in command
    assert "openat" in command
    assert "--io-slot-approved" in command
    assert request["relocation"]["original_path_fallback"] == "FORBIDDEN"
    profile_path = Path(request["source_identity"]["v26_profile"]["path"])
    overlay_path = Path(request["source_identity"]["v26_overlay"]["path"])
    probe_path = Path(request["source_identity"]["v26_metadata_probe"]["path"])
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    overlay = json.loads(overlay_path.read_text(encoding="utf-8"))
    probe = json.loads(probe_path.read_text(encoding="utf-8"))
    assert profile["schema"].endswith("source-profile.v25")
    assert profile["status"].startswith("READY_FOR_TYPED_ONLY_FULL401")
    assert overlay["schema"].endswith("overlay-verification.v26")
    assert overlay["consumer_input"]["original_path_fallback"] == "FORBIDDEN"
    assert probe["status"] == "VALIDATED_PENDING_IO_SLOT"
    assert probe["trajectory_read"] is False
    assert probe["hdf5_content_sha256"] is None


def test_v26_rejects_h5_identity_mutation_and_missing_io_trace() -> None:
    module = _module()
    request = _request()
    mutated = copy.deepcopy(request)
    mutated["trajectory_h5"]["content_sha256"] = "0" * 64
    mutated["sha256"] = _canonical(mutated)
    try:
        module.validate_request(mutated)
    except module.TypedReplayV26Error as error:
        assert "H5 input binding SHA differs" in str(error)
    else:
        raise AssertionError("wrong H5 identity must be rejected")

    no_trace = copy.deepcopy(request)
    no_trace["command"] = [item for item in no_trace["command"] if item != "/usr/bin/strace"]
    no_trace["sha256"] = _canonical(no_trace)
    try:
        module.validate_request(no_trace)
    except module.TypedReplayV26Error as error:
        assert "OS openat trace" in str(error)
    else:
        raise AssertionError("missing OS trace must be rejected")
