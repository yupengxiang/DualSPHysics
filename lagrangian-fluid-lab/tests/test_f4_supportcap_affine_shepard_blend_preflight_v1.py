from __future__ import annotations

import builtins
from copy import deepcopy

import pytest

from scripts import f4_supportcap_affine_shepard_blend_preflight_v1 as preflight


def _environment(*, load: float = 10.0) -> dict:
    return {
        "resources": {
            "process_visible_cpu_count": 128,
            "load_average_1_5_15_min": [load, load, load],
            "available_ram_bytes": 32 * 1024**3,
            "filesystem_free_bytes": 32 * 1024**3,
            "active_material_worker_pids": [],
        },
        "controls": {"preflight_only": True, "native_particle_frames_loaded": False},
    }


def _authorization() -> dict:
    value, _ = preflight.read_authorization()
    return value


def _patch_run(monkeypatch, tmp_path, *, environments, source_probe=None, value=None):
    scope = tmp_path / "scope"
    scope.mkdir()
    state = tmp_path / "private-state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(preflight, "STATE_DIR", state)
    monkeypatch.setattr(preflight, "SCOPE_DIR", scope)
    monkeypatch.setattr(preflight, "OUTPUT_NAMESPACE", tmp_path / "canary")
    authorization = _authorization() if value is None else value
    binding = {"path": "fixed-test-authorization", "bytes": 1, "sha256": "a" * 64}
    monkeypatch.setattr(preflight, "read_authorization", lambda: (authorization, binding))
    values = iter(environments)
    monkeypatch.setattr(preflight, "environment_preflight", lambda: next(values))
    if source_probe is not None:
        monkeypatch.setattr(preflight, "input_preflight", source_probe)
    return scope


def test_candidate_card_is_hash_bound_and_preflight_only() -> None:
    card = preflight._decode_frozen_candidate_card(preflight._read_bounded(preflight.CARD_PATH))
    assert card["candidate_id"] == preflight.CANDIDATE_ID
    assert card["status"] == "proposal_only_cpu_native_preflight_authorized_runtime_not_authorized"
    assert card["synthetic_screen"]["screen_conditions_pass"] is True
    assert card["synthetic_screen"]["qualification_credit"] == 0
    assert card["preflight_scope"]["actual_canary_authorized"] is False
    assert len(card["input_bindings"]) == 22


def test_authorization_static_closure_is_exact_and_valid() -> None:
    value = _authorization()
    preflight.validate_authorization(value)
    preflight.validate_static_bindings(value)
    assert value["max_preflight_attempts"] == 1
    assert value["runtime_execution_authorized"] is False
    assert value["execution_controls"]["canary_started"] is False


def test_static_validation_does_not_import_candidate_modules(monkeypatch) -> None:
    value = _authorization()
    original_import = builtins.__import__

    def reject_candidate_import(name, *args, **kwargs):
        if name.startswith("scripts.f4_") or name in {"scripts.passive_tracers", "scripts.core_material"}:
            pytest.fail(f"preflight validation imported project module {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", reject_candidate_import)
    preflight.validate_static_bindings(value)


def test_run_api_does_not_accept_path_or_probe_overrides(tmp_path) -> None:
    with pytest.raises(TypeError):
        preflight.run_preflight({"schema": "forged"})
    with pytest.raises(TypeError):
        preflight.run_preflight(scope_dir=tmp_path / "scope")
    with pytest.raises(TypeError):
        preflight.run_preflight(environment_probe=lambda: _environment())
    with pytest.raises(TypeError):
        preflight.run_preflight(source_probe=lambda: {"passed": True})


def test_changed_static_digest_fails_before_any_one_shot_write(monkeypatch, tmp_path) -> None:
    value = deepcopy(_authorization())
    value["static_bindings"][0]["sha256"] = "0" * 64
    scope = tmp_path / "scope"
    monkeypatch.setattr(preflight, "read_authorization", lambda: (value, {"path": "test", "bytes": 1, "sha256": "a" * 64}))
    with pytest.raises(ValueError, match="static binding digest/size mismatch"):
        preflight.run_preflight()
    assert not scope.exists()


def test_resource_deferral_does_not_consume_the_one_shot(monkeypatch, tmp_path) -> None:
    scope = _patch_run(
        monkeypatch,
        tmp_path,
        environments=(_environment(load=129.0),),
        source_probe=lambda: pytest.fail("source opened after resource deferral"),
    )
    result = preflight.run_preflight()
    assert result["status"] == "deferred_before_one_shot_consumed"
    assert result["preflight_started"] is False
    assert result["authorization_consumed"] is False
    assert result["resource_blockers"] == ["one-minute load exceeds process-visible CPU capacity"]
    assert list(scope.iterdir()) == []
    assert list((tmp_path / "private-state").iterdir()) == []


def test_passing_preflight_checks_input_but_never_runs_candidate(monkeypatch, tmp_path) -> None:
    scope = _patch_run(
        monkeypatch,
        tmp_path,
        environments=(_environment(), _environment()),
        source_probe=lambda: {"source_hdf5_opened_after_hash_match": True, "native_particle_frames_loaded": False},
    )
    result = preflight.run_preflight()
    assert result["status"] == "preflight_passed_runtime_not_authorized"
    assert result["input_preflight"]["native_particle_frames_loaded"] is False
    assert result["execution_controls"]["candidate_executed"] is False
    assert result["execution_controls"]["canary_started"] is False
    assert result["preflight_started"] is True
    assert result["authorization_consumed"] is True
    assert (scope / preflight.LOCK_NAME).is_file()
    assert (scope / preflight.RECEIPT_NAME).is_file()
    assert (tmp_path / "private-state" / preflight.ONE_SHOT_MARKER_NAME).is_file()


