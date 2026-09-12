from pathlib import Path
import subprocess
import pytest
from scripts import l1r_branch_runner as runner
from scripts import l1r_input_preflight as preflight
from scripts import l1r_q2_mdbc_bridge as bridge
from scripts import l1r_branch_cases as cases
from scripts.l1r_continuation_evidence import active_window_hours
from datetime import datetime, timezone


def test_execution_failure_stops_remaining_launches(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "write", lambda *args: None)
    monkeypatch.setattr(
        runner, "run", lambda r: calls.append(r["id"]) or {"status": "failed"}
    )
    assert runner.run_registry([{"id": "first"}, {"id": "second"}]) == [
        {"status": "failed"}
    ]
    assert calls == ["first"]


def test_closed_resource_window_does_not_charge_idle_wait_for_owner():
    windows = [
        {
            "started_at": "2026-09-09T16:00:00+00:00",
            "finished_at": "2026-09-09T17:00:00+00:00",
        }
    ]
    assert (
        active_window_hours(windows, datetime(2026, 9, 10, tzinfo=timezone.utc)) == 1.0
    )


def test_gpu_guard_binds_launch_uuid_even_when_replacement_is_allowlisted(monkeypatch):
    monkeypatch.setattr(
        bridge, "allowed_gpu_uuids", lambda: {"original", "replacement"}
    )
    monkeypatch.setattr(
        bridge,
        "gpu_snapshot",
        lambda: [{"index": 4, "uuid": "replacement", "memory_free_mib": 8000}],
    )
    assert bridge.gpu_guard(4, "original")["ok"] is False


def test_physical_failure_does_not_lock_unexecuted_backgrounds(monkeypatch):
    calls = []
    monkeypatch.setattr(runner, "write", lambda *args: None)
    monkeypatch.setattr(
        runner,
        "run",
        lambda r: calls.append(r["id"]) or {"audit_status": "quality_failed"},
    )
    runner.run_registry([{"id": "first"}, {"id": "second"}])
    assert calls == ["first", "second"]


def test_empty_asset_is_rejected_before_any_native_process(monkeypatch, tmp_path):
    monkeypatch.setattr(preflight, "LAB", tmp_path)
    (tmp_path / "CaseSloshingAccData.csv").touch()
    monkeypatch.setattr(
        preflight.subprocess,
        "run",
        lambda *a, **k: pytest.fail("must reject before process launch"),
    )
    with pytest.raises(ValueError, match="empty"):
        preflight.check_input({"generated_prefix": "case", "time_max_s": 1.5})


def test_cli_cannot_silently_override_xml_boundary_mode(monkeypatch,tmp_path):
    monkeypatch.setattr(preflight,'LAB',tmp_path)
    (tmp_path/'case.xml').write_text('<case><parameters><parameter key="Boundary" value="2"/><parameter key="SlipMode" value="2"/></parameters></case>')
    record={'generated_prefix':'case','solver_mode':'-mdbc'}
    with pytest.raises(ValueError,match='override'):
        preflight.check_boundary_mode(record)
    record['solver_mode']='-mdbc_noslip'
    preflight.check_boundary_mode(record)


def test_no_penetration_requires_consistent_xml_cli_and_live_log(monkeypatch,tmp_path):
    monkeypatch.setattr(preflight,'LAB',tmp_path)
    (tmp_path/'case.xml').write_text('<case><parameters><parameter key="Boundary" value="2"/><parameter key="SlipMode" value="2"/><parameter key="NoPenetration" value="1"/></parameters></case>')
    record={'generated_prefix':'case','solver_mode':'-mdbc_noslip','expected_no_penetration':True,'expected_slip_mode':'No-slip'}
    with pytest.raises(ValueError,match='no-penetration mode would override'):
        preflight.check_boundary_mode(record)
    record['solver_mode']='-mdbc_noslip:1'
    preflight.check_boundary_mode(record)
    assert runner.boundary_log_mismatch(record,'SlipMode="No-slip"\n  No Penetration=True') is None
    assert runner.boundary_log_mismatch(record,'SlipMode="No-slip"\n  No Penetration=False')['field']=='expected_no_penetration'
    assert runner.boundary_log_mismatch(record,'SlipMode="DBC vel=0"')['field']=='expected_slip_mode'


def test_completed_source_requires_native_boundary_fields_before_audit(tmp_path):
    record={'expected_no_penetration':True,'expected_slip_mode':'No-slip'}
    result={'attempt_directory':str(tmp_path)}
    log=tmp_path/'Run.out'
    log.write_text('Finished execution (code=0)')
    with pytest.raises(ValueError,match='lacks required boundary field'):
        runner.check_completed_boundary(record,result)
    log.write_text('SlipMode="No-slip"\nNo Penetration=False\nFinished execution (code=0)')
    with pytest.raises(ValueError,match='boundary mismatch'):
        runner.check_completed_boundary(record,result)
    log.write_text('SlipMode="No-slip"\nNo Penetration=True\nFinished execution (code=0)')
    runner.check_completed_boundary(record,result)


def test_missing_latest_does_not_allow_repeating_registered_single_attempt(tmp_path):
    record={'id':'one','max_attempts':1}
    runner.check_case_attempt_limit(record,tmp_path)
    (tmp_path/'one/attempts/interrupted.partial').mkdir(parents=True)
    with pytest.raises(RuntimeError,match='per-case attempt limit'):
        runner.check_case_attempt_limit(record,tmp_path)


def test_preparation_cannot_overwrite_attempted_inputs(monkeypatch, tmp_path):
    monkeypatch.setattr(cases, "LAB", tmp_path)
    attempted = (
        tmp_path
        / "campaigns/l1-resume/runs/branches/F1_OFFICIAL_NS_NOP0_dp02_t15/attempts/old.failed"
    )
    attempted.mkdir(parents=True)
    with pytest.raises(ValueError, match="immutable"):
        cases.prepare("f1")


def test_native_acceleration_reader_rejects_empty_and_nonmonotonic_inputs(tmp_path):
    executable = runner.LAB / "campaigns/l1-resume/artifacts/check_acc_input"
    if not executable.exists():
        pytest.skip(
            "build native/check_acc_input.cpp for native parser integration test"
        )
    good = tmp_path / "good.csv"
    good.write_text("#t;ax;ay;az;rx;ry;rz\n0;0;0;-9.81;0;0;0\n1.5;1;0;-9.81;0;0;0\n")
    empty = tmp_path / "empty.csv"
    empty.touch()
    reversed_time = tmp_path / "reversed.csv"
    reversed_time.write_text("1;0;0;0;0;0;0\n0;0;0;0;0;0;0\n")
    assert (
        subprocess.run([str(executable), str(good)], capture_output=True).returncode
        == 0
    )
    assert (
        subprocess.run([str(executable), str(empty)], capture_output=True).returncode
        != 0
    )
    assert (
        subprocess.run(
            [str(executable), str(reversed_time)], capture_output=True
        ).returncode
        != 0
    )