def test_resource_failure_after_durable_start_consumes_one_shot(monkeypatch, tmp_path) -> None:
    scope = _patch_run(
        monkeypatch,
        tmp_path,
        environments=(_environment(), _environment(load=129.0)),
        source_probe=lambda: pytest.fail("input opened after second resource gate failed"),
    )
    result = preflight.run_preflight()
    assert result["status"] == "preflight_deferred_resource_gate_runtime_not_authorized"
    assert result["resource_blockers"]
    assert result["preflight_started"] is True
    assert result["authorization_consumed"] is True
    assert (scope / preflight.LOCK_NAME).is_file()
    assert (scope / preflight.RECEIPT_NAME).is_file()
    assert (tmp_path / "private-state" / preflight.ONE_SHOT_MARKER_NAME).is_file()


def test_existing_future_canary_namespace_fails_before_consumption(monkeypatch, tmp_path) -> None:
    scope = _patch_run(monkeypatch, tmp_path, environments=(_environment(),))
    namespace = tmp_path / "canary"
    namespace.mkdir()
    with pytest.raises(FileExistsError, match="fresh v5 canary namespace"):
        preflight.run_preflight()
    assert list(scope.iterdir()) == []


def test_symlinked_scope_fails_before_consumption(monkeypatch, tmp_path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    linked_scope = tmp_path / "scope-link"
    linked_scope.symlink_to(target, target_is_directory=True)
    state = tmp_path / "private-state"
    state.mkdir(mode=0o700)
    monkeypatch.setattr(preflight, "STATE_DIR", state)
    monkeypatch.setattr(preflight, "SCOPE_DIR", linked_scope)
    monkeypatch.setattr(preflight, "OUTPUT_NAMESPACE", tmp_path / "canary")
    authorization = _authorization()
    monkeypatch.setattr(preflight, "read_authorization", lambda: (authorization, {"path": "test", "bytes": 1, "sha256": "a" * 64}))
    with pytest.raises(OSError):
        preflight.run_preflight()
    assert list(target.iterdir()) == []
    assert list(state.iterdir()) == []


def test_nonprivate_one_shot_state_directory_fails_closed(monkeypatch, tmp_path) -> None:
    scope = tmp_path / "scope"
    scope.mkdir()
    shared_state = tmp_path / "shared-state"
    shared_state.mkdir(mode=0o755)
    monkeypatch.setattr(preflight, "STATE_DIR", shared_state)
    monkeypatch.setattr(preflight, "SCOPE_DIR", scope)
    monkeypatch.setattr(preflight, "OUTPUT_NAMESPACE", tmp_path / "canary")
    authorization = _authorization()
    monkeypatch.setattr(preflight, "read_authorization", lambda: (authorization, {"path": "test", "bytes": 1, "sha256": "a" * 64}))
    with pytest.raises(PermissionError, match="must be private"):
        preflight.run_preflight()
    assert list(scope.iterdir()) == []


def test_symlinked_output_namespace_fails_before_consumption(monkeypatch, tmp_path) -> None:
    scope = _patch_run(monkeypatch, tmp_path, environments=(_environment(),))
    target = tmp_path / "target"
    target.mkdir()
    namespace = tmp_path / "canary"
    namespace.symlink_to(target, target_is_directory=True)
    with pytest.raises(FileExistsError, match="fresh v5 canary namespace"):
        preflight.run_preflight()
    assert list(scope.iterdir()) == []
    assert list((tmp_path / "private-state").iterdir()) == []


def test_scope_replacement_cannot_bypass_external_one_shot_marker(monkeypatch, tmp_path) -> None:
    scope = _patch_run(monkeypatch, tmp_path, environments=())
    values = iter((_environment(), _environment()))
    calls = 0

    def environment_with_scope_replacement():
        nonlocal calls
        calls += 1
        if calls == 2:
            scope.rename(tmp_path / "moved-scope")
            scope.mkdir()
        return next(values)

    monkeypatch.setattr(preflight, "environment_preflight", environment_with_scope_replacement)
    monkeypatch.setattr(
        preflight,
        "input_preflight",
        lambda: pytest.fail("input was opened after the pinned scope path changed"),
    )
    result = preflight.run_preflight()
    marker = tmp_path / "private-state" / preflight.ONE_SHOT_MARKER_NAME
    assert result["status"] == "preflight_failed_runtime_not_authorized"
    assert "one-shot scope path no longer names the pinned directory" in result["failure"]
    assert marker.is_file()
    assert list(scope.iterdir()) == []
    with pytest.raises(FileExistsError, match="already consumed"):
        preflight.run_preflight()
    assert list(scope.iterdir()) == []


def test_one_shot_state_replacement_is_detected_before_source_access(monkeypatch, tmp_path) -> None:
    scope = _patch_run(monkeypatch, tmp_path, environments=())
    state = tmp_path / "private-state"
    values = iter((_environment(), _environment()))
    calls = 0

    def environment_with_state_replacement():
        nonlocal calls
        calls += 1
        if calls == 2:
            state.rename(tmp_path / "moved-private-state")
            state.mkdir(mode=0o700)
        return next(values)

    monkeypatch.setattr(preflight, "environment_preflight", environment_with_state_replacement)
    monkeypatch.setattr(
        preflight,
        "input_preflight",
        lambda: pytest.fail("input was opened after the one-shot state path changed"),
    )
    result = preflight.run_preflight()
    moved_state = tmp_path / "moved-private-state"
    assert result["status"] == "preflight_failed_runtime_not_authorized"
    assert "one-shot state path no longer names the pinned directory" in result["failure"]
    assert (moved_state / preflight.ONE_SHOT_MARKER_NAME).is_file()
    assert (scope / preflight.LOCK_NAME).is_file()
    assert (scope / preflight.RECEIPT_NAME).is_file()
